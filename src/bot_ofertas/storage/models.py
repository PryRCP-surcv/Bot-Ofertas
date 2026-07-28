"""SQLAlchemy models for tracked products, crawl runs, and observations."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from bot_ofertas.domain import Availability, ProductCondition


def utc_now() -> datetime:
    return datetime.now(UTC)


class CrawlRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


def _enum_values(enum_class: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_class]


class Base(DeclarativeBase):
    pass


class StoreCrawlState(Base):
    """Persistent circuit-breaker state for one store."""

    __tablename__ = "store_crawl_states"
    __table_args__ = (
        CheckConstraint(
            "consecutive_blocks >= 0",
            name="ck_store_crawl_states_consecutive_blocks_non_negative",
        ),
        CheckConstraint(
            "(paused_until IS NULL) = (pause_reason IS NULL)",
            name="ck_store_crawl_states_pause_pair",
        ),
        Index(
            "ix_store_crawl_states_paused_until",
            "paused_until",
            postgresql_where=text("paused_until IS NOT NULL"),
        ),
    )

    store_slug: Mapped[str] = mapped_column(String(64), primary_key=True)
    paused_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pause_reason: Mapped[str | None] = mapped_column(Text)
    consecutive_blocks: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
    )


class TrackedProduct(Base):
    """A store listing explicitly scheduled for responsible monitoring."""

    __tablename__ = "tracked_products"
    __table_args__ = (
        UniqueConstraint("store_slug", "source_url", name="uq_tracked_products_store_url"),
        CheckConstraint(
            "check_interval_minutes >= 30",
            name="ck_tracked_products_minimum_interval",
        ),
        CheckConstraint(
            "consecutive_failures >= 0",
            name="ck_tracked_products_consecutive_failures_non_negative",
        ),
        CheckConstraint(
            "(lease_token IS NULL) = (lease_expires_at IS NULL)",
            name="ck_tracked_products_lease_pair",
        ),
        Index(
            "ix_tracked_products_scheduler",
            "store_slug",
            "last_checked_at",
            "lease_expires_at",
            postgresql_where=text("active"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    store_slug: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(String(500), nullable=False)
    expected_brand: Mapped[str | None] = mapped_column(String(200))
    expected_model: Mapped[str | None] = mapped_column(String(200))
    expected_variant: Mapped[dict[str, str]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    expected_is_accessory: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    check_interval_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=60,
        server_default=text("60"),
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_failures: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
    )

    observations: Mapped[list[PriceObservationRecord]] = relationship(
        back_populates="tracked_product",
        passive_deletes=True,
    )
    equivalence_membership: Mapped[EquivalentProductMembership | None] = relationship(
        back_populates="tracked_product",
        passive_deletes=True,
        uselist=False,
    )


class EquivalentProductGroup(Base):
    """A manually verified cross-store identity for one exact product variant."""

    __tablename__ = "equivalent_product_groups"
    __table_args__ = (
        UniqueConstraint("name", name="uq_equivalent_product_groups_name"),
        CheckConstraint("name <> ''", name="ck_equivalent_product_groups_name_non_empty"),
        CheckConstraint("brand <> ''", name="ck_equivalent_product_groups_brand_non_empty"),
        CheckConstraint("model <> ''", name="ck_equivalent_product_groups_model_non_empty"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    brand: Mapped[str] = mapped_column(String(200), nullable=False)
    model: Mapped[str] = mapped_column(String(300), nullable=False)
    canonical_variant: Mapped[dict[str, str]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
    )

    memberships: Mapped[list[EquivalentProductMembership]] = relationship(
        back_populates="group",
        passive_deletes=True,
    )


class EquivalentProductMembership(Base):
    """Verified membership of one tracked listing in one equivalence group."""

    __tablename__ = "equivalent_product_memberships"
    __table_args__ = (
        UniqueConstraint(
            "tracked_product_id",
            name="uq_equivalent_product_memberships_tracked_product",
        ),
        Index(
            "ix_equivalent_product_memberships_group",
            "group_id",
        ),
    )

    group_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "equivalent_product_groups.id",
            name="fk_equivalent_product_memberships_group_id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    tracked_product_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "tracked_products.id",
            name="fk_equivalent_product_memberships_tracked_product_id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
    )

    group: Mapped[EquivalentProductGroup] = relationship(back_populates="memberships")
    tracked_product: Mapped[TrackedProduct] = relationship(back_populates="equivalence_membership")


class CrawlRun(Base):
    """One bounded execution of one store spider."""

    __tablename__ = "crawl_runs"
    __table_args__ = (
        Index("ix_crawl_runs_store_started", "store_slug", "started_at"),
        CheckConstraint(
            "requested_url_count >= 0 AND observation_count >= 0 AND error_count >= 0",
            name="ck_crawl_runs_non_negative_counts",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    store_slug: Mapped[str] = mapped_column(String(64), nullable=False)
    spider_name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[CrawlRunStatus] = mapped_column(
        Enum(
            CrawlRunStatus,
            name="crawl_run_status",
            values_callable=_enum_values,
        ),
        nullable=False,
        default=CrawlRunStatus.RUNNING,
        server_default=CrawlRunStatus.RUNNING.value,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_url_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    observation_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    error_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    stats: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    error_summary: Mapped[str | None] = mapped_column(Text)

    observations: Mapped[list[PriceObservationRecord]] = relationship(
        back_populates="run",
        passive_deletes=True,
    )


class PriceObservationRecord(Base):
    """Append-only normalized price history for an exact SKU and seller."""

    __tablename__ = "price_observations"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "tracked_product_id",
            "sku",
            "seller_id",
            name="uq_price_observations_run_target_sku_seller",
        ),
        CheckConstraint(
            "price IS NULL OR price >= 0",
            name="ck_price_observations_price_non_negative",
        ),
        CheckConstraint(
            "list_price IS NULL OR list_price >= 0",
            name="ck_price_observations_list_price_non_negative",
        ),
        CheckConstraint(
            "available_quantity IS NULL OR available_quantity >= 0",
            name="ck_price_observations_quantity_non_negative",
        ),
        Index(
            "ix_price_observations_offer_history",
            "tracked_product_id",
            "store_slug",
            "sku",
            "seller_id",
            "observed_at",
        ),
        Index(
            "ix_price_observations_tracked_history",
            "tracked_product_id",
            "observed_at",
        ),
        Index(
            "ix_price_observations_external_product",
            "store_slug",
            "external_product_id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "crawl_runs.id",
            name="fk_price_observations_run_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    tracked_product_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "tracked_products.id",
            name="fk_price_observations_tracked_product_id",
            ondelete="SET NULL",
        ),
    )
    store_slug: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    external_product_id: Mapped[str] = mapped_column(String(300), nullable=False)
    product_reference: Mapped[str | None] = mapped_column(String(300))
    sku: Mapped[str] = mapped_column(String(300), nullable=False)
    sku_reference: Mapped[str | None] = mapped_column(String(300))
    seller_id: Mapped[str] = mapped_column(String(300), nullable=False)
    seller_name: Mapped[str] = mapped_column(String(500), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    brand: Mapped[str | None] = mapped_column(String(300))
    model: Mapped[str | None] = mapped_column(String(300))
    category_path: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    variant: Mapped[dict[str, str]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    condition: Mapped[ProductCondition] = mapped_column(
        Enum(
            ProductCondition,
            name="product_condition",
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    list_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    availability: Mapped[Availability] = mapped_column(
        Enum(
            Availability,
            name="offer_availability",
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    available_quantity: Mapped[int | None] = mapped_column(Integer)
    is_marketplace: Mapped[bool] = mapped_column(Boolean, nullable=False)
    installments: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(100), nullable=False)
    source_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    quality_flags: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
    )

    run: Mapped[CrawlRun] = relationship(back_populates="observations")
    tracked_product: Mapped[TrackedProduct | None] = relationship(
        back_populates="observations",
    )

    detections: Mapped[list[DealDetection]] = relationship(
        back_populates="observation",
        foreign_keys="DealDetection.observation_id",
        passive_deletes=True,
    )


class DealDetection(Base):
    """Auditable detector decision for one immutable price observation."""

    __tablename__ = "deal_detections"
    __table_args__ = (
        UniqueConstraint(
            "observation_id",
            "detector_version",
            name="uq_deal_detections_observation_version",
        ),
        CheckConstraint(
            "score >= 0 AND score <= 100",
            name="ck_deal_detections_score_range",
        ),
        CheckConstraint(
            "detector_version <> ''",
            name="ck_deal_detections_detector_version_non_empty",
        ),
        CheckConstraint(
            "confidence_score >= 0 AND confidence_score <= 100",
            name="ck_deal_detections_confidence_score_range",
        ),
        CheckConstraint(
            "confidence_level IN ('none', 'low', 'medium', 'high')",
            name="ck_deal_detections_confidence_level",
        ),
        CheckConstraint(
            "confirmation_status IN "
            "('not_applicable', 'not_required', 'awaiting', 'confirmed', "
            "'expired', 'replaced')",
            name="ck_deal_detections_confirmation_status",
        ),
        CheckConstraint(
            "confirmation_count >= 0",
            name="ck_deal_detections_confirmation_count_non_negative",
        ),
        CheckConstraint(
            "current_price IS NULL OR current_price >= 0",
            name="ck_deal_detections_current_price_non_negative",
        ),
        CheckConstraint(
            "reference_price IS NULL OR reference_price >= 0",
            name="ck_deal_detections_reference_price_non_negative",
        ),
        CheckConstraint(
            "classification IN ('none', 'good_deal', 'exceptional_deal', 'possible_price_error')",
            name="ck_deal_detections_classification",
        ),
        CheckConstraint(
            "notification_status IN "
            "('not_applicable', 'awaiting_confirmation', 'pending', "
            "'suppressed', 'retrying', 'sent', 'failed', 'superseded')",
            name="ck_deal_detections_notification_status",
        ),
        Index(
            "ix_deal_detections_recent",
            "detected_at",
            "classification",
        ),
        Index(
            "ix_deal_detections_offer_key",
            "offer_key",
            "detected_at",
        ),
        Index(
            "ix_deal_detections_confirmation",
            "confirmation_status",
            "detected_at",
            postgresql_where=text("confirmation_status = 'awaiting'"),
        ),
        Index(
            "ix_deal_detections_notification",
            "notification_status",
            "detected_at",
            postgresql_where=text("notification_status IN ('pending', 'retrying')"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    observation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "price_observations.id",
            name="fk_deal_detections_observation_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    detector_version: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="phase3-v2",
        server_default=text("'phase3-v2'"),
    )
    tracked_product_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "tracked_products.id",
            name="fk_deal_detections_tracked_product_id",
            ondelete="SET NULL",
        ),
    )
    offer_key: Mapped[str] = mapped_column(String(64), nullable=False)
    classification: Mapped[str] = mapped_column(String(40), nullable=False)
    eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence_score: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    confidence_level: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="none",
        server_default=text("'none'"),
    )
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    reference_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    previous_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    median_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    median_price_7d: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    median_price_30d: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    median_price_90d: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    historical_min_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    equivalent_median_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    drop_from_previous_pct: Mapped[Decimal | None] = mapped_column(Numeric(9, 4))
    drop_from_median_pct: Mapped[Decimal | None] = mapped_column(Numeric(9, 4))
    drop_from_median_7d_pct: Mapped[Decimal | None] = mapped_column(Numeric(9, 4))
    drop_from_median_30d_pct: Mapped[Decimal | None] = mapped_column(Numeric(9, 4))
    drop_from_median_90d_pct: Mapped[Decimal | None] = mapped_column(Numeric(9, 4))
    drop_from_equivalent_pct: Mapped[Decimal | None] = mapped_column(Numeric(9, 4))
    list_discount_pct: Mapped[Decimal | None] = mapped_column(Numeric(9, 4))
    reasons: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    rejection_reasons: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    metrics: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    notification_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="not_applicable",
        server_default=text("'not_applicable'"),
    )
    confirmation_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="not_applicable",
        server_default=text("'not_applicable'"),
    )
    confirmation_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    confirmation_observation_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "price_observations.id",
            name="fk_deal_detections_confirmation_observation_id",
            ondelete="SET NULL",
        ),
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
    )
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
    )

    observation: Mapped[PriceObservationRecord] = relationship(
        back_populates="detections",
        foreign_keys=[observation_id],
    )
    confirmation_observation: Mapped[PriceObservationRecord | None] = relationship(
        foreign_keys=[confirmation_observation_id],
    )
    deliveries: Mapped[list[NotificationDelivery]] = relationship(
        back_populates="detection",
        passive_deletes=True,
    )


class OfferAlertState(Base):
    """Serialized deduplication state for one exact product/SKU/seller/variant."""

    __tablename__ = "offer_alert_states"
    __table_args__ = (
        CheckConstraint(
            "last_price IS NULL OR last_price >= 0",
            name="ck_offer_alert_states_last_price_non_negative",
        ),
        CheckConstraint(
            "channel <> ''",
            name="ck_offer_alert_states_channel_non_empty",
        ),
        Index(
            "ix_offer_alert_states_tracked_product",
            "tracked_product_id",
        ),
    )

    offer_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    channel: Mapped[str] = mapped_column(String(32), primary_key=True)
    tracked_product_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "tracked_products.id",
            name="fk_offer_alert_states_tracked_product_id",
            ondelete="SET NULL",
        ),
    )
    last_classification: Mapped[str | None] = mapped_column(String(40))
    last_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    last_reserved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
    )


class OfferConfirmationState(Base):
    """Serialized evidence that an anomalous price survived independent crawls."""

    __tablename__ = "offer_confirmation_states"
    __table_args__ = (
        CheckConstraint(
            "candidate_price > 0",
            name="ck_offer_confirmation_states_candidate_price_positive",
        ),
        CheckConstraint(
            "confirmation_count >= 1",
            name="ck_offer_confirmation_states_count_positive",
        ),
        CheckConstraint(
            "last_seen_at >= first_seen_at",
            name="ck_offer_confirmation_states_seen_order",
        ),
        CheckConstraint(
            "expires_at > first_seen_at AND last_seen_at <= expires_at",
            name="ck_offer_confirmation_states_expiry_order",
        ),
        CheckConstraint(
            "candidate_classification IN ('good_deal', 'exceptional_deal', 'possible_price_error')",
            name="ck_offer_confirmation_states_classification",
        ),
        Index(
            "ix_offer_confirmation_states_tracked_product",
            "tracked_product_id",
        ),
        Index(
            "ix_offer_confirmation_states_expires",
            "expires_at",
        ),
    )

    offer_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    tracked_product_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "tracked_products.id",
            name="fk_offer_confirmation_states_tracked_product_id",
            ondelete="SET NULL",
        ),
    )
    candidate_observation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "price_observations.id",
            name="fk_offer_confirmation_states_candidate_observation_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    candidate_detection_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "deal_detections.id",
            name="fk_offer_confirmation_states_candidate_detection_id",
            ondelete="SET NULL",
        ),
    )
    candidate_classification: Mapped[str] = mapped_column(String(40), nullable=False)
    candidate_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    confirmation_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
    )


class NotificationDelivery(Base):
    """Durable, leased delivery attempt for one alert channel."""

    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "detection_id",
            "channel",
            name="uq_notification_deliveries_detection_channel",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_notification_deliveries_attempt_count_non_negative",
        ),
        CheckConstraint(
            "(lease_token IS NULL) = (lease_expires_at IS NULL)",
            name="ck_notification_deliveries_lease_pair",
        ),
        CheckConstraint(
            "status IN ('pending', 'retrying', 'sent', 'failed', 'superseded')",
            name="ck_notification_deliveries_status",
        ),
        CheckConstraint(
            "(status = 'sent') = (sent_at IS NOT NULL)",
            name="ck_notification_deliveries_sent_pair",
        ),
        CheckConstraint(
            "channel <> ''",
            name="ck_notification_deliveries_channel_non_empty",
        ),
        Index(
            "ix_notification_deliveries_scheduler",
            "channel",
            "status",
            "next_attempt_at",
            "lease_expires_at",
            postgresql_where=text("status IN ('pending', 'retrying')"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    detection_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "deal_detections.id",
            name="fk_notification_deliveries_detection_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        server_default=text("'pending'"),
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
    )
    lease_token: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_message_id: Mapped[str | None] = mapped_column(String(300))
    last_error_code: Mapped[str | None] = mapped_column(String(100))
    last_error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
    )

    detection: Mapped[DealDetection] = relationship(back_populates="deliveries")
