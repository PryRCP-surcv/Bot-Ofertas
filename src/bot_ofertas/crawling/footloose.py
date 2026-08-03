"""Footloose wrappers around its reviewed public VTEX product catalogue."""

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

FOOTLOOSE_HOSTS = frozenset({"footloose.pe", "www.footloose.pe"})
EXTRACTOR_VERSION = "footloose-vtex-v1"
_OWN_SELLER_ID = "1"
_OWN_SELLER_NAMES = frozenset({"Inversiones Rubin's SAC"})


class FootloosePayloadError(VtexPayloadError):
    """Raised when Footloose's public response no longer matches the reviewed shape."""


def normalize_footloose_product_url(url: str) -> str:
    return normalize_root_vtex_product_url(
        url,
        hosts=FOOTLOOSE_HOSTS,
        canonical_host="www.footloose.pe",
        display_name="Footloose",
    )


def build_footloose_catalog_url(product_url: str) -> str:
    return build_vtex_catalog_url(
        product_url,
        normalize_product_url=normalize_footloose_product_url,
        api_host="www.footloose.pe",
    )


def is_footloose_own_seller(seller_id: str, seller_name: str) -> bool:
    return is_exact_own_seller(
        seller_id,
        seller_name,
        expected_id=_OWN_SELLER_ID,
        expected_names=_OWN_SELLER_NAMES,
    )


def _footloose_offer_quality_flags(
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
        ambiguous_seller_flag="ambiguous_footloose_seller_identity",
        delivery_location_confirmation=False,
    )


_PARSER_CONFIG = VtexParserConfig(
    store_slug="footloose",
    display_name="Footloose",
    extractor_version=EXTRACTOR_VERSION,
    normalize_product_url=normalize_footloose_product_url,
    is_own_seller=is_footloose_own_seller,
    payload_error=FootloosePayloadError,
    offer_quality_flags=_footloose_offer_quality_flags,
)


def parse_footloose_products(
    payload: Any,
    source_url: str,
    tracked_product_id: UUID | str | None,
    observed_at: datetime | str,
) -> list[dict[str, Any]]:
    validate_vtex_payload_identity(
        payload,
        source_url,
        normalize_product_url=normalize_footloose_product_url,
        display_name="Footloose",
        payload_error=FootloosePayloadError,
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
    "FOOTLOOSE_HOSTS",
    "FootloosePayloadError",
    "build_footloose_catalog_url",
    "is_footloose_own_seller",
    "normalize_footloose_product_url",
    "parse_footloose_products",
]
