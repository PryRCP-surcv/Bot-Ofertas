"""Persistence and concurrency controls for bounded catalogue discovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from bot_ofertas.storage.models import (
    DiscoveryCandidate,
    DiscoveryCandidateStatus,
    DiscoveryRun,
    DiscoveryRunStatus,
    DiscoverySource,
    TrackedProduct,
)
from bot_ofertas.stores import StoreRegistry


class DiscoveryLeaseLostError(RuntimeError):
    """Raised when a worker no longer owns a discovery source."""


class DiscoveryReviewError(ValueError):
    """Raised when a candidate cannot be approved or rejected safely."""


@dataclass(frozen=True, slots=True)
class DiscoveryClaim:
    source_id: UUID
    run_id: UUID
    lease_token: UUID


@dataclass(frozen=True, slots=True)
class CandidateRecordResult:
    candidate_id: UUID
    inserted_pending: bool
    duplicate: bool


class DiscoveryRepository:
    """Source synchronization, leases, candidates, and review limits."""

    MAX_CLAIM_SIZE = 10
    LEASE_DURATION = timedelta(minutes=30)

    def __init__(self, session: Session) -> None:
        self.session = session

    def sync_registry(self, registry: StoreRegistry) -> int:
        """Upsert code-reviewed sources while preserving operator enablement."""

        self.session.execute(select(func.pg_advisory_xact_lock(5_105_001)))
        changed = 0
        timestamp = datetime.now(UTC)
        for adapter in registry.adapters:
            for spec in adapter.discovery_sources:
                source = self.session.scalar(
                    select(DiscoverySource)
                    .where(
                        DiscoverySource.store_slug == adapter.slug,
                        DiscoverySource.source_key == spec.key,
                    )
                    .with_for_update()
                )
                if source is None:
                    source = DiscoverySource(
                        store_slug=adapter.slug,
                        source_key=spec.key,
                        source_type=spec.source_type,
                        source_url=spec.url,
                        enabled=spec.enabled and adapter.policy.enabled,
                        minimum_interval_minutes=spec.minimum_interval_minutes,
                        max_documents_per_run=spec.max_documents_per_run,
                        max_candidates_per_run=spec.max_candidates_per_run,
                        daily_approval_limit=spec.daily_approval_limit,
                        active_product_limit=spec.active_product_limit,
                        child_path_pattern=spec.child_path_pattern,
                        url_entry_filter=spec.url_entry_filter,
                        notes=spec.notes,
                        next_run_at=timestamp,
                    )
                    self.session.add(source)
                    changed += 1
                    continue
                desired = {
                    "source_type": spec.source_type,
                    "source_url": spec.url,
                    "minimum_interval_minutes": spec.minimum_interval_minutes,
                    "max_documents_per_run": spec.max_documents_per_run,
                    "max_candidates_per_run": spec.max_candidates_per_run,
                    "daily_approval_limit": spec.daily_approval_limit,
                    "active_product_limit": spec.active_product_limit,
                    "child_path_pattern": spec.child_path_pattern,
                    "url_entry_filter": spec.url_entry_filter,
                    "notes": spec.notes,
                }
                if any(getattr(source, key) != value for key, value in desired.items()):
                    for key, value in desired.items():
                        setattr(source, key, value)
                    source.version += 1
                    source.updated_at = timestamp
                    changed += 1
        self.session.flush()
        return changed

    def list_sources(self) -> list[DiscoverySource]:
        return list(
            self.session.scalars(
                select(DiscoverySource).order_by(
                    DiscoverySource.store_slug,
                    DiscoverySource.source_key,
                )
            )
        )

    def request_run(self, source_id: UUID, *, now: datetime | None = None) -> DiscoverySource:
        timestamp = _utc(now)
        source = self.session.scalar(
            select(DiscoverySource)
            .where(DiscoverySource.id == source_id)
            .with_for_update()
        )
        if source is None:
            raise DiscoveryReviewError("fuente de descubrimiento no encontrada")
        if not source.enabled:
            raise DiscoveryReviewError("la fuente de descubrimiento está deshabilitada")
        if (
            source.lease_token is not None
            and source.lease_expires_at is not None
            and source.lease_expires_at > timestamp
        ):
            raise DiscoveryReviewError("la fuente ya tiene una ejecución en curso")
        source.next_run_at = timestamp
        source.updated_at = timestamp
        source.version += 1
        self.session.flush()
        return source

    def claim_due(
        self,
        *,
        requested_by: str,
        limit: int = 3,
        force: bool = False,
        store_slug: str | None = None,
        source_id: UUID | None = None,
        now: datetime | None = None,
    ) -> tuple[DiscoveryClaim, ...]:
        if requested_by not in {"scheduler", "api", "cli"}:
            raise ValueError("invalid discovery requester")
        if not 1 <= limit <= self.MAX_CLAIM_SIZE:
            raise ValueError("discovery claim limit must be between 1 and 10")
        timestamp = _utc(now)
        statement = select(DiscoverySource).where(
            DiscoverySource.enabled.is_(True),
            or_(
                DiscoverySource.lease_token.is_(None),
                DiscoverySource.lease_expires_at <= timestamp,
            ),
        )
        if not force:
            statement = statement.where(DiscoverySource.next_run_at <= timestamp)
        if store_slug:
            statement = statement.where(
                DiscoverySource.store_slug == store_slug.strip().lower()
            )
        if source_id is not None:
            statement = statement.where(DiscoverySource.id == source_id)
        sources = list(
            self.session.scalars(
                statement.order_by(
                    DiscoverySource.next_run_at,
                    DiscoverySource.store_slug,
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        claims: list[DiscoveryClaim] = []
        for source in sources:
            self._expire_stale_runs(source, now=timestamp)
            token = uuid4()
            run = DiscoveryRun(
                source_id=source.id,
                store_slug=source.store_slug,
                requested_by=requested_by,
                started_at=timestamp,
            )
            self.session.add(run)
            self.session.flush()
            source.lease_token = token
            source.lease_expires_at = timestamp + self.LEASE_DURATION
            source.last_started_at = timestamp
            source.last_finished_at = None
            source.last_status = DiscoveryRunStatus.RUNNING.value
            source.last_error_code = None
            source.last_error = None
            source.updated_at = timestamp
            source.version += 1
            claims.append(
                DiscoveryClaim(
                    source_id=source.id,
                    run_id=run.id,
                    lease_token=token,
                )
            )
        self.session.flush()
        return tuple(claims)

    def get_claim(
        self,
        claim: DiscoveryClaim,
        *,
        lock: bool = False,
        now: datetime | None = None,
    ) -> tuple[DiscoverySource, DiscoveryRun]:
        timestamp = _utc(now)
        statement = select(DiscoverySource).where(
            DiscoverySource.id == claim.source_id,
            DiscoverySource.lease_token == claim.lease_token,
            DiscoverySource.lease_expires_at > timestamp,
        )
        if lock:
            statement = statement.with_for_update()
        source = self.session.scalar(statement)
        run = self.session.get(DiscoveryRun, claim.run_id)
        if (
            source is None
            or run is None
            or run.source_id != claim.source_id
            or run.status != DiscoveryRunStatus.RUNNING.value
        ):
            raise DiscoveryLeaseLostError("the discovery claim is no longer active")
        return source, run

    def record_candidate(
        self,
        claim: DiscoveryClaim,
        *,
        discovered_url: str,
        canonical_url: str,
        label: str,
        metadata: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> CandidateRecordResult:
        timestamp = _utc(now)
        source, _run = self.get_claim(claim, now=timestamp)
        fingerprint = sha256(canonical_url.encode("utf-8")).hexdigest()
        tracked_product = self.session.scalar(
            select(TrackedProduct).where(
                TrackedProduct.store_slug == source.store_slug,
                TrackedProduct.source_url == canonical_url,
            )
        )
        candidate_id = uuid4()
        initial_status = (
            DiscoveryCandidateStatus.DUPLICATE.value
            if tracked_product is not None
            else DiscoveryCandidateStatus.PENDING.value
        )
        initial_reason = "already_tracked" if tracked_product is not None else None
        inserted_id = self.session.scalar(
            insert(DiscoveryCandidate)
            .values(
                id=candidate_id,
                source_id=source.id,
                latest_run_id=claim.run_id,
                tracked_product_id=(
                    tracked_product.id if tracked_product is not None else None
                ),
                store_slug=source.store_slug,
                discovered_url=discovered_url,
                canonical_url=canonical_url,
                url_fingerprint=fingerprint,
                label=label,
                status=initial_status,
                reason=initial_reason,
                discovery_metadata=metadata or {},
                first_seen_at=timestamp,
                last_seen_at=timestamp,
                created_at=timestamp,
                updated_at=timestamp,
            )
            .on_conflict_do_nothing(
                index_elements=["store_slug", "url_fingerprint"]
            )
            .returning(DiscoveryCandidate.id)
        )
        if inserted_id is not None:
            return CandidateRecordResult(
                candidate_id=inserted_id,
                inserted_pending=tracked_product is None,
                duplicate=tracked_product is not None,
            )

        existing = self.session.scalar(
            select(DiscoveryCandidate)
            .where(
                DiscoveryCandidate.store_slug == source.store_slug,
                DiscoveryCandidate.url_fingerprint == fingerprint,
            )
            .with_for_update()
        )
        if existing is None:  # pragma: no cover - conflict invariant
            raise RuntimeError("candidate conflict was not readable")
        existing.latest_run_id = claim.run_id
        existing.source_id = source.id
        existing.discovered_url = discovered_url
        existing.last_seen_at = timestamp
        existing.updated_at = timestamp
        if tracked_product is not None and existing.status != DiscoveryCandidateStatus.APPROVED:
            existing.status = DiscoveryCandidateStatus.DUPLICATE.value
            existing.reason = "already_tracked"
            existing.tracked_product_id = tracked_product.id
            existing.version += 1
        self.session.flush()
        return CandidateRecordResult(
            candidate_id=existing.id,
            inserted_pending=False,
            duplicate=True,
        )

    def complete_claim(
        self,
        claim: DiscoveryClaim,
        *,
        status: DiscoveryRunStatus,
        document_count: int,
        candidate_count: int,
        new_count: int,
        duplicate_count: int,
        rejected_count: int,
        error_count: int,
        stats: dict[str, Any],
        next_scan_cursor: int | None,
        error_code: str | None = None,
        error_summary: str | None = None,
        now: datetime | None = None,
    ) -> DiscoveryRun:
        if status is DiscoveryRunStatus.RUNNING:
            raise ValueError("a discovery run cannot finish as running")
        timestamp = _utc(now)
        source, run = self.get_claim(claim, lock=True, now=timestamp)
        run.status = status.value
        run.document_count = document_count
        run.candidate_count = candidate_count
        run.new_count = new_count
        run.duplicate_count = duplicate_count
        run.rejected_count = rejected_count
        run.error_count = error_count
        run.error_code = _safe_optional(error_code, 100)
        run.error_summary = _safe_optional(error_summary, 1_000)
        run.stats = stats
        run.finished_at = timestamp
        source.last_status = status.value
        source.last_finished_at = timestamp
        source.last_error_code = run.error_code
        source.last_error = run.error_summary
        source.next_run_at = timestamp + timedelta(
            minutes=source.minimum_interval_minutes
        )
        if next_scan_cursor is not None and next_scan_cursor >= 0:
            source.scan_cursor = next_scan_cursor
        source.lease_token = None
        source.lease_expires_at = None
        source.updated_at = timestamp
        source.version += 1
        self.session.flush()
        return run

    def fail_claim_if_owned(
        self,
        claim: DiscoveryClaim,
        *,
        error_code: str,
        error_summary: str,
        now: datetime | None = None,
    ) -> bool:
        timestamp = _utc(now)
        source = self.session.scalar(
            select(DiscoverySource)
            .where(
                DiscoverySource.id == claim.source_id,
                DiscoverySource.lease_token == claim.lease_token,
            )
            .with_for_update()
        )
        run = self.session.get(DiscoveryRun, claim.run_id)
        if source is None or run is None or run.status != DiscoveryRunStatus.RUNNING.value:
            return False
        run.status = DiscoveryRunStatus.FAILED.value
        run.error_count = max(run.error_count, 1)
        run.error_code = _safe_optional(error_code, 100)
        run.error_summary = _safe_optional(error_summary, 1_000)
        run.finished_at = timestamp
        source.last_status = DiscoveryRunStatus.FAILED.value
        source.last_finished_at = timestamp
        source.last_error_code = run.error_code
        source.last_error = run.error_summary
        source.next_run_at = timestamp + timedelta(
            minutes=source.minimum_interval_minutes
        )
        source.lease_token = None
        source.lease_expires_at = None
        source.updated_at = timestamp
        source.version += 1
        self.session.flush()
        return True

    def approve_candidate(
        self,
        candidate_id: UUID,
        *,
        reviewed_by: str,
        registry: StoreRegistry,
        label: str | None = None,
        now: datetime | None = None,
    ) -> DiscoveryCandidate:
        timestamp = _utc(now)
        candidate = self._reviewable_candidate(candidate_id)
        source = self.session.scalar(
            select(DiscoverySource)
            .where(DiscoverySource.id == candidate.source_id)
            .with_for_update()
        )
        if source is None:  # pragma: no cover - foreign key invariant
            raise DiscoveryReviewError("la fuente ya no existe")
        adapter, canonical_url = registry.resolve(candidate.canonical_url)
        if adapter.slug != candidate.store_slug or canonical_url != candidate.canonical_url:
            raise DiscoveryReviewError("la URL candidata ya no cumple el adaptador")

        existing = self.session.scalar(
            select(TrackedProduct).where(
                TrackedProduct.store_slug == candidate.store_slug,
                TrackedProduct.source_url == candidate.canonical_url,
            )
        )
        if existing is not None:
            candidate.status = DiscoveryCandidateStatus.DUPLICATE.value
            candidate.reason = "already_tracked"
            candidate.tracked_product_id = existing.id
            self._set_review(candidate, reviewed_by=reviewed_by, now=timestamp)
            return candidate

        utc_day = timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
        approved_today = self.session.scalar(
            select(func.count(DiscoveryCandidate.id)).where(
                DiscoveryCandidate.store_slug == candidate.store_slug,
                DiscoveryCandidate.status == DiscoveryCandidateStatus.APPROVED.value,
                DiscoveryCandidate.reviewed_at >= utc_day,
            )
        )
        if int(approved_today or 0) >= source.daily_approval_limit:
            raise DiscoveryReviewError(
                "se alcanzó el límite diario de aprobaciones de esta tienda"
            )
        active_products = self.session.scalar(
            select(func.count(TrackedProduct.id)).where(
                TrackedProduct.store_slug == candidate.store_slug,
                TrackedProduct.active.is_(True),
                TrackedProduct.archived_at.is_(None),
            )
        )
        if int(active_products or 0) >= source.active_product_limit:
            raise DiscoveryReviewError(
                "se alcanzó el límite de productos activos de esta tienda"
            )

        final_label = " ".join((label or candidate.label).split())[:500]
        if not final_label:
            raise DiscoveryReviewError("el producto requiere una etiqueta")
        product = TrackedProduct(
            store_slug=candidate.store_slug,
            source_url=candidate.canonical_url,
            label=final_label,
            expected_variant={},
            expected_is_accessory=False,
            check_interval_minutes=max(60, adapter.policy.minimum_interval_minutes),
            active=True,
        )
        self.session.add(product)
        self.session.flush()
        candidate.label = final_label
        candidate.status = DiscoveryCandidateStatus.APPROVED.value
        candidate.reason = "approved_for_monitoring"
        candidate.tracked_product_id = product.id
        self._set_review(candidate, reviewed_by=reviewed_by, now=timestamp)
        return candidate

    def reject_candidate(
        self,
        candidate_id: UUID,
        *,
        reviewed_by: str,
        reason: str,
        now: datetime | None = None,
    ) -> DiscoveryCandidate:
        timestamp = _utc(now)
        candidate = self._reviewable_candidate(candidate_id)
        normalized_reason = " ".join(reason.split())[:500]
        if not normalized_reason:
            raise DiscoveryReviewError("el rechazo requiere un motivo")
        candidate.status = DiscoveryCandidateStatus.REJECTED.value
        candidate.reason = normalized_reason
        candidate.tracked_product_id = None
        self._set_review(candidate, reviewed_by=reviewed_by, now=timestamp)
        return candidate

    def _reviewable_candidate(self, candidate_id: UUID) -> DiscoveryCandidate:
        candidate = self.session.scalar(
            select(DiscoveryCandidate)
            .where(DiscoveryCandidate.id == candidate_id)
            .with_for_update()
        )
        if candidate is None:
            raise DiscoveryReviewError("candidato de descubrimiento no encontrado")
        if candidate.status != DiscoveryCandidateStatus.PENDING.value:
            raise DiscoveryReviewError(
                "solo se pueden revisar candidatos pendientes"
            )
        return candidate

    def _set_review(
        self,
        candidate: DiscoveryCandidate,
        *,
        reviewed_by: str,
        now: datetime,
    ) -> None:
        reviewer = " ".join(reviewed_by.split())[:200]
        if not reviewer:
            raise DiscoveryReviewError("reviewed_by must not be empty")
        candidate.reviewed_by = reviewer
        candidate.reviewed_at = now
        candidate.updated_at = now
        candidate.version += 1
        self.session.flush()

    def _expire_stale_runs(self, source: DiscoverySource, *, now: datetime) -> None:
        stale_runs = list(
            self.session.scalars(
                select(DiscoveryRun)
                .where(
                    DiscoveryRun.source_id == source.id,
                    DiscoveryRun.status == DiscoveryRunStatus.RUNNING.value,
                )
                .with_for_update()
            )
        )
        for run in stale_runs:
            run.status = DiscoveryRunStatus.FAILED.value
            run.error_count = max(run.error_count, 1)
            run.error_code = "lease_expired"
            run.error_summary = "La ejecución anterior perdió su lease."
            run.finished_at = now


def _safe_optional(value: str | None, maximum: int) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())[:maximum]
    return normalized or None


def _utc(value: datetime | None) -> datetime:
    timestamp = value or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return timestamp.astimezone(UTC)


__all__ = [
    "CandidateRecordResult",
    "DiscoveryClaim",
    "DiscoveryLeaseLostError",
    "DiscoveryRepository",
    "DiscoveryReviewError",
]
