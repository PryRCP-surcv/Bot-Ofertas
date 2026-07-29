"""Bounded catalogue discovery for reviewed Peruvian stores."""

from bot_ofertas.discovery.sitemap import (
    SitemapDocument,
    SitemapDocumentError,
    label_from_product_url,
    parse_sitemap_document,
    select_product_sitemap,
)

__all__ = [
    "SitemapDocument",
    "SitemapDocumentError",
    "label_from_product_url",
    "parse_sitemap_document",
    "select_product_sitemap",
]
