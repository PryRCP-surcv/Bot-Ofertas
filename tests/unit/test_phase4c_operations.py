from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import CheckConstraint
from sqlalchemy.orm import Session, configure_mappers

from bot_ofertas.services.operations import read_operations_snapshot
from bot_ofertas.storage.models import (
    Base,
    WorkerRuntimeState,
    WorkerWatchdogState,
)
from bot_ofertas.storage.operations import (
    WorkerAlreadyRunningError,
    WorkerOwnershipLostError,
    WorkerRuntimeStateRepository,
    WorkerWatchdogStateRepository,
)


def _state(
    *,
    now: datetime,
    lifecycle_status: str = "running",
    heartbeat_age_seconds: int = 0,
) -> WorkerRuntimeState:
    return WorkerRuntimeState(
        worker_name="monitor",
        instance_id=uuid4(),
        lifecycle_status=lifecycle_status,
        started_at=now - timedelta(hours=1),
        last_heartbeat_at=now - timedelta(seconds=heartbeat_age_seconds),
        stale_after_seconds=120,
        last_cycle_started_at=now - timedelta(minutes=2),
        last_cycle_finished_at=now - timedelta(minutes=1),
        last_cycle_status="succeeded",
        stopped_at=now if lifecycle_status == "stopped" else None,
        message="Estado persistido.",
    )


def _session_for(state: WorkerRuntimeState | None) -> Mock:
    session = Mock(spec=Session)
    session.get.return_value = state
    session.execute.return_value = []
    return session


