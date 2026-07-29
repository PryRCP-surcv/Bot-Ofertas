from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from bot_ofertas.api.app import create_app
from bot_ofertas.api.settings import ApiSettings
from bot_ofertas.notifications import NotificationResult, NotificationStatus
from bot_ofertas.services.watchdog import WorkerWatchdogService
from bot_ofertas.storage import DatabaseSettings, create_database_engine
from bot_ofertas.storage.operations import (
    WorkerRuntimeStateRepository,
    WorkerWatchdogStateRepository,
)
from bot_ofertas.stores import build_store_registry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_POSTGRES_TESTS") != "1",
        reason="define RUN_POSTGRES_TESTS=1 para usar PostgreSQL local",
    ),
]

_TOKEN = "phase4c-integration-admin-token-0001"


class RecordingOperationalNotifier:
    enabled = True

    def __init__(self, status: NotificationStatus = NotificationStatus.SENT) -> None:
        self.status = status
        self.messages: list[str] = []

    def send_text(self, message: str) -> NotificationResult:
        self.messages.append(message)
        return NotificationResult(
            channel="telegram",
            status=self.status,
            detail=(
                "Telegram credentials are not configured"
                if self.status is NotificationStatus.DISABLED
                else None
            ),
        )


def test_operations_status_is_protected_and_derives_freshness() -> None:
    engine = create_database_engine(DatabaseSettings.from_env())
    connection = engine.connect()
    outer_transaction = connection.begin()
    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    application = create_app(
        ApiSettings(admin_token=_TOKEN),
        session_factory=factory,
        registry=build_store_registry(include_plugins=False),
    )
    headers = {"Authorization": f"Bearer {_TOKEN}"}
    instance_id = uuid4()

    try:
        with factory.begin() as session:
            repository = WorkerRuntimeStateRepository(session)
            cycle_started_at = datetime.now(UTC)
            repository.register_start(
                worker_name="monitor",
                instance_id=instance_id,
                stale_after_seconds=120,
                now=cycle_started_at,
            )
            repository.mark_cycle_started(
                worker_name="monitor",
                instance_id=instance_id,
                now=cycle_started_at,
            )
            repository.mark_cycle_finished(
                worker_name="monitor",
                instance_id=instance_id,
                succeeded=True,
                error=None,
                now=cycle_started_at + timedelta(seconds=1),
            )

        with TestClient(application, raise_server_exceptions=False) as client:
            unauthorized = client.get("/api/v1/operations/status")
            assert unauthorized.status_code == 401

            running = client.get("/api/v1/operations/status", headers=headers)
            assert running.status_code == 200, running.text
            payload = running.json()
            assert payload["worker"]["state"] == "running"
            assert payload["worker"]["instance_id"] == str(instance_id)
            assert payload["worker"]["heartbeat_age_seconds"] >= 0
            assert payload["worker"]["last_cycle_status"] == "succeeded"
            assert set(payload["queue"]) == {"queued", "running", "retrying"}

            stale_time = datetime.now(UTC) - timedelta(minutes=10)
            with factory.begin() as session:
                state = WorkerRuntimeStateRepository(session).get("monitor")
                assert state is not None
                state.started_at = stale_time - timedelta(minutes=1)
                state.last_heartbeat_at = stale_time

            stale = client.get("/api/v1/operations/status", headers=headers)
            assert stale.status_code == 200, stale.text
            assert stale.json()["worker"]["state"] == "stale"

            with factory.begin() as session:
                WorkerRuntimeStateRepository(session).mark_stopped(
                    worker_name="monitor",
                    instance_id=instance_id,
                    error=None,
                    now=datetime.now(UTC),
                )

            stopped = client.get("/api/v1/operations/status", headers=headers)
            assert stopped.status_code == 200, stopped.text
            assert stopped.json()["worker"]["state"] == "stopped"

            ready = client.get("/health/ready")
            assert ready.status_code == 200, ready.text
    finally:
        outer_transaction.rollback()
        connection.close()
        engine.dispose()


def test_watchdog_persists_one_outage_and_one_recovery_notification() -> None:
    engine = create_database_engine(DatabaseSettings.from_env())
    connection = engine.connect()
    outer_transaction = connection.begin()
    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    now = datetime.now(UTC)
    current_time = [now]
    instance_id = uuid4()
    notifier = RecordingOperationalNotifier()

    try:
        with factory.begin() as session:
            WorkerRuntimeStateRepository(session).register_start(
                worker_name="monitor",
                instance_id=instance_id,
                stale_after_seconds=30,
                now=now - timedelta(minutes=10),
            )
        watchdog = WorkerWatchdogService(
            factory,
            notifier,
            grace_seconds=0,
            clock=lambda: current_time[0],
        )

        alert = watchdog.check_once()
        duplicate_alert = watchdog.check_once()
        assert alert.action == "alert"
        assert alert.notification_status is NotificationStatus.SENT
        assert duplicate_alert.action is None
        assert len(notifier.messages) == 1
        assert "fuera de servicio" in notifier.messages[0]

        current_time[0] = now + timedelta(seconds=1)
        with factory.begin() as session:
            WorkerRuntimeStateRepository(session).heartbeat(
                worker_name="monitor",
                instance_id=instance_id,
                now=current_time[0],
            )
        recovery = watchdog.check_once()
        duplicate_recovery = watchdog.check_once()
        assert recovery.action == "recovery"
        assert recovery.notification_status is NotificationStatus.SENT
        assert duplicate_recovery.action is None
        assert len(notifier.messages) == 2
        assert "recuperado" in notifier.messages[1]

        with factory.begin() as session:
            watchdog_state = WorkerWatchdogStateRepository(session).get("monitor")
            assert watchdog_state is not None
            assert watchdog_state.incident_id is None
            assert watchdog_state.last_alert_sent_at is not None
            assert watchdog_state.last_recovery_sent_at is not None

        current_time[0] = now + timedelta(seconds=2)
        with factory.begin() as session:
            WorkerRuntimeStateRepository(session).mark_stopped(
                worker_name="monitor",
                instance_id=instance_id,
                error=None,
                now=current_time[0],
            )
        disabled_notifier = RecordingOperationalNotifier(NotificationStatus.DISABLED)
        disabled_watchdog = WorkerWatchdogService(
            factory,
            disabled_notifier,
            grace_seconds=0,
            clock=lambda: current_time[0],
        )
        disabled = disabled_watchdog.check_once()
        assert disabled.action == "alert"
        assert disabled.notification_status is NotificationStatus.DISABLED
    finally:
        outer_transaction.rollback()
        connection.close()
        engine.dispose()
