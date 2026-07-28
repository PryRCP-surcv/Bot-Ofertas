import signal
import threading

from bot_ofertas.scheduling import LocalScheduler


def test_stop_sets_injected_event() -> None:
    stop_event = threading.Event()
    scheduler = LocalScheduler(lambda: None, 60, stop_event=stop_event)

    scheduler.stop()

    assert stop_event.is_set()


def test_signal_handler_requests_cooperative_stop() -> None:
    stop_event = threading.Event()
    scheduler = LocalScheduler(lambda: None, 60, stop_event=stop_event)

    scheduler.handle_stop_signal(signal.SIGTERM, None)

    assert stop_event.is_set()


def test_run_restores_process_signal_handlers() -> None:
    previous_sigint = signal.getsignal(signal.SIGINT)
    previous_sigterm = signal.getsignal(signal.SIGTERM)
    scheduler = LocalScheduler(lambda: None, 60)

    scheduler.run_once()

    assert signal.getsignal(signal.SIGINT) == previous_sigint
    assert signal.getsignal(signal.SIGTERM) == previous_sigterm
