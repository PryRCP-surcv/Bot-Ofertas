"""Bounded Casaideas spider backed by its reviewed public VTEX endpoint."""

from bot_ofertas.crawling.casaideas import (
    CASAIDEAS_HOSTS,
    build_casaideas_catalog_url,
    normalize_casaideas_product_url,
    parse_casaideas_products,
)
from bot_ofertas.crawling.spiders.reviewed_vtex_product import ReviewedVtexProductSpider


class CasaideasProductSpider(ReviewedVtexProductSpider):
    name = "casaideas_product"
    store_slug = "casaideas"
    display_name = "Casaideas"
    allowed_domains = ["casaideas.com.pe", "www.casaideas.com.pe"]
    request_hosts = CASAIDEAS_HOSTS
    max_targets = 10
    normalize_url = staticmethod(normalize_casaideas_product_url)
    catalog_url = staticmethod(build_casaideas_catalog_url)
    product_parser = staticmethod(parse_casaideas_products)


__all__ = ["CasaideasProductSpider"]
