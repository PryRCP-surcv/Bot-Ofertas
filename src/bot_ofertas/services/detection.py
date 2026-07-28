"""Application service for evaluating newly persisted observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.orm import Session

from bot_ofertas.detection import (
    DealClassification,
    DealDetector,
    ExpectedProductContext,
    canonicalize_variant,
)
from bot_ofertas.domain import PriceObservation
from bot_ofertas.runtime_config import RuntimeSettings
from bot_ofertas.storage.detections import DetectionRepository
from bot_ofertas.storage.models import PriceObservationRecord, TrackedProduct


@dataclass(frozen=True, slots=True)
class DetectionBatchSummary:
    processed: int = 0
    processing_errors: int = 0
    rejected: int = 0
    no_deal: int = 0
    alert_candidates: int = 0
    notifications_reserved: int = 0
    duplicates_suppressed: int = 0


class DetectionService:
    """Run the pure detector and persist every decision atomically."""

    def __init__(
        self,
        session: Session,
        settings: RuntimeSettings,
        detector: DealDetector | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._detector = detector or DealDetector(settings.detector_config)

    def process_new(self, *, limit: int = 100) -> DetectionBatchSummary:
        repository = DetectionRepository(self._session)
        observations = repository.unprocessed_observations(limit=limit)
        counters = {
            "processed": 0,
            "processing_errors": 0,
            "rejected": 0,
            "no_deal": 0,
            "alert_candidates": 0,
            "notifications_reserved": 0,
            "duplicates_suppressed": 0,
        }
        for record in observations:
            try:
                with self._session.begin_nested():
                    tracked_product = repository.tracked_product(record)
                    history_records = repository.history_before(
                        record,
                        limit=self._settings.detection_history_limit,
                    )
                    current = _domain_observation(record)
                    history = [_domain_observation(item) for item in history_records]
                    decision = self._detector.evaluate(
                        current,
                        history,
                        expected=_expected_context(record, tracked_product),
                    )
                    if decision.is_valid:
                        _learn_first_variant(tracked_product, record)
                    result = repository.save(
                        observation=record,
                        decision=decision,
                        cooldown=timedelta(
                            hours=self._settings.alert_cooldown_hours
                        ),
                        significant_improvement_ratio=(
                            self._settings.alert_significant_improvement_ratio
                        ),
                        allow_notification=repository.is_latest_snapshot(record),
                    )
            except Exception as error:
                with self._session.begin_nested():
                    result = repository.save_processing_error(
                        observation=record,
                        error_type=type(error).__name__,
                    )
                if result.inserted:
                    counters["processed"] += 1
                    counters["processing_errors"] += 1
                continue
            if not result.inserted:
                continue
            counters["processed"] += 1
            if not decision.is_valid:
                counters["rejected"] += 1
            elif decision.classification is DealClassification.NONE:
                counters["no_deal"] += 1
            else:
                counters["alert_candidates"] += 1
                if result.notification_reserved:
                    counters["notifications_reserved"] += 1
                else:
                    counters["duplicates_suppressed"] += 1
        return DetectionBatchSummary(**counters)


def _learn_first_variant(
    tracked_product: TrackedProduct | None,
    observation: PriceObservationRecord,
) -> None:
    if (
        tracked_product is not None
        and not tracked_product.expected_variant
        and observation.variant
    ):
        tracked_product.expected_variant = canonicalize_variant(observation.variant)


def _expected_context(
    observation: PriceObservationRecord,
    tracked_product: TrackedProduct | None,
) -> ExpectedProductContext:
    return ExpectedProductContext(
        store_slug=observation.store_slug,
        external_product_id=observation.external_product_id,
        sku=observation.sku,
        seller_id=observation.seller_id,
        brand=tracked_product.expected_brand if tracked_product is not None else None,
        model=tracked_product.expected_model if tracked_product is not None else None,
        variant=(
            dict(tracked_product.expected_variant)
            if tracked_product is not None
            else {}
        ),
        expected_is_accessory=(
            tracked_product.expected_is_accessory
            if tracked_product is not None
            else False
        ),
    )


def _domain_observation(record: PriceObservationRecord) -> PriceObservation:
    return PriceObservation(
        tracked_product_id=record.tracked_product_id,
        store_slug=record.store_slug,
        source_url=record.source_url,
        external_product_id=record.external_product_id,
        product_reference=record.product_reference,
        sku=record.sku,
        sku_reference=record.sku_reference,
        seller_id=record.seller_id,
        seller_name=record.seller_name,
        title=record.title,
        brand=record.brand,
        model=record.model,
        category_path=list(record.category_path),
        variant=dict(record.variant),
        condition=record.condition,
        currency=record.currency,
        price=record.price,
        list_price=record.list_price,
        availability=record.availability,
        available_quantity=record.available_quantity,
        is_marketplace=record.is_marketplace,
        installments=list(record.installments),
        observed_at=record.observed_at,
        extractor_version=record.extractor_version,
        source_payload_hash=record.source_payload_hash,
        quality_flags=list(record.quality_flags),
    )


__all__ = [
    "DetectionBatchSummary",
    "DetectionService",
]
