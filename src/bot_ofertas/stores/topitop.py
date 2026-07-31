"""Reviewed Topitop store integration metadata."""

from bot_ofertas.crawling.spiders.topitop_product import TopitopProductSpider
from bot_ofertas.crawling.topitop import TOPITOP_HOSTS, normalize_topitop_product_url
from bot_ofertas.stores.base import DiscoverySourceSpec, StoreAdapter, StorePolicy


class TopitopAdapter(StoreAdapter):
    slug = "topitop"
    display_name = "Topitop"
    hosts = TOPITOP_HOSTS
    policy = StorePolicy(
        enabled=True,
        minimum_interval_minutes=60,
        max_targets_per_run=10,
        requires_explicit_product_url=True,
        notes=(
            "Catálogo público VTEX con SKU por talla, vendedor propio verificado "
            "y precio total separado de promociones o cuotas."
        ),
    )
    spider_class = TopitopProductSpider
    discovery_sources = (
        DiscoverySourceSpec(
            key="products-sitemap",
            url="https://www.topitop.pe/sitemap.xml",
            max_candidates_per_run=50,
            daily_approval_limit=40,
            active_product_limit=300,
            notes=(
                "Índice oficial anunciado en robots.txt; se rota un sitemap de "
                "productos por ejecución diaria."
            ),
        ),
    )

    def normalize_product_url(self, url: str) -> str:
        return normalize_topitop_product_url(url)


__all__ = ["TopitopAdapter"]
