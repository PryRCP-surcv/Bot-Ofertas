"""Scrapy pipeline that persists normalized observations and crawl metadata."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID

from scrapy import signals
from scrapy.exceptions import DropItem
from sqlalchemy import Engine

from bot_ofertas.domain import PriceObservation
from bot_ofertas.storage.config import DatabaseSettings
from bot_ofertas.storage.database import (
    create_database_engine,
    create_session_factory,
    session_scope,
)
from bot_ofertas.storage.models import CrawlRun, CrawlRunStatus
from bot_ofertas.storage.repositories import (
    CrawlRunRepository,
    PriceObservationRepository,
    StoreCrawlStateRepository,
    TrackedProductRepository,
)

PIPELINE_PATH = "bot_ofertas.crawling.pipelines.PostgresPriceObservationPipeline"
_CANCELLED_REASONS = frozenset(
    {
        "cancelled",
        "keyboard_interrupt",
        "shutdown",
    }
)
_STORE_BLOCK_PAUSE_DURATION = timedelta(hours=6)
_STORE_BLOCK_REASON_MARKERS = (
    "_blocked_http_403",
    "_blocked_http_429",
    "_blocked_http_503",
    "_html_or_captcha_detected",
)
_STORE_BLOCK_STATUS_STATS = (
    "downloader/response_status_count/403",
    "downloader/response_status_count/429",
    "downloader/response_status_count/503",
)


@dataclass(frozen=True, slots=True)
class _TargetContext:
    source_url: str
    lease_token: UUID


class PostgresPriceObservationPipeline:
    """Persist one crawl run and its normalized, append-only observations."""

    def __init__(self, crawler: Any, settings: DatabaseSettings) -> None:
        self._crawler = crawler
        self._engine: Engine = create_database_engine(settings)
        self._session_factory = create_session_factory(self._engine)
        self._run_id: UUID | None = None
        self._store_slug: str | None = None
        self._requested_target_count = 0
        self._expected_target_ids: set[UUID] = set()
        self._target_contexts: dict[UUID, _TargetContext] = {}
        self._successful_target_ids: set[UUID] = set()
        self._failed_item_target_ids: set[UUID] = set()
        self._persisted_observations = 0
        self._item_errors = 0
        self._target_configuration_errors = 0

    @classmethod
    def from_crawler(cls, crawler: Any) -> PostgresPriceObservationPipeline:
        pipeline = cls(crawler, DatabaseSettings.from_env())
        crawler.signals.connect(
            pipeline._spider_closed,
            signal=signals.spider_closed,
            weak=False,
        )
        return pipeline

    def open_spider(self) -> None:
        """Create and commit the run before the first HTTP request."""

        spider = self._crawler.spider
        self._store_slug = _spider_store_slug(spider)
        (
            self._requested_target_count,
            self._target_contexts,
            self._target_configuration_errors,
        ) = _spider_targets(spider)
        self._expected_target_ids = set(self._target_contexts)

        if self._target_configuration_errors or not self._target_contexts:
            self._engine.dispose()
            raise RuntimeError("the spider targets are incomplete or invalid")

        try:
            with session_scope(self._session_factory) as session:
                tracked_repository = TrackedProductRepository(session)
                for target_id, context in self._target_contexts.items():
                    if not tracked_repository.authorize_observation_target(
                        product_id=target_id,
                        store_slug=self._store_slug,
                        source_url=context.source_url,
                        lease_token=context.lease_token,
                        lock=True,
                    ):
                        raise RuntimeError("a crawl target does not match an active database lease")

                run = CrawlRunRepository(session).start(
                    store_slug=self._store_slug,
                    spider_name=spider.name,
                    requested_url_count=self._requested_target_count,
                    stats={"phase": "started"},
                )
                self._run_id = run.id
        except RuntimeError:
            self._engine.dispose()
            raise
        except Exception:
            self._engine.dispose()
            raise RuntimeError("No se pudieron validar los targets en PostgreSQL.") from None

        self._crawler.stats.set_value(
            "bot_ofertas/crawl_run_id",
            str(self._run_id),
        )
        if self._target_configuration_errors:
            self._crawler.stats.set_value(
                "bot_ofertas/invalid_targets",
                self._target_configuration_errors,
            )

    def process_item(self, item: Any) -> Any:
        """Validate the item as a domain object and persist it transactionally."""

        spider = self._crawler.spider
        if self._run_id is None:
            raise DropItem("La corrida no fue inicializada.")

        raw_target_id = _item_target_id(item)
        try:
            payload = dict(item)
            observation = PriceObservation(**payload)
            target_context = self._validate_observation_target(observation)
            with session_scope(self._session_factory) as session:
                if not TrackedProductRepository(session).authorize_observation_target(
                    product_id=observation.tracked_product_id,
                    store_slug=observation.store_slug,
                    source_url=observation.source_url,
                    lease_token=target_context.lease_token,
                    lock=True,
                ):
                    raise RuntimeError("the observation target lease is no longer active")
                result = PriceObservationRepository(session).save(
                    run_id=self._run_id,
                    observation=observation,
                )
            if result.inserted:
                self._persisted_observations += 1
                self._crawler.stats.inc_value("bot_ofertas/persisted_observations")
            else:
                self._crawler.stats.inc_value("bot_ofertas/duplicate_observations")
            if observation.tracked_product_id is not None:
                self._successful_target_ids.add(observation.tracked_product_id)
            return item
        except (TypeError, ValueError, RuntimeError) as exc:
            if raw_target_id is not None:
                self._failed_item_target_ids.add(raw_target_id)
            else:
                self._failed_item_target_ids.update(self._expected_target_ids)
            self._record_item_error(spider, exc)
            raise DropItem("La observación no superó la validación.") from None
        except Exception as exc:
            # Database drivers expose several exception subclasses. Keep their
            # messages out of logs because connection diagnostics can contain
            # environment-specific details.
            if raw_target_id is not None:
                self._failed_item_target_ids.add(raw_target_id)
            else:
                self._failed_item_target_ids.update(self._expected_target_ids)
            self._record_item_error(spider, exc)
            raise DropItem("No se pudo persistir la observación.") from None

    def _validate_observation_target(
        self,
        observation: PriceObservation,
    ) -> _TargetContext:
        if self._store_slug is None:
            raise RuntimeError("the crawl store was not initialized")
        if observation.store_slug != self._store_slug:
            raise ValueError("the observation belongs to a different store")
        target_id = observation.tracked_product_id
        if target_id is None:
            raise ValueError("tracked_product_id is required for scheduled crawls")
        target_context = self._target_contexts.get(target_id)
        if target_context is None:
            raise ValueError("tracked_product_id was not requested by this crawl")
        if observation.source_url != target_context.source_url:
            raise ValueError("the observation URL does not match its requested target")
        return target_context

    def _record_item_error(self, spider: Any, error: Exception) -> None:
        self._item_errors += 1
        self._crawler.stats.inc_value("bot_ofertas/item_errors")
        spider.logger.error(
            "Se descartó una observación inválida (%s).",
            type(error).__name__,
        )

    def _spider_closed(
        self,
        spider: Any,
        reason: str,
        **_kwargs: Any,
    ) -> None:
        """Finalize the run and scheduler state using Scrapy's close reason."""

        if self._run_id is None:
            self._engine.dispose()
            return

        finished_at = datetime.now(UTC)
        successful_target_ids = self._successful_target_ids - self._failed_item_target_ids
        unsuccessful_target_ids = self._expected_target_ids - successful_target_ids
        claim_completion_errors = 0

        try:
            with session_scope(self._session_factory) as session:
                if self._store_slug is None:
                    raise RuntimeError("the crawl store was not initialized")
                store_states = StoreCrawlStateRepository(session)
                # Every finalizer locks the store before any product row. A common
                # lock order prevents a pause/revocation from deadlocking another
                # worker that is completing products for the same store.
                store_states.lock_for_finalization(
                    store_slug=self._store_slug,
                    now=finished_at,
                )
                tracked_repository = TrackedProductRepository(session)
                for target_id in self._expected_target_ids:
                    succeeded = target_id in successful_target_ids
                    lease_token = self._target_contexts[target_id].lease_token
                    if not tracked_repository.complete_claim(
                        product_id=target_id,
                        token=lease_token,
                        succeeded=succeeded,
                        checked_at=finished_at,
                    ):
                        claim_completion_errors += 1

                failed_target_ids = unsuccessful_target_ids
                error_count = (
                    self._item_errors
                    + self._target_configuration_errors
                    + len(failed_target_ids)
                    + claim_completion_errors
                )
                if reason != "finished" and error_count == 0:
                    error_count = 1

                status = _crawl_status(
                    reason=reason,
                    observation_count=self._persisted_observations,
                    error_count=error_count,
                )
                self._crawler.stats.set_value(
                    "bot_ofertas/error_count",
                    error_count,
                )
                self._crawler.stats.set_value(
                    "bot_ofertas/successful_targets",
                    len(successful_target_ids),
                )
                self._crawler.stats.set_value(
                    "bot_ofertas/failed_targets",
                    len(failed_target_ids),
                )
                self._crawler.stats.set_value(
                    "bot_ofertas/claim_completion_errors",
                    claim_completion_errors,
                )
                self._crawler.stats.set_value(
                    "bot_ofertas/run_status",
                    status.value,
                )

                if _should_pause_store(
                    reason=reason,
                    stats=self._crawler.stats.get_stats(),
                ):
                    store_state = store_states.pause(
                        store_slug=self._store_slug,
                        reason=_safe_reason(reason),
                        duration=_STORE_BLOCK_PAUSE_DURATION,
                        now=finished_at,
                        revoke_leases=True,
                    )
                    self._crawler.stats.set_value(
                        "bot_ofertas/store_paused_until",
                        store_state.paused_until.isoformat(),
                    )
                elif status is CrawlRunStatus.SUCCEEDED:
                    store_states.record_success(
                        store_slug=self._store_slug,
                        now=finished_at,
                    )

                run = session.get(CrawlRun, self._run_id)
                if run is None:
                    raise RuntimeError("the crawl run no longer exists")
                CrawlRunRepository(session).finish(
                    run,
                    status=status,
                    observation_count=self._persisted_observations,
                    error_count=error_count,
                    stats=_json_safe(self._crawler.stats.get_stats()),
                    error_summary=_error_summary(
                        status=status,
                        reason=reason,
                        error_count=error_count,
                    ),
                    finished_at=finished_at,
                )
        except Exception:
            self._crawler.stats.inc_value("bot_ofertas/finalization_errors")
            spider.logger.error("No se pudo finalizar la corrida en PostgreSQL.")
            raise RuntimeError("No se pudo finalizar la corrida en PostgreSQL.") from None
        finally:
            self._engine.dispose()


