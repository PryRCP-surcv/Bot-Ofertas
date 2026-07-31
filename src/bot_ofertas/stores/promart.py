"""Promart pilot integration metadata."""

from __future__ import annotations

from bot_ofertas.crawling.promart import PROMART_HOSTS, normalize_promart_product_url
from bot_ofertas.crawling.spiders.promart_product import PromartProductSpider
from bot_ofertas.stores.base import DiscoverySourceSpec, StoreAdapter, StorePolicy


class PromartAdapter(StoreAdapter):
    slug = "promart"
    display_name = "Promart"
    hosts = PROMART_HOSTS
    policy = StorePolicy(
        enabled=True,
        minimum_interval_minutes=60,
        max_targets_per_run=5,
        requires_explicit_product_url=True,
        notes=(
            "Historial piloto de unidad fija; alertas bloqueadas hasta modelar "
            "ubicacion."
        ),
    )
    spider_class = PromartProductSpider
    discovery_sources = (
        DiscoverySourceSpec(
            key="products-sitemap",
            url="https://www.promart.pe/sitemap.xml",
            max_candidates_per_run=75,
            daily_approval_limit=20,
            active_product_limit=400,
            notes=(
                "Índice oficial anunciado en robots.txt; los productos aprobados "
                "mantienen el bloqueo de alertas hasta verificar ubicación."
            ),
        ),
    )

    def normalize_product_url(self, url: str) -> str:
        return normalize_promart_product_url(url)


__all__ = ["PromartAdapter"]
