"""Persistence operations for the local worker control plane."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bot_ofertas.storage.models import (
    CrawlJob,
    CrawlJobStatus,
    WorkerCycleStatus,
    WorkerLifecycleStatus,
    WorkerRuntimeState,
    WorkerWatchdogState,
)


class WorkerAlreadyRunningError(RuntimeError):
    """Raised when another fresh instance already owns the worker name."""


class WorkerOwnershipLostError(RuntimeError):
    """Raised when a superseded process tries to update worker state."""


WatchdogAction = Literal["alert", "recovery"]


@dataclass(frozen=True, slots=True)
class WatchdogDecision:
    action: WatchdogAction | None
    incident_id: UUID | None
    incident_opened_at: datetime | None
    observed_state: str


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _trimmed(value: str | None, *, maximum: int) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    return normalized[:maximum] or None


class WorkerRuntimeStateRepository:
    """Serialize lifecycle updates for one named worker."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, worker_name: str) -> WorkerRuntimeState | None:
        return self.session.get(WorkerRuntimeState, worker_name)

    def register_start(
        self,
        *,
        worker_name: str,
        instance_id: UUID,
        stale_after_seconds: int,
        now: datetime,
    ) -> WorkerRuntimeState:
        if not 30 <= stale_after_seconds <= 86_400:
            raise ValueError("stale_after_seconds must be between 30 and 86400")
        timestamp = _as_utc(now)
        state = self.session.get(
            WorkerRuntimeState,
            worker_name,
            with_for_update=True,
        )
        if state is None:
            state = WorkerRuntimeState(
                worker_name=worker_name,
                instance_id=instance_id,
                lifecycle_status=WorkerLifecycleStatus.RUNNING.value,
                started_at=timestamp,
                last_heartbeat_at=timestamp,
                stale_after_seconds=stale_after_seconds,
                message="Monitor iniciado.",
            )
            self.session.add(state)
            self.session.flush()
            return state

        heartbeat = _as_utc(state.last_heartbeat_at)
        fresh_until = heartbeat + timedelta(seconds=state.stale_after_seconds)
        if (
            state.lifecycle_status == WorkerLifecycleStatus.RUNNING.value
            and state.instance_id != instance_id
            and timestamp <= fresh_until
        ):
            raise WorkerAlreadyRunningError(
                "Another monitor instance is already reporting a fresh heartbeat."
            )

        if (
            state.lifecycle_status == WorkerLifecycleStatus.RUNNING.value
            and state.instance_id != instance_id
            and state.last_cycle_status == WorkerCycleStatus.RUNNING.value
        ):
            state.last_cycle_status = WorkerCycleStatus.FAILED.value
            state.last_cycle_finished_at = timestamp
            state.last_error = (
                "La instancia anterior dejó de enviar señales durante un ciclo."
            )

        state.instance_id = instance_id
        state.lifecycle_status = WorkerLifecycleStatus.RUNNING.value
        state.started_at = timestamp
        state.last_heartbeat_at = timestamp
        state.stale_after_seconds = stale_after_seconds
        state.stopped_at = None
        state.message = "Monitor iniciado."
        self.session.flush()
        return state

    def heartbeat(
        self,
        *,
        worker_name: str,
        instance_id: UUID,
        now: datetime,
    ) -> WorkerRuntimeState:
        state = self._owned_running_state(
            worker_name=worker_name,
            instance_id=instance_id,
        )
        state.last_heartbeat_at = _as_utc(now)
        self.session.flush()
        return state

    def mark_cycle_started(
        self,
        *,
        worker_name: str,
        instance_id: UUID,
        now: datetime,
    ) -> WorkerRuntimeState:
        state = self._owned_running_state(
            worker_name=worker_name,
            instance_id=instance_id,
        )
        timestamp = _as_utc(now)
        state.last_heartbeat_at = timestamp
        state.last_cycle_started_at = timestamp
        state.last_cycle_finished_at = None
        state.last_cycle_status = WorkerCycleStatus.RUNNING.value
        state.message = "Ciclo de rastreo en ejecución."
        self.session.flush()
        return state

    def mark_cycle_finished(
        self,
        *,
        worker_name: str,
        instance_id: UUID,
        succeeded: bool,
        error: str | None,
        now: datetime,
    ) -> WorkerRuntimeState:
        state = self._owned_running_state(
            worker_name=worker_name,
            instance_id=instance_id,
        )
        if state.last_cycle_status != WorkerCycleStatus.RUNNING.value:
            raise RuntimeError("The worker has no active cycle to finish.")
        timestamp = _as_utc(now)
        state.last_heartbeat_at = timestamp
        state.last_cycle_finished_at = timestamp
        state.last_cycle_status = (
            WorkerCycleStatus.SUCCEEDED.value
            if succeeded
            else WorkerCycleStatus.FAILED.value
        )
        state.last_error = None if succeeded else _trimmed(error, maximum=4_000)
        state.message = (
            "Último ciclo completado correctamente."
            if succeeded
            else "El último ciclo terminó con errores; el monitor continúa activo."
        )
        self.session.flush()
        return state

    def mark_stopped(
        self,
        *,
        worker_name: str,
        instance_id: UUID,
        error: str | None,
        now: datetime,
    ) -> WorkerRuntimeState:
        state = self._owned_state(
            worker_name=worker_name,
            instance_id=instance_id,
        )
        timestamp = _as_utc(now)
        normalized_error = _trimmed(error, maximum=4_000)
        if state.last_cycle_status == WorkerCycleStatus.RUNNING.value:
            state.last_cycle_status = WorkerCycleStatus.FAILED.value
            state.last_cycle_finished_at = timestamp
            state.last_error = normalized_error or "El monitor se detuvo durante un ciclo."
        elif normalized_error is not None:
            state.last_error = normalized_error
        state.lifecycle_status = WorkerLifecycleStatus.STOPPED.value
        state.last_heartbeat_at = timestamp
        state.stopped_at = timestamp
        state.message = (
            "Monitor detenido por un error."
            if normalized_error is not None
            else "Monitor detenido correctamente."
        )
        self.session.flush()
        return state

    def _owned_running_state(
        self,
        *,
        worker_name: str,
        instance_id: UUID,
    ) -> WorkerRuntimeState:
        state = self._owned_state(
            worker_name=worker_name,
            instance_id=instance_id,
        )
        if state.lifecycle_status != WorkerLifecycleStatus.RUNNING.value:
            raise WorkerOwnershipLostError("The worker is no longer marked as running.")
        return state

    def _owned_state(
        self,
        *,
        worker_name: str,
        instance_id: UUID,
    ) -> WorkerRuntimeState:
        state = self.session.get(
            WorkerRuntimeState,
            worker_name,
            with_for_update=True,
        )
        if state is None or state.instance_id != instance_id:
            raise WorkerOwnershipLostError(
                "This process no longer owns the persisted worker state."
            )
        return state

    def active_queue_counts(self) -> dict[str, int]:
        statuses = (
            CrawlJobStatus.QUEUED,
            CrawlJobStatus.RUNNING,
            CrawlJobStatus.RETRYING,
        )
        rows = self.session.execute(
            select(CrawlJob.status, func.count(CrawlJob.id))
            .where(CrawlJob.status.in_([status.value for status in statuses]))
            .group_by(CrawlJob.status)
        )
        counts = {status.value: 0 for status in statuses}
        for raw_status, count in rows:
            status = raw_status.value if isinstance(raw_status, CrawlJobStatus) else raw_status
            counts[str(status)] = int(count)
        return counts


