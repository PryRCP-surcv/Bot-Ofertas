from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import pytest

from bot_ofertas.notifications import (
    DownloadedImage,
    NotificationChannel,
    NotificationStatus,
    OfferNotification,
    RemoteImageError,
    TelegramNotifier,
    TelegramTransportError,
    UrllibTelegramTransport,
    render_telegram_caption,
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
        self.multipart_calls: list[dict[str, object]] = []

    def post_json(
        self,
        *,
        url: str,
        payload: Mapping[str, object],
        timeout: float,
    ) -> Mapping[str, Any]:
        self.calls.append((url, payload, timeout))
        return self.response

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
        self.multipart_calls.append(
            {
                "url": url,
                "fields": fields,
                "file_field": file_field,
                "filename": filename,
                "content_type": content_type,
                "content": content,
                "timeout": timeout,
            }
        )
        return self.response


class SequenceTransport:
    def __init__(self, responses: list[Mapping[str, Any]]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, Mapping[str, object], float]] = []
        self.multipart_calls: list[dict[str, object]] = []
        self.events: list[str] = []

    def post_json(
        self,
        *,
        url: str,
        payload: Mapping[str, object],
        timeout: float,
    ) -> Mapping[str, Any]:
        self.calls.append((url, payload, timeout))
        self.events.append(url.rsplit("/", 1)[-1])
        return self.responses.pop(0)

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
        self.multipart_calls.append(
            {
                "url": url,
                "fields": fields,
                "file_field": file_field,
                "filename": filename,
                "content_type": content_type,
                "content": content,
                "timeout": timeout,
            }
        )
        self.events.append(f"{url.rsplit('/', 1)[-1]}:multipart")
        return self.responses.pop(0)


class RecordingImageFetcher:
    def __init__(
        self,
        result: DownloadedImage | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result or DownloadedImage(
            content=b"\xff\xd8\xffvalidated-jpeg",
            content_type="image/jpeg",
            filename="offer.jpg",
        )
        self.error = error
        self.calls: list[tuple[str, float]] = []

    def fetch(self, url: str, *, timeout: float) -> DownloadedImage:
        self.calls.append((url, timeout))
        if self.error is not None:
            raise self.error
        return self.result


class FakeTelegramResponse:
    def __enter__(self) -> "FakeTelegramResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return b'{"ok":true,"result":{"message_id":88}}'


def test_urllib_transport_encodes_an_in_memory_photo_as_multipart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request: object, *, timeout: float) -> FakeTelegramResponse:
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeTelegramResponse()

    monkeypatch.setattr(
        "bot_ofertas.notifications.telegram.urlopen",
        fake_urlopen,
    )
    response = UrllibTelegramTransport().post_multipart(
        url="https://api.telegram.org/bot123:test/sendPhoto",
        fields={
            "chat_id": "-100123",
            "caption": "Oferta Perú",
            "reply_markup": {"inline_keyboard": []},
        },
        file_field="photo",
        filename="offer.webp",
        content_type="image/webp",
        content=b"RIFF1234WEBPcontent",
        timeout=6.0,
    )

    request = captured["request"]
    body = request.data  # type: ignore[attr-defined]
    content_type = request.headers["Content-type"]  # type: ignore[attr-defined]
    assert response["ok"] is True
    assert captured["timeout"] == 6.0
    assert content_type.startswith("multipart/form-data; boundary=botofertas-")
    assert b'name="chat_id"\r\n\r\n-100123' in body
    assert "Oferta Perú".encode() in body
    assert b'name="reply_markup"' in body
    assert b'filename="offer.webp"' in body
    assert b"Content-Type: image/webp" in body
    assert b"RIFF1234WEBPcontent" in body


def test_offer_notification_normalizes_values_and_rejects_float_money() -> None:
    notification = make_notification()

    assert notification.currency == "PEN"
    assert notification.classification == "price_error"
    assert notification.current_price == Decimal("179")

    with pytest.raises(TypeError, match="floats are not accepted"):
        make_notification(current_price=179.0)


