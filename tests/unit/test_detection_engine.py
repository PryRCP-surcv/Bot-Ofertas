from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from bot_ofertas.detection import (
    COMMERCIAL_CONDITION_SIGNATURE_PREFIX,
    INFORMATIONAL_QUALITY_FLAGS,
    ConfidenceLevel,
    DealClassification,
    DetectorConfig,
    ExpectedProductContext,
    PriceConditionFamily,
    RejectionReason,
    SignalKind,
    SignalThresholds,
    assess_quality_flags,
    commercial_condition_signatures,
    conditional_price_families,
    detect_deal,
)
from bot_ofertas.domain import (
    Availability,
    InstallmentOption,
    PriceObservation,
    ProductCondition,
)

NOW = datetime(2026, 7, 27, 12, tzinfo=UTC)


def make_observation(
    *,
    price: Decimal | None = Decimal("100"),
    list_price: Decimal | None = None,
    observed_at: datetime = NOW,
    **overrides: object,
) -> PriceObservation:
    values: dict[str, object] = {
        "store_slug": "coolbox",
        "source_url": "https://www.coolbox.pe/laptop-demo/p",
        "external_product_id": "product-1",
        "sku": "sku-1",
        "seller_id": "1",
        "seller_name": "Coolbox",
        "title": "Laptop Demo 16 GB",
        "condition": ProductCondition.NEW,
        "currency": "PEN",
        "availability": Availability.IN_STOCK,
        "is_marketplace": False,
        "observed_at": observed_at,
        "extractor_version": "test-v1",
        "source_payload_hash": f"{int(observed_at.timestamp()):064x}"[-64:],
        "variant": {"Memoria": "16 GB", "Color": "Negro"},
        "price": price,
        "list_price": list_price,
    }
    values.update(overrides)
    return PriceObservation(**values)  # type: ignore[arg-type]


def history_at_prices(*prices: str) -> list[PriceObservation]:
    return [
        make_observation(
            price=Decimal(price),
            observed_at=NOW - timedelta(days=len(prices) - index),
        )
        for index, price in enumerate(prices)
    ]


def signal(decision: object, kind: SignalKind) -> object:
    return next(item for item in decision.signals if item.kind is kind)  # type: ignore[attr-defined]


def test_audits_previous_median_minimum_and_list_price_signals() -> None:
    current = make_observation(price=Decimal("25"), list_price=Decimal("200"))
    decision = detect_deal(current, history_at_prices("120", "100", "110"))

    assert decision.classification is DealClassification.POSSIBLE_PRICE_ERROR
    assert decision.should_alert is True
    assert decision.history_samples_used == 3
    assert decision.history_samples_ignored == 0

    previous = signal(decision, SignalKind.PREVIOUS_PRICE)
    median = signal(decision, SignalKind.HISTORICAL_MEDIAN)
    minimum = signal(decision, SignalKind.HISTORICAL_MINIMUM)
    listed = signal(decision, SignalKind.LIST_PRICE)
    assert previous.reference_price == Decimal("110")
    assert previous.discount_ratio == Decimal("0.7727")
    assert median.reference_price == Decimal("110")
    assert minimum.reference_price == Decimal("100")
    assert listed.reference_price == Decimal("200")
    assert listed.discount_percent == Decimal("87.50")
    assert all(
        item.eligible for item in decision.signals if item.kind is not SignalKind.EQUIVALENT_MEDIAN
    )
    assert signal(decision, SignalKind.EQUIVALENT_MEDIAN).eligible is False
    assert decision.confidence_score == 90
    assert decision.confidence_level is ConfidenceLevel.HIGH
    assert decision.corroborating_signal_count >= 2


def test_previous_price_is_eligible_before_window_medians_are_ready() -> None:
    current = make_observation(price=Decimal("50"), list_price=Decimal("100"))
    decision = detect_deal(current, history_at_prices("200", "180"))

    assert decision.classification is DealClassification.EXCEPTIONAL_DEAL
    assert signal(decision, SignalKind.PREVIOUS_PRICE).eligible is True
    assert signal(decision, SignalKind.PREVIOUS_PRICE).reference_price == Decimal("180")
    assert signal(decision, SignalKind.MEDIAN_7D).eligible is False
    assert signal(decision, SignalKind.LIST_PRICE).classification is (
        DealClassification.EXCEPTIONAL_DEAL
    )


