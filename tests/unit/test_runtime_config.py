from decimal import Decimal

import pytest

import bot_ofertas.runtime_config as runtime_config
from bot_ofertas.runtime_config import RuntimeSettings

_RUNTIME_ENV_NAMES = (
    "BOT_ALERT_COOLDOWN_HOURS",
    "BOT_ALERT_MIN_CONFIDENCE",
    "BOT_ALERT_SIGNIFICANT_IMPROVEMENT_PERCENT",
    "BOT_CONFIRMATION_CONFIDENCE_BONUS",
    "BOT_CONFIRMATION_MAX_AGE_MINUTES",
    "BOT_CONFIRMATION_PRICE_TOLERANCE_PERCENT",
    "BOT_CONFIRMATION_REQUIRED",
    "BOT_DEAL_EXCEPTIONAL_PERCENT",
    "BOT_DEAL_GOOD_PERCENT",
    "BOT_DEAL_PRICE_ERROR_PERCENT",
    "BOT_DETECTION_HISTORY_DAYS",
    "BOT_DETECTION_HISTORY_LIMIT",
    "BOT_DETECTION_MIN_EQUIVALENT_SAMPLES",
    "BOT_DETECTION_MIN_HISTORY_SAMPLES",
    "BOT_DETECTOR_VERSION",
    "BOT_EQUIVALENT_LIMIT",
    "BOT_EQUIVALENT_MAX_AGE_HOURS",
    "BOT_NOTIFICATION_LEASE_SECONDS",
    "BOT_NOTIFICATION_MAX_ATTEMPTS",
    "BOT_NOTIFICATION_RETRY_BASE_SECONDS",
    "BOT_PRICE_ERROR_MIN_CONFIDENCE",
    "BOT_PRICE_ERROR_MIN_CORROBORATING_SIGNALS",
    "BOT_SCHEDULER_POLL_SECONDS",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TELEGRAM_ENABLED",
)


@pytest.fixture(autouse=True)
def _do_not_read_the_developer_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime_config, "load_dotenv", lambda *_args, **_kwargs: False)
    for name in _RUNTIME_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_runtime_settings_load_safe_defaults() -> None:
    settings = RuntimeSettings.from_env()

    assert settings.scheduler_poll_seconds == 300
    assert settings.detector_version == "phase3-v2"
    assert settings.detection_history_limit == 2_500
    assert settings.detection_history_days == 90
    assert settings.equivalent_max_age_hours == 24
    assert settings.equivalent_limit == 20
    assert settings.confirmation_required is True
    assert settings.confirmation_max_age_minutes == 180
    assert settings.confirmation_price_tolerance_ratio == Decimal("0.03")
    assert settings.confirmation_confidence_bonus == 20
    assert settings.minimum_alert_confidence == 50
    assert settings.alert_significant_improvement_ratio == Decimal("0.05")
    assert settings.telegram_token is None
    assert settings.detector_config.minimum_history_samples == 3
    assert settings.detector_config.minimum_equivalent_samples == 2
    assert settings.detector_config.possible_error_minimum_corroborating_signals == 2
    assert settings.detector_config.possible_error_minimum_confidence == 50
    assert settings.detector_config.allowed_currency == "PEN"


