import logging
import threading

import pytest

from bot_ofertas.scheduling import LocalScheduler, SchedulerAlreadyRunningError


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.waits: list[float] = []

    def clock(self) -> float:
        return self.now

    def wait(self, stop_event: threading.Event, timeout: float) -> bool:
        self.waits.append(timeout)
        self.now += timeout
        return stop_event.is_set()


@pytest.mark.parametrize("interval", [0, -1, float("inf"), float("-inf"), float("nan"), True])
def test_interval_must_be_positive_and_finite(interval: float) -> None:
    with pytest.raises(ValueError, match="finite number greater than zero"):
        LocalScheduler(lambda: None, interval)


def test_run_once_executes_immediately_without_waiting() -> None:
    fake_time = FakeTime()
    calls: list[float] = []
    scheduler = LocalScheduler(
        lambda: calls.append(fake_time.clock()),
        60,
        clock=fake_time.clock,
        wait=fake_time.wait,
        handle_signals=False,
    )

    scheduler.run_once()

    assert calls == [0.0]
    assert fake_time.waits == []
    assert scheduler.is_running is False


def test_recurring_loop_runs_immediately_then_at_interval() -> None:
    fake_time = FakeTime()
    stop_event = threading.Event()
    calls: list[float] = []

    def cycle() -> None:
        calls.append(fake_time.clock())
        if len(calls) == 3:
            stop_event.set()

    LocalScheduler(
        cycle,
        30,
        stop_event=stop_event,
        clock=fake_time.clock,
        wait=fake_time.wait,
        handle_signals=False,
    ).run()

    assert calls == [0.0, 30.0, 60.0]
    assert fake_time.waits == [30.0, 30.0]


def test_long_cycle_skips_missed_slots_without_overlap() -> None:
    fake_time = FakeTime()
    stop_event = threading.Event()
    calls: list[float] = []
    active_cycles = 0

    def slow_cycle() -> None:
        nonlocal active_cycles
        active_cycles += 1
        assert active_cycles == 1
        calls.append(fake_time.clock())
        fake_time.now += 25
        active_cycles -= 1
        if len(calls) == 2:
            stop_event.set()

    LocalScheduler(
        slow_cycle,
        10,
        stop_event=stop_event,
        clock=fake_time.clock,
        wait=fake_time.wait,
        handle_signals=False,
    ).run()

    assert calls == [0.0, 30.0]
    assert fake_time.waits == [5.0]


def test_cycle_error_is_logged_and_recurring_loop_continues(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_time = FakeTime()
    stop_event = threading.Event()
    calls = 0

    def unreliable_cycle() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary failure")
        stop_event.set()

    with caplog.at_level(logging.ERROR):
        LocalScheduler(
            unreliable_cycle,
            5,
            stop_event=stop_event,
            clock=fake_time.clock,
            wait=fake_time.wait,
            handle_signals=False,
        ).run()

    assert calls == 2
    assert "Scheduled cycle failed; the scheduler will continue." in caplog.text
    assert "temporary failure" in caplog.text


def test_same_scheduler_cannot_run_concurrently() -> None:
    scheduler = LocalScheduler(lambda: None, 1, handle_signals=False)
    assert scheduler._run_lock.acquire(blocking=False)  # noqa: SLF001
    try:
        with pytest.raises(SchedulerAlreadyRunningError, match="already running"):
            scheduler.run_once()
    finally:
        scheduler._run_lock.release()  # noqa: SLF001