def test_computes_distinct_7_30_90_day_medians_and_equivalent_median() -> None:
    current = make_observation(price=Decimal("50"))
    history = [
        make_observation(price=Decimal("400"), observed_at=NOW - timedelta(days=100)),
        make_observation(price=Decimal("300"), observed_at=NOW - timedelta(days=40)),
        make_observation(price=Decimal("200"), observed_at=NOW - timedelta(days=10)),
        make_observation(price=Decimal("100"), observed_at=NOW - timedelta(days=2)),
    ]

    decision = detect_deal(
        current,
        reversed(history),
        config=DetectorConfig(
            minimum_history_samples=1,
            minimum_equivalent_samples=3,
        ),
        historical_minimum=Decimal("45"),
        equivalent_prices=(Decimal("90"), Decimal("110"), Decimal("130")),
    )

    median_7d = signal(decision, SignalKind.MEDIAN_7D)
    median_30d = signal(decision, SignalKind.MEDIAN_30D)
    median_90d = signal(decision, SignalKind.MEDIAN_90D)
    historical_minimum = signal(decision, SignalKind.HISTORICAL_MINIMUM)
    equivalents = signal(decision, SignalKind.EQUIVALENT_MEDIAN)
    assert median_7d.reference_price == Decimal("100")
    assert median_7d.sample_count == 1
    assert median_7d.window_days == 7
    assert median_30d.reference_price == Decimal("150")
    assert median_30d.sample_count == 2
    assert median_90d.reference_price == Decimal("200")
    assert median_90d.sample_count == 3
    assert SignalKind.MEDIAN_90D is SignalKind.HISTORICAL_MEDIAN
    assert historical_minimum.reference_price == Decimal("45")
    assert historical_minimum.eligible is True
    assert equivalents.reference_price == Decimal("110")
    assert equivalents.sample_count == 3


def test_two_independent_equivalent_prices_are_enough_by_default() -> None:
    decision = detect_deal(
        make_observation(price=Decimal("50")),
        equivalent_prices=(Decimal("100"), Decimal("120")),
    )

    equivalents = signal(decision, SignalKind.EQUIVALENT_MEDIAN)
    assert equivalents.eligible is True
    assert equivalents.reference_price == Decimal("110")
    assert equivalents.sample_count == 2


def test_window_cutoff_is_inclusive_and_future_samples_remain_ignored() -> None:
    current = make_observation(price=Decimal("80"))
    exact_cutoff = make_observation(
        price=Decimal("100"),
        observed_at=NOW - timedelta(days=7),
    )
    outside = make_observation(
        price=Decimal("200"),
        observed_at=NOW - timedelta(days=7, microseconds=1),
    )
    future = make_observation(
        price=Decimal("999"),
        observed_at=NOW + timedelta(seconds=1),
    )

    decision = detect_deal(
        current,
        [outside, future, exact_cutoff],
        config=DetectorConfig(minimum_history_samples=1),
    )

    median_7d = signal(decision, SignalKind.MEDIAN_7D)
    assert median_7d.reference_price == Decimal("100")
    assert median_7d.sample_count == 1
    assert decision.history_samples_used == 2
    assert decision.history_samples_ignored == 1


def test_list_price_alone_can_never_claim_a_possible_price_error() -> None:
    decision = detect_deal(
        make_observation(price=Decimal("10"), list_price=Decimal("100")),
    )

    assert signal(decision, SignalKind.LIST_PRICE).classification is (
        DealClassification.POSSIBLE_PRICE_ERROR
    )
    assert decision.classification is DealClassification.EXCEPTIONAL_DEAL
    assert decision.corroborating_signal_count == 0
    assert decision.confidence_score == 25
    assert decision.confidence_level is ConfidenceLevel.LOW


def test_confidence_depends_on_evidence_not_discount_severity() -> None:
    history = history_at_prices("100", "100", "100")

    ordinary = detect_deal(make_observation(price=Decimal("95")), history)
    dramatic = detect_deal(make_observation(price=Decimal("10")), history)

    assert ordinary.classification is DealClassification.NONE
    assert dramatic.classification is DealClassification.POSSIBLE_PRICE_ERROR
    assert ordinary.confidence_score == dramatic.confidence_score
    assert ordinary.confidence_level is dramatic.confidence_level