def _spider_store_slug(spider: Any) -> str:
    raw_store_slug = getattr(spider, "store_slug", None)
    if not isinstance(raw_store_slug, str):
        raise RuntimeError("the spider must declare a store_slug")
    store_slug = raw_store_slug.strip().lower()
    if not store_slug:
        raise RuntimeError("the spider store_slug must not be empty")
    return store_slug


def _spider_targets(spider: Any) -> tuple[int, dict[UUID, _TargetContext], int]:
    raw_targets = getattr(spider, "targets", None)
    if raw_targets is None:
        tracked_product_id = getattr(spider, "tracked_product_id", None)
        source_url = getattr(spider, "source_url", None)
        lease_token = getattr(spider, "lease_token", None)
        raw_targets = (
            [
                {
                    "tracked_product_id": tracked_product_id,
                    "url": source_url,
                    "lease_token": lease_token,
                }
            ]
            if tracked_product_id is not None
            else []
        )

    if not isinstance(raw_targets, (list, tuple)):
        return 1, {}, 1

    target_contexts: dict[UUID, _TargetContext] = {}
    invalid_count = 0
    for target in raw_targets:
        if not isinstance(target, Mapping):
            invalid_count += 1
            continue
        try:
            target_id = UUID(str(target.get("tracked_product_id", "")).strip())
        except (AttributeError, TypeError, ValueError):
            invalid_count += 1
            continue

        source_url = target.get("url")
        if not isinstance(source_url, str) or not source_url.strip():
            invalid_count += 1
            continue

        raw_lease_token = target.get("lease_token")
        try:
            lease_token = UUID(str(raw_lease_token or "").strip())
        except (AttributeError, TypeError, ValueError):
            invalid_count += 1
            continue
        if target_id in target_contexts:
            invalid_count += 1
            continue
        target_contexts[target_id] = _TargetContext(
            source_url=source_url.strip(),
            lease_token=lease_token,
        )
    return len(raw_targets), target_contexts, invalid_count


