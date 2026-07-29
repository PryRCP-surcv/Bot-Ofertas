"""Reviewed Cassinelli store integration metadata."""

from __future__ import annotations

from bot_ofertas.crawling.cassinelli import (
    CASSINELLI_HOSTS,
    normalize_cassinelli_product_url,
)
from bot_ofertas.crawling.spiders.cassinelli_product import CassinelliProductSpider
from bot_ofertas.stores.base import DiscoverySourceSpec, StoreAdapter, StorePolicy


class CassinelliAdapter(StoreAdapter):
    slug = "cassinelli"
    display_name = "Cassinelli"
    hosts = CASSINELLI_HOSTS
    policy = StorePolicy(
        enabled=True,
        minimum_interval_minutes=60,
        max_targets_per_run=10,
        requires_explicit_product_url=True,
        notes=(
            "Catálogo público VTEX revisado. Los productos cuyo precio depende "
            "de peso o medida guardan historial, pero no generan alertas todavía."
        ),
    )
    spider_class = CassinelliProductSpider
    discovery_sources = (
        DiscoverySourceSpec(
            key="products-sitemap",
            url="https://www.cassinelli.com/sitemap.xml",
            max_candidates_per_run=50,
            daily_approval_limit=10,
            active_product_limit=300,
            notes=(
                "Índice público revisado; se rota como máximo un sitemap de "
                "productos por ejecución diaria."
            ),
        ),
    )

    def normalize_product_url(self, url: str) -> str:
        return normalize_cassinelli_product_url(url)


__all__ = ["CassinelliAdapter"]
