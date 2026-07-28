import pytest

from bot_ofertas.crawling.vtex import conditional_vtex_price_flags
from bot_ofertas.detection import (
    COMMERCIAL_CONDITION_SIGNATURE_PREFIX,
    commercial_condition_signatures,
)


def _signature(flags: list[str]) -> str:
    signatures = commercial_condition_signatures(flags)
    assert len(signatures) == 1
    signature = signatures[0]
    assert len(signature) == 64
    assert set(signature) <= set("0123456789abcdef")
    assert flags[-1] == f"{COMMERCIAL_CONDITION_SIGNATURE_PREFIX}{signature}"
    return signature


@pytest.mark.parametrize(
    ("offer", "expected_flag"),
    [
        (
            {
                "Teasers": [
                    {
                        "<Conditions>k__BackingField": {
                            "<Parameters>k__BackingField": [
                                {
                                    "<Name>k__BackingField": "PaymentMethodId",
                                    "<Value>k__BackingField": "205",
                                }
                            ]
                        }
                    }
                ]
            },
            "payment_method_price",
        ),
        (
            {"PromotionTeasers": [{"name": "Precio exclusivo de membresía"}]},
            "membership_price",
        ),
        (
            {"promotionTeasers": [{"name": "Aplica el cupón VERANO"}]},
            "coupon_price",
        ),
        (
            {"teasers": [{"name": "Precio desde 3 unidades"}]},
            "minimum_quantity_price",
        ),
    ],
)
def test_conditional_flags_classify_vtex_teaser_evidence(
    offer: dict,
    expected_flag: str,
) -> None:
    flags = conditional_vtex_price_flags({}, {}, {}, offer)

    assert flags[:-1] == [expected_flag, "conditional_promotion_price"]
    _signature(flags)


def test_conditional_flags_inspect_only_relevant_product_and_item_metadata() -> None:
    product = {
        "productName": "Tarjeta de memoria de 128 GB",
        "Promociones": ["Usa el cupón AHORRA20"],
        "Precio Tarjeta": ["S/ 49.90"],
    }
    item = {
        "Membresía": ["Precio para socios"],
        "Cantidad mínima": [3],
    }

    flags = conditional_vtex_price_flags(product, item, {}, {})

    assert flags[:-1] == [
        "payment_method_price",
        "membership_price",
        "coupon_price",
        "minimum_quantity_price",
        "conditional_promotion_price",
    ]
    _signature(flags)


def test_installments_alone_are_not_treated_as_a_conditioned_cash_price() -> None:
    offer = {
        "Installments": [
            {
                "NumberOfInstallments": 12,
                "Value": 10,
                "PaymentMethodId": "205",
                "PaymentSystemName": "Tarjeta Oh",
            }
        ]
    }

    assert conditional_vtex_price_flags({}, {}, {}, offer) == []


def test_unknown_non_empty_teaser_is_kept_as_generic_conditional_evidence() -> None:
    offer = {
        "PromotionTeasers": [
            {
                "name": "Beneficio especial",
                "conditions": {"parameters": []},
            }
        ]
    }

    flags = conditional_vtex_price_flags({}, {}, {}, offer)

    assert flags[:-1] == ["conditional_promotion_price"]
    _signature(flags)


def test_empty_teaser_and_unrelated_text_do_not_create_flags() -> None:
    product = {
        "productName": "Tarjeta de memoria de 128 GB",
        "description": "Compatible con membresías digitales",
    }
    offer = {"Teasers": [], "PromotionTeasers": None}

    assert conditional_vtex_price_flags(product, {}, {}, offer) == []


def test_commercial_condition_signature_is_canonical_and_uses_only_relevant_evidence() -> None:
    first = {
        "Teasers": [
            {
                "<Conditions>k__BackingField": {
                    "<Parameters>k__BackingField": [
                        {
                            "<Name>k__BackingField": "PaymentMethodId",
                            "<Value>k__BackingField": "205",
                        }
                    ]
                },
                "name": "Precio con Tarjeta Oh",
            }
        ],
        "Installments": [{"PaymentMethodId": "999", "Value": 1}],
        "unrelated": "contenido ignorado",
    }
    same_content_reordered = {
        "unrelated": "otro contenido ignorado",
        "installments": [{"PaymentMethodId": "111", "Value": 500}],
        "promotionTeasers": [
            {
                "NAME": "  precio CON tarjeta OH ",
                "conditions": {
                    "parameters": [
                        {
                            "value": "205",
                            "name": "paymentMethodId",
                        }
                    ]
                },
            }
        ],
    }

    first_signature = _signature(conditional_vtex_price_flags({}, {}, {}, first))
    second_signature = _signature(
        conditional_vtex_price_flags(
            {"productName": "Producto distinto pero irrelevante"},
            {},
            {},
            same_content_reordered,
        )
    )

    assert first_signature == second_signature


@pytest.mark.parametrize(
    ("first_offer", "second_offer"),
    [
        (
            {
                "Teasers": [
                    {
                        "name": "Precio con tarjeta",
                        "conditions": {"parameters": [{"name": "PaymentMethodId", "value": "205"}]},
                    }
                ]
            },
            {
                "Teasers": [
                    {
                        "name": "Precio con tarjeta",
                        "conditions": {"parameters": [{"name": "PaymentMethodId", "value": "206"}]},
                    }
                ]
            },
        ),
        (
            {"Teasers": [{"name": "Aplica el cupón VERANO"}]},
            {"Teasers": [{"name": "Aplica el cupón INVIERNO"}]},
        ),
        (
            {"Teasers": [{"name": "Precio desde 3 unidades"}]},
            {"Teasers": [{"name": "Precio desde 4 unidades"}]},
        ),
    ],
)
def test_commercial_condition_signature_changes_with_exact_condition_content(
    first_offer: dict,
    second_offer: dict,
) -> None:
    first = _signature(conditional_vtex_price_flags({}, {}, {}, first_offer))
    second = _signature(conditional_vtex_price_flags({}, {}, {}, second_offer))

    assert first != second
