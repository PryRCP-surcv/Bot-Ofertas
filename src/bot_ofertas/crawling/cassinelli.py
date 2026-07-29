"""Cassinelli-specific wrappers around its reviewed public VTEX catalog."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from bot_ofertas.crawling.vtex import (
    VtexParserConfig,
    VtexPayloadError,
    build_vtex_catalog_url,
    conditional_vtex_price_flags,
    normalize_vtex_product_url,
    parse_vtex_products,
)

CASSINELLI_HOSTS = frozenset({"cassinelli.com", "www.cassinelli.com"})
EXTRACTOR_VERSION = "cassinelli-vtex-v1"


class CassinelliPayloadError(VtexPayloadError):
    """Raised when Cassinelli's public response no longer has the reviewed shape."""


def normalize_cassinelli_product_url(url: str) -> str:
    """Accept only an explicit Cassinelli product-detail URL."""

    return normalize_vtex_product_url(
        url,
        hosts=CASSINELLI_HOSTS,
        canonical_host="www.cassinelli.com",
        display_name="Cassinelli",
    )


def build_cassinelli_catalog_url(product_url: str) -> str:
    """Derive Cassinelli's read-only public VTEX product endpoint."""

    return build_vtex_catalog_url(
        product_url,
        normalize_product_url=normalize_cassinelli_product_url,
        api_host="www.cassinelli.com",
    )


def _cassinelli_offer_quality_flags(
    product: Mapping[str, Any],
    item: Mapping[str, Any],
    seller: Mapping[str, Any],
    offer: Mapping[str, Any],
) -> list[str]:
    flags = conditional_vtex_price_flags(product, item, seller, offer)
    unit = _normalized_unit(product.get("unitOriginal"))
    if unit and unit not in {"un", "unidad", "und", "piece", "pieza"}:
        flags.append("variable_measure_price_basis")
    return flags


def _normalized_unit(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.casefold().split())


_PARSER_CONFIG = VtexParserConfig(
    store_slug="cassinelli",
    display_name="Cassinelli",
    extractor_version=EXTRACTOR_VERSION,
    normalize_product_url=normalize_cassinelli_product_url,
    is_own_seller=lambda seller_id, _seller_name: seller_id == "1",
    payload_error=CassinelliPayloadError,
    offer_quality_flags=_cassinelli_offer_quality_flags,
)


def parse_cassinelli_products(
    payload: Any,
    source_url: str,
    tracked_product_id: UUID | str | None,
    observed_at: datetime | str,
) -> list[dict[str, Any]]:
    """Normalize Cassinelli into one observation per exact SKU and seller."""

    return parse_vtex_products(
        payload,
        source_url,
        tracked_product_id,
        observed_at,
        config=_PARSER_CONFIG,
    )


__all__ = [
    "CASSINELLI_HOSTS",
    "EXTRACTOR_VERSION",
    "CassinelliPayloadError",
    "build_cassinelli_catalog_url",
    "normalize_cassinelli_product_url",
    "parse_cassinelli_products",
]