def test_previous_price_can_classify_but_not_claim_an_uncorroborated_price_error() -> None:
    decision = detect_deal(
        make_observation(price=Decimal("10")),
        history_at_prices("100", "100"),
    )

    assert decision.is_valid is True
    assert signal(decision, SignalKind.PREVIOUS_PRICE).classification is (
        DealClassification.POSSIBLE_PRICE_ERROR
    )
    assert signal(decision, SignalKind.MEDIAN_7D).eligible is False
    assert decision.classification is DealClassification.EXCEPTIONAL_DEAL
    assert decision.should_alert is True
    assert decision.corroborating_signal_count == 1


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"currency": "USD"}, RejectionReason.CURRENCY_NOT_ALLOWED),
        ({"price": None}, RejectionReason.MISSING_PRICE),
        ({"price": Decimal("0")}, RejectionReason.NON_POSITIVE_PRICE),
        ({"availability": Availability.OUT_OF_STOCK}, RejectionReason.NOT_IN_STOCK),
        ({"is_marketplace": True}, RejectionReason.MARKETPLACE_OFFER),
        ({"condition": ProductCondition.USED}, RejectionReason.CONDITION_NOT_NEW),
        ({"quality_flags": ["ambiguous_price"]}, RejectionReason.QUALITY_FLAGS_PRESENT),
    ],
)
def test_invalid_current_observations_never_alert(
    overrides: dict[str, object],
    reason: RejectionReason,
) -> None:
    decision = detect_deal(
        make_observation(list_price=Decimal("1000"), **overrides),
        history_at_prices("1000", "1000", "1000"),
    )

    assert decision.classification is DealClassification.NONE
    assert decision.should_alert is False
    assert reason in decision.rejection_reasons
    assert decision.history_samples_used == 0


@pytest.mark.parametrize(
    ("quality_flag", "family"),
    [
        ("conditional_card_price", PriceConditionFamily.PAYMENT_METHOD),
        ("conditional_payment_method_price", PriceConditionFamily.PAYMENT_METHOD),
        ("payment_method_price", PriceConditionFamily.PAYMENT_METHOD),
        ("card_only_price", PriceConditionFamily.PAYMENT_METHOD),
        ("tarjeta_only_price", PriceConditionFamily.PAYMENT_METHOD),
        ("conditional_membership_price", PriceConditionFamily.MEMBERSHIP),
        ("membership_price", PriceConditionFamily.MEMBERSHIP),
        ("membership_only_price", PriceConditionFamily.MEMBERSHIP),
        ("conditional_coupon_price", PriceConditionFamily.COUPON),
        ("coupon_price", PriceConditionFamily.COUPON),
        ("coupon_only_price", PriceConditionFamily.COUPON),
        ("conditional_quantity_price", PriceConditionFamily.MINIMUM_QUANTITY),
        ("minimum_quantity_price", PriceConditionFamily.MINIMUM_QUANTITY),
        ("quantity_tier_price", PriceConditionFamily.MINIMUM_QUANTITY),
        ("conditional_promotion_price", PriceConditionFamily.PROMOTION),
    ],
)
def test_conditioned_price_flags_are_informational_and_do_not_block(
    quality_flag: str,
    family: PriceConditionFamily,
) -> None:
    decision = detect_deal(
        make_observation(
            price=Decimal("10"),
            list_price=Decimal("100"),
            quality_flags=[quality_flag],
        )
    )

    assert quality_flag in INFORMATIONAL_QUALITY_FLAGS
    assert decision.rejection_reasons == ()
    assert decision.informational_quality_flags == (quality_flag,)
    assert decision.blocking_quality_flags == ()
    assert decision.conditional_quality_flags == (quality_flag,)
    assert decision.conditional_price_families == (family,)
    assert decision.should_alert is True
    assert decision.classification is DealClassification.EXCEPTIONAL_DEAL
    assert decision.confidence_score == 25
    assert decision.confidence_level is ConfidenceLevel.LOW


