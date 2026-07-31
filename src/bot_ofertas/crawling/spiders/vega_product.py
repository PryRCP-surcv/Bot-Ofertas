"""Bounded Vega spider backed by its reviewed public VTEX endpoint."""

from bot_ofertas.crawling.spiders.reviewed_vtex_product import ReviewedVtexProductSpider
from bot_ofertas.crawling.vega import (
    VEGA_HOSTS,
    build_vega_catalog_url,
    normalize_vega_product_url,
    parse_vega_products,
)


class VegaProductSpider(ReviewedVtexProductSpider):
    name = "vega_product"
    store_slug = "vega"
    display_name = "Vega"
    allowed_domains = ["vega.pe", "www.vega.pe"]
    request_hosts = VEGA_HOSTS
    max_targets = 5
    normalize_url = staticmethod(normalize_vega_product_url)
    catalog_url = staticmethod(build_vega_catalog_url)
    product_parser = staticmethod(parse_vega_products)


__all__ = ["VegaProductSpider"]