@pytest.mark.parametrize(
    "image_url",
    [
        "http://cdn.example.pe/producto.jpg",
        "https://user:secret@cdn.example.pe/producto.jpg",
        "https://cdn.example.pe:8443/producto.jpg",
    ],
)
def test_offer_notification_rejects_unsafe_image_urls(image_url: str) -> None:
    with pytest.raises(ValueError, match="image_url"):
        make_notification(image_url=image_url)


def test_offer_notification_normalizes_and_deduplicates_conditions() -> None:
    notification = make_notification(
        conditions=[
            "  requiere un cupón  ",
            "requiere un cupón",
            "precio exclusivo para socios",
        ]
    )

    assert notification.conditions == (
        "requiere un cupón",
        "precio exclusivo para socios",
    )


@pytest.mark.parametrize(
    "conditions",
    [
        "requiere un cupón",
        ("condición válida", 42),
        ["  "],
    ],
)
def test_offer_notification_rejects_invalid_conditions(conditions: object) -> None:
    with pytest.raises((TypeError, ValueError), match="conditions"):
        make_notification(conditions=conditions)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("confidence_score", -1, "confidence_score"),
        ("confidence_score", 101, "confidence_score"),
        ("confidence_score", True, "confidence_score"),
        ("confirmation_count", 0, "confirmation_count"),
        ("confirmation_count", -1, "confirmation_count"),
        ("confirmation_count", True, "confirmation_count"),
    ],
)
def test_offer_notification_rejects_invalid_phase3_metadata(
    field: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        make_notification(**{field: value})


def test_rendered_message_explains_offer_and_escapes_dynamic_html() -> None:
    message = render_telegram_message(make_notification())

    assert "🚨 Posible error de precio" in message
    assert "<b>Audífonos &lt;Pro&gt; &amp; &quot;Case&quot;</b>" in message
    assert "💰 <b>Precio:</b> S/ 179.00" in message
    assert "<s>S/ 499.00</s> · <b>64.13% de descuento</b>" in message
    assert "mínimo histórico" not in message
    assert "Coolbox &amp; Perú" in message
    assert 'href="https://www.coolbox.pe/producto?a=1&amp;b=2"' in message
    assert "Razón:" not in message
    assert len(message) <= 4096


def test_rendered_message_shows_conditions_and_escapes_their_html() -> None:
    message = render_telegram_message(
        make_notification(
            conditions=(
                "precio con tarjeta <Oh!>",
                'requiere cupón "VERANO" & membresía',
            )
        )
    )

    assert "⚠️ precio con tarjeta &lt;Oh!&gt;" in message
    assert "⚠️ requiere cupón &quot;VERANO&quot; &amp; membresía" in message


def test_public_message_hides_audit_metadata_but_keeps_verified_badge() -> None:
    notification = make_notification(
        confidence_score=85,
        confirmation_count=3,
        reason="descuento confirmado. Referencia interna #20",
    )

    assert notification.confidence_score == 85
    assert notification.confirmation_count == 3
    assert "Referencia interna #20" in notification.reason

    message = render_telegram_message(notification)
    caption = render_telegram_caption(notification)

    for public_text in (message, caption):
        assert "Confianza:" not in public_text
        assert "Confirmaciones:" not in public_text
        assert "Razón:" not in public_text
        assert "Referencia interna" not in public_text
        assert "✅ Precio verificado" in public_text


def test_public_message_cleans_store_prefix_internal_code_and_product_casing() -> None:
    message = render_telegram_message(
        make_notification(
            product_name="topitop cafarena mujer sole color vino grape 1739109",
            store_name="topitop",
        )
    )

    assert "<b>Cafarena Mujer Sole Color Vino Grape</b>" in message
    assert "<b>Topitop cafarena" not in message
    assert "1739109" not in message

    model_message = render_telegram_message(
        make_notification(
            product_name="estilos thomas batidoras th 350p pedestal14998",
            store_name="estilos",
        )
    )

    assert "<b>Thomas Batidoras TH 350P Pedestal</b>" in model_message
    assert "14998" not in model_message


def test_public_message_formats_variant_labels_without_equals() -> None:
    message = render_telegram_message(
        make_notification(
            variant_summary=(
                "Disponibles: Color=cobre, Talla=35; "
                "Color=blanco, Talla=36"
            ),
        )
    )

    assert "🔹 <b>Variantes disponibles:</b>" in message
    assert "<b>Color:</b> Cobre" in message
    assert "<b>Talla:</b> 35" in message
    assert "Color=" not in message
    assert "Talla=" not in message


@pytest.mark.parametrize(
    ("discount_percent", "expected_heading"),
    [
        (Decimal("35"), "🔥 Oferta imperdible"),
        (Decimal("49.99"), "🔥 Oferta imperdible"),
        (Decimal("50"), "💥 Oferta excepcional"),
        (Decimal("69.99"), "💥 Oferta excepcional"),
    ],
)
def test_exceptional_heading_reflects_commercial_discount_tier(
    discount_percent: Decimal,
    expected_heading: str,
) -> None:
    message = render_telegram_message(
        make_notification(
            classification="exceptional_deal",
            discount_percent=discount_percent,
        )
    )

    assert expected_heading in message


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
    assert result.delivery_method == "text"
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


def test_send_with_image_uses_photo_caption_and_product_button() -> None:
    transport = RecordingTransport()
    notifier = TelegramNotifier(
        token="123:secret-token",
        chat_id="-100123",
        timeout_seconds=3.5,
        transport=transport,
    )
    notification = make_notification(
        image_url="https://cdn.coolbox.pe/productos/audifonos.jpg"
    )

    result = notifier.send(notification)

    assert result.status is NotificationStatus.SENT
    assert result.delivery_method == "photo_url"
    assert transport.calls == [
        (
            "https://api.telegram.org/bot123:secret-token/sendPhoto",
            {
                "chat_id": "-100123",
                "photo": "https://cdn.coolbox.pe/productos/audifonos.jpg",
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
            3.5,
        )
    ]
    assert len(render_telegram_caption(notification)) <= 1024


def test_bad_remote_photo_is_downloaded_and_uploaded_from_memory() -> None:
    transport = SequenceTransport(
        [
            {"ok": False, "error_code": 400},
            {"ok": True, "result": {"message_id": 99}},
        ]
    )
    image_fetcher = RecordingImageFetcher()
    notifier = TelegramNotifier(
        token="123:secret-token",
        chat_id="-100123",
        transport=transport,
        image_fetcher=image_fetcher,
    )
    notification = make_notification(
        image_url="https://cdn.coolbox.pe/productos/invalida.jpg"
    )

    result = notifier.send(notification)

    assert result.status is NotificationStatus.SENT
    assert result.message_id == "99"
    assert result.delivery_method == "photo_upload"
    assert transport.events == [
        "sendPhoto",
        "sendPhoto:multipart",
    ]
    assert image_fetcher.calls == [(notification.image_url, 10.0)]
    assert transport.multipart_calls == [
        {
            "url": "https://api.telegram.org/bot123:secret-token/sendPhoto",
            "fields": {
                "chat_id": "-100123",
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
            "file_field": "photo",
            "filename": "offer.jpg",
            "content_type": "image/jpeg",
            "content": b"\xff\xd8\xffvalidated-jpeg",
            "timeout": 10.0,
        }
    ]


def test_bad_remote_and_uploaded_photo_fall_back_to_complete_text() -> None:
    transport = SequenceTransport(
        [
            {"ok": False, "error_code": 400},
            {"ok": False, "error_code": 400},
            {"ok": True, "result": {"message_id": 100}},
        ]
    )
    notifier = TelegramNotifier(
        token="123:secret-token",
        chat_id="-100123",
        transport=transport,
        image_fetcher=RecordingImageFetcher(),
    )
    notification = make_notification(
        image_url="https://cdn.coolbox.pe/productos/invalida.jpg"
    )

    result = notifier.send(notification)

    assert result.status is NotificationStatus.SENT
    assert result.message_id == "100"
    assert result.delivery_method == "text_fallback"
    assert transport.events == [
        "sendPhoto",
        "sendPhoto:multipart",
        "sendMessage",
    ]
    assert transport.calls[-1][1]["text"] == render_telegram_message(notification)


def test_failed_image_download_falls_back_to_complete_text() -> None:
    transport = SequenceTransport(
        [
            {"ok": False, "error_code": 400},
            {"ok": True, "result": {"message_id": 101}},
        ]
    )
    image_fetcher = RecordingImageFetcher(
        error=RemoteImageError("remote_network_error")
    )
    notifier = TelegramNotifier(
        token="123:secret-token",
        chat_id="-100123",
        transport=transport,
        image_fetcher=image_fetcher,
    )
    notification = make_notification(
        image_url="https://cdn.coolbox.pe/productos/invalida.jpg"
    )

    result = notifier.send(notification)

    assert result.status is NotificationStatus.SENT
    assert result.delivery_method == "text_fallback"
    assert transport.events == ["sendPhoto", "sendMessage"]
    assert transport.multipart_calls == []


def test_photo_rate_limit_is_retried_later_without_a_duplicate_text_attempt() -> None:
    transport = RecordingTransport(
        {
            "ok": False,
            "error_code": 429,
            "parameters": {"retry_after": 30},
        }
    )
    image_fetcher = RecordingImageFetcher()
    notifier = TelegramNotifier(
        token="123:secret-token",
        chat_id="-100123",
        transport=transport,
        image_fetcher=image_fetcher,
    )

    result = notifier.send(
        make_notification(image_url="https://cdn.coolbox.pe/productos/audifonos.jpg")
    )

    assert result.status is NotificationStatus.FAILED
    assert result.retryable is True
    assert result.retry_after_seconds == 30
    assert len(transport.calls) == 1
    assert transport.calls[0][0].endswith("/sendPhoto")
    assert image_fetcher.calls == []


def test_uploaded_photo_rate_limit_is_retried_without_text_fallback() -> None:
    transport = SequenceTransport(
        [
            {"ok": False, "error_code": 400},
            {
                "ok": False,
                "error_code": 429,
                "parameters": {"retry_after": 45},
            },
        ]
    )
    notifier = TelegramNotifier(
        token="123:secret-token",
        chat_id="-100123",
        transport=transport,
        image_fetcher=RecordingImageFetcher(),
    )

    result = notifier.send(
        make_notification(image_url="https://cdn.example.pe/product.jpg")
    )

    assert result.status is NotificationStatus.FAILED
    assert result.retryable is True
    assert result.retry_after_seconds == 45
    assert transport.events == ["sendPhoto", "sendPhoto:multipart"]


def test_send_text_uses_plain_telegram_message_without_html_mode() -> None:
    transport = RecordingTransport()
    notifier = TelegramNotifier(
        token="123:secret-token",
        chat_id="-100123",
        transport=transport,
    )

    result = notifier.send_text("⚠️ Monitor detenido")

    assert result.status is NotificationStatus.SENT
    assert transport.calls == [
        (
            "https://api.telegram.org/bot123:secret-token/sendMessage",
            {
                "chat_id": "-100123",
                "text": "⚠️ Monitor detenido",
                "disable_web_page_preview": True,
            },
            10.0,
        )
    ]


@pytest.mark.parametrize("message", ["", "   ", "x" * 4_097])
def test_send_text_rejects_empty_or_oversized_messages(message: str) -> None:
    notifier = TelegramNotifier(token="token", chat_id="chat")

    with pytest.raises(ValueError, match="message"):
        notifier.send_text(message)


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
