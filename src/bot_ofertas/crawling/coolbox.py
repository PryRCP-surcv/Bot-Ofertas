"""Coolbox-specific wrappers around the shared public VTEX parser."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from bot_ofertas.crawling.vtex import (
    MAX_REPORTED_QUANTITY,
    VtexParserConfig,
    VtexPayloadError,
    build_vtex_catalog_url,
    normalize_vtex_product_url,
    parse_vtex_products,
)
from bot_ofertas.crawling.vtex import canonical_payload_hash as vtex_payload_hash

COOLBOX_HOSTS = frozenset({"coolbox.pe", "www.coolbox.pe"})
EXTRACTOR_VERSION = "coolbox-vtex-v1"


class CoolboxPayloadError(VtexPayloadError):
    """Raised when Coolbox's public response no longer matches the expected shape."""


def normalize_coolbox_product_url(url: str) -> str:
    """Validate and canonicalize an explicit public Coolbox product URL."""

    return normalize_vtex_product_url(
        url,
        hosts=COOLBOX_HOSTS,
        canonical_host="www.coolbox.pe",
        display_name="Coolbox",
    )


def build_coolbox_catalog_url(product_url: str) -> str:
    """Derive Coolbox's read-only public VTEX endpoint for a product page."""

    return build_vtex_catalog_url(
        product_url,
        normalize_product_url=normalize_coolbox_product_url,
        api_host="www.coolbox.pe",
    )


def canonical_payload_hash(payload: Any) -> str:
    """Preserve Coolbox's public payload hashing API."""

    return vtex_payload_hash(
        payload,
        display_name="Coolbox",
        payload_error=CoolboxPayloadError,
    )


_PARSER_CONFIG = VtexParserConfig(
    store_slug="coolbox",
    display_name="Coolbox",
    extractor_version=EXTRACTOR_VERSION,
    normalize_product_url=normalize_coolbox_product_url,
    is_own_seller=lambda seller_id, _seller_name: seller_id == "1",
    payload_error=CoolboxPayloadError,
)


def parse_coolbox_products(
    payload: Any,
    source_url: str,
    tracked_product_id: UUID | str | None,
    observed_at: datetime | str,
) -> list[dict[str, Any]]:
    """Normalize Coolbox into one observation per exact SKU and seller."""

    return parse_vtex_products(
        payload,
        source_url,
        tracked_product_id,
        observed_at,
        config=_PARSER_CONFIG,
    )


__all__ = [
    "COOLBOX_HOSTS",
    "EXTRACTOR_VERSION",
    "MAX_REPORTED_QUANTITY",
    "CoolboxPayloadError",
    "build_coolbox_catalog_url",
    "canonical_payload_hash",
    "normalize_coolbox_product_url",
    "parse_coolbox_products",
]
