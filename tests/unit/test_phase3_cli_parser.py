from uuid import UUID

import pytest

from bot_ofertas.cli import _build_parser, _quality_flag_labels

_GROUP_ID = UUID("11111111-1111-4111-8111-111111111111")
_PRODUCT_ID = UUID("22222222-2222-4222-8222-222222222222")


def test_config_show_parser_selects_phase3_configuration_command() -> None:
    args = _build_parser().parse_args(["config", "show"])

    assert args.command == "config"
    assert args.config_command == "show"


def test_product_variant_parser_accepts_repeated_exact_variant_pairs() -> None:
    args = _build_parser().parse_args(
        [
            "product",
            "variant",
            str(_PRODUCT_ID),
            "--variant",
            "Color=Negro",
            "--variant",
            "Memoria=16 GB",
        ]
    )

    assert args.command == "product"
    assert args.product_command == "variant"
    assert args.product_id == _PRODUCT_ID
    assert args.variant == [("Color", "Negro"), ("Memoria", "16 GB")]


def test_equivalence_create_parser_collects_identity_and_variant() -> None:
    args = _build_parser().parse_args(
        [
            "equivalence",
            "create",
            "--name",
            "iPhone 16 128 GB Negro",
            "--brand",
            "Apple",
            "--model",
            "iPhone 16",
            "--variant",
            "Color=Negro",
            "--variant",
            "Capacidad=128 GB",
        ]
    )

    assert args.command == "equivalence"
    assert args.equivalence_command == "create"
    assert args.name == "iPhone 16 128 GB Negro"
    assert args.brand == "Apple"
    assert args.model == "iPhone 16"
    assert args.variant == [("Color", "Negro"), ("Capacidad", "128 GB")]


def test_equivalence_list_parser_selects_list_command() -> None:
    args = _build_parser().parse_args(["equivalence", "list"])

    assert args.command == "equivalence"
    assert args.equivalence_command == "list"


@pytest.mark.parametrize(
    "action",
    ["add-product", "remove-product"],
)
def test_equivalence_membership_parser_accepts_group_and_product_ids(
    action: str,
) -> None:
    args = _build_parser().parse_args(["equivalence", action, str(_GROUP_ID), str(_PRODUCT_ID)])

    assert args.command == "equivalence"
    assert args.equivalence_command == action
    assert args.group_id == _GROUP_ID
    assert args.product_id == _PRODUCT_ID


def test_confirmation_list_parser_accepts_bounded_limit() -> None:
    args = _build_parser().parse_args(["confirmation", "list", "--limit", "75"])

    assert args.command == "confirmation"
    assert args.confirmation_command == "list"
    assert args.limit == 75


def test_quality_flags_separate_useful_conditions_from_blocking_warnings() -> None:
    conditions, blocking = _quality_flag_labels(
        [
            "payment_method_price",
            "conditional_promotion_price",
            "coupon_price",
            f"commercial_condition_signature:{'a' * 64}",
            "ambiguous_oechsle_seller_identity",
        ]
    )

    assert conditions == (
        "requiere tarjeta o medio de pago específico",
        "requiere cupón o código promocional",
    )
    assert blocking == ("ambiguous_oechsle_seller_identity",)


def test_generic_condition_is_shown_when_no_specific_requirement_is_known() -> None:
    conditions, blocking = _quality_flag_labels(["conditional_promotion_price"])

    assert conditions == ("promoción con requisitos; revisar condiciones",)
    assert blocking == ()


@pytest.mark.parametrize(
    "argv",
    [
        ["product", "variant", str(_PRODUCT_ID), "--variant", "Color"],
        ["equivalence", "add-product", "not-a-uuid", str(_PRODUCT_ID)],
        ["confirmation", "list", "--limit", "0"],
    ],
)
def test_phase3_parser_rejects_malformed_values(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as error:
        _build_parser().parse_args(argv)

    assert error.value.code == 2
