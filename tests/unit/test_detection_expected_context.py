from datetime import UTC, datetime
from decimal import Decimal

import pytest

from bot_ofertas.detection import (
    ExpectedProductContext,
    RejectionReason,
    detect_deal,
)
from bot_ofertas.domain import Availability, PriceObservation, ProductCondition


def _observation(**overrides: object) -> PriceObservation:
    values: dict[str, object] = {
        "store_slug": "coolbox",
        "source_url": "https://www.coolbox.pe/notebook-acme-x14/p",
        "external_product_id": "product-x14",
        "sku": "sku-x14-16-negro",
        "seller_id": "1",
        "seller_name": "Coolbox",
        "title": "Notebook Ácme Profesional X14-2026 16 GB",
        "brand": "Ácme",
        "model": "X14-2026",
        "variant": {"Memória": "16 GB", "Color": "Negro"},
        "condition": ProductCondition.NEW,
        "currency": "PEN",
        "price": Decimal("40"),
        "list_price": Decimal("100"),
        "availability": Availability.IN_STOCK,
        "is_marketplace": False,
        "observed_at": datetime(2026, 7, 27, 16, tzinfo=UTC),
        "extractor_version": "expected-context-test",
        "source_payload_hash": "e" * 64,
    }
    values.update(overrides)
    return PriceObservation(**values)  # type: ignore[arg-type]


def test_expected_brand_model_and_variant_normalize_case_accents_and_punctuation() -> None:
    decision = detect_deal(
        _observation(),
        expected=ExpectedProductContext(
            brand="acme",
            model="x14 2026",
            variant={"memoria": "16 gb", "color": "negro"},
            expected_is_accessory=False,
        ),
    )

    assert decision.rejection_reasons == ()
    assert decision.should_alert is True


@pytest.mark.parametrize(
    "expected",
    [
        ExpectedProductContext(brand="Otra Marca"),
        ExpectedProductContext(model="X15-2026"),
    ],
)
def test_wrong_expected_brand_or_model_rejects_product(
    expected: ExpectedProductContext,
) -> None:
    decision = detect_deal(_observation(), expected=expected)

    assert decision.rejection_reasons == (
        RejectionReason.EXPECTED_PRODUCT_MISMATCH,
    )
    assert decision.should_alert is False


def test_expected_variant_is_exact_and_rejects_a_cheaper_different_variant() -> None:
    decision = detect_deal(
        _observation(variant={"Memoria": "8 GB", "Color": "Negro"}),
        expected=ExpectedProductContext(
            variant={"Memoria": "16 GB", "Color": "Negro"},
        ),
    )

    assert decision.rejection_reasons == (
        RejectionReason.EXPECTED_VARIANT_MISMATCH,
    )


@pytest.mark.parametrize(
    ("title", "expected_is_accessory", "rejected"),
    [
        ("Funda para Notebook Acme X14", False, True),
        ("Notebook Acme X14 16 GB", True, False),
        ("Funda para Notebook Acme X14", True, False),
        ("Notebook Acme X14 16 GB", False, False),
    ],
)
def test_accessory_confirmation_overrides_the_conservative_title_heuristic(
    title: str,
    expected_is_accessory: bool,
    rejected: bool,
) -> None:
    decision = detect_deal(
        _observation(title=title),
        expected=ExpectedProductContext(
            expected_is_accessory=expected_is_accessory,
        ),
    )

    assert (
        RejectionReason.ACCESSORY_MISMATCH in decision.rejection_reasons
    ) is rejected


def test_structured_model_must_match_exactly_even_if_title_contains_expected_text() -> None:
    decision = detect_deal(
        _observation(
            model="iPhone 15 Pro",
            title="Apple iPhone 15 Pro con iPhone 15 en la descripción",
        ),
        expected=ExpectedProductContext(model="iPhone 15"),
    )

    assert decision.rejection_reasons == (
        RejectionReason.EXPECTED_PRODUCT_MISMATCH,
    )
