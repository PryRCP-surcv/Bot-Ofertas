"""Application service for durable, retryable notification delivery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.orm import Session, sessionmaker

from bot_ofertas.notifications import (
    NotificationChannel,
    NotificationResult,
    NotificationStatus,
    OfferNotification,
)
from bot_ofertas.runtime_config import RuntimeSettings
from bot_ofertas.storage.database import session_scope
from bot_ofertas.storage.models import NotificationDelivery
from bot_ofertas.storage.notifications import (
    NotificationClaim,
    NotificationDeliveryRepository,
)

_REASON_LABELS = {
    "previous_price": "caída frente al precio anterior",
    "median_7d": "caída frente a la mediana de 7 días",
    "median_30d": "caída frente a la mediana de 30 días",
    "historical_median": "caída frente a la mediana de 90 días",
    "equivalent_median": "caída frente a productos equivalentes",
    "historical_minimum": "nuevo mínimo histórico",
    "list_price": "descuento frente al precio de lista",
}
_CONDITION_LABELS = {
    "conditional_card_price": "precio condicionado a tarjeta o medio de pago",
    "conditional_payment_method_price": "precio condicionado a tarjeta o medio de pago",
    "payment_method_price": "precio condicionado a tarjeta o medio de pago",
    "card_only_price": "precio condicionado a tarjeta o medio de pago",
    "tarjeta_only_price": "precio condicionado a tarjeta o medio de pago",
    "conditional_membership_price": "precio exclusivo para miembros o socios",
    "membership_price": "precio exclusivo para miembros o socios",
    "membership_only_price": "precio exclusivo para miembros o socios",
    "conditional_coupon_price": "requiere un cupón",
    "coupon_price": "requiere un cupón",
    "coupon_only_price": "requiere un cupón",
    "conditional_quantity_price": "requiere una cantidad mínima de compra",
    "minimum_quantity_price": "requiere una cantidad mínima de compra",
    "quantity_tier_price": "requiere una cantidad mínima de compra",
    "conditional_promotion_price": "promoción con condiciones adicionales",
    "delivery_location_confirmation": (
        "confirma disponibilidad y delivery para tu distrito de Lima"
    ),
}
_GENERIC_CONDITION_FLAG = "conditional_promotion_price"


@dataclass(frozen=True, slots=True)
class NotificationBatchSummary:
    configured: bool
    claimed: int = 0
    sent: int = 0
    retrying: int = 0
    failed: int = 0
    released: int = 0


class NotificationDispatcher:
    """Dispatch leased deliveries without keeping transactions open on the network."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        settings: RuntimeSettings,
        channel: NotificationChannel,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._channel = channel

    def dispatch_due(self, *, limit: int = 20) -> NotificationBatchSummary:
        if not self._channel.enabled:
            return NotificationBatchSummary(configured=False)

        claimed = 0
        sent = 0
        retrying = 0
        failed = 0
        released = 0
        for _position in range(limit):
            with session_scope(self._session_factory) as session:
                claims = NotificationDeliveryRepository(session).claim_due(
                    channel=self._channel.channel_name,
                    limit=1,
                    max_attempts=self._settings.notification_max_attempts,
                    lease_duration=timedelta(seconds=self._settings.notification_lease_seconds),
                )
            if not claims:
                break
            claim = claims[0]
            claimed += 1
            try:
                result = self._channel.send(_notification(claim))
            except Exception:
                result = NotificationResult(
                    channel=self._channel.channel_name,
                    status=NotificationStatus.FAILED,
                    detail="El canal lanzó un error inesperado y seguro.",
                    retryable=True,
                )
            if result.status is NotificationStatus.DISABLED:
                with session_scope(self._session_factory) as session:
                    released += int(
                        NotificationDeliveryRepository(session).release(
                            delivery_id=claim.delivery_id,
                            lease_token=claim.lease_token,
                        )
                    )
                continue

            completed = False
            with session_scope(self._session_factory) as session:
                completed = NotificationDeliveryRepository(session).complete(
                    delivery_id=claim.delivery_id,
                    lease_token=claim.lease_token,
                    sent=result.sent,
                    max_attempts=self._settings.notification_max_attempts,
                    retry_base_seconds=(self._settings.notification_retry_base_seconds),
                    retryable=(result.retryable if result.retryable is not None else True),
                    retry_after_seconds=result.retry_after_seconds,
                    provider_message_id=result.message_id,
                    error_code=result.status.value if not result.sent else None,
                    error_detail=result.detail,
                )
                if completed and not result.sent:
                    delivery = session.get(NotificationDelivery, claim.delivery_id)
                    if delivery is not None and delivery.status == "failed":
                        failed += 1
                    else:
                        retrying += 1
            if completed and result.sent:
                sent += 1
        return NotificationBatchSummary(
            configured=True,
            claimed=claimed,
            sent=sent,
            retrying=retrying,
            failed=failed,
            released=released,
        )


def _notification(claim: NotificationClaim) -> OfferNotification:
    return OfferNotification(
        classification=claim.classification,
        product_name=claim.product_name,
        current_price=claim.current_price,
        currency=claim.currency,
        reason=f"{_reason(claim.reason_codes)}. Referencia interna #{claim.detection_id}",
        product_url=claim.product_url,
        comparison_price=claim.comparison_price,
        discount_percent=claim.discount_percent,
        store_name=claim.store_slug,
        comparison_label=claim.comparison_label,
        confidence_score=claim.confidence_score,
        confirmation_count=claim.confirmation_count,
        conditions=_conditions(claim.condition_flags),
    )


def _reason(reason_codes: tuple[str, ...]) -> str:
    labels: list[str] = []
    for reason_code in reason_codes:
        signal_name, _, _classification = reason_code.partition(":")
        label = _REASON_LABELS.get(signal_name, signal_name.replace("_", " "))
        if label not in labels:
            labels.append(label)
    return "; ".join(labels) if labels else "reducción anormal detectada"


def _conditions(condition_flags: tuple[str, ...]) -> tuple[str, ...]:
    normalized_flags = tuple(
        dict.fromkeys(flag.strip().casefold() for flag in condition_flags if flag.strip())
    )
    has_specific_condition = any(
        flag in _CONDITION_LABELS and flag != _GENERIC_CONDITION_FLAG for flag in normalized_flags
    )

    labels: list[str] = []
    for flag in normalized_flags:
        if flag == _GENERIC_CONDITION_FLAG and has_specific_condition:
            continue
        label = _CONDITION_LABELS.get(flag)
        if label is not None and label not in labels:
            labels.append(label)
    return tuple(labels)


__all__ = [
    "NotificationBatchSummary",
    "NotificationDispatcher",
]
