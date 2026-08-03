"""Falabella Peru integration metadata."""

from __future__ import annotations

from bot_ofertas.crawling.falabella import (
    FALABELLA_HOSTS,
    normalize_falabella_product_url,
)
from bot_ofertas.crawling.spiders.falabella_product import FalabellaProductSpider
from bot_ofertas.stores.base import DiscoverySourceSpec, StoreAdapter, StorePolicy


class FalabellaAdapter(StoreAdapter):
    slug = "falabella"
    display_name = "Falabella"
    hosts = FALABELLA_HOSTS
    policy = StorePolicy(
        enabled=True,
        minimum_interval_minutes=60,
        max_targets_per_run=10,
        requires_explicit_product_url=True,
        notes=(
            "Solo fichas públicas exactas; venta directa FALABELLA_PERU, "
            "PEN y condiciones CMR identificadas antes de alertar."
        ),
    )
    spider_class = FalabellaProductSpider
    discovery_sources = (
        DiscoverySourceSpec(
            key="pdp-sitemap",
            url=(
                "https://www.falabella.com.pe/static/site/sitemaps/"
                "pdp/pdp_pe_FA_COM-index.xml"
            ),
            max_candidates_per_run=100,
            daily_approval_limit=20,
            active_product_limit=300,
            child_path_pattern=(
                r"^/static/site/sitemaps/pdp/pdp_pe_FA_COM-\d+\.xml$"
            ),
            notes=(
                "Sitemap PDP oficial anunciado en robots.txt. El parser descarta "
                "Marketplace y valida el SKU exacto antes de generar ofertas."
            ),
        ),
    )

    def normalize_product_url(self, url: str) -> str:
        return normalize_falabella_product_url(url)


__all__ = ["FalabellaAdapter"]
