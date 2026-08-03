"""Reviewed Casaideas Peru store integration metadata."""

from bot_ofertas.crawling.casaideas import (
    CASAIDEAS_HOSTS,
    normalize_casaideas_product_url,
)
from bot_ofertas.crawling.spiders.casaideas_product import CasaideasProductSpider
from bot_ofertas.stores.base import DiscoverySourceSpec, StoreAdapter, StorePolicy


class CasaideasAdapter(StoreAdapter):
    slug = "casaideas"
    display_name = "Casaideas"
    hosts = CASAIDEAS_HOSTS
    policy = StorePolicy(
        enabled=True,
        minimum_interval_minutes=60,
        max_targets_per_run=10,
        requires_explicit_product_url=True,
        notes=(
            "Catalogo publico VTEX de Casaideas Peru. SKU, vendedor, unidad, "
            "precio y disponibilidad se validan antes de detectar ofertas."
        ),
    )
    spider_class = CasaideasProductSpider
    discovery_sources = (
        DiscoverySourceSpec(
            key="products-sitemap",
            url="https://www.casaideas.com.pe/sitemap.xml",
            max_candidates_per_run=75,
            daily_approval_limit=40,
            active_product_limit=500,
            child_path_pattern=r"^/sitemap/product-\d+\.xml$",
            notes="Indice oficial publico con sitemaps de productos.",
        ),
    )

    def normalize_product_url(self, url: str) -> str:
        return normalize_casaideas_product_url(url)


__all__ = ["CasaideasAdapter"]
