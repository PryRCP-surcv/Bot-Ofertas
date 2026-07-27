"""Reusable bounded spider behavior for reviewed public product sources."""

from __future__ import annotations

import json
from abc import abstractmethod
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import scrapy
from scrapy.exceptions import CloseSpider
from scrapy.http import Response
from twisted.python.failure import Failure

_BLOCKING_HTTP_STATUSES = frozenset({403, 429, 503})


class BoundedProductSpider(scrapy.Spider):
    """Fetch only explicit product targets and stop on blocking/challenge signals."""

    store_slug: str
    display_name: str
    request_hosts: frozenset[str]
    accepts_html = True
    handle_httpstatus_list = sorted(_BLOCKING_HTTP_STATUSES)
    max_targets = 20

    def __init__(
        self,
        url: str | None = None,
        tracked_product_id: str | None = None,
        lease_token: str | None = None,
        targets: list[dict[str, Any]] | str | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        raw_targets = _decode_targets(targets)
        if url is not None:
            raw_targets.append(
                {
                    "url": url,
                    "tracked_product_id": tracked_product_id,
                    "lease_token": lease_token,
                }
            )
        if not raw_targets:
            raise ValueError(f"{self.name} requires an explicit URL or a bounded targets list.")
        if len(raw_targets) > self.max_targets:
            raise ValueError(
                f"A {self.store_slug} crawl may contain at most {self.max_targets} product URLs."
            )

        normalized_targets: list[dict[str, str | None]] = []
        seen_urls: set[str] = set()
        for target in raw_targets:
            target_url = target.get("url")
            if not isinstance(target_url, str):
                raise ValueError(f"Every {self.store_slug} target must contain a string URL.")
            source_url = self.normalize_product_url(target_url)
            if source_url in seen_urls:
                continue
            seen_urls.add(source_url)
            normalized_targets.append(
                {
                    "url": source_url,
                    "tracked_product_id": _optional_text(target.get("tracked_product_id")),
                    "lease_token": _optional_text(target.get("lease_token")),
                }
            )
        self.targets = normalized_targets

    async def start(self):  # type: ignore[no-untyped-def]
        """Issue one read-only request per explicit, canonical product target."""

        for target in self.targets:
            source_url = target["url"]
            if source_url is None:  # Guarded in __init__, retained for narrowing.
                continue
            request_url = _validate_public_request_url(
                self.build_request_url(source_url),
                self.request_hosts,
            )
            yield scrapy.Request(
                request_url,
                method="GET",
                headers=self.request_headers(),
                callback=self.parse_product_response,
                errback=self.request_failed,
                cb_kwargs={
                    "source_url": source_url,
                    "tracked_product_id": target["tracked_product_id"],
                },
                meta=self.request_meta(),
            )

    def parse_product_response(
        self,
        response: Response,
        source_url: str,
        tracked_product_id: str | None,
    ):
        """Validate one public response before delegating store-specific parsing."""

        if response.status in _BLOCKING_HTTP_STATUSES:
            self.crawler.stats.inc_value(f"{self.store_slug}/stopped_http_{response.status}")
            raise CloseSpider(reason=f"{self.store_slug}_blocked_http_{response.status}")

        content_type = response.headers.get(b"Content-Type", b"").decode(
            "latin-1", errors="replace"
        )
        body_prefix = response.body[:16_384].lstrip().lower()
        if _contains_challenge(body_prefix) or (
            not self.accepts_html and _looks_like_html(content_type, body_prefix)
        ):
            self.crawler.stats.inc_value(f"{self.store_slug}/stopped_unexpected_html_or_challenge")
            raise CloseSpider(reason=f"{self.store_slug}_html_or_captcha_detected")

        try:
            payload = self.decode_response(response)
        except (TypeError, ValueError, UnicodeDecodeError) as exc:
            self.logger.error(
                "%s returned invalid content: %s",
                self.display_name,
                type(exc).__name__,
            )
            raise CloseSpider(reason=f"{self.store_slug}_invalid_response") from exc

        try:
            observations = list(
                self.parse_payload(
                    payload=payload,
                    source_url=source_url,
                    tracked_product_id=tracked_product_id,
                    observed_at=datetime.now(UTC),
                )
            )
        except (TypeError, ValueError) as exc:
            self.logger.error(
                "%s schema validation failed: %s",
                self.display_name,
                type(exc).__name__,
            )
            raise CloseSpider(reason=f"{self.store_slug}_invalid_payload") from exc

        if not observations:
            self.logger.warning(
                "%s returned no SKU/seller observations for %s",
                self.display_name,
                source_url,
            )
            self.crawler.stats.inc_value(f"{self.store_slug}/empty_product_response")
            return

        self.crawler.stats.inc_value(
            f"{self.store_slug}/observations",
            count=len(observations),
        )
        yield from observations

    def request_failed(self, failure: Failure) -> None:
        """Stop after retries; never switch identity, route, or solve challenges."""

        response = getattr(failure.value, "response", None)
        status = getattr(response, "status", None)
        if status in _BLOCKING_HTTP_STATUSES:
            self.crawler.stats.inc_value(f"{self.store_slug}/stopped_http_{status}")
            raise CloseSpider(reason=f"{self.store_slug}_blocked_http_{status}")

        self.logger.error(
            "%s request failed: %s",
            self.display_name,
            failure.getErrorMessage(),
        )
        self.crawler.stats.inc_value(f"{self.store_slug}/request_failed")
        raise CloseSpider(reason=f"{self.store_slug}_request_failed")

    def request_headers(self) -> dict[str, str]:
        return {
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
            "Cache-Control": "max-age=0",
        }

    def request_meta(self) -> dict[str, Any]:
        return {
            "dont_redirect": True,
            "download_timeout": 30,
        }

    def decode_response(self, response: Response) -> Any:
        """Decode a normal response; HTML adapters may override and return Response."""

        return response.text

    @abstractmethod
    def normalize_product_url(self, url: str) -> str:
        """Validate and canonicalize one explicit store product URL."""

    @abstractmethod
    def build_request_url(self, source_url: str) -> str:
        """Return the reviewed public read-only URL for one product."""

    @abstractmethod
    def parse_payload(
        self,
        *,
        payload: Any,
        source_url: str,
        tracked_product_id: str | None,
        observed_at: datetime,
    ) -> Iterable[Mapping[str, Any]]:
        """Normalize one response into exact SKU/seller observations."""


class JsonProductSpider(BoundedProductSpider):
    """Bounded product spider for reviewed JSON endpoints."""

    accepts_html = False

    def request_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Cache-Control": "max-age=0",
        }

    def decode_response(self, response: Response) -> Any:
        return json.loads(response.text)


