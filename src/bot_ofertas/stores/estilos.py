"""Reviewed Estilos store integration metadata."""

from bot_ofertas.crawling.estilos import ESTILOS_HOSTS, normalize_estilos_product_url
from bot_ofertas.crawling.spiders.estilos_product import EstilosProductSpider
from bot_ofertas.stores.base import DiscoverySourceSpec, StoreAdapter, StorePolicy


class EstilosAdapter(StoreAdapter):
    slug = "estilos"
    display_name = "Estilos"
    hosts = ESTILOS_HOSTS
    policy = StorePolicy(
        enabled=True,
        minimum_interval_minutes=60,
        max_targets_per_run=10,
        requires_explicit_product_url=True,
        notes=(
            "Catálogo público VTEX de Estilos Perú. Conserva SKU, vendedor, "
            "unidad y condiciones comerciales; la entrega depende de ubicación."
        ),
    )
    spider_class = EstilosProductSpider
    discovery_sources = (
        DiscoverySourceSpec(
            key="products-sitemap",
            url="https://www.estilos.com.pe/sitemap.xml",
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
        return normalize_estilos_product_url(url)


__all__ = ["EstilosAdapter"]