def test_available_quantity_sentinel_is_informational_and_does_not_block() -> None:
    decision = detect_deal(
        make_observation(
            price=Decimal("50"),
            list_price=Decimal("100"),
            quality_flags=["available_quantity_sentinel"],
        )
    )

    assert decision.rejection_reasons == ()
    assert decision.informational_quality_flags == ("available_quantity_sentinel",)
    assert decision.blocking_quality_flags == ()
    assert decision.conditional_quality_flags == ()
    assert decision.conditional_price_families == ()
    assert signal(decision, SignalKind.LIST_PRICE).eligible is True
    assert decision.should_alert is True


@pytest.mark.parametrize(
    "quality_flag",
    ["non_positive_list_price", "list_price_below_price"],
)
def test_invalid_list_price_flags_are_informational_but_disable_list_signal(
    quality_flag: str,
) -> None:
    historical = make_observation(
        price=Decimal("100"),
        observed_at=NOW - timedelta(hours=1),
    )
    decision = detect_deal(
        make_observation(
            price=Decimal("50"),
            list_price=Decimal("100"),
            quality_flags=[quality_flag],
        ),
        [historical],
        config=DetectorConfig(minimum_history_samples=1),
    )

    list_price = signal(decision, SignalKind.LIST_PRICE)
    assert decision.is_valid is True
    assert decision.informational_quality_flags == (quality_flag,)
    assert decision.blocking_quality_flags == ()
    assert list_price.reference_price == Decimal("100")
    assert list_price.eligible is False
    assert list_price.classification is DealClassification.NONE
    assert decision.should_alert is True


def test_informational_flag_keeps_detail_when_an_unrelated_flag_blocks() -> None:
    decision = detect_deal(
        make_observation(
            price=Decimal("10"),
            list_price=Decimal("100"),
            quality_flags=["payment_method_price", "ambiguous_price"],
        )
    )

    assert decision.rejection_reasons == (RejectionReason.QUALITY_FLAGS_PRESENT,)
    assert decision.informational_quality_flags == ("payment_method_price",)
    assert decision.blocking_quality_flags == ("ambiguous_price",)
    assert decision.conditional_quality_flags == ("payment_method_price",)
    assert decision.conditional_price_families == (PriceConditionFamily.PAYMENT_METHOD,)
    assert decision.should_alert is False


def test_public_quality_flag_helpers_expose_partition_and_condition_families() -> None:
    assessment = assess_quality_flags(
        [
            "payment_method_price",
            "conditional_promotion_price",
            "available_quantity_sentinel",
            "ambiguous_price",
            "installment_only_price",
        ]
    )

    assert assessment.informational_quality_flags == (
        "available_quantity_sentinel",
        "conditional_promotion_price",
        "payment_method_price",
    )
    assert assessment.blocking_quality_flags == (
        "ambiguous_price",
        "installment_only_price",
    )
    assert assessment.conditional_quality_flags == (
        "conditional_promotion_price",
        "payment_method_price",
    )
    assert assessment.conditional_price_families == (PriceConditionFamily.PAYMENT_METHOD,)
    assert conditional_price_families(
        [
            "coupon_price",
            "conditional_promotion_price",
            "membership_price",
            "unknown_flag",
        ]
    ) == (
        PriceConditionFamily.COUPON,
        PriceConditionFamily.MEMBERSHIP,
    )
    assert conditional_price_families(["conditional_promotion_price"]) == (
        PriceConditionFamily.PROMOTION,
    )


def test_commercial_condition_signature_is_informational_but_not_a_family() -> None:
    signature = "a" * 64
    signature_flag = f"{COMMERCIAL_CONDITION_SIGNATURE_PREFIX}{signature}"
    decision = detect_deal(
        make_observation(
            price=Decimal("50"),
            list_price=Decimal("100"),
            quality_flags=[
                "payment_method_price",
                "conditional_promotion_price",
                signature_flag,
            ],
        )
    )

    assert decision.rejection_reasons == ()
    assert signature_flag in decision.informational_quality_flags
    assert signature_flag not in decision.conditional_quality_flags
    assert decision.conditional_price_families == (PriceConditionFamily.PAYMENT_METHOD,)
    assert commercial_condition_signatures(decision.informational_quality_flags) == (signature,)
    assert decision.should_alert is True


