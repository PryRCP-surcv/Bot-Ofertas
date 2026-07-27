"""Add persistent per-store crawl circuit breakers.

Revision ID: 0004_store_circuit_breaker
Revises: 0003_observation_target_identity
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_store_circuit_breaker"
down_revision: str | Sequence[str] | None = "0003_observation_target_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "store_crawl_states",
        sa.Column("store_slug", sa.String(length=64), nullable=False),
        sa.Column("paused_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pause_reason", sa.Text(), nullable=True),
        sa.Column(
            "consecutive_blocks",
            sa.Integer(),
            server_default=sa.text("0"),
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
            "consecutive_blocks >= 0",
            name="ck_store_crawl_states_consecutive_blocks_non_negative",
        ),
        sa.CheckConstraint(
            "(paused_until IS NULL) = (pause_reason IS NULL)",
            name="ck_store_crawl_states_pause_pair",
        ),
        sa.PrimaryKeyConstraint("store_slug"),
    )
    op.create_index(
        "ix_store_crawl_states_paused_until",
        "store_crawl_states",
        ["paused_until"],
        unique=False,
        postgresql_where=sa.text("paused_until IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_store_crawl_states_paused_until",
        table_name="store_crawl_states",
    )
    op.drop_table("store_crawl_states")
