import hashlib
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bot_ofertas.detection import DetectorConfig
from bot_ofertas.domain import Availability, PriceObservation, ProductCondition
from bot_ofertas.runtime_config import RuntimeSettings
from bot_ofertas.services.detection import DetectionService
from bot_ofertas.storage import DatabaseSettings, create_database_engine
from bot_ofertas.storage.models import NotificationDelivery
from bot_ofertas.storage.notifications import NotificationDeliveryRepository
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


def _settings() -> RuntimeSettings:
    return RuntimeSettings(
        detector_version="phase6-6-variant-integration",
        confirmation_required=True,
        confirmation_max_age_minutes=180,
        confirmation_price_tolerance_ratio=Decimal("0.03"),
        confirmation_confidence_bonus=20,
        minimum_alert_confidence=50,
        detector_config=DetectorConfig(minimum_history_samples=1),
    )


def _save_size_run(
    session: Session,
    *,
    product_id: UUID,
    source_url: str,
    external_product_id: str,
    observed_at: datetime,
    marker: str,
) -> None:
    run = CrawlRunRepository(session).start(
        store_slug="topitop",
        spider_name="phase6_6_topitop",
        requested_url_count=1,
        started_at=observed_at,
    )
    for size in ("S", "M"):
        PriceObservationRepository(session).save(
            run_id=run.id,
            observation=PriceObservation(
                tracked_product_id=product_id,
                store_slug="topitop",
                source_url=source_url,
                external_product_id=external_product_id,
                product_reference=f"REF-{external_product_id}",
                sku=f"SKU-{external_product_id}-{size}",
                sku_reference=f"SKU-REF-{size}",
                seller_id="1",
                seller_name="TRADING FASHION LINE S.A.",
                title=f"Polo urbano azul talla {size}",
                brand="Topitop",
                model="Urbano",
                category_path=["Básicos", "Hombre"],
                variant={"Color": "Azul", "Talla": size},
                condition=ProductCondition.NEW,
                currency="PEN",
                price=Decimal("59.90"),
                list_price=Decimal("99.90"),
                availability=Availability.IN_STOCK,
                available_quantity=3,
                is_marketplace=False,
                observed_at=observed_at,
                extractor_version="phase6-6-integration",
                source_payload_hash=hashlib.sha256(
                    f"{marker}-{size}".encode()
                ).hexdigest(),
            ),
        )


def test_exact_sizes_are_confirmed_independently_but_notify_as_one_group() -> None:
    engine = create_database_engine(DatabaseSettings.from_env())
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    suffix = uuid4().hex
    settings = _settings()
    first_at = datetime.now(UTC) - timedelta(hours=2)

    try:
        source_url = f"https://www.topitop.pe/polo-balance-{suffix}/p"
        product = TrackedProductRepository(session).add(
            store_slug="topitop",
            source_url=source_url,
            label="Polo urbano azul",
            expected_variant={},
            check_interval_minutes=60,
        )
        external_product_id = f"balance-{suffix}"
        _save_size_run(
            session,
            product_id=product.id,
            source_url=source_url,
            external_product_id=external_product_id,
            observed_at=first_at,
            marker="first",
        )
        first = DetectionService(session, settings).process_new()

        assert first.alert_candidates == 2
        assert first.awaiting_confirmation == 2
        assert product.expected_variant == {}

        _save_size_run(
            session,
            product_id=product.id,
            source_url=source_url,
            external_product_id=external_product_id,
            observed_at=first_at + timedelta(hours=1),
            marker="second",
        )
        second = DetectionService(session, settings).process_new()

        assert second.confirmed_candidates == 2
        assert second.notifications_reserved == 1
        assert (
            session.scalar(select(func.count()).select_from(NotificationDelivery))
            == 1
        )

        claim = NotificationDeliveryRepository(session).claim_due(
            channel="telegram_free",
            limit=10,
            max_attempts=5,
        )[0]
        assert claim.variant_summary is not None
        assert "Talla=m" in claim.variant_summary
        assert "Talla=s" in claim.variant_summary
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()
