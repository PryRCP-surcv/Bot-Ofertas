"""Bounded Coolbox product spider backed by the public VTEX catalog API."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from bot_ofertas.crawling.coolbox import (
    COOLBOX_HOSTS,
    build_coolbox_catalog_url,
    normalize_coolbox_product_url,
    parse_coolbox_products,
)
from bot_ofertas.crawling.spiders.base_product import JsonProductSpider


class CoolboxProductSpider(JsonProductSpider):
    """Observe up to 20 explicitly supplied Coolbox product pages."""

    name = "coolbox_product"
    store_slug = "coolbox"
    display_name = "Coolbox"
    allowed_domains = ["coolbox.pe", "www.coolbox.pe"]
    request_hosts = COOLBOX_HOSTS
    max_targets = 20

    def normalize_product_url(self, url: str) -> str:
        return normalize_coolbox_product_url(url)

    def build_request_url(self, source_url: str) -> str:
        return build_coolbox_catalog_url(source_url)

    def parse_payload(
        self,
        *,
        payload: Any,
        source_url: str,
        tracked_product_id: str | None,
        observed_at: datetime,
    ) -> Iterable[Mapping[str, Any]]:
        return parse_coolbox_products(
            payload=payload,
            source_url=source_url,
            tracked_product_id=tracked_product_id,
            observed_at=observed_at,
        )


__all__ = ["CoolboxProductSpider"]
