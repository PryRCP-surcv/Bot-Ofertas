"""Oechsle-specific policy around its reviewed public VTEX product endpoint."""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from datetime import datetime
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

OECHSLE_HOSTS = frozenset({"oechsle.pe", "www.oechsle.pe"})
EXTRACTOR_VERSION = "oechsle-vtex-v1"
_OWN_SELLER_ID = "1"
_OWN_SELLER_NAME = "oechsle"


class OechslePayloadError(VtexPayloadError):
    """Raised when Oechsle's public response no longer matches the reviewed shape."""


def normalize_oechsle_product_url(url: str) -> str:
    """Accept only explicit canonical Oechsle product-detail paths."""

    candidate = url.strip()
    try:
        parts = urlsplit(candidate)
    except ValueError as exc:
        raise ValueError("The Oechsle product URL is invalid.") from exc
    path_segments = [segment for segment in unquote(parts.path).split("/") if segment]
    if len(path_segments) != 2:
        raise ValueError("The Oechsle URL must use the explicit '/product-slug/p' form.")

    return normalize_vtex_product_url(
        candidate,
        hosts=OECHSLE_HOSTS,
        canonical_host="www.oechsle.pe",
        display_name="Oechsle",
    )


def build_oechsle_catalog_url(product_url: str) -> str:
    """Derive Oechsle's read-only public VTEX endpoint for one explicit product."""

    return build_vtex_catalog_url(
        product_url,
        normalize_product_url=normalize_oechsle_product_url,
        api_host="www.oechsle.pe",
    )


def is_oechsle_own_seller(seller_id: str, seller_name: str) -> bool:
    """Recognize Oechsle only when both reviewed seller identifiers agree."""

    return seller_id.strip() == _OWN_SELLER_ID and _searchable_text(seller_name) == _OWN_SELLER_NAME


def _oechsle_offer_quality_flags(
    product: Mapping[str, Any],
    item: Mapping[str, Any],
    seller: Mapping[str, Any],
    offer: Mapping[str, Any],
) -> list[str]:
    flags: list[str] = []
    seller_id = _optional_text(seller.get("sellerId"))
    seller_name = _optional_text(seller.get("sellerName"))
    id_claims_own = seller_id == _OWN_SELLER_ID
    name_claims_own = seller_name is not None and _searchable_text(seller_name) == _OWN_SELLER_NAME
    if id_claims_own != name_claims_own:
        flags.append("ambiguous_oechsle_seller_identity")

    flags.extend(conditional_vtex_price_flags(product, item, seller, offer))
    return flags


_PARSER_CONFIG = VtexParserConfig(
    store_slug="oechsle",
    display_name="Oechsle",
    extractor_version=EXTRACTOR_VERSION,
    normalize_product_url=normalize_oechsle_product_url,
    is_own_seller=is_oechsle_own_seller,
    payload_error=OechslePayloadError,
    offer_quality_flags=_oechsle_offer_quality_flags,
)


def parse_oechsle_products(
    payload: Any,
    source_url: str,
    tracked_product_id: UUID | str | None,
    observed_at: datetime | str,
) -> list[dict[str, Any]]:
    """Normalize Oechsle into one observation per exact SKU and seller."""

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
    canonical_url = normalize_oechsle_product_url(source_url)
    expected_slug = unquote(urlsplit(canonical_url).path).strip("/").rsplit("/", maxsplit=1)[0]
    for index, product in enumerate(payload):
        if not isinstance(product, Mapping):
            continue
        link_text = _optional_text(product.get("linkText"))
        if link_text is None:
            raise OechslePayloadError(
                f"Product at index {index} is missing the Oechsle canonical slug."
            )
        observed_slug = unquote(link_text).strip("/").casefold()
        if observed_slug != expected_slug.casefold():
            raise OechslePayloadError(
                f"Product at index {index} does not match the requested Oechsle slug."
            )


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized or None


def _searchable_text(value: Any) -> str:
    parts: list[str] = []

    def collect(candidate: Any) -> None:
        if isinstance(candidate, Mapping):
            for key, nested_value in candidate.items():
                collect(key)
                collect(nested_value)
        elif isinstance(candidate, (list, tuple)):
            for nested_value in candidate:
                collect(nested_value)
        elif isinstance(candidate, str):
            parts.append(candidate)

    collect(value)
    normalized = unicodedata.normalize("NFKD", " ".join(parts).casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(normalized.split())


__all__ = [
    "EXTRACTOR_VERSION",
    "OECHSLE_HOSTS",
    "OechslePayloadError",
    "build_oechsle_catalog_url",
    "is_oechsle_own_seller",
    "normalize_oechsle_product_url",
    "parse_oechsle_products",
]
