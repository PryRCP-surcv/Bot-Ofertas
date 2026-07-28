"""Promart-specific policy around its reviewed public VTEX product endpoint."""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import UUID

from bot_ofertas.crawling.vtex import (
    VtexParserConfig,
    VtexPayloadError,
    build_vtex_catalog_url,
    conditional_vtex_price_flags,
    normalize_vtex_product_url,
    parse_vtex_products,
)

PROMART_HOSTS = frozenset({"promart.pe", "www.promart.pe"})
EXTRACTOR_VERSION = "promart-vtex-v1"
_OWN_SELLER_ID = "1"
_OWN_SELLER_NAME = "promart"
_FIXED_MEASUREMENT_UNITS = frozenset({"un", "unidad", "unit"})


class PromartPayloadError(VtexPayloadError):
    """Raised when Promart's public response no longer matches the reviewed shape."""


def normalize_promart_product_url(url: str) -> str:
    """Accept only explicit canonical Promart product-detail paths."""

    candidate = url.strip()
    try:
        parts = urlsplit(candidate)
    except ValueError as exc:
        raise ValueError("The Promart product URL is invalid.") from exc
    path_segments = [segment for segment in unquote(parts.path).split("/") if segment]
    if len(path_segments) != 2:
        raise ValueError("The Promart URL must use the explicit '/product-slug/p' form.")

    return normalize_vtex_product_url(
        candidate,
        hosts=PROMART_HOSTS,
        canonical_host="www.promart.pe",
        display_name="Promart",
    )


def build_promart_catalog_url(product_url: str) -> str:
    """Derive Promart's read-only public VTEX endpoint for one explicit product."""

    return build_vtex_catalog_url(
        product_url,
        normalize_product_url=normalize_promart_product_url,
        api_host="www.promart.pe",
    )


def is_promart_own_seller(seller_id: str, seller_name: str) -> bool:
    """Recognize Promart only when both reviewed seller identifiers agree."""

    return seller_id.strip() == _OWN_SELLER_ID and _searchable_text(seller_name) == _OWN_SELLER_NAME


def _promart_offer_quality_flags(
    product: Mapping[str, Any],
    item: Mapping[str, Any],
    seller: Mapping[str, Any],
    offer: Mapping[str, Any],
) -> list[str]:
    flags: list[str] = ["location_context_unverified"]
    seller_id = _optional_text(seller.get("sellerId"))
    seller_name = _optional_text(seller.get("sellerName"))
    id_claims_own = seller_id == _OWN_SELLER_ID
    name_claims_own = seller_name is not None and _searchable_text(seller_name) == _OWN_SELLER_NAME
    if id_claims_own != name_claims_own:
        flags.append("ambiguous_promart_seller_identity")

    measurement_unit = _searchable_text(item.get("measurementUnit"))
    unit_multiplier = _positive_decimal(item.get("unitMultiplier"))
    if measurement_unit not in _FIXED_MEASUREMENT_UNITS or unit_multiplier != Decimal("1"):
        flags.append("unsupported_price_basis")

    flags.extend(conditional_vtex_price_flags(product, item, seller, offer))
    return flags


_PARSER_CONFIG = VtexParserConfig(
    store_slug="promart",
    display_name="Promart",
    extractor_version=EXTRACTOR_VERSION,
    normalize_product_url=normalize_promart_product_url,
    is_own_seller=is_promart_own_seller,
    payload_error=PromartPayloadError,
    offer_quality_flags=_promart_offer_quality_flags,
)


def parse_promart_products(
    payload: Any,
    source_url: str,
    tracked_product_id: UUID | str | None,
    observed_at: datetime | str,
) -> list[dict[str, Any]]:
    """Normalize Promart into one observation per exact SKU and seller."""

    _validate_payload_identity(payload, source_url)
    return parse_vtex_products(
        payload,
        source_url,
        tracked_product_id,
        observed_at,
        config=_PARSER_CONFIG,
    )


def _validate_payload_identity(payload: Any, source_url: str) -> None:
    if not isinstance(payload, list):
        return
    canonical_url = normalize_promart_product_url(source_url)
    expected_slug = unquote(urlsplit(canonical_url).path).strip("/").rsplit("/", maxsplit=1)[0]
    for index, product in enumerate(payload):
        if not isinstance(product, Mapping):
            continue
        link_text = _optional_text(product.get("linkText"))
        if link_text is None:
            raise PromartPayloadError(
                f"Product at index {index} is missing the Promart canonical slug."
            )
        observed_slug = unquote(link_text).strip("/").casefold()
        if observed_slug != expected_slug.casefold():
            raise PromartPayloadError(
                f"Product at index {index} does not match the requested Promart slug."
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


def _searchable_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(normalized.split())


__all__ = [
    "EXTRACTOR_VERSION",
    "PROMART_HOSTS",
    "PromartPayloadError",
    "build_promart_catalog_url",
    "is_promart_own_seller",
    "normalize_promart_product_url",
    "parse_promart_products",
]
