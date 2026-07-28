"""Pure, deterministic deal detection over normalized price observations.

The detector deliberately has no persistence, network, or notification concerns.
Callers provide the current observation and an iterable of exact comparable history;
the returned decision contains every reference used to reach its classification.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, localcontext
from enum import StrEnum

from bot_ofertas.domain import Availability, PriceObservation, ProductCondition

_RATIO_QUANTUM = Decimal("0.0001")
_ZERO = Decimal("0")


class DealClassification(StrEnum):
    """Alert severity in ascending order."""

    NONE = "none"
    GOOD_DEAL = "good_deal"
    EXCEPTIONAL_DEAL = "exceptional_deal"
    POSSIBLE_PRICE_ERROR = "possible_price_error"


class SignalKind(StrEnum):
    """Price references evaluated by the detector."""

    PREVIOUS_PRICE = "previous_price"
    HISTORICAL_MEDIAN = "historical_median"
    HISTORICAL_MINIMUM = "historical_minimum"
    LIST_PRICE = "list_price"


class RejectionReason(StrEnum):
    """Reasons why a current observation cannot produce an alert."""

    CURRENCY_NOT_ALLOWED = "currency_not_allowed"
    MISSING_PRICE = "missing_price"
    NON_POSITIVE_PRICE = "non_positive_price"
    NOT_IN_STOCK = "not_in_stock"
    MARKETPLACE_OFFER = "marketplace_offer"
    CONDITION_NOT_NEW = "condition_not_new"
    QUALITY_FLAGS_PRESENT = "quality_flags_present"
    INSTALLMENT_USED_AS_PRICE = "installment_used_as_price"
    EXPECTED_PRODUCT_MISMATCH = "expected_product_mismatch"
    EXPECTED_VARIANT_MISMATCH = "expected_variant_mismatch"
    ACCESSORY_MISMATCH = "accessory_mismatch"


@dataclass(frozen=True, slots=True)
class SignalThresholds:
    """Minimum fractional reductions for one signal.

    Values are ratios, not percentages: ``Decimal("0.20")`` means 20%.
    """

    good_deal: Decimal = Decimal("0.20")
    exceptional_deal: Decimal = Decimal("0.40")
    possible_price_error: Decimal = Decimal("0.70")

    def __post_init__(self) -> None:
        values = (self.good_deal, self.exceptional_deal, self.possible_price_error)
        if any(not isinstance(value, Decimal) for value in values):
            raise TypeError("signal thresholds must be Decimal values")
        if any(not value.is_finite() for value in values):
            raise ValueError("signal thresholds must be finite")
        if not (_ZERO <= self.good_deal <= self.exceptional_deal):
            raise ValueError("signal thresholds must be ordered")
        if not (self.exceptional_deal <= self.possible_price_error < Decimal("1")):
            raise ValueError("signal thresholds must be ordered and below 1")


@dataclass(frozen=True, slots=True)
class DetectorConfig:
    """Configurable policy for the first production detector."""

    allowed_currency: str = "PEN"
    minimum_history_samples: int = 3
    previous_price_thresholds: SignalThresholds = field(default_factory=SignalThresholds)
    historical_median_thresholds: SignalThresholds = field(default_factory=SignalThresholds)
    historical_minimum_thresholds: SignalThresholds = field(default_factory=SignalThresholds)
    list_price_thresholds: SignalThresholds = field(default_factory=SignalThresholds)
    allowed_availabilities: frozenset[Availability] = frozenset({Availability.IN_STOCK})
    reject_any_quality_flag: bool = True
    accessory_terms: frozenset[str] = frozenset(
        {
            "adaptador",
            "accesorio",
            "airpods",
            "audifono",
            "auricular",
            "cable",
            "carcasa",
            "case",
            "cargador",
            "correa",
            "cover",
            "estuche",
            "funda",
            "mica",
            "mouse",
            "power bank",
            "protector",
            "repuesto",
            "soporte",
            "strap",
            "vidrio templado",
        }
    )

    def __post_init__(self) -> None:
        currency = self.allowed_currency.strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError("allowed_currency must be a three-letter currency code")
        object.__setattr__(self, "allowed_currency", currency)

        if (
            not isinstance(self.minimum_history_samples, int)
            or isinstance(self.minimum_history_samples, bool)
            or self.minimum_history_samples < 1
        ):
            raise ValueError("minimum_history_samples must be a positive integer")
        if not isinstance(self.reject_any_quality_flag, bool):
            raise TypeError("reject_any_quality_flag must be a boolean")

        availabilities = frozenset(
            Availability(availability) for availability in self.allowed_availabilities
        )
        if not availabilities:
            raise ValueError("allowed_availabilities must not be empty")
        object.__setattr__(self, "allowed_availabilities", availabilities)

        terms = frozenset(
            normalized
            for term in self.accessory_terms
            if (normalized := _normalized_words(term))
        )
        object.__setattr__(self, "accessory_terms", terms)


@dataclass(frozen=True, slots=True)
class ExpectedProductContext:
    """Optional constraints for the product the caller intended to track.

    Empty fields are unconstrained. When ``variant`` is provided it must match
    exactly, preventing a cheaper size, color, capacity, or other variant from
    being compared with the tracked one.
    """

    store_slug: str | None = None
    external_product_id: str | None = None
    sku: str | None = None
    seller_id: str | None = None
    brand: str | None = None
    model: str | None = None
    variant: Mapping[str, str] = field(default_factory=dict)
    expected_is_accessory: bool | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "store_slug",
            "external_product_id",
            "sku",
            "seller_id",
            "brand",
            "model",
        ):
            value = getattr(self, field_name)
            if value is not None:
                normalized = value.strip()
                if not normalized:
                    raise ValueError(f"{field_name} must not be empty when provided")
                object.__setattr__(self, field_name, normalized)

        object.__setattr__(self, "variant", canonicalize_variant(self.variant))

        if self.expected_is_accessory is not None and not isinstance(
            self.expected_is_accessory,
            bool,
        ):
            raise TypeError("expected_is_accessory must be a boolean or None")


@dataclass(frozen=True, slots=True)
class SignalAssessment:
    """Auditable evaluation of a single price reference."""

    kind: SignalKind
    eligible: bool
    reference_price: Decimal | None
    discount_ratio: Decimal | None
    classification: DealClassification
    sample_count: int | None = None

    @property
    def discount_percent(self) -> Decimal | None:
        """Return the signed discount percentage with two decimal places."""

        if self.discount_ratio is None:
            return None
        return (self.discount_ratio * Decimal("100")).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )


@dataclass(frozen=True, slots=True)
class DetectionDecision:
    """Final detector result, including validation and all evaluated signals."""

    classification: DealClassification
    current_price: Decimal | None
    rejection_reasons: tuple[RejectionReason, ...]
    blocking_quality_flags: tuple[str, ...]
    signals: tuple[SignalAssessment, ...]
    history_samples_used: int
    history_samples_ignored: int

    @property
    def is_valid(self) -> bool:
        return not self.rejection_reasons

    @property
    def should_alert(self) -> bool:
        return self.is_valid and self.classification is not DealClassification.NONE


class DealDetector:
    """Evaluate normalized observations without side effects."""

    def __init__(self, config: DetectorConfig | None = None) -> None:
        self.config = config or DetectorConfig()

    def evaluate(
        self,
        current: PriceObservation,
        history: Iterable[PriceObservation] = (),
        *,
        expected: ExpectedProductContext | None = None,
    ) -> DetectionDecision:
        """Evaluate one observation against earlier exact-comparable observations."""

        history_items = tuple(history)
        reasons = _rejection_reasons(current, self.config, expected)
        blocking_flags = (
            tuple(sorted(set(current.quality_flags)))
            if self.config.reject_any_quality_flag
            else ()
        )
        if reasons:
            return DetectionDecision(
                classification=DealClassification.NONE,
                current_price=current.price,
                rejection_reasons=reasons,
                blocking_quality_flags=blocking_flags,
                signals=_empty_signals(),
                history_samples_used=0,
                history_samples_ignored=len(history_items),
            )

        # The missing/non-positive price cases above guarantee a Decimal here.
        price = current.price
        assert price is not None and price > _ZERO

        comparable = [
            observation
            for observation in history_items
            if _is_eligible_history(observation, current, self.config)
        ]
        comparable.sort(key=lambda item: (item.observed_at, item.source_payload_hash))
        history_ready = len(comparable) >= self.config.minimum_history_samples
        history_prices = [item.price for item in comparable]
        assert all(item is not None and item > _ZERO for item in history_prices)
        exact_prices = [item for item in history_prices if item is not None]

        previous_price = exact_prices[-1] if exact_prices else None
        median_price = _median(exact_prices) if exact_prices else None
        minimum_price = min(exact_prices) if exact_prices else None

        signals = (
            _assess_signal(
                SignalKind.PREVIOUS_PRICE,
                price,
                previous_price,
                eligible=history_ready,
                thresholds=self.config.previous_price_thresholds,
                sample_count=len(exact_prices),
            ),
            _assess_signal(
                SignalKind.HISTORICAL_MEDIAN,
                price,
                median_price,
                eligible=history_ready,
                thresholds=self.config.historical_median_thresholds,
                sample_count=len(exact_prices),
            ),
            _assess_signal(
                SignalKind.HISTORICAL_MINIMUM,
                price,
                minimum_price,
                eligible=history_ready,
                thresholds=self.config.historical_minimum_thresholds,
                sample_count=len(exact_prices),
            ),
            _assess_signal(
                SignalKind.LIST_PRICE,
                price,
                current.list_price,
                eligible=current.list_price is not None and current.list_price > _ZERO,
                thresholds=self.config.list_price_thresholds,
            ),
        )
        classification = max(
            (signal.classification for signal in signals),
            key=_classification_rank,
        )
        return DetectionDecision(
            classification=classification,
            current_price=price,
            rejection_reasons=(),
            blocking_quality_flags=(),
            signals=signals,
            history_samples_used=len(comparable),
            history_samples_ignored=len(history_items) - len(comparable),
        )


def detect_deal(
    current: PriceObservation,
    history: Iterable[PriceObservation] = (),
    *,
    expected: ExpectedProductContext | None = None,
    config: DetectorConfig | None = None,
) -> DetectionDecision:
    """Convenience function for one-off deterministic evaluations."""

    return DealDetector(config).evaluate(current, history, expected=expected)


def _empty_signals() -> tuple[SignalAssessment, ...]:
    return tuple(
        SignalAssessment(
            kind=kind,
            eligible=False,
            reference_price=None,
            discount_ratio=None,
            classification=DealClassification.NONE,
        )
        for kind in SignalKind
    )


def _rejection_reasons(
    observation: PriceObservation,
    config: DetectorConfig,
    expected: ExpectedProductContext | None,
) -> tuple[RejectionReason, ...]:
    reasons: list[RejectionReason] = []
    if observation.currency != config.allowed_currency:
        reasons.append(RejectionReason.CURRENCY_NOT_ALLOWED)
    if observation.price is None:
        reasons.append(RejectionReason.MISSING_PRICE)
    elif observation.price <= _ZERO:
        reasons.append(RejectionReason.NON_POSITIVE_PRICE)
    if observation.availability not in config.allowed_availabilities:
        reasons.append(RejectionReason.NOT_IN_STOCK)
    if observation.is_marketplace:
        reasons.append(RejectionReason.MARKETPLACE_OFFER)
    if observation.condition is not ProductCondition.NEW:
        reasons.append(RejectionReason.CONDITION_NOT_NEW)
    if config.reject_any_quality_flag and observation.quality_flags:
        reasons.append(RejectionReason.QUALITY_FLAGS_PRESENT)
    if _looks_like_installment_price(observation):
        reasons.append(RejectionReason.INSTALLMENT_USED_AS_PRICE)

    if expected is not None:
        identity_matches = (
            _matches_if_expected(observation.store_slug, expected.store_slug)
            and _matches_if_expected(
                observation.external_product_id,
                expected.external_product_id,
            )
            and _matches_if_expected(observation.sku, expected.sku)
            and _matches_if_expected(observation.seller_id, expected.seller_id)
        )
        if not identity_matches:
            reasons.append(RejectionReason.EXPECTED_PRODUCT_MISMATCH)

        brand_matches = expected.brand is None or (
            observation.brand is not None
            and _normalized_words(observation.brand) == _normalized_words(expected.brand)
        )
        model_matches = expected.model is None or (
            _normalized_words(observation.model) == _normalized_words(expected.model)
            if observation.model is not None
            else _contains_normalized_phrase(observation.title, expected.model)
        )
        if not brand_matches or not model_matches:
            reasons.append(RejectionReason.EXPECTED_PRODUCT_MISMATCH)

        if expected.variant and canonicalize_variant(observation.variant) != expected.variant:
            reasons.append(RejectionReason.EXPECTED_VARIANT_MISMATCH)

        if expected.expected_is_accessory is False and _looks_like_accessory(
            observation.title,
            config.accessory_terms,
        ):
            reasons.append(RejectionReason.ACCESSORY_MISMATCH)

    return tuple(dict.fromkeys(reasons))


def _is_eligible_history(
    candidate: PriceObservation,
    current: PriceObservation,
    config: DetectorConfig,
) -> bool:
    if candidate.observed_at >= current.observed_at:
        return False
    if not _same_offer(candidate, current):
        return False
    if candidate.currency != config.allowed_currency:
        return False
    if candidate.price is None or candidate.price <= _ZERO:
        return False
    if candidate.availability not in config.allowed_availabilities:
        return False
    if candidate.is_marketplace or candidate.condition is not ProductCondition.NEW:
        return False
    if config.reject_any_quality_flag and candidate.quality_flags:
        return False
    return not _looks_like_installment_price(candidate)


def _same_offer(left: PriceObservation, right: PriceObservation) -> bool:
    return (
        left.store_slug == right.store_slug
        and left.external_product_id == right.external_product_id
        and left.sku == right.sku
        and left.seller_id == right.seller_id
        and canonicalize_variant(left.variant) == canonicalize_variant(right.variant)
    )


def _matches_if_expected(actual: str, expected: str | None) -> bool:
    return expected is None or _normalized_words(actual) == _normalized_words(expected)


def _contains_normalized_phrase(actual: str, expected: str) -> bool:
    normalized_actual = f" {_normalized_words(actual)} "
    normalized_expected = _normalized_words(expected)
    return bool(normalized_expected) and f" {normalized_expected} " in normalized_actual


def _looks_like_installment_price(observation: PriceObservation) -> bool:
    if observation.price is None:
        return False
    return any(
        option.count > 1
        and option.currency == observation.currency
        and option.amount == observation.price
        for option in observation.installments
    )


def _looks_like_accessory(title: str, accessory_terms: frozenset[str]) -> bool:
    title_words = _normalized_words(title).split()
    for term in accessory_terms:
        term_words = term.split()
        maximum_start = min(2, len(title_words) - len(term_words))
        if any(
            title_words[start : start + len(term_words)] == term_words
            for start in range(maximum_start + 1)
        ):
            return True
    return False


def canonicalize_variant(variant: Mapping[str, str]) -> dict[str, str]:
    """Return the stable identity form used by validation, history, and dedupe."""

    normalized: dict[str, str] = {}
    for key, value in variant.items():
        normalized_key = _normalized_words(key)
        normalized_value = _normalized_words(value)
        if not normalized_key or not normalized_value:
            raise ValueError("variant keys and values must not be empty")
        if normalized_key in normalized:
            raise ValueError("variant keys must be unique after normalization")
        normalized[normalized_key] = normalized_value
    return normalized


def _normalized_words(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.strip().casefold())
    without_accents = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(re.findall(r"[a-z0-9]+", without_accents))


def _median(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal("2")


def _assess_signal(
    kind: SignalKind,
    current_price: Decimal,
    reference_price: Decimal | None,
    *,
    eligible: bool,
    thresholds: SignalThresholds,
    sample_count: int | None = None,
) -> SignalAssessment:
    if reference_price is None or reference_price <= _ZERO:
        return SignalAssessment(
            kind=kind,
            eligible=False,
            reference_price=reference_price,
            discount_ratio=None,
            classification=DealClassification.NONE,
            sample_count=sample_count,
        )

    with localcontext() as context:
        context.prec = 28
        ratio = ((reference_price - current_price) / reference_price).quantize(
            _RATIO_QUANTUM,
            rounding=ROUND_HALF_UP,
        )

    classification = (
        _classify_reduction(current_price, reference_price, thresholds)
        if eligible
        else DealClassification.NONE
    )
    return SignalAssessment(
        kind=kind,
        eligible=eligible,
        reference_price=reference_price,
        discount_ratio=ratio,
        classification=classification,
        sample_count=sample_count,
    )


def _classify_reduction(
    current_price: Decimal,
    reference_price: Decimal,
    thresholds: SignalThresholds,
) -> DealClassification:
    reduction = reference_price - current_price
    if reduction < _ZERO:
        return DealClassification.NONE
    if reduction >= reference_price * thresholds.possible_price_error:
        return DealClassification.POSSIBLE_PRICE_ERROR
    if reduction >= reference_price * thresholds.exceptional_deal:
        return DealClassification.EXCEPTIONAL_DEAL
    if reduction >= reference_price * thresholds.good_deal:
        return DealClassification.GOOD_DEAL
    return DealClassification.NONE


def _classification_rank(classification: DealClassification) -> int:
    return {
        DealClassification.NONE: 0,
        DealClassification.GOOD_DEAL: 1,
        DealClassification.EXCEPTIONAL_DEAL: 2,
        DealClassification.POSSIBLE_PRICE_ERROR: 3,
    }[classification]


__all__ = [
    "DealClassification",
    "DealDetector",
    "DetectionDecision",
    "DetectorConfig",
    "ExpectedProductContext",
    "RejectionReason",
    "SignalAssessment",
    "SignalKind",
    "SignalThresholds",
    "canonicalize_variant",
    "detect_deal",
]