def test_commercial_condition_signatures_are_sorted_normalized_and_deduplicated() -> None:
    flags = [
        f"{COMMERCIAL_CONDITION_SIGNATURE_PREFIX}{'b' * 64}",
        f"{COMMERCIAL_CONDITION_SIGNATURE_PREFIX}{'A' * 64}",
        f"{COMMERCIAL_CONDITION_SIGNATURE_PREFIX}{'a' * 64}",
        f"{COMMERCIAL_CONDITION_SIGNATURE_PREFIX}malformed",
        "unknown_flag",
    ]

    assert commercial_condition_signatures(flags) == ("a" * 64, "b" * 64)


@pytest.mark.parametrize(
    "signature_flag",
    [
        COMMERCIAL_CONDITION_SIGNATURE_PREFIX,
        f"{COMMERCIAL_CONDITION_SIGNATURE_PREFIX}{'a' * 63}",
        f"{COMMERCIAL_CONDITION_SIGNATURE_PREFIX}{'g' * 64}",
        f"{COMMERCIAL_CONDITION_SIGNATURE_PREFIX}{'a' * 64}extra",
        f"COMMERCIAL_CONDITION_SIGNATURE:{'a' * 64}",
    ],
)
def test_malformed_commercial_condition_signature_always_blocks(
    signature_flag: str,
) -> None:
    decision = detect_deal(
        make_observation(
            price=Decimal("50"),
            list_price=Decimal("100"),
            quality_flags=[signature_flag],
        ),
        config=DetectorConfig(reject_any_quality_flag=False),
    )

    assert decision.rejection_reasons == (RejectionReason.QUALITY_FLAGS_PRESENT,)
    assert decision.blocking_quality_flags == (signature_flag,)
    assert decision.informational_quality_flags == ()
    assert commercial_condition_signatures([signature_flag]) == ()
    assert decision.should_alert is False


def test_informational_quality_flags_are_eligible_history() -> None:
    historical = make_observation(
        price=Decimal("100"),
        observed_at=NOW - timedelta(hours=1),
        quality_flags=sorted(INFORMATIONAL_QUALITY_FLAGS),
    )

    decision = detect_deal(
        make_observation(price=Decimal("50")),
        [historical],
        config=DetectorConfig(minimum_history_samples=1),
    )

    assert decision.history_samples_used == 1
    assert decision.history_samples_ignored == 0
    assert signal(decision, SignalKind.PREVIOUS_PRICE).eligible is True
    assert decision.classification is DealClassification.EXCEPTIONAL_DEAL


def test_installment_only_quality_flag_remains_a_specific_blocker() -> None:
    decision = detect_deal(
        make_observation(
            price=Decimal("49.90"),
            list_price=Decimal("599"),
            quality_flags=["installment_only_price"],
        )
    )

    assert decision.rejection_reasons == (RejectionReason.INSTALLMENT_USED_AS_PRICE,)
    assert RejectionReason.QUALITY_FLAGS_PRESENT not in decision.rejection_reasons
    assert decision.blocking_quality_flags == ("installment_only_price",)
    assert decision.informational_quality_flags == ()
    assert decision.should_alert is False


def test_rejects_an_installment_amount_mistaken_for_total_price() -> None:
    current = make_observation(
        price=Decimal("49.90"),
        list_price=Decimal("599"),
        installments=[
            InstallmentOption(
                count=12,
                amount=Decimal("49.90"),
                currency="PEN",
                total=Decimal("598.80"),
            )
        ],
    )

    decision = detect_deal(current)

    assert RejectionReason.INSTALLMENT_USED_AS_PRICE in decision.rejection_reasons
    assert decision.should_alert is False


def test_expected_context_rejects_wrong_identity_and_variant() -> None:
    expected = ExpectedProductContext(
        store_slug="coolbox",
        external_product_id="product-1",
        sku="sku-expected",
        seller_id="1",
        variant={"memoria": "32 gb", "color": "negro"},
        expected_is_accessory=False,
    )

    decision = detect_deal(
        make_observation(price=Decimal("1"), list_price=Decimal("1000")),
        expected=expected,
    )

    assert decision.rejection_reasons == (
        RejectionReason.EXPECTED_PRODUCT_MISMATCH,
        RejectionReason.EXPECTED_VARIANT_MISMATCH,
    )
    assert decision.should_alert is False


def test_required_variant_selection_rejects_an_unconfigured_variant() -> None:
    decision = detect_deal(
        make_observation(price=Decimal("10"), list_price=Decimal("100")),
        expected=ExpectedProductContext(variant_selection_required=True),
    )

    assert RejectionReason.VARIANT_SELECTION_REQUIRED in decision.rejection_reasons
    assert decision.should_alert is False


