from __future__ import annotations

from unittest.mock import Mock

from fastapi.testclient import TestClient

from bot_ofertas.api import routes
from bot_ofertas.api.app import create_app
from bot_ofertas.api.schemas import (
    TelegramDistributionStatusRead,
    TelegramTestRead,
)
from bot_ofertas.api.service import send_telegram_beta_test
from bot_ofertas.api.settings import ApiSettings
from bot_ofertas.notifications import NotificationResult, NotificationStatus
from bot_ofertas.runtime_config import RuntimeSettings
from bot_ofertas.services.runtime_policy import EffectiveRuntimePolicy

TOKEN = "phase5-2-admin-token-with-safe-length-0001"


def _client(monkeypatch) -> TestClient:
    session = Mock()
    factory = Mock(return_value=session)
    application = create_app(
        ApiSettings(
            admin_token=TOKEN,
            cors_origins=("http://localhost:3000",),
        ),
        session_factory=factory,
    )
    monkeypatch.setattr(
        routes,
        "telegram_distribution_status",
        lambda _session: TelegramDistributionStatusRead(
            enabled=True,
            configured=True,
            ready=True,
            audience_mode="single_chat",
            membership_mode="manual",
            payment_mode="manual_external",
            automatic_offer_delivery=True,
            queue_counts={
                "pending": 1,
                "retrying": 0,
                "sent": 3,
                "failed": 0,
                "superseded": 0,
            },
            last_sent_at=None,
            last_error_at=None,
            last_error_code=None,
            last_error=None,
        ),
    )
    monkeypatch.setattr(
        routes,
        "send_telegram_beta_test",
        lambda _session, **_kwargs: TelegramTestRead(
            status="sent",
            sent=True,
            message_id="88",
            detail=None,
        ),
    )
    return TestClient(application, raise_server_exceptions=False)


def test_distribution_routes_are_admin_only_and_never_expose_chat_identity(
    monkeypatch,
) -> None:
    with _client(monkeypatch) as client:
        unauthorized = client.get("/api/v1/distribution/telegram")
        assert unauthorized.status_code == 401

        headers = {"Authorization": f"Bearer {TOKEN}"}
        status = client.get("/api/v1/distribution/telegram", headers=headers)
        test = client.post(
            "/api/v1/distribution/telegram/test",
            headers=headers,
        )

    assert status.status_code == 200
    assert status.json()["ready"] is True
    assert status.json()["membership_mode"] == "manual"
    assert "chat_id" not in status.text
    assert test.status_code == 200
    assert test.json() == {
        "destination": "telegram_free",
        "status": "sent",
        "sent": True,
        "message_id": "88",
        "detail": None,
    }


def test_beta_test_message_is_fixed_and_safe(monkeypatch) -> None:
    sent_messages: list[str] = []

    class FakeNotifier:
        def send_text(self, message: str) -> NotificationResult:
            sent_messages.append(message)
            return NotificationResult(
                channel="telegram",
                status=NotificationStatus.SENT,
                message_id="99",
            )

    monkeypatch.setattr(
        "bot_ofertas.api.service.resolve_runtime_policy",
        lambda _session: EffectiveRuntimePolicy(
            settings=RuntimeSettings(
                telegram_token="secret",
                telegram_chat_id="-100123",
                telegram_enabled=True,
            ),
            revision_id=None,
        ),
    )

    result = send_telegram_beta_test(
        Mock(),
        notifier=FakeNotifier(),  # type: ignore[arg-type]
    )

    assert result.sent is True
    assert result.message_id == "99"
    assert len(sent_messages) == 1
    assert "Bot Ofertas Perú está conectado" in sent_messages[0]
