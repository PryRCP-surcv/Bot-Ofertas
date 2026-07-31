"""Shared safeguards for reviewed fixed-unit VTEX retailers."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import unquote, urlsplit

from bot_ofertas.crawling.vtex import (
    ProductUrlNormalizer,
    VtexPayloadError,
    conditional_vtex_price_flags,
    normalize_vtex_product_url,
)

DELIVERY_LOCATION_CONFIRMATION_FLAG = "delivery_location_confirmation"
_FIXED_MEASUREMENT_UNITS = frozenset({"un", "und", "unidad", "unit"})


def normalized_identity(value: Any) -> str:
    """Return a punctuation-insensitive commercial identity."""

    if not isinstance(value, str):
        return ""
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_accents = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(re.findall(r"[a-z0-9]+", without_accents))


def is_exact_own_seller(
    seller_id: str,
    seller_name: str,
    *,
    expected_id: str,
    expected_names: frozenset[str],
) -> bool:
    """Require both the reviewed seller identifier and one reviewed legal name."""

    normalized_names = frozenset(normalized_identity(name) for name in expected_names)
    return seller_id.strip() == expected_id and normalized_identity(seller_name) in normalized_names


def reviewed_retail_offer_quality_flags(
    product: Mapping[str, Any],
    item: Mapping[str, Any],
    seller: Mapping[str, Any],
    offer: Mapping[str, Any],
    *,
    expected_seller_id: str,
    expected_seller_names: frozenset[str],
    ambiguous_seller_flag: str,
    delivery_location_confirmation: bool,
) -> list[str]:
    """Validate seller identity, unit basis and public commercial conditions."""

    flags: list[str] = []
    seller_id = _optional_text(seller.get("sellerId"))
    seller_name = _optional_text(seller.get("sellerName"))
    normalized_names = frozenset(
        normalized_identity(name) for name in expected_seller_names
    )
    id_claims_own = seller_id == expected_seller_id
    name_claims_own = (
        seller_name is not None and normalized_identity(seller_name) in normalized_names
    )
    if id_claims_own != name_claims_own:
        flags.append(ambiguous_seller_flag)

    measurement_unit = normalized_identity(item.get("measurementUnit"))
    unit_multiplier = _positive_decimal(item.get("unitMultiplier"))
    if (
        measurement_unit not in _FIXED_MEASUREMENT_UNITS
        or unit_multiplier != Decimal("1")
    ):
        flags.append("unsupported_price_basis")

    if delivery_location_confirmation and id_claims_own and name_claims_own:
        flags.append(DELIVERY_LOCATION_CONFIRMATION_FLAG)

    flags.extend(conditional_vtex_price_flags(product, item, seller, offer))
    return flags


def normalize_root_vtex_product_url(
    url: str,
    *,
    hosts: frozenset[str],
    canonical_host: str,
    display_name: str,
) -> str:
    """Accept only a root ``/slug/p`` product detail URL."""

    candidate = url.strip()
    try:
        parts = urlsplit(candidate)
    except ValueError as exc:
        raise ValueError(f"The {display_name} product URL is invalid.") from exc
    segments = [segment for segment in unquote(parts.path).split("/") if segment]
    if len(segments) != 2:
        raise ValueError(
            f"The {display_name} URL must use the explicit '/product-slug/p' form."
        )
    return normalize_vtex_product_url(
        candidate,
        hosts=hosts,
        canonical_host=canonical_host,
        display_name=display_name,
    )


def validate_vtex_payload_identity(
    payload: Any,
    source_url: str,
    *,
    normalize_product_url: ProductUrlNormalizer,
    display_name: str,
    payload_error: type[VtexPayloadError],
) -> None:
    """Fence a public VTEX response to the exact requested product slug."""

    if not isinstance(payload, list):
        return
    canonical_url = normalize_product_url(source_url)
    expected_slug = unquote(urlsplit(canonical_url).path).strip("/").rsplit("/", 1)[0]
    for index, product in enumerate(payload):
        if not isinstance(product, Mapping):
            continue
        link_text = _optional_text(product.get("linkText"))
        if link_text is None:
            raise payload_error(
                f"Product at index {index} is missing the {display_name} canonical slug."
            )
        observed_slug = unquote(link_text).strip("/").casefold()
        if observed_slug != expected_slug.casefold():
            raise payload_error(
                f"Product at index {index} does not match the requested {display_name} slug."
            )


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized or None


def _positive_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not numeric.is_finite() or numeric <= 0:
        return None
    return numeric


__all__ = [
    "DELIVERY_LOCATION_CONFIRMATION_FLAG",
    "is_exact_own_seller",
    "normalize_root_vtex_product_url",
    "normalized_identity",
    "reviewed_retail_offer_quality_flags",
    "validate_vtex_payload_identity",
]
