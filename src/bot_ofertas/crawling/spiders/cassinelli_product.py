"""Bounded Cassinelli product spider backed by its public VTEX endpoint."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from bot_ofertas.crawling.cassinelli import (
    CASSINELLI_HOSTS,
    build_cassinelli_catalog_url,
    normalize_cassinelli_product_url,
    parse_cassinelli_products,
)
from bot_ofertas.crawling.spiders.base_product import JsonProductSpider


class CassinelliProductSpider(JsonProductSpider):
    """Observe at most ten explicitly approved Cassinelli product pages."""

    name = "cassinelli_product"
    store_slug = "cassinelli"
    display_name = "Cassinelli"
    allowed_domains = ["cassinelli.com", "www.cassinelli.com"]
    request_hosts = CASSINELLI_HOSTS
    max_targets = 10

    def normalize_product_url(self, url: str) -> str:
        return normalize_cassinelli_product_url(url)

    def build_request_url(self, source_url: str) -> str:
        return build_cassinelli_catalog_url(source_url)

    def parse_payload(
        self,
        *,
        payload: Any,
        source_url: str,
        tracked_product_id: str | None,
        observed_at: datetime,
    ) -> Iterable[Mapping[str, Any]]:
        return parse_cassinelli_products(
            payload,
            source_url,
            tracked_product_id,
            observed_at,
        )


__all__ = ["CassinelliProductSpider"]
