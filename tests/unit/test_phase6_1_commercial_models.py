from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.orm import configure_mappers

from bot_ofertas.api.schemas import PaymentCreate, SubscriberCreate
from bot_ofertas.storage.models import (
    Base,
    BetaLaunchChecklistItem,
    BetaPayment,
    BetaSubscriber,
)


def _constraint_names(model: type) -> set[str]:
    return {
        constraint.name
        for constraint in model.__table__.constraints
        if isinstance(constraint, (CheckConstraint, UniqueConstraint))
        and constraint.name is not None
    }


def test_phase6_models_register_commercial_tables_and_guards() -> None:
    configure_mappers()

    assert {
        "beta_subscribers",
        "beta_payments",
        "beta_launch_checklist_items",
    }.issubset(Base.metadata.tables)
    assert "uq_beta_subscribers_telegram_username" in _constraint_names(
        BetaSubscriber
    )
    assert "uq_beta_payments_idempotency_hash" in _constraint_names(
        BetaPayment
    )
    assert "ck_beta_launch_checklist_completion_shape" in _constraint_names(
        BetaLaunchChecklistItem
    )
    assert BetaPayment.__table__.c.currency.nullable is False
    assert BetaSubscriber.__table__.c.version.nullable is False


def test_subscriber_contract_normalizes_telegram_and_contact_data() -> None:
    payload = SubscriberCreate(
        full_name="  Ada   Pérez  ",
        telegram_username="@Ada_2026",
        email=" ADA@EXAMPLE.COM ",
        phone=" 999 111 222 ",
    )

    assert payload.full_name == "Ada Pérez"
    assert payload.telegram_username == "ada_2026"
    assert payload.email == "ada@example.com"
    assert payload.phone == "999 111 222"


@pytest.mark.parametrize(
    "username",
    ["abc", "9usuario", "usuario-con-guion", "@@usuario"],
)
def test_subscriber_contract_rejects_unsafe_telegram_usernames(
    username: str,
) -> None:
    with pytest.raises(ValidationError):
        SubscriberCreate(
            full_name="Persona beta",
            telegram_username=username,
        )


def test_payment_contract_is_pen_sized_and_bounded() -> None:
    payload = PaymentCreate(
        amount=Decimal("12.50"),
        method="yape",
        renewal_days=30,
    )

    assert payload.amount == Decimal("12.50")
    assert payload.renewal_days == 30

    with pytest.raises(ValidationError):
        PaymentCreate(
            amount=Decimal("0"),
            method="yape",
            renewal_days=30,
        )
