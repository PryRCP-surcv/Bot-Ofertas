import os
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from bot_ofertas.domain import Availability, PriceObservation, ProductCondition
from bot_ofertas.storage import DatabaseSettings, create_database_engine
from bot_ofertas.storage.models import CrawlRunStatus
from bot_ofertas.storage.repositories import (
    CrawlRunRepository,
    PriceObservationRepository,
    TrackedProductRepository,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_POSTGRES_TESTS") != "1",
        reason="define RUN_POSTGRES_TESTS=1 para usar PostgreSQL local",
    ),
]


def _observation(
    *,
    tracked_product_id: UUID,
    source_url: str,
    suffix: str,
    price: str,
    payload_hash_character: str,
) -> PriceObservation:
    return PriceObservation(
        tracked_product_id=tracked_product_id,
        store_slug="coolbox",
        source_url=source_url,
        external_product_id=f"product-{tracked_product_id}",
        product_reference=f"REF-{tracked_product_id}",
        sku=f"SHARED-SKU-{suffix}",
        sku_reference=f"SHARED-SKU-REF-{suffix}",
        seller_id="1",
        seller_name="Rash Peru S.R.L",
        title="Producto de integración",
        brand="Marca",
        model="Modelo",
        category_path=["Tecnología"],
        variant={"Color": "Negro"},
        condition=ProductCondition.NEW,
        currency="PEN",
        price=Decimal(price),
        list_price=Decimal("249.90"),
        availability=Availability.IN_STOCK,
        available_quantity=2,
        is_marketplace=False,
        observed_at=datetime.now(UTC),
        extractor_version="integration-v1",
        source_payload_hash=payload_hash_character * 64,
    )


def test_history_identity_is_idempotent_per_tracked_product() -> None:
    engine = create_database_engine(DatabaseSettings.from_env())
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    suffix = uuid4().hex

    try:
        products = TrackedProductRepository(session)
        first_product = products.add(
            store_slug="coolbox",
            source_url=f"https://www.coolbox.pe/integration-a-{suffix}/p",
            label="Primera ficha",
            check_interval_minutes=60,
        )
        second_product = products.add(
            store_slug="coolbox",
            source_url=f"https://www.coolbox.pe/integration-b-{suffix}/p",
            label="Segunda ficha",
            check_interval_minutes=60,
        )
        run = CrawlRunRepository(session).start(
            store_slug="coolbox",
            spider_name="integration_test",
            requested_url_count=2,
        )
        first_observation = _observation(
            tracked_product_id=first_product.id,
            source_url=first_product.source_url,
            suffix=suffix,
            price="199.90",
            payload_hash_character="a",
        )
        second_observation = _observation(
            tracked_product_id=second_product.id,
            source_url=second_product.source_url,
            suffix=suffix,
            price="149.90",
            payload_hash_character="b",
        )
        repository = PriceObservationRepository(session)

        first = repository.save(run_id=run.id, observation=first_observation)
        duplicate = repository.save(run_id=run.id, observation=first_observation)
        second = repository.save(run_id=run.id, observation=second_observation)
        latest_first = repository.latest_for_offer(
            tracked_product_id=first_product.id,
            store_slug="coolbox",
            sku=first_observation.sku,
            seller_id=first_observation.seller_id,
        )
        latest_second = repository.latest_for_offer(
            tracked_product_id=second_product.id,
            store_slug="coolbox",
            sku=second_observation.sku,
            seller_id=second_observation.seller_id,
        )
        CrawlRunRepository(session).finish(
            run,
            status=CrawlRunStatus.SUCCEEDED,
            observation_count=2,
            error_count=0,
        )

        assert first.inserted is True
        assert duplicate.inserted is False
        assert duplicate.observation_id == first.observation_id
        assert second.inserted is True
        assert second.observation_id != first.observation_id
        assert latest_first is not None
        assert latest_first.price == Decimal("199.9000")
        assert latest_second is not None
        assert latest_second.price == Decimal("149.9000")
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()
