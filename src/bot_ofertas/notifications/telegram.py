"""Telegram delivery channel using the official HTTPS Bot API."""

from __future__ import annotations

import html
import json
import re
import secrets
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
from bot_ofertas.notifications.remote_image import (
    DownloadedImage,
    RemoteImageFetcher,
    SafeRemoteImageFetcher,
)

_TELEGRAM_API_ROOT = "https://api.telegram.org"
_MAX_MESSAGE_LENGTH = 4096
_MAX_CAPTION_LENGTH = 1024
_CONNECTOR_WORDS = frozenset(
    {
        "a",
        "al",
        "con",
        "de",
        "del",
        "e",
        "el",
        "en",
        "la",
        "las",
        "los",
        "o",
        "para",
        "por",
        "sin",
        "un",
        "una",
        "y",
    }
)
_STORE_DISPLAY_NAMES = {
    "casaideas": "Casaideas",
    "coolbox": "Coolbox",
    "curacao": "La Curacao",
    "efe": "EFE",
    "footloose": "Footloose",
    "lacuracao": "La Curacao",
    "oechsle": "Oechsle",
    "plazavea": "PlazaVea",
    "promart": "Promart",
    "topitop": "Topitop",
}


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

    def post_multipart(
        self,
        *,
        url: str,
        fields: Mapping[str, object],
        file_field: str,
        filename: str,
        content_type: str,
        content: bytes,
        timeout: float,
    ) -> Mapping[str, Any]:
        """POST one in-memory file and return the decoded provider response."""


@dataclass(frozen=True, slots=True)
class TelegramTransportError(Exception):
    """Sanitized transport failure that never contains the request URL."""

    category: str
    status_code: int | None = None
    retryable: bool = True
    retry_after_seconds: int | None = None


class UrllibTelegramTransport:
    """Standard-library JSON and multipart transport for Telegram."""

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
        return self._execute(request, timeout=timeout)

    def post_multipart(
        self,
        *,
        url: str,
        fields: Mapping[str, object],
        file_field: str,
        filename: str,
        content_type: str,
        content: bytes,
        timeout: float,
    ) -> Mapping[str, Any]:
        boundary = f"botofertas-{secrets.token_hex(16)}"
        body = _multipart_body(
            boundary=boundary,
            fields=fields,
            file_field=file_field,
            filename=filename,
            content_type=content_type,
            content=content,
        )
        request = Request(
            url,
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body)),
                "User-Agent": "bot-ofertas/0.1",
            },
            method="POST",
        )
        return self._execute(request, timeout=timeout)

    @staticmethod
    def _execute(request: Request, *, timeout: float) -> Mapping[str, Any]:
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
                        retry_after = _positive_integer(parameters.get("retry_after"))
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


def _multipart_body(
    *,
    boundary: str,
    fields: Mapping[str, object],
    file_field: str,
    filename: str,
    content_type: str,
    content: bytes,
) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9-]{1,70}", boundary):
        raise ValueError("multipart boundary is invalid")
    if not re.fullmatch(r"[A-Za-z0-9_]{1,70}", file_field):
        raise ValueError("multipart file field is invalid")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", filename):
        raise ValueError("multipart filename is invalid")
    chunks: list[bytes] = []
    marker = f"--{boundary}\r\n".encode()
    for name, value in fields.items():
        if not re.fullmatch(r"[A-Za-z0-9_]{1,70}", name):
            raise ValueError("multipart field name is invalid")
        rendered = (
            json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            if isinstance(value, (Mapping, list, tuple))
            else str(value)
        )
        chunks.extend(
            (
                marker,
                (
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                ).encode(),
                rendered.encode("utf-8"),
                b"\r\n",
            )
        )
    chunks.extend(
        (
            marker,
            (
                f'Content-Disposition: form-data; name="{file_field}"; '
                f'filename="{filename}"\r\n'
            ).encode(),
            f"Content-Type: {content_type}\r\n\r\n".encode(),
            content,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        )
    )
    return b"".join(chunks)


def _format_money(value: Decimal, currency: str) -> str:
    prefix = "S/" if currency == "PEN" else currency
    return f"{prefix} {value:,.2f}"


