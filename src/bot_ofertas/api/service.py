"""Application queries and mutations exposed by the HTTP administration layer."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from math import ceil
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, exists, func, or_, select, text
from sqlalchemy.orm import Session, aliased, selectinload

from bot_ofertas.api.cursors import (
    CursorError,
    cursor_scope,
    decode_cursor,
    encode_cursor,
)
from bot_ofertas.api.schemas import (
    AnalysisBacklogRead,
    CatalogCoverageRead,
    CommercialSummaryRead,
    ConfirmationRead,
    CrawlJobCreate,
    CrawlJobRead,
    CrawlRunRead,
    DiscoveryBulkReview,
    DiscoveryCandidateRead,
    DiscoveryReview,
    DiscoveryRunRead,
    DiscoverySourceRead,
    DistributionBucketRead,
    DistributionConcentrationRead,
    LaunchChecklistItemRead,
    LaunchChecklistUpdate,
    ObservationRead,
    OfferRead,
    OperationsStatusRead,
    Page,
    PaymentCreate,
    PaymentRead,
    ProductActivation,
    ProductCreate,
    ProductPatch,
    ProductRead,
    ProductVariant,
    RuntimePolicyPatch,
    RuntimePolicyRead,
    StoreCoverageRead,
    StoreRead,
    SubscriberCreate,
    SubscriberPatch,
    SubscriberRead,
    TelegramDestinationStatusRead,
    TelegramDistributionStatusRead,
    TelegramTestRead,
)
from bot_ofertas.catalog_balance import CATEGORY_LABELS, catalog_category
from bot_ofertas.detection import canonicalize_variant
from bot_ofertas.domain import Availability
from bot_ofertas.notifications import TelegramNotifier
from bot_ofertas.services.operations import read_operations_snapshot
from bot_ofertas.services.runtime_policy import (
    EffectiveRuntimePolicy,
    replace_runtime_policy,
    resolve_runtime_policy,
)
from bot_ofertas.storage.admin import (
    CrawlJobRepository,
    IdempotencyConflictError,
    OptimisticConcurrencyError,
)
from bot_ofertas.storage.discovery import DiscoveryRepository
from bot_ofertas.storage.models import (
    BetaLaunchChecklistItem,
    BetaPayment,
    BetaSubscriber,
    CrawlJob,
    CrawlJobStatus,
    CrawlRun,
    DealDetection,
    DiscoveryCandidate,
    DiscoveryRun,
    NotificationDelivery,
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


class InvalidDiscoveryRequestError(ValueError):
    pass


class SubscriberNotFoundError(LookupError):
    pass


class LaunchChecklistItemNotFoundError(LookupError):
    pass


class InvalidCommercialRequestError(ValueError):
    pass


def operations_status(session: Session) -> OperationsStatusRead:
    """Return worker freshness and queue pressure without affecting readiness."""

    return OperationsStatusRead.model_validate(read_operations_snapshot(session))


_DISTRIBUTION_QUEUE_STATUSES = (
    "pending",
    "retrying",
    "sent",
    "failed",
    "superseded",
)
_COVERAGE_TARGET_PERCENT = Decimal("95")
_CONCENTRATION_WARNING_PERCENT = Decimal("50")


def _percentage(count: int, total: int) -> Decimal:
    if total <= 0:
        return Decimal("0.00")
    return (Decimal(count) * Decimal("100") / Decimal(total)).quantize(
        Decimal("0.01")
    )


def _queue_counts(session: Session, *, channel: str) -> dict[str, int]:
    counts = {status: 0 for status in _DISTRIBUTION_QUEUE_STATUSES}
    for delivery_status, count in session.execute(
        select(
            NotificationDelivery.status,
            func.count(NotificationDelivery.id),
        )
        .where(NotificationDelivery.channel == channel)
        .group_by(NotificationDelivery.status)
    ):
        if delivery_status in counts:
            counts[delivery_status] = int(count)
    return counts


def _last_delivery_failure(
    session: Session,
    *,
    channel: str,
) -> NotificationDelivery | None:
    return session.scalar(
        select(NotificationDelivery)
        .where(
            NotificationDelivery.channel == channel,
            NotificationDelivery.last_error.is_not(None),
        )
        .order_by(
            NotificationDelivery.updated_at.desc(),
            NotificationDelivery.id.desc(),
        )
        .limit(1)
    )


def _distribution_buckets(
    counts: Counter[str],
    *,
    labels: dict[str, str] | None = None,
) -> list[DistributionBucketRead]:
    total = sum(counts.values())
    resolved_labels = labels or {}
    return [
        DistributionBucketRead(
            key=key,
            label=resolved_labels.get(key, key),
            count=count,
            percentage=_percentage(count, total),
        )
        for key, count in sorted(
            counts.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]


def _catalog_coverage(
    session: Session,
    *,
    now: datetime,
) -> CatalogCoverageRead:
    cutoff = now - timedelta(hours=24)
    stores: list[StoreCoverageRead] = []
    active_total = 0
    successful_total = 0
    for store_slug, active_count, successful_count in session.execute(
        select(
            TrackedProduct.store_slug,
            func.count(TrackedProduct.id),
            func.count(TrackedProduct.id).filter(
                TrackedProduct.last_success_at >= cutoff
            ),
        )
        .where(
            TrackedProduct.active.is_(True),
            TrackedProduct.archived_at.is_(None),
        )
        .group_by(TrackedProduct.store_slug)
        .order_by(TrackedProduct.store_slug)
    ):
        active = int(active_count)
        successful = int(successful_count)
        coverage = _percentage(successful, active)
        active_total += active
        successful_total += successful
        stores.append(
            StoreCoverageRead(
                store_slug=store_slug,
                active_products=active,
                successful_products_24h=successful,
                coverage_percent=coverage,
                meets_target=coverage >= _COVERAGE_TARGET_PERCENT,
            )
        )
    coverage = _percentage(successful_total, active_total)
    return CatalogCoverageRead(
        active_products=active_total,
        successful_products_24h=successful_total,
        coverage_percent=coverage,
        target_percent=_COVERAGE_TARGET_PERCENT,
        meets_target=coverage >= _COVERAGE_TARGET_PERCENT,
        stores=stores,
    )


def _analysis_backlog(
    session: Session,
    *,
    detector_version: str,
    capacity_per_cycle: int,
    now: datetime,
) -> AnalysisBacklogRead:
    processed = exists(
        select(DealDetection.id).where(
            DealDetection.observation_id == PriceObservationRecord.id,
            DealDetection.detector_version == detector_version,
        )
    )
    pending, oldest = session.execute(
        select(
            func.count(PriceObservationRecord.id),
            func.min(PriceObservationRecord.observed_at),
        ).where(~processed)
    ).one()
    pending_count = int(pending)
    oldest_age_hours = (
        Decimal(str(max(0.0, (now - oldest).total_seconds() / 3_600))).quantize(
            Decimal("0.01")
        )
        if oldest is not None
        else Decimal("0")
    )
    estimated_cycles = (
        ceil(pending_count / capacity_per_cycle)
        if pending_count
        else 0
    )
    return AnalysisBacklogRead(
        pending_observations=pending_count,
        oldest_observed_at=oldest,
        oldest_age_hours=oldest_age_hours,
        capacity_per_cycle=capacity_per_cycle,
        estimated_cycles=estimated_cycles,
        warning=(
            pending_count > capacity_per_cycle
            or oldest_age_hours >= Decimal("2")
        ),
    )


def _distribution_concentration(
    session: Session,
    *,
    now: datetime,
) -> DistributionConcentrationRead:
    cutoff = now - timedelta(hours=24)
    rows = list(
        session.execute(
            select(DealDetection.id, PriceObservationRecord)
            .join(
                PriceObservationRecord,
                PriceObservationRecord.id == DealDetection.observation_id,
            )
            .join(
                NotificationDelivery,
                NotificationDelivery.detection_id == DealDetection.id,
            )
            .where(
                NotificationDelivery.channel == "telegram_free",
                NotificationDelivery.status == "sent",
                NotificationDelivery.sent_at >= cutoff,
            )
            .order_by(DealDetection.id)
        )
    )
    category_counts: Counter[str] = Counter()
    store_counts: Counter[str] = Counter()
    seen_detections: set[int] = set()
    for detection_id, observation in rows:
        if detection_id in seen_detections:
            continue
        seen_detections.add(detection_id)
        category_counts[
            catalog_category(
                store_slug=observation.store_slug,
                label=observation.title,
                category_path=tuple(observation.category_path or ()),
            )
        ] += 1
        store_counts[observation.store_slug] += 1

    latest_observation = (
        select(
            PriceObservationRecord.tracked_product_id.label("tracked_product_id"),
            func.max(PriceObservationRecord.id).label("observation_id"),
        )
        .where(PriceObservationRecord.tracked_product_id.is_not(None))
        .group_by(PriceObservationRecord.tracked_product_id)
        .subquery()
    )
    uncategorized = 0
    for store_slug, label, title, category_path in session.execute(
        select(
            TrackedProduct.store_slug,
            TrackedProduct.label,
            PriceObservationRecord.title,
            PriceObservationRecord.category_path,
        )
        .outerjoin(
            latest_observation,
            latest_observation.c.tracked_product_id == TrackedProduct.id,
        )
        .outerjoin(
            PriceObservationRecord,
            PriceObservationRecord.id == latest_observation.c.observation_id,
        )
        .where(
            TrackedProduct.active.is_(True),
            TrackedProduct.archived_at.is_(None),
        )
    ):
        category = catalog_category(
            store_slug=store_slug,
            label=title or label,
            category_path=tuple(category_path or ()),
        )
        uncategorized += int(category == "other")

    unique_alerts = len(seen_detections)
    dominant_category = (
        category_counts.most_common(1)[0][0] if category_counts else None
    )
    dominant_count = (
        category_counts[dominant_category] if dominant_category is not None else 0
    )
    dominant_percent = _percentage(dominant_count, unique_alerts)
    return DistributionConcentrationRead(
        window_hours=24,
        unique_alerts=unique_alerts,
        warning_threshold_percent=_CONCENTRATION_WARNING_PERCENT,
        dominant_category=dominant_category,
        dominant_category_label=(
            CATEGORY_LABELS.get(dominant_category)
            if dominant_category is not None
            else None
        ),
        dominant_category_percent=dominant_percent,
        warning=(
            unique_alerts > 0
            and dominant_percent >= _CONCENTRATION_WARNING_PERCENT
        ),
        categories=_distribution_buckets(
            category_counts,
            labels=CATEGORY_LABELS,
        ),
        stores=_distribution_buckets(store_counts),
        uncategorized_catalog_products=uncategorized,
    )


def telegram_distribution_status(
    session: Session,
) -> TelegramDistributionStatusRead:
    """Expose safe multi-destination readiness, coverage, and concentration."""

    now = datetime.now(UTC)
    settings = resolve_runtime_policy(session).settings
    destinations: list[TelegramDestinationStatusRead] = []
    aggregate_counts = {status: 0 for status in _DISTRIBUTION_QUEUE_STATUSES}
    latest_sent: datetime | None = None
    latest_failure: NotificationDelivery | None = None
    for destination in settings.telegram_offer_destinations():
        counts = _queue_counts(session, channel=destination.channel)
        for status, count in counts.items():
            aggregate_counts[status] += count
        last_sent_at = session.scalar(
            select(func.max(NotificationDelivery.sent_at)).where(
                NotificationDelivery.channel == destination.channel,
                NotificationDelivery.status == "sent",
            )
        )
        last_failure = _last_delivery_failure(
            session,
            channel=destination.channel,
        )
        if last_sent_at is not None and (
            latest_sent is None or last_sent_at > latest_sent
        ):
            latest_sent = last_sent_at
        if last_failure is not None and (
            latest_failure is None
            or last_failure.updated_at > latest_failure.updated_at
        ):
            latest_failure = last_failure
        configured = bool(settings.telegram_token and destination.chat_id)
        destinations.append(
            TelegramDestinationStatusRead(
                channel=destination.channel,
                audience=destination.audience,
                dispatch_mode=destination.dispatch_mode,
                configured=configured,
                ready=settings.telegram_enabled and configured,
                queue_counts=counts,
                sent_24h=int(
                    session.scalar(
                        select(func.count(NotificationDelivery.id)).where(
                            NotificationDelivery.channel == destination.channel,
                            NotificationDelivery.status == "sent",
                            NotificationDelivery.sent_at >= now - timedelta(hours=24),
                        )
                    )
                    or 0
                ),
                sent_7d=int(
                    session.scalar(
                        select(func.count(NotificationDelivery.id)).where(
                            NotificationDelivery.channel == destination.channel,
                            NotificationDelivery.status == "sent",
                            NotificationDelivery.sent_at >= now - timedelta(days=7),
                        )
                    )
                    or 0
                ),
                last_sent_at=last_sent_at,
                last_error_at=(
                    last_failure.updated_at if last_failure is not None else None
                ),
                last_error_code=(
                    last_failure.last_error_code
                    if last_failure is not None
                    else None
                ),
                last_error=(
                    last_failure.last_error if last_failure is not None else None
                ),
            )
        )

    primary = next(
        (destination for destination in destinations if destination.audience == "free"),
        None,
    )
    configured = bool(primary and primary.configured)
    ready = bool(primary and primary.ready)
    return TelegramDistributionStatusRead(
        enabled=settings.telegram_enabled,
        configured=configured,
        ready=ready,
        audience_mode=(
            "multi_destination" if len(destinations) > 1 else "single_chat"
        ),
        membership_mode="manual",
        payment_mode="manual_external",
        automatic_offer_delivery=ready,
        queue_counts=aggregate_counts,
        destinations=destinations,
        coverage=_catalog_coverage(session, now=now),
        analysis_backlog=_analysis_backlog(
            session,
            detector_version=settings.detector_version,
            capacity_per_cycle=settings.analysis_limit,
            now=now,
        ),
        concentration=_distribution_concentration(session, now=now),
        last_sent_at=latest_sent,
        last_error_at=(
            latest_failure.updated_at if latest_failure is not None else None
        ),
        last_error_code=(
            latest_failure.last_error_code
            if latest_failure is not None
            else None
        ),
        last_error=(
            latest_failure.last_error if latest_failure is not None else None
        ),
    )


def send_telegram_beta_test(
    session: Session,
    *,
    destination: str = "telegram_free",
    notifier: TelegramNotifier | None = None,
) -> TelegramTestRead:
    """Send one fixed, non-user-controlled message to an allowed destination."""

    settings = resolve_runtime_policy(session).settings
    allowed = {
        item.channel: item for item in settings.telegram_offer_destinations()
    }
    selected = allowed.get(destination.strip().casefold())
    if selected is None:
        raise InvalidCommercialRequestError(
            "destino Telegram desconocido o no habilitado"
        )
    channel = notifier or TelegramNotifier(
        token=settings.telegram_token,
        chat_id=selected.chat_id,
        channel_name=selected.channel,
        enabled=settings.telegram_enabled,
        timeout_seconds=8,
    )
    result = channel.send_text(
        "✅ Bot Ofertas Perú está conectado.\n"
        "Este es un mensaje de prueba del canal beta. "
        "Las ofertas confirmadas llegarán automáticamente aquí."
    )
    return TelegramTestRead(
        destination=selected.channel,
        status=result.status.value,
        sent=result.sent,
        message_id=result.message_id,
        detail=result.detail,
    )


def _effective_subscriber_status(
    subscriber: BetaSubscriber,
    *,
    now: datetime,
) -> str:
    if subscriber.status == "suspended":
        return "suspended"
    if subscriber.expires_at <= now:
        return "expired"
    return subscriber.status


def _subscriber_read(
    subscriber: BetaSubscriber,
    *,
    now: datetime | None = None,
) -> SubscriberRead:
    checked_at = now or datetime.now(UTC)
    remaining_seconds = max(
        0,
        (subscriber.expires_at - checked_at).total_seconds(),
    )
    return SubscriberRead(
        id=subscriber.id,
        full_name=subscriber.full_name,
        telegram_username=subscriber.telegram_username,
        email=subscriber.email,
        phone=subscriber.phone,
        status=_effective_subscriber_status(subscriber, now=checked_at),
        stored_status=subscriber.status,
        telegram_membership_status=subscriber.telegram_membership_status,
        starts_at=subscriber.starts_at,
        expires_at=subscriber.expires_at,
        days_remaining=ceil(remaining_seconds / 86_400),
        notes=subscriber.notes,
        version=subscriber.version,
        created_by=subscriber.created_by,
        created_at=subscriber.created_at,
        updated_at=subscriber.updated_at,
    )


def _subscriber_status_expression(now: datetime):
    return case(
        (BetaSubscriber.status == "suspended", "suspended"),
        (BetaSubscriber.expires_at <= now, "expired"),
        else_=BetaSubscriber.status,
    )


def commercial_summary(session: Session) -> CommercialSummaryRead:
    """Return actionable beta membership, revenue and launch readiness."""

    now = datetime.now(UTC)
    effective_status = _subscriber_status_expression(now)
    status_counts = {
        key: int(value)
        for key, value in session.execute(
            select(effective_status, func.count(BetaSubscriber.id)).group_by(
                effective_status
            )
        )
    }
    active_statuses = ("trial", "active")
    pending_group_access = int(
        session.scalar(
            select(func.count(BetaSubscriber.id)).where(
                effective_status.in_(active_statuses),
                BetaSubscriber.telegram_membership_status == "pending",
            )
        )
        or 0
    )
    members_in_group = int(
        session.scalar(
            select(func.count(BetaSubscriber.id)).where(
                effective_status.in_(active_statuses),
                BetaSubscriber.telegram_membership_status == "in_group",
            )
        )
        or 0
    )
    expiring_within_7_days = int(
        session.scalar(
            select(func.count(BetaSubscriber.id)).where(
                effective_status.in_(active_statuses),
                BetaSubscriber.expires_at > now,
                BetaSubscriber.expires_at <= now + timedelta(days=7),
            )
        )
        or 0
    )

    lima_now = now.astimezone(ZoneInfo("America/Lima"))
    month_start_lima = lima_now.replace(
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    month_start = month_start_lima.astimezone(UTC)
    revenue_total = session.scalar(select(func.sum(BetaPayment.amount)))
    revenue_month = session.scalar(
        select(func.sum(BetaPayment.amount)).where(
            BetaPayment.paid_at >= month_start
        )
    )

    sent_base = (
        NotificationDelivery.channel == "telegram_free",
        NotificationDelivery.status == "sent",
        NotificationDelivery.sent_at.is_not(None),
    )
    alerts_sent_7_days = int(
        session.scalar(
            select(func.count(NotificationDelivery.id)).where(
                *sent_base,
                NotificationDelivery.sent_at >= now - timedelta(days=7),
            )
        )
        or 0
    )
    alerts_sent_30_days = int(
        session.scalar(
            select(func.count(NotificationDelivery.id)).where(
                *sent_base,
                NotificationDelivery.sent_at >= now - timedelta(days=30),
            )
        )
        or 0
    )
    last_alert_sent_at = session.scalar(
        select(func.max(NotificationDelivery.sent_at)).where(*sent_base)
    )

    checklist_required = int(
        session.scalar(
            select(func.count(BetaLaunchChecklistItem.item_key)).where(
                BetaLaunchChecklistItem.required.is_(True)
            )
        )
        or 0
    )
    checklist_completed = int(
        session.scalar(
            select(func.count(BetaLaunchChecklistItem.item_key)).where(
                BetaLaunchChecklistItem.required.is_(True),
                BetaLaunchChecklistItem.completed.is_(True),
            )
        )
        or 0
    )
    runtime_settings = resolve_runtime_policy(session).settings
    telegram_ready = bool(
        runtime_settings.telegram_enabled
        and runtime_settings.telegram_token
        and runtime_settings.effective_telegram_free_chat_id
    )
    return CommercialSummaryRead(
        total_subscribers=sum(status_counts.values()),
        trial_subscribers=status_counts.get("trial", 0),
        active_subscribers=status_counts.get("active", 0),
        expired_subscribers=status_counts.get("expired", 0),
        suspended_subscribers=status_counts.get("suspended", 0),
        pending_group_access=pending_group_access,
        members_in_group=members_in_group,
        expiring_within_7_days=expiring_within_7_days,
        confirmed_revenue_total_pen=revenue_total or Decimal("0"),
        confirmed_revenue_month_pen=revenue_month or Decimal("0"),
        telegram_ready=telegram_ready,
        alerts_sent_7_days=alerts_sent_7_days,
        alerts_sent_30_days=alerts_sent_30_days,
        last_alert_sent_at=last_alert_sent_at,
        checklist_completed=checklist_completed,
        checklist_required=checklist_required,
        launch_ready=(
            telegram_ready
            and checklist_required > 0
            and checklist_completed == checklist_required
        ),
        checked_at=now,
    )


def create_subscriber(
    session: Session,
    *,
    payload: SubscriberCreate,
    created_by: str,
) -> SubscriberRead:
    now = datetime.now(UTC)
    subscriber = BetaSubscriber(
        full_name=payload.full_name,
        telegram_username=payload.telegram_username,
        email=payload.email,
        phone=payload.phone,
        status=payload.status,
        telegram_membership_status=payload.telegram_membership_status,
        starts_at=now,
        expires_at=now + timedelta(days=payload.duration_days),
        notes=payload.notes,
        created_by=created_by,
    )
    session.add(subscriber)
    session.flush()
    return _subscriber_read(subscriber, now=now)


def get_subscriber(
    session: Session,
    *,
    subscriber_id: UUID,
    for_update: bool = False,
) -> BetaSubscriber:
    statement = select(BetaSubscriber).where(BetaSubscriber.id == subscriber_id)
    if for_update:
        statement = statement.with_for_update()
    subscriber = session.scalar(statement)
    if subscriber is None:
        raise SubscriberNotFoundError("suscriptor no encontrado")
    return subscriber


def subscriber(
    session: Session,
    *,
    subscriber_id: UUID,
) -> SubscriberRead:
    return _subscriber_read(
        get_subscriber(session, subscriber_id=subscriber_id)
    )


def list_subscribers(
    session: Session,
    *,
    cursor: str | None,
    limit: int,
    status: str | None,
    membership_status: str | None,
    search: str | None,
) -> Page[SubscriberRead]:
    page_size = _page_size(limit)
    normalized_status = status.strip().lower() if status else None
    normalized_membership = (
        membership_status.strip().lower() if membership_status else None
    )
    normalized_search = _search_term(search)
    scope = cursor_scope(
        "beta-subscribers",
        status=normalized_status,
        membership_status=normalized_membership,
        search=normalized_search,
    )
    now = datetime.now(UTC)
    effective_status = _subscriber_status_expression(now)
    filters = []
    if normalized_status:
        filters.append(effective_status == normalized_status)
    if normalized_membership:
        filters.append(
            BetaSubscriber.telegram_membership_status
            == normalized_membership
        )
    if normalized_search:
        term = f"%{_escaped_like(normalized_search)}%"
        filters.append(
            or_(
                BetaSubscriber.full_name.ilike(term, escape="\\"),
                BetaSubscriber.telegram_username.ilike(term, escape="\\"),
                BetaSubscriber.email.ilike(term, escape="\\"),
                BetaSubscriber.phone.ilike(term, escape="\\"),
            )
        )
    if cursor is not None:
        position = decode_cursor(cursor, scope=scope)
        subscriber_id = _cursor_uuid(position.key)
        filters.append(
            or_(
                BetaSubscriber.created_at < position.timestamp,
                and_(
                    BetaSubscriber.created_at == position.timestamp,
                    BetaSubscriber.id < subscriber_id,
                ),
            )
        )
    rows = list(
        session.scalars(
            select(BetaSubscriber)
            .where(*filters)
            .order_by(
                BetaSubscriber.created_at.desc(),
                BetaSubscriber.id.desc(),
            )
            .limit(page_size + 1)
        )
    )
    has_more = len(rows) > page_size
    visible = rows[:page_size]
    return Page(
        items=[_subscriber_read(item, now=now) for item in visible],
        limit=page_size,
        has_more=has_more,
        next_cursor=(
            encode_cursor(
                scope=scope,
                timestamp=visible[-1].created_at,
                key=str(visible[-1].id),
            )
            if has_more
            else None
        ),
    )


def update_subscriber(
    session: Session,
    *,
    subscriber_id: UUID,
    payload: SubscriberPatch,
    expected_version: int,
) -> SubscriberRead:
    subscriber_row = get_subscriber(
        session,
        subscriber_id=subscriber_id,
        for_update=True,
    )
    if subscriber_row.version != expected_version:
        raise OptimisticConcurrencyError(
            f"expected subscriber version {expected_version}, "
            f"current is {subscriber_row.version}"
        )
    changed = payload.model_fields_set
    for field_name in (
        "full_name",
        "telegram_username",
        "email",
        "phone",
        "status",
        "telegram_membership_status",
        "expires_at",
        "notes",
    ):
        if field_name not in changed:
            continue
        value = getattr(payload, field_name)
        if field_name in {
            "full_name",
            "telegram_username",
            "status",
            "telegram_membership_status",
            "expires_at",
        } and value is None:
            raise InvalidCommercialRequestError(
                f"{field_name} no puede ser null"
            )
        setattr(subscriber_row, field_name, value)
    if subscriber_row.expires_at <= subscriber_row.starts_at:
        raise InvalidCommercialRequestError(
            "expires_at debe ser posterior al inicio de la suscripción"
        )
    subscriber_row.version += 1
    subscriber_row.updated_at = datetime.now(UTC)
    session.flush()
    return _subscriber_read(subscriber_row)


def record_subscriber_payment(
    session: Session,
    *,
    subscriber_id: UUID,
    payload: PaymentCreate,
    recorded_by: str,
    idempotency_key: str,
) -> tuple[PaymentRead, SubscriberRead, bool]:
    subscriber_row = get_subscriber(
        session,
        subscriber_id=subscriber_id,
        for_update=True,
    )
    normalized_key = " ".join(idempotency_key.split())
    if not 8 <= len(normalized_key) <= 512:
        raise InvalidCommercialRequestError(
            "Idempotency-Key debe tener entre 8 y 512 caracteres"
        )
    idempotency_hash = hashlib.sha256(
        normalized_key.encode("utf-8")
    ).hexdigest()
    fingerprint_payload = {
        "subscriber_id": str(subscriber_id),
        "payment": payload.model_dump(mode="json"),
    }
    request_fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    existing = session.scalar(
        select(BetaPayment).where(
            BetaPayment.idempotency_key_hash == idempotency_hash
        )
    )
    if existing is not None:
        if existing.request_fingerprint != request_fingerprint:
            raise IdempotencyConflictError(
                "Idempotency-Key ya se usó con otro pago"
            )
        return (
            PaymentRead.model_validate(existing),
            _subscriber_read(subscriber_row),
            False,
        )
    now = datetime.now(UTC)
    paid_at = payload.paid_at or now
    if paid_at > now + timedelta(minutes=5):
        raise InvalidCommercialRequestError(
            "paid_at no puede estar en el futuro"
        )
    if paid_at < now - timedelta(days=1_825):
        raise InvalidCommercialRequestError(
            "paid_at no puede tener más de cinco años"
        )
    coverage_starts_at = max(now, subscriber_row.expires_at)
    coverage_ends_at = coverage_starts_at + timedelta(
        days=payload.renewal_days
    )
    payment = BetaPayment(
        subscriber_id=subscriber_row.id,
        amount=payload.amount,
        method=payload.method,
        reference=payload.reference,
        paid_at=paid_at,
        coverage_starts_at=coverage_starts_at,
        coverage_ends_at=coverage_ends_at,
        renewal_days=payload.renewal_days,
        notes=payload.notes,
        recorded_by=recorded_by,
        idempotency_key_hash=idempotency_hash,
        request_fingerprint=request_fingerprint,
    )
    session.add(payment)
    subscriber_row.status = "active"
    subscriber_row.expires_at = coverage_ends_at
    if subscriber_row.telegram_membership_status == "removed":
        subscriber_row.telegram_membership_status = "pending"
    subscriber_row.version += 1
    subscriber_row.updated_at = now
    session.flush()
    return (
        PaymentRead.model_validate(payment),
        _subscriber_read(subscriber_row, now=now),
        True,
    )


def list_subscriber_payments(
    session: Session,
    *,
    subscriber_id: UUID,
    limit: int,
) -> list[PaymentRead]:
    get_subscriber(session, subscriber_id=subscriber_id)
    page_size = _page_size(limit)
    rows = session.scalars(
        select(BetaPayment)
        .where(BetaPayment.subscriber_id == subscriber_id)
        .order_by(BetaPayment.paid_at.desc(), BetaPayment.id.desc())
        .limit(page_size)
    )
    return [PaymentRead.model_validate(row) for row in rows]


def list_launch_checklist(
    session: Session,
) -> list[LaunchChecklistItemRead]:
    rows = session.scalars(
        select(BetaLaunchChecklistItem).order_by(
            BetaLaunchChecklistItem.position
        )
    )
    return [LaunchChecklistItemRead.model_validate(row) for row in rows]


def update_launch_checklist_item(
    session: Session,
    *,
    item_key: str,
    payload: LaunchChecklistUpdate,
    changed_by: str,
) -> LaunchChecklistItemRead:
    normalized_key = item_key.strip().lower()
    item = session.scalar(
        select(BetaLaunchChecklistItem)
        .where(BetaLaunchChecklistItem.item_key == normalized_key)
        .with_for_update()
    )
    if item is None:
        raise LaunchChecklistItemNotFoundError(
            "elemento de lanzamiento no encontrado"
        )
    now = datetime.now(UTC)
    item.completed = payload.completed
    item.completed_at = now if payload.completed else None
    item.completed_by = changed_by if payload.completed else None
    item.updated_at = now
    session.flush()
    return LaunchChecklistItemRead.model_validate(item)


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
        analysis_limit=settings.analysis_limit,
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
        verified_list_price_alert_percent=(
            settings.verified_list_price_alert_ratio * Decimal("100")
        ),
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
            settings.telegram_token and settings.effective_telegram_free_chat_id
        ),
        telegram_token_configured=bool(settings.telegram_token),
        telegram_chat_id_configured=bool(
            settings.effective_telegram_free_chat_id
        ),
        telegram_free_chat_id_configured=bool(
            settings.effective_telegram_free_chat_id
        ),
        telegram_vip_chat_id_configured=bool(settings.telegram_vip_chat_id),
        telegram_operations_chat_id_configured=bool(
            settings.effective_telegram_operations_chat_id
        ),
        telegram_vip_mirror_enabled=settings.telegram_vip_mirror_enabled,
    )


def list_discovery_sources(
    session: Session,
    registry: StoreRegistry,
) -> list[DiscoverySourceRead]:
    repository = DiscoveryRepository(session)
    repository.sync_registry(registry)
    counts: dict[UUID, dict[str, int]] = {}
    for source_id, candidate_status, count in session.execute(
        select(
            DiscoveryCandidate.source_id,
            DiscoveryCandidate.status,
            func.count(DiscoveryCandidate.id),
        ).group_by(
            DiscoveryCandidate.source_id,
            DiscoveryCandidate.status,
        )
    ):
        counts.setdefault(source_id, {})[candidate_status] = int(count)
    return [
        DiscoverySourceRead.model_validate(source).model_copy(
            update={"candidate_counts": counts.get(source.id, {})}
        )
        for source in repository.list_sources()
    ]


def request_discovery_run(
    session: Session,
    registry: StoreRegistry,
    *,
    source_id: UUID,
) -> DiscoverySourceRead:
    repository = DiscoveryRepository(session)
    repository.sync_registry(registry)
    try:
        source = repository.request_run(source_id)
    except ValueError as error:
        raise InvalidDiscoveryRequestError(str(error)) from error
    return DiscoverySourceRead.model_validate(source).model_copy(
        update={"candidate_counts": {}}
    )


def list_discovery_candidates(
    session: Session,
    *,
    cursor: str | None,
    limit: int,
    status: str | None,
    store_slug: str | None,
    search: str | None,
) -> Page[DiscoveryCandidateRead]:
    page_size = _page_size(limit)
    normalized_status = status.strip().lower() if status else None
    normalized_store = store_slug.strip().lower() if store_slug else None
    normalized_search = _search_term(search)
    scope = cursor_scope(
        "discovery-candidates",
        status=normalized_status,
        store_slug=normalized_store,
        search=normalized_search,
    )
    filters = []
    if normalized_status:
        filters.append(DiscoveryCandidate.status == normalized_status)
    if normalized_store:
        filters.append(DiscoveryCandidate.store_slug == normalized_store)
    if normalized_search:
        term = f"%{_escaped_like(normalized_search)}%"
        filters.append(
            or_(
                DiscoveryCandidate.label.ilike(term, escape="\\"),
                DiscoveryCandidate.canonical_url.ilike(term, escape="\\"),
            )
        )
    if cursor is not None:
        position = decode_cursor(cursor, scope=scope)
        candidate_id = _cursor_uuid(position.key)
        filters.append(
            or_(
                DiscoveryCandidate.last_seen_at < position.timestamp,
                and_(
                    DiscoveryCandidate.last_seen_at == position.timestamp,
                    DiscoveryCandidate.id < candidate_id,
                ),
            )
        )
    rows = list(
        session.scalars(
            select(DiscoveryCandidate)
            .where(*filters)
            .order_by(
                DiscoveryCandidate.last_seen_at.desc(),
                DiscoveryCandidate.id.desc(),
            )
            .limit(page_size + 1)
        )
    )
    has_more = len(rows) > page_size
    visible = rows[:page_size]
    return Page(
        items=[
            DiscoveryCandidateRead.model_validate(candidate)
            for candidate in visible
        ],
        limit=page_size,
        has_more=has_more,
        next_cursor=(
            encode_cursor(
                scope=scope,
                timestamp=visible[-1].last_seen_at,
                key=str(visible[-1].id),
            )
            if has_more
            else None
        ),
    )


def list_discovery_runs(
    session: Session,
    *,
    limit: int,
    store_slug: str | None,
) -> list[DiscoveryRunRead]:
    page_size = _page_size(limit)
    statement = select(DiscoveryRun)
    if store_slug:
        statement = statement.where(
            DiscoveryRun.store_slug == store_slug.strip().lower()
        )
    runs = session.scalars(
        statement.order_by(
            DiscoveryRun.started_at.desc(),
            DiscoveryRun.id.desc(),
        ).limit(page_size)
    )
    return [DiscoveryRunRead.model_validate(run) for run in runs]


def review_discovery_candidate(
    session: Session,
    registry: StoreRegistry,
    *,
    candidate_id: UUID,
    payload: DiscoveryReview,
    reviewed_by: str,
) -> DiscoveryCandidateRead:
    repository = DiscoveryRepository(session)
    try:
        if payload.action == "approve":
            candidate = repository.approve_candidate(
                candidate_id,
                reviewed_by=reviewed_by,
                registry=registry,
                label=payload.label,
            )
        else:
            candidate = repository.reject_candidate(
                candidate_id,
                reviewed_by=reviewed_by,
                reason=payload.reason or "",
            )
    except ValueError as error:
        raise InvalidDiscoveryRequestError(str(error)) from error
    return DiscoveryCandidateRead.model_validate(candidate)


def bulk_review_discovery_candidates(
    session: Session,
    registry: StoreRegistry,
    *,
    payload: DiscoveryBulkReview,
    reviewed_by: str,
) -> list[DiscoveryCandidateRead]:
    results: list[DiscoveryCandidateRead] = []
    for candidate_id in payload.candidate_ids:
        results.append(
            review_discovery_candidate(
                session,
                registry,
                candidate_id=candidate_id,
                payload=DiscoveryReview(
                    action=payload.action,
                    label=payload.label,
                    reason=payload.reason,
                ),
                reviewed_by=reviewed_by,
            )
        )
    return results


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
    "InvalidCommercialRequestError",
    "InvalidCrawlJobRequestError",
    "InvalidDiscoveryRequestError",
    "InvalidRuntimePolicyError",
    "LaunchChecklistItemNotFoundError",
    "ProductNotFoundError",
    "SubscriberNotFoundError",
    "UnsafeProductConfigurationError",
    "archive_product",
    "bulk_review_discovery_candidates",
    "cancel_crawl_job",
    "commercial_summary",
    "create_product",
    "create_subscriber",
    "enqueue_crawl_job",
    "get_crawl_job",
    "get_product",
    "list_launch_checklist",
    "list_confirmations",
    "list_crawl_jobs",
    "list_crawl_runs",
    "list_discovery_candidates",
    "list_discovery_runs",
    "list_discovery_sources",
    "list_observations",
    "list_offers",
    "list_products",
    "list_subscriber_payments",
    "list_subscribers",
    "list_stores",
    "runtime_policy",
    "request_discovery_run",
    "record_subscriber_payment",
    "review_discovery_candidate",
    "set_product_activation",
    "set_product_variant",
    "subscriber",
    "update_launch_checklist_item",
    "update_runtime_policy",
    "update_product",
    "update_subscriber",
]
