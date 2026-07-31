"""Reusable bounded spider for reviewed public VTEX product endpoints."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from typing import Any, ClassVar

from bot_ofertas.crawling.spiders.base_product import JsonProductSpider

ProductUrlNormalizer = Callable[[str], str]
CatalogUrlBuilder = Callable[[str], str]
ProductParser = Callable[[Any, str, str | None, datetime], list[dict[str, Any]]]


class ReviewedVtexProductSpider(JsonProductSpider):
    """Delegate reviewed store details while preserving the common safety fence."""

    normalize_url: ClassVar[ProductUrlNormalizer]
    catalog_url: ClassVar[CatalogUrlBuilder]
    product_parser: ClassVar[ProductParser]

    def normalize_product_url(self, url: str) -> str:
        return type(self).normalize_url(url)

    def build_request_url(self, source_url: str) -> str:
        return type(self).catalog_url(source_url)

    def parse_payload(
        self,
        *,
        payload: Any,
        source_url: str,
        tracked_product_id: str | None,
        observed_at: datetime,
    ) -> Iterable[Mapping[str, Any]]:
        return type(self).product_parser(
            payload,
            source_url,
            tracked_product_id,
            observed_at,
        )


__all__ = ["ReviewedVtexProductSpider"]
