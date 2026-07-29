"""Contracts shared by all store integrations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar
from urllib.parse import urlsplit

from scrapy import Spider


@dataclass(frozen=True, slots=True)
class DiscoverySourceSpec:
    """Reviewed public source used to discover product-detail URLs."""

    key: str
    url: str
    source_type: str = "sitemap"
    minimum_interval_minutes: int = 1_440
    max_documents_per_run: int = 2
    max_candidates_per_run: int = 100
    daily_approval_limit: int = 20
    active_product_limit: int = 500
    child_path_pattern: str = r"^/sitemap/product-\d+\.xml$"
    url_entry_filter: str = "all"
    enabled: bool = True
    notes: str = ""

    def __post_init__(self) -> None:
        normalized_key = self.key.strip().lower()
        if not normalized_key or normalized_key != self.key:
            raise ValueError("discovery source key must be normalized and non-empty")
        if self.source_type != "sitemap":
            raise ValueError("only reviewed sitemap discovery sources are supported")
        parts = urlsplit(self.url)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.port not in (None, 443)
            or parts.query
            or parts.fragment
        ):
            raise ValueError("discovery source URL must be public canonical HTTPS")
        if self.minimum_interval_minutes < 60:
            raise ValueError("discovery interval must be at least 60 minutes")
        if not 1 <= self.max_documents_per_run <= 10:
            raise ValueError("max_documents_per_run must be between 1 and 10")
        if not 1 <= self.max_candidates_per_run <= 500:
            raise ValueError("max_candidates_per_run must be between 1 and 500")
        if not 1 <= self.daily_approval_limit <= 1_000:
            raise ValueError("daily_approval_limit must be between 1 and 1000")
        if not 1 <= self.active_product_limit <= 10_000:
            raise ValueError("active_product_limit must be between 1 and 10000")
        if not self.child_path_pattern:
            raise ValueError("child_path_pattern must not be empty")
        if self.url_entry_filter not in {"all", "has_image"}:
            raise ValueError("url_entry_filter must be 'all' or 'has_image'")


@dataclass(frozen=True, slots=True)
class StorePolicy:
    """Safety limits and enablement state reviewed for one store."""

    enabled: bool
    minimum_interval_minutes: int = 30
    max_targets_per_run: int = 20
    requires_explicit_product_url: bool = True
    notes: str = ""

    def __post_init__(self) -> None:
        if self.minimum_interval_minutes < 30:
            raise ValueError("minimum_interval_minutes must be at least 30")
        if self.max_targets_per_run <= 0:
            raise ValueError("max_targets_per_run must be positive")


class StoreAdapter(ABC):
    """Extension point for one reviewed store and its bounded spider."""

    slug: ClassVar[str]
    display_name: ClassVar[str]
    hosts: ClassVar[frozenset[str]]
    policy: ClassVar[StorePolicy]
    spider_class: ClassVar[type[Spider]]
    discovery_sources: ClassVar[tuple[DiscoverySourceSpec, ...]] = ()

    @abstractmethod
    def normalize_product_url(self, url: str) -> str:
        """Validate a public product URL and return its canonical form."""


__all__ = ["DiscoverySourceSpec", "StoreAdapter", "StorePolicy"]
