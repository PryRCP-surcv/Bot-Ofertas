"""A small, deterministic scheduler for the first deployment phase."""

from __future__ import annotations

import logging
import math
import signal
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import FrameType
from typing import Any

CycleCallback = Callable[[], Any]
Clock = Callable[[], float]
Wait = Callable[[threading.Event, float], bool]

LOGGER = logging.getLogger(__name__)


class SchedulerError(RuntimeError):
    """Base error raised by the local scheduler."""


class SchedulerAlreadyRunningError(SchedulerError):
    """Raised when the same scheduler is started more than once concurrently."""


def _wait_on_event(stop_event: threading.Event, timeout: float) -> bool:
    return stop_event.wait(timeout)


class LocalScheduler:
    """Run one synchronous callback immediately and then on a fixed cadence.

    A cycle always completes before another one can start. If a cycle lasts
    longer than the configured interval, missed slots are skipped instead of
    being replayed in a burst.
    """

    def __init__(
        self,
        cycle: CycleCallback,
        interval_seconds: float,
        *,
        stop_event: threading.Event | None = None,
        clock: Clock = time.monotonic,
        wait: Wait = _wait_on_event,
        logger: logging.Logger | None = None,
        handle_signals: bool = True,
    ) -> None:
        if not callable(cycle):
            raise TypeError("cycle must be callable.")
        if isinstance(interval_seconds, bool):
            raise ValueError("interval_seconds must be a finite number greater than zero.")
        try:
            normalized_interval = float(interval_seconds)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "interval_seconds must be a finite number greater than zero."
            ) from exc
        if not math.isfinite(normalized_interval) or normalized_interval <= 0:
            raise ValueError("interval_seconds must be a finite number greater than zero.")
        if not callable(clock):
            raise TypeError("clock must be callable.")
        if not callable(wait):
            raise TypeError("wait must be callable.")

        self.cycle = cycle
        self.interval_seconds = normalized_interval
        self.stop_event = stop_event if stop_event is not None else threading.Event()
        self.clock = clock
        self.wait = wait
        self.logger = logger if logger is not None else LOGGER
        self.handle_signals = handle_signals
        self._run_lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        """Return whether this instance currently owns its execution loop."""

        return self._run_lock.locked()

    def stop(self) -> None:
        """Request a graceful stop and wake any interval wait."""

        self.stop_event.set()

    def handle_stop_signal(
        self,
        signum: int,
        _frame: FrameType | None,
    ) -> None:
        """Translate SIGINT/SIGTERM into the same cooperative stop event."""

        try:
            signal_name = signal.Signals(signum).name
        except ValueError:
            signal_name = str(signum)
        self.logger.info("Received %s; stopping scheduler after the active cycle.", signal_name)
        self.stop()

    def run_once(self) -> None:
        """Run exactly one cycle, logging ordinary callback failures."""

        self.run(run_once=True)

    def run(self, *, run_once: bool = False) -> None:
        """Run immediately, then wait for each cadence until stopped.

        ``run_once`` executes one cycle and returns. Ordinary callback
        exceptions are logged and do not terminate a recurring loop.
        """

        if not isinstance(run_once, bool):
            raise TypeError("run_once must be a bool.")
        if not self._run_lock.acquire(blocking=False):
            raise SchedulerAlreadyRunningError("This scheduler instance is already running.")

        try:
            with self._installed_signal_handlers(enabled=self.handle_signals):
                self._run_loop(run_once=run_once)
        finally:
            self._run_lock.release()

    def _run_loop(self, *, run_once: bool) -> None:
        if self.stop_event.is_set():
            return

        next_deadline = self.clock()
        while not self.stop_event.is_set():
            delay = max(0.0, next_deadline - self.clock())
            if delay > 0 and self.wait(self.stop_event, delay):
                break
            if self.stop_event.is_set():
                break

            try:
                self.cycle()
            except Exception:
                self.logger.exception("Scheduled cycle failed; the scheduler will continue.")

            if run_once or self.stop_event.is_set():
                break

            next_deadline += self.interval_seconds
            now = self.clock()
            if next_deadline <= now:
                missed_slots = math.floor((now - next_deadline) / self.interval_seconds) + 1
                next_deadline += missed_slots * self.interval_seconds

    @contextmanager
    def _installed_signal_handlers(self, *, enabled: bool) -> Iterator[None]:
        if not enabled or threading.current_thread() is not threading.main_thread():
            yield
            return

        previous_handlers: dict[signal.Signals, signal.Handlers] = {}
        supported_signals = tuple(
            member
            for member in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None))
            if member is not None
        )
        try:
            for member in supported_signals:
                previous_handlers[member] = signal.getsignal(member)
                signal.signal(member, self.handle_stop_signal)
            yield
        finally:
            for member, previous_handler in previous_handlers.items():
                signal.signal(member, previous_handler)


__all__ = [
    "Clock",
    "CycleCallback",
    "LocalScheduler",
    "SchedulerAlreadyRunningError",
    "SchedulerError",
    "Wait",
]
