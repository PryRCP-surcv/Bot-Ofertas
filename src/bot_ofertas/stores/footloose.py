"""Reviewed Footloose Peru store integration metadata."""

from bot_ofertas.crawling.footloose import (
    FOOTLOOSE_HOSTS,
    normalize_footloose_product_url,
)
from bot_ofertas.crawling.spiders.footloose_product import FootlooseProductSpider
from bot_ofertas.stores.base import DiscoverySourceSpec, StoreAdapter, StorePolicy


class FootlooseAdapter(StoreAdapter):
    slug = "footloose"
    display_name = "Footloose"
    hosts = FOOTLOOSE_HOSTS
    policy = StorePolicy(
        enabled=True,
        minimum_interval_minutes=60,
        max_targets_per_run=10,
        requires_explicit_product_url=True,
        allow_all_exact_variants=True,
        notes=(
            "Catalogo publico VTEX de Footloose Peru. Cada talla se conserva "
            "como SKU independiente y solo se acepta al vendedor propio."
        ),
    )
    spider_class = FootlooseProductSpider
    discovery_sources = (
        DiscoverySourceSpec(
            key="products-sitemap",
            url="https://www.footloose.pe/sitemap.xml",
            max_candidates_per_run=75,
            daily_approval_limit=40,
            active_product_limit=500,
            child_path_pattern=r"^/sitemap/product-\d+\.xml$",
            notes="Indice oficial publico con sitemaps de productos.",
        ),
    )

    def normalize_product_url(self, url: str) -> str:
        return normalize_footloose_product_url(url)


__all__ = ["FootlooseAdapter"]
