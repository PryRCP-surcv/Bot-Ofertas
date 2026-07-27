"""Create the initial monitoring and price history schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_crawl_run_status_values = ("running", "succeeded", "partial", "failed", "cancelled")
_product_condition_values = ("new", "used", "refurbished", "open_box", "unknown")
_offer_availability_values = ("in_stock", "out_of_stock", "preorder", "backorder", "unknown")

crawl_run_status = postgresql.ENUM(
    *_crawl_run_status_values,
    name="crawl_run_status",
    create_type=False,
)
product_condition = postgresql.ENUM(
    *_product_condition_values,
    name="product_condition",
    create_type=False,
)
offer_availability = postgresql.ENUM(
    *_offer_availability_values,
    name="offer_availability",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(*_crawl_run_status_values, name="crawl_run_status").create(
        bind,
        checkfirst=True,
    )
    postgresql.ENUM(*_product_condition_values, name="product_condition").create(
        bind,
        checkfirst=True,
    )
    postgresql.ENUM(*_offer_availability_values, name="offer_availability").create(
        bind,
        checkfirst=True,
    )

    op.create_table(
        "tracked_products",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_slug", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("label", sa.String(length=500), nullable=False),
        sa.Column("expected_brand", sa.String(length=200), nullable=True),
        sa.Column("expected_model", sa.String(length=200), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "check_interval_minutes",
            sa.Integer(),
            server_default=sa.text("60"),
            nullable=False,
        ),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
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
            "check_interval_minutes >= 30",
            name="ck_tracked_products_minimum_interval",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "store_slug",
            "source_url",
            name="uq_tracked_products_store_url",
        ),
    )
    op.create_index(
        "ix_tracked_products_scheduler",
        "tracked_products",
        ["active", "last_checked_at"],
        unique=False,
    )

    op.create_table(
        "crawl_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_slug", sa.String(length=64), nullable=False),
        sa.Column("spider_name", sa.String(length=160), nullable=False),
        sa.Column(
            "status",
            crawl_run_status,
            server_default="running",
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "requested_url_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "observation_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "error_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "stats",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "requested_url_count >= 0 AND observation_count >= 0 AND error_count >= 0",
            name="ck_crawl_runs_non_negative_counts",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_crawl_runs_store_started",
        "crawl_runs",
        ["store_slug", "started_at"],
        unique=False,
    )

    op.create_table(
        "price_observations",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tracked_product_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("store_slug", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("external_product_id", sa.String(length=300), nullable=False),
        sa.Column("product_reference", sa.String(length=300), nullable=True),
        sa.Column("sku", sa.String(length=300), nullable=False),
        sa.Column("sku_reference", sa.String(length=300), nullable=True),
        sa.Column("seller_id", sa.String(length=300), nullable=False),
        sa.Column("seller_name", sa.String(length=500), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("brand", sa.String(length=300), nullable=True),
        sa.Column("model", sa.String(length=300), nullable=True),
        sa.Column(
            "category_path",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "variant",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("condition", product_condition, nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("price", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("list_price", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("availability", offer_availability, nullable=False),
        sa.Column("available_quantity", sa.Integer(), nullable=True),
        sa.Column("is_marketplace", sa.Boolean(), nullable=False),
        sa.Column(
            "installments",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("extractor_version", sa.String(length=100), nullable=False),
        sa.Column("source_payload_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "quality_flags",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "available_quantity IS NULL OR available_quantity >= 0",
            name="ck_price_observations_quantity_non_negative",
        ),
        sa.CheckConstraint(
            "list_price IS NULL OR list_price >= 0",
            name="ck_price_observations_list_price_non_negative",
        ),
        sa.CheckConstraint(
            "price IS NULL OR price >= 0",
            name="ck_price_observations_price_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["crawl_runs.id"],
            name="fk_price_observations_run_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tracked_product_id"],
            ["tracked_products.id"],
            name="fk_price_observations_tracked_product_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id",
            "sku",
            "seller_id",
            name="uq_price_observations_run_sku_seller",
        ),
    )
    op.create_index(
        "ix_price_observations_external_product",
        "price_observations",
        ["store_slug", "external_product_id"],
        unique=False,
    )
    op.create_index(
        "ix_price_observations_offer_history",
        "price_observations",
        ["store_slug", "sku", "seller_id", "observed_at"],
        unique=False,
    )
    op.create_index(
        "ix_price_observations_tracked_history",
        "price_observations",
        ["tracked_product_id", "observed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_price_observations_tracked_history",
        table_name="price_observations",
    )
    op.drop_index(
        "ix_price_observations_offer_history",
        table_name="price_observations",
    )
    op.drop_index(
        "ix_price_observations_external_product",
        table_name="price_observations",
    )
    op.drop_table("price_observations")
    op.drop_index("ix_crawl_runs_store_started", table_name="crawl_runs")
    op.drop_table("crawl_runs")
    op.drop_index("ix_tracked_products_scheduler", table_name="tracked_products")
    op.drop_table("tracked_products")

    bind = op.get_bind()
    offer_availability.drop(bind, checkfirst=True)
    product_condition.drop(bind, checkfirst=True)
    crawl_run_status.drop(bind, checkfirst=True)