def _decode_targets(targets: list[dict[str, Any]] | str | None) -> list[dict[str, Any]]:
    if targets is None:
        return []
    if isinstance(targets, list):
        if not all(isinstance(target, dict) for target in targets):
            raise ValueError("targets must be a list of objects.")
        return list(targets)
    if isinstance(targets, str):
        try:
            decoded = json.loads(targets)
        except json.JSONDecodeError as exc:
            raise ValueError("targets must be valid JSON.") from exc
        if not isinstance(decoded, list) or not all(isinstance(target, dict) for target in decoded):
            raise ValueError("targets must decode to a list of objects.")
        return decoded
    raise TypeError("targets must be a list, JSON string, or None.")


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _looks_like_html(content_type: str, body_prefix: bytes) -> bool:
    lowered_type = content_type.casefold()
    return (
        "text/html" in lowered_type
        or body_prefix.startswith(b"<!doctype html")
        or body_prefix.startswith(b"<html")
    )


def _contains_challenge(body_prefix: bytes) -> bool:
    challenge_markers = (
        b"captcha",
        b"g-recaptcha",
        b"hcaptcha",
        b"cf-chl-",
        b"attention required",
        b"access denied",
    )
    return any(marker in body_prefix for marker in challenge_markers)


def _validate_public_request_url(url: str, request_hosts: frozenset[str]) -> str:
    if not isinstance(url, str) or url != url.strip():
        raise ValueError("the store request URL must be a canonical string")
    try:
        parts = urlsplit(url)
        hostname = (parts.hostname or "").rstrip(".").lower()
        port = parts.port
    except ValueError as exc:
        raise ValueError("the store request URL is invalid") from exc
    if (
        parts.scheme.lower() != "https"
        or not hostname
        or hostname not in request_hosts
        or parts.username is not None
        or parts.password is not None
        or port not in (None, 443)
    ):
        raise ValueError("the store request URL must use HTTPS on an explicitly reviewed hostname")
    return url


__all__ = ["BoundedProductSpider", "JsonProductSpider"]
