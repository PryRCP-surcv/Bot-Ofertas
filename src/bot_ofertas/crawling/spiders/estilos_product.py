"""Bounded Estilos spider backed by its reviewed public VTEX endpoint."""

from bot_ofertas.crawling.estilos import (
    ESTILOS_HOSTS,
    build_estilos_catalog_url,
    normalize_estilos_product_url,
    parse_estilos_products,
)
from bot_ofertas.crawling.spiders.reviewed_vtex_product import ReviewedVtexProductSpider


class EstilosProductSpider(ReviewedVtexProductSpider):
    name = "estilos_product"
    store_slug = "estilos"
    display_name = "Estilos"
    allowed_domains = ["estilos.com.pe", "www.estilos.com.pe"]
    request_hosts = ESTILOS_HOSTS
    max_targets = 10
    normalize_url = staticmethod(normalize_estilos_product_url)
    catalog_url = staticmethod(build_estilos_catalog_url)
    product_parser = staticmethod(parse_estilos_products)


__all__ = ["EstilosProductSpider"]
