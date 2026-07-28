from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from bot_ofertas.detection import (
    DealClassification,
    DetectorConfig,
    ExpectedProductContext,
    RejectionReason,
    SignalKind,
    SignalThresholds,
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
    assert all(item.eligible for item in decision.signals)


def test_history_needs_minimum_samples_but_list_price_can_classify_alone() -> None:
    current = make_observation(price=Decimal("50"), list_price=Decimal("100"))
    decision = detect_deal(current, history_at_prices("200", "180"))

    assert decision.classification is DealClassification.EXCEPTIONAL_DEAL
    assert signal(decision, SignalKind.PREVIOUS_PRICE).eligible is False
    assert signal(decision, SignalKind.PREVIOUS_PRICE).classification is DealClassification.NONE
    assert signal(decision, SignalKind.LIST_PRICE).classification is (
        DealClassification.EXCEPTIONAL_DEAL
    )


def test_history_below_minimum_does_not_classify_without_list_price() -> None:
    decision = detect_deal(
        make_observation(price=Decimal("10")),
        history_at_prices("100", "100"),
    )

    assert decision.is_valid is True
    assert decision.classification is DealClassification.NONE
    assert decision.should_alert is False


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
