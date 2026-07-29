"""Reusable bounded HTML spider for reviewed Magento JSON-LD product pages."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, ClassVar

from scrapy.http import Response

from bot_ofertas.crawling.magento import (
    MagentoParserConfig,
    normalize_magento_product_url,
    parse_magento_product,
)
from bot_ofertas.crawling.spiders.base_product import BoundedProductSpider


class MagentoProductSpider(BoundedProductSpider):
    """Fetch an exact product page and parse only consistent structured evidence."""

    parser_config: ClassVar[MagentoParserConfig]

    def normalize_product_url(self, url: str) -> str:
        return normalize_magento_product_url(url, config=self.parser_config)

    def build_request_url(self, source_url: str) -> str:
        return self.normalize_product_url(source_url)

    def decode_response(self, response: Response) -> Response:
        return response

    def parse_payload(
        self,
        *,
        payload: Any,
        source_url: str,
        tracked_product_id: str | None,
        observed_at: datetime,
    ) -> Iterable[Mapping[str, Any]]:
        if not isinstance(payload, Response):
            raise TypeError("Magento product payload must be a Scrapy response")
        return parse_magento_product(
            payload,
            source_url,
            tracked_product_id,
            observed_at,
            config=self.parser_config,
        )


__all__ = ["MagentoProductSpider"]
