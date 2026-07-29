"""EFE-specific policy around its reviewed public Magento product pages."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from bot_ofertas.crawling.magento import (
    MagentoParserConfig,
    normalize_magento_product_url,
    parse_magento_product,
)

EFE_HOSTS = frozenset({"efe.com.pe", "www.efe.com.pe"})
EXTRACTOR_VERSION = "efe-magento-jsonld-v1"

EFE_PARSER_CONFIG = MagentoParserConfig(
    store_slug="efe",
    display_name="EFE",
    extractor_version=EXTRACTOR_VERSION,
    hosts=EFE_HOSTS,
    canonical_host="www.efe.com.pe",
    own_seller_names=frozenset({"Tiendas EFE", "EFE"}),
)


def normalize_efe_product_url(url: str) -> str:
    return normalize_magento_product_url(url, config=EFE_PARSER_CONFIG)


def parse_efe_product(
    payload: Any,
    source_url: str,
    tracked_product_id: UUID | str | None,
    observed_at: datetime | str,
) -> list[dict[str, Any]]:
    return parse_magento_product(
        payload,
        source_url,
        tracked_product_id,
        observed_at,
        config=EFE_PARSER_CONFIG,
    )


__all__ = [
    "EFE_HOSTS",
    "EFE_PARSER_CONFIG",
    "EXTRACTOR_VERSION",
    "normalize_efe_product_url",
    "parse_efe_product",
]
