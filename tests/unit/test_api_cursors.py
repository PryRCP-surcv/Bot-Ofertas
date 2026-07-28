from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from bot_ofertas.api.cursors import (
    CursorError,
    cursor_scope,
    decode_cursor,
    encode_cursor,
)
from bot_ofertas.api.service import _discount_percent


def _token(payload: object) -> str:
    serialized = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(serialized).decode().rstrip("=")


def test_cursor_round_trip_normalizes_timestamp_to_utc() -> None:
    scope = cursor_scope("offers", store_slug="coolbox", classification=None)
    timestamp = datetime.fromisoformat("2026-07-28T11:30:45.123456-05:00")

    encoded = encode_cursor(
        scope=scope,
        timestamp=timestamp,
        key="42",
    )
    decoded = decode_cursor(encoded, scope=scope)

    assert decoded.timestamp == datetime(
        2026,
        7,
        28,
        16,
        30,
        45,
        123456,
        tzinfo=UTC,
    )
    assert decoded.key == "42"
    assert "=" not in encoded


def test_cursor_is_bound_to_normalized_filters() -> None:
    coolbox_scope = cursor_scope("products", store_slug="coolbox", active=True)
    promart_scope = cursor_scope("products", store_slug="promart", active=True)
    encoded = encode_cursor(
        scope=coolbox_scope,
        timestamp=datetime.now(UTC),
        key="8c5f22ea-f928-4fd1-94d3-93b4bdd0cdfb",
    )

    with pytest.raises(CursorError, match="current filters"):
        decode_cursor(encoded, scope=promart_scope)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "not+urlsafe",
        _token({"v": 1, "s": "scope", "t": "2026-01-01T00:00:00+00:00"}),
        _token({"v": 2, "s": "scope", "t": "2026-01-01T00:00:00+00:00", "k": "1"}),
        _token({"v": 1, "s": "scope", "t": "2026-01-01T00:00:00", "k": "1"}),
    ],
)
def test_invalid_cursors_are_rejected(value: str) -> None:
    with pytest.raises(CursorError):
        decode_cursor(value, scope="scope")


def test_cursor_requires_timezone_aware_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        encode_cursor(
            scope="products:test",
            timestamp=datetime(2026, 7, 28),
            key="1",
        )


def test_scope_is_stable_regardless_of_filter_argument_order() -> None:
    first = cursor_scope("products", active=True, store_slug="coolbox")
    second = cursor_scope("products", store_slug="coolbox", active=True)

    assert first == second


def test_offer_discount_uses_primary_signal_matching_reference_price() -> None:
    detection = SimpleNamespace(
        reference_price=Decimal("100"),
        drop_from_previous_pct=Decimal("80"),
        metrics={
            "primary_signal_kind": "median_30d",
            "signals": {
                "previous_price": {
                    "reference_price": "500",
                    "discount_percent": "80",
                },
                "median_30d": {
                    "reference_price": "100",
                    "discount_percent": "20",
                },
            },
        },
    )

    assert _discount_percent(detection) == Decimal("20")


def test_offer_discount_rejects_primary_signal_for_another_reference() -> None:
    detection = SimpleNamespace(
        reference_price=Decimal("100"),
        metrics={
            "primary_signal_kind": "median_30d",
            "signals": {
                "median_30d": {
                    "reference_price": "101",
                    "discount_percent": "20",
                },
            },
        },
    )

    assert _discount_percent(detection) is None
