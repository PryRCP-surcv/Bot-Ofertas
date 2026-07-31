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
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext
from enum import StrEnum

from bot_ofertas.domain import Availability, PriceObservation, ProductCondition

_RATIO_QUANTUM = Decimal("0.0001")
_ZERO = Decimal("0")
COMMERCIAL_CONDITION_SIGNATURE_PREFIX = "commercial_condition_signature:"
_COMMERCIAL_CONDITION_SIGNATURE_PATTERN = re.compile(
    rf"^{re.escape(COMMERCIAL_CONDITION_SIGNATURE_PREFIX)}([0-9a-fA-F]{{64}})$"
)
UNUSABLE_LIST_PRICE_QUALITY_FLAGS = frozenset(
    {
        "non_positive_list_price",
        "list_price_below_price",
    }
)
_INSTALLMENT_ONLY_PRICE_FLAG = "installment_only_price"
_CONDITIONAL_FLAG_REASONS = {
    "conditional_card_price": "payment_method",
    "conditional_payment_method_price": "payment_method",
    "payment_method_price": "payment_method",
    "card_only_price": "payment_method",
    "tarjeta_only_price": "payment_method",
    "conditional_membership_price": "membership",
    "membership_price": "membership",
    "membership_only_price": "membership",
    "conditional_coupon_price": "coupon",
    "coupon_price": "coupon",
    "coupon_only_price": "coupon",
    "conditional_quantity_price": "minimum_quantity",
    "minimum_quantity_price": "minimum_quantity",
    "quantity_tier_price": "minimum_quantity",
    "conditional_promotion_price": "promotion",
}
INFORMATIONAL_QUALITY_FLAGS = frozenset(
    {
        "available_quantity_sentinel",
        "delivery_location_confirmation",
        "non_positive_list_price",
        "list_price_below_price",
        *_CONDITIONAL_FLAG_REASONS,
    }
)


class DealClassification(StrEnum):
    """Alert severity in ascending order."""

    NONE = "none"
    GOOD_DEAL = "good_deal"
    EXCEPTIONAL_DEAL = "exceptional_deal"
    POSSIBLE_PRICE_ERROR = "possible_price_error"


class SignalKind(StrEnum):
    """Price references evaluated by the detector."""

    PREVIOUS_PRICE = "previous_price"
    MEDIAN_7D = "median_7d"
    MEDIAN_30D = "median_30d"
    HISTORICAL_MEDIAN = "historical_median"
    # Keep the Phase 1 value stable for persistence and notification consumers.
    MEDIAN_90D = "historical_median"
    HISTORICAL_MINIMUM = "historical_minimum"
    EQUIVALENT_MEDIAN = "equivalent_median"
    LIST_PRICE = "list_price"


class ConfidenceLevel(StrEnum):
    """Evidence strength, deliberately independent from deal severity."""

    NONE = "none"
    INSUFFICIENT = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PriceConditionFamily(StrEnum):
    """Stable families used to compare like-for-like conditional prices."""

    PAYMENT_METHOD = "payment_method"
    MEMBERSHIP = "membership"
    COUPON = "coupon"
    MINIMUM_QUANTITY = "minimum_quantity"
    PROMOTION = "promotion"


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
    VARIANT_SELECTION_REQUIRED = "variant_selection_required"
    ACCESSORY_MISMATCH = "accessory_mismatch"
    CONDITIONAL_CARD_PRICE = "conditional_card_price"
    CONDITIONAL_MEMBERSHIP_PRICE = "conditional_membership_price"
    CONDITIONAL_COUPON_PRICE = "conditional_coupon_price"
    CONDITIONAL_QUANTITY_PRICE = "conditional_quantity_price"
    CONDITIONAL_PROMOTION_PRICE = "conditional_promotion_price"