def _item_target_id(item: Any) -> UUID | None:
    if not isinstance(item, Mapping):
        return None
    try:
        return UUID(str(item.get("tracked_product_id", "")).strip())
    except (AttributeError, TypeError, ValueError):
        return None


def _crawl_status(
    *,
    reason: str,
    observation_count: int,
    error_count: int,
) -> CrawlRunStatus:
    normalized_reason = reason.strip().casefold()
    if normalized_reason in _CANCELLED_REASONS:
        return CrawlRunStatus.CANCELLED
    if normalized_reason == "finished" and observation_count > 0 and error_count == 0:
        return CrawlRunStatus.SUCCEEDED
    if observation_count > 0:
        return CrawlRunStatus.PARTIAL
    return CrawlRunStatus.FAILED


def _error_summary(
    *,
    status: CrawlRunStatus,
    reason: str,
    error_count: int,
) -> str | None:
    if status is CrawlRunStatus.SUCCEEDED:
        return None
    return f"Motivo de cierre: {_safe_reason(reason)}; errores registrados: {error_count}."


def _safe_reason(reason: Any) -> str:
    return " ".join(str(reason).split())[:200] or "unknown"


def _should_pause_store(*, reason: str, stats: Mapping[str, Any]) -> bool:
    normalized_reason = reason.strip().casefold()
    if any(marker in normalized_reason for marker in _STORE_BLOCK_REASON_MARKERS):
        return True
    return any(int(stats.get(key, 0) or 0) > 0 for key in _STORE_BLOCK_STATUS_STATS)


def _json_safe(value: Any) -> Any:
    """Convert Scrapy stats recursively into values accepted by PostgreSQL JSONB."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat()
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, Enum):
        return _json_safe(value.value)
    if isinstance(value, (UUID, Path)):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, Mapping):
        return {str(key): _json_safe(nested_value) for key, nested_value in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    return str(value)


__all__ = [
    "PIPELINE_PATH",
    "PostgresPriceObservationPipeline",
]
