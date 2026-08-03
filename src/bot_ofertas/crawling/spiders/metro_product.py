"""Bounded Metro spider backed by its reviewed public VTEX endpoint."""

from bot_ofertas.crawling.metro import (
    METRO_HOSTS,
    build_metro_catalog_url,
    normalize_metro_product_url,
    parse_metro_products,
)
from bot_ofertas.crawling.spiders.reviewed_vtex_product import ReviewedVtexProductSpider


class MetroProductSpider(ReviewedVtexProductSpider):
    name = "metro_product"
    store_slug = "metro"
    display_name = "Metro"
    allowed_domains = ["metro.pe", "www.metro.pe"]
    request_hosts = METRO_HOSTS
    max_targets = 10
    normalize_url = staticmethod(normalize_metro_product_url)
    catalog_url = staticmethod(build_metro_catalog_url)
    product_parser = staticmethod(parse_metro_products)


__all__ = ["MetroProductSpider"]
