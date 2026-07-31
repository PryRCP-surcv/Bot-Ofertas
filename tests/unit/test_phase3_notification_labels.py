from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest

from bot_ofertas.services.notifications import _conditions, _notification, _reason
from bot_ofertas.storage.notifications import (
    NotificationClaim,
    _comparison,
    _condition_flags,
)

_SIGNAL_LABELS = (
    ("previous_price", "caída frente al precio anterior", "Precio anterior"),
    ("median_7d", "caída frente a la mediana de 7 días", "Mediana de 7 días"),
    ("median_30d", "caída frente a la mediana de 30 días", "Mediana de 30 días"),
    (
        "historical_median",
        "caída frente a la mediana de 90 días",
        "Mediana de 90 días",
    ),
    (
        "equivalent_median",
        "caída frente a productos equivalentes",
        "Mediana de productos equivalentes",
    ),
    ("historical_minimum", "nuevo mínimo histórico", "Mínimo histórico"),
    ("list_price", "descuento frente al precio de lista", "Precio de lista"),
)


@pytest.mark.parametrize(
    ("signal_name", "reason_label", "_comparison_label"),
    _SIGNAL_LABELS,
)
def test_phase3_reason_codes_have_human_readable_labels(
    signal_name: str,
    reason_label: str,
    _comparison_label: str,
) -> None:
    assert _reason((f"{signal_name}:good_deal",)) == reason_label


@pytest.mark.parametrize(
    ("signal_name", "_reason_label", "comparison_label"),
    _SIGNAL_LABELS,
)
def test_phase3_comparison_signals_have_human_readable_labels(
    signal_name: str,
    _reason_label: str,
    comparison_label: str,
) -> None:
    detection = SimpleNamespace(
        reference_price=Decimal("100"),
        metrics={
            "primary_signal_kind": signal_name,
            "signals": {
                signal_name: {
                    "reference_price": "100",
                    "discount_percent": "35.5",
                }
            },
        },
    )

    assert _comparison(detection) == (comparison_label, Decimal("35.5"))


def test_notification_claim_preserves_phase3_confidence_and_confirmations() -> None:
    claim = NotificationClaim(
        delivery_id=10,
        lease_token=UUID("11111111-1111-4111-8111-111111111111"),
        detection_id=20,
        classification="exceptional_deal",
        product_name="Laptop de prueba",
        current_price=Decimal("1999"),
        currency="PEN",
        reason_codes=("median_30d:exceptional_deal", "historical_minimum:good_deal"),
        product_url="https://tienda.example/producto",
        comparison_price=Decimal("2999"),
        discount_percent=Decimal("33.34"),
        comparison_label="Mediana de 30 días",
        store_slug="tienda",
        confidence_score=80,
        confirmation_count=2,
        condition_flags=(
            "payment_method_price",
            "membership_price",
            "coupon_price",
            "minimum_quantity_price",
            "conditional_promotion_price",
            "installment_only_price",
        ),
    )

    notification = _notification(claim)

    assert notification.confidence_score == 80
    assert notification.confirmation_count == 2
    assert notification.comparison_label == "Mediana de 30 días"
    assert "caída frente a la mediana de 30 días" in notification.reason
    assert "nuevo mínimo histórico" in notification.reason
    assert "Referencia interna #20" in notification.reason
    assert notification.conditions == (
        "precio condicionado a tarjeta o medio de pago",
        "precio exclusivo para miembros o socios",
        "requiere un cupón",
        "requiere una cantidad mínima de compra",
    )


def test_generic_condition_is_used_only_without_a_more_specific_flag() -> None:
    assert _conditions(("conditional_promotion_price",)) == (
        "promoción con condiciones adicionales",
    )
    assert _conditions(("conditional_promotion_price", "coupon_price")) == ("requiere un cupón",)
    assert (
        _conditions(
            (
                "installment_only_price",
                "available_quantity_sentinel",
                "non_positive_list_price",
                f"commercial_condition_signature:{'a' * 64}",
            )
        )
        == ()
    )


def test_delivery_location_reminder_is_rendered_without_hiding_the_offer() -> None:
    assert _conditions(("delivery_location_confirmation",)) == (
        "confirma disponibilidad y delivery para tu distrito de Lima",
    )


@pytest.mark.parametrize(
    ("aliases", "expected_label"),
    [
        (
            (
                "conditional_card_price",
                "conditional_payment_method_price",
                "payment_method_price",
                "card_only_price",
                "tarjeta_only_price",
            ),
            "precio condicionado a tarjeta o medio de pago",
        ),
        (
            (
                "conditional_membership_price",
                "membership_price",
                "membership_only_price",
            ),
            "precio exclusivo para miembros o socios",
        ),
        (
            (
                "conditional_coupon_price",
                "coupon_price",
                "coupon_only_price",
            ),
            "requiere un cupón",
        ),
        (
            (
                "conditional_quantity_price",
                "minimum_quantity_price",
                "quantity_tier_price",
            ),
            "requiere una cantidad mínima de compra",
        ),
    ],
)
def test_condition_aliases_are_deduplicated_by_commercial_family(
    aliases: tuple[str, ...],
    expected_label: str,
) -> None:
    assert _conditions((*aliases, "conditional_promotion_price")) == (expected_label,)


def test_claim_condition_flags_are_normalized_from_observation_quality_flags() -> None:
    assert _condition_flags(
        [
            " Payment_Method_Price ",
            "payment_method_price",
            42,
            "",
            "installment_only_price",
        ]
    ) == ("payment_method_price", "installment_only_price")
