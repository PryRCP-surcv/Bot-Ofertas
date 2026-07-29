"""Add the Phase 4C worker heartbeat and cycle state.

Revision ID: 0010_worker_runtime_state
Revises: 0009_phase4_admin
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_worker_runtime_state"
down_revision: str | Sequence[str] | None = "0009_phase4_admin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "worker_runtime_states",
        sa.Column("worker_name", sa.String(length=64), nullable=False),
        sa.Column(
            "instance_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "lifecycle_status",
            sa.String(length=16),
            server_default="running",
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_heartbeat_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "stale_after_seconds",
            sa.Integer(),
            server_default=sa.text("120"),
            nullable=False,
        ),
        sa.Column("last_cycle_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_cycle_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_cycle_status", sa.String(length=16), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("message", sa.String(length=500), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
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
            "lifecycle_status IN ('running', 'stopped')",
            name="ck_worker_runtime_states_lifecycle_status",
        ),
        sa.CheckConstraint(
            "stale_after_seconds >= 30 AND stale_after_seconds <= 86400",
            name="ck_worker_runtime_states_stale_after_range",
        ),
        sa.CheckConstraint(
            "last_cycle_status IS NULL "
            "OR last_cycle_status IN ('running', 'succeeded', 'failed')",
            name="ck_worker_runtime_states_cycle_status",
        ),
        sa.CheckConstraint(
            "(lifecycle_status = 'stopped') = (stopped_at IS NOT NULL)",
            name="ck_worker_runtime_states_stopped_pair",
        ),
        sa.CheckConstraint(
            "last_heartbeat_at >= started_at",
            name="ck_worker_runtime_states_heartbeat_order",
        ),
        sa.CheckConstraint(
            "stopped_at IS NULL OR stopped_at >= started_at",
            name="ck_worker_runtime_states_stop_order",
        ),
        sa.CheckConstraint(
            "CASE "
            "WHEN last_cycle_status IS NULL THEN "
            "last_cycle_started_at IS NULL AND last_cycle_finished_at IS NULL "
            "WHEN last_cycle_status = 'running' THEN "
            "last_cycle_started_at IS NOT NULL AND last_cycle_finished_at IS NULL "
            "ELSE "
            "last_cycle_started_at IS NOT NULL AND last_cycle_finished_at IS NOT NULL "
            "END",
            name="ck_worker_runtime_states_cycle_shape",
        ),
        sa.CheckConstraint(
            "last_cycle_finished_at IS NULL "
            "OR last_cycle_finished_at >= last_cycle_started_at",
            name="ck_worker_runtime_states_cycle_order",
        ),
        sa.PrimaryKeyConstraint("worker_name"),
    )


def downgrade() -> None:
    op.drop_table("worker_runtime_states")
