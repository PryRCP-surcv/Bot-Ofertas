"""Add Phase 3 evidence windows, confidence, and durable confirmation.

Revision ID: 0007_phase3_detection
Revises: 0006_notification_robustness
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_phase3_detection"
down_revision: str | Sequence[str] | None = "0006_notification_robustness"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "equivalent_product_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("brand", sa.String(length=200), nullable=False),
        sa.Column("model", sa.String(length=300), nullable=False),
        sa.Column(
            "canonical_variant",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
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
            "name <> ''",
            name="ck_equivalent_product_groups_name_non_empty",
        ),
        sa.CheckConstraint(
            "brand <> ''",
            name="ck_equivalent_product_groups_brand_non_empty",
        ),
        sa.CheckConstraint(
            "model <> ''",
            name="ck_equivalent_product_groups_model_non_empty",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_equivalent_product_groups_name"),
    )
    op.create_table(
        "equivalent_product_memberships",
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tracked_product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "verified_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["equivalent_product_groups.id"],
            name="fk_equivalent_product_memberships_group_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tracked_product_id"],
            ["tracked_products.id"],
            name="fk_equivalent_product_memberships_tracked_product_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("group_id", "tracked_product_id"),
        sa.UniqueConstraint(
            "tracked_product_id",
            name="uq_equivalent_product_memberships_tracked_product",
        ),
    )
    op.create_index(
        "ix_equivalent_product_memberships_group",
        "equivalent_product_memberships",
        ["group_id"],
        unique=False,
    )

    op.add_column(
        "deal_detections",
        sa.Column(
            "detector_version",
            sa.String(length=40),
            nullable=True,
        ),
    )
    op.execute(sa.text("UPDATE deal_detections SET detector_version = 'phase1-v1'"))
    op.alter_column(
        "deal_detections",
        "detector_version",
        existing_type=sa.String(length=40),
        nullable=False,
        server_default=sa.text("'phase3-v1'"),
    )
    op.drop_constraint(
        "uq_deal_detections_observation_id",
        "deal_detections",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_deal_detections_observation_version",
        "deal_detections",
        ["observation_id", "detector_version"],
    )
    op.create_check_constraint(
        "ck_deal_detections_detector_version_non_empty",
        "deal_detections",
        "detector_version <> ''",
    )

    op.add_column(
        "deal_detections",
        sa.Column(
            "confidence_score",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "deal_detections",
        sa.Column(
            "confidence_level",
            sa.String(length=20),
            server_default=sa.text("'none'"),
            nullable=False,
        ),
    )
    for column_name in (
        "median_price_7d",
        "median_price_30d",
        "median_price_90d",
        "equivalent_median_price",
    ):
        op.add_column(
            "deal_detections",
            sa.Column(column_name, sa.Numeric(precision=18, scale=4), nullable=True),
        )
    for column_name in (
        "drop_from_median_7d_pct",
        "drop_from_median_30d_pct",
        "drop_from_median_90d_pct",
        "drop_from_equivalent_pct",
    ):
        op.add_column(
            "deal_detections",
            sa.Column(column_name, sa.Numeric(precision=9, scale=4), nullable=True),
        )
    op.add_column(
        "deal_detections",
        sa.Column(
            "confirmation_status",
            sa.String(length=32),
            server_default=sa.text("'not_applicable'"),
            nullable=False,
        ),
    )
    op.add_column(
        "deal_detections",
        sa.Column(
            "confirmation_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "deal_detections",
        sa.Column("confirmation_observation_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "deal_detections",
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_deal_detections_confirmation_observation_id",
        "deal_detections",
        "price_observations",
        ["confirmation_observation_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.execute(
        sa.text(
            "UPDATE deal_detections "
            "SET median_price_90d = median_price, "
            "drop_from_median_90d_pct = drop_from_median_pct"
        )
    )

    op.create_check_constraint(
        "ck_deal_detections_confidence_score_range",
        "deal_detections",
        "confidence_score >= 0 AND confidence_score <= 100",
    )
    op.create_check_constraint(
        "ck_deal_detections_confidence_level",
        "deal_detections",
        "confidence_level IN ('none', 'low', 'medium', 'high')",
    )
    op.create_check_constraint(
        "ck_deal_detections_confirmation_status",
        "deal_detections",
        "confirmation_status IN "
        "('not_applicable', 'not_required', 'awaiting', 'confirmed', "
        "'expired', 'replaced')",
    )
    op.create_check_constraint(
        "ck_deal_detections_confirmation_count_non_negative",
        "deal_detections",
        "confirmation_count >= 0",
    )
    op.drop_constraint(
        "ck_deal_detections_notification_status",
        "deal_detections",
        type_="check",
    )
    op.create_check_constraint(
        "ck_deal_detections_notification_status",
        "deal_detections",
        "notification_status IN "
        "('not_applicable', 'awaiting_confirmation', 'pending', "
        "'suppressed', 'retrying', 'sent', 'failed', 'superseded')",
    )
    op.create_index(
        "ix_deal_detections_confirmation",
        "deal_detections",
        ["confirmation_status", "detected_at"],
        unique=False,
        postgresql_where=sa.text("confirmation_status = 'awaiting'"),
    )

    op.create_table(
        "offer_confirmation_states",
        sa.Column("offer_key", sa.String(length=64), nullable=False),
        sa.Column("tracked_product_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("candidate_observation_id", sa.BigInteger(), nullable=False),
        sa.Column("candidate_detection_id", sa.BigInteger(), nullable=True),
        sa.Column("candidate_classification", sa.String(length=40), nullable=False),
        sa.Column(
            "candidate_price",
            sa.Numeric(precision=18, scale=4),
            nullable=False,
        ),
        sa.Column(
            "confirmation_count",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
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
            "candidate_price > 0",
            name="ck_offer_confirmation_states_candidate_price_positive",
        ),
        sa.CheckConstraint(
            "confirmation_count >= 1",
            name="ck_offer_confirmation_states_count_positive",
        ),
        sa.CheckConstraint(
            "last_seen_at >= first_seen_at",
            name="ck_offer_confirmation_states_seen_order",
        ),
        sa.CheckConstraint(
            "expires_at > first_seen_at AND last_seen_at <= expires_at",
            name="ck_offer_confirmation_states_expiry_order",
        ),
        sa.CheckConstraint(
            "candidate_classification IN ('good_deal', 'exceptional_deal', 'possible_price_error')",
            name="ck_offer_confirmation_states_classification",
        ),
        sa.ForeignKeyConstraint(
            ["tracked_product_id"],
            ["tracked_products.id"],
            name="fk_offer_confirmation_states_tracked_product_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_observation_id"],
            ["price_observations.id"],
            name="fk_offer_confirmation_states_candidate_observation_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_detection_id"],
            ["deal_detections.id"],
            name="fk_offer_confirmation_states_candidate_detection_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("offer_key"),
    )
    op.create_index(
        "ix_offer_confirmation_states_tracked_product",
        "offer_confirmation_states",
        ["tracked_product_id"],
        unique=False,
    )
    op.create_index(
        "ix_offer_confirmation_states_expires",
        "offer_confirmation_states",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_offer_confirmation_states_expires",
        table_name="offer_confirmation_states",
    )
    op.drop_index(
        "ix_offer_confirmation_states_tracked_product",
        table_name="offer_confirmation_states",
    )
    op.drop_table("offer_confirmation_states")

    op.execute(sa.text("DELETE FROM deal_detections WHERE detector_version <> 'phase1-v1'"))
    op.drop_index(
        "ix_deal_detections_confirmation",
        table_name="deal_detections",
    )
    op.drop_constraint(
        "ck_deal_detections_notification_status",
        "deal_detections",
        type_="check",
    )
    op.execute(
        sa.text(
            "UPDATE deal_detections "
            "SET notification_status = 'suppressed' "
            "WHERE notification_status = 'awaiting_confirmation'"
        )
    )
    op.create_check_constraint(
        "ck_deal_detections_notification_status",
        "deal_detections",
        "notification_status IN "
        "('not_applicable', 'pending', 'suppressed', 'retrying', "
        "'sent', 'failed', 'superseded')",
    )
    op.drop_constraint(
        "ck_deal_detections_confirmation_count_non_negative",
        "deal_detections",
        type_="check",
    )
    op.drop_constraint(
        "ck_deal_detections_confirmation_status",
        "deal_detections",
        type_="check",
    )
    op.drop_constraint(
        "ck_deal_detections_confidence_level",
        "deal_detections",
        type_="check",
    )
    op.drop_constraint(
        "ck_deal_detections_confidence_score_range",
        "deal_detections",
        type_="check",
    )
    op.drop_constraint(
        "fk_deal_detections_confirmation_observation_id",
        "deal_detections",
        type_="foreignkey",
    )
    for column_name in (
        "confirmed_at",
        "confirmation_observation_id",
        "confirmation_count",
        "confirmation_status",
        "drop_from_equivalent_pct",
        "drop_from_median_90d_pct",
        "drop_from_median_30d_pct",
        "drop_from_median_7d_pct",
        "equivalent_median_price",
        "median_price_90d",
        "median_price_30d",
        "median_price_7d",
        "confidence_level",
        "confidence_score",
    ):
        op.drop_column("deal_detections", column_name)
    op.drop_constraint(
        "ck_deal_detections_detector_version_non_empty",
        "deal_detections",
        type_="check",
    )
    op.drop_constraint(
        "uq_deal_detections_observation_version",
        "deal_detections",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_deal_detections_observation_id",
        "deal_detections",
        ["observation_id"],
    )
    op.drop_column("deal_detections", "detector_version")

    op.drop_index(
        "ix_equivalent_product_memberships_group",
        table_name="equivalent_product_memberships",
    )
    op.drop_table("equivalent_product_memberships")
    op.drop_table("equivalent_product_groups")
