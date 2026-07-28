import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from bot_ofertas.storage import DatabaseSettings, create_database_engine
from bot_ofertas.storage.models import TrackedProduct
from bot_ofertas.storage.repositories import TrackedProductRepository

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_POSTGRES_TESTS") != "1",
        reason="define RUN_POSTGRES_TESTS=1 para usar PostgreSQL local",
    ),
]


def test_claims_are_exclusive_and_can_be_completed_or_released() -> None:
    engine = create_database_engine(DatabaseSettings.from_env())
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    suffix = uuid4().hex
    store_slug = f"claim-{suffix[:12]}"
    checked_at = datetime(2026, 7, 26, 20, 0, tzinfo=UTC)
    repository = TrackedProductRepository(session)

    try:
        tracked = repository.add(
            store_slug=store_slug,
            source_url=f"https://example.test/{suffix}",
            label="Producto reservado",
            check_interval_minutes=60,
        )

        disabled = repository.set_active(tracked.id, active=False)
        assert disabled is tracked
        assert repository.claim_due(
            limit=1,
            store_slugs={store_slug},
            now=checked_at,
        ).products == ()
        enabled = repository.set_active(tracked.id, active=True)
        assert enabled is tracked

        first = repository.claim_due(
            limit=1,
            store_slugs={store_slug},
            lease_duration=timedelta(minutes=10),
            now=checked_at,
        )
        second = repository.claim_due(
            limit=1,
            store_slugs={store_slug},
            lease_duration=timedelta(minutes=10),
            now=checked_at,
        )

        assert [product.id for product in first.products] == [tracked.id]
        assert first.products[0].lease_token == first.token
        assert second.products == ()
        assert repository.authorize_observation_target(
            product_id=tracked.id,
            store_slug=tracked.store_slug,
            source_url=tracked.source_url,
            lease_token=first.token,
            now=checked_at + timedelta(minutes=1),
        )
        assert not repository.authorize_observation_target(
            product_id=tracked.id,
            store_slug=tracked.store_slug,
            source_url=tracked.source_url,
            lease_token=uuid4(),
            now=checked_at + timedelta(minutes=1),
        )
        assert not repository.authorize_observation_target(
            product_id=tracked.id,
            store_slug=tracked.store_slug,
            source_url=f"{tracked.source_url}/different",
            lease_token=first.token,
            now=checked_at + timedelta(minutes=1),
        )
        assert not repository.authorize_observation_target(
            product_id=tracked.id,
            store_slug=tracked.store_slug,
            source_url=tracked.source_url,
            lease_token=first.token,
            now=first.expires_at,
        )

        assert (
            repository.complete_claim(
                product_id=tracked.id,
                token=uuid4(),
                succeeded=False,
                checked_at=checked_at,
            )
            is False
        )
        session.refresh(tracked)
        assert tracked.lease_token == first.token
        assert tracked.last_checked_at is None

        assert (
            repository.complete_claim(
                product_id=tracked.id,
                token=first.token,
                succeeded=False,
                checked_at=checked_at,
            )
            is True
        )
        session.refresh(tracked)
        assert tracked.lease_token is None
        assert tracked.lease_expires_at is None
        assert tracked.last_checked_at == checked_at
        assert tracked.last_success_at is None
        assert tracked.consecutive_failures == 1

        not_due = repository.claim_due(
            limit=1,
            store_slugs={store_slug},
            now=checked_at + timedelta(minutes=60),
        )
        assert not_due.products == ()

        forced = repository.claim_due(
            limit=1,
            force=True,
            store_slugs={store_slug},
            now=checked_at + timedelta(minutes=60),
        )
        assert [product.id for product in forced.products] == [tracked.id]
        assert repository.release_batch(forced) == 1
        session.refresh(tracked)
        assert tracked.last_checked_at == checked_at
        assert tracked.lease_token is None

        successful = repository.claim_due(
            limit=1,
            force=True,
            store_slugs={store_slug},
            now=checked_at + timedelta(minutes=61),
        )
        completed_at = checked_at + timedelta(minutes=62)
        assert repository.complete_claim(
            product_id=tracked.id,
            token=successful.token,
            succeeded=True,
            checked_at=completed_at,
        )
        session.refresh(tracked)
        assert tracked.last_checked_at == completed_at
        assert tracked.last_success_at == completed_at
        assert tracked.consecutive_failures == 0

        with pytest.raises(ValueError, match="at least 30"):
            repository.claim_due(minimum_interval_minutes=29)

        policy_not_due = repository.claim_due(
            limit=1,
            store_slugs={store_slug},
            minimum_interval_minutes=120,
            now=completed_at + timedelta(minutes=60),
        )
        assert policy_not_due.products == ()

        policy_due = repository.claim_due(
            limit=1,
            store_slugs={store_slug},
            minimum_interval_minutes=120,
            now=completed_at + timedelta(minutes=120),
        )
        assert [product.id for product in policy_due.products] == [tracked.id]
        assert repository.release_batch(policy_due) == 1
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def test_uncommitted_claim_lock_is_skipped_by_a_second_database_session() -> None:
    engine = create_database_engine(DatabaseSettings.from_env())
    setup_session = Session(bind=engine, expire_on_commit=False)
    first_worker = Session(bind=engine, expire_on_commit=False)
    second_worker = Session(bind=engine, expire_on_commit=False)
    suffix = uuid4().hex
    store_slug = f"lock-{suffix[:12]}"
    claimed_at = datetime(2026, 7, 26, 21, 0, tzinfo=UTC)
    tracked_id = None

    try:
        tracked = TrackedProductRepository(setup_session).add(
            store_slug=store_slug,
            source_url=f"https://example.test/lock/{suffix}",
            label="Producto para dos workers",
            check_interval_minutes=30,
        )
        tracked_id = tracked.id
        setup_session.commit()

        first = TrackedProductRepository(first_worker).claim_due(
            limit=1,
            store_slugs={store_slug},
            now=claimed_at,
        )
        assert [product.id for product in first.products] == [tracked_id]

        while_first_lock_is_uncommitted = TrackedProductRepository(second_worker).claim_due(
            limit=1,
            store_slugs={store_slug},
            now=claimed_at,
        )
        assert while_first_lock_is_uncommitted.products == ()

        first_worker.rollback()
        second_worker.rollback()

        after_rollback = TrackedProductRepository(second_worker).claim_due(
            limit=1,
            store_slugs={store_slug},
            now=claimed_at,
        )
        assert [product.id for product in after_rollback.products] == [tracked_id]
        assert after_rollback.token != first.token
        second_worker.commit()

        assert not TrackedProductRepository(first_worker).authorize_observation_target(
            product_id=tracked_id,
            store_slug=store_slug,
            source_url=f"https://example.test/lock/{suffix}",
            lease_token=first.token,
            now=claimed_at + timedelta(minutes=1),
        )
    finally:
        setup_session.rollback()
        first_worker.rollback()
        second_worker.rollback()
        setup_session.close()
        first_worker.close()
        second_worker.close()
        if tracked_id is not None:
            with engine.begin() as cleanup_connection:
                cleanup_connection.execute(
                    delete(TrackedProduct).where(TrackedProduct.id == tracked_id)
                )
        engine.dispose()
