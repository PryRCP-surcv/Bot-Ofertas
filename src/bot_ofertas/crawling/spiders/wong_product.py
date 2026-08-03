"""Bounded Wong spider backed by its reviewed public VTEX endpoint."""

from bot_ofertas.crawling.spiders.reviewed_vtex_product import ReviewedVtexProductSpider
from bot_ofertas.crawling.wong import (
    WONG_HOSTS,
    build_wong_catalog_url,
    normalize_wong_product_url,
    parse_wong_products,
)


class WongProductSpider(ReviewedVtexProductSpider):
    name = "wong_product"
    store_slug = "wong"
    display_name = "Wong"
    allowed_domains = ["wong.pe", "www.wong.pe"]
    request_hosts = WONG_HOSTS
    max_targets = 10
    normalize_url = staticmethod(normalize_wong_product_url)
    catalog_url = staticmethod(build_wong_catalog_url)
    product_parser = staticmethod(parse_wong_products)


__all__ = ["WongProductSpider"]
