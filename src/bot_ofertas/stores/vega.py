"""Reviewed Vega store integration metadata."""

from bot_ofertas.crawling.spiders.vega_product import VegaProductSpider
from bot_ofertas.crawling.vega import VEGA_HOSTS, normalize_vega_product_url
from bot_ofertas.stores.base import DiscoverySourceSpec, StoreAdapter, StorePolicy


class VegaAdapter(StoreAdapter):
    slug = "vega"
    display_name = "Vega"
    hosts = VEGA_HOSTS
    policy = StorePolicy(
        enabled=True,
        minimum_interval_minutes=60,
        max_targets_per_run=5,
        requires_explicit_product_url=True,
        notes=(
            "Catálogo público VTEX de Vega Perú. Solo vendedor propio y base "
            "unitaria; confirmar delivery para el distrito de Lima."
        ),
    )
    spider_class = VegaProductSpider
    discovery_sources = (
        DiscoverySourceSpec(
            key="products-sitemap",
            url="https://www.vega.pe/sitemap.xml",
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
        return normalize_vega_product_url(url)


__all__ = ["VegaAdapter"]
