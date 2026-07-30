"""Prevent unchanged offers from being re-sent after the cooldown.

Revision ID: 0015_offer_episode_deduplication
Revises: 0014_phase6_1_commercial_beta
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_offer_episode_deduplication"
down_revision: str | Sequence[str] | None = "0014_phase6_1_commercial_beta"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "offer_alert_states",
        sa.Column(
            "episode_active",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "offer_alert_states",
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "offer_alert_states",
        sa.Column("last_inactive_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE offer_alert_states "
            "SET episode_active = true, last_seen_at = last_reserved_at "
            "WHERE last_reserved_at IS NOT NULL"
        )
    )
    op.create_check_constraint(
        "ck_offer_alert_states_active_seen",
        "offer_alert_states",
        "NOT episode_active OR last_seen_at IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_offer_alert_states_active_seen",
        "offer_alert_states",
        type_="check",
    )
    op.drop_column("offer_alert_states", "last_inactive_at")
    op.drop_column("offer_alert_states", "last_seen_at")
    op.drop_column("offer_alert_states", "episode_active")
