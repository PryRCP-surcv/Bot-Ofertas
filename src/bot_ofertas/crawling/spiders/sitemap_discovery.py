"""Strictly bounded Scrapy spider for reviewed public product sitemaps."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import scrapy
from scrapy.exceptions import CloseSpider
from scrapy.http import Response
from twisted.python.failure import Failure

from bot_ofertas.discovery import (
    SitemapDocumentError,
    label_from_product_url,
    parse_sitemap_document,
    select_product_sitemap,
)
from bot_ofertas.stores import get_store_registry

_BLOCKING_HTTP_STATUSES = frozenset({403, 429, 503})
_REDIRECT_HTTP_STATUSES = frozenset({301, 302, 303, 307, 308})
_HANDLED_HTTP_STATUSES = sorted(_BLOCKING_HTTP_STATUSES | _REDIRECT_HTTP_STATUSES)


class SitemapDiscoverySpider(scrapy.Spider):
    """Read one sitemap index and at most one rotated product sitemap."""

    name = "bounded_sitemap_discovery"
    handle_httpstatus_list = _HANDLED_HTTP_STATUSES
    custom_settings = {
        "ITEM_PIPELINES": {
            "bot_ofertas.crawling.discovery_pipeline.PostgresDiscoveryPipeline": 300,
        },
        "DOWNLOAD_MAXSIZE": 12 * 1024 * 1024,
        "DOWNLOAD_WARNSIZE": 11 * 1024 * 1024,
        "CONCURRENT_REQUESTS": 2,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "ROBOTSTXT_OBEY": True,
    }

    def __init__(
        self,
        *,
        source_id: str,
        run_id: str,
        lease_token: str,
        store_slug: str,
        source_url: str,
        scan_cursor: int | str,
        max_documents_per_run: int | str,
        max_candidates_per_run: int | str,
        child_path_pattern: str,
        url_entry_filter: str,
        requested_by: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.source_id = source_id
        self.run_id = run_id
        self.lease_token = lease_token
        self.store_slug = store_slug.strip().lower()
        self.source_url = source_url.strip()
        self.scan_cursor = _bounded_integer(scan_cursor, minimum=0, maximum=2_147_483_647)
        self.max_documents_per_run = _bounded_integer(
            max_documents_per_run,
            minimum=1,
            maximum=10,
        )
        self.max_candidates_per_run = _bounded_integer(
            max_candidates_per_run,
            minimum=1,
            maximum=500,
        )
        self.child_path_pattern = child_path_pattern
        if url_entry_filter not in {"all", "has_image"}:
            raise ValueError("invalid sitemap URL entry filter")
        self.url_entry_filter = url_entry_filter
        self.requested_by = requested_by
        self.adapter = get_store_registry().get(self.store_slug)
        self.request_hosts = frozenset(self.adapter.hosts)
        self.allowed_domains = sorted(self.request_hosts)
        self._seen_products: set[str] = set()
        self._documents_requested = 0

        reviewed_sources = {
            source.url
            for source in self.adapter.discovery_sources
            if source.enabled
        }
        if self.source_url not in reviewed_sources:
            raise ValueError("the discovery source is not declared by the store adapter")
        _validate_request_url(self.source_url, self.request_hosts)

    async def start(self):  # type: ignore[no-untyped-def]
        yield self._request(self.source_url, callback=self.parse_root)

    def _request(self, url: str, *, callback: Any) -> scrapy.Request:
        if self._documents_requested >= self.max_documents_per_run:
            raise CloseSpider(reason="discovery_document_limit")
        validated = _validate_request_url(url, self.request_hosts)
        self._documents_requested += 1
        return scrapy.Request(
            validated,
            method="GET",
            callback=callback,
            errback=self.request_failed,
            headers={
                "Accept": "application/xml,text/xml;q=0.9,text/plain;q=0.5",
                "Cache-Control": "no-cache",
            },
            meta={
                "dont_redirect": True,
                "download_timeout": 30,
            },
        )

    def parse_root(self, response: Response):
        document = self._document(response)
        if document.kind == "urls":
            yield from self._product_items(self._filtered_locations(document))
            return
        if self.max_documents_per_run < 2:
            raise CloseSpider(reason="discovery_document_limit")
        selected, next_cursor, child_count = select_product_sitemap(
            document.locations,
            source_url=self.source_url,
            child_path_pattern=self.child_path_pattern,
            cursor=self.scan_cursor,
        )
        self.crawler.stats.set_value(
            "bot_ofertas/discovery_selected_sitemap",
            selected,
        )
        self.crawler.stats.set_value(
            "bot_ofertas/discovery_product_sitemap_count",
            child_count,
        )
        self.crawler.stats.set_value(
            "bot_ofertas/discovery_next_scan_cursor",
            next_cursor,
        )
        yield self._request(selected, callback=self.parse_product_sitemap)

    def parse_product_sitemap(self, response: Response):
        document = self._document(response)
        if document.kind != "urls":
            raise CloseSpider(reason="discovery_nested_index_not_allowed")
        yield from self._product_items(self._filtered_locations(document))

    def _filtered_locations(self, document: Any) -> tuple[str, ...]:
        if self.url_entry_filter == "has_image":
            self.crawler.stats.set_value(
                "bot_ofertas/discovery_url_filter",
                "has_image",
            )
            return document.image_locations
        return document.locations

    def _document(self, response: Response):
        if response.status in _BLOCKING_HTTP_STATUSES:
            raise CloseSpider(reason=f"{self.store_slug}_discovery_blocked_{response.status}")
        if response.status in _REDIRECT_HTTP_STATUSES:
            raise CloseSpider(reason=f"{self.store_slug}_discovery_redirect_{response.status}")
        content_type = response.headers.get(b"Content-Type", b"").decode(
            "latin-1",
            errors="replace",
        )
        prefix = response.body[:16_384].lstrip().lower()
        if _contains_challenge(prefix) or _looks_like_html(content_type, prefix):
            raise CloseSpider(reason=f"{self.store_slug}_discovery_html_or_captcha")
        try:
            document = parse_sitemap_document(response.body)
        except (TypeError, ValueError, SitemapDocumentError) as error:
            self.logger.warning(
                "Sitemap inválido para %s (%s).",
                self.store_slug,
                type(error).__name__,
            )
            raise CloseSpider(reason=f"{self.store_slug}_discovery_invalid_sitemap") from error
        self.crawler.stats.inc_value("bot_ofertas/discovery_document_count")
        return document

    def _product_items(self, locations: tuple[str, ...]):
        yielded = 0
        for discovered_url in locations:
            if yielded >= self.max_candidates_per_run:
                break
            try:
                canonical_url = self.adapter.normalize_product_url(discovered_url)
            except (TypeError, ValueError):
                self.crawler.stats.inc_value("bot_ofertas/discovery_rejected_urls")
                continue
            if canonical_url in self._seen_products:
                self.crawler.stats.inc_value("bot_ofertas/discovery_duplicate_urls")
                continue
            self._seen_products.add(canonical_url)
            yielded += 1
            yield {
                "store_slug": self.store_slug,
                "discovered_url": discovered_url,
                "canonical_url": canonical_url,
                "label": label_from_product_url(
                    canonical_url,
                    store_name=self.adapter.display_name,
                ),
                "metadata": {
                    "source_type": "sitemap",
                    "selected_sitemap": self.crawler.stats.get_value(
                        "bot_ofertas/discovery_selected_sitemap",
                        self.source_url,
                    ),
                },
            }
        self.crawler.stats.inc_value(
            "bot_ofertas/discovery_yielded_candidates",
            yielded,
        )

    def request_failed(self, failure: Failure) -> None:
        response = getattr(failure.value, "response", None)
        status = getattr(response, "status", None)
        if status in _BLOCKING_HTTP_STATUSES:
            raise CloseSpider(reason=f"{self.store_slug}_discovery_blocked_{status}")
        raise CloseSpider(reason=f"{self.store_slug}_discovery_request_failed")


def _bounded_integer(value: int | str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError("boolean is not an integer limit")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("invalid discovery integer") from error
    if not minimum <= parsed <= maximum:
        raise ValueError("discovery integer is outside its safety range")
    return parsed


def _validate_request_url(url: str, allowed_hosts: frozenset[str]) -> str:
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").rstrip(".").lower()
        port = parts.port
    except ValueError as error:
        raise ValueError("invalid discovery request URL") from error
    if (
        url != url.strip()
        or parts.scheme.lower() != "https"
        or host not in allowed_hosts
        or parts.username is not None
        or parts.password is not None
        or port not in (None, 443)
        or parts.query
        or parts.fragment
    ):
        raise ValueError("discovery requests must stay on a reviewed HTTPS host")
    return url


def _contains_challenge(prefix: bytes) -> bool:
    markers = (
        b"captcha",
        b"g-recaptcha",
        b"hcaptcha",
        b"cf-chl-",
        b"attention required",
        b"access denied",
    )
    return any(marker in prefix for marker in markers)


def _looks_like_html(content_type: str, prefix: bytes) -> bool:
    lowered = content_type.casefold()
    return (
        "text/html" in lowered
        or prefix.startswith(b"<!doctype html")
        or prefix.startswith(b"<html")
    )


__all__ = ["SitemapDiscoverySpider"]
