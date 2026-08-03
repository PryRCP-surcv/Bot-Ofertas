"""Versioned request and response contracts for the administration API."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)

from bot_ofertas.detection import canonicalize_variant


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page[ItemT](ApiModel):
    items: list[ItemT]
    limit: int = Field(ge=1, le=100)
    has_more: bool
    next_cursor: str | None = None


class HealthRead(ApiModel):
    status: str
    service: str = "bot-ofertas-api"
    database: str | None = None


class WorkerOperationsRead(ApiModel):
    state: Literal["running", "stale", "stopped", "unknown"]
    instance_id: UUID | None
    started_at: datetime | None
    last_heartbeat_at: datetime | None
    heartbeat_age_seconds: int | None = Field(default=None, ge=0)
    stale_after_seconds: int | None = Field(default=None, ge=30, le=86_400)
    last_cycle_started_at: datetime | None
    last_cycle_finished_at: datetime | None
    last_cycle_status: Literal["running", "succeeded", "failed"] | None
    last_error: str | None
    message: str


class QueueOperationsRead(ApiModel):
    queued: int = Field(ge=0)
    running: int = Field(ge=0)
    retrying: int = Field(ge=0)


class OperationsStatusRead(ApiModel):
    worker: WorkerOperationsRead
    queue: QueueOperationsRead
    checked_at: datetime


def _normalize_variant(value: dict[str, str]) -> dict[str, str]:
    if len(value) > 20:
        raise ValueError("expected_variant admite como máximo 20 atributos")
    normalized: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = " ".join(raw_key.split())
        variant_value = " ".join(raw_value.split())
        if not key or not variant_value:
            raise ValueError("las claves y valores de expected_variant no pueden estar vacíos")
        if len(key) > 100 or len(variant_value) > 300:
            raise ValueError("expected_variant contiene una clave o valor demasiado largo")
        normalized[key] = variant_value
    try:
        return canonicalize_variant(normalized)
    except ValueError as error:
        raise ValueError(
            "expected_variant contiene atributos duplicados tras normalizar"
        ) from error


class StoreRead(ApiModel):
    slug: str
    display_name: str
    hosts: list[str]
    enabled: bool
    minimum_interval_minutes: int
    max_targets_per_run: int
    requires_explicit_product_url: bool
    notes: str
    health: str
    paused_until: datetime | None = None
    pause_reason: str | None = None
    consecutive_blocks: int = 0
    tracked_products: int = 0
    active_products: int = 0
    last_run_id: UUID | None = None
    last_run_status: str | None = None
    last_run_started_at: datetime | None = None
    last_run_finished_at: datetime | None = None


class ProductCreate(ApiModel):
    url: HttpUrl
    label: str = Field(min_length=1, max_length=500)
    expected_brand: str | None = Field(default=None, max_length=200)
    expected_model: str | None = Field(default=None, max_length=300)
    expected_variant: dict[str, str] = Field(default_factory=dict)
    expected_is_accessory: bool = False
    check_interval_minutes: int = Field(default=60, ge=30, le=525_600)
    active: bool = True

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("label no puede estar vacío")
        return normalized

    @field_validator("expected_brand", "expected_model")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized or None

    @field_validator("expected_variant")
    @classmethod
    def normalize_variant(cls, value: dict[str, str]) -> dict[str, str]:
        return _normalize_variant(value)


class ProductPatch(ApiModel):
    label: str | None = Field(default=None, min_length=1, max_length=500)
    expected_brand: str | None = Field(default=None, max_length=200)
    expected_model: str | None = Field(default=None, max_length=300)
    expected_is_accessory: bool | None = None
    check_interval_minutes: int | None = Field(default=None, ge=30, le=525_600)

    @model_validator(mode="after")
    def require_change(self) -> ProductPatch:
        if not self.model_fields_set:
            raise ValueError("se requiere al menos un campo para actualizar")
        return self

    @field_validator("label")
    @classmethod
    def normalize_optional_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("label no puede estar vacío")
        return normalized

    @field_validator("expected_brand", "expected_model")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized or None


class ProductRead(ApiModel):
    id: UUID
    store_slug: str
    source_url: str
    label: str
    expected_brand: str | None
    expected_model: str | None
    expected_variant: dict[str, str]
    expected_is_accessory: bool
    active: bool
    version: int
    archived_at: datetime | None
    check_interval_minutes: int
    last_checked_at: datetime | None
    last_success_at: datetime | None
    consecutive_failures: int
    created_at: datetime
    updated_at: datetime


class ProductActivation(ApiModel):
    active: bool


class ProductVariant(ApiModel):
    expected_variant: dict[str, str]

    @field_validator("expected_variant")
    @classmethod
    def require_variant(cls, value: dict[str, str]) -> dict[str, str]:
        if not value:
            raise ValueError("expected_variant no puede estar vacío")
        return _normalize_variant(value)


class ObservationRead(ApiModel):
    id: int
    tracked_product_id: UUID | None
    run_id: UUID
    store_slug: str
    source_url: str
    external_product_id: str
    sku: str
    seller_id: str
    seller_name: str
    title: str
    brand: str | None
    model: str | None
    image_url: str | None
    variant: dict[str, str]
    condition: str
    currency: str
    price: Decimal | None
    list_price: Decimal | None
    availability: str
    available_quantity: int | None
    is_marketplace: bool
    installments: list[dict[str, object]]
    quality_flags: list[str]
    observed_at: datetime


class OfferRead(ApiModel):
    id: int
    observation_id: int
    tracked_product_id: UUID | None
    product_label: str
    title: str
    store_slug: str
    source_url: str
    detector_version: str
    policy_fingerprint: str
    config_revision_id: int | None
    classification: str
    eligible: bool
    score: int
    confidence_score: int
    confidence_level: str
    currency: str
    current_price: Decimal | None
    reference_price: Decimal | None
    discount_percent: Decimal | None
    primary_signal_kind: str | None
    signals: dict[str, object]
    notification_status: str
    confirmation_status: str
    confirmation_count: int
    reasons: list[str]
    rejection_reasons: list[str]
    quality_flags: list[str]
    detected_at: datetime


class ConfirmationRead(ApiModel):
    offer_key: str
    tracked_product_id: UUID | None
    product_label: str | None
    candidate_detection_id: int | None
    candidate_classification: str
    candidate_price: Decimal
    confirmation_count: int
    first_seen_at: datetime
    last_seen_at: datetime
    expires_at: datetime


class CrawlRunRead(ApiModel):
    id: UUID
    store_slug: str
    spider_name: str
    status: str
    requested_url_count: int
    observation_count: int
    error_count: int
    error_summary: str | None
    started_at: datetime
    finished_at: datetime | None


class CrawlJobCreate(ApiModel):
    product_ids: list[UUID] = Field(min_length=1, max_length=20)

    @field_validator("product_ids")
    @classmethod
    def unique_products(cls, value: list[UUID]) -> list[UUID]:
        if len(set(value)) != len(value):
            raise ValueError("product_ids no puede contener duplicados")
        return value


class CrawlJobItemRead(ApiModel):
    id: int
    tracked_product_id: UUID
    crawl_run_id: UUID | None
    store_slug: str
    source_url: str
    label: str
    status: str
    attempt_count: int
    started_at: datetime | None
    finished_at: datetime | None
    last_error_code: str | None
    last_error: str | None
    result: dict[str, object]


class CrawlJobRead(ApiModel):
    id: UUID
    status: str
    request_source: str
    requested_by: str
    request_payload: dict[str, object]
    priority: int
    max_attempts: int
    attempt_count: int
    next_attempt_at: datetime
    config_revision_id: int | None
    started_at: datetime | None
    finished_at: datetime | None
    cancel_requested_at: datetime | None
    last_error_code: str | None
    last_error: str | None
    result: dict[str, object]
    created_at: datetime
    updated_at: datetime
    items: list[CrawlJobItemRead]


class DiscoverySourceRead(ApiModel):
    id: UUID
    store_slug: str
    source_key: str
    source_type: str
    source_url: str
    enabled: bool
    minimum_interval_minutes: int
    max_documents_per_run: int
    max_candidates_per_run: int
    daily_approval_limit: int
    active_product_limit: int
    url_entry_filter: str
    notes: str
    scan_cursor: int
    next_run_at: datetime
    last_started_at: datetime | None
    last_finished_at: datetime | None
    last_status: str
    last_error_code: str | None
    last_error: str | None
    version: int
    candidate_counts: dict[str, int] = Field(default_factory=dict)


class DiscoveryRunRead(ApiModel):
    id: UUID
    source_id: UUID
    store_slug: str
    status: str
    requested_by: str
    document_count: int
    candidate_count: int
    new_count: int
    duplicate_count: int
    rejected_count: int
    error_count: int
    error_code: str | None
    error_summary: str | None
    stats: dict[str, object]
    started_at: datetime
    finished_at: datetime | None


class DiscoveryCandidateRead(ApiModel):
    id: UUID
    source_id: UUID
    latest_run_id: UUID
    tracked_product_id: UUID | None
    store_slug: str
    discovered_url: str
    canonical_url: str
    label: str
    status: str
    reason: str | None
    discovery_metadata: dict[str, object]
    first_seen_at: datetime
    last_seen_at: datetime
    reviewed_by: str | None
    reviewed_at: datetime | None
    version: int


class DiscoveryReview(ApiModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["approve", "reject"]
    label: str | None = Field(default=None, max_length=500)
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_action_fields(self) -> DiscoveryReview:
        if self.action == "reject" and not (self.reason or "").strip():
            raise ValueError("reason es obligatorio al rechazar")
        if self.action == "approve" and self.reason is not None:
            raise ValueError("reason no aplica al aprobar")
        if self.label is not None:
            self.label = " ".join(self.label.split()) or None
        if self.reason is not None:
            self.reason = " ".join(self.reason.split()) or None
        return self


class DiscoveryBulkReview(DiscoveryReview):
    candidate_ids: list[UUID] = Field(min_length=1, max_length=20)

    @field_validator("candidate_ids")
    @classmethod
    def unique_candidates(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("candidate_ids no puede contener duplicados")
        return value


class DistributionBucketRead(ApiModel):
    key: str
    label: str
    count: int
    percentage: Decimal


class StoreCoverageRead(ApiModel):
    store_slug: str
    active_products: int
    successful_products_24h: int
    coverage_percent: Decimal
    meets_target: bool


class CatalogCoverageRead(ApiModel):
    active_products: int = 0
    successful_products_24h: int = 0
    coverage_percent: Decimal = Decimal("0")
    target_percent: Decimal = Decimal("95")
    meets_target: bool = False
    stores: list[StoreCoverageRead] = Field(default_factory=list)


class AnalysisBacklogRead(ApiModel):
    pending_observations: int = 0
    oldest_observed_at: datetime | None = None
    oldest_age_hours: Decimal = Decimal("0")
    capacity_per_cycle: int = 1_000
    estimated_cycles: int = 0
    warning: bool = False


class TelegramDestinationStatusRead(ApiModel):
    channel: str
    audience: Literal["free", "vip"]
    dispatch_mode: Literal["immediate", "mirrored", "delayed"]
    configured: bool
    ready: bool
    queue_counts: dict[str, int] = Field(default_factory=dict)
    sent_24h: int
    sent_7d: int
    last_sent_at: datetime | None
    last_error_at: datetime | None
    last_error_code: str | None
    last_error: str | None


class DistributionConcentrationRead(ApiModel):
    window_hours: int = 24
    unique_alerts: int = 0
    warning_threshold_percent: Decimal = Decimal("50")
    dominant_category: str | None = None
    dominant_category_label: str | None = None
    dominant_category_percent: Decimal = Decimal("0")
    warning: bool = False
    categories: list[DistributionBucketRead] = Field(default_factory=list)
    stores: list[DistributionBucketRead] = Field(default_factory=list)
    uncategorized_catalog_products: int = 0


class TelegramDistributionStatusRead(ApiModel):
    enabled: bool
    configured: bool
    ready: bool
    audience_mode: Literal["single_chat", "multi_destination"]
    membership_mode: Literal["manual"]
    payment_mode: Literal["manual_external"]
    automatic_offer_delivery: bool
    queue_counts: dict[str, int] = Field(default_factory=dict)
    destinations: list[TelegramDestinationStatusRead] = Field(default_factory=list)
    coverage: CatalogCoverageRead = Field(default_factory=CatalogCoverageRead)
    analysis_backlog: AnalysisBacklogRead = Field(
        default_factory=AnalysisBacklogRead
    )
    concentration: DistributionConcentrationRead = Field(
        default_factory=DistributionConcentrationRead
    )
    last_sent_at: datetime | None
    last_error_at: datetime | None
    last_error_code: str | None
    last_error: str | None


class TelegramTestRead(ApiModel):
    destination: str = "telegram_free"
    status: Literal["sent", "failed", "disabled"]
    sent: bool
    message_id: str | None
    detail: str | None


def _normalize_required_text(value: str, *, field_name: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError(f"{field_name} no puede estar vacío")
    return normalized


def _normalize_optional_contact(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    return normalized or None


def _normalize_telegram_username(value: str) -> str:
    normalized = value.strip().removeprefix("@").lower()
    if not re.fullmatch(r"[a-z][a-z0-9_]{4,31}", normalized):
        raise ValueError(
            "telegram_username debe tener entre 5 y 32 caracteres y usar "
            "solo letras, números o guion bajo"
        )
    return normalized


class SubscriberCreate(ApiModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=200)
    telegram_username: str = Field(min_length=5, max_length=33)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=40)
    status: Literal["trial", "active"] = "trial"
    telegram_membership_status: Literal["pending", "in_group", "removed"] = (
        "pending"
    )
    duration_days: int = Field(default=7, ge=1, le=366)
    notes: str | None = Field(default=None, max_length=2_000)

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str) -> str:
        return _normalize_required_text(value, field_name="full_name")

    @field_validator("telegram_username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return _normalize_telegram_username(value)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        normalized = _normalize_optional_contact(value)
        if normalized is None:
            return None
        lowered = normalized.lower()
        if (
            "@" not in lowered
            or lowered.startswith("@")
            or lowered.endswith("@")
            or "." not in lowered.rsplit("@", 1)[-1]
        ):
            raise ValueError("email no tiene un formato válido")
        return lowered

    @field_validator("phone", "notes")
    @classmethod
    def normalize_optional_fields(cls, value: str | None) -> str | None:
        return _normalize_optional_contact(value)


class SubscriberPatch(ApiModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    telegram_username: str | None = Field(default=None, min_length=5, max_length=33)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=40)
    status: Literal["trial", "active", "suspended"] | None = None
    telegram_membership_status: (
        Literal["pending", "in_group", "removed"] | None
    ) = None
    expires_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def require_change(self) -> SubscriberPatch:
        if not self.model_fields_set:
            raise ValueError("se requiere al menos un campo para actualizar")
        return self

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_required_text(value, field_name="full_name")

    @field_validator("telegram_username")
    @classmethod
    def normalize_username(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_telegram_username(value)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        normalized = _normalize_optional_contact(value)
        if normalized is None:
            return None
        lowered = normalized.lower()
        if (
            "@" not in lowered
            or lowered.startswith("@")
            or lowered.endswith("@")
            or "." not in lowered.rsplit("@", 1)[-1]
        ):
            raise ValueError("email no tiene un formato válido")
        return lowered

    @field_validator("phone", "notes")
    @classmethod
    def normalize_optional_fields(cls, value: str | None) -> str | None:
        return _normalize_optional_contact(value)

    @field_validator("expires_at")
    @classmethod
    def require_aware_expiry(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("expires_at debe incluir zona horaria")
        return value


class SubscriberRead(ApiModel):
    id: UUID
    full_name: str
    telegram_username: str
    email: str | None
    phone: str | None
    status: Literal["trial", "active", "expired", "suspended"]
    stored_status: Literal["trial", "active", "expired", "suspended"]
    telegram_membership_status: Literal["pending", "in_group", "removed"]
    starts_at: datetime
    expires_at: datetime
    days_remaining: int = Field(ge=0)
    notes: str | None
    version: int = Field(ge=1)
    created_by: str
    created_at: datetime
    updated_at: datetime


class PaymentCreate(ApiModel):
    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(gt=0, le=100_000, decimal_places=2)
    method: Literal["yape", "plin", "bank_transfer", "cash", "other"]
    reference: str | None = Field(default=None, max_length=200)
    paid_at: datetime | None = None
    renewal_days: int = Field(default=30, ge=1, le=366)
    notes: str | None = Field(default=None, max_length=2_000)

    @field_validator("reference", "notes")
    @classmethod
    def normalize_optional_fields(cls, value: str | None) -> str | None:
        return _normalize_optional_contact(value)

    @field_validator("paid_at")
    @classmethod
    def require_aware_paid_at(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("paid_at debe incluir zona horaria")
        return value


class PaymentRead(ApiModel):
    id: UUID
    subscriber_id: UUID
    amount: Decimal
    currency: Literal["PEN"]
    method: Literal["yape", "plin", "bank_transfer", "cash", "other"]
    reference: str | None
    paid_at: datetime
    coverage_starts_at: datetime
    coverage_ends_at: datetime
    renewal_days: int = Field(ge=1, le=366)
    notes: str | None
    recorded_by: str
    created_at: datetime


class PaymentRecordRead(ApiModel):
    payment: PaymentRead
    subscriber: SubscriberRead


class CommercialSummaryRead(ApiModel):
    total_subscribers: int = Field(ge=0)
    trial_subscribers: int = Field(ge=0)
    active_subscribers: int = Field(ge=0)
    expired_subscribers: int = Field(ge=0)
    suspended_subscribers: int = Field(ge=0)
    pending_group_access: int = Field(ge=0)
    members_in_group: int = Field(ge=0)
    expiring_within_7_days: int = Field(ge=0)
    confirmed_revenue_total_pen: Decimal = Field(ge=0)
    confirmed_revenue_month_pen: Decimal = Field(ge=0)
    telegram_ready: bool
    alerts_sent_7_days: int = Field(ge=0)
    alerts_sent_30_days: int = Field(ge=0)
    last_alert_sent_at: datetime | None
    checklist_completed: int = Field(ge=0)
    checklist_required: int = Field(ge=0)
    launch_ready: bool
    checked_at: datetime


class LaunchChecklistItemRead(ApiModel):
    item_key: str
    position: int = Field(ge=1)
    title: str
    description: str
    category: str
    required: bool
    completed: bool
    completed_at: datetime | None
    completed_by: str | None
    updated_at: datetime


class LaunchChecklistUpdate(ApiModel):
    model_config = ConfigDict(extra="forbid")

    completed: bool


class RuntimePolicyRead(ApiModel):
    revision_id: int | None
    policy_fingerprint: str
    changed_by: str | None = None
    change_reason: str | None = None
    detector_version: str
    analysis_limit: int = 1_000
    scheduler_poll_seconds: int
    detection_history_limit: int
    detection_history_days: int
    minimum_history_samples: int
    equivalent_max_age_hours: int
    equivalent_limit: int
    minimum_equivalent_samples: int
    possible_error_minimum_corroborating_signals: int
    possible_error_minimum_confidence: int
    confirmation_required: bool
    confirmation_max_age_minutes: int
    confirmation_price_tolerance_percent: Decimal
    confirmation_confidence_bonus: int
    minimum_alert_confidence: int
    verified_list_price_alert_percent: Decimal
    good_deal_percent: Decimal
    exceptional_deal_percent: Decimal
    possible_price_error_percent: Decimal
    alert_cooldown_hours: int
    alert_significant_improvement_percent: Decimal
    notification_lease_seconds: int
    notification_max_attempts: int
    notification_retry_base_seconds: int
    telegram_enabled: bool
    telegram_configured: bool
    telegram_token_configured: bool
    telegram_chat_id_configured: bool
    telegram_free_chat_id_configured: bool = False
    telegram_vip_chat_id_configured: bool = False
    telegram_operations_chat_id_configured: bool = False
    telegram_vip_mirror_enabled: bool = True


class RuntimePolicyPatch(ApiModel):
    model_config = ConfigDict(extra="forbid")

    analysis_limit: int | None = Field(default=None, ge=100, le=5_000)
    scheduler_poll_seconds: int | None = Field(default=None, ge=30, le=86_400)
    detection_history_limit: int | None = Field(default=None, ge=3, le=10_000)
    detection_history_days: int | None = Field(default=None, ge=30, le=3_650)
    equivalent_max_age_hours: int | None = Field(default=None, ge=1, le=720)
    equivalent_limit: int | None = Field(default=None, ge=2, le=100)
    confirmation_required: bool | None = None
    confirmation_max_age_minutes: int | None = Field(
        default=None,
        ge=30,
        le=10_080,
    )
    confirmation_price_tolerance_percent: Decimal | None = Field(
        default=None,
        ge=0,
        lt=100,
    )
    confirmation_confidence_bonus: int | None = Field(
        default=None,
        ge=0,
        le=100,
    )
    minimum_alert_confidence: int | None = Field(default=None, ge=0, le=100)
    verified_list_price_alert_percent: Decimal | None = Field(
        default=None,
        ge=0,
        lt=100,
    )
    alert_cooldown_hours: int | None = Field(default=None, ge=1, le=720)
    alert_significant_improvement_percent: Decimal | None = Field(
        default=None,
        ge=0,
        lt=100,
    )
    notification_lease_seconds: int | None = Field(
        default=None,
        ge=30,
        le=3_600,
    )
    notification_max_attempts: int | None = Field(default=None, ge=1, le=20)
    notification_retry_base_seconds: int | None = Field(
        default=None,
        ge=30,
        le=86_400,
    )
    telegram_enabled: bool | None = None
    minimum_history_samples: int | None = Field(default=None, ge=1, le=100)
    minimum_equivalent_samples: int | None = Field(default=None, ge=1, le=20)
    possible_error_minimum_corroborating_signals: int | None = Field(
        default=None,
        ge=2,
        le=8,
    )
    possible_error_minimum_confidence: int | None = Field(
        default=None,
        ge=0,
        le=100,
    )
    good_deal_percent: Decimal | None = Field(default=None, ge=0, lt=100)
    exceptional_deal_percent: Decimal | None = Field(default=None, ge=0, lt=100)
    possible_price_error_percent: Decimal | None = Field(
        default=None,
        ge=0,
        lt=100,
    )

    @model_validator(mode="after")
    def require_change(self) -> RuntimePolicyPatch:
        if not self.model_fields_set:
            raise ValueError("se requiere al menos un campo para actualizar")
        if any(getattr(self, field_name) is None for field_name in self.model_fields_set):
            raise ValueError("los campos de configuración no pueden ser null")
        return self

    def overrides(self) -> dict[str, object]:
        return self.model_dump(exclude_unset=True, exclude_none=True)


__all__ = [
    "AnalysisBacklogRead",
    "CatalogCoverageRead",
    "ConfirmationRead",
    "CrawlJobCreate",
    "CrawlJobItemRead",
    "CrawlJobRead",
    "CrawlRunRead",
    "DiscoveryBulkReview",
    "DiscoveryCandidateRead",
    "DiscoveryReview",
    "DiscoveryRunRead",
    "DiscoverySourceRead",
    "DistributionBucketRead",
    "DistributionConcentrationRead",
    "HealthRead",
    "ObservationRead",
    "OfferRead",
    "Page",
    "ProductCreate",
    "ProductActivation",
    "ProductPatch",
    "ProductRead",
    "ProductVariant",
    "RuntimePolicyRead",
    "RuntimePolicyPatch",
    "StoreRead",
    "StoreCoverageRead",
    "TelegramDestinationStatusRead",
    "TelegramDistributionStatusRead",
    "TelegramTestRead",
]
