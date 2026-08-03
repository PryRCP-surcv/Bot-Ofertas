"""Normalized price observation contracts.

This module intentionally uses only the standard library. Crawlers can create these
objects without knowing anything about PostgreSQL, and storage code can persist them
without depending on a particular spider implementation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")
_MAX_MEDIA_URL_LENGTH = 2_048


class ProductCondition(StrEnum):
    """Condition reported for the exact offer being observed."""

    NEW = "new"
    USED = "used"
    REFURBISHED = "refurbished"
    OPEN_BOX = "open_box"
    UNKNOWN = "unknown"


class Availability(StrEnum):
    """Normalized stock state for an offer."""

    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    PREORDER = "preorder"
    BACKORDER = "backorder"
    UNKNOWN = "unknown"


def _required_text(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def normalize_optional_https_url(
    value: str | None,
    field_name: str = "URL",
) -> str | None:
    """Normalize one optional, public HTTPS URL suitable for external media."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string or None")
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > _MAX_MEDIA_URL_LENGTH:
        raise ValueError(f"{field_name} must not exceed {_MAX_MEDIA_URL_LENGTH} characters")
    if any(character.isspace() for character in normalized):
        raise ValueError(f"{field_name} must not contain whitespace")
    try:
        parsed = urlsplit(normalized)
        port = parsed.port
    except ValueError as error:
        raise ValueError(f"{field_name} must be a valid HTTPS URL") from error
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        raise ValueError(
            f"{field_name} must be an absolute HTTPS URL without credentials or custom ports"
        )
    return normalized


def _decimal_or_none(value: Decimal | int | str | None, field_name: str) -> Decimal | None:
    if value is None:
        return None
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


def _currency_code(value: str, field_name: str = "currency") -> str:
    normalized = value.strip().upper()
    if not _CURRENCY_PATTERN.fullmatch(normalized):
        raise ValueError(f"{field_name} must be a three-letter ISO-style currency code")
    return normalized


@dataclass(frozen=True, slots=True)
class InstallmentOption:
    """Financing information kept separate from the actual product price."""

    count: int
    amount: Decimal
    currency: str
    total: Decimal | None = None
    down_payment: Decimal | None = None
    interest_free: bool | None = None
    issuer: str | None = None
    payment_method: str | None = None
    source_text: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.count, int) or isinstance(self.count, bool) or self.count <= 0:
            raise ValueError("installment count must be a positive integer")

        amount = _decimal_or_none(self.amount, "installment amount")
        if amount is None:  # pragma: no cover - the type is non-optional
            raise ValueError("installment amount is required")

        object.__setattr__(self, "amount", amount)
        object.__setattr__(self, "total", _decimal_or_none(self.total, "installment total"))
        object.__setattr__(
            self,
            "down_payment",
            _decimal_or_none(self.down_payment, "installment down payment"),
        )
        object.__setattr__(self, "currency", _currency_code(self.currency, "installment currency"))
        object.__setattr__(self, "issuer", _optional_text(self.issuer))
        object.__setattr__(self, "payment_method", _optional_text(self.payment_method))
        object.__setattr__(self, "source_text", _optional_text(self.source_text))

    def as_json(self) -> dict[str, Any]:
        """Return an exact, JSON-compatible representation.

        Decimal values are strings so database JSON serialization never introduces
        binary floating-point rounding.
        """

        return {
            "count": self.count,
            "amount": str(self.amount),
            "currency": self.currency,
            "total": str(self.total) if self.total is not None else None,
            "down_payment": str(self.down_payment) if self.down_payment is not None else None,
            "interest_free": self.interest_free,
            "issuer": self.issuer,
            "payment_method": self.payment_method,
            "source_text": self.source_text,
        }


@dataclass(slots=True)
class PriceObservation:
    """One normalized observation for one exact SKU and seller."""

    store_slug: str
    source_url: str
    external_product_id: str
    sku: str
    seller_id: str
    seller_name: str
    title: str
    condition: ProductCondition
    currency: str
    availability: Availability
    is_marketplace: bool
    observed_at: datetime
    extractor_version: str
    source_payload_hash: str
    tracked_product_id: UUID | None = None
    product_reference: str | None = None
    sku_reference: str | None = None
    brand: str | None = None
    model: str | None = None
    image_url: str | None = None
    category_path: list[str] = field(default_factory=list)
    variant: dict[str, str] = field(default_factory=dict)
    price: Decimal | None = None
    list_price: Decimal | None = None
    available_quantity: int | None = None
    installments: list[InstallmentOption] = field(default_factory=list)
    quality_flags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.store_slug = _required_text(self.store_slug, "store_slug").lower()
        self.external_product_id = _required_text(
            self.external_product_id,
            "external_product_id",
        )
        self.sku = _required_text(self.sku, "sku")
        self.seller_id = _required_text(self.seller_id, "seller_id")
        self.seller_name = _required_text(self.seller_name, "seller_name")
        self.title = _required_text(self.title, "title")
        self.extractor_version = _required_text(self.extractor_version, "extractor_version")

        parsed_url = urlsplit(self.source_url.strip())
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("source_url must be an absolute HTTP or HTTPS URL")
        self.source_url = self.source_url.strip()

        self.product_reference = _optional_text(self.product_reference)
        self.sku_reference = _optional_text(self.sku_reference)
        self.brand = _optional_text(self.brand)
        self.model = _optional_text(self.model)
        self.image_url = normalize_optional_https_url(self.image_url, "image_url")
        self.condition = ProductCondition(self.condition)
        self.availability = Availability(self.availability)
        self.currency = _currency_code(self.currency)
        self.price = _decimal_or_none(self.price, "price")
        self.list_price = _decimal_or_none(self.list_price, "list_price")
        if not isinstance(self.is_marketplace, bool):
            raise TypeError("is_marketplace must be a boolean")

        if not isinstance(self.observed_at, datetime):
            raise TypeError("observed_at must be a datetime")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        self.observed_at = self.observed_at.astimezone(UTC)

        normalized_hash = self.source_payload_hash.strip().lower()
        if not _SHA256_PATTERN.fullmatch(normalized_hash):
            raise ValueError("source_payload_hash must be a lowercase SHA-256 hex digest")
        self.source_payload_hash = normalized_hash

        if self.available_quantity is not None:
            if not isinstance(self.available_quantity, int) or isinstance(
                self.available_quantity,
                bool,
            ):
                raise TypeError("available_quantity must be an integer or None")
            if self.available_quantity < 0:
                raise ValueError("available_quantity must not be negative")

        self.category_path = [
            _required_text(part, "category_path item") for part in self.category_path
        ]
        self.variant = {
            _required_text(key, "variant key"): _required_text(value, "variant value")
            for key, value in self.variant.items()
        }
        self.installments = [
            option if isinstance(option, InstallmentOption) else InstallmentOption(**option)
            for option in self.installments
        ]
        self.quality_flags = list(
            dict.fromkeys(_required_text(flag, "quality flag") for flag in self.quality_flags)
        )
