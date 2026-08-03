"""Durable leasing and retry state for external notification deliveries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from bot_ofertas.catalog_balance import BalanceEntry, balanced_indices, catalog_category
from bot_ofertas.detection import canonicalize_variant
from bot_ofertas.domain import Availability
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


def _variant_summary(
    session: Session,
    observation: PriceObservationRecord,
) -> str | None:
    """Summarize exact sibling variants sharing the representative offer."""

    if observation.tracked_product_id is None:
        return None
    statement = select(PriceObservationRecord.variant).where(
        PriceObservationRecord.run_id == observation.run_id,
        PriceObservationRecord.tracked_product_id == observation.tracked_product_id,
        PriceObservationRecord.external_product_id == observation.external_product_id,
        PriceObservationRecord.seller_id == observation.seller_id,
        PriceObservationRecord.condition == observation.condition,
        PriceObservationRecord.currency == observation.currency,
        PriceObservationRecord.price == observation.price,
        PriceObservationRecord.list_price == observation.list_price,
        PriceObservationRecord.availability == Availability.IN_STOCK,
        PriceObservationRecord.is_marketplace.is_(False),
        PriceObservationRecord.quality_flags == observation.quality_flags,
    )
    variants: set[tuple[tuple[str, str], ...]] = set()
    for raw_variant in session.scalars(statement):
        try:
            canonical = canonicalize_variant(raw_variant)
        except ValueError:
            continue
        if canonical:
            variants.add(tuple(sorted(canonical.items())))
    if len(variants) <= 1:
        return None

    ordered = sorted(variants)
    keys = {tuple(key for key, _value in variant) for variant in ordered}
    if len(keys) == 1 and len(next(iter(keys))) == 1:
        key = next(iter(keys))[0]
        values = sorted({variant[0][1] for variant in ordered})
        visible = values[:12]
        suffix = f" y {len(values) - len(visible)} más" if len(values) > len(visible) else ""
        label = "Tallas disponibles" if key in {"talla", "size"} else f"{key.title()} disponibles"
        return f"{label}: {', '.join(visible)}{suffix}"

    formatted = [
        ", ".join(f"{key.title()}={value}" for key, value in variant)
        for variant in ordered[:8]
    ]
    suffix = f" y {len(ordered) - len(formatted)} más" if len(ordered) > len(formatted) else ""
    return f"Disponibles: {'; '.join(formatted)}{suffix}"


def _balance_entry(
    observation: PriceObservationRecord,
    tracked_label: str | None,
) -> BalanceEntry:
    return BalanceEntry(
        store_slug=observation.store_slug,
        category=catalog_category(
            store_slug=observation.store_slug,
            label=tracked_label or observation.title,
            category_path=observation.category_path,
        ),
    )


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
    channel: str = "telegram_free"
    provider: str = "telegram"
    audience: str = "free"
    dispatch_mode: str = "immediate"
    routing_rule: str = "explicit_single_destination"
    routing_reason: str | None = None
    scheduled_for: datetime | None = None
    image_url: str | None = None
    condition_flags: tuple[str, ...] = ()
    variant_summary: str | None = None


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
                DealDetection.score.desc(),
                NotificationDelivery.next_attempt_at.asc(),
                NotificationDelivery.id.asc(),
            )
            .limit(1_000)
            .with_for_update(of=NotificationDelivery, skip_locked=True)
        )
        pool = self._session.execute(statement).all()
        entries = [
            _balance_entry(
                observation,
                tracked_label,
            )
            for _delivery, _detection, observation, tracked_label in pool
        ]
        recent_sent = [
            _balance_entry(observation, tracked_label)
            for observation, tracked_label in self._session.execute(
                select(
                    PriceObservationRecord,
                    TrackedProduct.label,
                )
                .select_from(NotificationDelivery)
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
                    NotificationDelivery.status == "sent",
                    NotificationDelivery.sent_at >= timestamp - timedelta(hours=24),
                )
                .order_by(NotificationDelivery.sent_at.desc())
                .limit(2_000)
            )
        ]
        rows = [
            pool[position]
            for position in balanced_indices(
                entries,
                limit=limit,
                initial_entries=recent_sent,
            )
        ]
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
                    channel=delivery.channel,
                    provider=delivery.provider,
                    audience=delivery.audience,
                    dispatch_mode=delivery.dispatch_mode,
                    routing_rule=delivery.routing_rule,
                    routing_reason=delivery.routing_reason,
                    scheduled_for=delivery.scheduled_for,
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
                    image_url=observation.image_url,
                    condition_flags=_condition_flags(observation.quality_flags),
                    variant_summary=_variant_summary(self._session, observation),
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
        delivery_method: str | None = None,
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
        normalized_delivery_method = _safe_text(delivery_method, maximum=32)
        if normalized_delivery_method not in {
            None,
            "photo_url",
            "photo_upload",
            "text",
            "text_fallback",
        }:
            raise ValueError("delivery_method is not supported")
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
            delivery.delivery_method = normalized_delivery_method
            delivery.last_error_code = None
            delivery.last_error = None
            delivery.sent_at = timestamp
        else:
            delivery.delivery_method = None
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
        self._refresh_detection_status(detection)
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
        touched_detections: dict[int, DealDetection] = {}
        for delivery, detection in rows:
            delivery.status = "failed"
            delivery.lease_token = None
            delivery.lease_expires_at = None
            delivery.last_error_code = delivery.last_error_code or "attempts_exhausted"
            delivery.last_error = (
                delivery.last_error or "La entrega agotó sus intentos después de perder un lease."
            )
            delivery.updated_at = now
            touched_detections[detection.id] = detection
        for detection in touched_detections.values():
            self._refresh_detection_status(detection)
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

    def _refresh_detection_status(
        self,
        detection: DealDetection,
    ) -> None:
        deliveries = list(
            self._session.scalars(
                select(NotificationDelivery).where(
                    NotificationDelivery.detection_id == detection.id
                )
            )
        )
        statuses = {delivery.status for delivery in deliveries}
        sent_times = [
            delivery.sent_at
            for delivery in deliveries
            if delivery.status == "sent" and delivery.sent_at is not None
        ]
        if "pending" in statuses:
            detection.notification_status = "pending"
        elif "retrying" in statuses:
            detection.notification_status = "retrying"
        elif "sent" in statuses:
            detection.notification_status = "sent"
        elif "failed" in statuses:
            detection.notification_status = "failed"
        elif statuses and statuses == {"superseded"}:
            detection.notification_status = "superseded"
        if sent_times:
            detection.notified_at = max(sent_times)


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
