"""Bounded Tottus Peru product spider."""

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from scrapy.http import Response

from bot_ofertas.crawling.spiders.base_product import BoundedProductSpider
from bot_ofertas.crawling.tottus import (
    TOTTUS_HOSTS,
    normalize_tottus_product_url,
    parse_tottus_product,
)


class TottusProductSpider(BoundedProductSpider):
    name = "tottus_product"
    store_slug = "tottus"
    display_name = "Tottus"
    allowed_domains = ["tottus.com.pe", "www.tottus.com.pe"]
    request_hosts = TOTTUS_HOSTS
    max_targets = 10

    def normalize_product_url(self, url: str) -> str:
        return normalize_tottus_product_url(url)

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
            raise TypeError("Tottus product payload must be a Scrapy response")
        return parse_tottus_product(
            payload,
            source_url,
            tracked_product_id,
            observed_at,
        )


__all__ = ["TottusProductSpider"]
