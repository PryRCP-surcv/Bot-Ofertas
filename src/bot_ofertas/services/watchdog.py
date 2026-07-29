"""Independent watchdog that turns worker outages into deduplicated alerts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.orm import Session, sessionmaker

from bot_ofertas.notifications import NotificationResult, NotificationStatus
from bot_ofertas.services.operations import (
    WorkerOperationalSnapshot,
    read_operations_snapshot,
)
from bot_ofertas.storage.database import session_scope
from bot_ofertas.storage.models import utc_now
from bot_ofertas.storage.operations import (
    WatchdogAction,
    WorkerWatchdogStateRepository,
)


class OperationalNotifier(Protocol):
    @property
    def enabled(self) -> bool: ...

    def send_text(self, message: str) -> NotificationResult: ...


@dataclass(frozen=True, slots=True)
class WatchdogCheckResult:
    worker_state: str
    action: WatchdogAction | None
    notification_status: NotificationStatus | None
    detail: str


class WorkerWatchdogService:
    """Observe one worker and persist alert/recovery delivery boundaries."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        notifier: OperationalNotifier,
        *,
        worker_name: str = "monitor",
        grace_seconds: int = 180,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if isinstance(grace_seconds, bool) or not 0 <= grace_seconds <= 86_400:
            raise ValueError("grace_seconds must be between 0 and 86400")
        self.session_factory = session_factory
        self.notifier = notifier
        self.worker_name = worker_name
        self.grace_seconds = grace_seconds
        self.clock = clock

    def check_once(self) -> WatchdogCheckResult:
        now = self.clock()
        with session_scope(self.session_factory) as session:
            snapshot = read_operations_snapshot(
                session,
                now=now,
                worker_name=self.worker_name,
            ).worker
        with session_scope(self.session_factory) as session:
            decision = WorkerWatchdogStateRepository(session).observe(
                worker_name=self.worker_name,
                observed_state=snapshot.state,
                grace_seconds=self.grace_seconds,
                now=now,
            )

        if decision.action is None or decision.incident_id is None:
            return WatchdogCheckResult(
                worker_state=snapshot.state,
                action=None,
                notification_status=None,
                detail="Sin cambio operativo que notificar.",
            )

        message = _operational_message(
            action=decision.action,
            worker=snapshot,
            checked_at=now,
        )
        try:
            delivery = self.notifier.send_text(message)
        except Exception:
            delivery = NotificationResult(
                channel="telegram",
                status=NotificationStatus.FAILED,
                detail="Operational notification failed unexpectedly",
                retryable=True,
            )

        with session_scope(self.session_factory) as session:
            WorkerWatchdogStateRepository(session).record_delivery(
                worker_name=self.worker_name,
                incident_id=decision.incident_id,
                action=decision.action,
                sent=delivery.sent,
                error=delivery.detail,
                now=self.clock(),
            )
        return WatchdogCheckResult(
            worker_state=snapshot.state,
            action=decision.action,
            notification_status=delivery.status,
            detail=delivery.detail or (
                "Alerta operativa enviada."
                if decision.action == "alert"
                else "Recuperación operativa enviada."
            ),
        )


def _operational_message(
    *,
    action: WatchdogAction,
    worker: WorkerOperationalSnapshot,
    checked_at: datetime,
) -> str:
    checked = _iso_utc(checked_at)
    heartbeat = (
        _iso_utc(worker.last_heartbeat_at)
        if worker.last_heartbeat_at is not None
        else "nunca"
    )
    if action == "alert":
        state_label = {
            "stale": "sin señales recientes",
            "stopped": "detenido",
            "unknown": "sin registro de inicio",
        }.get(worker.state, worker.state)
        return (
            "⚠️ Bot Ofertas: monitor fuera de servicio\n"
            f"Estado: {state_label}\n"
            f"Última señal: {heartbeat}\n"
            f"Comprobado: {checked}\n"
            "El watchdog continuará revisando automáticamente."
        )
    return (
        "✅ Bot Ofertas: monitor recuperado\n"
        "Estado: activo\n"
        f"Última señal: {heartbeat}\n"
        f"Comprobado: {checked}"
    )


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="seconds")


__all__ = [
    "OperationalNotifier",
    "WatchdogCheckResult",
    "WorkerWatchdogService",
]
