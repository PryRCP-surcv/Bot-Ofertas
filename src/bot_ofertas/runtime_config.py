"""Runtime policy loaded from environment variables for the local monitor."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path

from dotenv import load_dotenv

from bot_ofertas.detection import DetectorConfig, SignalThresholds

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_EDITABLE_POLICY_KEYS = frozenset(
    {
        "scheduler_poll_seconds",
        "detection_history_limit",
        "detection_history_days",
        "equivalent_max_age_hours",
        "equivalent_limit",
        "confirmation_required",
        "confirmation_max_age_minutes",
        "confirmation_price_tolerance_percent",
        "confirmation_confidence_bonus",
        "minimum_alert_confidence",
        "alert_cooldown_hours",
        "alert_significant_improvement_percent",
        "notification_lease_seconds",
        "notification_max_attempts",
        "notification_retry_base_seconds",
        "telegram_enabled",
        "minimum_history_samples",
        "minimum_equivalent_samples",
        "possible_error_minimum_corroborating_signals",
        "possible_error_minimum_confidence",
        "good_deal_percent",
        "exceptional_deal_percent",
        "possible_price_error_percent",
    }
)
_DETECTION_POLICY_KEYS = _EDITABLE_POLICY_KEYS.difference(
    {
        "scheduler_poll_seconds",
        "notification_lease_seconds",
        "notification_max_attempts",
        "notification_retry_base_seconds",
        "telegram_enabled",
    }
)


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


def _percent_text(value: Decimal) -> str:
    rendered = format(value * Decimal("100"), "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _mapping_integer(
    values: Mapping[str, object],
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    raw_value = values.get(name, default)
    if isinstance(raw_value, bool):
        raise ValueError(f"{name} debe ser un número entero")
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} debe ser un número entero") from exc
    if value != raw_value and not isinstance(raw_value, str):
        raise ValueError(f"{name} debe ser un número entero")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} debe estar entre {minimum} y {maximum}")
    return value


def _mapping_boolean(
    values: Mapping[str, object],
    name: str,
    default: bool,
) -> bool:
    raw_value = values.get(name, default)
    if not isinstance(raw_value, bool):
        raise ValueError(f"{name} debe ser true o false")
    return raw_value


def _mapping_ratio(
    values: Mapping[str, object],
    name: str,
    default: Decimal,
) -> Decimal:
    raw_value = values.get(name, _percent_text(default))
    try:
        percentage = Decimal(str(raw_value))
    except InvalidOperation as exc:
        raise ValueError(f"{name} debe ser un porcentaje decimal") from exc
    if not percentage.is_finite() or not Decimal("0") <= percentage < Decimal("100"):
        raise ValueError(f"{name} debe estar entre 0 y menos de 100")
    return percentage / Decimal("100")


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
    policy_revision_id: int | None = None
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

    def public_policy(self) -> dict[str, int | bool | str]:
        """Return the complete editable policy without any credentials."""

        thresholds = self.detector_config.list_price_thresholds
        return {
            "scheduler_poll_seconds": self.scheduler_poll_seconds,
            "detection_history_limit": self.detection_history_limit,
            "detection_history_days": self.detection_history_days,
            "equivalent_max_age_hours": self.equivalent_max_age_hours,
            "equivalent_limit": self.equivalent_limit,
            "confirmation_required": self.confirmation_required,
            "confirmation_max_age_minutes": self.confirmation_max_age_minutes,
            "confirmation_price_tolerance_percent": _percent_text(
                self.confirmation_price_tolerance_ratio
            ),
            "confirmation_confidence_bonus": self.confirmation_confidence_bonus,
            "minimum_alert_confidence": self.minimum_alert_confidence,
            "alert_cooldown_hours": self.alert_cooldown_hours,
            "alert_significant_improvement_percent": _percent_text(
                self.alert_significant_improvement_ratio
            ),
            "notification_lease_seconds": self.notification_lease_seconds,
            "notification_max_attempts": self.notification_max_attempts,
            "notification_retry_base_seconds": self.notification_retry_base_seconds,
            "telegram_enabled": self.telegram_enabled,
            "minimum_history_samples": self.detector_config.minimum_history_samples,
            "minimum_equivalent_samples": (
                self.detector_config.minimum_equivalent_samples
            ),
            "possible_error_minimum_corroborating_signals": (
                self.detector_config.possible_error_minimum_corroborating_signals
            ),
            "possible_error_minimum_confidence": (
                self.detector_config.possible_error_minimum_confidence
            ),
            "good_deal_percent": _percent_text(thresholds.good_deal),
            "exceptional_deal_percent": _percent_text(
                thresholds.exceptional_deal
            ),
            "possible_price_error_percent": _percent_text(
                thresholds.possible_price_error
            ),
        }

    @property
    def policy_fingerprint(self) -> str:
        """Hash only settings that can change a persisted detection decision."""

        public_policy = self.public_policy()
        decision_policy = {
            key: public_policy[key] for key in sorted(_DETECTION_POLICY_KEYS)
        }
        decision_policy["detector_version"] = self.detector_version
        payload = json.dumps(
            decision_policy,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def with_policy_overrides(
        self,
        overrides: Mapping[str, object],
        *,
        revision_id: int | None = None,
    ) -> RuntimeSettings:
        """Apply a validated non-secret policy snapshot to environment defaults."""

        unknown = sorted(set(overrides).difference(_EDITABLE_POLICY_KEYS))
        if unknown:
            raise ValueError(
                "configuración no editable o desconocida: " + ", ".join(unknown)
            )
        current = self.public_policy()
        current.update(overrides)

        thresholds = SignalThresholds(
            good_deal=_mapping_ratio(
                current,
                "good_deal_percent",
                self.detector_config.list_price_thresholds.good_deal,
            ),
            exceptional_deal=_mapping_ratio(
                current,
                "exceptional_deal_percent",
                self.detector_config.list_price_thresholds.exceptional_deal,
            ),
            possible_price_error=_mapping_ratio(
                current,
                "possible_price_error_percent",
                self.detector_config.list_price_thresholds.possible_price_error,
            ),
        )
        detector_config = replace(
            self.detector_config,
            minimum_history_samples=_mapping_integer(
                current,
                "minimum_history_samples",
                self.detector_config.minimum_history_samples,
                minimum=1,
                maximum=100,
            ),
            minimum_equivalent_samples=_mapping_integer(
                current,
                "minimum_equivalent_samples",
                self.detector_config.minimum_equivalent_samples,
                minimum=1,
                maximum=20,
            ),
            possible_error_minimum_corroborating_signals=_mapping_integer(
                current,
                "possible_error_minimum_corroborating_signals",
                self.detector_config.possible_error_minimum_corroborating_signals,
                minimum=2,
                maximum=8,
            ),
            possible_error_minimum_confidence=_mapping_integer(
                current,
                "possible_error_minimum_confidence",
                self.detector_config.possible_error_minimum_confidence,
                minimum=0,
                maximum=100,
            ),
            previous_price_thresholds=thresholds,
            historical_median_thresholds=thresholds,
            historical_minimum_thresholds=thresholds,
            list_price_thresholds=thresholds,
        )
        return replace(
            self,
            scheduler_poll_seconds=_mapping_integer(
                current,
                "scheduler_poll_seconds",
                self.scheduler_poll_seconds,
                minimum=30,
                maximum=86_400,
            ),
            detection_history_limit=_mapping_integer(
                current,
                "detection_history_limit",
                self.detection_history_limit,
                minimum=3,
                maximum=10_000,
            ),
            detection_history_days=_mapping_integer(
                current,
                "detection_history_days",
                self.detection_history_days,
                minimum=30,
                maximum=3_650,
            ),
            equivalent_max_age_hours=_mapping_integer(
                current,
                "equivalent_max_age_hours",
                self.equivalent_max_age_hours,
                minimum=1,
                maximum=720,
            ),
            equivalent_limit=_mapping_integer(
                current,
                "equivalent_limit",
                self.equivalent_limit,
                minimum=2,
                maximum=100,
            ),
            confirmation_required=_mapping_boolean(
                current,
                "confirmation_required",
                self.confirmation_required,
            ),
            confirmation_max_age_minutes=_mapping_integer(
                current,
                "confirmation_max_age_minutes",
                self.confirmation_max_age_minutes,
                minimum=30,
                maximum=10_080,
            ),
            confirmation_price_tolerance_ratio=_mapping_ratio(
                current,
                "confirmation_price_tolerance_percent",
                self.confirmation_price_tolerance_ratio,
            ),
            confirmation_confidence_bonus=_mapping_integer(
                current,
                "confirmation_confidence_bonus",
                self.confirmation_confidence_bonus,
                minimum=0,
                maximum=100,
            ),
            minimum_alert_confidence=_mapping_integer(
                current,
                "minimum_alert_confidence",
                self.minimum_alert_confidence,
                minimum=0,
                maximum=100,
            ),
            alert_cooldown_hours=_mapping_integer(
                current,
                "alert_cooldown_hours",
                self.alert_cooldown_hours,
                minimum=1,
                maximum=720,
            ),
            alert_significant_improvement_ratio=_mapping_ratio(
                current,
                "alert_significant_improvement_percent",
                self.alert_significant_improvement_ratio,
            ),
            notification_lease_seconds=_mapping_integer(
                current,
                "notification_lease_seconds",
                self.notification_lease_seconds,
                minimum=30,
                maximum=3_600,
            ),
            notification_max_attempts=_mapping_integer(
                current,
                "notification_max_attempts",
                self.notification_max_attempts,
                minimum=1,
                maximum=20,
            ),
            notification_retry_base_seconds=_mapping_integer(
                current,
                "notification_retry_base_seconds",
                self.notification_retry_base_seconds,
                minimum=30,
                maximum=86_400,
            ),
            telegram_enabled=_mapping_boolean(
                current,
                "telegram_enabled",
                self.telegram_enabled,
            ),
            policy_revision_id=revision_id,
            detector_config=detector_config,
        )


__all__ = ["RuntimeSettings"]
