from __future__ import annotations

import argparse
from datetime import UTC, datetime
from uuid import uuid4

import bot_ofertas.cli as cli
from bot_ofertas.storage.models import CrawlJobStatus


def test_cycle_runs_an_admin_job_in_one_crawler_execution(
    monkeypatch,
) -> None:
    claim = cli._ClaimedCrawlJob(  # noqa: SLF001
        job_id=uuid4(),
        lease_token=uuid4(),
        claimed_at=datetime.now(UTC),
    )
    product_ids = (uuid4(), uuid4())
    crawl_arguments = []
    finalized = []

    monkeypatch.setattr(
        cli,
        "_claim_admin_crawl_jobs",
        lambda *, limit: [claim],
    )
    monkeypatch.setattr(
        cli,
        "_prepare_admin_crawl_job",
        lambda _claim: product_ids,
    )
    monkeypatch.setattr(
        cli,
        "_execute_crawl",
        lambda args: crawl_arguments.append(args)
        or cli._CrawlExecution(  # noqa: SLF001
            status=0,
            attempted_product_ids=frozenset(product_ids),
            run_by_product={},
        ),
    )

    def finalize(
        _claim,
        *,
        execution_error: bool,
        attempted_product_ids,
        run_by_product,
    ):
        finalized.append(
            (execution_error, attempted_product_ids, run_by_product)
        )
        return CrawlJobStatus.SUCCEEDED

    monkeypatch.setattr(cli, "_finalize_admin_crawl_job", finalize)

    result = cli._crawl(  # noqa: SLF001
        argparse.Namespace(
            force=False,
            limit=20,
            process_admin_jobs=True,
        )
    )

    assert result == 0
    assert len(crawl_arguments) == 1
    assert crawl_arguments[0].force is False
    assert crawl_arguments[0].product_ids == set(product_ids)
    assert finalized == [(False, frozenset(product_ids), {})]


def test_admin_job_worker_fences_and_records_unexpected_crawl_failure(
    monkeypatch,
) -> None:
    claim = cli._ClaimedCrawlJob(  # noqa: SLF001
        job_id=uuid4(),
        lease_token=uuid4(),
        claimed_at=datetime.now(UTC),
    )
    finalized: list[bool] = []

    monkeypatch.setattr(
        cli,
        "_claim_admin_crawl_jobs",
        lambda *, limit: [claim],
    )
    monkeypatch.setattr(
        cli,
        "_prepare_admin_crawl_job",
        lambda _claim: (uuid4(),),
    )
    monkeypatch.setattr(
        cli,
        "_execute_crawl",
        lambda _args: (_ for _ in ()).throw(RuntimeError("private detail")),
    )

    def finalize(
        _claim,
        *,
        execution_error: bool,
        attempted_product_ids,
        run_by_product,
    ):
        finalized.append(execution_error)
        assert attempted_product_ids == frozenset()
        assert run_by_product == {}
        return CrawlJobStatus.FAILED

    monkeypatch.setattr(cli, "_finalize_admin_crawl_job", finalize)

    result = cli._crawl(  # noqa: SLF001
        argparse.Namespace(
            force=False,
            limit=20,
            process_admin_jobs=True,
        )
    )

    assert result == 1
    assert finalized == [True]
