from __future__ import annotations

import pytest

from bot_ofertas.discovery import (
    SitemapDocumentError,
    label_from_product_url,
    parse_sitemap_document,
    select_product_sitemap,
)
from bot_ofertas.stores import build_store_registry


def test_parses_index_and_rotates_only_reviewed_product_children() -> None:
    document = parse_sitemap_document(
        b"""<?xml version="1.0"?>
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <sitemap><loc>https://www.oechsle.pe/sitemap/brand-0.xml</loc></sitemap>
          <sitemap><loc>https://www.oechsle.pe/sitemap/product-0.xml</loc></sitemap>
          <sitemap><loc>https://www.oechsle.pe/sitemap/product-1.xml</loc></sitemap>
          <sitemap><loc>https://example.com/sitemap/product-2.xml</loc></sitemap>
        </sitemapindex>"""
    )

    assert document.kind == "index"
    selected, next_cursor, total = select_product_sitemap(
        document.locations,
        source_url="https://www.oechsle.pe/sitemap.xml",
        child_path_pattern=r"^/sitemap/product-\d+\.xml$",
        cursor=1,
    )

    assert selected == "https://www.oechsle.pe/sitemap/product-1.xml"
    assert next_cursor == 2
    assert total == 2


def test_sitemap_parser_rejects_entities_and_unsupported_roots() -> None:
    with pytest.raises(SitemapDocumentError):
        parse_sitemap_document(
            b'<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
            b"<urlset><url><loc>&xxe;</loc></url></urlset>"
        )

    with pytest.raises(SitemapDocumentError):
        parse_sitemap_document(b"<html><body>not a sitemap</body></html>")


def test_urlset_deduplicates_locations_and_builds_editable_label() -> None:
    document = parse_sitemap_document(
        b"""<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://www.coolbox.pe/barra-sonido-s25/p</loc></url>
          <url><loc>https://www.coolbox.pe/barra-sonido-s25/p</loc></url>
        </urlset>"""
    )

    assert document.locations == (
        "https://www.coolbox.pe/barra-sonido-s25/p",
    )
    assert (
        label_from_product_url(document.locations[0], store_name="Coolbox")
        == "barra sonido s25"
    )


def test_urlset_identifies_image_backed_entries_in_a_mixed_magento_sitemap() -> None:
    document = parse_sitemap_document(
        b"""<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
              xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">
          <url><loc>https://www.efe.com.pe/electrohogar.html</loc></url>
          <url>
            <loc>https://www.efe.com.pe/cafetera-demo.html</loc>
            <image:image><image:loc>https://www.efe.com.pe/demo.jpg</image:loc></image:image>
          </url>
        </urlset>"""
    )

    assert document.locations == (
        "https://www.efe.com.pe/electrohogar.html",
        "https://www.efe.com.pe/cafetera-demo.html",
    )
    assert document.image_locations == (
        "https://www.efe.com.pe/cafetera-demo.html",
    )
    assert (
        label_from_product_url(document.image_locations[0], store_name="EFE")
        == "cafetera demo"
    )


def test_builtin_adapters_declare_daily_bounded_sitemap_sources() -> None:
    registry = build_store_registry(include_plugins=False)

    assert {adapter.slug for adapter in registry.adapters} == {
        "cassinelli",
        "coolbox",
        "curacao",
        "efe",
        "oechsle",
        "promart",
    }
    for adapter in registry.adapters:
        assert len(adapter.discovery_sources) == 1
        source = adapter.discovery_sources[0]
        assert source.url.startswith("https://")
        assert source.minimum_interval_minutes >= 1_440
        assert source.max_documents_per_run == 2
        assert source.max_candidates_per_run <= 100
        assert source.daily_approval_limit == 20
        assert source.url_entry_filter in {"all", "has_image"}
