from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from bot_ofertas.domain import (
    Availability,
    InstallmentOption,
    PriceObservation,
    ProductCondition,
)


def make_observation(**overrides: object) -> PriceObservation:
    values: dict[str, object] = {
        "store_slug": "coolbox",
        "source_url": "https://www.coolbox.pe/producto-demo/p",
        "external_product_id": "product-1",
        "product_reference": "REF-1",
        "sku": "sku-1",
        "sku_reference": "SKU-REF-1",
        "seller_id": "1",
        "seller_name": "Rash Peru S.R.L",
        "title": "Producto de prueba",
        "brand": "Marca",
        "model": "Modelo",
        "category_path": ["Tecnología", "Computación"],
        "variant": {"Color": "Negro"},
        "condition": ProductCondition.NEW,
        "currency": "pen",
        "price": Decimal("199.90"),
        "list_price": Decimal("249.90"),
        "availability": Availability.IN_STOCK,
        "available_quantity": 3,
        "is_marketplace": False,
        "installments": [
            {
                "count": 4,
                "amount": Decimal("49.975"),
                "currency": "PEN",
                "total": Decimal("199.90"),
                "interest_free": True,
                "payment_method": "Visa",
            }
        ],
        "observed_at": datetime(2026, 7, 26, 10, 0, tzinfo=timezone(timedelta(hours=-5))),
        "extractor_version": "test-v1",
        "source_payload_hash": "a" * 64,
        "quality_flags": ["flag-a", "flag-a"],
    }
    values.update(overrides)
    return PriceObservation(**values)  # type: ignore[arg-type]


def test_observation_normalizes_money_currency_time_and_flags() -> None:
    observation = make_observation()

    assert observation.price == Decimal("199.90")
    assert observation.currency == "PEN"
    assert observation.observed_at == datetime(2026, 7, 26, 15, 0, tzinfo=UTC)
    assert observation.quality_flags == ["flag-a"]
    assert observation.installments == [
        InstallmentOption(
            count=4,
            amount=Decimal("49.975"),
            currency="PEN",
            total=Decimal("199.90"),
            interest_free=True,
            payment_method="Visa",
        )
    ]


def test_installment_never_replaces_total_price() -> None:
    observation = make_observation(
        price=Decimal("199.90"),
        installments=[
            {
                "count": 12,
                "amount": Decimal("16.66"),
                "currency": "PEN",
            }
        ],
    )

    assert observation.price == Decimal("199.90")
    assert observation.installments[0].amount == Decimal("16.66")


def test_observation_rejects_float_money() -> None:
    with pytest.raises(TypeError, match="floats are not accepted"):
        make_observation(price=199.9)


def test_observation_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        make_observation(observed_at=datetime(2026, 7, 26, 10, 0))


def test_observation_rejects_invalid_payload_hash() -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        make_observation(source_payload_hash="not-a-hash")
