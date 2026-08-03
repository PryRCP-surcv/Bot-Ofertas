"""Wong wrappers around its reviewed public VTEX product catalogue."""

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

WONG_HOSTS = frozenset({"wong.pe", "www.wong.pe"})
EXTRACTOR_VERSION = "wong-vtex-v1"
_OWN_SELLER_ID = "1"
_OWN_SELLER_NAMES = frozenset({"WongIO"})


class WongPayloadError(VtexPayloadError):
    """Raised when Wong's public response no longer matches the reviewed shape."""


def normalize_wong_product_url(url: str) -> str:
    return normalize_root_vtex_product_url(
        url,
        hosts=WONG_HOSTS,
        canonical_host="www.wong.pe",
        display_name="Wong",
    )


def build_wong_catalog_url(product_url: str) -> str:
    return build_vtex_catalog_url(
        product_url,
        normalize_product_url=normalize_wong_product_url,
        api_host="www.wong.pe",
    )


def is_wong_own_seller(seller_id: str, seller_name: str) -> bool:
    return is_exact_own_seller(
        seller_id,
        seller_name,
        expected_id=_OWN_SELLER_ID,
        expected_names=_OWN_SELLER_NAMES,
    )


def _wong_offer_quality_flags(
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
        ambiguous_seller_flag="ambiguous_wong_seller_identity",
        delivery_location_confirmation=True,
    )


_PARSER_CONFIG = VtexParserConfig(
    store_slug="wong",
    display_name="Wong",
    extractor_version=EXTRACTOR_VERSION,
    normalize_product_url=normalize_wong_product_url,
    is_own_seller=is_wong_own_seller,
    payload_error=WongPayloadError,
    offer_quality_flags=_wong_offer_quality_flags,
)


def parse_wong_products(
    payload: Any,
    source_url: str,
    tracked_product_id: UUID | str | None,
    observed_at: datetime | str,
) -> list[dict[str, Any]]:
    validate_vtex_payload_identity(
        payload,
        source_url,
        normalize_product_url=normalize_wong_product_url,
        display_name="Wong",
        payload_error=WongPayloadError,
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
    "WONG_HOSTS",
    "WongPayloadError",
    "build_wong_catalog_url",
    "is_wong_own_seller",
    "normalize_wong_product_url",
    "parse_wong_products",
]
