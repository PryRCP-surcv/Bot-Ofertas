"""Runtime policy loaded from environment variables for the local monitor."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from dotenv import load_dotenv

from bot_ofertas.detection import DetectorConfig, SignalThresholds

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _integer(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw_value = os.environ.get(name, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} debe ser un número entero") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} debe estar entre {minimum} y {maximum}")
    return value


def _decimal_ratio(name: str, default_percent: str) -> Decimal:
    raw_value = os.environ.get(name, default_percent).strip()
    try:
        percentage = Decimal(raw_value)
    except InvalidOperation as exc:
        raise RuntimeError(f"{name} debe ser un porcentaje decimal") from exc
    if not percentage.is_finite() or not Decimal("0") <= percentage < Decimal("100"):
        raise RuntimeError(f"{name} debe estar entre 0 y menos de 100")
    return percentage / Decimal("100")


def _boolean(name: str, default: bool) -> bool:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    normalized = raw_value.strip().casefold()
    if normalized in {"1", "true", "yes", "on", "si", "sí"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} debe ser true o false")


def _required_text(name: str, default: str) -> str:
    value = os.environ.get(name, default).strip()
    if not value:
        raise RuntimeError(f"{name} no puede estar vacío")
    if len(value) > 50:
        raise RuntimeError(f"{name} no puede superar 50 caracteres")
    return value


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    """Operational settings whose defaults are safe for the local Phase 3 monitor."""

    scheduler_poll_seconds: int = 300
    detector_version: str = "phase3-v2"
    detection_history_limit: int = 2_500
    detection_history_days: int = 90
    equivalent_max_age_hours: int = 24
    equivalent_limit: int = 20
    confirmation_required: bool = True
    confirmation_max_age_minutes: int = 180
    confirmation_price_tolerance_ratio: Decimal = Decimal("0.03")
    confirmation_confidence_bonus: int = 20
    minimum_alert_confidence: int = 50
    alert_cooldown_hours: int = 24
    alert_significant_improvement_ratio: Decimal = Decimal("0.05")
    notification_lease_seconds: int = 120
    notification_max_attempts: int = 5
    notification_retry_base_seconds: int = 300
    telegram_token: str | None = field(default=None, repr=False)
    telegram_chat_id: str | None = None
    telegram_enabled: bool = True
    detector_config: DetectorConfig = field(default_factory=DetectorConfig)

    @classmethod
    def from_env(cls) -> RuntimeSettings:
        load_dotenv(_PROJECT_ROOT / ".env", override=False)

        good = _decimal_ratio("BOT_DEAL_GOOD_PERCENT", "20")
        exceptional = _decimal_ratio("BOT_DEAL_EXCEPTIONAL_PERCENT", "40")
        possible_error = _decimal_ratio("BOT_DEAL_PRICE_ERROR_PERCENT", "70")
        thresholds = SignalThresholds(
            good_deal=good,
            exceptional_deal=exceptional,
            possible_price_error=possible_error,
        )

        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() or None
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip() or None
        return cls(
            detector_version=_required_text("BOT_DETECTOR_VERSION", "phase3-v2"),
            scheduler_poll_seconds=_integer(
                "BOT_SCHEDULER_POLL_SECONDS",
                300,
                minimum=30,
                maximum=86_400,
            ),
            detection_history_limit=_integer(
                "BOT_DETECTION_HISTORY_LIMIT",
                2_500,
                minimum=3,
                maximum=10_000,
            ),
            detection_history_days=_integer(
                "BOT_DETECTION_HISTORY_DAYS",
                90,
                minimum=30,
                maximum=3_650,
            ),
            equivalent_max_age_hours=_integer(
                "BOT_EQUIVALENT_MAX_AGE_HOURS",
                24,
                minimum=1,
                maximum=720,
            ),
            equivalent_limit=_integer(
                "BOT_EQUIVALENT_LIMIT",
                20,
                minimum=2,
                maximum=100,
            ),
            confirmation_required=_boolean(
                "BOT_CONFIRMATION_REQUIRED",
                True,
            ),
            confirmation_max_age_minutes=_integer(
                "BOT_CONFIRMATION_MAX_AGE_MINUTES",
                180,
                minimum=30,
                maximum=10_080,
            ),
            confirmation_price_tolerance_ratio=_decimal_ratio(
                "BOT_CONFIRMATION_PRICE_TOLERANCE_PERCENT",
                "3",
            ),
            confirmation_confidence_bonus=_integer(
                "BOT_CONFIRMATION_CONFIDENCE_BONUS",
                20,
                minimum=0,
                maximum=100,
            ),
            minimum_alert_confidence=_integer(
                "BOT_ALERT_MIN_CONFIDENCE",
                50,
                minimum=0,
                maximum=100,
            ),
            alert_cooldown_hours=_integer(
                "BOT_ALERT_COOLDOWN_HOURS",
                24,
                minimum=1,
                maximum=720,
            ),
            alert_significant_improvement_ratio=_decimal_ratio(
                "BOT_ALERT_SIGNIFICANT_IMPROVEMENT_PERCENT",
                "5",
            ),
            notification_lease_seconds=_integer(
                "BOT_NOTIFICATION_LEASE_SECONDS",
                120,
                minimum=30,
                maximum=3_600,
            ),
            notification_max_attempts=_integer(
                "BOT_NOTIFICATION_MAX_ATTEMPTS",
                5,
                minimum=1,
                maximum=20,
            ),
            notification_retry_base_seconds=_integer(
                "BOT_NOTIFICATION_RETRY_BASE_SECONDS",
                300,
                minimum=30,
                maximum=86_400,
            ),
            telegram_token=token,
            telegram_chat_id=chat_id,
            telegram_enabled=_boolean("TELEGRAM_ENABLED", True),
            detector_config=DetectorConfig(
                minimum_history_samples=_integer(
                    "BOT_DETECTION_MIN_HISTORY_SAMPLES",
                    3,
                    minimum=1,
                    maximum=100,
                ),
                minimum_equivalent_samples=_integer(
                    "BOT_DETECTION_MIN_EQUIVALENT_SAMPLES",
                    2,
                    minimum=1,
                    maximum=20,
                ),
                possible_error_minimum_corroborating_signals=_integer(
                    "BOT_PRICE_ERROR_MIN_CORROBORATING_SIGNALS",
                    2,
                    minimum=2,
                    maximum=8,
                ),
                possible_error_minimum_confidence=_integer(
                    "BOT_PRICE_ERROR_MIN_CONFIDENCE",
                    50,
                    minimum=0,
                    maximum=100,
                ),
                previous_price_thresholds=thresholds,
                historical_median_thresholds=thresholds,
                historical_minimum_thresholds=thresholds,
                list_price_thresholds=thresholds,
            ),
        )


__all__ = ["RuntimeSettings"]
