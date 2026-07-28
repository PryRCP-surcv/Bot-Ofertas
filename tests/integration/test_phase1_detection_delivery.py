import hashlib
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from bot_ofertas.detection import DetectorConfig
from bot_ofertas.domain import Availability, PriceObservation, ProductCondition
from bot_ofertas.notifications import (
    NotificationResult,
    NotificationStatus,
    OfferNotification,
)
from bot_ofertas.runtime_config import RuntimeSettings
from bot_ofertas.services.detection import DetectionService
from bot_ofertas.services.notifications import NotificationDispatcher
from bot_ofertas.storage import DatabaseSettings, create_database_engine
from bot_ofertas.storage.models import (
    DealDetection,
    NotificationDelivery,
    TrackedProduct,
)
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


def _observation(
    *,
    tracked_product_id: UUID,
    source_url: str,
    observed_at: datetime,
    price: str,
    payload_marker: str,
    variant: dict[str, str] | None = None,
    is_marketplace: bool = False,
) -> PriceObservation:
    return PriceObservation(
        tracked_product_id=tracked_product_id,
        store_slug="coolbox",
        source_url=source_url,
        external_product_id="phase1-product",
        product_reference="PHASE1-REF",
        sku="PHASE1-SKU",
        sku_reference="PHASE1-SKU-REF",
        seller_id="1",
        seller_name="Coolbox",
        title="Laptop Acme Pro 14 Modelo X14",
        brand="Acme",
        model="X14",
        category_path=["Tecnología", "Computación"],
        variant=variant or {"Memoria": "16 GB", "Color": "Negro"},
        condition=ProductCondition.NEW,
        currency="PEN",
        price=Decimal(price),
        list_price=Decimal("100.00"),
        availability=Availability.IN_STOCK,
        available_quantity=4,
        is_marketplace=is_marketplace,
        observed_at=observed_at,
        extractor_version="phase1-integration-v1",
        source_payload_hash=hashlib.sha256(payload_marker.encode()).hexdigest(),
    )


