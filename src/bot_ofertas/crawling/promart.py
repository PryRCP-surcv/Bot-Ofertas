"""Promart-specific policy around its reviewed public VTEX product endpoint."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from bot_ofertas.crawling.retail_vtex import (
    is_exact_own_seller,
    normalize_root_vtex_product_url,
    reviewed_retail_offer_quality_flags,
    validate_vtex_payload_identity,
)
from bot_ofertas.crawling.vtex import (
    VtexParserConfig,
    VtexPayloadError,
    build_vtex_catalog_url,
    parse_vtex_products,
)

PROMART_HOSTS = frozenset({"promart.pe", "www.promart.pe"})
EXTRACTOR_VERSION = "promart-vtex-v2"
_OWN_SELLER_ID = "1"
_OWN_SELLER_NAMES = frozenset({"Promart"})


class PromartPayloadError(VtexPayloadError):
    """Raised when Promart's public response no longer matches the reviewed shape."""


def normalize_promart_product_url(url: str) -> str:
    """Accept only explicit canonical Promart product-detail paths."""

    return normalize_root_vtex_product_url(
        url,
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

    return is_exact_own_seller(
        seller_id,
        seller_name,
        expected_id=_OWN_SELLER_ID,
        expected_names=_OWN_SELLER_NAMES,
    )


def _promart_offer_quality_flags(
    product: Mapping[str, Any],
    item: Mapping[str, Any],
    seller: Mapping[str, Any],
    offer: Mapping[str, Any],
) -> list[str]:
    return reviewed_retail_offer_quality_flags(
        product,
        item,
        seller,
        offer,
        expected_seller_id=_OWN_SELLER_ID,
        expected_seller_names=_OWN_SELLER_NAMES,
        ambiguous_seller_flag="ambiguous_promart_seller_identity",
        delivery_location_confirmation=True,
    )


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

    validate_vtex_payload_identity(
        payload,
        source_url,
        normalize_product_url=normalize_promart_product_url,
        display_name="Promart",
        payload_error=PromartPayloadError,
    )
    return parse_vtex_products(
        payload,
        source_url,
        tracked_product_id,
        observed_at,
        config=_PARSER_CONFIG,
    )


__all__ = [
    "EXTRACTOR_VERSION",
    "PROMART_HOSTS",
    "PromartPayloadError",
    "build_promart_catalog_url",
    "is_promart_own_seller",
    "normalize_promart_product_url",
    "parse_promart_products",
]