class WorkerWatchdogStateRepository:
    """Persist watchdog incidents and successful notification boundaries."""

    _OUTAGE_STATES = frozenset({"stale", "stopped", "unknown"})
    _VALID_STATES = frozenset({"running", "stale", "stopped", "unknown"})

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, worker_name: str) -> WorkerWatchdogState | None:
        return self.session.get(WorkerWatchdogState, worker_name)

    def observe(
        self,
        *,
        worker_name: str,
        observed_state: str,
        grace_seconds: int,
        now: datetime,
    ) -> WatchdogDecision:
        if observed_state not in self._VALID_STATES:
            raise ValueError("observed_state is not supported")
        if isinstance(grace_seconds, bool) or not 0 <= grace_seconds <= 86_400:
            raise ValueError("grace_seconds must be between 0 and 86400")
        timestamp = _as_utc(now)
        state = self.session.get(
            WorkerWatchdogState,
            worker_name,
            with_for_update=True,
        )
        if state is None:
            state = WorkerWatchdogState(
                worker_name=worker_name,
                last_observed_state=observed_state,
                last_observed_at=timestamp,
            )
            self.session.add(state)
            self.session.flush()

        state.last_observed_state = observed_state
        state.last_observed_at = timestamp
        action: WatchdogAction | None = None

        if observed_state in self._OUTAGE_STATES:
            if state.incident_id is None:
                state.incident_id = uuid4()
                state.incident_opened_at = timestamp
                state.incident_alerted_at = None
                state.last_notification_error = None
            assert state.incident_opened_at is not None
            grace_elapsed = timestamp >= state.incident_opened_at + timedelta(
                seconds=grace_seconds
            )
            if grace_elapsed and state.incident_alerted_at is None:
                action = "alert"
        elif observed_state == "running" and state.incident_id is not None:
            if state.incident_alerted_at is None:
                self._close_incident(state)
            else:
                action = "recovery"

        self.session.flush()
        return WatchdogDecision(
            action=action,
            incident_id=state.incident_id,
            incident_opened_at=state.incident_opened_at,
            observed_state=observed_state,
        )

    def record_delivery(
        self,
        *,
        worker_name: str,
        incident_id: UUID,
        action: WatchdogAction,
        sent: bool,
        error: str | None,
        now: datetime,
    ) -> None:
        state = self.session.get(
            WorkerWatchdogState,
            worker_name,
            with_for_update=True,
        )
        if state is None or state.incident_id != incident_id:
            return

        timestamp = _as_utc(now)
        if not sent:
            state.last_notification_error = _trimmed(error, maximum=1_000)
            self.session.flush()
            return

        state.last_notification_error = None
        if action == "alert":
            state.incident_alerted_at = timestamp
            state.last_alert_sent_at = timestamp
        elif action == "recovery":
            if state.incident_alerted_at is None:
                raise RuntimeError("Cannot record a recovery without a sent outage alert.")
            state.last_recovery_sent_at = timestamp
            self._close_incident(state)
        else:  # pragma: no cover - guarded by the Literal contract
            raise ValueError("action is not supported")
        self.session.flush()

    @staticmethod
    def _close_incident(state: WorkerWatchdogState) -> None:
        state.incident_id = None
        state.incident_opened_at = None
        state.incident_alerted_at = None
        state.last_notification_error = None


__all__ = [
    "WatchdogAction",
    "WatchdogDecision",
    "WorkerAlreadyRunningError",
    "WorkerOwnershipLostError",
    "WorkerRuntimeStateRepository",
    "WorkerWatchdogStateRepository",
]
