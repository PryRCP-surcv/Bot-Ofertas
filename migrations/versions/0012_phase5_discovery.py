"""Add the bounded Phase 5.1 catalogue discovery engine.

Revision ID: 0012_phase5_discovery
Revises: 0011_worker_watchdog_state
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_phase5_discovery"
down_revision: str | Sequence[str] | None = "0011_worker_watchdog_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "discovery_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_slug", sa.String(length=64), nullable=False),
        sa.Column("source_key", sa.String(length=100), nullable=False),
        sa.Column(
            "source_type",
            sa.String(length=32),
            server_default=sa.text("'sitemap'"),
            nullable=False,
        ),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "minimum_interval_minutes",
            sa.Integer(),
            server_default=sa.text("1440"),
            nullable=False,
        ),
        sa.Column(
            "max_documents_per_run",
            sa.Integer(),
            server_default=sa.text("2"),
            nullable=False,
        ),
        sa.Column(
            "max_candidates_per_run",
            sa.Integer(),
            server_default=sa.text("100"),
            nullable=False,
        ),
        sa.Column(
            "daily_approval_limit",
            sa.Integer(),
            server_default=sa.text("20"),
            nullable=False,
        ),
        sa.Column(
            "active_product_limit",
            sa.Integer(),
            server_default=sa.text("500"),
            nullable=False,
        ),
        sa.Column("child_path_pattern", sa.String(length=500), nullable=False),
        sa.Column("notes", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "scan_cursor",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "next_run_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_status",
            sa.String(length=32),
            server_default=sa.text("'never'"),
            nullable=False,
        ),
        sa.Column("last_error_code", sa.String(length=100), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "version",
            sa.Integer(),
            server_default=sa.text("1"),
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
            "source_type = 'sitemap'",
            name="ck_discovery_sources_type",
        ),
        sa.CheckConstraint(
            "minimum_interval_minutes >= 60",
            name="ck_discovery_sources_interval",
        ),
        sa.CheckConstraint(
            "max_documents_per_run BETWEEN 1 AND 10",
            name="ck_discovery_sources_document_limit",
        ),
        sa.CheckConstraint(
            "max_candidates_per_run BETWEEN 1 AND 500",
            name="ck_discovery_sources_candidate_limit",
        ),
        sa.CheckConstraint(
            "daily_approval_limit BETWEEN 1 AND 1000",
            name="ck_discovery_sources_approval_limit",
        ),
        sa.CheckConstraint(
            "active_product_limit BETWEEN 1 AND 10000",
            name="ck_discovery_sources_product_limit",
        ),
        sa.CheckConstraint(
            "scan_cursor >= 0",
            name="ck_discovery_sources_scan_cursor",
        ),
        sa.CheckConstraint(
            "(lease_token IS NULL) = (lease_expires_at IS NULL)",
            name="ck_discovery_sources_lease_pair",
        ),
        sa.CheckConstraint(
            "last_status IN "
            "('never', 'running', 'succeeded', 'partial', 'failed', 'blocked', 'cancelled')",
            name="ck_discovery_sources_last_status",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_discovery_sources_version",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "store_slug",
            "source_key",
            name="uq_discovery_sources_store_key",
        ),
        sa.UniqueConstraint(
            "store_slug",
            "source_url",
            name="uq_discovery_sources_store_url",
        ),
    )
    op.create_index(
        "ix_discovery_sources_scheduler",
        "discovery_sources",
        ["enabled", "next_run_at", "lease_expires_at"],
        unique=False,
    )

    op.create_table(
        "discovery_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_slug", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'running'"),
            nullable=False,
        ),
        sa.Column("requested_by", sa.String(length=32), nullable=False),
        sa.Column(
            "document_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "candidate_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("new_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "duplicate_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "rejected_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "error_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column(
            "stats",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'partial', 'failed', 'blocked', 'cancelled')",
            name="ck_discovery_runs_status",
        ),
        sa.CheckConstraint(
            "requested_by IN ('scheduler', 'api', 'cli')",
            name="ck_discovery_runs_requested_by",
        ),
        sa.CheckConstraint(
            "document_count >= 0 AND candidate_count >= 0 AND new_count >= 0 "
            "AND duplicate_count >= 0 AND rejected_count >= 0 AND error_count >= 0",
            name="ck_discovery_runs_counts",
        ),
        sa.CheckConstraint(
            "(status = 'running') = (finished_at IS NULL)",
            name="ck_discovery_runs_finished_state",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["discovery_sources.id"],
            name="fk_discovery_runs_source_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_discovery_runs_recent",
        "discovery_runs",
        ["started_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_discovery_runs_source_recent",
        "discovery_runs",
        ["source_id", "started_at"],
        unique=False,
    )

    op.create_table(
        "discovery_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("latest_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tracked_product_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("store_slug", sa.String(length=64), nullable=False),
        sa.Column("discovered_url", sa.Text(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("url_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=500), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("reviewed_by", sa.String(length=200), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "version",
            sa.Integer(),
            server_default=sa.text("1"),
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
            "status IN "
            "('pending', 'approved', 'rejected', 'duplicate', 'policy_blocked', 'unavailable')",
            name="ck_discovery_candidates_status",
        ),
        sa.CheckConstraint(
            "length(url_fingerprint) = 64",
            name="ck_discovery_candidates_fingerprint",
        ),
        sa.CheckConstraint(
            "status <> 'approved' OR tracked_product_id IS NOT NULL",
            name="ck_discovery_candidates_approved_product",
        ),
        sa.CheckConstraint(
            "(reviewed_at IS NULL) = (reviewed_by IS NULL)",
            name="ck_discovery_candidates_review_pair",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_discovery_candidates_version",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["discovery_sources.id"],
            name="fk_discovery_candidates_source_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["latest_run_id"],
            ["discovery_runs.id"],
            name="fk_discovery_candidates_latest_run_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tracked_product_id"],
            ["tracked_products.id"],
            name="fk_discovery_candidates_tracked_product_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "store_slug",
            "url_fingerprint",
            name="uq_discovery_candidates_store_fingerprint",
        ),
    )
    op.create_index(
        "ix_discovery_candidates_status_recent",
        "discovery_candidates",
        ["status", "last_seen_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_discovery_candidates_store_status",
        "discovery_candidates",
        ["store_slug", "status", "last_seen_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_discovery_candidates_store_status",
        table_name="discovery_candidates",
    )
    op.drop_index(
        "ix_discovery_candidates_status_recent",
        table_name="discovery_candidates",
    )
    op.drop_table("discovery_candidates")

    op.drop_index("ix_discovery_runs_source_recent", table_name="discovery_runs")
    op.drop_index("ix_discovery_runs_recent", table_name="discovery_runs")
    op.drop_table("discovery_runs")

    op.drop_index(
        "ix_discovery_sources_scheduler",
        table_name="discovery_sources",
    )
    op.drop_table("discovery_sources")
