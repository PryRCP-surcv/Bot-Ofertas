"""Reviewed Wong Peru store integration metadata."""

from bot_ofertas.crawling.spiders.wong_product import WongProductSpider
from bot_ofertas.crawling.wong import WONG_HOSTS, normalize_wong_product_url
from bot_ofertas.stores.base import DiscoverySourceSpec, StoreAdapter, StorePolicy


class WongAdapter(StoreAdapter):
    slug = "wong"
    display_name = "Wong"
    hosts = WONG_HOSTS
    policy = StorePolicy(
        enabled=True,
        minimum_interval_minutes=60,
        max_targets_per_run=10,
        requires_explicit_product_url=True,
        notes=(
            "Catalogo publico VTEX de Wong Peru. Vendedor, unidad, precio y "
            "disponibilidad se validan; el delivery depende de la ubicacion."
        ),
    )
    spider_class = WongProductSpider
    discovery_sources = (
        DiscoverySourceSpec(
            key="products-sitemap",
            url="https://www.wong.pe/sitemap.xml",
            max_candidates_per_run=75,
            daily_approval_limit=40,
            active_product_limit=500,
            child_path_pattern=r"^/sitemap/product-\d+\.xml$",
            notes="Indice oficial anunciado en robots.txt.",
        ),
    )

    def normalize_product_url(self, url: str) -> str:
        return normalize_wong_product_url(url)


__all__ = ["WongAdapter"]
