"""Topitop wrappers around its reviewed public VTEX product catalogue."""

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

TOPITOP_HOSTS = frozenset({"topitop.pe", "www.topitop.pe"})
EXTRACTOR_VERSION = "topitop-vtex-v1"
_OWN_SELLER_ID = "1"
_OWN_SELLER_NAMES = frozenset({"Trading Fashion Line S.A.", "Trading Fashion Line S.A"})


class TopitopPayloadError(VtexPayloadError):
    """Raised when Topitop's public response no longer matches the reviewed shape."""


def normalize_topitop_product_url(url: str) -> str:
    return normalize_root_vtex_product_url(
        url,
        hosts=TOPITOP_HOSTS,
        canonical_host="www.topitop.pe",
        display_name="Topitop",
    )


def build_topitop_catalog_url(product_url: str) -> str:
    return build_vtex_catalog_url(
        product_url,
        normalize_product_url=normalize_topitop_product_url,
        api_host="www.topitop.pe",
    )


def is_topitop_own_seller(seller_id: str, seller_name: str) -> bool:
    return is_exact_own_seller(
        seller_id,
        seller_name,
        expected_id=_OWN_SELLER_ID,
        expected_names=_OWN_SELLER_NAMES,
    )


def _topitop_offer_quality_flags(
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
        ambiguous_seller_flag="ambiguous_topitop_seller_identity",
        delivery_location_confirmation=False,
    )


_PARSER_CONFIG = VtexParserConfig(
    store_slug="topitop",
    display_name="Topitop",
    extractor_version=EXTRACTOR_VERSION,
    normalize_product_url=normalize_topitop_product_url,
    is_own_seller=is_topitop_own_seller,
    payload_error=TopitopPayloadError,
    offer_quality_flags=_topitop_offer_quality_flags,
)


def parse_topitop_products(
    payload: Any,
    source_url: str,
    tracked_product_id: UUID | str | None,
    observed_at: datetime | str,
) -> list[dict[str, Any]]:
    validate_vtex_payload_identity(
        payload,
        source_url,
        normalize_product_url=normalize_topitop_product_url,
        display_name="Topitop",
        payload_error=TopitopPayloadError,
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
    "TOPITOP_HOSTS",
    "TopitopPayloadError",
    "build_topitop_catalog_url",
    "is_topitop_own_seller",
    "normalize_topitop_product_url",
    "parse_topitop_products",
]