def test_required_variant_selection_accepts_the_explicit_matching_variant() -> None:
    decision = detect_deal(
        make_observation(price=Decimal("50"), list_price=Decimal("100")),
        expected=ExpectedProductContext(
            variant_selection_required=True,
            variant={"Memoria": "16 GB", "Color": "Negro"},
        ),
    )

    assert RejectionReason.VARIANT_SELECTION_REQUIRED not in decision.rejection_reasons
    assert RejectionReason.EXPECTED_VARIANT_MISMATCH not in decision.rejection_reasons
    assert decision.is_valid is True


def test_expected_non_accessory_context_rejects_accessory_title() -> None:
    decision = detect_deal(
        make_observation(
            title="Funda para Laptop Demo 16 GB",
            price=Decimal("10"),
            list_price=Decimal("100"),
        ),
        expected=ExpectedProductContext(expected_is_accessory=False),
    )

    assert RejectionReason.ACCESSORY_MISMATCH in decision.rejection_reasons


def test_only_exact_earlier_comparable_history_is_used_regardless_of_input_order() -> None:
    exact = history_at_prices("100", "110", "120")
    wrong_variant = make_observation(
        price=Decimal("500"),
        observed_at=NOW - timedelta(hours=1),
        variant={"Memoria": "32 GB", "Color": "Negro"},
    )
    future = make_observation(price=Decimal("900"), observed_at=NOW + timedelta(hours=1))
    history = [future, exact[2], wrong_variant, exact[0], exact[1]]
    current = make_observation(price=Decimal("60"))

    first = detect_deal(current, history)
    second = detect_deal(current, reversed(history))

    assert first == second
    assert first.history_samples_used == 3
    assert first.history_samples_ignored == 2
    assert signal(first, SignalKind.PREVIOUS_PRICE).reference_price == Decimal("120")
    assert first.classification is DealClassification.EXCEPTIONAL_DEAL


def test_custom_decimal_thresholds_change_classification() -> None:
    config = DetectorConfig(
        minimum_history_samples=1,
        list_price_thresholds=SignalThresholds(
            good_deal=Decimal("0.10"),
            exceptional_deal=Decimal("0.20"),
            possible_price_error=Decimal("0.30"),
        ),
    )

    decision = detect_deal(
        make_observation(price=Decimal("75"), list_price=Decimal("100")),
        config=config,
    )

    assert decision.classification is DealClassification.EXCEPTIONAL_DEAL


def test_thresholds_reject_floats_and_invalid_order() -> None:
    with pytest.raises(TypeError, match="Decimal"):
        SignalThresholds(good_deal=0.1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="ordered"):
        SignalThresholds(
            good_deal=Decimal("0.50"),
            exceptional_deal=Decimal("0.40"),
            possible_price_error=Decimal("0.70"),
        )


def test_external_historical_minimum_is_audited_without_loaded_history() -> None:
    decision = detect_deal(
        make_observation(price=Decimal("50")),
        historical_minimum=Decimal("100"),
    )

    minimum = signal(decision, SignalKind.HISTORICAL_MINIMUM)
    assert minimum.eligible is True
    assert minimum.reference_price == Decimal("100")
    assert minimum.sample_count == 0
    assert decision.classification is DealClassification.EXCEPTIONAL_DEAL


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"historical_minimum": Decimal("0")}, ValueError),
        ({"historical_minimum": Decimal("NaN")}, ValueError),
        ({"historical_minimum": 100}, TypeError),
        ({"equivalent_prices": [Decimal("-1")]}, ValueError),
        ({"equivalent_prices": [99]}, TypeError),
    ],
)
def test_external_references_require_exact_positive_decimals(
    kwargs: dict[str, object],
    error: type[Exception],
) -> None:
    with pytest.raises(error):
        detect_deal(make_observation(), **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"minimum_equivalent_samples": 0},
        {"possible_error_minimum_corroborating_signals": 1},
        {"possible_error_minimum_confidence": -1},
        {"possible_error_minimum_confidence": 101},
    ],
)
def test_phase3_detector_config_rejects_unsafe_bounds(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        DetectorConfig(**kwargs)  # type: ignore[arg-type]
