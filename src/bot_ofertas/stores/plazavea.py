"""Reviewed plazaVea store integration metadata."""

from bot_ofertas.crawling.plazavea import (
    PLAZAVEA_HOSTS,
    normalize_plazavea_product_url,
)
from bot_ofertas.crawling.spiders.plazavea_product import PlazaVeaProductSpider
from bot_ofertas.stores.base import DiscoverySourceSpec, StoreAdapter, StorePolicy


class PlazaVeaAdapter(StoreAdapter):
    slug = "plazavea"
    display_name = "plazaVea"
    hosts = PLAZAVEA_HOSTS
    policy = StorePolicy(
        enabled=True,
        minimum_interval_minutes=60,
        max_targets_per_run=5,
        requires_explicit_product_url=True,
        notes=(
            "Catálogo público VTEX. Solo vendedor plazaVea y base unitaria; "
            "marketplace, peso variable y ubicación ambigua permanecen bloqueados."
        ),
    )
    spider_class = PlazaVeaProductSpider
    discovery_sources = (
        DiscoverySourceSpec(
            key="products-sitemap",
            url="https://www.plazavea.com.pe/sitemap.xml",
            max_candidates_per_run=50,
            daily_approval_limit=40,
            active_product_limit=300,
            notes=(
                "Índice oficial anunciado en robots.txt; la aprobación debe "
                "priorizar productos empacados de unidad fija y vendedor propio."
            ),
        ),
    )

    def normalize_product_url(self, url: str) -> str:
        return normalize_plazavea_product_url(url)


__all__ = ["PlazaVeaAdapter"]
