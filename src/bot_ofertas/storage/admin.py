"""Durable PostgreSQL control-plane repositories for Phase 4.

HTTP handlers only enqueue work. Network crawling remains in a separate worker
that owns short database leases and must fence every mutation with its token.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, ClassVar
from uuid import UUID, uuid4

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from bot_ofertas.storage.models import (
    AdminConfigRevision,
    CrawlJob,
    CrawlJobItem,
    CrawlJobItemStatus,
    CrawlJobStatus,
    TrackedProduct,
)


class AdminStorageError(RuntimeError):
    """Base error for control-plane persistence."""


class OptimisticConcurrencyError(AdminStorageError):
    """The caller edited a stale policy or product representation."""


class IdempotencyConflictError(AdminStorageError):
    """One idempotency key was reused for a materially different command."""


class LeaseLostError(AdminStorageError):
    """A worker attempted to mutate work it no longer owns."""


def _utc(value: datetime | None = None) -> datetime:
    resolved = value or datetime.now(UTC)
    if resolved.tzinfo is None or resolved.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return resolved.astimezone(UTC)


def _text(value: str, *, name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    if len(normalized) > maximum:
        raise ValueError(f"{name} must not exceed {maximum} characters")
    return normalized


def _optional_text(value: str | None, *, name: str, maximum: int) -> str | None:
    if value is None:
        return None
    return _text(value, name=name, maximum=maximum)


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("JSON Decimal values must be finite")
        return format(value, "f")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON float values must be finite")
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return _utc(value).isoformat()
    if isinstance(value, Enum):
        return _json_value(value.value)
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            if not isinstance(raw_key, str) or not raw_key:
                raise ValueError("JSON object keys must be non-empty strings")
            normalized[raw_key] = _json_value(raw_value)
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(item) for item in value]
    raise TypeError(f"value of type {type(value).__name__} is not JSON-compatible")


def _json_object(value: Mapping[str, Any], *, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    normalized = _json_value(value)
    if not isinstance(normalized, dict):  # pragma: no cover - guarded by Mapping
        raise TypeError(f"{name} must be a JSON object")
    return normalized


def _fingerprint(value: Mapping[str, Any]) -> str:
    normalized = _json_object(value, name="fingerprint payload")
    serialized = json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _key_hash(value: str) -> str:
    normalized = _text(value, name="idempotency_key", maximum=512)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _reject_policy_secrets(policy: Mapping[str, Any]) -> None:
    """Reject obvious secret-bearing keys at every nesting level.

    The service layer still owns the positive allow-list of editable settings.
    This storage guard prevents accidental persistence of common credentials.
    """

    forbidden_exact = {
        "api_key",
        "bot_api_admin_token",
        "database_url",
        "dsn",
        "password",
        "postgres_password",
        "secret",
        "telegram_bot_token",
        "telegram_chat_id",
        "token",
    }
    forbidden_suffixes = ("_api_key", "_password", "_secret", "_token")

    def inspect(value: Any) -> None:
        if isinstance(value, Mapping):
            for raw_key, nested in value.items():
                normalized = str(raw_key).strip().casefold().replace("-", "_")
                if normalized in forbidden_exact or normalized.endswith(forbidden_suffixes):
                    raise ValueError("runtime policy must not contain secrets or credentials")
                inspect(nested)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for nested in value:
                inspect(nested)

    inspect(policy)


def _check_expected_revision(*, expected: int | None, actual: int | None) -> None:
    if expected != actual:
        raise OptimisticConcurrencyError(
            f"expected policy revision {expected!r}, current revision is {actual!r}"
        )


def _check_idempotent_fingerprint(*, stored: str, requested: str) -> None:
    if stored != requested:
        raise IdempotencyConflictError(
            "the idempotency key was already used for a different request"
        )


@dataclass(frozen=True, slots=True)
class PolicyReplaceResult:
    revision: AdminConfigRevision
    inserted: bool


class RuntimePolicyRepository:
    """Append-only, optimistic and idempotent runtime policy revisions."""

    _ADVISORY_LOCK_KEY: ClassVar[int] = 1_904_274_001

    def __init__(self, session: Session) -> None:
        self._session = session

    def current(self) -> AdminConfigRevision | None:
        return self._session.scalar(
            select(AdminConfigRevision).order_by(AdminConfigRevision.id.desc()).limit(1)
        )

    def history(
        self,
        *,
        limit: int = 50,
        before_revision: int | None = None,
    ) -> list[AdminConfigRevision]:
        if limit <= 0 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        statement: Select[tuple[AdminConfigRevision]] = select(AdminConfigRevision)
        if before_revision is not None:
            if before_revision <= 0:
                raise ValueError("before_revision must be positive")
            statement = statement.where(AdminConfigRevision.id < before_revision)
        statement = statement.order_by(AdminConfigRevision.id.desc()).limit(limit)
        return list(self._session.scalars(statement))

    def replace(
        self,
        *,
        policy: Mapping[str, Any],
        expected_revision: int | None,
        changed_by: str,
        change_reason: str | None = None,
        idempotency_key: str | None = None,
        schema_version: int = 1,
        restored_from_revision: int | None = None,
        now: datetime | None = None,
    ) -> PolicyReplaceResult:
        if not isinstance(schema_version, int) or isinstance(schema_version, bool):
            raise TypeError("schema_version must be an integer")
        if schema_version < 1:
            raise ValueError("schema_version must be positive")
        if expected_revision is not None and expected_revision <= 0:
            raise ValueError("expected_revision must be positive or None")
        actor = _text(changed_by, name="changed_by", maximum=200)
        reason = _optional_text(change_reason, name="change_reason", maximum=2_000)
        normalized_policy = _json_object(policy, name="policy")
        _reject_policy_secrets(normalized_policy)
        policy_fingerprint = _fingerprint(normalized_policy)
        idempotency_hash = _key_hash(idempotency_key) if idempotency_key is not None else None
        request_fingerprint = (
            _fingerprint(
                {
                    "policy": normalized_policy,
                    "expected_revision": expected_revision,
                    "changed_by": actor,
                    "change_reason": reason,
                    "schema_version": schema_version,
                    "restored_from_revision": restored_from_revision,
                }
            )
            if idempotency_hash is not None
            else None
        )

        if idempotency_hash is not None:
            existing = self._idempotent(idempotency_hash, request_fingerprint)
            if existing is not None:
                return PolicyReplaceResult(revision=existing, inserted=False)

        self._session.execute(
            select(func.pg_advisory_xact_lock(self._ADVISORY_LOCK_KEY))
        )
        if idempotency_hash is not None:
            existing = self._idempotent(idempotency_hash, request_fingerprint)
            if existing is not None:
                return PolicyReplaceResult(revision=existing, inserted=False)

        current = self.current()
        current_id = current.id if current is not None else None
        _check_expected_revision(expected=expected_revision, actual=current_id)

        if restored_from_revision is not None:
            if restored_from_revision <= 0:
                raise ValueError("restored_from_revision must be positive")
            restored = self._session.get(AdminConfigRevision, restored_from_revision)
            if restored is None:
                raise ValueError("restored_from_revision does not exist")

        revision = AdminConfigRevision(
            schema_version=schema_version,
            policy=normalized_policy,
            policy_fingerprint=policy_fingerprint,
            previous_revision_id=current_id,
            restored_from_revision_id=restored_from_revision,
            changed_by=actor,
            change_reason=reason,
            idempotency_key_hash=idempotency_hash,
            request_fingerprint=request_fingerprint,
            created_at=_utc(now),
        )
        self._session.add(revision)
        self._session.flush()
        return PolicyReplaceResult(revision=revision, inserted=True)

    def _idempotent(
        self,
        idempotency_hash: str,
        request_fingerprint: str | None,
    ) -> AdminConfigRevision | None:
        existing = self._session.scalar(
            select(AdminConfigRevision).where(
                AdminConfigRevision.idempotency_key_hash == idempotency_hash
            )
        )
        if existing is None:
            return None
        if request_fingerprint is None:  # pragma: no cover - internal invariant
            raise RuntimeError("request fingerprint is required for idempotency")
        _check_idempotent_fingerprint(
            stored=existing.request_fingerprint or "",
            requested=request_fingerprint,
        )
        return existing


@dataclass(frozen=True, slots=True)
class CrawlJobEnqueueResult:
    job: CrawlJob
    inserted: bool


@dataclass(frozen=True, slots=True)
class CrawlJobClaimBatch:
    token: UUID
    jobs: tuple[CrawlJob, ...]
    expires_at: datetime


class CrawlJobRepository:
    """Leased, idempotent crawl queue backed solely by PostgreSQL."""

    MAX_BATCH_SIZE: ClassVar[int] = 100
    MAX_TARGETS: ClassVar[int] = 1_000
    MAX_LEASE_DURATION: ClassVar[timedelta] = timedelta(hours=1)

    def __init__(self, session: Session) -> None:
        self._session = session

    def enqueue(
        self,
        *,
        product_ids: Sequence[UUID],
        requested_by: str,
        idempotency_key: str,
        request_payload: Mapping[str, Any] | None = None,
        request_source: str = "api",
        force: bool = False,
        priority: int = 50,
        max_attempts: int = 3,
        config_revision_id: int | None = None,
        now: datetime | None = None,
    ) -> CrawlJobEnqueueResult:
        normalized_ids = tuple(dict.fromkeys(product_ids))
        if not normalized_ids or len(normalized_ids) > self.MAX_TARGETS:
            raise ValueError(f"product_ids must contain between 1 and {self.MAX_TARGETS} IDs")
        if any(not isinstance(product_id, UUID) for product_id in normalized_ids):
            raise TypeError("every product_id must be a UUID")
        actor = _text(requested_by, name="requested_by", maximum=200)
        source = _text(request_source, name="request_source", maximum=24).lower()
        if source not in {"api", "cli", "scheduler"}:
            raise ValueError("request_source must be api, cli, or scheduler")
        if not isinstance(force, bool):
            raise TypeError("force must be a boolean")
        if not isinstance(priority, int) or isinstance(priority, bool) or not 0 <= priority <= 100:
            raise ValueError("priority must be an integer between 0 and 100")
        if (
            not isinstance(max_attempts, int)
            or isinstance(max_attempts, bool)
            or not 1 <= max_attempts <= 20
        ):
            raise ValueError("max_attempts must be an integer between 1 and 20")
        timestamp = _utc(now)
        payload = _json_object(request_payload or {}, name="request_payload")
        key_hash = _key_hash(idempotency_key)
        request_fingerprint = _fingerprint(
            {
                "product_ids": sorted(str(product_id) for product_id in normalized_ids),
                "request_payload": payload,
                "request_source": source,
                "requested_by": actor,
                "force": force,
                "priority": priority,
                "max_attempts": max_attempts,
            }
        )

        existing = self._by_idempotency(key_hash, request_fingerprint)
        if existing is not None:
            return CrawlJobEnqueueResult(job=existing, inserted=False)

        products = list(
            self._session.scalars(
                select(TrackedProduct)
                .where(
                    TrackedProduct.id.in_(normalized_ids),
                    TrackedProduct.active.is_(True),
                    TrackedProduct.archived_at.is_(None),
                )
                .order_by(TrackedProduct.id)
            )
        )
        if {product.id for product in products} != set(normalized_ids):
            raise ValueError("all requested products must exist, be active, and not be archived")

        job_id = uuid4()
        inserted_id = self._session.scalar(
            insert(CrawlJob)
            .values(
                id=job_id,
                status=CrawlJobStatus.QUEUED.value,
                request_source=source,
                requested_by=actor,
                request_payload=payload,
                idempotency_key_hash=key_hash,
                request_fingerprint=request_fingerprint,
                force=force,
                priority=priority,
                max_attempts=max_attempts,
                attempt_count=0,
                next_attempt_at=timestamp,
                config_revision_id=config_revision_id,
                result={},
                created_at=timestamp,
                updated_at=timestamp,
            )
            .on_conflict_do_nothing(constraint="uq_crawl_jobs_idempotency_hash")
            .returning(CrawlJob.id)
        )
        if inserted_id is None:
            existing = self._by_idempotency(key_hash, request_fingerprint)
            if existing is None:  # pragma: no cover - PostgreSQL conflict invariant
                raise RuntimeError("crawl job conflict occurred but no row was found")
            return CrawlJobEnqueueResult(job=existing, inserted=False)

        job = self._session.get(CrawlJob, inserted_id)
        if job is None:  # pragma: no cover - INSERT and SELECT share a transaction
            raise RuntimeError("inserted crawl job was not found")
        self._session.add_all(
            CrawlJobItem(
                job_id=job.id,
                tracked_product_id=product.id,
                store_slug=product.store_slug,
                source_url=product.source_url,
                label=product.label,
                created_at=timestamp,
                updated_at=timestamp,
            )
            for product in products
        )
        self._session.flush()
        return CrawlJobEnqueueResult(job=job, inserted=True)

    def get(self, job_id: UUID, *, lock: bool = False) -> CrawlJob | None:
        if not isinstance(job_id, UUID):
            raise TypeError("job_id must be a UUID")
        statement = select(CrawlJob).where(CrawlJob.id == job_id)
        if lock:
            statement = statement.with_for_update()
        return self._session.scalar(statement)

    def list(
        self,
        *,
        status: str | CrawlJobStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CrawlJob]:
        if limit <= 0 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        if offset < 0:
            raise ValueError("offset must not be negative")
        statement: Select[tuple[CrawlJob]] = select(CrawlJob)
        if status is not None:
            normalized_status = CrawlJobStatus(status).value
            statement = statement.where(CrawlJob.status == normalized_status)
        statement = (
            statement.order_by(CrawlJob.created_at.desc(), CrawlJob.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self._session.scalars(statement))

    def cancel(
        self,
        job_id: UUID,
        *,
        requested_by: str,
        now: datetime | None = None,
    ) -> CrawlJob | None:
        actor = _text(requested_by, name="requested_by", maximum=200)
        timestamp = _utc(now)
        job = self.get(job_id, lock=True)
        if job is None:
            return None
        if job.status in {
            CrawlJobStatus.SUCCEEDED.value,
            CrawlJobStatus.PARTIAL.value,
            CrawlJobStatus.FAILED.value,
            CrawlJobStatus.CANCELLED.value,
        }:
            return job
        job.cancel_requested_at = timestamp
        job.cancel_requested_by = actor
        job.updated_at = timestamp
        if job.status in {CrawlJobStatus.QUEUED.value, CrawlJobStatus.RETRYING.value}:
            job.status = CrawlJobStatus.CANCELLED.value
            job.finished_at = timestamp
            self._cancel_open_items(job.id, timestamp)
        self._session.flush()
        return job

    def claim_due(
        self,
        *,
        worker_id: str,
        limit: int = 10,
        lease_duration: timedelta = timedelta(minutes=15),
        now: datetime | None = None,
    ) -> CrawlJobClaimBatch:
        if limit <= 0 or limit > self.MAX_BATCH_SIZE:
            raise ValueError(f"limit must be between 1 and {self.MAX_BATCH_SIZE}")
        if lease_duration <= timedelta(0) or lease_duration > self.MAX_LEASE_DURATION:
            raise ValueError("lease_duration must be positive and at most one hour")
        worker = _text(worker_id, name="worker_id", maximum=200)
        timestamp = _utc(now)
        expires_at = timestamp + lease_duration
        token = uuid4()

        self._finalize_abandoned(timestamp)
        statement = (
            select(CrawlJob)
            .where(
                CrawlJob.cancel_requested_at.is_(None),
                CrawlJob.attempt_count < CrawlJob.max_attempts,
                or_(
                    (
                        CrawlJob.status.in_(
                            [
                                CrawlJobStatus.QUEUED.value,
                                CrawlJobStatus.RETRYING.value,
                            ]
                        )
                        & (CrawlJob.next_attempt_at <= timestamp)
                    ),
                    (
                        (CrawlJob.status == CrawlJobStatus.RUNNING.value)
                        & (CrawlJob.lease_expires_at <= timestamp)
                    ),
                ),
            )
            .order_by(
                CrawlJob.priority.desc(),
                CrawlJob.next_attempt_at.asc(),
                CrawlJob.created_at.asc(),
                CrawlJob.id.asc(),
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        jobs = tuple(self._session.scalars(statement))
        for job in jobs:
            job.status = CrawlJobStatus.RUNNING.value
            job.attempt_count += 1
            job.started_at = job.started_at or timestamp
            job.last_claimed_at = timestamp
            job.last_worker_id = worker
            job.lease_token = token
            job.lease_expires_at = expires_at
            job.updated_at = timestamp
        self._session.flush()
        return CrawlJobClaimBatch(token=token, jobs=jobs, expires_at=expires_at)

    def heartbeat(
        self,
        job_id: UUID,
        *,
        token: UUID,
        lease_duration: timedelta = timedelta(minutes=15),
        now: datetime | None = None,
    ) -> CrawlJob | None:
        if not isinstance(token, UUID):
            raise TypeError("token must be a UUID")
        if lease_duration <= timedelta(0) or lease_duration > self.MAX_LEASE_DURATION:
            raise ValueError("lease_duration must be positive and at most one hour")
        timestamp = _utc(now)
        job = self._session.scalar(
            select(CrawlJob)
            .where(
                CrawlJob.id == job_id,
                CrawlJob.status == CrawlJobStatus.RUNNING.value,
                CrawlJob.lease_token == token,
                CrawlJob.lease_expires_at > timestamp,
            )
            .with_for_update()
        )
        if job is None:
            return None
        if job.cancel_requested_at is None:
            job.lease_expires_at = timestamp + lease_duration
            job.updated_at = timestamp
            self._session.flush()
        return job

    def complete(
        self,
        job_id: UUID,
        *,
        token: UUID,
        status: str | CrawlJobStatus,
        result: Mapping[str, Any] | None = None,
        error_code: str | None = None,
        error: str | None = None,
        retry_at: datetime | None = None,
        now: datetime | None = None,
    ) -> bool:
        normalized_status = CrawlJobStatus(status)
        if normalized_status not in {
            CrawlJobStatus.RETRYING,
            CrawlJobStatus.SUCCEEDED,
            CrawlJobStatus.PARTIAL,
            CrawlJobStatus.FAILED,
            CrawlJobStatus.CANCELLED,
        }:
            raise ValueError("completion status must be retrying or terminal")
        timestamp = _utc(now)
        job = self._session.scalar(
            select(CrawlJob)
            .where(
                CrawlJob.id == job_id,
                CrawlJob.status == CrawlJobStatus.RUNNING.value,
                CrawlJob.lease_token == token,
                CrawlJob.lease_expires_at > timestamp,
            )
            .with_for_update()
        )
        if job is None:
            return False

        if job.cancel_requested_at is not None:
            normalized_status = CrawlJobStatus.CANCELLED
        if normalized_status is CrawlJobStatus.RETRYING:
            if job.attempt_count >= job.max_attempts:
                normalized_status = CrawlJobStatus.FAILED
            else:
                if retry_at is None:
                    raise ValueError("retry_at is required for retrying jobs")
                next_attempt = _utc(retry_at)
                if next_attempt <= timestamp:
                    raise ValueError("retry_at must be in the future")
                job.next_attempt_at = next_attempt

        job.status = normalized_status.value
        job.lease_token = None
        job.lease_expires_at = None
        job.last_error_code = _optional_text(
            error_code,
            name="error_code",
            maximum=100,
        )
        job.last_error = _optional_text(error, name="error", maximum=4_000)
        if result is not None:
            job.result = _json_object(result, name="result")
        job.finished_at = (
            None if normalized_status is CrawlJobStatus.RETRYING else timestamp
        )
        if normalized_status is CrawlJobStatus.CANCELLED:
            self._cancel_open_items(job.id, timestamp)
        elif normalized_status is CrawlJobStatus.FAILED:
            self._fail_open_items(
                job.id,
                timestamp,
                error_code=job.last_error_code,
                error=job.last_error,
            )
        job.updated_at = timestamp
        self._session.flush()
        return True

    def _by_idempotency(
        self,
        key_hash: str,
        request_fingerprint: str,
    ) -> CrawlJob | None:
        existing = self._session.scalar(
            select(CrawlJob).where(CrawlJob.idempotency_key_hash == key_hash)
        )
        if existing is None:
            return None
        _check_idempotent_fingerprint(
            stored=existing.request_fingerprint,
            requested=request_fingerprint,
        )
        return existing

    def _finalize_abandoned(self, timestamp: datetime) -> None:
        cancelled_ids = tuple(
            self._session.scalars(
                update(CrawlJob)
                .where(
                    CrawlJob.status == CrawlJobStatus.RUNNING.value,
                    CrawlJob.lease_expires_at <= timestamp,
                    CrawlJob.cancel_requested_at.is_not(None),
                )
                .values(
                    status=CrawlJobStatus.CANCELLED.value,
                    lease_token=None,
                    lease_expires_at=None,
                    finished_at=timestamp,
                    updated_at=timestamp,
                )
                .returning(CrawlJob.id)
            )
        )
        for job_id in cancelled_ids:
            self._cancel_open_items(job_id, timestamp)
        failed_ids = tuple(
            self._session.scalars(
                update(CrawlJob)
                .where(
                    CrawlJob.status == CrawlJobStatus.RUNNING.value,
                    CrawlJob.lease_expires_at <= timestamp,
                    CrawlJob.attempt_count >= CrawlJob.max_attempts,
                )
                .values(
                    status=CrawlJobStatus.FAILED.value,
                    lease_token=None,
                    lease_expires_at=None,
                    finished_at=timestamp,
                    last_error_code="lease_expired",
                    last_error="worker lease expired and no attempts remain",
                    updated_at=timestamp,
                )
                .returning(CrawlJob.id)
            )
        )
        for job_id in failed_ids:
            self._fail_open_items(
                job_id,
                timestamp,
                error_code="lease_expired",
                error="worker lease expired and no attempts remain",
            )

    def _cancel_open_items(self, job_id: UUID, timestamp: datetime) -> None:
        self._session.execute(
            update(CrawlJobItem)
            .where(
                CrawlJobItem.job_id == job_id,
                CrawlJobItem.status.in_(
                    [
                        CrawlJobItemStatus.QUEUED.value,
                        CrawlJobItemStatus.RUNNING.value,
                    ]
                ),
            )
            .values(
                status=CrawlJobItemStatus.CANCELLED.value,
                finished_at=timestamp,
                updated_at=timestamp,
            )
        )

    def _fail_open_items(
        self,
        job_id: UUID,
        timestamp: datetime,
        *,
        error_code: str | None,
        error: str | None,
    ) -> None:
        self._session.execute(
            update(CrawlJobItem)
            .where(
                CrawlJobItem.job_id == job_id,
                CrawlJobItem.status.in_(
                    [
                        CrawlJobItemStatus.QUEUED.value,
                        CrawlJobItemStatus.RUNNING.value,
                    ]
                ),
            )
            .values(
                status=CrawlJobItemStatus.FAILED.value,
                finished_at=timestamp,
                last_error_code=error_code,
                last_error=error,
                updated_at=timestamp,
            )
        )


__all__ = [
    "AdminStorageError",
    "CrawlJobClaimBatch",
    "CrawlJobEnqueueResult",
    "CrawlJobRepository",
    "IdempotencyConflictError",
    "LeaseLostError",
    "OptimisticConcurrencyError",
    "PolicyReplaceResult",
    "RuntimePolicyRepository",
]
