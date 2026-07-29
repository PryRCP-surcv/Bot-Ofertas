"""La Curacao policy around its reviewed public Magento product pages."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from bot_ofertas.crawling.magento import (
    MagentoParserConfig,
    normalize_magento_product_url,
    parse_magento_product,
)

CURACAO_HOSTS = frozenset({"lacuracao.pe", "www.lacuracao.pe"})
EXTRACTOR_VERSION = "curacao-magento-jsonld-v1"

CURACAO_PARSER_CONFIG = MagentoParserConfig(
    store_slug="curacao",
    display_name="La Curacao",
    extractor_version=EXTRACTOR_VERSION,
    hosts=CURACAO_HOSTS,
    canonical_host="www.lacuracao.pe",
    own_seller_names=frozenset({"La Curacao", "Curacao"}),
)


def normalize_curacao_product_url(url: str) -> str:
    return normalize_magento_product_url(url, config=CURACAO_PARSER_CONFIG)


def parse_curacao_product(
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
        config=CURACAO_PARSER_CONFIG,
    )


__all__ = [
    "CURACAO_HOSTS",
    "CURACAO_PARSER_CONFIG",
    "EXTRACTOR_VERSION",
    "normalize_curacao_product_url",
    "parse_curacao_product",
]