def test_detection_dedupe_and_retryable_telegram_delivery_are_transactional() -> None:
    engine = create_database_engine(DatabaseSettings.from_env())
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    suffix = uuid4().hex
    product_id: UUID | None = None

    settings = RuntimeSettings(
        detector_version="phase1-v1",
        confirmation_required=False,
        minimum_alert_confidence=0,
        detection_history_limit=10,
        alert_cooldown_hours=24,
        alert_significant_improvement_ratio=Decimal("0.05"),
        notification_lease_seconds=120,
        notification_max_attempts=3,
        notification_retry_base_seconds=30,
        detector_config=DetectorConfig(minimum_history_samples=1),
    )
    first_observed_at = datetime(2026, 7, 27, 14, 0, tzinfo=UTC)

    try:
        source_url = f"https://www.coolbox.pe/phase1-{suffix}/p"
        product = TrackedProductRepository(session).add(
            store_slug="coolbox",
            source_url=source_url,
            label="Laptop Acme Pro 14",
            check_interval_minutes=60,
            expected_brand="Acme",
            expected_model="X14",
            expected_variant={"Memoria": "16 GB", "Color": "Negro"},
            expected_is_accessory=False,
        )
        product_id = product.id
        observation_repository = PriceObservationRepository(session)

        first_run = CrawlRunRepository(session).start(
            store_slug="coolbox",
            spider_name="phase1_integration",
            requested_url_count=1,
            started_at=first_observed_at,
        )
        first_saved = observation_repository.save(
            run_id=first_run.id,
            observation=_observation(
                tracked_product_id=product.id,
                source_url=source_url,
                observed_at=first_observed_at,
                price="50.00",
                payload_marker=f"{suffix}-first",
            ),
        )
        assert first_saved.inserted is True

        first_summary = DetectionService(session, settings).process_new()
        first_detection = session.scalar(
            select(DealDetection).where(DealDetection.observation_id == first_saved.observation_id)
        )
        assert first_summary.processed == 1
        assert first_summary.alert_candidates == 1
        assert first_summary.notifications_reserved == 1
        assert first_summary.duplicates_suppressed == 0
        assert first_detection is not None
        assert first_detection.classification == "exceptional_deal"
        assert first_detection.notification_status == "pending"

        second_observed_at = first_observed_at + timedelta(hours=1)
        second_run = CrawlRunRepository(session).start(
            store_slug="coolbox",
            spider_name="phase1_integration",
            requested_url_count=1,
            started_at=second_observed_at,
        )
        second_saved = observation_repository.save(
            run_id=second_run.id,
            observation=_observation(
                tracked_product_id=product.id,
                source_url=source_url,
                observed_at=second_observed_at,
                price="49.00",
                payload_marker=f"{suffix}-second",
            ),
        )
        assert second_saved.inserted is True

        second_summary = DetectionService(session, settings).process_new()
        second_detection = session.scalar(
            select(DealDetection).where(DealDetection.observation_id == second_saved.observation_id)
        )
        assert second_summary.processed == 1
        assert second_summary.alert_candidates == 1
        assert second_summary.notifications_reserved == 0
        assert second_summary.duplicates_suppressed == 1
        assert second_detection is not None
        assert second_detection.notification_status == "suppressed"
        assert (
            session.scalar(
                select(func.count())
                .select_from(NotificationDelivery)
                .join(
                    DealDetection,
                    DealDetection.id == NotificationDelivery.detection_id,
                )
                .where(DealDetection.tracked_product_id == product.id)
            )
            == 1
        )

        claim_time = datetime.now(UTC) + timedelta(minutes=1)
        delivery_repository = NotificationDeliveryRepository(session)
        first_claims = delivery_repository.claim_due(
            channel="telegram",
            limit=100,
            max_attempts=3,
            lease_duration=timedelta(seconds=120),
            now=claim_time,
        )
        first_claim = next(
            claim for claim in first_claims if claim.detection_id == first_detection.id
        )
        assert first_claim.detection_id == first_detection.id
        assert first_claim.product_name == "Laptop Acme Pro 14"

        assert delivery_repository.complete(
            delivery_id=first_claim.delivery_id,
            lease_token=first_claim.lease_token,
            sent=False,
            max_attempts=3,
            retry_base_seconds=30,
            error_code="provider_unavailable",
            error_detail="fallo reintentable simulado",
            now=claim_time,
        )
        delivery = session.get(NotificationDelivery, first_claim.delivery_id)
        assert delivery is not None
        assert delivery.status == "retrying"
        assert delivery.attempt_count == 1
        assert delivery.next_attempt_at == claim_time + timedelta(seconds=30)
        assert first_detection.notification_status == "retrying"

        not_due_claims = delivery_repository.claim_due(
            channel="telegram",
            max_attempts=3,
            now=claim_time + timedelta(seconds=29),
        )
        assert all(claim.detection_id != first_detection.id for claim in not_due_claims)
        retry_claims = delivery_repository.claim_due(
            channel="telegram",
            max_attempts=3,
            now=claim_time + timedelta(seconds=30),
        )
        retry_claim = next(
            claim for claim in retry_claims if claim.detection_id == first_detection.id
        )
        assert retry_claim.delivery_id == first_claim.delivery_id

        sent_at = claim_time + timedelta(seconds=31)
        assert delivery_repository.complete(
            delivery_id=retry_claim.delivery_id,
            lease_token=retry_claim.lease_token,
            sent=True,
            max_attempts=3,
            retry_base_seconds=30,
            provider_message_id="fake-telegram-message",
            now=sent_at,
        )
        assert delivery.status == "sent"
        assert delivery.attempt_count == 2
        assert delivery.provider_message_id == "fake-telegram-message"
        assert delivery.sent_at == sent_at
        assert first_detection.notification_status == "sent"
        assert first_detection.notified_at == sent_at
    finally:
        session.close()
        transaction.rollback()
        connection.close()

    try:
        if product_id is not None:
            with engine.connect() as verification:
                remaining = verification.scalar(
                    select(func.count())
                    .select_from(TrackedProduct)
                    .where(TrackedProduct.id == product_id)
                )
            assert remaining == 0
    finally:
        engine.dispose()


