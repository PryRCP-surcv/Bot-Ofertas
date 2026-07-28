"""Add auditable detections, alert deduplication, and durable deliveries.

Revision ID: 0005_phase1_detection_alerts
Revises: 0004_store_circuit_breaker
Create Date: 2026-07-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_phase1_detection_alerts"
down_revision: str | Sequence[str] | None = "0004_store_circuit_breaker"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tracked_products",
        sa.Column(
            "expected_variant",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "tracked_products",
        sa.Column(
            "expected_is_accessory",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )

    op.create_table(
        "deal_detections",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("observation_id", sa.BigInteger(), nullable=False),
        sa.Column("tracked_product_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("offer_key", sa.String(length=64), nullable=False),
        sa.Column("classification", sa.String(length=40), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("current_price", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("reference_price", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("previous_price", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("median_price", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("historical_min_price", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column(
            "drop_from_previous_pct",
            sa.Numeric(precision=9, scale=4),
            nullable=True,
        ),
        sa.Column(
            "drop_from_median_pct",
            sa.Numeric(precision=9, scale=4),
            nullable=True,
        ),
        sa.Column("list_discount_pct", sa.Numeric(precision=9, scale=4), nullable=True),
        sa.Column(
            "reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "rejection_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "metrics",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "notification_status",
            sa.String(length=32),
            server_default=sa.text("'not_applicable'"),
            nullable=False,
        ),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "current_price IS NULL OR current_price >= 0",
            name="ck_deal_detections_current_price_non_negative",
        ),
        sa.CheckConstraint(
            "reference_price IS NULL OR reference_price >= 0",
            name="ck_deal_detections_reference_price_non_negative",
        ),
        sa.CheckConstraint(
            "score >= 0 AND score <= 100",
            name="ck_deal_detections_score_range",
        ),
        sa.ForeignKeyConstraint(
            ["observation_id"],
            ["price_observations.id"],
            name="fk_deal_detections_observation_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tracked_product_id"],
            ["tracked_products.id"],
            name="fk_deal_detections_tracked_product_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "observation_id",
            name="uq_deal_detections_observation_id",
        ),
    )
    op.create_index(
        "ix_deal_detections_notification",
        "deal_detections",
        ["notification_status", "detected_at"],
        unique=False,
        postgresql_where=sa.text(
            "notification_status IN ('pending', 'retrying')"
        ),
    )
    op.create_index(
        "ix_deal_detections_offer_key",
        "deal_detections",
        ["offer_key", "detected_at"],
        unique=False,
    )
    op.create_index(
        "ix_deal_detections_recent",
        "deal_detections",
        ["detected_at", "classification"],
        unique=False,
    )

    op.create_table(
        "offer_alert_states",
        sa.Column("offer_key", sa.String(length=64), nullable=False),
        sa.Column("tracked_product_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_classification", sa.String(length=40), nullable=True),
        sa.Column("last_price", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("last_reserved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "last_price IS NULL OR last_price >= 0",
            name="ck_offer_alert_states_last_price_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["tracked_product_id"],
            ["tracked_products.id"],
            name="fk_offer_alert_states_tracked_product_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("offer_key"),
    )
    op.create_index(
        "ix_offer_alert_states_tracked_product",
        "offer_alert_states",
        ["tracked_product_id"],
        unique=False,
    )

    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("detection_id", sa.BigInteger(), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_message_id", sa.String(length=300), nullable=True),
        sa.Column("last_error_code", sa.String(length=100), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_notification_deliveries_attempt_count_non_negative",
        ),
        sa.CheckConstraint(
            "(lease_token IS NULL) = (lease_expires_at IS NULL)",
            name="ck_notification_deliveries_lease_pair",
        ),
        sa.ForeignKeyConstraint(
            ["detection_id"],
            ["deal_detections.id"],
            name="fk_notification_deliveries_detection_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "detection_id",
            "channel",
            name="uq_notification_deliveries_detection_channel",
        ),
    )
    op.create_index(
        "ix_notification_deliveries_scheduler",
        "notification_deliveries",
        ["status", "next_attempt_at", "lease_expires_at"],
        unique=False,
        postgresql_where=sa.text("status IN ('pending', 'retrying')"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notification_deliveries_scheduler",
        table_name="notification_deliveries",
    )
    op.drop_table("notification_deliveries")
    op.drop_index(
        "ix_offer_alert_states_tracked_product",
        table_name="offer_alert_states",
    )
    op.drop_table("offer_alert_states")
    op.drop_index("ix_deal_detections_recent", table_name="deal_detections")
    op.drop_index("ix_deal_detections_offer_key", table_name="deal_detections")
    op.drop_index("ix_deal_detections_notification", table_name="deal_detections")
    op.drop_table("deal_detections")
    op.drop_column("tracked_products", "expected_is_accessory")
    op.drop_column("tracked_products", "expected_variant")
