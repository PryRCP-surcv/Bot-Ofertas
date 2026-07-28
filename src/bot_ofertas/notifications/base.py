"""Notification contracts shared by delivery channel implementations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Protocol, runtime_checkable
from urllib.parse import urlsplit

_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")


def _required_text(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def _decimal(value: Decimal | int | str, field_name: str) -> Decimal:
    if isinstance(value, (bool, float)):
        raise TypeError(f"{field_name} must use Decimal, int, or str; floats are not accepted")
    try:
        normalized = value if isinstance(value, Decimal) else Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{field_name} is not a valid decimal") from error
    if not normalized.is_finite():
        raise ValueError(f"{field_name} must be finite")
    if normalized < 0:
        raise ValueError(f"{field_name} must not be negative")
    return normalized


def _text_tuple(
    value: tuple[str, ...] | list[str],
    field_name: str,
) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise TypeError(f"{field_name} must be a tuple or list of strings")

    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise TypeError(f"{field_name} must contain only strings")
        text = _required_text(item, field_name)
        if text not in normalized:
            normalized.append(text)
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class OfferNotification:
    """Channel-neutral data required to explain one detected offer."""

    classification: str
    product_name: str
    current_price: Decimal
    currency: str
    reason: str
    product_url: str
    comparison_price: Decimal | None = None
    discount_percent: Decimal | None = None
    store_name: str | None = None
    comparison_label: str = "Precio de referencia"
    confidence_score: int | None = None
    confirmation_count: int | None = None
    conditions: tuple[str, ...] | list[str] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "classification",
            _required_text(self.classification, "classification").lower(),
        )
        object.__setattr__(self, "product_name", _required_text(self.product_name, "product_name"))
        object.__setattr__(self, "reason", _required_text(self.reason, "reason"))
        object.__setattr__(
            self,
            "comparison_label",
            _required_text(self.comparison_label, "comparison_label"),
        )

        currency = self.currency.strip().upper()
        if not _CURRENCY_PATTERN.fullmatch(currency):
            raise ValueError("currency must be a three-letter ISO-style currency code")
        object.__setattr__(self, "currency", currency)
        object.__setattr__(
            self,
            "current_price",
            _decimal(self.current_price, "current_price"),
        )
        if self.comparison_price is not None:
            object.__setattr__(
                self,
                "comparison_price",
                _decimal(self.comparison_price, "comparison_price"),
            )
        if self.discount_percent is not None:
            discount = _decimal(self.discount_percent, "discount_percent")
            if discount > 100:
                raise ValueError("discount_percent must not exceed 100")
            object.__setattr__(self, "discount_percent", discount)
        if self.confidence_score is not None and (
            isinstance(self.confidence_score, bool)
            or not isinstance(self.confidence_score, int)
            or not 0 <= self.confidence_score <= 100
        ):
            raise ValueError("confidence_score must be an integer between 0 and 100")
        if self.confirmation_count is not None and (
            isinstance(self.confirmation_count, bool)
            or not isinstance(self.confirmation_count, int)
            or self.confirmation_count < 1
        ):
            raise ValueError("confirmation_count must be a positive integer")
        object.__setattr__(
            self,
            "conditions",
            _text_tuple(self.conditions, "conditions"),
        )

        parsed_url = urlsplit(self.product_url.strip())
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("product_url must be an absolute HTTP or HTTPS URL")
        object.__setattr__(self, "product_url", self.product_url.strip())

        if self.store_name is not None:
            normalized_store = self.store_name.strip()
            object.__setattr__(self, "store_name", normalized_store or None)


class NotificationStatus(StrEnum):
    """Outcome of one attempt to deliver a notification."""

    SENT = "sent"
    DISABLED = "disabled"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class NotificationResult:
    """Safe result returned by a notification channel."""

    channel: str
    status: NotificationStatus
    message_id: str | None = None
    detail: str | None = None
    retryable: bool | None = None
    retry_after_seconds: int | None = None

    def __post_init__(self) -> None:
        if self.retryable is not None and not isinstance(self.retryable, bool):
            raise TypeError("retryable must be a boolean or None")
        if self.retry_after_seconds is not None and self.retry_after_seconds <= 0:
            raise ValueError("retry_after_seconds must be positive")

    @property
    def sent(self) -> bool:
        return self.status is NotificationStatus.SENT


@runtime_checkable
class NotificationChannel(Protocol):
    """Synchronous delivery contract implemented by all notification channels."""

    @property
    def channel_name(self) -> str:
        """Stable channel identifier used in delivery logs."""

    @property
    def enabled(self) -> bool:
        """Whether this channel currently has usable configuration."""

    def send(self, notification: OfferNotification) -> NotificationResult:
        """Deliver a notification without raising for provider failures."""


__all__ = [
    "NotificationChannel",
    "NotificationResult",
    "NotificationStatus",
    "OfferNotification",
]
