"""Add the Phase 4 administration control plane.

Revision ID: 0009_phase4_admin
Revises: 0008_conditioned_offers
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_phase4_admin"
down_revision: str | Sequence[str] | None = "0008_conditioned_offers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LEGACY_POLICY_FINGERPRINT = "0" * 64


def upgrade() -> None:
    op.add_column(
        "tracked_products",
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.add_column(
        "tracked_products",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_tracked_products_version_positive",
        "tracked_products",
        "version >= 1",
    )
    op.create_check_constraint(
        "ck_tracked_products_archived_inactive",
        "tracked_products",
        "archived_at IS NULL OR "
        "(NOT active AND lease_token IS NULL AND lease_expires_at IS NULL)",
    )
    op.drop_index("ix_tracked_products_scheduler", table_name="tracked_products")
    op.create_index(
        "ix_tracked_products_scheduler",
        "tracked_products",
        ["store_slug", "last_checked_at", "lease_expires_at"],
        unique=False,
        postgresql_where=sa.text("active AND archived_at IS NULL"),
    )

    op.create_table(
        "admin_config_revisions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "schema_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "policy",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("policy_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("previous_revision_id", sa.BigInteger(), nullable=True),
        sa.Column("restored_from_revision_id", sa.BigInteger(), nullable=True),
        sa.Column("changed_by", sa.String(length=200), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("idempotency_key_hash", sa.String(length=64), nullable=True),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "schema_version >= 1",
            name="ck_admin_config_revisions_schema_version_positive",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(policy) = 'object'",
            name="ck_admin_config_revisions_policy_object",
        ),
        sa.CheckConstraint(
            "policy_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_admin_config_revisions_policy_fingerprint",
        ),
        sa.CheckConstraint(
            "btrim(changed_by) <> ''",
            name="ck_admin_config_revisions_changed_by_non_empty",
        ),
        sa.CheckConstraint(
            "change_reason IS NULL OR btrim(change_reason) <> ''",
            name="ck_admin_config_revisions_reason_non_empty",
        ),
        sa.CheckConstraint(
            "(idempotency_key_hash IS NULL) = (request_fingerprint IS NULL)",
            name="ck_admin_config_revisions_idempotency_pair",
        ),
        sa.CheckConstraint(
            "idempotency_key_hash IS NULL "
            "OR idempotency_key_hash ~ '^[0-9a-f]{64}$'",
            name="ck_admin_config_revisions_idempotency_hash",
        ),
        sa.CheckConstraint(
            "request_fingerprint IS NULL "
            "OR request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_admin_config_revisions_request_fingerprint",
        ),
        sa.CheckConstraint(
            "previous_revision_id IS NULL OR previous_revision_id <> id",
            name="ck_admin_config_revisions_previous_distinct",
        ),
        sa.CheckConstraint(
            "restored_from_revision_id IS NULL OR restored_from_revision_id <> id",
            name="ck_admin_config_revisions_restored_distinct",
        ),
        sa.ForeignKeyConstraint(
            ["previous_revision_id"],
            ["admin_config_revisions.id"],
            name="fk_admin_config_revisions_previous_revision_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["restored_from_revision_id"],
            ["admin_config_revisions.id"],
            name="fk_admin_config_revisions_restored_from_revision_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key_hash",
            name="uq_admin_config_revisions_idempotency_hash",
        ),
    )
    op.create_index(
        "ix_admin_config_revisions_created",
        "admin_config_revisions",
        ["created_at", "id"],
        unique=False,
    )

    op.add_column(
        "deal_detections",
        sa.Column("policy_fingerprint", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "deal_detections",
        sa.Column("config_revision_id", sa.BigInteger(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE deal_detections "
            "SET policy_fingerprint = :legacy_policy_fingerprint"
        ).bindparams(legacy_policy_fingerprint=_LEGACY_POLICY_FINGERPRINT)
    )
    op.alter_column(
        "deal_detections",
        "policy_fingerprint",
        existing_type=sa.String(length=64),
        nullable=False,
    )
    op.drop_constraint(
        "uq_deal_detections_observation_version",
        "deal_detections",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_deal_detections_observation_version_policy",
        "deal_detections",
        ["observation_id", "detector_version", "policy_fingerprint"],
    )
    op.create_check_constraint(
        "ck_deal_detections_policy_fingerprint",
        "deal_detections",
        "policy_fingerprint ~ '^[0-9a-f]{64}$'",
    )
    op.create_foreign_key(
        "fk_deal_detections_config_revision_id",
        "deal_detections",
        "admin_config_revisions",
        ["config_revision_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_deal_detections_config_revision",
        "deal_detections",
        ["config_revision_id"],
        unique=False,
        postgresql_where=sa.text("config_revision_id IS NOT NULL"),
    )

    op.create_table(
        "crawl_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            sa.String(length=24),
            server_default=sa.text("'queued'"),
            nullable=False,
        ),
        sa.Column(
            "request_source",
            sa.String(length=24),
            server_default=sa.text("'api'"),
            nullable=False,
        ),
        sa.Column("requested_by", sa.String(length=200), nullable=False),
        sa.Column(
            "request_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("idempotency_key_hash", sa.String(length=64), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "force",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "priority",
            sa.Integer(),
            server_default=sa.text("50"),
            nullable=False,
        ),
        sa.Column(
            "max_attempts",
            sa.Integer(),
            server_default=sa.text("3"),
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
        sa.Column("config_revision_id", sa.BigInteger(), nullable=True),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_worker_id", sa.String(length=200), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_by", sa.String(length=200), nullable=True),
        sa.Column("last_error_code", sa.String(length=100), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "result",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
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
            "('queued', 'running', 'retrying', 'succeeded', 'partial', "
            "'failed', 'cancelled')",
            name="ck_crawl_jobs_status",
        ),
        sa.CheckConstraint(
            "request_source IN ('api', 'cli', 'scheduler')",
            name="ck_crawl_jobs_request_source",
        ),
        sa.CheckConstraint(
            "btrim(requested_by) <> ''",
            name="ck_crawl_jobs_requested_by_non_empty",
        ),
        sa.CheckConstraint(
            "priority >= 0 AND priority <= 100",
            name="ck_crawl_jobs_priority_range",
        ),
        sa.CheckConstraint(
            "max_attempts >= 1 AND max_attempts <= 20 "
            "AND attempt_count >= 0 AND attempt_count <= max_attempts",
            name="ck_crawl_jobs_attempts",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(request_payload) = 'object'",
            name="ck_crawl_jobs_request_payload_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(result) = 'object'",
            name="ck_crawl_jobs_result_object",
        ),
        sa.CheckConstraint(
            "idempotency_key_hash ~ '^[0-9a-f]{64}$'",
            name="ck_crawl_jobs_idempotency_hash",
        ),
        sa.CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_crawl_jobs_request_fingerprint",
        ),
        sa.CheckConstraint(
            "(lease_token IS NULL) = (lease_expires_at IS NULL)",
            name="ck_crawl_jobs_lease_pair",
        ),
        sa.CheckConstraint(
            "(status = 'running') = (lease_token IS NOT NULL)",
            name="ck_crawl_jobs_running_lease",
        ),
        sa.CheckConstraint(
            "(status IN ('succeeded', 'partial', 'failed', 'cancelled')) "
            "= (finished_at IS NOT NULL)",
            name="ck_crawl_jobs_terminal_finished",
        ),
        sa.CheckConstraint(
            "(attempt_count = 0) = (started_at IS NULL)",
            name="ck_crawl_jobs_started_attempt",
        ),
        sa.CheckConstraint(
            "(attempt_count = 0) = (last_claimed_at IS NULL)",
            name="ck_crawl_jobs_last_claim_attempt",
        ),
        sa.CheckConstraint(
            "last_claimed_at IS NULL OR last_claimed_at >= started_at",
            name="ck_crawl_jobs_claim_order",
        ),
        sa.CheckConstraint(
            "lease_expires_at IS NULL OR lease_expires_at > last_claimed_at",
            name="ck_crawl_jobs_lease_order",
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= COALESCE(started_at, created_at)",
            name="ck_crawl_jobs_finish_order",
        ),
        sa.CheckConstraint(
            "(cancel_requested_at IS NULL) = (cancel_requested_by IS NULL)",
            name="ck_crawl_jobs_cancel_pair",
        ),
        sa.CheckConstraint(
            "cancel_requested_at IS NULL OR status IN ('running', 'cancelled')",
            name="ck_crawl_jobs_cancel_status",
        ),
        sa.ForeignKeyConstraint(
            ["config_revision_id"],
            ["admin_config_revisions.id"],
            name="fk_crawl_jobs_config_revision_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key_hash",
            name="uq_crawl_jobs_idempotency_hash",
        ),
    )
    op.create_index(
        "ix_crawl_jobs_claim",
        "crawl_jobs",
        ["status", "next_attempt_at", "priority", "created_at"],
        unique=False,
        postgresql_where=sa.text("status IN ('queued', 'retrying', 'running')"),
    )
    op.create_index(
        "ix_crawl_jobs_expired_lease",
        "crawl_jobs",
        ["lease_expires_at"],
        unique=False,
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_index(
        "ix_crawl_jobs_recent",
        "crawl_jobs",
        ["created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_crawl_jobs_status_recent",
        "crawl_jobs",
        ["status", "created_at", "id"],
        unique=False,
    )

    op.create_table(
        "crawl_job_items",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tracked_product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("crawl_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("store_slug", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("label", sa.String(length=500), nullable=False),
        sa.Column(
            "status",
            sa.String(length=24),
            server_default=sa.text("'queued'"),
            nullable=False,
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=100), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "result",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
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
            "('queued', 'running', 'succeeded', 'failed', 'skipped', 'cancelled')",
            name="ck_crawl_job_items_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_crawl_job_items_attempt_count_non_negative",
        ),
        sa.CheckConstraint(
            "btrim(store_slug) <> '' AND btrim(source_url) <> '' AND btrim(label) <> ''",
            name="ck_crawl_job_items_snapshot_non_empty",
        ),
        sa.CheckConstraint(
            "(status IN ('succeeded', 'failed', 'skipped', 'cancelled')) "
            "= (finished_at IS NOT NULL)",
            name="ck_crawl_job_items_terminal_finished",
        ),
        sa.CheckConstraint(
            "(attempt_count = 0) = (started_at IS NULL)",
            name="ck_crawl_job_items_started_attempt",
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="ck_crawl_job_items_finish_order",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["crawl_jobs.id"],
            name="fk_crawl_job_items_job_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tracked_product_id"],
            ["tracked_products.id"],
            name="fk_crawl_job_items_tracked_product_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["crawl_run_id"],
            ["crawl_runs.id"],
            name="fk_crawl_job_items_crawl_run_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id",
            "tracked_product_id",
            name="uq_crawl_job_items_job_product",
        ),
    )
    op.create_index(
        "ix_crawl_job_items_job_status",
        "crawl_job_items",
        ["job_id", "status", "id"],
        unique=False,
    )
    op.create_index(
        "ix_crawl_job_items_product_recent",
        "crawl_job_items",
        ["tracked_product_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_crawl_job_items_run",
        "crawl_job_items",
        ["crawl_run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_crawl_job_items_run", table_name="crawl_job_items")
    op.drop_index(
        "ix_crawl_job_items_product_recent",
        table_name="crawl_job_items",
    )
    op.drop_index("ix_crawl_job_items_job_status", table_name="crawl_job_items")
    op.drop_table("crawl_job_items")

    op.drop_index("ix_crawl_jobs_status_recent", table_name="crawl_jobs")
    op.drop_index("ix_crawl_jobs_recent", table_name="crawl_jobs")
    op.drop_index("ix_crawl_jobs_expired_lease", table_name="crawl_jobs")
    op.drop_index("ix_crawl_jobs_claim", table_name="crawl_jobs")
    op.drop_table("crawl_jobs")

    op.drop_index(
        "ix_deal_detections_config_revision",
        table_name="deal_detections",
    )
    op.drop_constraint(
        "fk_deal_detections_config_revision_id",
        "deal_detections",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_deal_detections_policy_fingerprint",
        "deal_detections",
        type_="check",
    )
    op.drop_constraint(
        "uq_deal_detections_observation_version_policy",
        "deal_detections",
        type_="unique",
    )
    # A single observation may have been evaluated under several policy
    # fingerprints. The Phase 3 schema can retain only the newest decision.
    op.execute(
        sa.text(
            "DELETE FROM deal_detections AS older "
            "USING deal_detections AS newer "
            "WHERE older.observation_id = newer.observation_id "
            "AND older.detector_version = newer.detector_version "
            "AND older.id < newer.id"
        )
    )
    op.create_unique_constraint(
        "uq_deal_detections_observation_version",
        "deal_detections",
        ["observation_id", "detector_version"],
    )
    op.drop_column("deal_detections", "config_revision_id")
    op.drop_column("deal_detections", "policy_fingerprint")

    op.drop_index(
        "ix_admin_config_revisions_created",
        table_name="admin_config_revisions",
    )
    op.drop_table("admin_config_revisions")

    op.drop_index("ix_tracked_products_scheduler", table_name="tracked_products")
    op.create_index(
        "ix_tracked_products_scheduler",
        "tracked_products",
        ["store_slug", "last_checked_at", "lease_expires_at"],
        unique=False,
        postgresql_where=sa.text("active"),
    )
    op.drop_constraint(
        "ck_tracked_products_archived_inactive",
        "tracked_products",
        type_="check",
    )
    op.drop_constraint(
        "ck_tracked_products_version_positive",
        "tracked_products",
        type_="check",
    )
    op.drop_column("tracked_products", "archived_at")
    op.drop_column("tracked_products", "version")
