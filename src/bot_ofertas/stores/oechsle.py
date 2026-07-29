"""Oechsle pilot integration metadata."""

from __future__ import annotations

from bot_ofertas.crawling.oechsle import OECHSLE_HOSTS, normalize_oechsle_product_url
from bot_ofertas.crawling.spiders.oechsle_product import OechsleProductSpider
from bot_ofertas.stores.base import DiscoverySourceSpec, StoreAdapter, StorePolicy


class OechsleAdapter(StoreAdapter):
    slug = "oechsle"
    display_name = "Oechsle"
    hosts = OECHSLE_HOSTS
    policy = StorePolicy(
        enabled=True,
        minimum_interval_minutes=60,
        max_targets_per_run=5,
        requires_explicit_product_url=True,
        notes="Piloto limitado a URLs explicitas y al endpoint publico VTEX revisado.",
    )
    spider_class = OechsleProductSpider
    discovery_sources = (
        DiscoverySourceSpec(
            key="products-sitemap",
            url="https://www.oechsle.pe/sitemap.xml",
            max_candidates_per_run=75,
            daily_approval_limit=15,
            active_product_limit=400,
            notes=(
                "Índice oficial anunciado en robots.txt; se consulta solo un "
                "sitemap de productos por ejecución diaria."
            ),
        ),
    )

    def normalize_product_url(self, url: str) -> str:
        return normalize_oechsle_product_url(url)


__all__ = ["OechsleAdapter"]
