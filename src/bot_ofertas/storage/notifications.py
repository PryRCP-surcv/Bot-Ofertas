"""Durable leasing and retry state for external notification deliveries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from bot_ofertas.storage.models import (
    DealDetection,
    NotificationDelivery,
    PriceObservationRecord,
    TrackedProduct,
)


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


def _safe_text(value: str | None, *, maximum: int) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    return normalized[:maximum] or None


def _condition_flags(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()

    flags: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        normalized = item.strip().casefold()
        if normalized and normalized not in flags:
            flags.append(normalized)
    return tuple(flags)


@dataclass(frozen=True, slots=True)
class NotificationClaim:
    delivery_id: int
    lease_token: UUID
    detection_id: int
    classification: str
    product_name: str
    current_price: Decimal
    currency: str
    reason_codes: tuple[str, ...]
    product_url: str
    comparison_price: Decimal | None
    discount_percent: Decimal | None
    comparison_label: str
    store_slug: str
    confidence_score: int
    confirmation_count: int
    condition_flags: tuple[str, ...] = ()


class NotificationDeliveryRepository:
    """Reserve provider calls without holding a database transaction open."""

    MAX_CLAIM_SIZE = 100
    MAX_LEASE_DURATION = timedelta(hours=1)

    def __init__(self, session: Session) -> None:
        self._session = session

    def claim_due(
        self,
        *,
        channel: str,
        limit: int = 20,
        max_attempts: int = 5,
        lease_duration: timedelta = timedelta(minutes=2),
        now: datetime | None = None,
    ) -> list[NotificationClaim]:
        if limit <= 0 or limit > self.MAX_CLAIM_SIZE:
            raise ValueError(f"limit must be between 1 and {self.MAX_CLAIM_SIZE}")
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if lease_duration <= timedelta(0) or lease_duration > self.MAX_LEASE_DURATION:
            raise ValueError("lease_duration must be positive and at most one hour")
        normalized_channel = channel.strip().lower()
        if not normalized_channel:
            raise ValueError("channel must not be empty")

        timestamp = _timestamp(self._session, now)
        self._expire_exhausted(
            channel=normalized_channel,
            max_attempts=max_attempts,
            now=timestamp,
        )
        token = uuid4()
        statement: Select[
            tuple[
                NotificationDelivery,
                DealDetection,
                PriceObservationRecord,
                str | None,
            ]
        ] = (
            select(
                NotificationDelivery,
                DealDetection,
                PriceObservationRecord,
                TrackedProduct.label,
            )
            .join(
                DealDetection,
                DealDetection.id == NotificationDelivery.detection_id,
            )
            .join(
                PriceObservationRecord,
                PriceObservationRecord.id == DealDetection.observation_id,
            )
            .outerjoin(
                TrackedProduct,
                TrackedProduct.id == DealDetection.tracked_product_id,
            )
            .where(
                NotificationDelivery.channel == normalized_channel,
                NotificationDelivery.status.in_(("pending", "retrying")),
                NotificationDelivery.next_attempt_at <= timestamp,
                NotificationDelivery.attempt_count < max_attempts,
                or_(
                    NotificationDelivery.lease_token.is_(None),
                    NotificationDelivery.lease_expires_at <= timestamp,
                ),
            )
            .order_by(
                NotificationDelivery.next_attempt_at.asc(),
                NotificationDelivery.id.asc(),
            )
            .limit(limit)
            .with_for_update(of=NotificationDelivery, skip_locked=True)
        )
        rows = self._session.execute(statement).all()
        claims: list[NotificationClaim] = []
        for delivery, detection, observation, tracked_label in rows:
            if detection.current_price is None:
                delivery.status = "failed"
                delivery.last_error_code = "missing_current_price"
                delivery.last_error = "La alerta no tiene un precio actual utilizable."
                detection.notification_status = "failed"
                continue

            delivery.lease_token = token
            delivery.lease_expires_at = timestamp + lease_duration
            delivery.attempt_count += 1
            comparison_label, discount = _comparison(detection)
            claims.append(
                NotificationClaim(
                    delivery_id=delivery.id,
                    lease_token=token,
                    detection_id=detection.id,
                    classification=detection.classification,
                    product_name=tracked_label or observation.title,
                    current_price=detection.current_price,
                    currency=observation.currency,
                    reason_codes=tuple(detection.reasons),
                    product_url=observation.source_url,
                    comparison_price=detection.reference_price,
                    discount_percent=discount,
                    comparison_label=comparison_label,
                    store_slug=observation.store_slug,
                    confidence_score=detection.confidence_score,
                    confirmation_count=detection.confirmation_count,
                    condition_flags=_condition_flags(observation.quality_flags),
                )
            )
        self._session.flush()
        return claims

    def complete(
        self,
        *,
        delivery_id: int,
        lease_token: UUID,
        sent: bool,
        max_attempts: int,
        retry_base_seconds: int,
        retryable: bool = True,
        retry_after_seconds: int | None = None,
        provider_message_id: str | None = None,
        error_code: str | None = None,
        error_detail: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if retry_base_seconds <= 0:
            raise ValueError("retry_base_seconds must be positive")
        if not isinstance(retryable, bool):
            raise TypeError("retryable must be a boolean")
        if retry_after_seconds is not None and retry_after_seconds <= 0:
            raise ValueError("retry_after_seconds must be positive")
        timestamp = _timestamp(self._session, now)
        delivery = self._session.scalar(
            select(NotificationDelivery)
            .where(
                NotificationDelivery.id == delivery_id,
                NotificationDelivery.lease_token == lease_token,
            )
            .with_for_update()
        )
        if delivery is None:
            return False
        detection = self._session.get(DealDetection, delivery.detection_id)
        if detection is None:  # pragma: no cover - protected by the foreign key
            raise RuntimeError("delivery detection no longer exists")

        delivery.lease_token = None
        delivery.lease_expires_at = None
        delivery.updated_at = timestamp
        if sent:
            delivery.status = "sent"
            delivery.provider_message_id = _safe_text(
                provider_message_id,
                maximum=300,
            )
            delivery.last_error_code = None
            delivery.last_error = None
            delivery.sent_at = timestamp
            detection.notification_status = "sent"
            detection.notified_at = timestamp
        else:
            exhausted = not retryable or delivery.attempt_count >= max_attempts
            delivery.status = "failed" if exhausted else "retrying"
            delivery.last_error_code = _safe_text(error_code, maximum=100)
            delivery.last_error = _safe_text(error_detail, maximum=500)
            if not exhausted:
                if retry_after_seconds is not None:
                    retry_seconds = min(retry_after_seconds, 86_400)
                else:
                    exponent = min(max(delivery.attempt_count - 1, 0), 8)
                    retry_seconds = min(
                        retry_base_seconds * (2**exponent),
                        86_400,
                    )
                delivery.next_attempt_at = timestamp + timedelta(seconds=retry_seconds)
            detection.notification_status = "failed" if exhausted else "retrying"
        self._session.flush()
        return True

    def _expire_exhausted(
        self,
        *,
        channel: str,
        max_attempts: int,
        now: datetime,
    ) -> int:
        rows = self._session.execute(
            select(NotificationDelivery, DealDetection)
            .join(
                DealDetection,
                DealDetection.id == NotificationDelivery.detection_id,
            )
            .where(
                NotificationDelivery.channel == channel,
                NotificationDelivery.status.in_(("pending", "retrying")),
                NotificationDelivery.attempt_count >= max_attempts,
                or_(
                    NotificationDelivery.lease_token.is_(None),
                    NotificationDelivery.lease_expires_at <= now,
                ),
            )
            .with_for_update(of=NotificationDelivery, skip_locked=True)
        ).all()
        for delivery, detection in rows:
            delivery.status = "failed"
            delivery.lease_token = None
            delivery.lease_expires_at = None
            delivery.last_error_code = delivery.last_error_code or "attempts_exhausted"
            delivery.last_error = (
                delivery.last_error or "La entrega agotó sus intentos después de perder un lease."
            )
            delivery.updated_at = now
            detection.notification_status = "failed"
        self._session.flush()
        return len(rows)

    def release(
        self,
        *,
        delivery_id: int,
        lease_token: UUID,
    ) -> bool:
        delivery = self._session.scalar(
            select(NotificationDelivery)
            .where(
                NotificationDelivery.id == delivery_id,
                NotificationDelivery.lease_token == lease_token,
            )
            .with_for_update()
        )
        if delivery is None:
            return False
        delivery.lease_token = None
        delivery.lease_expires_at = None
        delivery.attempt_count = max(0, delivery.attempt_count - 1)
        self._session.flush()
        return True


def _comparison(detection: DealDetection) -> tuple[str, Decimal | None]:
    signal_metrics = detection.metrics.get("signals", {})
    if not isinstance(signal_metrics, dict):
        return "Precio de referencia", None
    labels = (
        ("previous_price", "Precio anterior"),
        ("median_7d", "Mediana de 7 días"),
        ("median_30d", "Mediana de 30 días"),
        ("historical_median", "Mediana de 90 días"),
        ("equivalent_median", "Mediana de productos equivalentes"),
        ("historical_minimum", "Mínimo histórico"),
        ("list_price", "Precio de lista"),
    )
    primary_signal = detection.metrics.get("primary_signal_kind")
    if isinstance(primary_signal, str):
        labels = tuple(
            (signal_name, label) for signal_name, label in labels if signal_name == primary_signal
        ) + tuple(
            (signal_name, label) for signal_name, label in labels if signal_name != primary_signal
        )
    best_label = "Precio de referencia"
    best_discount: Decimal | None = None
    for signal_name, label in labels:
        raw_signal = signal_metrics.get(signal_name)
        if not isinstance(raw_signal, dict):
            continue
        raw_reference = raw_signal.get("reference_price")
        if raw_reference is None or (
            detection.reference_price is not None
            and Decimal(str(raw_reference)) != detection.reference_price
        ):
            continue
        raw_discount = raw_signal.get("discount_percent")
        best_label = label
        best_discount = Decimal(str(raw_discount)) if raw_discount is not None else None
        break
    return best_label, best_discount


__all__ = [
    "NotificationClaim",
    "NotificationDeliveryRepository",
]