def _classification_heading(
    classification: str,
    discount_percent: Decimal | None,
) -> str:
    normalized = classification.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"great_deal", "exceptional_deal", "irresistible"}:
        if discount_percent is not None and discount_percent >= Decimal("50"):
            return "💥 Oferta excepcional"
        return "🔥 Oferta imperdible"
    headings = {
        "offer": "🏷️ Oferta detectada",
        "good_deal": "🏷️ Buena oferta",
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


def _display_store_name(value: str) -> str:
    normalized = " ".join(value.replace("_", " ").split())
    compact = normalized.casefold().replace(" ", "").replace("-", "")
    return _STORE_DISPLAY_NAMES.get(
        compact,
        " ".join(word[:1].upper() + word[1:] for word in normalized.split()),
    )


def _remove_internal_product_code(value: str) -> str:
    without_leading_code = re.sub(r"^\d{5,}\s+", "", value)
    without_trailing_code = re.sub(r"\s+\d{5,}$", "", without_leading_code)
    return re.sub(r"(?<=[^\W\d_])\d{5,}$", "", without_trailing_code)


def _display_product_name(value: str, store_name: str | None) -> str:
    """Apply conservative editorial casing without changing product identity."""

    normalized = " ".join(value.split())
    if store_name is not None:
        normalized_store = " ".join(store_name.replace("_", " ").split())
        store_pattern = re.compile(
            rf"^(?:{re.escape(normalized_store)}|"
            rf"{re.escape(normalized_store.replace(' ', ''))})\b[\s:—-]*",
            flags=re.IGNORECASE,
        )
        normalized = store_pattern.sub("", normalized, count=1)
    normalized = _remove_internal_product_code(normalized).strip(" -–—:")
    if not normalized:
        normalized = " ".join(value.split())

    words = normalized.split()
    displayed: list[str] = []
    for position, word in enumerate(words):
        if any(character.isupper() for character in word):
            displayed.append(word)
            continue
        letters = "".join(character for character in word if character.isalpha())
        has_digit = any(character.isdigit() for character in word)
        next_has_digit = (
            position + 1 < len(words)
            and any(character.isdigit() for character in words[position + 1])
        )
        if letters and len(letters) <= 3 and (has_digit or next_has_digit):
            displayed.append(word.upper())
        elif position == 0:
            displayed.append(word[:1].upper() + word[1:])
        elif word.casefold() in _CONNECTOR_WORDS:
            displayed.append(word.casefold())
        else:
            displayed.append(word[:1].upper() + word[1:])
    return " ".join(displayed)


def _discount_text(discount_percent: Decimal) -> str:
    normalized = discount_percent.quantize(Decimal("0.01"))
    visible = format(normalized, "f").rstrip("0").rstrip(".")
    return f"{visible}% de descuento"


def _comparison_line(notification: OfferNotification, price: str) -> str | None:
    if notification.comparison_price is None:
        return None
    previous = _escaped_bounded(
        _format_money(notification.comparison_price, notification.currency),
        100,
    )
    label = notification.comparison_label.strip().casefold()
    prefix = (
        "Antes"
        if label in {"precio anterior", "precio de lista"}
        else _escaped_bounded(notification.comparison_label, 150)
    )
    pieces = [f"<b>{prefix}:</b> <s>{previous}</s>"]
    if notification.discount_percent is not None:
        pieces.append(f"<b>{_discount_text(notification.discount_percent)}</b>")
    elif previous != price:
        pieces.append(f"Ahora {price}")
    return " · ".join(pieces)


def _variant_label(value: str) -> tuple[str, str]:
    normalized = value.strip().casefold()
    if normalized in {"size", "talla"}:
        return "📐", "Talla"
    if normalized == "tallas":
        return "📐", "Tallas"
    if normalized in {"color", "colour"}:
        return "🎨", "Color"
    return "🔹", value.strip().title()


def _display_variant_value(label: str, value: str) -> str:
    normalized = value.strip()
    if label in {"Talla", "Tallas"}:
        return normalized.upper()
    if label == "Color":
        return normalized[:1].upper() + normalized[1:]
    return normalized


def _variant_lines(summary: str, *, value_limit: int) -> list[str]:
    """Render controlled variant summaries with readable labels and no raw '='."""

    normalized = " ".join(summary.split())
    simple = re.fullmatch(r"(.+?)\s+disponibles:\s*(.+)", normalized, re.IGNORECASE)
    if simple is not None:
        emoji, label = _variant_label(simple.group(1))
        values = _escaped_bounded(
            _display_variant_value(label, simple.group(2)),
            value_limit,
        )
        return [f"{emoji} <b>{_escaped_bounded(label, 60)}:</b> {values}"]

    content = re.sub(r"^Disponibles:\s*", "", normalized, flags=re.IGNORECASE)
    combinations = [item.strip() for item in content.split(";") if item.strip()]
    rendered: list[str] = []
    for combination in combinations[:8]:
        parts: list[str] = []
        for item in combination.split(","):
            key, separator, value = item.partition("=")
            if not separator:
                key, separator, value = item.partition(":")
            if not separator:
                parts.append(_escaped_bounded(item.strip(), value_limit))
                continue
            _emoji, label = _variant_label(key)
            parts.append(
                f"<b>{_escaped_bounded(label, 60)}:</b> "
                f"{_escaped_bounded(_display_variant_value(label, value), value_limit)}"
            )
        rendered.append("• " + " · ".join(parts))
    if rendered:
        return ["🔹 <b>Variantes disponibles:</b>", *rendered]
    return [f"🔹 <b>Variantes:</b> {_escaped_bounded(normalized, value_limit)}"]


def _condition_lines(conditions: tuple[str, ...], *, limit: int) -> list[str]:
    rendered: list[str] = []
    for condition in conditions:
        normalized = condition.casefold()
        emoji = (
            "📍"
            if any(
                marker in normalized
                for marker in ("delivery", "distrito", "disponibilidad", "recojo")
            )
            else "⚠️"
        )
        rendered.append(f"{emoji} {_escaped_bounded(condition, limit)}")
    return rendered


def render_telegram_message(notification: OfferNotification) -> str:
    """Render a bounded, HTML-escaped Telegram message."""

    heading = _escaped_bounded(
        _classification_heading(
            notification.classification,
            notification.discount_percent,
        ),
        120,
    )
    product = _escaped_bounded(
        _display_product_name(notification.product_name, notification.store_name),
        600,
    )
    price = _escaped_bounded(
        _format_money(notification.current_price, notification.currency),
        100,
    )
    url = _escaped_bounded(notification.product_url, 900)

    lines = [
        f"<b>{heading}</b>",
        f"<b>{product}</b>",
    ]
    if notification.store_name is not None:
        store = _escaped_bounded(_display_store_name(notification.store_name), 250)
        lines.append(f"🏬 <b>Tienda:</b> {store}")
    lines.append(f"💰 <b>Precio:</b> {price}")
    comparison = _comparison_line(notification, price)
    if comparison is not None:
        lines.append(comparison)
    if notification.variant_summary is not None:
        lines.extend(_variant_lines(notification.variant_summary, value_limit=250))
    if notification.conditions:
        lines.extend(_condition_lines(notification.conditions, limit=400))
    if notification.confirmation_count is not None and notification.confirmation_count >= 2:
        lines.append("✅ Precio verificado")
    lines.append(f'<a href="{url}">Ver producto</a>')
    message = "\n".join(lines)
    if len(message) > _MAX_MESSAGE_LENGTH:  # pragma: no cover - budgets above prevent it
        raise ValueError("rendered Telegram message exceeds the provider limit")
    return message


def render_telegram_caption(notification: OfferNotification) -> str:
    """Render the compact explanation shown below a Telegram product photo."""

    heading = _escaped_bounded(
        _classification_heading(
            notification.classification,
            notification.discount_percent,
        ),
        80,
    )
    product = _escaped_bounded(
        _display_product_name(notification.product_name, notification.store_name),
        180,
    )
    price = _escaped_bounded(
        _format_money(notification.current_price, notification.currency),
        50,
    )

    lines = [
        f"<b>{heading}</b>",
        f"<b>{product}</b>",
    ]
    if notification.store_name is not None:
        store = _escaped_bounded(_display_store_name(notification.store_name), 60)
        lines.append(f"🏬 <b>Tienda:</b> {store}")
    lines.append(f"💰 <b>Precio:</b> {price}")
    comparison = _comparison_line(notification, price)
    if comparison is not None:
        lines.append(comparison)
    if notification.variant_summary is not None:
        lines.extend(_variant_lines(notification.variant_summary, value_limit=80))
    if notification.conditions:
        lines.extend(_condition_lines(notification.conditions, limit=100))
    if notification.confirmation_count is not None and notification.confirmation_count >= 2:
        lines.append("✅ Precio verificado")
    caption = "\n".join(lines)
    if len(caption) > _MAX_CAPTION_LENGTH:  # pragma: no cover - budgets above prevent it
        raise ValueError("rendered Telegram caption exceeds the provider limit")
    return caption


class TelegramNotifier:
    """Synchronous and failure-safe Telegram notification channel."""

    def __init__(
        self,
        *,
        token: str | None,
        chat_id: str | int | None,
        channel_name: str = "telegram",
        enabled: bool = True,
        timeout_seconds: float = 10.0,
        transport: TelegramTransport | None = None,
        image_fetcher: RemoteImageFetcher | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        normalized_channel = channel_name.strip().casefold()
        if not normalized_channel:
            raise ValueError("channel_name must not be empty")
        if len(normalized_channel) > 32:
            raise ValueError("channel_name must not exceed 32 characters")
        self.channel_name = normalized_channel
        self._token = token.strip() if token else None
        self._chat_id = str(chat_id).strip() if chat_id is not None else None
        self._explicitly_enabled = enabled
        self._timeout_seconds = timeout_seconds
        self._transport = transport or UrllibTelegramTransport()
        self._image_fetcher = image_fetcher or SafeRemoteImageFetcher()

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
        if notification.image_url is not None:
            result, bad_photo_request = self._send_payload(
                method="sendPhoto",
                payload={
                    "chat_id": self._chat_id or "",
                    "photo": notification.image_url,
                    "caption": render_telegram_caption(notification),
                    "parse_mode": "HTML",
                    "reply_markup": {
                        "inline_keyboard": [
                            [
                                {
                                    "text": "Ver producto",
                                    "url": notification.product_url,
                                }
                            ]
                        ]
                    },
                },
                delivery_method="photo_url",
            )
            if result.sent or not bad_photo_request:
                return result
            # Telegram returns HTTP/API 400 when it cannot fetch or decode a remote
            # photo. Download it once under strict limits and upload the in-memory
            # bytes so the fallback also works for future stores and CDNs.
            try:
                downloaded = self._image_fetcher.fetch(
                    notification.image_url,
                    timeout=self._timeout_seconds,
                )
            except Exception:
                # A malformed or temporarily unavailable remote image must never
                # abort the durable notification. Details stay private and the
                # public alert continues through the text fallback.
                downloaded = None
            if downloaded is not None:
                upload_result, bad_upload_request = self._send_uploaded_photo(
                    notification,
                    downloaded,
                )
                if upload_result.sent or not bad_upload_request:
                    return upload_result
            # If both photo paths are unusable, text still keeps the durable alert.
        return self._send_message(
            render_telegram_message(notification),
            parse_mode="HTML",
            delivery_method=(
                "text_fallback"
                if notification.image_url is not None
                else "text"
            ),
        )

    def send_text(self, message: str) -> NotificationResult:
        """Send one bounded plain-text operational message."""

        if not isinstance(message, str):
            raise TypeError("message must be a string")
        normalized = message.strip()
        if not normalized:
            raise ValueError("message must not be empty")
        if len(normalized) > _MAX_MESSAGE_LENGTH:
            raise ValueError("message exceeds the Telegram limit")
        return self._send_message(normalized)

    def _send_message(
        self,
        message: str,
        *,
        parse_mode: str | None = None,
        delivery_method: str = "text",
    ) -> NotificationResult:
        payload: dict[str, object] = {
            "chat_id": self._chat_id or "",
            "text": message,
            "disable_web_page_preview": True,
        }
        if parse_mode is not None:
            payload["parse_mode"] = parse_mode
        result, _bad_request = self._send_payload(
            method="sendMessage",
            payload=payload,
            delivery_method=delivery_method,
        )
        return result

    def _send_uploaded_photo(
        self,
        notification: OfferNotification,
        downloaded: DownloadedImage,
    ) -> tuple[NotificationResult, bool]:
        return self._send_payload(
            method="sendPhoto",
            payload={
                "chat_id": self._chat_id or "",
                "caption": render_telegram_caption(notification),
                "parse_mode": "HTML",
                "reply_markup": {
                    "inline_keyboard": [
                        [
                            {
                                "text": "Ver producto",
                                "url": notification.product_url,
                            }
                        ]
                    ]
                },
            },
            upload=downloaded,
            delivery_method="photo_upload",
        )

    def _send_payload(
        self,
        *,
        method: str,
        payload: Mapping[str, object],
        upload: DownloadedImage | None = None,
        delivery_method: str,
    ) -> tuple[NotificationResult, bool]:
        """Send one Bot API payload and identify a photo-safe HTTP/API 400."""

        if not self.enabled:
            return (
                NotificationResult(
                    channel=self.channel_name,
                    status=NotificationStatus.DISABLED,
                    detail=self.disabled_reason,
                ),
                False,
            )

        token = self._token
        assert token is not None
        endpoint = f"{_TELEGRAM_API_ROOT}/bot{token}/{method}"
        try:
            if upload is None:
                response = self._transport.post_json(
                    url=endpoint,
                    payload=payload,
                    timeout=self._timeout_seconds,
                )
            else:
                response = self._transport.post_multipart(
                    url=endpoint,
                    fields=payload,
                    file_field="photo",
                    filename=upload.filename,
                    content_type=upload.content_type,
                    content=upload.content,
                    timeout=self._timeout_seconds,
                )
        except TelegramTransportError as error:
            detail = f"Telegram transport failed ({error.category})"
            if error.status_code is not None:
                detail += f" with HTTP {error.status_code}"
            return (
                NotificationResult(
                    channel=self.channel_name,
                    status=NotificationStatus.FAILED,
                    detail=detail,
                    retryable=error.retryable,
                    retry_after_seconds=error.retry_after_seconds,
                ),
                error.status_code == 400,
            )
        except Exception:
            # Third-party injected transports may raise arbitrary exceptions. Their
            # messages are deliberately not exposed because the endpoint contains a token.
            return (
                NotificationResult(
                    channel=self.channel_name,
                    status=NotificationStatus.FAILED,
                    detail="Telegram delivery failed unexpectedly",
                    retryable=True,
                ),
                False,
            )

        if response.get("ok") is not True:
            raw_error_code = response.get("error_code")
            error_code = (
                raw_error_code
                if isinstance(raw_error_code, int) and not isinstance(raw_error_code, bool)
                else None
            )
            parameters = response.get("parameters")
            retry_after = (
                _positive_integer(parameters.get("retry_after"))
                if isinstance(parameters, Mapping)
                else None
            )
            return (
                NotificationResult(
                    channel=self.channel_name,
                    status=NotificationStatus.FAILED,
                    detail="Telegram API rejected the message",
                    retryable=(error_code is None or error_code == 429 or error_code >= 500),
                    retry_after_seconds=retry_after,
                ),
                error_code == 400,
            )

        result = response.get("result")
        message_id: str | None = None
        if isinstance(result, Mapping) and result.get("message_id") is not None:
            message_id = str(result["message_id"])
        return (
            NotificationResult(
                channel=self.channel_name,
                status=NotificationStatus.SENT,
                message_id=message_id,
                delivery_method=delivery_method,
            ),
            False,
        )


__all__ = [
    "TelegramNotifier",
    "TelegramTransport",
    "TelegramTransportError",
    "UrllibTelegramTransport",
    "render_telegram_caption",
    "render_telegram_message",
]
