"""Add persistent watchdog incident deduplication.

Revision ID: 0011_worker_watchdog_state
Revises: 0010_worker_runtime_state
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_worker_watchdog_state"
down_revision: str | Sequence[str] | None = "0010_worker_runtime_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "worker_watchdog_states",
        sa.Column("worker_name", sa.String(length=64), nullable=False),
        sa.Column(
            "last_observed_state",
            sa.String(length=16),
            server_default="unknown",
            nullable=False,
        ),
        sa.Column(
            "last_observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "incident_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("incident_opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("incident_alerted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_alert_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_recovery_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_notification_error", sa.Text(), nullable=True),
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
            "last_observed_state IN ('running', 'stale', 'stopped', 'unknown')",
            name="ck_worker_watchdog_states_observed_state",
        ),
        sa.CheckConstraint(
            "(incident_id IS NULL) = (incident_opened_at IS NULL)",
            name="ck_worker_watchdog_states_incident_pair",
        ),
        sa.CheckConstraint(
            "incident_alerted_at IS NULL OR incident_id IS NOT NULL",
            name="ck_worker_watchdog_states_alert_incident",
        ),
        sa.CheckConstraint(
            "incident_alerted_at IS NULL "
            "OR incident_alerted_at >= incident_opened_at",
            name="ck_worker_watchdog_states_alert_order",
        ),
        sa.PrimaryKeyConstraint("worker_name"),
    )


def downgrade() -> None:
    op.drop_table("worker_watchdog_states")
