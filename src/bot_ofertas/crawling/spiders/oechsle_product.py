"""Bounded Oechsle spider backed by its reviewed public VTEX catalog endpoint."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from bot_ofertas.crawling.oechsle import (
    OECHSLE_HOSTS,
    build_oechsle_catalog_url,
    normalize_oechsle_product_url,
    parse_oechsle_products,
)
from bot_ofertas.crawling.spiders.base_product import JsonProductSpider


class OechsleProductSpider(JsonProductSpider):
    """Observe at most five explicitly supplied Oechsle product pages."""

    name = "oechsle_product"
    store_slug = "oechsle"
    display_name = "Oechsle"
    allowed_domains = ["oechsle.pe", "www.oechsle.pe"]
    request_hosts = OECHSLE_HOSTS
    max_targets = 5

    def normalize_product_url(self, url: str) -> str:
        return normalize_oechsle_product_url(url)

    def build_request_url(self, source_url: str) -> str:
        return build_oechsle_catalog_url(source_url)

    def parse_payload(
        self,
        *,
        payload: Any,
        source_url: str,
        tracked_product_id: str | None,
        observed_at: datetime,
    ) -> Iterable[Mapping[str, Any]]:
        return parse_oechsle_products(
            payload=payload,
            source_url=source_url,
            tracked_product_id=tracked_product_id,
            observed_at=observed_at,
        )


__all__ = ["OechsleProductSpider"]
