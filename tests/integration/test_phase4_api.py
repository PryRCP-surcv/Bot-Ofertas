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

_TOKEN = "phase4-integration-admin-token-0001"


def test_phase4_admin_api_crud_policy_and_crawl_queue() -> None:
    engine = create_database_engine(DatabaseSettings.from_env())
    connection = engine.connect()
    outer_transaction = connection.begin()
    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    suffix = uuid4().hex
    application = create_app(
        ApiSettings(
            admin_token=_TOKEN,
            cors_origins=("http://localhost:5173",),
        ),
        session_factory=factory,
        registry=build_store_registry(include_plugins=False),
    )
    headers = {"Authorization": f"Bearer {_TOKEN}"}

    try:
        with TestClient(application, raise_server_exceptions=False) as client:
            created = client.post(
                "/api/v1/products",
                headers=headers,
                json={
                    "url": f"https://www.coolbox.pe/phase4-api-{suffix}/p",
                    "label": "Producto API Fase 4",
                    "expected_brand": "Marca",
                    "expected_model": "Modelo",
                    "expected_variant": {"Color": "Negro"},
                    "check_interval_minutes": 60,
                },
            )
            assert created.status_code == 201, created.text
            product = created.json()
            product_id = product["id"]
            assert product["store_slug"] == "coolbox"
            assert product["version"] == 1
            assert product["archived_at"] is None
            assert created.headers["etag"] == '"1"'

            missing_precondition = client.patch(
                f"/api/v1/products/{product_id}",
                headers=headers,
                json={"label": "No debe aplicarse"},
            )
            assert missing_precondition.status_code == 428

            updated = client.patch(
                f"/api/v1/products/{product_id}",
                headers={**headers, "If-Match": '"1"'},
                json={"label": "Producto API actualizado"},
            )
            assert updated.status_code == 200, updated.text
            assert updated.json()["version"] == 2
            assert updated.headers["etag"] == '"2"'

            deactivated = client.put(
                f"/api/v1/products/{product_id}/activation",
                headers={**headers, "If-Match": '"2"'},
                json={"active": False},
            )
            assert deactivated.status_code == 200, deactivated.text
            assert deactivated.json()["active"] is False
            assert deactivated.json()["version"] == 3

            variant = client.put(
                f"/api/v1/products/{product_id}/variant",
                headers={**headers, "If-Match": '"3"'},
                json={"expected_variant": {"Color": "Azul"}},
            )
            assert variant.status_code == 200, variant.text
            assert variant.json()["expected_variant"] == {"color": "azul"}
            assert variant.json()["version"] == 4

            cleared_variant = client.delete(
                f"/api/v1/products/{product_id}/variant",
                headers={**headers, "If-Match": '"4"'},
            )
            assert cleared_variant.status_code == 200, cleared_variant.text
            assert cleared_variant.json()["expected_variant"] == {}
            assert cleared_variant.json()["version"] == 5

            reactivated = client.put(
                f"/api/v1/products/{product_id}/activation",
                headers={**headers, "If-Match": '"5"'},
                json={"active": True},
            )
            assert reactivated.status_code == 200, reactivated.text
            assert reactivated.json()["active"] is True
            assert reactivated.json()["version"] == 6

            invalid_job = client.post(
                "/api/v1/crawl-jobs",
                headers={
                    **headers,
                    "Idempotency-Key": f"phase4-missing-product-{suffix}",
                },
                json={"product_ids": [str(uuid4())]},
            )
            assert invalid_job.status_code == 422, invalid_job.text

            oechsle_product_ids = []
            for index in range(6):
                oechsle_product = client.post(
                    "/api/v1/products",
                    headers=headers,
                    json={
                        "url": (
                            "https://www.oechsle.pe/"
                            f"phase4-quota-{suffix}-{index}/p"
                        ),
                        "label": f"Producto cuota Oechsle {index}",
                        "check_interval_minutes": 60,
                    },
                )
                assert oechsle_product.status_code == 201, oechsle_product.text
                oechsle_product_ids.append(oechsle_product.json()["id"])
            over_quota_job = client.post(
                "/api/v1/crawl-jobs",
                headers={
                    **headers,
                    "Idempotency-Key": f"phase4-over-quota-{suffix}",
                },
                json={"product_ids": oechsle_product_ids},
            )
            assert over_quota_job.status_code == 422, over_quota_job.text

            job_key = f"phase4-job-{suffix}"
            queued = client.post(
                "/api/v1/crawl-jobs",
                headers={**headers, "Idempotency-Key": job_key},
                json={"product_ids": [product_id]},
            )
            assert queued.status_code == 202, queued.text
            job = queued.json()
            assert job["status"] == "queued"
            assert len(job["items"]) == 1
            assert job["items"][0]["tracked_product_id"] == product_id

            replay = client.post(
                "/api/v1/crawl-jobs",
                headers={**headers, "Idempotency-Key": job_key},
                json={"product_ids": [product_id]},
            )
            assert replay.status_code == 202
            assert replay.json()["id"] == job["id"]
            assert replay.headers["x-idempotent-replay"] == "true"

            jobs = client.get("/api/v1/crawl-jobs", headers=headers)
            assert jobs.status_code == 200, jobs.text
            assert job["id"] in {item["id"] for item in jobs.json()["items"]}

            cancelled = client.post(
                f"/api/v1/crawl-jobs/{job['id']}/cancel",
                headers=headers,
            )
            assert cancelled.status_code == 200, cancelled.text
            assert cancelled.json()["status"] == "cancelled"
            assert cancelled.json()["items"][0]["status"] == "cancelled"

            policy_before = client.get("/api/v1/settings", headers=headers)
            assert policy_before.status_code == 200, policy_before.text
            old_etag = policy_before.headers["etag"]
            assert _TOKEN not in policy_before.text
            invalid_policy = client.patch(
                "/api/v1/settings",
                headers={
                    **headers,
                    "If-Match": old_etag,
                    "Idempotency-Key": f"phase4-invalid-policy-{suffix}",
                },
                json={"good_deal_percent": 80},
            )
            assert invalid_policy.status_code == 422, invalid_policy.text

            changed = client.patch(
                "/api/v1/settings",
                headers={
                    **headers,
                    "If-Match": old_etag,
                    "Idempotency-Key": f"phase4-policy-{suffix}",
                    "X-Change-Reason": "Prueba transaccional Fase 4",
                },
                json={"scheduler_poll_seconds": 601},
            )
            assert changed.status_code == 200, changed.text
            assert changed.headers["etag"] != old_etag
            assert changed.json()["scheduler_poll_seconds"] == 601
            assert len(changed.json()["policy_fingerprint"]) == 64

            replay_after_policy_change = client.post(
                "/api/v1/crawl-jobs",
                headers={**headers, "Idempotency-Key": job_key},
                json={"product_ids": [product_id]},
            )
            assert replay_after_policy_change.status_code == 202
            assert replay_after_policy_change.json()["id"] == job["id"]
            assert replay_after_policy_change.headers["x-idempotent-replay"] == "true"

            stale = client.patch(
                "/api/v1/settings",
                headers={
                    **headers,
                    "If-Match": old_etag,
                    "Idempotency-Key": f"phase4-policy-stale-{suffix}",
                },
                json={"scheduler_poll_seconds": 602},
            )
            assert stale.status_code == 412

            stores = client.get("/api/v1/stores", headers=headers)
            assert stores.status_code == 200, stores.text
            assert "coolbox" in {store["slug"] for store in stores.json()}

            active_offers = client.get("/api/v1/offers", headers=headers)
            history_offers = client.get(
                "/api/v1/offers?state=history",
                headers=headers,
            )
            assert active_offers.status_code == 200, active_offers.text
            assert history_offers.status_code == 200, history_offers.text

            archived = client.delete(
                f"/api/v1/products/{product_id}",
                headers={**headers, "If-Match": '"6"'},
            )
            assert archived.status_code == 204
            detail = client.get(
                f"/api/v1/products/{product_id}",
                headers=headers,
            )
            assert detail.status_code == 200
            assert detail.json()["active"] is False
            assert detail.json()["archived_at"] is not None
            assert detail.json()["version"] == 7

            active_products = client.get("/api/v1/products", headers=headers)
            assert active_products.status_code == 200
            assert product_id not in {
                item["id"] for item in active_products.json()["items"]
            }
    finally:
        outer_transaction.rollback()
        connection.close()
        engine.dispose()
