"""Bounded Topitop spider backed by its reviewed public VTEX endpoint."""

from bot_ofertas.crawling.spiders.reviewed_vtex_product import ReviewedVtexProductSpider
from bot_ofertas.crawling.topitop import (
    TOPITOP_HOSTS,
    build_topitop_catalog_url,
    normalize_topitop_product_url,
    parse_topitop_products,
)


class TopitopProductSpider(ReviewedVtexProductSpider):
    name = "topitop_product"
    store_slug = "topitop"
    display_name = "Topitop"
    allowed_domains = ["topitop.pe", "www.topitop.pe"]
    request_hosts = TOPITOP_HOSTS
    max_targets = 10
    normalize_url = staticmethod(normalize_topitop_product_url)
    catalog_url = staticmethod(build_topitop_catalog_url)
    product_parser = staticmethod(parse_topitop_products)


__all__ = ["TopitopProductSpider"]