@dataclass(frozen=True, slots=True)
class QualityFlagAssessment:
    """Auditable partition of raw flags under detector quality policy."""

    informational_quality_flags: tuple[str, ...]
    blocking_quality_flags: tuple[str, ...]
    conditional_quality_flags: tuple[str, ...]
    conditional_price_families: tuple[PriceConditionFamily, ...]


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
    minimum_equivalent_samples: int = 2
    possible_error_minimum_corroborating_signals: int = 2
    possible_error_minimum_confidence: int = 50
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
        if (
            not isinstance(self.minimum_equivalent_samples, int)
            or isinstance(self.minimum_equivalent_samples, bool)
            or self.minimum_equivalent_samples < 1
        ):
            raise ValueError("minimum_equivalent_samples must be a positive integer")
        if (
            not isinstance(self.possible_error_minimum_corroborating_signals, int)
            or isinstance(self.possible_error_minimum_corroborating_signals, bool)
            or self.possible_error_minimum_corroborating_signals < 2
        ):
            raise ValueError("possible_error_minimum_corroborating_signals must be at least 2")
        if (
            not isinstance(self.possible_error_minimum_confidence, int)
            or isinstance(self.possible_error_minimum_confidence, bool)
            or not 0 <= self.possible_error_minimum_confidence <= 100
        ):
            raise ValueError("possible_error_minimum_confidence must be between 0 and 100")
        if not isinstance(self.reject_any_quality_flag, bool):
            raise TypeError("reject_any_quality_flag must be a boolean")

        availabilities = frozenset(
            Availability(availability) for availability in self.allowed_availabilities
        )
        if not availabilities:
            raise ValueError("allowed_availabilities must not be empty")
        object.__setattr__(self, "allowed_availabilities", availabilities)

        terms = frozenset(
            normalized for term in self.accessory_terms if (normalized := _normalized_words(term))
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
    variant_selection_required: bool = False

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
        if not isinstance(self.variant_selection_required, bool):
            raise TypeError("variant_selection_required must be a boolean")


@dataclass(frozen=True, slots=True)
class SignalAssessment:
    """Auditable evaluation of a single price reference."""

    kind: SignalKind
    eligible: bool
    reference_price: Decimal | None
    discount_ratio: Decimal | None
    classification: DealClassification
    sample_count: int | None = None
    window_days: int | None = None

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
    confidence_score: int = 0
    confidence_level: ConfidenceLevel = ConfidenceLevel.INSUFFICIENT
    corroborating_signal_count: int = 0
    informational_quality_flags: tuple[str, ...] = ()
    conditional_quality_flags: tuple[str, ...] = ()
    conditional_price_families: tuple[PriceConditionFamily, ...] = ()

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
        historical_minimum: Decimal | None = None,
        equivalent_prices: Iterable[Decimal] = (),
    ) -> DetectionDecision:
        """Evaluate one observation against earlier exact-comparable observations."""

        history_items = tuple(history)
        explicit_historical_minimum = _optional_positive_reference(
            historical_minimum,
            "historical_minimum",
        )
        normalized_equivalent_prices = tuple(
            _positive_reference(value, "equivalent price") for value in equivalent_prices
        )
        quality_flags = assess_quality_flags(
            current.quality_flags,
            reject_unknown=self.config.reject_any_quality_flag,
        )
        reasons = _rejection_reasons(
            current,
            self.config,
            expected,
            blocking_quality_flags=quality_flags.blocking_quality_flags,
        )
        if reasons:
            return DetectionDecision(
                classification=DealClassification.NONE,
                current_price=current.price,
                rejection_reasons=reasons,
                blocking_quality_flags=quality_flags.blocking_quality_flags,
                signals=_empty_signals(),
                history_samples_used=0,
                history_samples_ignored=len(history_items),
                confidence_score=0,
                confidence_level=ConfidenceLevel.INSUFFICIENT,
                corroborating_signal_count=0,
                informational_quality_flags=quality_flags.informational_quality_flags,
                conditional_quality_flags=quality_flags.conditional_quality_flags,
                conditional_price_families=quality_flags.conditional_price_families,
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
        prices_7d = _window_prices(comparable, current=current, days=7)
        prices_30d = _window_prices(comparable, current=current, days=30)
        prices_90d = _window_prices(comparable, current=current, days=90)
        median_7d = _median(prices_7d) if prices_7d else None
        median_30d = _median(prices_30d) if prices_30d else None
        median_90d = _median(prices_90d) if prices_90d else None
        minimum_price = (
            explicit_historical_minimum
            if explicit_historical_minimum is not None
            else min(exact_prices)
            if exact_prices
            else None
        )
        equivalent_median = (
            _median(list(normalized_equivalent_prices)) if normalized_equivalent_prices else None
        )

        signals = (
            _assess_signal(
                SignalKind.PREVIOUS_PRICE,
                price,
                previous_price,
                eligible=previous_price is not None,
                thresholds=self.config.previous_price_thresholds,
                sample_count=len(exact_prices),
            ),
            _assess_signal(
                SignalKind.MEDIAN_7D,
                price,
                median_7d,
                eligible=len(prices_7d) >= self.config.minimum_history_samples,
                thresholds=self.config.historical_median_thresholds,
                sample_count=len(prices_7d),
                window_days=7,
            ),
            _assess_signal(
                SignalKind.MEDIAN_30D,
                price,
                median_30d,
                eligible=len(prices_30d) >= self.config.minimum_history_samples,
                thresholds=self.config.historical_median_thresholds,
                sample_count=len(prices_30d),
                window_days=30,
            ),
            _assess_signal(
                SignalKind.MEDIAN_90D,
                price,
                median_90d,
                eligible=len(prices_90d) >= self.config.minimum_history_samples,
                thresholds=self.config.historical_median_thresholds,
                sample_count=len(prices_90d),
                window_days=90,
            ),
            _assess_signal(
                SignalKind.HISTORICAL_MINIMUM,
                price,
                minimum_price,
                eligible=explicit_historical_minimum is not None or history_ready,
                thresholds=self.config.historical_minimum_thresholds,
                sample_count=len(exact_prices),
            ),
            _assess_signal(
                SignalKind.EQUIVALENT_MEDIAN,
                price,
                equivalent_median,
                eligible=(
                    len(normalized_equivalent_prices) >= self.config.minimum_equivalent_samples
                ),
                thresholds=self.config.historical_median_thresholds,
                sample_count=len(normalized_equivalent_prices),
            ),
            _assess_signal(
                SignalKind.LIST_PRICE,
                price,
                current.list_price,
                eligible=(
                    current.list_price is not None
                    and current.list_price > _ZERO
                    and not _has_quality_flag(
                        current.quality_flags,
                        UNUSABLE_LIST_PRICE_QUALITY_FLAGS,
                    )
                ),
                thresholds=self.config.list_price_thresholds,
            ),
        )
        raw_classification = max(
            (signal.classification for signal in signals),
            key=_classification_rank,
        )
        confidence_score = _confidence_score(signals)
        confidence_level = _confidence_level(confidence_score)
        corroborating_signal_count = _possible_error_corroborating_signal_count(signals)
        classification = raw_classification
        if raw_classification is DealClassification.POSSIBLE_PRICE_ERROR and (
            corroborating_signal_count < self.config.possible_error_minimum_corroborating_signals
            or confidence_score < self.config.possible_error_minimum_confidence
        ):
            # A single catalogue/list reference can support a deal, but never the
            # stronger claim that the store may have made a pricing error.
            classification = DealClassification.EXCEPTIONAL_DEAL
        return DetectionDecision(
            classification=classification,
            current_price=price,
            rejection_reasons=(),
            blocking_quality_flags=(),
            signals=signals,
            history_samples_used=len(comparable),
            history_samples_ignored=len(history_items) - len(comparable),
            confidence_score=confidence_score,
            confidence_level=confidence_level,
            corroborating_signal_count=corroborating_signal_count,
            informational_quality_flags=quality_flags.informational_quality_flags,
            conditional_quality_flags=quality_flags.conditional_quality_flags,
            conditional_price_families=quality_flags.conditional_price_families,
        )


def detect_deal(
    current: PriceObservation,
    history: Iterable[PriceObservation] = (),
    *,
    expected: ExpectedProductContext | None = None,
    config: DetectorConfig | None = None,
    historical_minimum: Decimal | None = None,
    equivalent_prices: Iterable[Decimal] = (),
) -> DetectionDecision:
    """Convenience function for one-off deterministic evaluations."""

    return DealDetector(config).evaluate(
        current,
        history,
        expected=expected,
        historical_minimum=historical_minimum,
        equivalent_prices=equivalent_prices,
    )


def _empty_signals() -> tuple[SignalAssessment, ...]:
    return tuple(
        SignalAssessment(
            kind=kind,
            eligible=False,
            reference_price=None,
            discount_ratio=None,
            classification=DealClassification.NONE,
            window_days=_signal_window_days(kind),
        )
        for kind in SignalKind
    )


def _rejection_reasons(
    observation: PriceObservation,
    config: DetectorConfig,
    expected: ExpectedProductContext | None,
    *,
    blocking_quality_flags: tuple[str, ...],
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
    conditional_reasons = _conditional_rejection_reasons(blocking_quality_flags)
    reasons.extend(conditional_reasons)
    if any(_uses_generic_quality_rejection(flag) for flag in blocking_quality_flags):
        reasons.append(RejectionReason.QUALITY_FLAGS_PRESENT)
    if any(
        _normalized_quality_flag(flag) == _INSTALLMENT_ONLY_PRICE_FLAG
        for flag in blocking_quality_flags
    ) or _looks_like_installment_price(observation):
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

        if expected.variant_selection_required and not expected.variant:
            reasons.append(RejectionReason.VARIANT_SELECTION_REQUIRED)
        elif expected.variant and canonicalize_variant(observation.variant) != expected.variant:
            reasons.append(RejectionReason.EXPECTED_VARIANT_MISMATCH)

        if expected.expected_is_accessory is False and _looks_like_accessory(
            observation.title,
            config.accessory_terms,
        ):
            reasons.append(RejectionReason.ACCESSORY_MISMATCH)

    return tuple(dict.fromkeys(reasons))


def assess_quality_flags(
    quality_flags: Iterable[str],
    *,
    reject_unknown: bool = True,
) -> QualityFlagAssessment:
    """Partition flags and expose condition families for downstream reuse."""

    if not isinstance(reject_unknown, bool):
        raise TypeError("reject_unknown must be a boolean")

    informational: set[str] = set()
    blocking: set[str] = set()
    conditional: set[str] = set()
    families: set[PriceConditionFamily] = set()
    for raw_flag in quality_flags:
        if not isinstance(raw_flag, str):
            raise TypeError("quality flags must be strings")
        flag = _normalized_quality_flag(raw_flag)
        signature = _commercial_condition_signature(raw_flag)
        family = _CONDITIONAL_FLAG_REASONS.get(flag)
        if family is not None:
            conditional.add(raw_flag)
            families.add(PriceConditionFamily(family))
        if signature is not None or flag in INFORMATIONAL_QUALITY_FLAGS:
            informational.add(raw_flag)
        elif (
            _is_commercial_condition_signature_flag(raw_flag)
            or flag == _INSTALLMENT_ONLY_PRICE_FLAG
            or family is not None
            or reject_unknown
        ):
            blocking.add(raw_flag)
    if len(families) > 1:
        # VTEX adds a generic promotion marker alongside a more precise condition.
        # Suppressing only that generic family keeps offer signatures stable.
        families.discard(PriceConditionFamily.PROMOTION)
    return QualityFlagAssessment(
        informational_quality_flags=tuple(sorted(informational)),
        blocking_quality_flags=tuple(sorted(blocking)),
        conditional_quality_flags=tuple(sorted(conditional)),
        conditional_price_families=tuple(sorted(families, key=lambda item: item.value)),
    )


def conditional_price_families(
    quality_flags: Iterable[str],
) -> tuple[PriceConditionFamily, ...]:
    """Return stable conditional-price identities without rejecting other flags."""

    return assess_quality_flags(
        quality_flags,
        reject_unknown=False,
    ).conditional_price_families


def commercial_condition_signatures(
    quality_flags: Iterable[str],
) -> tuple[str, ...]:
    """Return valid commercial-condition hashes, normalized and deduplicated."""

    signatures: set[str] = set()
    for raw_flag in quality_flags:
        if not isinstance(raw_flag, str):
            raise TypeError("quality flags must be strings")
        signature = _commercial_condition_signature(raw_flag)
        if signature is not None:
            signatures.add(signature)
    return tuple(sorted(signatures))


def _commercial_condition_signature(raw_flag: str) -> str | None:
    match = _COMMERCIAL_CONDITION_SIGNATURE_PATTERN.fullmatch(raw_flag.strip())
    return match.group(1).lower() if match is not None else None


def _is_commercial_condition_signature_flag(raw_flag: str) -> bool:
    return raw_flag.strip().casefold().startswith(COMMERCIAL_CONDITION_SIGNATURE_PREFIX)


def _normalized_quality_flag(raw_flag: str) -> str:
    return raw_flag.strip().casefold()


def _has_quality_flag(
    quality_flags: Iterable[str],
    expected_flags: frozenset[str],
) -> bool:
    return any(_normalized_quality_flag(flag) in expected_flags for flag in quality_flags)


def _uses_generic_quality_rejection(raw_flag: str) -> bool:
    flag = _normalized_quality_flag(raw_flag)
    return flag not in _CONDITIONAL_FLAG_REASONS and flag != _INSTALLMENT_ONLY_PRICE_FLAG


def _conditional_rejection_reasons(
    quality_flags: Iterable[str],
) -> tuple[RejectionReason, ...]:
    reason_by_kind = {
        "payment_method": RejectionReason.CONDITIONAL_CARD_PRICE,
        "membership": RejectionReason.CONDITIONAL_MEMBERSHIP_PRICE,
        "coupon": RejectionReason.CONDITIONAL_COUPON_PRICE,
        "minimum_quantity": RejectionReason.CONDITIONAL_QUANTITY_PRICE,
        "promotion": RejectionReason.CONDITIONAL_PROMOTION_PRICE,
    }
    reasons: list[RejectionReason] = []
    for raw_flag in quality_flags:
        flag = _normalized_quality_flag(raw_flag)
        kind = _CONDITIONAL_FLAG_REASONS.get(flag)
        if kind is not None:
            reasons.append(reason_by_kind[kind])
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
    quality_flags = assess_quality_flags(
        candidate.quality_flags,
        reject_unknown=config.reject_any_quality_flag,
    )
    if quality_flags.blocking_quality_flags:
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


def _window_prices(
    observations: Iterable[PriceObservation],
    *,
    current: PriceObservation,
    days: int,
) -> list[Decimal]:
    cutoff = current.observed_at - timedelta(days=days)
    return [
        observation.price
        for observation in observations
        if observation.observed_at >= cutoff and observation.price is not None
    ]


def _optional_positive_reference(
    value: Decimal | None,
    field_name: str,
) -> Decimal | None:
    if value is None:
        return None
    return _positive_reference(value, field_name)


def _positive_reference(value: Decimal, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be a Decimal")
    if not value.is_finite() or value <= _ZERO:
        raise ValueError(f"{field_name} must be finite and positive")
    return value


def _signal_window_days(kind: SignalKind) -> int | None:
    return {
        SignalKind.MEDIAN_7D: 7,
        SignalKind.MEDIAN_30D: 30,
        SignalKind.MEDIAN_90D: 90,
    }.get(kind)


def _confidence_score(signals: Iterable[SignalAssessment]) -> int:
    """Measure evidence availability without incorporating discount magnitude."""

    weights = {
        SignalKind.PREVIOUS_PRICE: 10,
        SignalKind.MEDIAN_7D: 10,
        SignalKind.MEDIAN_30D: 15,
        SignalKind.MEDIAN_90D: 20,
        SignalKind.HISTORICAL_MINIMUM: 10,
        SignalKind.EQUIVALENT_MEDIAN: 10,
        SignalKind.LIST_PRICE: 5,
    }
    # A validated current observation is the prerequisite evidence.
    score = 20 + sum(weights.get(signal.kind, 0) for signal in signals if signal.eligible)
    return min(100, score)


def _confidence_level(score: int) -> ConfidenceLevel:
    if score <= 0:
        return ConfidenceLevel.INSUFFICIENT
    if score < 40:
        return ConfidenceLevel.LOW
    if score < 70:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.HIGH


def _possible_error_corroborating_signal_count(
    signals: Iterable[SignalAssessment],
) -> int:
    """Count independent reference families supporting possible-error severity."""

    families: set[str] = set()
    for signal in signals:
        if (
            not signal.eligible
            or signal.classification is not DealClassification.POSSIBLE_PRICE_ERROR
        ):
            continue
        if signal.kind is SignalKind.PREVIOUS_PRICE:
            families.add("previous")
        elif signal.kind in {
            SignalKind.MEDIAN_7D,
            SignalKind.MEDIAN_30D,
            SignalKind.MEDIAN_90D,
        }:
            families.add("historical_median")
        elif signal.kind is SignalKind.HISTORICAL_MINIMUM:
            families.add("historical_minimum")
        elif signal.kind is SignalKind.EQUIVALENT_MEDIAN:
            families.add("equivalent_median")
        # List price is deliberately not corroboration for a possible error.
    return len(families)


def _assess_signal(
    kind: SignalKind,
    current_price: Decimal,
    reference_price: Decimal | None,
    *,
    eligible: bool,
    thresholds: SignalThresholds,
    sample_count: int | None = None,
    window_days: int | None = None,
) -> SignalAssessment:
    if reference_price is None or reference_price <= _ZERO:
        return SignalAssessment(
            kind=kind,
            eligible=False,
            reference_price=reference_price,
            discount_ratio=None,
            classification=DealClassification.NONE,
            sample_count=sample_count,
            window_days=window_days,
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
        window_days=window_days,
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
    "COMMERCIAL_CONDITION_SIGNATURE_PREFIX",
    "ConfidenceLevel",
    "DealClassification",
    "DealDetector",
    "DetectionDecision",
    "DetectorConfig",
    "ExpectedProductContext",
    "INFORMATIONAL_QUALITY_FLAGS",
    "PriceConditionFamily",
    "QualityFlagAssessment",
    "RejectionReason",
    "SignalAssessment",
    "SignalKind",
    "SignalThresholds",
    "UNUSABLE_LIST_PRICE_QUALITY_FLAGS",
    "assess_quality_flags",
    "canonicalize_variant",
    "commercial_condition_signatures",
    "conditional_price_families",
    "detect_deal",
]
