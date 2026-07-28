from decimal import Decimal

import pytest

import bot_ofertas.runtime_config as runtime_config
from bot_ofertas.runtime_config import RuntimeSettings


@pytest.fixture(autouse=True)
def _do_not_read_the_developer_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime_config, "load_dotenv", lambda *_args, **_kwargs: False)


def test_runtime_settings_load_safe_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    names = (
        "BOT_SCHEDULER_POLL_SECONDS",
        "BOT_DETECTION_HISTORY_LIMIT",
        "BOT_ALERT_COOLDOWN_HOURS",
        "BOT_ALERT_SIGNIFICANT_IMPROVEMENT_PERCENT",
        "BOT_DEAL_GOOD_PERCENT",
        "BOT_DEAL_EXCEPTIONAL_PERCENT",
        "BOT_DEAL_PRICE_ERROR_PERCENT",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "TELEGRAM_ENABLED",
    )
    for name in names:
        monkeypatch.delenv(name, raising=False)

    settings = RuntimeSettings.from_env()

    assert settings.scheduler_poll_seconds == 300
    assert settings.alert_significant_improvement_ratio == Decimal("0.05")
    assert settings.telegram_token is None
    assert settings.detector_config.allowed_currency == "PEN"


def test_runtime_settings_load_thresholds_and_telegram(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOT_DEAL_GOOD_PERCENT", "25")
    monkeypatch.setenv("BOT_DEAL_EXCEPTIONAL_PERCENT", "50")
    monkeypatch.setenv("BOT_DEAL_PRICE_ERROR_PERCENT", "80")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "secret-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")

    settings = RuntimeSettings.from_env()

    thresholds = settings.detector_config.list_price_thresholds
    assert thresholds.good_deal == Decimal("0.25")
    assert thresholds.exceptional_deal == Decimal("0.5")
    assert thresholds.possible_price_error == Decimal("0.8")
    assert settings.telegram_token == "secret-token"
    assert settings.telegram_chat_id == "12345"
    assert "secret-token" not in repr(settings)


def test_runtime_settings_reject_invalid_threshold_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOT_DEAL_GOOD_PERCENT", "60")
    monkeypatch.setenv("BOT_DEAL_EXCEPTIONAL_PERCENT", "40")

    with pytest.raises(ValueError, match="ordered"):
        RuntimeSettings.from_env()
