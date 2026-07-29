"""Scrapy pipeline for durable, auditable discovery candidates."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from scrapy import signals
from scrapy.exceptions import DropItem

from bot_ofertas.storage.config import DatabaseSettings
from bot_ofertas.storage.database import (
    create_database_engine,
    create_session_factory,
    session_scope,
)
from bot_ofertas.storage.discovery import DiscoveryClaim, DiscoveryRepository
from bot_ofertas.storage.models import DiscoveryRunStatus
from bot_ofertas.storage.repositories import StoreCrawlStateRepository

_BLOCK_MARKERS = (
    "_discovery_blocked_403",
    "_discovery_blocked_429",
    "_discovery_blocked_503",
    "_discovery_html_or_captcha",
)


class PostgresDiscoveryPipeline:
    """Persist candidates and finalize the source lease exactly once."""

    def __init__(self, crawler: Any, settings: DatabaseSettings) -> None:
        self.crawler = crawler
        self.engine = create_database_engine(settings)
        self.session_factory = create_session_factory(self.engine)
        self.claim: DiscoveryClaim | None = None
        self.store_slug = ""
        self.candidate_count = 0
        self.new_count = 0
        self.duplicate_count = 0
        self.rejected_count = 0

    @classmethod
    def from_crawler(cls, crawler: Any) -> PostgresDiscoveryPipeline:
        pipeline = cls(crawler, DatabaseSettings.from_env())
        crawler.signals.connect(
            pipeline._spider_closed,
            signal=signals.spider_closed,
            weak=False,
        )
        return pipeline

    def open_spider(self) -> None:
        spider = self.crawler.spider
        try:
            self.claim = DiscoveryClaim(
                source_id=UUID(str(spider.source_id)),
                run_id=UUID(str(spider.run_id)),
                lease_token=UUID(str(spider.lease_token)),
            )
            self.store_slug = str(spider.store_slug).strip().lower()
            with session_scope(self.session_factory) as session:
                source, run = DiscoveryRepository(session).get_claim(self.claim)
                if (
                    source.store_slug != self.store_slug
                    or run.requested_by != spider.requested_by
                    or source.source_url != spider.source_url
                ):
                    raise RuntimeError("discovery claim does not match the spider")
        except Exception:
            self.engine.dispose()
            raise RuntimeError("No se pudo validar la ejecución de descubrimiento.") from None
        self.crawler.stats.set_value(
            "bot_ofertas/discovery_run_id",
            str(self.claim.run_id),
        )

    def process_item(self, item: Any) -> Any:
        if self.claim is None:
            raise DropItem("La ejecución de descubrimiento no fue inicializada.")
        self.candidate_count += 1
        try:
            if not isinstance(item, Mapping):
                raise ValueError("discovery item must be a mapping")
            store_slug = str(item.get("store_slug", "")).strip().lower()
            discovered_url = str(item.get("discovered_url", "")).strip()
            canonical_url = str(item.get("canonical_url", "")).strip()
            label = " ".join(str(item.get("label", "")).split())[:500]
            metadata = item.get("metadata", {})
            if (
                store_slug != self.store_slug
                or not discovered_url
                or not canonical_url
                or not label
                or not isinstance(metadata, dict)
            ):
                raise ValueError("discovery item does not match its source")
            with session_scope(self.session_factory) as session:
                result = DiscoveryRepository(session).record_candidate(
                    self.claim,
                    discovered_url=discovered_url,
                    canonical_url=canonical_url,
                    label=label,
                    metadata=metadata,
                )
            if result.inserted_pending:
                self.new_count += 1
            if result.duplicate:
                self.duplicate_count += 1
            return item
        except (TypeError, ValueError, RuntimeError):
            self.rejected_count += 1
            self.crawler.stats.inc_value("bot_ofertas/discovery_item_errors")
            raise DropItem("El candidato no superó la validación.") from None
        except Exception:
            self.rejected_count += 1
            self.crawler.stats.inc_value("bot_ofertas/discovery_item_errors")
            raise DropItem("No se pudo persistir el candidato.") from None

    def _spider_closed(
        self,
        spider: Any,
        reason: str,
        **_kwargs: Any,
    ) -> None:
        if self.claim is None:
            self.engine.dispose()
            return
        stats = self.crawler.stats.get_stats()
        document_count = int(
            stats.get("bot_ofertas/discovery_document_count", 0) or 0
        )
        rejected_urls = int(
            stats.get("bot_ofertas/discovery_rejected_urls", 0) or 0
        )
        duplicate_urls = int(
            stats.get("bot_ofertas/discovery_duplicate_urls", 0) or 0
        )
        rejected_count = self.rejected_count + rejected_urls
        duplicate_count = self.duplicate_count + duplicate_urls
        blocked = any(marker in reason.casefold() for marker in _BLOCK_MARKERS)
        cancelled = reason.casefold() in {"cancelled", "shutdown", "keyboard_interrupt"}
        ordinary_error = reason != "finished"
        error_count = rejected_count + (1 if ordinary_error else 0)
        if cancelled:
            status = DiscoveryRunStatus.CANCELLED
        elif blocked:
            status = DiscoveryRunStatus.BLOCKED
        elif reason == "finished" and document_count > 0 and self.candidate_count > 0:
            status = (
                DiscoveryRunStatus.PARTIAL
                if error_count
                else DiscoveryRunStatus.SUCCEEDED
            )
        elif self.candidate_count > 0:
            status = DiscoveryRunStatus.PARTIAL
        else:
            status = DiscoveryRunStatus.FAILED
            error_count = max(error_count, 1)

        next_cursor_value = stats.get("bot_ofertas/discovery_next_scan_cursor")
        next_cursor = (
            int(next_cursor_value)
            if status in {DiscoveryRunStatus.SUCCEEDED, DiscoveryRunStatus.PARTIAL}
            and next_cursor_value is not None
            else None
        )
        safe_stats = {
            "finish_reason": " ".join(reason.split())[:200],
            "selected_sitemap": str(
                stats.get("bot_ofertas/discovery_selected_sitemap", "")
            )[:4_096],
            "product_sitemap_count": int(
                stats.get("bot_ofertas/discovery_product_sitemap_count", 0) or 0
            ),
            "response_count": int(stats.get("downloader/response_count", 0) or 0),
            "rejected_urls": rejected_urls,
            "duplicate_urls": duplicate_urls,
        }
        error_code = None if status is DiscoveryRunStatus.SUCCEEDED else _error_code(
            reason,
            status=status,
        )
        error_summary = (
            None
            if status is DiscoveryRunStatus.SUCCEEDED
            else f"Motivo de cierre: {' '.join(reason.split())[:200]}."
        )
        try:
            with session_scope(self.session_factory) as session:
                if blocked:
                    StoreCrawlStateRepository(session).pause(
                        store_slug=self.store_slug,
                        reason="discovery_blocked",
                        duration=timedelta(hours=6),
                        now=datetime.now(UTC),
                        revoke_leases=True,
                    )
                DiscoveryRepository(session).complete_claim(
                    self.claim,
                    status=status,
                    document_count=document_count,
                    candidate_count=self.candidate_count,
                    new_count=self.new_count,
                    duplicate_count=duplicate_count,
                    rejected_count=rejected_count,
                    error_count=error_count,
                    stats=safe_stats,
                    next_scan_cursor=next_cursor,
                    error_code=error_code,
                    error_summary=error_summary,
                )
            self.crawler.stats.set_value(
                "bot_ofertas/discovery_status",
                status.value,
            )
            self.crawler.stats.set_value(
                "bot_ofertas/discovery_new_candidates",
                self.new_count,
            )
            self.crawler.stats.set_value(
                "bot_ofertas/discovery_duplicate_candidates",
                duplicate_count,
            )
            self.crawler.stats.set_value(
                "bot_ofertas/discovery_error_count",
                error_count,
            )
        except Exception:
            spider.logger.error("No se pudo finalizar la ejecución de descubrimiento.")
            raise RuntimeError(
                "No se pudo finalizar la ejecución de descubrimiento."
            ) from None
        finally:
            self.engine.dispose()


def _error_code(reason: str, *, status: DiscoveryRunStatus) -> str:
    if status is DiscoveryRunStatus.BLOCKED:
        return "store_blocked"
    normalized = "_".join(reason.casefold().split())
    return (normalized or "discovery_failed")[:100]


__all__ = ["PostgresDiscoveryPipeline"]
