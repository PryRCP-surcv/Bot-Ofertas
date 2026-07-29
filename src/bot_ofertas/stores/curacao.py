"""Reviewed La Curacao store integration metadata."""

from __future__ import annotations

from bot_ofertas.crawling.curacao import CURACAO_HOSTS, normalize_curacao_product_url
from bot_ofertas.crawling.spiders.curacao_product import CuracaoProductSpider
from bot_ofertas.stores.base import DiscoverySourceSpec, StoreAdapter, StorePolicy


class CuracaoAdapter(StoreAdapter):
    slug = "curacao"
    display_name = "La Curacao"
    hosts = CURACAO_HOSTS
    policy = StorePolicy(
        enabled=True,
        minimum_interval_minutes=60,
        max_targets_per_run=5,
        requires_explicit_product_url=True,
        notes=(
            "Piloto Magento basado en JSON-LD y precio HTML concordante. "
            "Se conserva la identidad del vendedor para distinguir marketplace."
        ),
    )
    spider_class = CuracaoProductSpider
    discovery_sources = (
        DiscoverySourceSpec(
            key="catalog-sitemap",
            url="https://www.lacuracao.pe/media/sitemap/sitemap_curacao.xml",
            max_candidates_per_run=50,
            daily_approval_limit=10,
            active_product_limit=300,
            child_path_pattern=r"^/media/sitemap/sitemap_curacao-\d+-\d+\.xml$",
            url_entry_filter="has_image",
            notes=(
                "Sitemap oficial anunciado en robots.txt. Como mezcla categorías "
                "y productos, solo se consideran entradas con imagen de producto."
            ),
        ),
    )

    def normalize_product_url(self, url: str) -> str:
        return normalize_curacao_product_url(url)


__all__ = ["CuracaoAdapter"]
