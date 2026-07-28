from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import pytest

from bot_ofertas.notifications import (
    NotificationChannel,
    NotificationStatus,
    OfferNotification,
    TelegramNotifier,
    TelegramTransportError,
    render_telegram_message,
)


def make_notification(**overrides: object) -> OfferNotification:
    values: dict[str, object] = {
        "classification": "price_error",
        "product_name": 'Audífonos <Pro> & "Case"',
        "current_price": Decimal("179"),
        "comparison_price": Decimal("499"),
        "discount_percent": Decimal("64.128"),
        "currency": "pen",
        "reason": "Precio 64% menor que la referencia & mínimo histórico.",
        "product_url": "https://www.coolbox.pe/producto?a=1&b=2",
        "store_name": "Coolbox & Perú",
    }
    values.update(overrides)
    return OfferNotification(**values)  # type: ignore[arg-type]


class RecordingTransport:
    def __init__(self, response: Mapping[str, Any] | None = None) -> None:
        self.response = response or {"ok": True, "result": {"message_id": 42}}
        self.calls: list[tuple[str, Mapping[str, object], float]] = []

    def post_json(
        self,
        *,
        url: str,
        payload: Mapping[str, object],
        timeout: float,
    ) -> Mapping[str, Any]:
        self.calls.append((url, payload, timeout))
        return self.response


def test_offer_notification_normalizes_values_and_rejects_float_money() -> None:
    notification = make_notification()

    assert notification.currency == "PEN"
    assert notification.classification == "price_error"
    assert notification.current_price == Decimal("179")

    with pytest.raises(TypeError, match="floats are not accepted"):
        make_notification(current_price=179.0)


def test_rendered_message_explains_offer_and_escapes_dynamic_html() -> None:
    message = render_telegram_message(make_notification())

    assert "🚨 Posible error de precio" in message
    assert "Audífonos &lt;Pro&gt; &amp; &quot;Case&quot;" in message
    assert "S/ 179.00" in message
    assert "S/ 499.00 → S/ 179.00 (64.13% menos)" in message
    assert "mínimo histórico" in message
    assert "Coolbox &amp; Perú" in message
    assert 'href="https://www.coolbox.pe/producto?a=1&amp;b=2"' in message
    assert len(message) <= 4096


def test_send_uses_official_https_endpoint_and_expected_payload() -> None:
    transport = RecordingTransport()
    notifier = TelegramNotifier(
        token="123:secret-token",
        chat_id="-100123",
        timeout_seconds=3.5,
        transport=transport,
    )

    result = notifier.send(make_notification())

    assert isinstance(notifier, NotificationChannel)
    assert result.status is NotificationStatus.SENT
    assert result.sent is True
    assert result.message_id == "42"
    assert transport.calls == [
        (
            "https://api.telegram.org/bot123:secret-token/sendMessage",
            {
                "chat_id": "-100123",
                "text": render_telegram_message(make_notification()),
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            3.5,
        )
    ]


@pytest.mark.parametrize(
    ("token", "chat_id", "enabled", "expected_detail"),
    [
        ("token", "chat", False, "Telegram notifications are disabled"),
        (None, "chat", True, "Telegram credentials are not configured"),
        ("token", None, True, "Telegram credentials are not configured"),
    ],
)
def test_disabled_or_unconfigured_notifier_does_not_use_transport(
    token: str | None,
    chat_id: str | None,
    enabled: bool,
    expected_detail: str,
) -> None:
    transport = RecordingTransport()
    notifier = TelegramNotifier(
        token=token,
        chat_id=chat_id,
        enabled=enabled,
        transport=transport,
    )

    result = notifier.send(make_notification())

    assert notifier.enabled is False
    assert result.status is NotificationStatus.DISABLED
    assert result.detail == expected_detail
    assert transport.calls == []


class ExplodingTransport:
    def post_json(
        self,
        *,
        url: str,
        payload: Mapping[str, object],
        timeout: float,
    ) -> Mapping[str, Any]:
        raise RuntimeError(f"failed URL was {url}")


def test_arbitrary_transport_error_never_leaks_token() -> None:
    secret = "123:do-not-leak"
    notifier = TelegramNotifier(
        token=secret,
        chat_id="chat",
        transport=ExplodingTransport(),
    )

    result = notifier.send(make_notification())

    assert result.status is NotificationStatus.FAILED
    assert secret not in (result.detail or "")
    assert result.detail == "Telegram delivery failed unexpectedly"


class SafeFailingTransport:
    def post_json(
        self,
        *,
        url: str,
        payload: Mapping[str, object],
        timeout: float,
    ) -> Mapping[str, Any]:
        raise TelegramTransportError("http_error", 429)


def test_sanitized_transport_error_preserves_useful_status_without_secret() -> None:
    notifier = TelegramNotifier(
        token="123:secret",
        chat_id="chat",
        transport=SafeFailingTransport(),
    )

    result = notifier.send(make_notification())

    assert result.status is NotificationStatus.FAILED
    assert result.detail == "Telegram transport failed (http_error) with HTTP 429"


def test_provider_rejection_is_failure_without_exposing_provider_description() -> None:
    transport = RecordingTransport(
        {
            "ok": False,
            "description": "request accidentally includes 123:secret-token",
        }
    )
    notifier = TelegramNotifier(
        token="123:secret-token",
        chat_id="chat",
        transport=transport,
    )

    result = notifier.send(make_notification())

    assert result.status is NotificationStatus.FAILED
    assert result.detail == "Telegram API rejected the message"


def test_long_html_message_is_bounded_without_cutting_tags_or_entities() -> None:
    notification = make_notification(
        product_name="<Producto & seguro>" * 500,
        reason="Razón & validación <auditada> " * 500,
        product_url="https://www.coolbox.pe/producto?" + "a=1&" * 2_000,
        store_name="Tienda & Perú " * 200,
    )

    message = render_telegram_message(notification)

    assert len(message) <= 4096
    assert message.endswith("</a>")
    assert "&amp…" not in message
    assert "&lt…" not in message
    assert "&quot…" not in message


def test_provider_rate_limit_exposes_safe_retry_after_policy() -> None:
    notifier = TelegramNotifier(
        token="123:secret",
        chat_id="chat",
        transport=RecordingTransport(
            {
                "ok": False,
                "error_code": 429,
                "description": "secret provider detail",
                "parameters": {"retry_after": 45},
            }
        ),
    )

    result = notifier.send(make_notification())

    assert result.status is NotificationStatus.FAILED
    assert result.retryable is True
    assert result.retry_after_seconds == 45
    assert result.detail == "Telegram API rejected the message"


def test_provider_bad_request_is_not_retried() -> None:
    notifier = TelegramNotifier(
        token="123:secret",
        chat_id="chat",
        transport=RecordingTransport({"ok": False, "error_code": 400}),
    )

    result = notifier.send(make_notification())

    assert result.status is NotificationStatus.FAILED
    assert result.retryable is False
