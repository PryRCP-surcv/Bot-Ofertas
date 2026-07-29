"""Reviewed EFE store integration metadata."""

from __future__ import annotations

from bot_ofertas.crawling.efe import EFE_HOSTS, normalize_efe_product_url
from bot_ofertas.crawling.spiders.efe_product import EfeProductSpider
from bot_ofertas.stores.base import DiscoverySourceSpec, StoreAdapter, StorePolicy


class EfeAdapter(StoreAdapter):
    slug = "efe"
    display_name = "EFE"
    hosts = EFE_HOSTS
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
    spider_class = EfeProductSpider
    discovery_sources = (
        DiscoverySourceSpec(
            key="catalog-sitemap",
            url="https://www.efe.com.pe/media/sitemap/sitemap_efe.xml",
            max_candidates_per_run=50,
            daily_approval_limit=10,
            active_product_limit=300,
            child_path_pattern=r"^/media/sitemap/sitemap_efe-\d+-\d+\.xml$",
            url_entry_filter="has_image",
            notes=(
                "Sitemap oficial anunciado en robots.txt. Como mezcla categorías "
                "y productos, solo se consideran entradas con imagen de producto."
            ),
        ),
    )

    def normalize_product_url(self, url: str) -> str:
        return normalize_efe_product_url(url)


__all__ = ["EfeAdapter"]
