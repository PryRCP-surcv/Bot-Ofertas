from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from bot_ofertas.api.app import create_app
from bot_ofertas.api.settings import ApiSettings
from bot_ofertas.storage import DatabaseSettings, create_database_engine
from bot_ofertas.storage.database import session_scope
from bot_ofertas.storage.discovery import DiscoveryRepository
from bot_ofertas.storage.models import DiscoveryRunStatus
from bot_ofertas.stores import build_store_registry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_POSTGRES_TESTS") != "1",
        reason="define RUN_POSTGRES_TESTS=1 para usar PostgreSQL local",
    ),
]

_TOKEN = "phase5-integration-admin-token-0001"


def test_phase5_sources_candidates_review_and_limits() -> None:
    engine = create_database_engine(DatabaseSettings.from_env())
    connection = engine.connect()
    outer_transaction = connection.begin()
    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    registry = build_store_registry(include_plugins=False)
    suffix = uuid4().hex
    application = create_app(
        ApiSettings(
            admin_token=_TOKEN,
            cors_origins=("http://localhost:3000",),
        ),
        session_factory=factory,
        registry=registry,
    )
    headers = {"Authorization": f"Bearer {_TOKEN}"}

    try:
        with session_scope(factory) as session:
            repository = DiscoveryRepository(session)
            repository.sync_registry(registry)
            source = next(
                source
                for source in repository.list_sources()
                if source.store_slug == "coolbox"
            )
            claim = repository.claim_due(
                requested_by="cli",
                limit=1,
                force=True,
                source_id=source.id,
            )[0]
            first = repository.record_candidate(
                claim,
                discovered_url=(
                    f"https://www.coolbox.pe/phase5-first-{suffix}/p"
                ),
                canonical_url=(
                    f"https://www.coolbox.pe/phase5-first-{suffix}/p"
                ),
                label="Producto descubierto uno",
            )
            second = repository.record_candidate(
                claim,
                discovered_url=(
                    f"https://www.coolbox.pe/phase5-second-{suffix}/p"
                ),
                canonical_url=(
                    f"https://www.coolbox.pe/phase5-second-{suffix}/p"
                ),
                label="Producto descubierto dos",
            )
            repository.complete_claim(
                claim,
                status=DiscoveryRunStatus.SUCCEEDED,
                document_count=2,
                candidate_count=2,
                new_count=2,
                duplicate_count=0,
                rejected_count=0,
                error_count=0,
                stats={"test": True},
                next_scan_cursor=1,
            )
            source_id = source.id

        with TestClient(application, raise_server_exceptions=False) as client:
            sources = client.get("/api/v1/discovery/sources", headers=headers)
            assert sources.status_code == 200, sources.text
            source_payload = next(
                item
                for item in sources.json()
                if item["id"] == str(source_id)
            )
            assert source_payload["candidate_counts"]["pending"] == 2
            assert source_payload["max_documents_per_run"] == 2

            candidates = client.get(
                "/api/v1/discovery/candidates?status=pending",
                headers=headers,
            )
            assert candidates.status_code == 200, candidates.text
            candidate_ids = {
                item["id"] for item in candidates.json()["items"]
            }
            assert str(first.candidate_id) in candidate_ids
            assert str(second.candidate_id) in candidate_ids

            with session_scope(factory) as session:
                source_for_limit = session.get(
                    type(source),
                    source_id,
                )
                assert source_for_limit is not None
                source_for_limit.daily_approval_limit = 1

            approved = client.post(
                f"/api/v1/discovery/candidates/{first.candidate_id}/review",
                headers=headers,
                json={"action": "approve", "label": "Producto aprobado"},
            )
            assert approved.status_code == 200, approved.text
            assert approved.json()["status"] == "approved"
            assert approved.json()["tracked_product_id"] is not None

            over_daily_limit = client.post(
                f"/api/v1/discovery/candidates/{second.candidate_id}/review",
                headers=headers,
                json={"action": "approve"},
            )
            assert over_daily_limit.status_code == 422, over_daily_limit.text

            rejected = client.post(
                f"/api/v1/discovery/candidates/{second.candidate_id}/review",
                headers=headers,
                json={"action": "reject", "reason": "No priorizado en la beta"},
            )
            assert rejected.status_code == 200, rejected.text
            assert rejected.json()["status"] == "rejected"
            assert rejected.json()["reason"] == "No priorizado en la beta"

            scheduled = client.post(
                f"/api/v1/discovery/sources/{source_id}/run",
                headers=headers,
            )
            assert scheduled.status_code == 202, scheduled.text

            runs = client.get("/api/v1/discovery/runs", headers=headers)
            assert runs.status_code == 200, runs.text
            assert str(claim.run_id) in {run["id"] for run in runs.json()}

            products = client.get(
                "/api/v1/products?search=Producto%20aprobado",
                headers=headers,
            )
            assert products.status_code == 200, products.text
            assert any(
                item["label"] == "Producto aprobado"
                for item in products.json()["items"]
            )
    finally:
        outer_transaction.rollback()
        connection.close()
        engine.dispose()
