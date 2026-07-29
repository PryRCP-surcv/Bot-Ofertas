"""Operational heartbeat reporting and read models for the local monitor."""

from __future__ import annotations

import logging
import math
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from bot_ofertas.storage.database import session_scope
from bot_ofertas.storage.models import (
    WorkerLifecycleStatus,
    WorkerRuntimeState,
    utc_now,
)
from bot_ofertas.storage.operations import (
    WorkerOwnershipLostError,
    WorkerRuntimeStateRepository,
)

LOGGER = logging.getLogger(__name__)
WorkerState = Literal["running", "stale", "stopped", "unknown"]


@dataclass(frozen=True, slots=True)
class WorkerOperationalSnapshot:
    state: WorkerState
    instance_id: UUID | None
    started_at: datetime | None
    last_heartbeat_at: datetime | None
    heartbeat_age_seconds: int | None
    stale_after_seconds: int | None
    last_cycle_started_at: datetime | None
    last_cycle_finished_at: datetime | None
    last_cycle_status: str | None
    last_error: str | None
    message: str


@dataclass(frozen=True, slots=True)
class QueueOperationalSnapshot:
    queued: int
    running: int
    retrying: int


@dataclass(frozen=True, slots=True)
class OperationsSnapshot:
    worker: WorkerOperationalSnapshot
    queue: QueueOperationalSnapshot
    checked_at: datetime


def read_operations_snapshot(
    session: Session,
    *,
    now: datetime | None = None,
    worker_name: str = "monitor",
) -> OperationsSnapshot:
    """Read worker freshness and active queue counts in one transaction."""

    timestamp = _normalized_utc(now or utc_now())
    repository = WorkerRuntimeStateRepository(session)
    state = repository.get(worker_name)
    queue_counts = repository.active_queue_counts()
    return OperationsSnapshot(
        worker=_worker_snapshot(state, now=timestamp),
        queue=QueueOperationalSnapshot(
            queued=queue_counts["queued"],
            running=queue_counts["running"],
            retrying=queue_counts["retrying"],
        ),
        checked_at=timestamp,
    )


def _worker_snapshot(
    state: WorkerRuntimeState | None,
    *,
    now: datetime,
) -> WorkerOperationalSnapshot:
    if state is None:
        return WorkerOperationalSnapshot(
            state="unknown",
            instance_id=None,
            started_at=None,
            last_heartbeat_at=None,
            heartbeat_age_seconds=None,
            stale_after_seconds=None,
            last_cycle_started_at=None,
            last_cycle_finished_at=None,
            last_cycle_status=None,
            last_error=None,
            message="El monitor aún no ha registrado actividad.",
        )

    heartbeat = _normalized_utc(state.last_heartbeat_at)
    heartbeat_age = max(0, int((now - heartbeat).total_seconds()))
    if state.lifecycle_status == WorkerLifecycleStatus.STOPPED.value:
        effective_state: WorkerState = "stopped"
        message = state.message or "El monitor está detenido."
    elif heartbeat_age > state.stale_after_seconds:
        effective_state = "stale"
        message = (
            "El monitor figura iniciado, pero dejó de enviar señales dentro "
            "del tiempo esperado."
        )
    else:
        effective_state = "running"
        message = state.message or "El monitor está activo."

    return WorkerOperationalSnapshot(
        state=effective_state,
        instance_id=state.instance_id,
        started_at=state.started_at,
        last_heartbeat_at=state.last_heartbeat_at,
        heartbeat_age_seconds=heartbeat_age,
        stale_after_seconds=state.stale_after_seconds,
        last_cycle_started_at=state.last_cycle_started_at,
        last_cycle_finished_at=state.last_cycle_finished_at,
        last_cycle_status=state.last_cycle_status,
        last_error=state.last_error,
        message=message,
    )


def _normalized_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class WorkerStatusService:
    """Persist lifecycle events using short, independent transactions."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        worker_name: str = "monitor",
        instance_id: UUID | None = None,
        stale_after_seconds: int = 120,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.session_factory = session_factory
        self.worker_name = worker_name
        self.instance_id = instance_id or uuid4()
        self.stale_after_seconds = stale_after_seconds
        self.clock = clock

    def register_start(self) -> None:
        with session_scope(self.session_factory) as session:
            WorkerRuntimeStateRepository(session).register_start(
                worker_name=self.worker_name,
                instance_id=self.instance_id,
                stale_after_seconds=self.stale_after_seconds,
                now=self.clock(),
            )

    def heartbeat(self) -> None:
        with session_scope(self.session_factory) as session:
            WorkerRuntimeStateRepository(session).heartbeat(
                worker_name=self.worker_name,
                instance_id=self.instance_id,
                now=self.clock(),
            )

    def cycle_started(self) -> None:
        with session_scope(self.session_factory) as session:
            WorkerRuntimeStateRepository(session).mark_cycle_started(
                worker_name=self.worker_name,
                instance_id=self.instance_id,
                now=self.clock(),
            )

    def cycle_finished(
        self,
        *,
        succeeded: bool,
        error: str | None = None,
    ) -> None:
        with session_scope(self.session_factory) as session:
            WorkerRuntimeStateRepository(session).mark_cycle_finished(
                worker_name=self.worker_name,
                instance_id=self.instance_id,
                succeeded=succeeded,
                error=error,
                now=self.clock(),
            )

    def register_stop(self, *, error: str | None = None) -> None:
        with session_scope(self.session_factory) as session:
            WorkerRuntimeStateRepository(session).mark_stopped(
                worker_name=self.worker_name,
                instance_id=self.instance_id,
                error=error,
                now=self.clock(),
            )


class WorkerHeartbeatLoop:
    """Refresh a worker heartbeat while its scheduler waits or crawls."""

    def __init__(
        self,
        service: WorkerStatusService,
        interval_seconds: float = 30,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        if isinstance(interval_seconds, bool):
            raise ValueError("interval_seconds must be a finite number greater than zero")
        normalized_interval = float(interval_seconds)
        if not math.isfinite(normalized_interval) or normalized_interval <= 0:
            raise ValueError("interval_seconds must be a finite number greater than zero")
        self.service = service
        self.interval_seconds = normalized_interval
        self.logger = logger or LOGGER
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("The heartbeat loop has already been started.")
        self._thread = threading.Thread(
            target=self._run,
            name=f"{self.service.worker_name}-heartbeat",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.interval_seconds + 1.0))

    def _run(self) -> None:
        while not self._stop_event.wait(self.interval_seconds):
            try:
                self.service.heartbeat()
            except WorkerOwnershipLostError:
                self.logger.error(
                    "Worker heartbeat ownership was lost; status reporting stopped."
                )
                return
            except SQLAlchemyError:
                self.logger.exception(
                    "Worker heartbeat could not be persisted; it will be retried."
                )
            except Exception:
                self.logger.exception(
                    "Unexpected worker heartbeat failure; it will be retried."
                )


__all__ = [
    "OperationsSnapshot",
    "QueueOperationalSnapshot",
    "WorkerHeartbeatLoop",
    "WorkerOperationalSnapshot",
    "WorkerState",
    "WorkerStatusService",
    "read_operations_snapshot",
]
