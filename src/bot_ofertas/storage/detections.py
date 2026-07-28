"""Persistence and deduplication for pure deal-detector decisions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from bot_ofertas.detection import (
    DealClassification,
    DetectionDecision,
    SignalAssessment,
    SignalKind,
    canonicalize_variant,
)
from bot_ofertas.domain import Availability
from bot_ofertas.storage.models import (
    DealDetection,
    NotificationDelivery,
    OfferAlertState,
    PriceObservationRecord,
    TrackedProduct,
)

_CLASSIFICATION_RANK = {
    DealClassification.NONE.value: 0,
    DealClassification.GOOD_DEAL.value: 1,
    DealClassification.EXCEPTIONAL_DEAL.value: 2,
    DealClassification.POSSIBLE_PRICE_ERROR.value: 3,
}
_CLASSIFICATION_SCORE = {
    DealClassification.NONE.value: 0,
    DealClassification.GOOD_DEAL.value: 55,
    DealClassification.EXCEPTIONAL_DEAL.value: 80,
    DealClassification.POSSIBLE_PRICE_ERROR.value: 95,
}


def _utc(value: datetime | None = None) -> datetime:
    resolved = value or datetime.now(UTC)
    if resolved.tzinfo is None or resolved.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return resolved.astimezone(UTC)


def _timestamp(session: Session, value: datetime | None) -> datetime:
    if value is not None:
        return _utc(value)
    timestamp = session.scalar(select(func.clock_timestamp()))
    if timestamp is None:  # pragma: no cover - PostgreSQL always returns a value
        raise RuntimeError("database clock did not return a timestamp")
    return _utc(timestamp)


def _decimal_text(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _signal_metrics(signal: SignalAssessment) -> dict[str, Any]:
    return {
        "eligible": signal.eligible,
        "reference_price": _decimal_text(signal.reference_price),
        "discount_ratio": _decimal_text(signal.discount_ratio),
        "discount_percent": _decimal_text(signal.discount_percent),
        "classification": signal.classification.value,
        "sample_count": signal.sample_count,
    }


def _positive_discount(signal: SignalAssessment) -> Decimal | None:
    discount = signal.discount_percent
    return discount if discount is not None and discount > 0 else None


def _offer_key(observation: PriceObservationRecord) -> str:
    identity = {
        "tracked_product_id": str(observation.tracked_product_id or ""),
        "store_slug": observation.store_slug,
        "external_product_id": observation.external_product_id,
        "sku": observation.sku,
        "seller_id": observation.seller_id,
        "variant": sorted(canonicalize_variant(observation.variant).items()),
        "condition": observation.condition.value,
        "currency": observation.currency,
    }
    encoded = json.dumps(
        identity,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _signal(
    decision: DetectionDecision,
    kind: SignalKind,
) -> SignalAssessment:
    return next(signal for signal in decision.signals if signal.kind is kind)


def _primary_signal(decision: DetectionDecision) -> SignalAssessment | None:
    eligible = [
        signal
        for signal in decision.signals
        if signal.eligible and signal.reference_price is not None
    ]
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda item: (
            _CLASSIFICATION_RANK[item.classification.value],
            (
                item.discount_ratio
                if item.discount_ratio is not None
                else Decimal("-1")
            ),
        ),
    )


def _score(decision: DetectionDecision) -> int:
    base = _CLASSIFICATION_SCORE[decision.classification.value]
    supporting_signals = sum(
        1
        for signal in decision.signals
        if signal.classification is not DealClassification.NONE
    )
    return min(100, base + max(0, supporting_signals - 1) * 2)


@dataclass(frozen=True, slots=True)
class DetectionSaveResult:
    detection: DealDetection
    inserted: bool
    notification_reserved: bool


class DetectionRepository:
    """Claim observations, persist decisions, and serialize alert deduplication."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def unprocessed_observations(self, *, limit: int = 100) -> list[PriceObservationRecord]:
        if limit <= 0 or limit > 1_000:
            raise ValueError("limit must be between 1 and 1000")
        statement: Select[tuple[PriceObservationRecord]] = (
            select(PriceObservationRecord)
            .where(
                ~exists(
                    select(DealDetection.id).where(
                        DealDetection.observation_id == PriceObservationRecord.id
                    )
                )
            )
            .order_by(
                PriceObservationRecord.observed_at.asc(),
                PriceObservationRecord.id.asc(),
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(self._session.scalars(statement))

    def history_before(
        self,
        observation: PriceObservationRecord,
        *,
        limit: int = 90,
    ) -> list[PriceObservationRecord]:
        if limit <= 0 or limit > 1_000:
            raise ValueError("limit must be between 1 and 1000")
        if observation.tracked_product_id is None:
            return []
        statement = (
            select(PriceObservationRecord)
            .where(
                PriceObservationRecord.tracked_product_id
                == observation.tracked_product_id,
                PriceObservationRecord.store_slug == observation.store_slug,
                PriceObservationRecord.external_product_id
                == observation.external_product_id,
                PriceObservationRecord.sku == observation.sku,
                PriceObservationRecord.seller_id == observation.seller_id,
                PriceObservationRecord.condition == observation.condition,
                PriceObservationRecord.currency == observation.currency,
                PriceObservationRecord.observed_at < observation.observed_at,
                PriceObservationRecord.price.is_not(None),
                PriceObservationRecord.price > 0,
                PriceObservationRecord.availability == Availability.IN_STOCK,
                PriceObservationRecord.is_marketplace.is_(False),
                PriceObservationRecord.quality_flags == [],
            )
            .order_by(
                PriceObservationRecord.observed_at.desc(),
                PriceObservationRecord.id.desc(),
            )
            .limit(min(limit * 4, 1_000))
        )
        expected_variant = canonicalize_variant(observation.variant)
        history: list[PriceObservationRecord] = []
        for item in self._session.scalars(statement):
            try:
                comparable_variant = canonicalize_variant(item.variant)
            except ValueError:
                continue
            if comparable_variant == expected_variant:
                history.append(item)
            if len(history) == limit:
                break
        history.reverse()
        return history

    def tracked_product(
        self,
        observation: PriceObservationRecord,
    ) -> TrackedProduct | None:
        if observation.tracked_product_id is None:
            return None
        return self._session.scalar(
            select(TrackedProduct)
            .where(TrackedProduct.id == observation.tracked_product_id)
            .with_for_update()
        )

    def is_latest_snapshot(self, observation: PriceObservationRecord) -> bool:
        """Return whether no newer crawl snapshot exists for the tracked URL."""

        if observation.tracked_product_id is None:
            return False
        newer_id = self._session.scalar(
            select(PriceObservationRecord.id)
            .where(
                PriceObservationRecord.tracked_product_id
                == observation.tracked_product_id,
                PriceObservationRecord.observed_at > observation.observed_at,
            )
            .limit(1)
        )
        return newer_id is None

    def save(
        self,
        *,
        observation: PriceObservationRecord,
        decision: DetectionDecision,
        cooldown: timedelta,
        significant_improvement_ratio: Decimal,
        channel: str = "telegram",
        allow_notification: bool = True,
        detected_at: datetime | None = None,
    ) -> DetectionSaveResult:
        if cooldown <= timedelta(0):
            raise ValueError("cooldown must be positive")
        if not Decimal("0") <= significant_improvement_ratio < Decimal("1"):
            raise ValueError("significant_improvement_ratio must be between 0 and 1")
        normalized_channel = channel.strip().lower()
        if not normalized_channel:
            raise ValueError("channel must not be empty")
        timestamp = _timestamp(self._session, detected_at)

        existing = self._session.scalar(
            select(DealDetection).where(
                DealDetection.observation_id == observation.id
            )
        )
        if existing is not None:
            return DetectionSaveResult(
                detection=existing,
                inserted=False,
                notification_reserved=existing.notification_status == "pending",
            )

        offer_key = _offer_key(observation)
        should_notify = False
        if decision.should_alert and allow_notification:
            self._session.execute(
                insert(OfferAlertState)
                .values(
                    offer_key=offer_key,
                    channel=normalized_channel,
                    tracked_product_id=observation.tracked_product_id,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        OfferAlertState.offer_key,
                        OfferAlertState.channel,
                    ]
                )
            )
            state = self._session.scalar(
                select(OfferAlertState)
                .where(
                    OfferAlertState.offer_key == offer_key,
                    OfferAlertState.channel == normalized_channel,
                )
                .with_for_update()
            )
            if state is None:  # pragma: no cover - insert/select share one transaction
                raise RuntimeError("alert state could not be acquired")

            cooldown_expired = (
                state.last_reserved_at is None
                or state.last_reserved_at <= timestamp - cooldown
            )
            severity_increased = _CLASSIFICATION_RANK[
                decision.classification.value
            ] > _CLASSIFICATION_RANK.get(state.last_classification or "none", 0)
            price_improved = (
                observation.price is not None
                and state.last_price is not None
                and observation.price
                <= state.last_price * (Decimal("1") - significant_improvement_ratio)
            )
            active_deliveries = self._session.execute(
                select(DealDetection, NotificationDelivery)
                .join(
                    NotificationDelivery,
                    NotificationDelivery.detection_id == DealDetection.id,
                )
                .where(
                    DealDetection.offer_key == offer_key,
                    NotificationDelivery.channel == normalized_channel,
                    NotificationDelivery.status.in_(("pending", "retrying")),
                )
                .with_for_update(of=NotificationDelivery)
            ).all()
            has_leased_delivery = any(
                delivery.lease_token is not None
                and delivery.lease_expires_at is not None
                and delivery.lease_expires_at > timestamp
                for _detection, delivery in active_deliveries
            )
            improved_candidate = severity_increased or price_improved
            if active_deliveries:
                should_notify = improved_candidate and not has_leased_delivery
                if should_notify:
                    for previous_detection, delivery in active_deliveries:
                        previous_detection.notification_status = "superseded"
                        delivery.status = "superseded"
                        delivery.lease_token = None
                        delivery.lease_expires_at = None
                        delivery.updated_at = timestamp
            else:
                should_notify = cooldown_expired or improved_candidate
            if should_notify:
                state.last_classification = decision.classification.value
                state.last_price = observation.price
                state.last_reserved_at = timestamp
                state.updated_at = timestamp

        primary = _primary_signal(decision)
        previous = _signal(decision, SignalKind.PREVIOUS_PRICE)
        median = _signal(decision, SignalKind.HISTORICAL_MEDIAN)
        historical_minimum = _signal(decision, SignalKind.HISTORICAL_MINIMUM)
        list_price = _signal(decision, SignalKind.LIST_PRICE)
        notification_status = (
            "pending"
            if should_notify
            else "suppressed"
            if decision.should_alert
            else "not_applicable"
        )
        reasons = [
            f"{signal.kind.value}:{signal.classification.value}"
            for signal in decision.signals
            if signal.classification is not DealClassification.NONE
        ]
        detection = DealDetection(
            observation_id=observation.id,
            tracked_product_id=observation.tracked_product_id,
            offer_key=offer_key,
            classification=decision.classification.value,
            eligible=decision.is_valid,
            score=_score(decision),
            current_price=decision.current_price,
            reference_price=primary.reference_price if primary is not None else None,
            previous_price=previous.reference_price,
            median_price=median.reference_price,
            historical_min_price=historical_minimum.reference_price,
            drop_from_previous_pct=_positive_discount(previous),
            drop_from_median_pct=_positive_discount(median),
            list_discount_pct=_positive_discount(list_price),
            reasons=reasons,
            rejection_reasons=[reason.value for reason in decision.rejection_reasons],
            metrics={
                "history_samples_used": decision.history_samples_used,
                "history_samples_ignored": decision.history_samples_ignored,
                "primary_signal_kind": (
                    primary.kind.value if primary is not None else None
                ),
                "signals": {
                    signal.kind.value: _signal_metrics(signal)
                    for signal in decision.signals
                },
            },
            notification_status=notification_status,
            detected_at=timestamp,
        )
        self._session.add(detection)
        self._session.flush()
        if should_notify:
            self._session.add(
                NotificationDelivery(
                    detection_id=detection.id,
                    channel=normalized_channel,
                    status="pending",
                    next_attempt_at=timestamp,
                )
            )
            self._session.flush()
        return DetectionSaveResult(
            detection=detection,
            inserted=True,
            notification_reserved=should_notify,
        )

    def save_processing_error(
        self,
        *,
        observation: PriceObservationRecord,
        error_type: str,
        detected_at: datetime | None = None,
    ) -> DetectionSaveResult:
        """Dead-letter one malformed observation without persisting error details."""

        existing = self._session.scalar(
            select(DealDetection).where(
                DealDetection.observation_id == observation.id
            )
        )
        if existing is not None:
            return DetectionSaveResult(
                detection=existing,
                inserted=False,
                notification_reserved=False,
            )
        timestamp = _timestamp(self._session, detected_at)
        safe_error_type = "".join(
            character
            for character in error_type.strip()
            if character.isalnum() or character in {"_", "."}
        )[:100] or "unknown"
        error_key = hashlib.sha256(
            f"processing-error:{observation.id}".encode()
        ).hexdigest()
        detection = DealDetection(
            observation_id=observation.id,
            tracked_product_id=observation.tracked_product_id,
            offer_key=error_key,
            classification=DealClassification.NONE.value,
            eligible=False,
            score=0,
            current_price=None,
            reference_price=None,
            reasons=[],
            rejection_reasons=["processing_error"],
            metrics={"processing_error_type": safe_error_type},
            notification_status="not_applicable",
            detected_at=timestamp,
        )
        self._session.add(detection)
        self._session.flush()
        return DetectionSaveResult(
            detection=detection,
            inserted=True,
            notification_reserved=False,
        )

    def recent(self, *, limit: int = 50, alerts_only: bool = False) -> list[DealDetection]:
        if limit <= 0 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        statement = select(DealDetection)
        if alerts_only:
            statement = statement.where(
                DealDetection.classification != DealClassification.NONE.value
            )
        statement = statement.order_by(
            DealDetection.detected_at.desc(),
            DealDetection.id.desc(),
        ).limit(limit)
        return list(self._session.scalars(statement))


__all__ = [
    "DetectionRepository",
    "DetectionSaveResult",
]