def test_backfill_persists_old_decisions_but_only_latest_snapshot_can_alert() -> None:
    engine = create_database_engine(DatabaseSettings.from_env())
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    suffix = uuid4().hex
    observed_at = datetime(2026, 7, 27, 17, 0, tzinfo=UTC)
    settings = RuntimeSettings(
        detector_version="phase1-v1",
        confirmation_required=False,
        minimum_alert_confidence=0,
        detector_config=DetectorConfig(minimum_history_samples=1),
    )

    try:
        source_url = f"https://www.coolbox.pe/backfill-{suffix}/p"
        product = TrackedProductRepository(session).add(
            store_slug="coolbox",
            source_url=source_url,
            label="Producto de backfill",
            expected_brand="Acme",
            expected_model="X14",
            expected_variant={"Memoria": "16 GB", "Color": "Negro"},
        )
        observations = PriceObservationRepository(session)
        saved_ids: list[int] = []
        for position, price in enumerate(("40.00", "100.00")):
            timestamp = observed_at + timedelta(hours=position)
            run = CrawlRunRepository(session).start(
                store_slug="coolbox",
                spider_name="phase1_backfill",
                requested_url_count=1,
                started_at=timestamp,
            )
            saved = observations.save(
                run_id=run.id,
                observation=_observation(
                    tracked_product_id=product.id,
                    source_url=source_url,
                    observed_at=timestamp,
                    price=price,
                    payload_marker=f"{suffix}-{position}",
                ),
            )
            saved_ids.append(saved.observation_id)

        summary = DetectionService(session, settings).process_new(limit=10)
        detections = list(
            session.scalars(
                select(DealDetection)
                .where(DealDetection.observation_id.in_(saved_ids))
                .order_by(DealDetection.observation_id.asc())
            )
        )

        assert summary.processed == 2
        assert detections[0].classification == "exceptional_deal"
        assert detections[0].notification_status == "suppressed"
        assert detections[1].classification == "none"
        assert detections[1].notification_status == "not_applicable"
        assert (
            session.scalar(
                select(func.count())
                .select_from(NotificationDelivery)
                .join(
                    DealDetection,
                    DealDetection.id == NotificationDelivery.detection_id,
                )
                .where(DealDetection.tracked_product_id == product.id)
            )
            == 0
        )
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def test_expired_last_attempt_is_swept_to_failed_after_worker_crash() -> None:
    engine = create_database_engine(DatabaseSettings.from_env())
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    suffix = uuid4().hex
    observed_at = datetime(2026, 7, 27, 19, 0, tzinfo=UTC)
    settings = RuntimeSettings(
        detector_version="phase1-v1",
        confirmation_required=False,
        minimum_alert_confidence=0,
        notification_max_attempts=1,
        detector_config=DetectorConfig(minimum_history_samples=1),
    )

    try:
        source_url = f"https://www.coolbox.pe/crash-{suffix}/p"
        product = TrackedProductRepository(session).add(
            store_slug="coolbox",
            source_url=source_url,
            label="Producto con worker interrumpido",
            expected_brand="Acme",
            expected_model="X14",
            expected_variant={"Memoria": "16 GB", "Color": "Negro"},
        )
        run = CrawlRunRepository(session).start(
            store_slug="coolbox",
            spider_name="phase1_crash",
            requested_url_count=1,
            started_at=observed_at,
        )
        saved = PriceObservationRepository(session).save(
            run_id=run.id,
            observation=_observation(
                tracked_product_id=product.id,
                source_url=source_url,
                observed_at=observed_at,
                price="40.00",
                payload_marker=suffix,
            ),
        )
        DetectionService(session, settings).process_new(limit=1)
        detection = session.scalar(
            select(DealDetection).where(DealDetection.observation_id == saved.observation_id)
        )
        assert detection is not None
        delivery = session.scalar(
            select(NotificationDelivery).where(NotificationDelivery.detection_id == detection.id)
        )
        assert delivery is not None
        isolated_channel = f"test-{suffix[:12]}"
        delivery.channel = isolated_channel
        session.flush()

        repository = NotificationDeliveryRepository(session)
        claim_time = datetime.now(UTC) + timedelta(minutes=1)
        claims = repository.claim_due(
            channel=isolated_channel,
            limit=1,
            max_attempts=1,
            lease_duration=timedelta(seconds=30),
            now=claim_time,
        )
        claim = next(item for item in claims if item.detection_id == detection.id)

        # Simulate a process crash: the claim is never completed.
        after_expiry = repository.claim_due(
            channel=isolated_channel,
            limit=1,
            max_attempts=1,
            lease_duration=timedelta(seconds=30),
            now=claim_time + timedelta(seconds=31),
        )
        delivery = session.get(NotificationDelivery, claim.delivery_id)

        assert all(item.detection_id != detection.id for item in after_expiry)
        assert delivery is not None
        assert delivery.status == "failed"
        assert delivery.lease_token is None
        assert detection.notification_status == "failed"
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def test_invalid_first_observation_cannot_poison_learned_variant() -> None:
    engine = create_database_engine(DatabaseSettings.from_env())
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    suffix = uuid4().hex
    observed_at = datetime(2026, 7, 27, 20, 0, tzinfo=UTC)

    try:
        source_url = f"https://www.coolbox.pe/variant-{suffix}/p"
        product = TrackedProductRepository(session).add(
            store_slug="coolbox",
            source_url=source_url,
            label="Producto con variante aprendida",
            expected_brand="Acme",
            expected_model="X14",
        )
        observations = PriceObservationRepository(session)
        for position, (variant, marketplace) in enumerate(
            (
                (
                    {
                        "Color": "Rojo",
                        "cólor": "Azul",
                        "Memoria": "8 GB",
                    },
                    False,
                ),
                ({"Color": "Negro", "Memoria": "16 GB"}, False),
            )
        ):
            timestamp = observed_at + timedelta(hours=position)
            run = CrawlRunRepository(session).start(
                store_slug="coolbox",
                spider_name="phase1_variant_learning",
                requested_url_count=1,
                started_at=timestamp,
            )
            observations.save(
                run_id=run.id,
                observation=_observation(
                    tracked_product_id=product.id,
                    source_url=source_url,
                    observed_at=timestamp,
                    price="100.00",
                    payload_marker=f"{suffix}-{position}",
                    variant=variant,
                    is_marketplace=marketplace,
                ),
            )

        summary = DetectionService(
            session,
            RuntimeSettings(
                detector_version="phase1-v1",
                confirmation_required=False,
                minimum_alert_confidence=0,
            ),
        ).process_new(limit=10)

        assert summary.processed == 2
        assert summary.processing_errors == 1
        assert summary.rejected == 0
        assert product.expected_variant == {
            "color": "negro",
            "memoria": "16 gb",
        }
        processing_error = session.scalar(
            select(DealDetection).where(
                DealDetection.tracked_product_id == product.id,
                DealDetection.rejection_reasons.contains(["processing_error"]),
            )
        )
        assert processing_error is not None
        assert processing_error.metrics == {"processing_error_type": "ValueError"}
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def test_stronger_candidate_supersedes_an_unsent_delivery() -> None:
    engine = create_database_engine(DatabaseSettings.from_env())
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    suffix = uuid4().hex
    first_at = datetime(2026, 7, 27, 22, 0, tzinfo=UTC)
    settings = RuntimeSettings(
        detector_version="phase1-v1",
        confirmation_required=False,
        minimum_alert_confidence=0,
        detector_config=DetectorConfig(minimum_history_samples=1),
    )

    try:
        source_url = f"https://www.coolbox.pe/supersede-{suffix}/p"
        product = TrackedProductRepository(session).add(
            store_slug="coolbox",
            source_url=source_url,
            label="Producto que mejora antes del envío",
            expected_brand="Acme",
            expected_model="X14",
            expected_variant={"Memoria": "16 GB", "Color": "Negro"},
        )
        observations = PriceObservationRepository(session)

        first_run = CrawlRunRepository(session).start(
            store_slug="coolbox",
            spider_name="phase1_supersede",
            requested_url_count=1,
            started_at=first_at,
        )
        first_saved = observations.save(
            run_id=first_run.id,
            observation=_observation(
                tracked_product_id=product.id,
                source_url=source_url,
                observed_at=first_at,
                price="50.00",
                payload_marker=f"{suffix}-first",
            ),
        )
        DetectionService(session, settings).process_new(limit=1)

        second_at = first_at + timedelta(hours=1)
        second_run = CrawlRunRepository(session).start(
            store_slug="coolbox",
            spider_name="phase1_supersede",
            requested_url_count=1,
            started_at=second_at,
        )
        second_saved = observations.save(
            run_id=second_run.id,
            observation=_observation(
                tracked_product_id=product.id,
                source_url=source_url,
                observed_at=second_at,
                price="30.00",
                payload_marker=f"{suffix}-second",
            ),
        )
        DetectionService(session, settings).process_new(limit=1)

        first_detection = session.scalar(
            select(DealDetection).where(DealDetection.observation_id == first_saved.observation_id)
        )
        second_detection = session.scalar(
            select(DealDetection).where(DealDetection.observation_id == second_saved.observation_id)
        )
        assert first_detection is not None
        assert second_detection is not None
        assert first_detection.notification_status == "superseded"
        assert second_detection.notification_status == "pending"
        assert second_detection.classification == "exceptional_deal"

        deliveries = list(
            session.scalars(
                select(NotificationDelivery)
                .join(
                    DealDetection,
                    DealDetection.id == NotificationDelivery.detection_id,
                )
                .where(DealDetection.tracked_product_id == product.id)
                .order_by(NotificationDelivery.id.asc())
            )
        )
        assert [delivery.status for delivery in deliveries] == [
            "superseded",
            "pending",
        ]
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def test_dispatcher_wires_a_leased_delivery_to_a_configured_channel() -> None:
    engine = create_database_engine(DatabaseSettings.from_env())
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    suffix = uuid4().hex
    observed_at = datetime(2026, 7, 27, 23, 0, tzinfo=UTC)
    channel_name = f"test-{suffix[:12]}"
    sent_notifications: list[OfferNotification] = []

    class FakeChannel:
        enabled = True

        @property
        def channel_name(self) -> str:
            return channel_name

        def send(self, notification: OfferNotification) -> NotificationResult:
            sent_notifications.append(notification)
            return NotificationResult(
                channel=channel_name,
                status=NotificationStatus.SENT,
                message_id="fake-dispatcher-message",
            )

    try:
        source_url = f"https://www.coolbox.pe/dispatcher-{suffix}/p"
        product = TrackedProductRepository(session).add(
            store_slug="coolbox",
            source_url=source_url,
            label="Producto enviado por dispatcher",
            expected_brand="Acme",
            expected_model="X14",
            expected_variant={"Memoria": "16 GB", "Color": "Negro"},
        )
        run = CrawlRunRepository(session).start(
            store_slug="coolbox",
            spider_name="phase1_dispatcher",
            requested_url_count=1,
            started_at=observed_at,
        )
        saved = PriceObservationRepository(session).save(
            run_id=run.id,
            observation=_observation(
                tracked_product_id=product.id,
                source_url=source_url,
                observed_at=observed_at,
                price="40.00",
                payload_marker=suffix,
            ),
        )
        settings = RuntimeSettings(
            detector_version="phase1-v1",
            confirmation_required=False,
            minimum_alert_confidence=0,
            detector_config=DetectorConfig(minimum_history_samples=1),
        )
        DetectionService(session, settings).process_new(limit=1)
        detection = session.scalar(
            select(DealDetection).where(DealDetection.observation_id == saved.observation_id)
        )
        assert detection is not None
        delivery = session.scalar(
            select(NotificationDelivery).where(NotificationDelivery.detection_id == detection.id)
        )
        assert delivery is not None
        delivery.channel = channel_name
        session.flush()

        factory = sessionmaker(
            bind=connection,
            autoflush=False,
            expire_on_commit=False,
        )
        summary = NotificationDispatcher(
            factory,
            settings,
            FakeChannel(),
        ).dispatch_due(limit=1)
        session.expire_all()

        assert summary.configured is True
        assert summary.claimed == 1
        assert summary.sent == 1
        assert len(sent_notifications) == 1
        assert sent_notifications[0].product_name == "Producto enviado por dispatcher"
        assert "Referencia interna" in sent_notifications[0].reason
        assert delivery.status == "sent"
        assert delivery.provider_message_id == "fake-dispatcher-message"
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()
