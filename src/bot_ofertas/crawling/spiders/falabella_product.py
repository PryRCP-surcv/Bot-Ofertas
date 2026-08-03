"""Bounded Falabella Peru product spider."""

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from scrapy.http import Response

from bot_ofertas.crawling.falabella import (
    FALABELLA_HOSTS,
    normalize_falabella_product_url,
    parse_falabella_product,
)
from bot_ofertas.crawling.spiders.base_product import BoundedProductSpider


class FalabellaProductSpider(BoundedProductSpider):
    name = "falabella_product"
    store_slug = "falabella"
    display_name = "Falabella"
    allowed_domains = ["falabella.com.pe", "www.falabella.com.pe"]
    request_hosts = FALABELLA_HOSTS
    max_targets = 10

    def normalize_product_url(self, url: str) -> str:
        return normalize_falabella_product_url(url)

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
            raise TypeError("Falabella product payload must be a Scrapy response")
        return parse_falabella_product(
            payload,
            source_url,
            tracked_product_id,
            observed_at,
        )


__all__ = ["FalabellaProductSpider"]
