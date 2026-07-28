"""Telegram delivery channel using the official HTTPS Bot API."""

from __future__ import annotations

import html
import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from bot_ofertas.notifications.base import (
    NotificationResult,
    NotificationStatus,
    OfferNotification,
)

_TELEGRAM_API_ROOT = "https://api.telegram.org"
_MAX_MESSAGE_LENGTH = 4096


class TelegramTransport(Protocol):
    """Minimal transport seam that keeps network access out of unit tests."""

    def post_json(
        self,
        *,
        url: str,
        payload: Mapping[str, object],
        timeout: float,
    ) -> Mapping[str, Any]:
        """POST JSON and return the decoded provider response."""


@dataclass(frozen=True, slots=True)
class TelegramTransportError(Exception):
    """Sanitized transport failure that never contains the request URL."""

    category: str
    status_code: int | None = None
    retryable: bool = True
    retry_after_seconds: int | None = None


class UrllibTelegramTransport:
    """Standard-library JSON transport for Telegram."""

    def post_json(
        self,
        *,
        url: str,
        payload: Mapping[str, object],
        timeout: float,
    ) -> Mapping[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            url,
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": "bot-ofertas/0.1",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310
                decoded = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            retry_after = _positive_integer(
                error.headers.get("Retry-After") if error.headers is not None else None
            )
            if retry_after is None:
                try:
                    error_payload = json.loads(error.read().decode("utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    error_payload = None
                if isinstance(error_payload, Mapping):
                    parameters = error_payload.get("parameters")
                    if isinstance(parameters, Mapping):
                        retry_after = _positive_integer(
                            parameters.get("retry_after")
                        )
            retryable = error.code == 429 or error.code >= 500
            raise TelegramTransportError(
                "http_error",
                error.code,
                retryable=retryable,
                retry_after_seconds=retry_after,
            ) from None
        except (URLError, TimeoutError):
            raise TelegramTransportError("network_error") from None
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise TelegramTransportError("invalid_response") from None

        if not isinstance(decoded, dict):
            raise TelegramTransportError("invalid_response")
        return decoded


def _format_money(value: Decimal, currency: str) -> str:
    prefix = "S/" if currency == "PEN" else currency
    return f"{prefix} {value:,.2f}"


def _classification_heading(classification: str) -> str:
    normalized = classification.strip().lower().replace("-", "_").replace(" ", "_")
    headings = {
        "offer": "🏷️ Oferta detectada",
        "good_deal": "🏷️ Buena oferta",
        "great_deal": "🔥 Descuento imperdible",
        "exceptional_deal": "🔥 Descuento imperdible",
        "irresistible": "🔥 Descuento imperdible",
        "price_error": "🚨 Posible error de precio",
        "possible_price_error": "🚨 Posible error de precio",
    }
    return headings.get(normalized, f"🔔 {classification.replace('_', ' ').title()}")


def _positive_integer(value: object) -> int | None:
    try:
        normalized = int(str(value))
    except (TypeError, ValueError):
        return None
    return normalized if normalized > 0 else None


def _escaped_bounded(value: str, limit: int, *, quote: bool = True) -> str:
    """Escape text without ever truncating inside an HTML entity."""

    pieces: list[str] = []
    used = 0
    for character in value:
        escaped = html.escape(character, quote=quote)
        if used + len(escaped) > limit - 1:
            pieces.append("…")
            break
        pieces.append(escaped)
        used += len(escaped)
    return "".join(pieces)


def render_telegram_message(notification: OfferNotification) -> str:
    """Render a bounded, HTML-escaped Telegram message."""

    heading = _escaped_bounded(
        _classification_heading(notification.classification),
        120,
    )
    product = _escaped_bounded(notification.product_name, 600)
    reason = _escaped_bounded(notification.reason, 1_000)
    price = _escaped_bounded(
        _format_money(notification.current_price, notification.currency),
        100,
    )
    label = _escaped_bounded(notification.comparison_label, 150)
    url = _escaped_bounded(notification.product_url, 900)

    if notification.comparison_price is not None:
        previous = _escaped_bounded(
            _format_money(notification.comparison_price, notification.currency),
            100,
        )
        comparison = f"{previous} → {price}"
    else:
        comparison = "Sin precio comparable disponible"

    if notification.discount_percent is not None:
        comparison += f" ({notification.discount_percent:.2f}% menos)"

    lines = [
        f"<b>{heading}</b>",
        f"<b>Producto:</b> {product}",
    ]
    if notification.store_name is not None:
        lines.append(
            f"<b>Tienda:</b> {_escaped_bounded(notification.store_name, 250)}"
        )
    lines.extend(
        [
            f"<b>Precio actual:</b> {price}",
            f"<b>{label}:</b> {comparison}",
            f"<b>Razón:</b> {reason}",
            f'<a href="{url}">Ver producto</a>',
        ]
    )
    message = "\n".join(lines)
    if len(message) > _MAX_MESSAGE_LENGTH:  # pragma: no cover - budgets above prevent it
        raise ValueError("rendered Telegram message exceeds the provider limit")
    return message


class TelegramNotifier:
    """Synchronous and failure-safe Telegram notification channel."""

    channel_name = "telegram"

    def __init__(
        self,
        *,
        token: str | None,
        chat_id: str | int | None,
        enabled: bool = True,
        timeout_seconds: float = 10.0,
        transport: TelegramTransport | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._token = token.strip() if token else None
        self._chat_id = str(chat_id).strip() if chat_id is not None else None
        self._explicitly_enabled = enabled
        self._timeout_seconds = timeout_seconds
        self._transport = transport or UrllibTelegramTransport()

    @property
    def configured(self) -> bool:
        return bool(self._token and self._chat_id)

    @property
    def enabled(self) -> bool:
        return self._explicitly_enabled and self.configured

    @property
    def disabled_reason(self) -> str | None:
        if not self._explicitly_enabled:
            return "Telegram notifications are disabled"
        if not self.configured:
            return "Telegram credentials are not configured"
        return None

    def send(self, notification: OfferNotification) -> NotificationResult:
        if not isinstance(notification, OfferNotification):
            raise TypeError("notification must be an OfferNotification")
        if not self.enabled:
            return NotificationResult(
                channel=self.channel_name,
                status=NotificationStatus.DISABLED,
                detail=self.disabled_reason,
            )

        # These values are guaranteed by `self.enabled`; locals help type checkers and
        # keep all secret handling in one small scope.
        token = self._token
        chat_id = self._chat_id
        assert token is not None
        assert chat_id is not None

        endpoint = f"{_TELEGRAM_API_ROOT}/bot{token}/sendMessage"
        payload: dict[str, object] = {
            "chat_id": chat_id,
            "text": render_telegram_message(notification),
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            response = self._transport.post_json(
                url=endpoint,
                payload=payload,
                timeout=self._timeout_seconds,
            )
        except TelegramTransportError as error:
            detail = f"Telegram transport failed ({error.category})"
            if error.status_code is not None:
                detail += f" with HTTP {error.status_code}"
            return NotificationResult(
                channel=self.channel_name,
                status=NotificationStatus.FAILED,
                detail=detail,
                retryable=error.retryable,
                retry_after_seconds=error.retry_after_seconds,
            )
        except Exception:
            # Third-party injected transports may raise arbitrary exceptions. Their
            # messages are deliberately not exposed because the endpoint contains a token.
            return NotificationResult(
                channel=self.channel_name,
                status=NotificationStatus.FAILED,
                detail="Telegram delivery failed unexpectedly",
                retryable=True,
            )

        if response.get("ok") is not True:
            raw_error_code = response.get("error_code")
            error_code = (
                raw_error_code
                if isinstance(raw_error_code, int)
                and not isinstance(raw_error_code, bool)
                else None
            )
            parameters = response.get("parameters")
            retry_after = (
                _positive_integer(parameters.get("retry_after"))
                if isinstance(parameters, Mapping)
                else None
            )
            return NotificationResult(
                channel=self.channel_name,
                status=NotificationStatus.FAILED,
                detail="Telegram API rejected the message",
                retryable=(
                    error_code is None
                    or error_code == 429
                    or error_code >= 500
                ),
                retry_after_seconds=retry_after,
            )

        result = response.get("result")
        message_id: str | None = None
        if isinstance(result, Mapping) and result.get("message_id") is not None:
            message_id = str(result["message_id"])
        return NotificationResult(
            channel=self.channel_name,
            status=NotificationStatus.SENT,
            message_id=message_id,
        )


__all__ = [
    "TelegramNotifier",
    "TelegramTransport",
    "TelegramTransportError",
    "UrllibTelegramTransport",
    "render_telegram_message",
]
