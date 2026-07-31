"""Bounded plazaVea spider backed by its reviewed public VTEX endpoint."""

from bot_ofertas.crawling.plazavea import (
    PLAZAVEA_HOSTS,
    build_plazavea_catalog_url,
    normalize_plazavea_product_url,
    parse_plazavea_products,
)
from bot_ofertas.crawling.spiders.reviewed_vtex_product import ReviewedVtexProductSpider


class PlazaVeaProductSpider(ReviewedVtexProductSpider):
    name = "plazavea_product"
    store_slug = "plazavea"
    display_name = "plazaVea"
    allowed_domains = ["plazavea.com.pe", "www.plazavea.com.pe"]
    request_hosts = PLAZAVEA_HOSTS
    max_targets = 5
    normalize_url = staticmethod(normalize_plazavea_product_url)
    catalog_url = staticmethod(build_plazavea_catalog_url)
    product_parser = staticmethod(parse_plazavea_products)


__all__ = ["PlazaVeaProductSpider"]
