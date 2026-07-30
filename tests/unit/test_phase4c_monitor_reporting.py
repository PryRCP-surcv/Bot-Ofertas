from __future__ import annotations

from unittest.mock import Mock

import pytest

import bot_ofertas.cli as cli
from bot_ofertas.cli import _reported_cycle
from bot_ofertas.services import WorkerStatusService


def test_reported_cycle_records_success() -> None:
    worker = Mock(spec=WorkerStatusService)

    result = _reported_cycle(worker, lambda: 0)

    assert result == 0
    worker.cycle_started.assert_called_once_with()
    worker.cycle_finished.assert_called_once_with(succeeded=True, error=None)


def test_reported_cycle_records_nonzero_exit() -> None:
    worker = Mock(spec=WorkerStatusService)

    result = _reported_cycle(worker, lambda: 3)

    assert result == 3
    worker.cycle_finished.assert_called_once_with(
        succeeded=False,
        error="El ciclo terminó con código 3.",
    )


def test_reported_cycle_records_unexpected_failure() -> None:
    worker = Mock(spec=WorkerStatusService)

    with pytest.raises(RuntimeError, match="fallo controlado"):
        _reported_cycle(worker, lambda: (_ for _ in ()).throw(RuntimeError("fallo controlado")))

    worker.cycle_finished.assert_called_once_with(
        succeeded=False,
        error="RuntimeError: fallo controlado",
    )


def test_worker_reporting_registers_start_heartbeat_and_stop(monkeypatch) -> None:
    database_settings = Mock()
    engine = Mock()
    worker = Mock(spec=WorkerStatusService)
    heartbeat = Mock()
    settings_factory = Mock(return_value=database_settings)
    engine_factory = Mock(return_value=engine)
    monkeypatch.setattr(cli.DatabaseSettings, "from_env", settings_factory)
    monkeypatch.setattr(cli, "create_database_engine", engine_factory)
    monkeypatch.setattr(cli, "create_session_factory", Mock(return_value=Mock()))
    monkeypatch.setattr(cli, "WorkerStatusService", Mock(return_value=worker))
    monkeypatch.setattr(cli, "WorkerHeartbeatLoop", Mock(return_value=heartbeat))

    with cli._worker_reporting() as active_worker:  # noqa: SLF001
        assert active_worker is worker

    worker.register_start.assert_called_once_with()
    heartbeat.start.assert_called_once_with()
    heartbeat.stop.assert_called_once_with()
    worker.register_stop.assert_called_once_with(error=None)
    engine.dispose.assert_called_once_with()
    settings_factory.assert_called_once_with()
    engine_factory.assert_called_once_with(database_settings)


def test_worker_reporting_persists_terminal_error(monkeypatch) -> None:
    database_settings = Mock()
    engine = Mock()
    worker = Mock(spec=WorkerStatusService)
    heartbeat = Mock()
    settings_factory = Mock(return_value=database_settings)
    engine_factory = Mock(return_value=engine)
    monkeypatch.setattr(cli.DatabaseSettings, "from_env", settings_factory)
    monkeypatch.setattr(cli, "create_database_engine", engine_factory)
    monkeypatch.setattr(cli, "create_session_factory", Mock(return_value=Mock()))
    monkeypatch.setattr(cli, "WorkerStatusService", Mock(return_value=worker))
    monkeypatch.setattr(cli, "WorkerHeartbeatLoop", Mock(return_value=heartbeat))

    with (
        pytest.raises(RuntimeError, match="fallo final"),
        cli._worker_reporting(),  # noqa: SLF001
    ):
        raise RuntimeError("fallo final")

    worker.register_stop.assert_called_once_with(error="RuntimeError: fallo final")
    engine.dispose.assert_called_once_with()
    settings_factory.assert_called_once_with()
    engine_factory.assert_called_once_with(database_settings)
