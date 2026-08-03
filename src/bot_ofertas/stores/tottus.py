"""Reviewed Tottus Peru store integration metadata."""

from bot_ofertas.crawling.spiders.tottus_product import TottusProductSpider
from bot_ofertas.crawling.tottus import TOTTUS_HOSTS, normalize_tottus_product_url
from bot_ofertas.stores.base import DiscoverySourceSpec, StoreAdapter, StorePolicy


class TottusAdapter(StoreAdapter):
    slug = "tottus"
    display_name = "Tottus"
    hosts = TOTTUS_HOSTS
    policy = StorePolicy(
        enabled=True,
        minimum_interval_minutes=60,
        max_targets_per_run=10,
        requires_explicit_product_url=True,
        notes=(
            "Ficha pública peruana con producto, variante, vendedor, precio "
            "normal/oferta y stock validados entre Next data y JSON-LD."
        ),
    )
    spider_class = TottusProductSpider
    discovery_sources = (
        DiscoverySourceSpec(
            key="products-sitemap",
            url=(
                "https://www.tottus.com.pe/static/site/sitemaps/pdp/"
                "pdp_pe_TO_COM-index.xml"
            ),
            max_candidates_per_run=75,
            daily_approval_limit=40,
            active_product_limit=500,
            child_path_pattern=(
                r"^/static/site/sitemaps/pdp/pdp_pe_TO_COM-\d+\.xml$"
            ),
            url_entry_filter="exclude_placeholder_slugs",
            notes=(
                "Índice PDP oficial anunciado en robots.txt; contiene fichas "
                "de producto de la tienda peruana."
            ),
        ),
    )

    def normalize_product_url(self, url: str) -> str:
        return normalize_tottus_product_url(url)


__all__ = ["TottusAdapter"]
