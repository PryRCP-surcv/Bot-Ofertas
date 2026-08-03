"""Versioned HTTP routes backed by the administration application service."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from bot_ofertas.api.dependencies import (
    AdminDependency,
    RegistryDependency,
    SessionDependency,
    require_admin,
)
from bot_ofertas.api.schemas import (
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
    HealthRead,
    LaunchChecklistItemRead,
    LaunchChecklistUpdate,
    ObservationRead,
    OfferRead,
    OperationsStatusRead,
    Page,
    PaymentCreate,
    PaymentRead,
    PaymentRecordRead,
    ProductActivation,
    ProductCreate,
    ProductPatch,
    ProductRead,
    ProductVariant,
    RuntimePolicyPatch,
    RuntimePolicyRead,
    StoreRead,
    SubscriberCreate,
    SubscriberPatch,
    SubscriberRead,
    TelegramDistributionStatusRead,
    TelegramTestRead,
)
from bot_ofertas.api.service import (
    archive_product,
    bulk_review_discovery_candidates,
    cancel_crawl_job,
    commercial_summary,
    create_product,
    create_subscriber,
    enqueue_crawl_job,
    get_crawl_job,
    get_product,
    list_confirmations,
    list_crawl_jobs,
    list_crawl_runs,
    list_discovery_candidates,
    list_discovery_runs,
    list_discovery_sources,
    list_launch_checklist,
    list_observations,
    list_offers,
    list_products,
    list_stores,
    list_subscriber_payments,
    list_subscribers,
    operations_status,
    record_subscriber_payment,
    request_discovery_run,
    review_discovery_candidate,
    runtime_policy,
    send_telegram_beta_test,
    set_product_activation,
    set_product_variant,
    subscriber,
    telegram_distribution_status,
    update_launch_checklist_item,
    update_product,
    update_runtime_policy,
    update_subscriber,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_LIMIT = 25

public_router = APIRouter(tags=["health"])
api_router = APIRouter(
    prefix="/api/v1",
    dependencies=[Depends(require_admin)],
)

Cursor = Annotated[str | None, Query(max_length=1_024)]
Limit = Annotated[int, Query(ge=1, le=100)]


def _revision_etag(revision_id: int | None) -> str:
    return f'"{revision_id or 0}"'


def _expected_revision(if_match: str | None) -> int | None:
    if if_match is None:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail="If-Match es obligatorio para cambiar la configuración.",
        )
    normalized = if_match.strip()
    if normalized.startswith('W/"') or normalized == "*":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="If-Match debe contener una revisión fuerte y exacta.",
        )
    if len(normalized) >= 2 and normalized[0] == normalized[-1] == '"':
        normalized = normalized[1:-1]
    try:
        revision = int(normalized)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="If-Match no contiene una revisión válida.",
        ) from error
    if revision < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="If-Match no contiene una revisión válida.",
        )
    return revision or None


def _expected_product_version(if_match: str | None) -> int:
    version = _expected_revision(if_match)
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="If-Match debe contener una versión de producto positiva.",
        )
    return version


def _expected_subscriber_version(if_match: str | None) -> int:
    version = _expected_revision(if_match)
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="If-Match debe contener una versión de suscriptor positiva.",
        )
    return version


@lru_cache(maxsize=1)
def _expected_migration_heads() -> frozenset[str]:
    config = Config(str(_PROJECT_ROOT / "alembic.ini"))
    return frozenset(ScriptDirectory.from_config(config).get_heads())


@public_router.get(
    "/health/live",
    response_model=HealthRead,
    summary="Comprueba que el proceso HTTP está vivo",
)
def health_live() -> HealthRead:
    return HealthRead(status="ok")


@public_router.get(
    "/health/ready",
    response_model=HealthRead,
    summary="Comprueba base de datos, migraciones y adaptadores",
)
def health_ready(request: Request, registry: RegistryDependency) -> HealthRead:
    try:
        expected_heads = _expected_migration_heads()
    except (CommandError, OSError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo comprobar la revisión requerida de la base de datos.",
        ) from error
    try:
        with request.app.state.session_factory() as session:
            session.execute(text("SELECT 1")).scalar_one()
            database_heads = frozenset(
                session.execute(text("SELECT version_num FROM alembic_version")).scalars()
            )
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="La base de datos no está disponible.",
        ) from error

    if not expected_heads or database_heads != expected_heads:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="La base de datos no está en la revisión de migración requerida.",
        )
    if not registry.enabled_adapters or registry.plugin_errors:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Los adaptadores de tiendas no están listos.",
        )
    return HealthRead(status="ready", database="ready")


@api_router.get(
    "/operations/status",
    response_model=OperationsStatusRead,
    tags=["operations"],
    summary="Estado persistente del monitor y su cola activa",
)
def operation_status(session: SessionDependency) -> OperationsStatusRead:
    return operations_status(session)


@api_router.get(
    "/stores",
    response_model=list[StoreRead],
    tags=["stores"],
)
def stores(
    session: SessionDependency,
    registry: RegistryDependency,
) -> list[StoreRead]:
    return list_stores(session, registry)


@api_router.get(
    "/products",
    response_model=Page[ProductRead],
    tags=["products"],
)
def products(
    session: SessionDependency,
    cursor: Cursor = None,
    limit: Limit = _DEFAULT_LIMIT,
    store_slug: Annotated[str | None, Query(max_length=64)] = None,
    active: bool | None = None,
    archived: bool = False,
    search: Annotated[str | None, Query(max_length=100)] = None,
) -> Page[ProductRead]:
    return list_products(
        session,
        cursor=cursor,
        limit=limit,
        store_slug=store_slug,
        active=active,
        archived=archived,
        search=search,
    )


@api_router.post(
    "/products",
    response_model=ProductRead,
    status_code=status.HTTP_201_CREATED,
    tags=["products"],
)
def add_product(
    payload: ProductCreate,
    session: SessionDependency,
    registry: RegistryDependency,
    response: Response,
) -> ProductRead:
    product = create_product(session, registry, payload)
    result = ProductRead.model_validate(product)
    response.headers["ETag"] = _revision_etag(result.version)
    return result


@api_router.get(
    "/products/{product_id}",
    response_model=ProductRead,
    tags=["products"],
)
def product(
    product_id: UUID,
    session: SessionDependency,
    response: Response,
) -> ProductRead:
    result = ProductRead.model_validate(get_product(session, product_id))
    response.headers["ETag"] = _revision_etag(result.version)
    return result


@api_router.patch(
    "/products/{product_id}",
    response_model=ProductRead,
    tags=["products"],
)
def patch_product(
    product_id: UUID,
    payload: ProductPatch,
    session: SessionDependency,
    registry: RegistryDependency,
    response: Response,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> ProductRead:
    updated = update_product(
        session,
        registry,
        product_id,
        payload,
        expected_version=_expected_product_version(if_match),
    )
    result = ProductRead.model_validate(updated)
    response.headers["ETag"] = _revision_etag(result.version)
    return result


@api_router.delete(
    "/products/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["products"],
)
def delete_product(
    product_id: UUID,
    session: SessionDependency,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> Response:
    archive_product(
        session,
        product_id,
        expected_version=_expected_product_version(if_match),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@api_router.put(
    "/products/{product_id}/activation",
    response_model=ProductRead,
    tags=["products"],
)
def product_activation(
    product_id: UUID,
    payload: ProductActivation,
    session: SessionDependency,
    response: Response,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> ProductRead:
    updated = set_product_activation(
        session,
        product_id,
        payload,
        expected_version=_expected_product_version(if_match),
    )
    result = ProductRead.model_validate(updated)
    response.headers["ETag"] = _revision_etag(result.version)
    return result


@api_router.put(
    "/products/{product_id}/variant",
    response_model=ProductRead,
    tags=["products"],
)
def product_variant(
    product_id: UUID,
    payload: ProductVariant,
    session: SessionDependency,
    response: Response,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> ProductRead:
    updated = set_product_variant(
        session,
        product_id,
        payload,
        expected_version=_expected_product_version(if_match),
    )
    result = ProductRead.model_validate(updated)
    response.headers["ETag"] = _revision_etag(result.version)
    return result


@api_router.delete(
    "/products/{product_id}/variant",
    response_model=ProductRead,
    tags=["products"],
)
def clear_product_variant(
    product_id: UUID,
    session: SessionDependency,
    response: Response,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> ProductRead:
    updated = set_product_variant(
        session,
        product_id,
        None,
        expected_version=_expected_product_version(if_match),
    )
    result = ProductRead.model_validate(updated)
    response.headers["ETag"] = _revision_etag(result.version)
    return result


@api_router.get(
    "/observations",
    response_model=Page[ObservationRead],
    tags=["observations"],
)
def observations(
    product_id: UUID,
    session: SessionDependency,
    cursor: Cursor = None,
    limit: Limit = _DEFAULT_LIMIT,
) -> Page[ObservationRead]:
    return list_observations(
        session,
        product_id=product_id,
        cursor=cursor,
        limit=limit,
    )


@api_router.get(
    "/products/{product_id}/observations",
    response_model=Page[ObservationRead],
    tags=["observations"],
)
def product_observations(
    product_id: UUID,
    session: SessionDependency,
    cursor: Cursor = None,
    limit: Limit = 50,
) -> Page[ObservationRead]:
    return list_observations(
        session,
        product_id=product_id,
        cursor=cursor,
        limit=limit,
    )


@api_router.get(
    "/offers",
    response_model=Page[OfferRead],
    tags=["offers"],
)
def offers(
    session: SessionDependency,
    cursor: Cursor = None,
    limit: Limit = _DEFAULT_LIMIT,
    classification: Annotated[str | None, Query(max_length=64)] = None,
    store_slug: Annotated[str | None, Query(max_length=64)] = None,
    notification_status: Annotated[str | None, Query(max_length=64)] = None,
    include_rejected: bool = False,
    offer_state: Annotated[
        Literal["active", "awaiting", "history"],
        Query(alias="state"),
    ] = "active",
) -> Page[OfferRead]:
    return list_offers(
        session,
        cursor=cursor,
        limit=limit,
        classification=classification,
        store_slug=store_slug,
        notification_status=notification_status,
        include_rejected=include_rejected,
        state=offer_state,
    )


@api_router.get(
    "/confirmations",
    response_model=Page[ConfirmationRead],
    tags=["confirmations"],
)
def confirmations(
    session: SessionDependency,
    cursor: Cursor = None,
    limit: Limit = _DEFAULT_LIMIT,
    active_only: bool = True,
) -> Page[ConfirmationRead]:
    return list_confirmations(
        session,
        cursor=cursor,
        limit=limit,
        active_only=active_only,
    )


@api_router.get(
    "/crawl-runs",
    response_model=Page[CrawlRunRead],
    tags=["crawl-runs"],
)
def crawl_runs(
    session: SessionDependency,
    cursor: Cursor = None,
    limit: Limit = _DEFAULT_LIMIT,
    store_slug: Annotated[str | None, Query(max_length=64)] = None,
    run_status: Annotated[
        Literal["running", "succeeded", "partial", "failed", "cancelled"] | None,
        Query(alias="status", max_length=64),
    ] = None,
) -> Page[CrawlRunRead]:
    return list_crawl_runs(
        session,
        cursor=cursor,
        limit=limit,
        store_slug=store_slug,
        status=run_status,
    )


@api_router.post(
    "/crawl-jobs",
    response_model=CrawlJobRead,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["crawl-jobs"],
)
def create_crawl_job(
    payload: CrawlJobCreate,
    session: SessionDependency,
    admin: AdminDependency,
    registry: RegistryDependency,
    response: Response,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=512),
    ],
) -> CrawlJobRead:
    job, inserted = enqueue_crawl_job(
        session,
        registry=registry,
        payload=payload,
        requested_by=admin.subject,
        idempotency_key=idempotency_key,
    )
    response.headers["Location"] = f"/api/v1/crawl-jobs/{job.id}"
    if not inserted:
        response.headers["X-Idempotent-Replay"] = "true"
    return CrawlJobRead.model_validate(job)


@api_router.get(
    "/crawl-jobs",
    response_model=Page[CrawlJobRead],
    tags=["crawl-jobs"],
)
def crawl_jobs(
    session: SessionDependency,
    cursor: Cursor = None,
    limit: Limit = _DEFAULT_LIMIT,
    job_status: Annotated[
        Literal[
            "queued",
            "running",
            "retrying",
            "succeeded",
            "partial",
            "failed",
            "cancelled",
        ]
        | None,
        Query(alias="status"),
    ] = None,
) -> Page[CrawlJobRead]:
    return list_crawl_jobs(
        session,
        cursor=cursor,
        limit=limit,
        status=job_status,
    )


@api_router.get(
    "/crawl-jobs/{job_id}",
    response_model=CrawlJobRead,
    tags=["crawl-jobs"],
)
def crawl_job(job_id: UUID, session: SessionDependency) -> CrawlJobRead:
    return CrawlJobRead.model_validate(get_crawl_job(session, job_id))


@api_router.post(
    "/crawl-jobs/{job_id}/cancel",
    response_model=CrawlJobRead,
    tags=["crawl-jobs"],
)
def cancel_job(
    job_id: UUID,
    session: SessionDependency,
    admin: AdminDependency,
) -> CrawlJobRead:
    return CrawlJobRead.model_validate(
        cancel_crawl_job(
            session,
            job_id=job_id,
            requested_by=admin.subject,
        )
    )


@api_router.get(
    "/discovery/sources",
    response_model=list[DiscoverySourceRead],
    tags=["discovery"],
)
def discovery_sources(
    session: SessionDependency,
    registry: RegistryDependency,
) -> list[DiscoverySourceRead]:
    return list_discovery_sources(session, registry)


@api_router.post(
    "/discovery/sources/{source_id}/run",
    response_model=DiscoverySourceRead,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["discovery"],
)
def schedule_discovery_source(
    source_id: UUID,
    session: SessionDependency,
    registry: RegistryDependency,
) -> DiscoverySourceRead:
    return request_discovery_run(
        session,
        registry,
        source_id=source_id,
    )


@api_router.get(
    "/discovery/candidates",
    response_model=Page[DiscoveryCandidateRead],
    tags=["discovery"],
)
def discovery_candidates(
    session: SessionDependency,
    cursor: Cursor = None,
    limit: Limit = _DEFAULT_LIMIT,
    candidate_status: Annotated[
        Literal[
            "pending",
            "approved",
            "rejected",
            "duplicate",
            "policy_blocked",
            "unavailable",
        ]
        | None,
        Query(alias="status"),
    ] = "pending",
    store_slug: Annotated[str | None, Query(max_length=64)] = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
) -> Page[DiscoveryCandidateRead]:
    return list_discovery_candidates(
        session,
        cursor=cursor,
        limit=limit,
        status=candidate_status,
        store_slug=store_slug,
        search=search,
    )


@api_router.get(
    "/discovery/runs",
    response_model=list[DiscoveryRunRead],
    tags=["discovery"],
)
def discovery_runs(
    session: SessionDependency,
    limit: Limit = _DEFAULT_LIMIT,
    store_slug: Annotated[str | None, Query(max_length=64)] = None,
) -> list[DiscoveryRunRead]:
    return list_discovery_runs(
        session,
        limit=limit,
        store_slug=store_slug,
    )


@api_router.get(
    "/distribution/telegram",
    response_model=TelegramDistributionStatusRead,
    tags=["distribution"],
)
def telegram_distribution(
    session: SessionDependency,
) -> TelegramDistributionStatusRead:
    return telegram_distribution_status(session)


@api_router.post(
    "/distribution/telegram/test",
    response_model=TelegramTestRead,
    tags=["distribution"],
)
def test_telegram_distribution(
    session: SessionDependency,
    _admin: AdminDependency,
    destination: Annotated[
        Literal["telegram_free", "telegram_vip"],
        Query(),
    ] = "telegram_free",
) -> TelegramTestRead:
    return send_telegram_beta_test(session, destination=destination)


@api_router.get(
    "/commercial/summary",
    response_model=CommercialSummaryRead,
    tags=["commercial-beta"],
)
def beta_commercial_summary(
    session: SessionDependency,
) -> CommercialSummaryRead:
    return commercial_summary(session)


@api_router.get(
    "/commercial/checklist",
    response_model=list[LaunchChecklistItemRead],
    tags=["commercial-beta"],
)
def beta_launch_checklist(
    session: SessionDependency,
) -> list[LaunchChecklistItemRead]:
    return list_launch_checklist(session)


@api_router.put(
    "/commercial/checklist/{item_key}",
    response_model=LaunchChecklistItemRead,
    tags=["commercial-beta"],
)
def set_beta_launch_checklist_item(
    item_key: str,
    payload: LaunchChecklistUpdate,
    session: SessionDependency,
    admin: AdminDependency,
) -> LaunchChecklistItemRead:
    return update_launch_checklist_item(
        session,
        item_key=item_key,
        payload=payload,
        changed_by=admin.subject,
    )


@api_router.get(
    "/subscribers",
    response_model=Page[SubscriberRead],
    tags=["subscribers"],
)
def subscribers(
    session: SessionDependency,
    cursor: Cursor = None,
    limit: Limit = _DEFAULT_LIMIT,
    subscriber_status: Annotated[
        Literal["trial", "active", "expired", "suspended"] | None,
        Query(alias="status"),
    ] = None,
    membership_status: Annotated[
        Literal["pending", "in_group", "removed"] | None,
        Query(),
    ] = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
) -> Page[SubscriberRead]:
    return list_subscribers(
        session,
        cursor=cursor,
        limit=limit,
        status=subscriber_status,
        membership_status=membership_status,
        search=search,
    )


@api_router.post(
    "/subscribers",
    response_model=SubscriberRead,
    status_code=status.HTTP_201_CREATED,
    tags=["subscribers"],
)
def add_subscriber(
    payload: SubscriberCreate,
    session: SessionDependency,
    admin: AdminDependency,
    response: Response,
) -> SubscriberRead:
    created = create_subscriber(
        session,
        payload=payload,
        created_by=admin.subject,
    )
    response.headers["Location"] = f"/api/v1/subscribers/{created.id}"
    response.headers["ETag"] = _revision_etag(created.version)
    return created


@api_router.get(
    "/subscribers/{subscriber_id}",
    response_model=SubscriberRead,
    tags=["subscribers"],
)
def get_beta_subscriber(
    subscriber_id: UUID,
    session: SessionDependency,
    response: Response,
) -> SubscriberRead:
    result = subscriber(session, subscriber_id=subscriber_id)
    response.headers["ETag"] = _revision_etag(result.version)
    return result


@api_router.patch(
    "/subscribers/{subscriber_id}",
    response_model=SubscriberRead,
    tags=["subscribers"],
)
def patch_beta_subscriber(
    subscriber_id: UUID,
    payload: SubscriberPatch,
    session: SessionDependency,
    response: Response,
    _admin: AdminDependency,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> SubscriberRead:
    result = update_subscriber(
        session,
        subscriber_id=subscriber_id,
        payload=payload,
        expected_version=_expected_subscriber_version(if_match),
    )
    response.headers["ETag"] = _revision_etag(result.version)
    return result


@api_router.get(
    "/subscribers/{subscriber_id}/payments",
    response_model=list[PaymentRead],
    tags=["subscribers"],
)
def subscriber_payments(
    subscriber_id: UUID,
    session: SessionDependency,
    limit: Limit = _DEFAULT_LIMIT,
) -> list[PaymentRead]:
    return list_subscriber_payments(
        session,
        subscriber_id=subscriber_id,
        limit=limit,
    )


@api_router.post(
    "/subscribers/{subscriber_id}/payments",
    response_model=PaymentRecordRead,
    status_code=status.HTTP_201_CREATED,
    tags=["subscribers"],
)
def add_subscriber_payment(
    subscriber_id: UUID,
    payload: PaymentCreate,
    session: SessionDependency,
    admin: AdminDependency,
    response: Response,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=512),
    ],
) -> PaymentRecordRead:
    payment, renewed_subscriber, inserted = record_subscriber_payment(
        session,
        subscriber_id=subscriber_id,
        payload=payload,
        recorded_by=admin.subject,
        idempotency_key=idempotency_key,
    )
    response.headers["Location"] = (
        f"/api/v1/subscribers/{subscriber_id}/payments"
    )
    response.headers["ETag"] = _revision_etag(renewed_subscriber.version)
    if not inserted:
        response.headers["X-Idempotent-Replay"] = "true"
    return PaymentRecordRead(
        payment=payment,
        subscriber=renewed_subscriber,
    )


@api_router.post(
    "/discovery/candidates/{candidate_id}/review",
    response_model=DiscoveryCandidateRead,
    tags=["discovery"],
)
def review_discovery(
    candidate_id: UUID,
    payload: DiscoveryReview,
    session: SessionDependency,
    registry: RegistryDependency,
    admin: AdminDependency,
) -> DiscoveryCandidateRead:
    return review_discovery_candidate(
        session,
        registry,
        candidate_id=candidate_id,
        payload=payload,
        reviewed_by=admin.subject,
    )


@api_router.post(
    "/discovery/candidates/review",
    response_model=list[DiscoveryCandidateRead],
    tags=["discovery"],
)
def bulk_review_discovery(
    payload: DiscoveryBulkReview,
    session: SessionDependency,
    registry: RegistryDependency,
    admin: AdminDependency,
) -> list[DiscoveryCandidateRead]:
    return bulk_review_discovery_candidates(
        session,
        registry,
        payload=payload,
        reviewed_by=admin.subject,
    )


@api_router.get(
    "/settings",
    response_model=RuntimePolicyRead,
    tags=["settings"],
)
def settings(
    session: SessionDependency,
    response: Response,
) -> RuntimePolicyRead:
    policy = runtime_policy(session)
    response.headers["ETag"] = _revision_etag(policy.revision_id)
    return policy


@api_router.patch(
    "/settings",
    response_model=RuntimePolicyRead,
    tags=["settings"],
)
def patch_settings(
    payload: RuntimePolicyPatch,
    session: SessionDependency,
    admin: AdminDependency,
    response: Response,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", min_length=8, max_length=512),
    ] = None,
    change_reason: Annotated[
        str | None,
        Header(alias="X-Change-Reason", max_length=2_000),
    ] = None,
) -> RuntimePolicyRead:
    policy, inserted = update_runtime_policy(
        session,
        payload=payload,
        expected_revision=_expected_revision(if_match),
        changed_by=admin.subject,
        change_reason=change_reason,
        idempotency_key=idempotency_key,
    )
    response.headers["ETag"] = _revision_etag(policy.revision_id)
    if not inserted:
        response.headers["X-Idempotent-Replay"] = "true"
    return policy


__all__ = ["api_router", "public_router"]
