"""Transaction-aware repositories for the initial persistence model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar
from uuid import UUID, uuid4

from sqlalchemy import Integer, Select, cast, exists, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from bot_ofertas.detection import canonicalize_variant
from bot_ofertas.domain import PriceObservation
from bot_ofertas.storage.models import (
    CrawlRun,
    CrawlRunStatus,
    EquivalentProductGroup,
    EquivalentProductMembership,
    PriceObservationRecord,
    StoreCrawlState,
    TrackedProduct,
)


def _utc(value: datetime | None = None) -> datetime:
    resolved = value or datetime.now(UTC)
    if resolved.tzinfo is None or resolved.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return resolved.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class SaveObservationResult:
    observation_id: int
    inserted: bool


@dataclass(frozen=True, slots=True)
class ProductClaimBatch:
    """Products reserved atomically for one scheduler worker."""

    token: UUID
    products: tuple[TrackedProduct, ...]
    expires_at: datetime


class StoreCrawlStateRepository:
    """Manage persistent per-store pauses after blocking responses."""

    MAX_PAUSE_DURATION: ClassVar[timedelta] = timedelta(days=30)

    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _normalize_store_slug(store_slug: str) -> str:
        if not isinstance(store_slug, str):
            raise TypeError("store_slug must be a string")
        normalized = store_slug.strip().lower()
        if not normalized:
            raise ValueError("store_slug must not be empty")
        if len(normalized) > 64:
            raise ValueError("store_slug must not exceed 64 characters")
        return normalized

    def lock_for_finalization(
        self,
        *,
        store_slug: str,
        now: datetime | None = None,
    ) -> StoreCrawlState:
        """Acquire the store lock before any product locks during finalization."""

        normalized_slug = self._normalize_store_slug(store_slug)
        timestamp = _utc(now)
        self._session.execute(
            insert(StoreCrawlState)
            .values(
                store_slug=normalized_slug,
                paused_until=None,
                pause_reason=None,
                consecutive_blocks=0,
                created_at=timestamp,
                updated_at=timestamp,
            )
            .on_conflict_do_nothing(index_elements=[StoreCrawlState.store_slug])
        )
        state = self._session.scalar(
            select(StoreCrawlState)
            .where(StoreCrawlState.store_slug == normalized_slug)
            .with_for_update()
        )
        if state is None:  # pragma: no cover - insert/select occur in one transaction
            raise RuntimeError("store finalization lock could not be acquired")
        return state

    def pause(
        self,
        *,
        store_slug: str,
        reason: str,
        duration: timedelta,
        now: datetime | None = None,
        revoke_leases: bool = True,
    ) -> StoreCrawlState:
        """Pause a store, extending (never shortening) an existing pause."""

        normalized_slug = self._normalize_store_slug(store_slug)
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason must not be empty")
        if not isinstance(duration, timedelta):
            raise TypeError("duration must be a timedelta")
        if duration <= timedelta(0) or duration > self.MAX_PAUSE_DURATION:
            raise ValueError("duration must be positive and at most 30 days")
        if not isinstance(revoke_leases, bool):
            raise TypeError("revoke_leases must be a boolean")

        timestamp = _utc(now)
        proposed_until = timestamp + duration
        normalized_reason = " ".join(reason.split())[:500]
        statement = (
            insert(StoreCrawlState)
            .values(
                store_slug=normalized_slug,
                paused_until=proposed_until,
                pause_reason=normalized_reason,
                consecutive_blocks=1,
                created_at=timestamp,
                updated_at=timestamp,
            )
            .on_conflict_do_update(
                index_elements=[StoreCrawlState.store_slug],
                set_={
                    "paused_until": func.greatest(
                        func.coalesce(StoreCrawlState.paused_until, proposed_until),
                        proposed_until,
                    ),
                    "pause_reason": normalized_reason,
                    "consecutive_blocks": StoreCrawlState.consecutive_blocks + 1,
                    "updated_at": timestamp,
                },
            )
            .returning(StoreCrawlState)
        )
        state = self._session.scalar(statement.execution_options(populate_existing=True))
        if state is None:  # pragma: no cover - PostgreSQL RETURNING is deterministic
            raise RuntimeError("store pause upsert did not return a state")
        if revoke_leases:
            self._session.execute(
                update(TrackedProduct)
                .where(
                    TrackedProduct.store_slug == normalized_slug,
                    TrackedProduct.lease_token.is_not(None),
                )
                .values(
                    lease_token=None,
                    lease_expires_at=None,
                    updated_at=timestamp,
                )
            )
        self._session.flush()
        return state

    def record_success(
        self,
        *,
        store_slug: str,
        now: datetime | None = None,
    ) -> StoreCrawlState:
        """Close the circuit after a successful store request."""

        normalized_slug = self._normalize_store_slug(store_slug)
        timestamp = _utc(now)
        statement = (
            insert(StoreCrawlState)
            .values(
                store_slug=normalized_slug,
                paused_until=None,
                pause_reason=None,
                consecutive_blocks=0,
                created_at=timestamp,
                updated_at=timestamp,
            )
            .on_conflict_do_update(
                index_elements=[StoreCrawlState.store_slug],
                set_={
                    "paused_until": None,
                    "pause_reason": None,
                    "consecutive_blocks": 0,
                    "updated_at": timestamp,
                },
            )
            .returning(StoreCrawlState)
        )
        state = self._session.scalar(statement.execution_options(populate_existing=True))
        if state is None:  # pragma: no cover - PostgreSQL RETURNING is deterministic
            raise RuntimeError("store success upsert did not return a state")
        self._session.flush()
        return state

    def get(self, store_slug: str) -> StoreCrawlState | None:
        return self._session.get(
            StoreCrawlState,
            self._normalize_store_slug(store_slug),
        )

    def active_pauses(
        self,
        *,
        store_slugs: set[str] | list[str] | tuple[str, ...] | None = None,
        now: datetime | None = None,
    ) -> list[StoreCrawlState]:
        """Return stores whose circuit is still open at ``now``."""

        timestamp = _utc(now)
        statement: Select[tuple[StoreCrawlState]] = select(StoreCrawlState).where(
            StoreCrawlState.paused_until > timestamp
        )
        if store_slugs is not None:
            normalized_store_slugs = {
                self._normalize_store_slug(store_slug) for store_slug in store_slugs
            }
            if not normalized_store_slugs:
                return []
            statement = statement.where(StoreCrawlState.store_slug.in_(normalized_store_slugs))
        statement = statement.order_by(
            StoreCrawlState.paused_until.desc(),
            StoreCrawlState.store_slug.asc(),
        )
        return list(self._session.scalars(statement))


class TrackedProductRepository:
    """Persistence operations used by local or distributed product schedulers."""

    MAX_CLAIM_SIZE: ClassVar[int] = 1_000
    MAX_LEASE_DURATION: ClassVar[timedelta] = timedelta(days=1)

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(
        self,
        *,
        store_slug: str,
        source_url: str,
        label: str,
        expected_brand: str | None = None,
        expected_model: str | None = None,
        expected_variant: dict[str, str] | None = None,
        expected_is_accessory: bool = False,
        check_interval_minutes: int = 60,
        active: bool = True,
    ) -> TrackedProduct:
        if check_interval_minutes < 30:
            raise ValueError("check_interval_minutes must be at least 30")
        if not isinstance(expected_is_accessory, bool):
            raise TypeError("expected_is_accessory must be a boolean")
        if expected_variant is not None and not isinstance(expected_variant, dict):
            raise TypeError("expected_variant must be a dictionary")

        tracked_product = TrackedProduct(
            store_slug=store_slug.strip().lower(),
            source_url=source_url.strip(),
            label=label.strip(),
            expected_brand=expected_brand.strip() if expected_brand else None,
            expected_model=expected_model.strip() if expected_model else None,
            expected_variant=canonicalize_variant(expected_variant or {}),
            expected_is_accessory=expected_is_accessory,
            check_interval_minutes=check_interval_minutes,
            active=active,
        )
        if (
            not tracked_product.store_slug
            or not tracked_product.source_url
            or not tracked_product.label
        ):
            raise ValueError("store_slug, source_url, and label must not be empty")
        self._session.add(tracked_product)
        self._session.flush()
        return tracked_product

    def get(self, tracked_product_id: UUID) -> TrackedProduct | None:
        return self._session.get(TrackedProduct, tracked_product_id)

    def set_active(
        self,
        tracked_product_id: UUID,
        *,
        active: bool,
    ) -> TrackedProduct | None:
        if not isinstance(tracked_product_id, UUID):
            raise TypeError("tracked_product_id must be a UUID")
        if not isinstance(active, bool):
            raise TypeError("active must be a boolean")
        product = self._session.scalar(
            select(TrackedProduct).where(TrackedProduct.id == tracked_product_id).with_for_update()
        )
        if product is None:
            return None
        if active and product.archived_at is not None:
            raise ValueError("an archived product cannot be activated")
        product.active = active
        if not active:
            product.lease_token = None
            product.lease_expires_at = None
        product.version += 1
        product.updated_at = _utc()
        self._session.flush()
        return product

    def set_expected_variant(
        self,
        tracked_product_id: UUID,
        *,
        expected_variant: dict[str, str],
    ) -> TrackedProduct | None:
        """Set the exact variant selected by the operator."""

        if not isinstance(tracked_product_id, UUID):
            raise TypeError("tracked_product_id must be a UUID")
        if not isinstance(expected_variant, dict):
            raise TypeError("expected_variant must be a dictionary")
        normalized_variant = canonicalize_variant(expected_variant)
        if not normalized_variant:
            raise ValueError("expected_variant must not be empty")
        product = self._session.scalar(
            select(TrackedProduct).where(TrackedProduct.id == tracked_product_id).with_for_update()
        )
        if product is None:
            return None
        if product.archived_at is not None:
            raise ValueError("an archived product cannot change variant")
        product.expected_variant = normalized_variant
        product.version += 1
        product.updated_at = _utc()
        self._session.flush()
        return product

    def list_active(self, *, limit: int = 100) -> list[TrackedProduct]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        statement: Select[tuple[TrackedProduct]] = (
            select(TrackedProduct)
            .where(
                TrackedProduct.active.is_(True),
                TrackedProduct.archived_at.is_(None),
            )
            .order_by(TrackedProduct.last_checked_at.asc().nulls_first())
            .limit(limit)
        )
        return list(self._session.scalars(statement))

    def claim_due(
        self,
        *,
        limit: int = 100,
        force: bool = False,
        store_slugs: set[str] | list[str] | tuple[str, ...] | None = None,
        product_ids: set[UUID] | list[UUID] | tuple[UUID, ...] | None = None,
        minimum_interval_minutes: int | None = None,
        lease_duration: timedelta = timedelta(minutes=15),
        now: datetime | None = None,
    ) -> ProductClaimBatch:
        """Atomically reserve due products without blocking other scheduler workers.

        The caller must commit the surrounding transaction before dispatching the
        returned work so other workers can observe the lease.
        """

        if limit <= 0 or limit > self.MAX_CLAIM_SIZE:
            raise ValueError(f"limit must be between 1 and {self.MAX_CLAIM_SIZE}")
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        if lease_duration > self.MAX_LEASE_DURATION:
            raise ValueError("lease_duration must not exceed one day")
        if minimum_interval_minutes is not None and (
            not isinstance(minimum_interval_minutes, int)
            or isinstance(minimum_interval_minutes, bool)
            or minimum_interval_minutes < 30
        ):
            raise ValueError("minimum_interval_minutes must be at least 30")
        normalized_product_ids: set[UUID] | None = None
        if product_ids is not None:
            normalized_product_ids = set(product_ids)
            if any(
                not isinstance(product_id, UUID)
                for product_id in normalized_product_ids
            ):
                raise TypeError("every product_id must be a UUID")
            if not normalized_product_ids:
                return ProductClaimBatch(
                    token=uuid4(),
                    products=(),
                    expires_at=_utc(now) + lease_duration,
                )

        timestamp = _utc(now)
        expires_at = timestamp + lease_duration
        token = uuid4()

        statement: Select[tuple[TrackedProduct]] = select(TrackedProduct).where(
            TrackedProduct.active.is_(True),
            TrackedProduct.archived_at.is_(None),
            or_(
                TrackedProduct.lease_token.is_(None),
                TrackedProduct.lease_expires_at <= timestamp,
            ),
            ~exists(
                select(StoreCrawlState.store_slug).where(
                    StoreCrawlState.store_slug == TrackedProduct.store_slug,
                    StoreCrawlState.paused_until > timestamp,
                )
            ),
        )

        if store_slugs is not None:
            normalized_store_slugs = {
                store_slug.strip().lower() for store_slug in store_slugs if store_slug.strip()
            }
            if not normalized_store_slugs:
                return ProductClaimBatch(
                    token=token,
                    products=(),
                    expires_at=expires_at,
                )
            statement = statement.where(TrackedProduct.store_slug.in_(normalized_store_slugs))
        if normalized_product_ids is not None:
            statement = statement.where(TrackedProduct.id.in_(normalized_product_ids))

        if not force:
            effective_interval = TrackedProduct.check_interval_minutes
            if minimum_interval_minutes is not None:
                effective_interval = func.greatest(
                    TrackedProduct.check_interval_minutes,
                    minimum_interval_minutes,
                )
            backoff_multiplier = cast(
                func.power(
                    2,
                    func.least(TrackedProduct.consecutive_failures, 4),
                ),
                Integer,
            )
            statement = statement.where(
                or_(
                    TrackedProduct.last_checked_at.is_(None),
                    TrackedProduct.last_checked_at
                    + effective_interval * backoff_multiplier * text("INTERVAL '1 minute'")
                    <= timestamp,
                )
            )

        statement = (
            statement.order_by(
                TrackedProduct.last_checked_at.asc().nulls_first(),
                TrackedProduct.id.asc(),
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        products = tuple(self._session.scalars(statement))
        for product in products:
            product.lease_token = token
            product.lease_expires_at = expires_at
        self._session.flush()

        return ProductClaimBatch(
            token=token,
            products=products,
            expires_at=expires_at,
        )

    def authorize_observation_target(
        self,
        *,
        product_id: UUID,
        store_slug: str,
        source_url: str,
        lease_token: UUID,
        now: datetime | None = None,
        lock: bool = True,
    ) -> bool:
        """Fence an observation write against the exact product's active lease.

        With ``lock=True`` the matching product row remains locked until the caller
        ends its transaction. Saving the observation in that same transaction
        therefore cannot race with a lease takeover.
        """

        if not isinstance(product_id, UUID):
            raise TypeError("product_id must be a UUID")
        if not isinstance(lease_token, UUID):
            raise TypeError("lease_token must be a UUID")
        if not isinstance(store_slug, str) or not store_slug:
            raise ValueError("store_slug must not be empty")
        if not isinstance(source_url, str) or not source_url:
            raise ValueError("source_url must not be empty")
        if not isinstance(lock, bool):
            raise TypeError("lock must be a boolean")

        lease_clock = func.clock_timestamp() if now is None else _utc(now)
        statement = select(TrackedProduct.id).where(
            TrackedProduct.id == product_id,
            TrackedProduct.active.is_(True),
            TrackedProduct.archived_at.is_(None),
            TrackedProduct.store_slug == store_slug,
            TrackedProduct.source_url == source_url,
            TrackedProduct.lease_token == lease_token,
            TrackedProduct.lease_expires_at > lease_clock,
            ~exists(
                select(StoreCrawlState.store_slug).where(
                    StoreCrawlState.store_slug == TrackedProduct.store_slug,
                    StoreCrawlState.paused_until > lease_clock,
                )
            ),
        )
        if lock:
            statement = statement.with_for_update()
        return self._session.scalar(statement) is not None

    def complete_claim(
        self,
        *,
        product_id: UUID,
        token: UUID,
        succeeded: bool,
        checked_at: datetime | None = None,
    ) -> bool:
        """Finish one claimed product if and only if its lease token still matches."""

        timestamp = _utc(checked_at)
        values: dict[str, Any] = {
            "last_checked_at": timestamp,
            "lease_token": None,
            "lease_expires_at": None,
            "updated_at": timestamp,
        }
        if succeeded:
            values["last_success_at"] = timestamp
            values["consecutive_failures"] = 0
        else:
            values["consecutive_failures"] = TrackedProduct.consecutive_failures + 1

        statement = (
            update(TrackedProduct)
            .where(
                TrackedProduct.id == product_id,
                TrackedProduct.lease_token == token,
            )
            .values(**values)
            .returning(TrackedProduct.id)
            .execution_options(synchronize_session="fetch")
        )
        completed_id = self._session.scalar(statement)
        self._session.flush()
        return completed_id is not None

    def release_batch(self, batch: ProductClaimBatch | UUID) -> int:
        """Release an aborted batch without marking its products as checked."""

        token = batch.token if isinstance(batch, ProductClaimBatch) else batch
        statement = (
            update(TrackedProduct)
            .where(TrackedProduct.lease_token == token)
            .values(lease_token=None, lease_expires_at=None)
            .returning(TrackedProduct.id)
            .execution_options(synchronize_session="fetch")
        )
        released_ids = tuple(self._session.scalars(statement))
        self._session.flush()
        return len(released_ids)

    def mark_checked(
        self,
        tracked_product: TrackedProduct,
        *,
        succeeded: bool,
        checked_at: datetime | None = None,
    ) -> None:
        timestamp = _utc(checked_at)
        tracked_product.last_checked_at = timestamp
        if succeeded:
            tracked_product.last_success_at = timestamp
        self._session.flush()


class EquivalentProductRepository:
    """Manage operator-verified equivalence between exact cross-store listings."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create_group(
        self,
        *,
        name: str,
        brand: str,
        model: str,
        canonical_variant: dict[str, str] | None = None,
    ) -> EquivalentProductGroup:
        normalized_name = " ".join(name.split())
        normalized_brand = " ".join(brand.split())
        normalized_model = " ".join(model.split())
        if not normalized_name or not normalized_brand or not normalized_model:
            raise ValueError("name, brand, and model must not be empty")
        group = EquivalentProductGroup(
            name=normalized_name,
            brand=normalized_brand,
            model=normalized_model,
            canonical_variant=canonicalize_variant(canonical_variant or {}),
        )
        self._session.add(group)
        self._session.flush()
        return group

    def list_groups(self) -> list[EquivalentProductGroup]:
        statement = select(EquivalentProductGroup).order_by(
            EquivalentProductGroup.active.desc(),
            EquivalentProductGroup.name.asc(),
        )
        return list(self._session.scalars(statement))

    def get_group(
        self,
        group_id: UUID,
        *,
        lock: bool = False,
    ) -> EquivalentProductGroup | None:
        statement = select(EquivalentProductGroup).where(EquivalentProductGroup.id == group_id)
        if lock:
            statement = statement.with_for_update()
        return self._session.scalar(statement)

    def add_product(
        self,
        *,
        group_id: UUID,
        tracked_product_id: UUID,
        verified_at: datetime | None = None,
    ) -> EquivalentProductMembership:
        group = self.get_group(group_id, lock=True)
        if group is None or not group.active:
            raise ValueError("the equivalence group does not exist or is inactive")
        product = self._session.scalar(
            select(TrackedProduct).where(TrackedProduct.id == tracked_product_id).with_for_update()
        )
        if product is None:
            raise ValueError("the tracked product does not exist")
        if product.expected_brand is None or product.expected_model is None:
            raise ValueError("the tracked product needs an expected brand and model first")
        if (
            product.expected_brand.casefold() != group.brand.casefold()
            or product.expected_model.casefold() != group.model.casefold()
        ):
            raise ValueError(
                "the tracked product brand and model do not match the equivalence group"
            )
        if canonicalize_variant(product.expected_variant) != canonicalize_variant(
            group.canonical_variant
        ):
            raise ValueError("the tracked product variant does not match the equivalence group")
        same_store_member = self._session.scalar(
            select(EquivalentProductMembership.tracked_product_id)
            .join(
                TrackedProduct,
                TrackedProduct.id == EquivalentProductMembership.tracked_product_id,
            )
            .where(
                EquivalentProductMembership.group_id == group.id,
                TrackedProduct.store_slug == product.store_slug,
                EquivalentProductMembership.tracked_product_id != product.id,
            )
            .limit(1)
        )
        if same_store_member is not None:
            raise ValueError("an equivalence group can contain only one listing per store")
        membership = EquivalentProductMembership(
            group_id=group.id,
            tracked_product_id=product.id,
            verified_at=_utc(verified_at),
        )
        self._session.add(membership)
        self._session.flush()
        return membership

    def remove_product(
        self,
        *,
        group_id: UUID,
        tracked_product_id: UUID,
    ) -> bool:
        membership = self._session.get(
            EquivalentProductMembership,
            (group_id, tracked_product_id),
        )
        if membership is None:
            return False
        self._session.delete(membership)
        self._session.flush()
        return True

    def members(self, group_id: UUID) -> list[TrackedProduct]:
        statement = (
            select(TrackedProduct)
            .join(
                EquivalentProductMembership,
                EquivalentProductMembership.tracked_product_id == TrackedProduct.id,
            )
            .where(EquivalentProductMembership.group_id == group_id)
            .order_by(TrackedProduct.store_slug.asc(), TrackedProduct.label.asc())
        )
        return list(self._session.scalars(statement))


