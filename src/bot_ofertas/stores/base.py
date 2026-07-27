"""Contracts shared by all store integrations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from scrapy import Spider


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

    @abstractmethod
    def normalize_product_url(self, url: str) -> str:
        """Validate a public product URL and return its canonical form."""


__all__ = ["StoreAdapter", "StorePolicy"]
