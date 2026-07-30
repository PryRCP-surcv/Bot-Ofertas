from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from bot_ofertas.api.app import create_app
from bot_ofertas.api.settings import ApiSettings
from bot_ofertas.storage import DatabaseSettings, create_database_engine
from bot_ofertas.stores import build_store_registry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_POSTGRES_TESTS") != "1",
        reason="define RUN_POSTGRES_TESTS=1 para usar PostgreSQL local",
    ),
]

_TOKEN = "phase6-1-integration-admin-token-0001"


def test_phase6_subscriber_payment_and_launch_workflow() -> None:
    engine = create_database_engine(DatabaseSettings.from_env())
    connection = engine.connect()
    outer_transaction = connection.begin()
    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    application = create_app(
        ApiSettings(
            admin_token=_TOKEN,
            cors_origins=("http://localhost:3000",),
        ),
        session_factory=factory,
        registry=build_store_registry(include_plugins=False),
    )
    headers = {"Authorization": f"Bearer {_TOKEN}"}
    username = f"beta_{uuid4().hex[:12]}"

    try:
        with TestClient(application, raise_server_exceptions=False) as client:
            unauthorized = client.get("/api/v1/commercial/summary")
            assert unauthorized.status_code == 401

            checklist = client.get(
                "/api/v1/commercial/checklist",
                headers=headers,
            )
            assert checklist.status_code == 200, checklist.text
            assert len(checklist.json()) == 8
            assert sum(item["required"] for item in checklist.json()) == 7

            created = client.post(
                "/api/v1/subscribers",
                headers=headers,
                json={
                    "full_name": "Persona Piloto",
                    "telegram_username": f"@{username.upper()}",
                    "email": "piloto@example.com",
                    "status": "trial",
                    "duration_days": 7,
                },
            )
            assert created.status_code == 201, created.text
            subscriber_id = created.json()["id"]
            assert created.json()["telegram_username"] == username
            assert created.json()["status"] == "trial"
            assert created.headers["etag"] == '"1"'

            duplicate = client.post(
                "/api/v1/subscribers",
                headers=headers,
                json={
                    "full_name": "Duplicado",
                    "telegram_username": username,
                    "duration_days": 7,
                },
            )
            assert duplicate.status_code == 409, duplicate.text

            listed = client.get(
                f"/api/v1/subscribers?search={username}",
                headers=headers,
            )
            assert listed.status_code == 200, listed.text
            assert [item["id"] for item in listed.json()["items"]] == [
                subscriber_id
            ]

            membership = client.patch(
                f"/api/v1/subscribers/{subscriber_id}",
                headers={**headers, "If-Match": '"1"'},
                json={"telegram_membership_status": "in_group"},
            )
            assert membership.status_code == 200, membership.text
            assert membership.json()["version"] == 2
            assert membership.json()["telegram_membership_status"] == "in_group"

            stale = client.patch(
                f"/api/v1/subscribers/{subscriber_id}",
                headers={**headers, "If-Match": '"1"'},
                json={"phone": "999111222"},
            )
            assert stale.status_code == 412, stale.text

            payment_headers = {
                **headers,
                "Idempotency-Key": f"payment-{uuid4()}",
            }
            payment_payload = {
                "amount": "12.50",
                "method": "yape",
                "reference": "operacion-beta",
                "renewal_days": 30,
            }
            paid = client.post(
                f"/api/v1/subscribers/{subscriber_id}/payments",
                headers=payment_headers,
                json=payment_payload,
            )
            assert paid.status_code == 201, paid.text
            assert paid.json()["payment"]["currency"] == "PEN"
            assert paid.json()["subscriber"]["status"] == "active"
            assert paid.json()["subscriber"]["version"] == 3
            payment_id = paid.json()["payment"]["id"]
            renewed_expiry = paid.json()["subscriber"]["expires_at"]

            replay = client.post(
                f"/api/v1/subscribers/{subscriber_id}/payments",
                headers=payment_headers,
                json=payment_payload,
            )
            assert replay.status_code == 201, replay.text
            assert replay.headers["x-idempotent-replay"] == "true"
            assert replay.json()["payment"]["id"] == payment_id
            assert replay.json()["subscriber"]["expires_at"] == renewed_expiry
            assert replay.json()["subscriber"]["version"] == 3

            conflict = client.post(
                f"/api/v1/subscribers/{subscriber_id}/payments",
                headers=payment_headers,
                json={**payment_payload, "amount": "15.00"},
            )
            assert conflict.status_code == 409, conflict.text

            payments = client.get(
                f"/api/v1/subscribers/{subscriber_id}/payments",
                headers=headers,
            )
            assert payments.status_code == 200, payments.text
            assert [item["id"] for item in payments.json()] == [payment_id]

            first_item = checklist.json()[0]
            checked = client.put(
                f"/api/v1/commercial/checklist/{first_item['item_key']}",
                headers=headers,
                json={"completed": True},
            )
            assert checked.status_code == 200, checked.text
            assert checked.json()["completed"] is True
            assert checked.json()["completed_by"] == "local-admin"

            summary = client.get(
                "/api/v1/commercial/summary",
                headers=headers,
            )
            assert summary.status_code == 200, summary.text
            assert summary.json()["active_subscribers"] == 1
            assert summary.json()["members_in_group"] == 1
            assert summary.json()["confirmed_revenue_total_pen"] == "12.50"
            assert summary.json()["checklist_completed"] == 1
    finally:
        outer_transaction.rollback()
        connection.close()
        engine.dispose()
