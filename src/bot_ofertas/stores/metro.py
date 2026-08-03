"""Reviewed Metro Peru store integration metadata."""

from bot_ofertas.crawling.metro import METRO_HOSTS, normalize_metro_product_url
from bot_ofertas.crawling.spiders.metro_product import MetroProductSpider
from bot_ofertas.stores.base import DiscoverySourceSpec, StoreAdapter, StorePolicy


class MetroAdapter(StoreAdapter):
    slug = "metro"
    display_name = "Metro"
    hosts = METRO_HOSTS
    policy = StorePolicy(
        enabled=True,
        minimum_interval_minutes=60,
        max_targets_per_run=10,
        requires_explicit_product_url=True,
        notes=(
            "Catálogo público VTEX de Metro Perú. Solo las bases unitarias "
            "exactas son elegibles; peso, vendedor y delivery se validan."
        ),
    )
    spider_class = MetroProductSpider
    discovery_sources = (
        DiscoverySourceSpec(
            key="products-sitemap",
            url="https://www.metro.pe/sitemap.xml",
            max_candidates_per_run=75,
            daily_approval_limit=40,
            active_product_limit=500,
            child_path_pattern=r"^/sitemap/product-\d+\.xml$",
            notes=(
                "Índice oficial anunciado en robots.txt; se rota un sitemap "
                "de productos por ejecución diaria."
            ),
        ),
    )

    def normalize_product_url(self, url: str) -> str:
        return normalize_metro_product_url(url)


__all__ = ["MetroAdapter"]