def test_runtime_settings_load_phase3_policy_thresholds_and_telegram(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOT_DETECTOR_VERSION", "phase3-experiment")
    monkeypatch.setenv("BOT_DETECTION_HISTORY_LIMIT", "9000")
    monkeypatch.setenv("BOT_DETECTION_HISTORY_DAYS", "365")
    monkeypatch.setenv("BOT_EQUIVALENT_MAX_AGE_HOURS", "48")
    monkeypatch.setenv("BOT_EQUIVALENT_LIMIT", "40")
    monkeypatch.setenv("BOT_DETECTION_MIN_HISTORY_SAMPLES", "5")
    monkeypatch.setenv("BOT_DETECTION_MIN_EQUIVALENT_SAMPLES", "4")
    monkeypatch.setenv("BOT_CONFIRMATION_REQUIRED", "false")
    monkeypatch.setenv("BOT_CONFIRMATION_MAX_AGE_MINUTES", "240")
    monkeypatch.setenv("BOT_CONFIRMATION_PRICE_TOLERANCE_PERCENT", "2.5")
    monkeypatch.setenv("BOT_CONFIRMATION_CONFIDENCE_BONUS", "15")
    monkeypatch.setenv("BOT_ALERT_MIN_CONFIDENCE", "65")
    monkeypatch.setenv("BOT_PRICE_ERROR_MIN_CORROBORATING_SIGNALS", "3")
    monkeypatch.setenv("BOT_PRICE_ERROR_MIN_CONFIDENCE", "75")
    monkeypatch.setenv("BOT_DEAL_GOOD_PERCENT", "25")
    monkeypatch.setenv("BOT_DEAL_EXCEPTIONAL_PERCENT", "50")
    monkeypatch.setenv("BOT_DEAL_PRICE_ERROR_PERCENT", "80")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "secret-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")

    settings = RuntimeSettings.from_env()

    assert settings.detector_version == "phase3-experiment"
    assert settings.detection_history_limit == 9_000
    assert settings.detection_history_days == 365
    assert settings.equivalent_max_age_hours == 48
    assert settings.equivalent_limit == 40
    assert settings.confirmation_required is False
    assert settings.confirmation_max_age_minutes == 240
    assert settings.confirmation_price_tolerance_ratio == Decimal("0.025")
    assert settings.confirmation_confidence_bonus == 15
    assert settings.minimum_alert_confidence == 65
    thresholds = settings.detector_config.list_price_thresholds
    assert thresholds.good_deal == Decimal("0.25")
    assert thresholds.exceptional_deal == Decimal("0.5")
    assert thresholds.possible_price_error == Decimal("0.8")
    assert settings.detector_config.minimum_history_samples == 5
    assert settings.detector_config.minimum_equivalent_samples == 4
    assert settings.detector_config.possible_error_minimum_corroborating_signals == 3
    assert settings.detector_config.possible_error_minimum_confidence == 75
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


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("BOT_DETECTION_HISTORY_LIMIT", "2"),
        ("BOT_DETECTION_HISTORY_LIMIT", "10001"),
        ("BOT_DETECTION_HISTORY_DAYS", "29"),
        ("BOT_DETECTION_HISTORY_DAYS", "3651"),
        ("BOT_EQUIVALENT_MAX_AGE_HOURS", "0"),
        ("BOT_EQUIVALENT_MAX_AGE_HOURS", "721"),
        ("BOT_EQUIVALENT_LIMIT", "1"),
        ("BOT_EQUIVALENT_LIMIT", "101"),
        ("BOT_CONFIRMATION_MAX_AGE_MINUTES", "29"),
        ("BOT_CONFIRMATION_MAX_AGE_MINUTES", "10081"),
        ("BOT_CONFIRMATION_CONFIDENCE_BONUS", "-1"),
        ("BOT_CONFIRMATION_CONFIDENCE_BONUS", "101"),
        ("BOT_ALERT_MIN_CONFIDENCE", "-1"),
        ("BOT_ALERT_MIN_CONFIDENCE", "101"),
        ("BOT_DETECTION_MIN_EQUIVALENT_SAMPLES", "0"),
        ("BOT_DETECTION_MIN_EQUIVALENT_SAMPLES", "21"),
        ("BOT_PRICE_ERROR_MIN_CORROBORATING_SIGNALS", "1"),
        ("BOT_PRICE_ERROR_MIN_CORROBORATING_SIGNALS", "9"),
        ("BOT_PRICE_ERROR_MIN_CONFIDENCE", "-1"),
        ("BOT_PRICE_ERROR_MIN_CONFIDENCE", "101"),
        ("BOT_EQUIVALENT_LIMIT", "not-an-integer"),
    ],
)
def test_runtime_settings_reject_invalid_phase3_integer_policy(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(RuntimeError, match=name):
        RuntimeSettings.from_env()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("BOT_CONFIRMATION_REQUIRED", "sometimes"),
        ("BOT_CONFIRMATION_PRICE_TOLERANCE_PERCENT", "-0.1"),
        ("BOT_CONFIRMATION_PRICE_TOLERANCE_PERCENT", "100"),
        ("BOT_CONFIRMATION_PRICE_TOLERANCE_PERCENT", "not-a-percent"),
        ("BOT_DETECTOR_VERSION", ""),
        ("BOT_DETECTOR_VERSION", "v" * 51),
    ],
)
def test_runtime_settings_reject_invalid_phase3_non_integer_policy(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(RuntimeError, match=name):
        RuntimeSettings.from_env()


def test_runtime_policy_snapshot_excludes_credentials_and_is_canonical() -> None:
    settings = RuntimeSettings(
        telegram_token="never-expose-token",
        telegram_chat_id="never-expose-chat",
    )

    policy = settings.public_policy()

    assert policy["good_deal_percent"] == "20"
    assert policy["exceptional_deal_percent"] == "40"
    assert policy["possible_price_error_percent"] == "70"
    assert "telegram_token" not in policy
    assert "telegram_chat_id" not in policy
    assert len(settings.policy_fingerprint) == 64
    assert settings.policy_fingerprint == RuntimeSettings().policy_fingerprint


def test_runtime_policy_overrides_are_validated_and_revisioned() -> None:
    base = RuntimeSettings()

    updated = base.with_policy_overrides(
        {
            "good_deal_percent": "25",
            "exceptional_deal_percent": "50",
            "possible_price_error_percent": "80",
            "minimum_history_samples": 5,
            "telegram_enabled": False,
        },
        revision_id=7,
    )

    thresholds = updated.detector_config.list_price_thresholds
    assert thresholds.good_deal == Decimal("0.25")
    assert thresholds.exceptional_deal == Decimal("0.50")
    assert thresholds.possible_price_error == Decimal("0.80")
    assert updated.detector_config.minimum_history_samples == 5
    assert updated.telegram_enabled is False
    assert updated.policy_revision_id == 7
    assert updated.policy_fingerprint != base.policy_fingerprint


def test_non_detection_policy_does_not_change_detection_fingerprint() -> None:
    base = RuntimeSettings()

    updated = base.with_policy_overrides(
        {
            "scheduler_poll_seconds": 900,
            "notification_retry_base_seconds": 600,
            "telegram_enabled": False,
        }
    )

    assert updated.policy_fingerprint == base.policy_fingerprint


@pytest.mark.parametrize(
    "overrides",
    [
        {"database_password": "not-editable"},
        {"confirmation_required": "yes"},
        {"minimum_history_samples": True},
        {
            "good_deal_percent": "80",
            "exceptional_deal_percent": "40",
        },
    ],
)
def test_runtime_policy_rejects_unknown_or_invalid_overrides(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        RuntimeSettings().with_policy_overrides(overrides)
