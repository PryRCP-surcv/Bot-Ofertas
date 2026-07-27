"""Coolbox store integration metadata."""

from __future__ import annotations

from bot_ofertas.crawling.coolbox import COOLBOX_HOSTS, normalize_coolbox_product_url
from bot_ofertas.crawling.spiders.coolbox_product import CoolboxProductSpider
from bot_ofertas.stores.base import StoreAdapter, StorePolicy


class CoolboxAdapter(StoreAdapter):
    slug = "coolbox"
    display_name = "Coolbox"
    hosts = COOLBOX_HOSTS
    policy = StorePolicy(
        enabled=True,
        minimum_interval_minutes=30,
        max_targets_per_run=20,
        requires_explicit_product_url=True,
        notes="Piloto habilitado sobre el catálogo público VTEX revisado.",
    )
    spider_class = CoolboxProductSpider

    def normalize_product_url(self, url: str) -> str:
        return normalize_coolbox_product_url(url)


__all__ = ["CoolboxAdapter"]