def test_phase4c_model_registers_worker_state_constraints() -> None:
    configure_mappers()

    assert "worker_runtime_states" in Base.metadata.tables
    assert "worker_watchdog_states" in Base.metadata.tables
    names = {
        constraint.name
        for constraint in WorkerRuntimeState.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert {
        "ck_worker_runtime_states_lifecycle_status",
        "ck_worker_runtime_states_stale_after_range",
        "ck_worker_runtime_states_cycle_shape",
        "ck_worker_runtime_states_stopped_pair",
    } <= names


def test_operations_snapshot_reports_unknown_without_a_heartbeat() -> None:
    now = datetime(2026, 7, 29, 12, tzinfo=UTC)

    result = read_operations_snapshot(_session_for(None), now=now)

    assert result.worker.state == "unknown"
    assert result.worker.last_heartbeat_at is None
    assert result.worker.heartbeat_age_seconds is None
    assert result.queue.queued == 0
    assert result.checked_at == now


@pytest.mark.parametrize(
    ("lifecycle_status", "heartbeat_age", "expected"),
    [
        ("running", 15, "running"),
        ("running", 121, "stale"),
        ("stopped", 15, "stopped"),
    ],
)
def test_operations_snapshot_derives_worker_freshness(
    lifecycle_status: str,
    heartbeat_age: int,
    expected: str,
) -> None:
    now = datetime(2026, 7, 29, 12, tzinfo=UTC)
    state = _state(
        now=now,
        lifecycle_status=lifecycle_status,
        heartbeat_age_seconds=heartbeat_age,
    )
    session = _session_for(state)
    session.execute.return_value = [("queued", 2), ("running", 1)]

    result = read_operations_snapshot(session, now=now)

    assert result.worker.state == expected
    assert result.worker.heartbeat_age_seconds == heartbeat_age
    assert result.worker.last_cycle_status == "succeeded"
    assert result.queue.queued == 2
    assert result.queue.running == 1
    assert result.queue.retrying == 0


def test_repository_rejects_a_second_fresh_monitor() -> None:
    now = datetime(2026, 7, 29, 12, tzinfo=UTC)
    current = _state(now=now)
    repository = WorkerRuntimeStateRepository(_session_for(current))

    with pytest.raises(WorkerAlreadyRunningError, match="already reporting"):
        repository.register_start(
            worker_name="monitor",
            instance_id=uuid4(),
            stale_after_seconds=120,
            now=now,
        )


def test_repository_records_cycle_failure_and_graceful_stop() -> None:
    now = datetime(2026, 7, 29, 12, tzinfo=UTC)
    state = _state(now=now)
    state.last_cycle_started_at = None
    state.last_cycle_finished_at = None
    state.last_cycle_status = None
    session = _session_for(state)
    repository = WorkerRuntimeStateRepository(session)

    repository.mark_cycle_started(
        worker_name="monitor",
        instance_id=state.instance_id,
        now=now,
    )
    repository.mark_cycle_finished(
        worker_name="monitor",
        instance_id=state.instance_id,
        succeeded=False,
        error="fallo controlado",
        now=now + timedelta(seconds=10),
    )
    repository.mark_stopped(
        worker_name="monitor",
        instance_id=state.instance_id,
        error=None,
        now=now + timedelta(seconds=20),
    )

    assert state.lifecycle_status == "stopped"
    assert state.last_cycle_status == "failed"
    assert state.last_error == "fallo controlado"
    assert state.stopped_at == now + timedelta(seconds=20)
    assert state.message == "Monitor detenido correctamente."


def test_repository_rejects_updates_from_a_superseded_instance() -> None:
    now = datetime(2026, 7, 29, 12, tzinfo=UTC)
    state = _state(now=now)
    repository = WorkerRuntimeStateRepository(_session_for(state))

    with pytest.raises(WorkerOwnershipLostError, match="no longer owns"):
        repository.heartbeat(
            worker_name="monitor",
            instance_id=uuid4(),
            now=now,
        )


def test_watchdog_repository_deduplicates_alert_and_recovery() -> None:
    now = datetime(2026, 7, 29, 12, tzinfo=UTC)
    state = WorkerWatchdogState(
        worker_name="monitor",
        last_observed_state="running",
        last_observed_at=now,
    )
    session = Mock(spec=Session)
    session.get.return_value = state
    repository = WorkerWatchdogStateRepository(session)

    opening = repository.observe(
        worker_name="monitor",
        observed_state="stale",
        grace_seconds=60,
        now=now,
    )
    alert = repository.observe(
        worker_name="monitor",
        observed_state="stopped",
        grace_seconds=60,
        now=now + timedelta(seconds=61),
    )
    assert opening.action is None
    assert alert.action == "alert"
    assert alert.incident_id is not None

    repository.record_delivery(
        worker_name="monitor",
        incident_id=alert.incident_id,
        action="alert",
        sent=True,
        error=None,
        now=now + timedelta(seconds=62),
    )
    duplicate = repository.observe(
        worker_name="monitor",
        observed_state="stale",
        grace_seconds=60,
        now=now + timedelta(seconds=120),
    )
    recovery = repository.observe(
        worker_name="monitor",
        observed_state="running",
        grace_seconds=60,
        now=now + timedelta(seconds=121),
    )
    assert duplicate.action is None
    assert recovery.action == "recovery"

    repository.record_delivery(
        worker_name="monitor",
        incident_id=alert.incident_id,
        action="recovery",
        sent=True,
        error=None,
        now=now + timedelta(seconds=122),
    )
    healthy_again = repository.observe(
        worker_name="monitor",
        observed_state="running",
        grace_seconds=60,
        now=now + timedelta(seconds=180),
    )
    assert healthy_again.action is None
    assert state.incident_id is None
    assert state.last_alert_sent_at == now + timedelta(seconds=62)
    assert state.last_recovery_sent_at == now + timedelta(seconds=122)


def test_watchdog_treats_never_started_worker_as_outage_after_grace() -> None:
    now = datetime.now(UTC)
    state = WorkerWatchdogState(
        worker_name="monitor",
        last_observed_state="unknown",
        last_observed_at=now,
    )
    session = _session_for(state)
    repository = WorkerWatchdogStateRepository(session)

    opening = repository.observe(
        worker_name="monitor",
        observed_state="unknown",
        grace_seconds=60,
        now=now,
    )
    alert = repository.observe(
        worker_name="monitor",
        observed_state="unknown",
        grace_seconds=60,
        now=now + timedelta(seconds=61),
    )

    assert opening.action is None
    assert alert.action == "alert"
