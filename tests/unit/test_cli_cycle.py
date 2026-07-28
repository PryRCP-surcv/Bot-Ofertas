import argparse

import bot_ofertas.cli as cli


def test_cycle_isolates_stage_failure_and_still_dispatches_notifications(
    monkeypatch,
    capsys,
) -> None:
    calls: list[str] = []

    def failing_crawl(_args: argparse.Namespace) -> int:
        calls.append("crawl")
        raise RuntimeError("fallo controlado")

    def analyze(_limit: int) -> int:
        calls.append("analyze")
        return 0

    def notify(_limit: int) -> int:
        calls.append("notify")
        return 0

    monkeypatch.setattr(cli, "_crawl", failing_crawl)
    monkeypatch.setattr(cli, "_analyze", analyze)
    monkeypatch.setattr(cli, "_notify", notify)

    result = cli._cycle(  # noqa: SLF001
        argparse.Namespace(
            crawl_limit=1,
            analysis_limit=2,
            notification_limit=3,
        )
    )

    output = capsys.readouterr()
    assert result == 1
    assert calls == ["crawl", "analyze", "notify"]
    assert "Error en rastreo" in output.err
