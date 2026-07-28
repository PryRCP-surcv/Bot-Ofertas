import hashlib
import os
from collections.abc import Sequence
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
from bot_ofertas.storage.models import (
    DealDetection,
    NotificationDelivery,
    OfferConfirmationState,
)
from bot_ofertas.storage.repositories import (
    CrawlRunRepository,
    EquivalentProductRepository,
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

_VARIANT = {"Memoria": "16 GB", "Color": "Negro"}


def _commercial_condition_signature(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"commercial_condition_signature:{digest}"


def _settings() -> RuntimeSettings:
    return RuntimeSettings(
        detector_version="phase3-integration-v1",
        confirmation_required=True,
        confirmation_max_age_minutes=180,
        confirmation_price_tolerance_ratio=Decimal("0.03"),
        confirmation_confidence_bonus=20,
        minimum_alert_confidence=50,
        detector_config=DetectorConfig(
            minimum_history_samples=1,
            minimum_equivalent_samples=2,
        ),
    )


def _save_observation(
    session: Session,
    *,
    product_id: UUID,
    store_slug: str,
    source_url: str,
    observed_at: datetime,
    price: str,
    marker: str,
    external_product_id: str,
    list_price: str = "100.00",
    quality_flags: Sequence[str] = (),
) -> int:
    run = CrawlRunRepository(session).start(
        store_slug=store_slug,
        spider_name=f"phase3_{store_slug}",
        requested_url_count=1,
        started_at=observed_at,
    )
    saved = PriceObservationRepository(session).save(
        run_id=run.id,
        observation=PriceObservation(
            tracked_product_id=product_id,
            store_slug=store_slug,
            source_url=source_url,
            external_product_id=external_product_id,
            product_reference=f"REF-{external_product_id}",
            sku=f"SKU-{external_product_id}",
            sku_reference=f"SKU-REF-{external_product_id}",
            seller_id="1",
            seller_name=store_slug.title(),
            title="Laptop Acme Pro 14 Modelo X14",
            brand="Acme",
            model="X14",
            category_path=["Tecnología", "Computación"],
            variant=_VARIANT,
            condition=ProductCondition.NEW,
            currency="PEN",
            price=Decimal(price),
            list_price=Decimal(list_price),
            availability=Availability.IN_STOCK,
            available_quantity=5,
            is_marketplace=False,
            observed_at=observed_at,
            extractor_version="phase3-integration-v1",
            source_payload_hash=hashlib.sha256(marker.encode()).hexdigest(),
            quality_flags=list(quality_flags),
        ),
    )
    return saved.observation_id


def test_alert_waits_for_a_stable_second_crawl_and_is_reserved_once() -> None:
    engine = create_database_engine(DatabaseSettings.from_env())
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    suffix = uuid4().hex
    settings = _settings()
    baseline_at = datetime.now(UTC) - timedelta(hours=3)

    try:
        source_url = f"https://www.coolbox.pe/phase3-confirm-{suffix}/p"
        product = TrackedProductRepository(session).add(
            store_slug="coolbox",
            source_url=source_url,
            label="Laptop Acme confirmación",
            expected_brand="Acme",
            expected_model="X14",
            expected_variant=_VARIANT,
            check_interval_minutes=60,
        )
        baseline_id = _save_observation(
            session,
            product_id=product.id,
            store_slug="coolbox",
            source_url=source_url,
            observed_at=baseline_at,
            price="100.00",
            marker=f"{suffix}-baseline",
            external_product_id=f"confirm-{suffix}",
        )
        baseline_summary = DetectionService(session, settings).process_new()
        baseline_detection = session.scalar(
            select(DealDetection).where(
                DealDetection.observation_id == baseline_id,
                DealDetection.detector_version == settings.detector_version,
            )
        )
        assert baseline_summary.processed >= 1
        assert baseline_detection is not None
        assert baseline_detection.classification == "none"

        candidate_at = baseline_at + timedelta(hours=1)
        first_candidate_id = _save_observation(
            session,
            product_id=product.id,
            store_slug="coolbox",
            source_url=source_url,
            observed_at=candidate_at,
            price="40.00",
            marker=f"{suffix}-candidate-1",
            external_product_id=f"confirm-{suffix}",
        )
        first_summary = DetectionService(session, settings).process_new()
        first_detection = session.scalar(
            select(DealDetection).where(
                DealDetection.observation_id == first_candidate_id,
                DealDetection.detector_version == settings.detector_version,
            )
        )

        assert first_summary.alert_candidates == 1
        assert first_summary.awaiting_confirmation == 1
        assert first_summary.notifications_reserved == 0
        assert first_detection is not None
        assert first_detection.confirmation_status == "awaiting"
        assert first_detection.confirmation_count == 1
        assert first_detection.notification_status == "awaiting_confirmation"

        confirmed_at = candidate_at + timedelta(hours=1)
        confirmed_observation_id = _save_observation(
            session,
            product_id=product.id,
            store_slug="coolbox",
            source_url=source_url,
            observed_at=confirmed_at,
            price="40.00",
            marker=f"{suffix}-candidate-2",
            external_product_id=f"confirm-{suffix}",
        )
        second_summary = DetectionService(session, settings).process_new()
        second_detection = session.scalar(
            select(DealDetection).where(
                DealDetection.observation_id == confirmed_observation_id,
                DealDetection.detector_version == settings.detector_version,
            )
        )

        assert second_summary.alert_candidates == 1
        assert second_summary.confirmed_candidates == 1
        assert second_summary.notifications_reserved == 1
        assert second_detection is not None
        assert second_detection.confirmation_status == "confirmed"
        assert second_detection.confirmation_count == 2
        assert second_detection.confirmation_observation_id == first_candidate_id
        assert second_detection.notification_status == "pending"
        assert second_detection.confidence_score >= settings.minimum_alert_confidence
        assert first_detection.confirmation_status == "confirmed"
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
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def test_material_price_change_restarts_confirmation_window() -> None:
    engine = create_database_engine(DatabaseSettings.from_env())
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    suffix = uuid4().hex
    settings = _settings()
    baseline_at = datetime.now(UTC) - timedelta(hours=4)

    try:
        source_url = f"https://www.coolbox.pe/phase3-replace-{suffix}/p"
        product = TrackedProductRepository(session).add(
            store_slug="coolbox",
            source_url=source_url,
            label="Laptop Acme reemplazo",
            expected_brand="Acme",
            expected_model="X14",
            expected_variant=_VARIANT,
            check_interval_minutes=60,
        )
        _save_observation(
            session,
            product_id=product.id,
            store_slug="coolbox",
            source_url=source_url,
            observed_at=baseline_at,
            price="100.00",
            marker=f"{suffix}-baseline",
            external_product_id=f"replace-{suffix}",
        )
        DetectionService(session, settings).process_new()

        first_id = _save_observation(
            session,
            product_id=product.id,
            store_slug="coolbox",
            source_url=source_url,
            observed_at=baseline_at + timedelta(hours=1),
            price="40.00",
            marker=f"{suffix}-candidate-1",
            external_product_id=f"replace-{suffix}",
        )
        DetectionService(session, settings).process_new()

        replacement_id = _save_observation(
            session,
            product_id=product.id,
            store_slug="coolbox",
            source_url=source_url,
            observed_at=baseline_at + timedelta(hours=2),
            price="35.00",
            marker=f"{suffix}-candidate-2",
            external_product_id=f"replace-{suffix}",
        )
        replacement_summary = DetectionService(session, settings).process_new()
        first_detection = session.scalar(
            select(DealDetection).where(
                DealDetection.observation_id == first_id,
                DealDetection.detector_version == settings.detector_version,
            )
        )
        replacement_detection = session.scalar(
            select(DealDetection).where(
                DealDetection.observation_id == replacement_id,
                DealDetection.detector_version == settings.detector_version,
            )
        )

        assert replacement_summary.awaiting_confirmation == 1
        assert replacement_summary.notifications_reserved == 0
        assert first_detection is not None
        assert first_detection.confirmation_status == "replaced"
        assert replacement_detection is not None
        assert replacement_detection.confirmation_status == "awaiting"
        assert replacement_detection.confirmation_count == 1

        final_id = _save_observation(
            session,
            product_id=product.id,
            store_slug="coolbox",
            source_url=source_url,
            observed_at=baseline_at + timedelta(hours=3),
            price="35.00",
            marker=f"{suffix}-candidate-3",
            external_product_id=f"replace-{suffix}",
        )
        final_summary = DetectionService(session, settings).process_new()
        final_detection = session.scalar(
            select(DealDetection).where(
                DealDetection.observation_id == final_id,
                DealDetection.detector_version == settings.detector_version,
            )
        )

        assert final_summary.confirmed_candidates == 1
        assert final_summary.notifications_reserved == 1
        assert final_detection is not None
        assert final_detection.confirmation_status == "confirmed"
        assert final_detection.confirmation_observation_id == replacement_id
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def test_verified_cross_store_group_supplies_equivalent_price_signal() -> None:
    engine = create_database_engine(DatabaseSettings.from_env())
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    suffix = uuid4().hex
    settings = _settings()
    reference_at = datetime.now(UTC) - timedelta(hours=2)

    try:
        products = TrackedProductRepository(session)
        tracked = {
            "coolbox": products.add(
                store_slug="coolbox",
                source_url=f"https://www.coolbox.pe/phase3-equivalent-{suffix}/p",
                label="Acme X14 Coolbox",
                expected_brand="Acme",
                expected_model="X14",
                expected_variant=_VARIANT,
                check_interval_minutes=60,
            ),
            "oechsle": products.add(
                store_slug="oechsle",
                source_url=f"https://www.oechsle.pe/phase3-equivalent-{suffix}/p",
                label="Acme X14 Oechsle",
                expected_brand="Acme",
                expected_model="X14",
                expected_variant=_VARIANT,
                check_interval_minutes=60,
            ),
            "promart": products.add(
                store_slug="promart",
                source_url=f"https://www.promart.pe/phase3-equivalent-{suffix}/p",
                label="Acme X14 Promart",
                expected_brand="Acme",
                expected_model="X14",
                expected_variant=_VARIANT,
                check_interval_minutes=60,
            ),
        }
        equivalences = EquivalentProductRepository(session)
        group = equivalences.create_group(
            name=f"Acme X14 16 GB {suffix}",
            brand="Acme",
            model="X14",
            canonical_variant=_VARIANT,
        )
        for product in tracked.values():
            equivalences.add_product(
                group_id=group.id,
                tracked_product_id=product.id,
            )
        duplicate_coolbox = products.add(
            store_slug="coolbox",
            source_url=f"https://www.coolbox.pe/phase3-equivalent-copy-{suffix}/p",
            label="Acme X14 Coolbox duplicado",
            expected_brand="Acme",
            expected_model="X14",
            expected_variant=_VARIANT,
        )
        with pytest.raises(ValueError, match="only one listing per store"):
            equivalences.add_product(
                group_id=group.id,
                tracked_product_id=duplicate_coolbox.id,
            )

        for store_slug, price in (("oechsle", "100.00"), ("promart", "120.00")):
            product = tracked[store_slug]
            _save_observation(
                session,
                product_id=product.id,
                store_slug=store_slug,
                source_url=product.source_url,
                observed_at=reference_at,
                price=price,
                list_price=price,
                marker=f"{suffix}-{store_slug}",
                external_product_id=f"{store_slug}-{suffix}",
            )
        DetectionService(session, settings).process_new(limit=10)

        candidate_id = _save_observation(
            session,
            product_id=tracked["coolbox"].id,
            store_slug="coolbox",
            source_url=tracked["coolbox"].source_url,
            observed_at=reference_at + timedelta(hours=1),
            price="50.00",
            list_price="50.00",
            marker=f"{suffix}-coolbox",
            external_product_id=f"coolbox-{suffix}",
        )
        summary = DetectionService(session, settings).process_new(limit=10)
        detection = session.scalar(
            select(DealDetection).where(
                DealDetection.observation_id == candidate_id,
                DealDetection.detector_version == settings.detector_version,
            )
        )
        confirmation_state = session.scalar(
            select(OfferConfirmationState).where(
                OfferConfirmationState.tracked_product_id == tracked["coolbox"].id
            )
        )

        assert summary.alert_candidates == 1
        assert summary.awaiting_confirmation == 1
        assert detection is not None
        assert detection.equivalent_median_price == Decimal("110.0000")
        assert detection.drop_from_equivalent_pct > Decimal("50")
        assert "equivalent_median:exceptional_deal" in detection.reasons
        assert confirmation_state is not None
        assert confirmation_state.confirmation_count == 1
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def test_confirmation_and_deduplication_keep_commercial_conditions_separate() -> None:
    engine = create_database_engine(DatabaseSettings.from_env())
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    suffix = uuid4().hex
    settings = RuntimeSettings(
        detector_version="phase3-conditioned-test-v1",
        confirmation_required=True,
        confirmation_max_age_minutes=240,
        minimum_alert_confidence=50,
        detector_config=DetectorConfig(minimum_history_samples=1),
    )
    baseline_at = datetime.now(UTC) - timedelta(hours=5)
    card_oh_signature = _commercial_condition_signature("tarjeta-oh")
    other_card_signature = _commercial_condition_signature("tarjeta-distinta")
    coupon_signature = _commercial_condition_signature("cupon-oferta-40")

    try:
        source_url = f"https://www.coolbox.pe/phase3-conditioned-{suffix}/p"
        product = TrackedProductRepository(session).add(
            store_slug="coolbox",
            source_url=source_url,
            label="Laptop Acme con condiciones",
            expected_brand="Acme",
            expected_model="X14",
            expected_variant=_VARIANT,
            check_interval_minutes=60,
        )
        _save_observation(
            session,
            product_id=product.id,
            store_slug="coolbox",
            source_url=source_url,
            observed_at=baseline_at,
            price="100.00",
            marker=f"{suffix}-baseline",
            external_product_id=f"conditioned-{suffix}",
        )
        DetectionService(session, settings).process_new(limit=100)

        card_observation_id = _save_observation(
            session,
            product_id=product.id,
            store_slug="coolbox",
            source_url=source_url,
            observed_at=baseline_at + timedelta(hours=1),
            price="40.00",
            marker=f"{suffix}-card-1",
            external_product_id=f"conditioned-{suffix}",
            quality_flags=(
                "payment_method_price",
                "conditional_promotion_price",
                card_oh_signature,
            ),
        )
        card_summary = DetectionService(session, settings).process_new()
        card_detection = session.scalar(
            select(DealDetection).where(
                DealDetection.observation_id == card_observation_id,
                DealDetection.detector_version == settings.detector_version,
            )
        )

        assert card_summary.awaiting_confirmation == 1
        assert card_detection is not None
        assert card_detection.eligible is True
        assert card_detection.classification == "exceptional_deal"
        assert card_detection.confirmation_status == "awaiting"

        other_card_observation_id = _save_observation(
            session,
            product_id=product.id,
            store_slug="coolbox",
            source_url=source_url,
            observed_at=baseline_at + timedelta(hours=2),
            price="40.00",
            marker=f"{suffix}-other-card-1",
            external_product_id=f"conditioned-{suffix}",
            quality_flags=(
                "payment_method_price",
                "conditional_promotion_price",
                other_card_signature,
            ),
        )
        other_card_summary = DetectionService(session, settings).process_new()
        other_card_detection = session.scalar(
            select(DealDetection).where(
                DealDetection.observation_id == other_card_observation_id,
                DealDetection.detector_version == settings.detector_version,
            )
        )

        assert other_card_summary.awaiting_confirmation == 1
        assert other_card_summary.confirmed_candidates == 0
        assert other_card_summary.notifications_reserved == 0
        assert other_card_detection is not None
        assert other_card_detection.confirmation_status == "awaiting"

        coupon_observation_id = _save_observation(
            session,
            product_id=product.id,
            store_slug="coolbox",
            source_url=source_url,
            observed_at=baseline_at + timedelta(hours=3),
            price="40.00",
            marker=f"{suffix}-coupon-1",
            external_product_id=f"conditioned-{suffix}",
            quality_flags=(
                "coupon_price",
                "conditional_promotion_price",
                coupon_signature,
            ),
        )
        coupon_summary = DetectionService(session, settings).process_new()
        coupon_detection = session.scalar(
            select(DealDetection).where(
                DealDetection.observation_id == coupon_observation_id,
                DealDetection.detector_version == settings.detector_version,
            )
        )

        assert coupon_summary.awaiting_confirmation == 1
        assert coupon_summary.confirmed_candidates == 0
        assert coupon_summary.notifications_reserved == 0
        assert coupon_detection is not None
        assert coupon_detection.confirmation_status == "awaiting"

        confirmed_card_id = _save_observation(
            session,
            product_id=product.id,
            store_slug="coolbox",
            source_url=source_url,
            observed_at=baseline_at + timedelta(hours=4),
            price="40.00",
            marker=f"{suffix}-card-2",
            external_product_id=f"conditioned-{suffix}",
            quality_flags=(
                "payment_method_price",
                "conditional_promotion_price",
                card_oh_signature,
            ),
        )
        confirmation_summary = DetectionService(session, settings).process_new()
        confirmed_card = session.scalar(
            select(DealDetection).where(
                DealDetection.observation_id == confirmed_card_id,
                DealDetection.detector_version == settings.detector_version,
            )
        )

        assert confirmation_summary.confirmed_candidates == 1
        assert confirmation_summary.notifications_reserved == 1
        assert confirmed_card is not None
        assert confirmed_card.confirmation_status == "confirmed"
        assert confirmed_card.confirmation_observation_id == card_observation_id
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
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()
