import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from bot_ofertas.storage import (
    DatabaseSettings,
    StoreCrawlStateRepository,
    TrackedProductRepository,
    create_database_engine,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_POSTGRES_TESTS") != "1",
        reason="define RUN_POSTGRES_TESTS=1 para usar PostgreSQL local",
    ),
]


def test_store_pause_excludes_normal_and_forced_claims_until_recovery() -> None:
    engine = create_database_engine(DatabaseSettings.from_env())
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    suffix = uuid4().hex
    paused_store = f"paused-{suffix[:12]}"
    healthy_store = f"healthy-{suffix[:12]}"
    now = datetime(2026, 7, 26, 22, 0, tzinfo=UTC)
    products = TrackedProductRepository(session)
    states = StoreCrawlStateRepository(session)

    try:
        paused_product = products.add(
            store_slug=paused_store,
            source_url=f"https://paused.example.test/{suffix}",
            label="Producto de tienda pausada",
            check_interval_minutes=30,
        )
        healthy_product = products.add(
            store_slug=healthy_store,
            source_url=f"https://healthy.example.test/{suffix}",
            label="Producto de tienda activa",
            check_interval_minutes=30,
        )

        pre_pause_claim = products.claim_due(
            limit=1,
            force=True,
            store_slugs={paused_store},
            now=now - timedelta(minutes=1),
        )
        assert [product.id for product in pre_pause_claim.products] == [paused_product.id]

        pause = states.pause(
            store_slug=paused_store,
            reason="HTTP 429",
            duration=timedelta(minutes=20),
            now=now,
        )
        assert pause.paused_until == now + timedelta(minutes=20)
        assert pause.pause_reason == "HTTP 429"
        assert pause.consecutive_blocks == 1
        session.refresh(paused_product)
        assert paused_product.lease_token is None
        assert paused_product.lease_expires_at is None
        assert states.get(paused_store) is pause
        assert [state.store_slug for state in states.active_pauses(now=now)] == [paused_store]

        normal_claim = products.claim_due(
            limit=10,
            store_slugs={paused_store, healthy_store},
            now=now,
        )
        assert [product.id for product in normal_claim.products] == [healthy_product.id]
        assert products.release_batch(normal_claim) == 1

        forced_claim = products.claim_due(
            limit=10,
            force=True,
            store_slugs={paused_store},
            now=now + timedelta(minutes=1),
        )
        assert forced_claim.products == ()

        shorter_extension = states.pause(
            store_slug=paused_store,
            reason="HTTP 403",
            duration=timedelta(minutes=5),
            now=now + timedelta(minutes=1),
        )
        assert shorter_extension.paused_until == now + timedelta(minutes=20)
        assert shorter_extension.pause_reason == "HTTP 403"
        assert shorter_extension.consecutive_blocks == 2

        expired_claim = products.claim_due(
            limit=1,
            force=True,
            store_slugs={paused_store},
            now=now + timedelta(minutes=20),
        )
        assert [product.id for product in expired_claim.products] == [paused_product.id]
        assert products.release_batch(expired_claim) == 1

        states.pause(
            store_slug=paused_store,
            reason="HTTP 503",
            duration=timedelta(minutes=30),
            now=now + timedelta(minutes=21),
        )
        assert (
            products.claim_due(
                limit=1,
                force=True,
                store_slugs={paused_store},
                now=now + timedelta(minutes=22),
            ).products
            == ()
        )

        recovered = states.record_success(
            store_slug=paused_store,
            now=now + timedelta(minutes=22),
        )
        assert recovered.paused_until is None
        assert recovered.pause_reason is None
        assert recovered.consecutive_blocks == 0
        assert states.active_pauses(store_slugs={paused_store}, now=now) == []

        recovered_claim = products.claim_due(
            limit=1,
            force=True,
            store_slugs={paused_store},
            now=now + timedelta(minutes=22),
        )
        assert [product.id for product in recovered_claim.products] == [paused_product.id]
        assert products.release_batch(recovered_claim) == 1
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()