class CrawlRunRepository:
    """Lifecycle operations for a bounded crawl run."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def start(
        self,
        *,
        store_slug: str,
        spider_name: str,
        requested_url_count: int = 0,
        stats: dict[str, Any] | None = None,
        started_at: datetime | None = None,
    ) -> CrawlRun:
        if requested_url_count < 0:
            raise ValueError("requested_url_count must not be negative")
        run = CrawlRun(
            store_slug=store_slug.strip().lower(),
            spider_name=spider_name.strip(),
            requested_url_count=requested_url_count,
            stats=dict(stats or {}),
            started_at=_utc(started_at),
        )
        if not run.store_slug or not run.spider_name:
            raise ValueError("store_slug and spider_name must not be empty")
        self._session.add(run)
        self._session.flush()
        return run

    def finish(
        self,
        run: CrawlRun,
        *,
        status: CrawlRunStatus,
        observation_count: int,
        error_count: int,
        stats: dict[str, Any] | None = None,
        error_summary: str | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        normalized_status = CrawlRunStatus(status)
        if normalized_status is CrawlRunStatus.RUNNING:
            raise ValueError("a finished crawl run cannot remain in running status")
        if observation_count < 0 or error_count < 0:
            raise ValueError("crawl run counts must not be negative")

        run.status = normalized_status
        run.observation_count = observation_count
        run.error_count = error_count
        run.finished_at = _utc(finished_at)
        if stats is not None:
            run.stats = dict(stats)
        run.error_summary = error_summary.strip() if error_summary else None
        self._session.flush()


class PriceObservationRepository:
    """Idempotent persistence for normalized observations."""

    _unique_constraint = "uq_price_observations_run_target_sku_seller"

    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, *, run_id: UUID, observation: PriceObservation) -> SaveObservationResult:
        values = {
            "run_id": run_id,
            "tracked_product_id": observation.tracked_product_id,
            "store_slug": observation.store_slug,
            "source_url": observation.source_url,
            "external_product_id": observation.external_product_id,
            "product_reference": observation.product_reference,
            "sku": observation.sku,
            "sku_reference": observation.sku_reference,
            "seller_id": observation.seller_id,
            "seller_name": observation.seller_name,
            "title": observation.title,
            "brand": observation.brand,
            "model": observation.model,
            "image_url": observation.image_url,
            "category_path": list(observation.category_path),
            "variant": dict(observation.variant),
            "condition": observation.condition,
            "currency": observation.currency,
            "price": observation.price,
            "list_price": observation.list_price,
            "availability": observation.availability,
            "available_quantity": observation.available_quantity,
            "is_marketplace": observation.is_marketplace,
            "installments": [option.as_json() for option in observation.installments],
            "observed_at": observation.observed_at,
            "extractor_version": observation.extractor_version,
            "source_payload_hash": observation.source_payload_hash,
            "quality_flags": list(observation.quality_flags),
        }
        statement = (
            insert(PriceObservationRecord)
            .values(**values)
            .on_conflict_do_nothing(constraint=self._unique_constraint)
            .returning(PriceObservationRecord.id)
        )
        observation_id = self._session.execute(statement).scalar_one_or_none()
        if observation_id is not None:
            return SaveObservationResult(observation_id=observation_id, inserted=True)

        existing_id = self._session.scalar(
            select(PriceObservationRecord.id).where(
                PriceObservationRecord.run_id == run_id,
                PriceObservationRecord.tracked_product_id == observation.tracked_product_id,
                PriceObservationRecord.sku == observation.sku,
                PriceObservationRecord.seller_id == observation.seller_id,
            )
        )
        if existing_id is None:
            raise RuntimeError("observation conflict occurred but the existing row was not found")
        return SaveObservationResult(observation_id=existing_id, inserted=False)

    def latest_for_offer(
        self,
        *,
        tracked_product_id: UUID,
        store_slug: str,
        sku: str,
        seller_id: str,
    ) -> PriceObservationRecord | None:
        statement = (
            select(PriceObservationRecord)
            .where(
                PriceObservationRecord.tracked_product_id == tracked_product_id,
                PriceObservationRecord.store_slug == store_slug,
                PriceObservationRecord.sku == sku,
                PriceObservationRecord.seller_id == seller_id,
            )
            .order_by(PriceObservationRecord.observed_at.desc())
            .limit(1)
        )
        return self._session.scalar(statement)
