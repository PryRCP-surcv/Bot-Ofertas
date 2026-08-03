"""Domain contracts shared by crawlers, detectors, and persistence."""

from bot_ofertas.domain.observations import (
    Availability,
    InstallmentOption,
    PriceObservation,
    ProductCondition,
    normalize_optional_https_url,
)

__all__ = [
    "Availability",
    "InstallmentOption",
    "PriceObservation",
    "ProductCondition",
    "normalize_optional_https_url",
]
