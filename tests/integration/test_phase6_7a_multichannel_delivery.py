from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from bot_ofertas.detection import DetectorConfig
from bot_ofertas.domain import Availability, PriceObservation, ProductCondition
from bot_ofertas.runtime_config import RuntimeSettings
from bot_ofertas.services.detection import DetectionService
from bot_ofertas.storage import DatabaseSettings, create_database_engine
from bot_ofertas.storage.models import DealDetection, NotificationDelivery
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


def test_one_detection_creates_auditable_independent_free_and_vip_deliveries() -> None:
    engine = create_database_engine(DatabaseSettings.from_env())
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    suffix = uuid4().hex
    observed_at = datetime.now(UTC) - timedelta(minutes=5)
    settings = RuntimeSettings(
        detector_version="phase6-7a-integration",
        confirmation_required=False,
        minimum_alert_confidence=0,
        telegram_free_chat_id="-100111",
        telegram_vip_chat_id="-100222",
        telegram_vip_mirror_enabled=True,
        detector_config=DetectorConfig(minimum_history_samples=1),
    )

    try:
        source_url = f"https://www.coolbox.pe/phase67a-{suffix}/p"
        product = TrackedProductRepository(session).add(
            store_slug="coolbox",
            source_url=source_url,
            label="Audifonos Phase 6.7A",
            check_interval_minutes=60,
        )
        run = CrawlRunRepository(session).start(
            store_slug="coolbox",
            spider_name="phase6_7a_integration",
            requested_url_count=1,
            started_at=observed_at,
        )
        saved = PriceObservationRepository(session).save(
            run_id=run.id,
            observation=PriceObservation(
                tracked_product_id=product.id,
                store_slug="coolbox",
                source_url=source_url,
                external_product_id=f"phase67a-{suffix}",
                product_reference=f"REF-{suffix}",
                sku=f"SKU-{suffix}",
                sku_reference=f"SKU-REF-{suffix}",
                seller_id="1",
                seller_name="Coolbox",
                title="Audifonos inalambricos Phase 6.7A",
                brand="Acme",
                model="A67",
                category_path=["Tecnologia", "Audio"],
                variant={"Color": "Negro"},
                condition=ProductCondition.NEW,
                currency="PEN",
                price=Decimal("49.90"),
                list_price=Decimal("99.90"),
                availability=Availability.IN_STOCK,
                available_quantity=5,
                is_marketplace=False,
                observed_at=observed_at,
                extractor_version="phase6-7a-integration",
                source_payload_hash=hashlib.sha256(suffix.encode()).hexdigest(),
            ),
        )

        summary = DetectionService(session, settings).process_new()
        detection = session.scalar(
            select(DealDetection).where(
                DealDetection.observation_id == saved.observation_id
            )
        )
        assert detection is not None
        deliveries = list(
            session.scalars(
                select(NotificationDelivery)
                .where(NotificationDelivery.detection_id == detection.id)
                .order_by(NotificationDelivery.channel)
            )
        )

        assert summary.notifications_reserved == 1
        assert [delivery.channel for delivery in deliveries] == [
            "telegram_free",
            "telegram_vip",
        ]
        assert [delivery.audience for delivery in deliveries] == ["free", "vip"]
        assert [delivery.dispatch_mode for delivery in deliveries] == [
            "immediate",
            "mirrored",
        ]
        assert all(delivery.provider == "telegram" for delivery in deliveries)
        assert all(delivery.routing_reason for delivery in deliveries)
        assert all(
            delivery.scheduled_for >= delivery.routed_at
            for delivery in deliveries
        )

        repository = NotificationDeliveryRepository(session)
        free_claim = repository.claim_due(
            channel="telegram_free",
            now=datetime.now(UTC),
        )[0]
        vip_claim = repository.claim_due(
            channel="telegram_vip",
            now=datetime.now(UTC),
        )[0]

        assert free_claim.audience == "free"
        assert vip_claim.audience == "vip"
        assert free_claim.delivery_id != vip_claim.delivery_id
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()
