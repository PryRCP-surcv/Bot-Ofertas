"""Bounded Promart spider backed by its reviewed public VTEX catalog endpoint."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from bot_ofertas.crawling.promart import (
    PROMART_HOSTS,
    build_promart_catalog_url,
    normalize_promart_product_url,
    parse_promart_products,
)
from bot_ofertas.crawling.spiders.base_product import JsonProductSpider


class PromartProductSpider(JsonProductSpider):
    """Observe at most five explicitly supplied Promart product pages."""

    name = "promart_product"
    store_slug = "promart"
    display_name = "Promart"
    allowed_domains = ["promart.pe", "www.promart.pe"]
    request_hosts = PROMART_HOSTS
    max_targets = 5

    def normalize_product_url(self, url: str) -> str:
        return normalize_promart_product_url(url)

    def build_request_url(self, source_url: str) -> str:
        return build_promart_catalog_url(source_url)

    def parse_payload(
        self,
        *,
        payload: Any,
        source_url: str,
        tracked_product_id: str | None,
        observed_at: datetime,
    ) -> Iterable[Mapping[str, Any]]:
        return parse_promart_products(
            payload=payload,
            source_url=source_url,
            tracked_product_id=tracked_product_id,
            observed_at=observed_at,
        )


__all__ = ["PromartProductSpider"]
