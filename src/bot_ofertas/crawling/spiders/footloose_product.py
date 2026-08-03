"""Bounded Footloose spider backed by its reviewed public VTEX endpoint."""

from bot_ofertas.crawling.footloose import (
    FOOTLOOSE_HOSTS,
    build_footloose_catalog_url,
    normalize_footloose_product_url,
    parse_footloose_products,
)
from bot_ofertas.crawling.spiders.reviewed_vtex_product import ReviewedVtexProductSpider


class FootlooseProductSpider(ReviewedVtexProductSpider):
    name = "footloose_product"
    store_slug = "footloose"
    display_name = "Footloose"
    allowed_domains = ["footloose.pe", "www.footloose.pe"]
    request_hosts = FOOTLOOSE_HOSTS
    max_targets = 10
    normalize_url = staticmethod(normalize_footloose_product_url)
    catalog_url = staticmethod(build_footloose_catalog_url)
    product_parser = staticmethod(parse_footloose_products)


__all__ = ["FootlooseProductSpider"]
