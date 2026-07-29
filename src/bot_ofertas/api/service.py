"""Application queries and mutations exposed by the HTTP administration layer."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select, text
from sqlalchemy.orm import Session, aliased, selectinload

from bot_ofertas.api.cursors import (
    CursorError,
    cursor_scope,
    decode_cursor,
    encode_cursor,
)
from bot_ofertas.api.schemas import (
    ConfirmationRead,
    CrawlJobCreate,
    CrawlJobRead,
    CrawlRunRead,
    ObservationRead,
    OfferRead,
    OperationsStatusRead,
    Page,
    ProductActivation,
    ProductCreate,
    ProductPatch,
    ProductRead,
    ProductVariant,
    RuntimePolicyPatch,
    RuntimePolicyRead,
    StoreRead,
)
from bot_ofertas.detection import canonicalize_variant
from bot_ofertas.domain import Availability
from bot_ofertas.services.operations import read_operations_snapshot
from bot_ofertas.services.runtime_policy import (
    EffectiveRuntimePolicy,
    replace_runtime_policy,
    resolve_runtime_policy,
)
from bot_ofertas.storage.admin import (
    CrawlJobRepository,
    OptimisticConcurrencyError,
)
from bot_ofertas.storage.models import (
    CrawlJob,
    CrawlJobStatus,
    CrawlRun,
    DealDetection,
    OfferConfirmationState,
    PriceObservationRecord,
    StoreCrawlState,
    TrackedProduct,
)
from bot_ofertas.storage.repositories import TrackedProductRepository
from bot_ofertas.stores import StoreRegistry

_MAX_PAGE_SIZE = 100
_MAX_SEARCH_LENGTH = 100


class ProductNotFoundError(LookupError):
    pass


class CrawlJobNotFoundError(LookupError):
    pass


class UnsafeProductConfigurationError(ValueError):
    pass


class InvalidCrawlJobRequestError(ValueError):
    pass


class InvalidRuntimePolicyError(ValueError):
    pass


def operations_status(session: Session) -> OperationsStatusRead:
    """Return worker freshness and queue pressure without affecting readiness."""

    return OperationsStatusRead.model_validate(read_operations_snapshot(session))


def _page_size(limit: int) -> int:
    if isinstance(limit, bool) or not 1 <= limit <= _MAX_PAGE_SIZE:
        raise ValueError(f"limit must be between 1 and {_MAX_PAGE_SIZE}")
    return limit


def _search_term(search: str | None) -> str | None:
    if search is None:
        return None
    normalized = " ".join(search.split())
    if not normalized:
        return None
    if len(normalized) > _MAX_SEARCH_LENGTH:
        raise ValueError(f"search must not exceed {_MAX_SEARCH_LENGTH} characters")
    return normalized


def _escaped_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _cursor_uuid(raw_key: str) -> UUID:
    try:
        return UUID(raw_key)
    except ValueError as error:
        raise CursorError("invalid pagination cursor") from error


def _cursor_integer(raw_key: str) -> int:
    try:
        value = int(raw_key)
    except ValueError as error:
        raise CursorError("invalid pagination cursor") from error
    if value <= 0 or str(value) != raw_key:
        raise CursorError("invalid pagination cursor")
    return value


def list_stores(session: Session, registry: StoreRegistry) -> list[StoreRead]:
    states = {
        state.store_slug: state
        for state in session.scalars(select(StoreCrawlState))
    }
    counts = {
        store_slug: (total, active)
        for store_slug, total, active in session.execute(
            select(
                TrackedProduct.store_slug,
                func.count(TrackedProduct.id),
                func.count(TrackedProduct.id).filter(TrackedProduct.active.is_(True)),
            )
            .where(TrackedProduct.archived_at.is_(None))
            .group_by(TrackedProduct.store_slug)
        )
    }
    ranked_runs = (
        select(
            CrawlRun.id.label("run_id"),
            func.row_number()
            .over(
                partition_by=CrawlRun.store_slug,
                order_by=(CrawlRun.started_at.desc(), CrawlRun.id.desc()),
            )
            .label("position"),
        )
        .subquery()
    )
    last_runs = {
        run.store_slug: run
        for run in session.scalars(
            select(CrawlRun)
            .join(ranked_runs, ranked_runs.c.run_id == CrawlRun.id)
            .where(ranked_runs.c.position == 1)
        )
    }
    timestamp = datetime.now(UTC)
    result: list[StoreRead] = []
    for adapter in registry.adapters:
        state = states.get(adapter.slug)
        last_run = last_runs.get(adapter.slug)
        total, active = counts.get(adapter.slug, (0, 0))
        health = (
            "disabled"
            if not adapter.policy.enabled
            else "paused"
            if state is not None
            and state.paused_until is not None
            and state.paused_until > timestamp
            else "healthy"
        )
        result.append(
            StoreRead(
                slug=adapter.slug,
                display_name=adapter.display_name,
                hosts=sorted(adapter.hosts),
                enabled=adapter.policy.enabled,
                minimum_interval_minutes=adapter.policy.minimum_interval_minutes,
                max_targets_per_run=adapter.policy.max_targets_per_run,
                requires_explicit_product_url=(
                    adapter.policy.requires_explicit_product_url
                ),
                notes=adapter.policy.notes,
                health=health,
                paused_until=state.paused_until if state is not None else None,
                pause_reason=state.pause_reason if state is not None else None,
                consecutive_blocks=(
                    state.consecutive_blocks if state is not None else 0
                ),
                tracked_products=total,
                active_products=active,
                last_run_id=last_run.id if last_run is not None else None,
                last_run_status=(
                    last_run.status.value if last_run is not None else None
                ),
                last_run_started_at=(
                    last_run.started_at if last_run is not None else None
                ),
                last_run_finished_at=(
                    last_run.finished_at if last_run is not None else None
                ),
            )
        )
    return result


def create_product(
    session: Session,
    registry: StoreRegistry,
    payload: ProductCreate,
) -> TrackedProduct:
    adapter, canonical_url = registry.resolve(str(payload.url))
    if payload.check_interval_minutes < adapter.policy.minimum_interval_minutes:
        raise UnsafeProductConfigurationError(
            f"{adapter.display_name} requiere un intervalo mínimo de "
            f"{adapter.policy.minimum_interval_minutes} minutos"
        )
    return TrackedProductRepository(session).add(
        store_slug=adapter.slug,
        source_url=canonical_url,
        label=payload.label,
        expected_brand=payload.expected_brand,
        expected_model=payload.expected_model,
        expected_variant=payload.expected_variant,
        expected_is_accessory=payload.expected_is_accessory,
        check_interval_minutes=payload.check_interval_minutes,
        active=payload.active,
    )


def get_product(session: Session, product_id: UUID) -> TrackedProduct:
    product = session.get(TrackedProduct, product_id)
    if product is None:
        raise ProductNotFoundError("producto no encontrado")
    return product


def list_products(
    session: Session,
    *,
    cursor: str | None,
    limit: int,
    store_slug: str | None,
    active: bool | None,
    archived: bool,
    search: str | None,
) -> Page[ProductRead]:
    page_size = _page_size(limit)
    normalized_store = store_slug.strip().lower() if store_slug else None
    normalized_search = _search_term(search)
    scope = cursor_scope(
        "products",
        store_slug=normalized_store,
        active=active,
        archived=archived,
        search=normalized_search,
    )
    filters = []
    filters.append(
        TrackedProduct.archived_at.is_not(None)
        if archived
        else TrackedProduct.archived_at.is_(None)
    )
    if normalized_store is not None:
        filters.append(TrackedProduct.store_slug == normalized_store)
    if active is not None:
        filters.append(TrackedProduct.active.is_(active))
    if normalized_search is not None:
        term = f"%{_escaped_like(normalized_search)}%"
        filters.append(
            or_(
                TrackedProduct.label.ilike(term, escape="\\"),
                TrackedProduct.expected_brand.ilike(term, escape="\\"),
                TrackedProduct.expected_model.ilike(term, escape="\\"),
                TrackedProduct.source_url.ilike(term, escape="\\"),
            )
        )
    if cursor is not None:
        position = decode_cursor(cursor, scope=scope)
        product_id = _cursor_uuid(position.key)
        filters.append(
            or_(
                TrackedProduct.created_at < position.timestamp,
                and_(
                    TrackedProduct.created_at == position.timestamp,
                    TrackedProduct.id < product_id,
                ),
            )
        )
    statement = (
        select(TrackedProduct)
        .where(*filters)
        .order_by(TrackedProduct.created_at.desc(), TrackedProduct.id.desc())
        .limit(page_size + 1)
    )
    products = list(session.scalars(statement))
    has_more = len(products) > page_size
    visible = products[:page_size]
    items = [
        ProductRead.model_validate(item)
        for item in visible
    ]
    next_cursor = (
        encode_cursor(
            scope=scope,
            timestamp=visible[-1].created_at,
            key=str(visible[-1].id),
        )
        if has_more
        else None
    )
    return Page(
        items=items,
        limit=page_size,
        has_more=has_more,
        next_cursor=next_cursor,
    )


def update_product(
    session: Session,
    registry: StoreRegistry,
    product_id: UUID,
    payload: ProductPatch,
    *,
    expected_version: int,
) -> TrackedProduct:
    product = session.scalar(
        select(TrackedProduct)
        .where(TrackedProduct.id == product_id)
        .with_for_update()
    )
    if product is None:
        raise ProductNotFoundError("producto no encontrado")
    _require_mutable_product(product, expected_version=expected_version)
    adapter = registry.get(product.store_slug)
    changed = payload.model_fields_set

    if "label" in changed:
        if payload.label is None:
            raise UnsafeProductConfigurationError("label no puede ser null")
        product.label = payload.label
    if "expected_brand" in changed:
        product.expected_brand = payload.expected_brand
    if "expected_model" in changed:
        product.expected_model = payload.expected_model
    if "expected_is_accessory" in changed:
        if payload.expected_is_accessory is None:
            raise UnsafeProductConfigurationError(
                "expected_is_accessory no puede ser null"
            )
        product.expected_is_accessory = payload.expected_is_accessory
    if "check_interval_minutes" in changed:
        interval = payload.check_interval_minutes
        if interval is None:
            raise UnsafeProductConfigurationError(
                "check_interval_minutes no puede ser null"
            )
        if interval < adapter.policy.minimum_interval_minutes:
            raise UnsafeProductConfigurationError(
                f"{adapter.display_name} requiere un intervalo mínimo de "
                f"{adapter.policy.minimum_interval_minutes} minutos"
            )
        product.check_interval_minutes = interval
    product.version += 1
    product.updated_at = datetime.now(UTC)
    session.flush()
    return product


def _require_mutable_product(
    product: TrackedProduct,
    *,
    expected_version: int,
) -> None:
    if expected_version <= 0:
        raise ValueError("expected_version must be positive")
    if product.version != expected_version:
        raise OptimisticConcurrencyError(
            f"expected product version {expected_version}, current is {product.version}"
        )
    if product.archived_at is not None:
        raise UnsafeProductConfigurationError(
            "un producto archivado conserva su historial y no puede modificarse"
        )


def set_product_activation(
    session: Session,
    product_id: UUID,
    payload: ProductActivation,
    *,
    expected_version: int,
) -> TrackedProduct:
    product = session.scalar(
        select(TrackedProduct)
        .where(TrackedProduct.id == product_id)
        .with_for_update()
    )
    if product is None:
        raise ProductNotFoundError("producto no encontrado")
    _require_mutable_product(product, expected_version=expected_version)
    product.active = payload.active
    if not product.active:
        product.lease_token = None
        product.lease_expires_at = None
    product.version += 1
    product.updated_at = datetime.now(UTC)
    session.flush()
    return product


def set_product_variant(
    session: Session,
    product_id: UUID,
    payload: ProductVariant | None,
    *,
    expected_version: int,
) -> TrackedProduct:
    product = session.scalar(
        select(TrackedProduct)
        .where(TrackedProduct.id == product_id)
        .with_for_update()
    )
    if product is None:
        raise ProductNotFoundError("producto no encontrado")
    _require_mutable_product(product, expected_version=expected_version)
    product.expected_variant = canonicalize_variant(
        payload.expected_variant if payload is not None else {}
    )
    product.version += 1
    product.updated_at = datetime.now(UTC)
    session.flush()
    return product


def archive_product(
    session: Session,
    product_id: UUID,
    *,
    expected_version: int,
) -> None:
    product = session.scalar(
        select(TrackedProduct)
        .where(TrackedProduct.id == product_id)
        .with_for_update()
    )
    if product is None:
        raise ProductNotFoundError("producto no encontrado")
    _require_mutable_product(product, expected_version=expected_version)
    timestamp = datetime.now(UTC)
    product.active = False
    product.archived_at = timestamp
    product.lease_token = None
    product.lease_expires_at = None
    product.version += 1
    product.updated_at = timestamp
    session.flush()


def list_observations(
    session: Session,
    *,
    product_id: UUID,
    cursor: str | None,
    limit: int,
) -> Page[ObservationRead]:
    page_size = _page_size(limit)
    get_product(session, product_id)
    scope = cursor_scope("product-observations", product_id=product_id)
    filters = [PriceObservationRecord.tracked_product_id == product_id]
    if cursor is not None:
        position = decode_cursor(cursor, scope=scope)
        observation_id = _cursor_integer(position.key)
        filters.append(
            or_(
                PriceObservationRecord.observed_at < position.timestamp,
                and_(
                    PriceObservationRecord.observed_at == position.timestamp,
                    PriceObservationRecord.id < observation_id,
                ),
            )
        )
    statement = (
        select(PriceObservationRecord)
        .where(*filters)
        .order_by(
            PriceObservationRecord.observed_at.desc(),
            PriceObservationRecord.id.desc(),
        )
        .limit(page_size + 1)
    )
    observations = list(session.scalars(statement))
    has_more = len(observations) > page_size
    visible = observations[:page_size]
    items = [
        ObservationRead.model_validate(item)
        for item in visible
    ]
    next_cursor = (
        encode_cursor(
            scope=scope,
            timestamp=visible[-1].observed_at,
            key=str(visible[-1].id),
        )
        if has_more
        else None
    )
    return Page(
        items=items,
        limit=page_size,
        has_more=has_more,
        next_cursor=next_cursor,
    )


def _discount_percent(detection: DealDetection) -> Decimal | None:
    """Return the discount belonging to the persisted primary reference only."""

    if detection.reference_price is None or not isinstance(detection.metrics, dict):
        return None
    primary_signal = detection.metrics.get("primary_signal_kind")
    signals = detection.metrics.get("signals")
    if not isinstance(primary_signal, str) or not isinstance(signals, dict):
        return None
    signal = signals.get(primary_signal)
    if not isinstance(signal, dict):
        return None
    try:
        reference_price = Decimal(str(signal.get("reference_price")))
        discount = Decimal(str(signal.get("discount_percent")))
    except (InvalidOperation, ValueError):
        return None
    if (
        not reference_price.is_finite()
        or not discount.is_finite()
        or reference_price != detection.reference_price
        or discount <= 0
    ):
        return None
    return discount


def list_offers(
    session: Session,
    *,
    cursor: str | None,
    limit: int,
    classification: str | None,
    store_slug: str | None,
    notification_status: str | None,
    include_rejected: bool,
    state: str,
) -> Page[OfferRead]:
    page_size = _page_size(limit)
    normalized_store = store_slug.strip().lower() if store_slug else None
    scope = cursor_scope(
        "offers",
        classification=classification,
        store_slug=normalized_store,
        notification_status=notification_status,
        include_rejected=include_rejected,
        state=state,
    )
    filters = []
    if state not in {"active", "awaiting", "history"}:
        raise ValueError("state must be active, awaiting, or history")
    if state != "history" or not include_rejected:
        filters.append(DealDetection.classification != "none")
    if state == "active":
        effective = resolve_runtime_policy(session).settings
        newer = aliased(DealDetection)
        filters.extend(
            (
                DealDetection.eligible.is_(True),
                DealDetection.detector_version == effective.detector_version,
                DealDetection.policy_fingerprint == effective.policy_fingerprint,
                DealDetection.confirmation_status.in_(("confirmed", "not_required")),
                PriceObservationRecord.availability == Availability.IN_STOCK,
                PriceObservationRecord.observed_at
                >= func.now() - text("INTERVAL '24 hours'"),
                TrackedProduct.active.is_(True),
                TrackedProduct.archived_at.is_(None),
                ~exists(
                    select(newer.id).where(
                        newer.offer_key == DealDetection.offer_key,
                        newer.detector_version == DealDetection.detector_version,
                        newer.policy_fingerprint == DealDetection.policy_fingerprint,
                        or_(
                            newer.detected_at > DealDetection.detected_at,
                            and_(
                                newer.detected_at == DealDetection.detected_at,
                                newer.id > DealDetection.id,
                            ),
                        ),
                    )
                ),
            )
        )
    elif state == "awaiting":
        effective = resolve_runtime_policy(session).settings
        filters.extend(
            (
                DealDetection.confirmation_status == "awaiting",
                DealDetection.detector_version == effective.detector_version,
                DealDetection.policy_fingerprint == effective.policy_fingerprint,
                TrackedProduct.active.is_(True),
                TrackedProduct.archived_at.is_(None),
                exists(
                    select(OfferConfirmationState.offer_key).where(
                        OfferConfirmationState.candidate_detection_id
                        == DealDetection.id,
                        OfferConfirmationState.expires_at > func.now(),
                    )
                ),
            )
        )
    if classification is not None:
        filters.append(DealDetection.classification == classification)
    if normalized_store is not None:
        filters.append(PriceObservationRecord.store_slug == normalized_store)
    if notification_status is not None:
        filters.append(DealDetection.notification_status == notification_status)
    if cursor is not None:
        position = decode_cursor(cursor, scope=scope)
        detection_id = _cursor_integer(position.key)
        filters.append(
            or_(
                DealDetection.detected_at < position.timestamp,
                and_(
                    DealDetection.detected_at == position.timestamp,
                    DealDetection.id < detection_id,
                ),
            )
        )
    statement = (
        select(
            DealDetection,
            PriceObservationRecord,
            TrackedProduct.label,
        )
        .join(
            PriceObservationRecord,
            PriceObservationRecord.id == DealDetection.observation_id,
        )
        .outerjoin(
            TrackedProduct,
            TrackedProduct.id == DealDetection.tracked_product_id,
        )
        .where(*filters)
        .order_by(DealDetection.detected_at.desc(), DealDetection.id.desc())
        .limit(page_size + 1)
    )
    rows = list(session.execute(statement))
    has_more = len(rows) > page_size
    visible = rows[:page_size]
    items = [
        OfferRead(
            id=detection.id,
            observation_id=detection.observation_id,
            tracked_product_id=detection.tracked_product_id,
            product_label=label or observation.title,
            title=observation.title,
            store_slug=observation.store_slug,
            source_url=observation.source_url,
            detector_version=detection.detector_version,
            policy_fingerprint=detection.policy_fingerprint,
            config_revision_id=detection.config_revision_id,
            classification=detection.classification,
            eligible=detection.eligible,
            score=detection.score,
            confidence_score=detection.confidence_score,
            confidence_level=detection.confidence_level,
            currency=observation.currency,
            current_price=detection.current_price,
            reference_price=detection.reference_price,
            discount_percent=_discount_percent(detection),
            primary_signal_kind=(
                detection.metrics.get("primary_signal_kind")
                if isinstance(
                    detection.metrics.get("primary_signal_kind"),
                    str,
                )
                else None
            ),
            signals=(
                dict(detection.metrics.get("signals", {}))
                if isinstance(detection.metrics.get("signals"), dict)
                else {}
            ),
            notification_status=detection.notification_status,
            confirmation_status=detection.confirmation_status,
            confirmation_count=detection.confirmation_count,
            reasons=list(detection.reasons),
            rejection_reasons=list(detection.rejection_reasons),
            quality_flags=list(observation.quality_flags),
            detected_at=detection.detected_at,
        )
        for detection, observation, label in visible
    ]
    next_cursor = (
        encode_cursor(
            scope=scope,
            timestamp=visible[-1][0].detected_at,
            key=str(visible[-1][0].id),
        )
        if has_more
        else None
    )
    return Page(
        items=items,
        limit=page_size,
        has_more=has_more,
        next_cursor=next_cursor,
    )


def list_confirmations(
    session: Session,
    *,
    cursor: str | None,
    limit: int,
    active_only: bool,
) -> Page[ConfirmationRead]:
    page_size = _page_size(limit)
    scope = cursor_scope("confirmations", active_only=active_only)
    filters = []
    if active_only:
        effective = resolve_runtime_policy(session).settings
        filters.extend(
            (
                OfferConfirmationState.expires_at > func.now(),
                DealDetection.confirmation_status == "awaiting",
                DealDetection.detector_version == effective.detector_version,
                DealDetection.policy_fingerprint == effective.policy_fingerprint,
                TrackedProduct.active.is_(True),
                TrackedProduct.archived_at.is_(None),
            )
        )
    if cursor is not None:
        position = decode_cursor(cursor, scope=scope)
        filters.append(
            or_(
                OfferConfirmationState.created_at < position.timestamp,
                and_(
                    OfferConfirmationState.created_at == position.timestamp,
                    OfferConfirmationState.offer_key < position.key,
                ),
            )
        )
    statement = (
        select(
            OfferConfirmationState,
            TrackedProduct.label,
        )
        .outerjoin(
            TrackedProduct,
            TrackedProduct.id == OfferConfirmationState.tracked_product_id,
        )
    )
    if active_only:
        statement = statement.join(
            DealDetection,
            DealDetection.id == OfferConfirmationState.candidate_detection_id,
        )
    statement = (
        statement.where(*filters)
        .order_by(
            OfferConfirmationState.created_at.desc(),
            OfferConfirmationState.offer_key.desc(),
        )
        .limit(page_size + 1)
    )
    rows = list(session.execute(statement))
    has_more = len(rows) > page_size
    visible = rows[:page_size]
    items = [
        ConfirmationRead(
            offer_key=state.offer_key,
            tracked_product_id=state.tracked_product_id,
            product_label=label,
            candidate_detection_id=state.candidate_detection_id,
            candidate_classification=state.candidate_classification,
            candidate_price=state.candidate_price,
            confirmation_count=state.confirmation_count,
            first_seen_at=state.first_seen_at,
            last_seen_at=state.last_seen_at,
            expires_at=state.expires_at,
        )
        for state, label in visible
    ]
    next_cursor = (
        encode_cursor(
            scope=scope,
            timestamp=visible[-1][0].created_at,
            key=visible[-1][0].offer_key,
        )
        if has_more
        else None
    )
    return Page(
        items=items,
        limit=page_size,
        has_more=has_more,
        next_cursor=next_cursor,
    )


def list_crawl_runs(
    session: Session,
    *,
    cursor: str | None,
    limit: int,
    store_slug: str | None,
    status: str | None,
) -> Page[CrawlRunRead]:
    page_size = _page_size(limit)
    normalized_store = store_slug.strip().lower() if store_slug else None
    scope = cursor_scope(
        "crawl-runs",
        store_slug=normalized_store,
        status=status,
    )
    filters = []
    if normalized_store is not None:
        filters.append(CrawlRun.store_slug == normalized_store)
    if status is not None:
        filters.append(CrawlRun.status == status)
    if cursor is not None:
        position = decode_cursor(cursor, scope=scope)
        run_id = _cursor_uuid(position.key)
        filters.append(
            or_(
                CrawlRun.started_at < position.timestamp,
                and_(
                    CrawlRun.started_at == position.timestamp,
                    CrawlRun.id < run_id,
                ),
            )
        )
    statement = (
        select(CrawlRun)
        .where(*filters)
        .order_by(CrawlRun.started_at.desc(), CrawlRun.id.desc())
        .limit(page_size + 1)
    )
    runs = list(session.scalars(statement))
    has_more = len(runs) > page_size
    visible = runs[:page_size]
    items = [
        CrawlRunRead.model_validate(item)
        for item in visible
    ]
    next_cursor = (
        encode_cursor(
            scope=scope,
            timestamp=visible[-1].started_at,
            key=str(visible[-1].id),
        )
        if has_more
        else None
    )
    return Page(
        items=items,
        limit=page_size,
        has_more=has_more,
        next_cursor=next_cursor,
    )


def enqueue_crawl_job(
    session: Session,
    *,
    registry: StoreRegistry,
    payload: CrawlJobCreate,
    requested_by: str,
    idempotency_key: str,
) -> tuple[CrawlJob, bool]:
    effective_policy = resolve_runtime_policy(session)
    try:
        result = CrawlJobRepository(session).enqueue(
            product_ids=payload.product_ids,
            requested_by=requested_by,
            idempotency_key=idempotency_key,
            request_payload={
                "product_ids": [
                    str(product_id) for product_id in payload.product_ids
                ],
                "due_only": True,
            },
            request_source="api",
            force=False,
            config_revision_id=effective_policy.revision_id,
        )
    except ValueError as error:
        raise InvalidCrawlJobRequestError(
            "Todos los productos deben existir, estar activos y no estar archivados."
        ) from error
    if result.inserted:
        store_counts = {
            store_slug: target_count
            for store_slug, target_count in session.execute(
                select(
                    TrackedProduct.store_slug,
                    func.count(TrackedProduct.id),
                )
                .where(TrackedProduct.id.in_(payload.product_ids))
                .group_by(TrackedProduct.store_slug)
            )
        }
        for store_slug, target_count in store_counts.items():
            adapter = registry.get(store_slug)
            if target_count > adapter.policy.max_targets_per_run:
                raise InvalidCrawlJobRequestError(
                    f"{adapter.display_name} admite como máximo "
                    f"{adapter.policy.max_targets_per_run} productos por trabajo."
                )
    session.flush()
    return get_crawl_job(session, result.job.id), result.inserted


def get_crawl_job(session: Session, job_id: UUID) -> CrawlJob:
    job = session.scalar(
        select(CrawlJob)
        .where(CrawlJob.id == job_id)
        .options(selectinload(CrawlJob.items))
    )
    if job is None:
        raise CrawlJobNotFoundError("trabajo de rastreo no encontrado")
    return job


def list_crawl_jobs(
    session: Session,
    *,
    cursor: str | None,
    limit: int,
    status: str | None,
) -> Page[CrawlJobRead]:
    page_size = _page_size(limit)
    normalized_status = CrawlJobStatus(status).value if status is not None else None
    scope = cursor_scope("crawl-jobs", status=normalized_status)
    filters = []
    if normalized_status is not None:
        filters.append(CrawlJob.status == normalized_status)
    if cursor is not None:
        position = decode_cursor(cursor, scope=scope)
        job_id = _cursor_uuid(position.key)
        filters.append(
            or_(
                CrawlJob.created_at < position.timestamp,
                and_(
                    CrawlJob.created_at == position.timestamp,
                    CrawlJob.id < job_id,
                ),
            )
        )
    statement = (
        select(CrawlJob)
        .where(*filters)
        .options(selectinload(CrawlJob.items))
        .order_by(CrawlJob.created_at.desc(), CrawlJob.id.desc())
        .limit(page_size + 1)
    )
    jobs = list(session.scalars(statement))
    has_more = len(jobs) > page_size
    visible = jobs[:page_size]
    next_cursor = (
        encode_cursor(
            scope=scope,
            timestamp=visible[-1].created_at,
            key=str(visible[-1].id),
        )
        if has_more
        else None
    )
    return Page(
        items=[CrawlJobRead.model_validate(job) for job in visible],
        limit=page_size,
        has_more=has_more,
        next_cursor=next_cursor,
    )


def cancel_crawl_job(
    session: Session,
    *,
    job_id: UUID,
    requested_by: str,
) -> CrawlJob:
    job = CrawlJobRepository(session).cancel(
        job_id,
        requested_by=requested_by,
    )
    if job is None:
        raise CrawlJobNotFoundError("trabajo de rastreo no encontrado")
    return get_crawl_job(session, job.id)


def _runtime_policy_read(effective: EffectiveRuntimePolicy) -> RuntimePolicyRead:
    settings = effective.settings
    detector = settings.detector_config
    thresholds = detector.list_price_thresholds
    return RuntimePolicyRead(
        revision_id=effective.revision_id,
        policy_fingerprint=settings.policy_fingerprint,
        changed_by=effective.changed_by,
        change_reason=effective.change_reason,
        detector_version=settings.detector_version,
        scheduler_poll_seconds=settings.scheduler_poll_seconds,
        detection_history_limit=settings.detection_history_limit,
        detection_history_days=settings.detection_history_days,
        minimum_history_samples=detector.minimum_history_samples,
        equivalent_max_age_hours=settings.equivalent_max_age_hours,
        equivalent_limit=settings.equivalent_limit,
        minimum_equivalent_samples=detector.minimum_equivalent_samples,
        possible_error_minimum_corroborating_signals=(
            detector.possible_error_minimum_corroborating_signals
        ),
        possible_error_minimum_confidence=(
            detector.possible_error_minimum_confidence
        ),
        confirmation_required=settings.confirmation_required,
        confirmation_max_age_minutes=settings.confirmation_max_age_minutes,
        confirmation_price_tolerance_percent=(
            settings.confirmation_price_tolerance_ratio * Decimal("100")
        ),
        confirmation_confidence_bonus=settings.confirmation_confidence_bonus,
        minimum_alert_confidence=settings.minimum_alert_confidence,
        good_deal_percent=thresholds.good_deal * Decimal("100"),
        exceptional_deal_percent=(
            thresholds.exceptional_deal * Decimal("100")
        ),
        possible_price_error_percent=(
            thresholds.possible_price_error * Decimal("100")
        ),
        alert_cooldown_hours=settings.alert_cooldown_hours,
        alert_significant_improvement_percent=(
            settings.alert_significant_improvement_ratio * Decimal("100")
        ),
        notification_lease_seconds=settings.notification_lease_seconds,
        notification_max_attempts=settings.notification_max_attempts,
        notification_retry_base_seconds=(
            settings.notification_retry_base_seconds
        ),
        telegram_enabled=settings.telegram_enabled,
        telegram_configured=bool(
            settings.telegram_token and settings.telegram_chat_id
        ),
        telegram_token_configured=bool(settings.telegram_token),
        telegram_chat_id_configured=bool(settings.telegram_chat_id),
    )


def runtime_policy(session: Session) -> RuntimePolicyRead:
    return _runtime_policy_read(resolve_runtime_policy(session))


def update_runtime_policy(
    session: Session,
    *,
    payload: RuntimePolicyPatch,
    expected_revision: int | None,
    changed_by: str,
    change_reason: str | None,
    idempotency_key: str | None,
) -> tuple[RuntimePolicyRead, bool]:
    try:
        change = replace_runtime_policy(
            session,
            overrides=payload.overrides(),
            expected_revision=expected_revision,
            changed_by=changed_by,
            change_reason=change_reason,
            idempotency_key=idempotency_key,
        )
    except ValueError as error:
        raise InvalidRuntimePolicyError(
            "Los valores no forman una política coherente; revisa límites y umbrales."
        ) from error
    return _runtime_policy_read(change.policy), change.inserted


__all__ = [
    "CrawlJobNotFoundError",
    "InvalidCrawlJobRequestError",
    "InvalidRuntimePolicyError",
    "ProductNotFoundError",
    "UnsafeProductConfigurationError",
    "archive_product",
    "cancel_crawl_job",
    "create_product",
    "enqueue_crawl_job",
    "get_crawl_job",
    "get_product",
    "list_confirmations",
    "list_crawl_jobs",
    "list_crawl_runs",
    "list_observations",
    "list_offers",
    "list_products",
    "list_stores",
    "runtime_policy",
    "set_product_activation",
    "set_product_variant",
    "update_runtime_policy",
    "update_product",
]
