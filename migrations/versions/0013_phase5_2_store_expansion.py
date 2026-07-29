"""Add the Phase 5.2 sitemap entry filter for reviewed mixed catalogues.

Revision ID: 0013_phase5_2_store_expansion
Revises: 0012_phase5_discovery
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_phase5_2_store_expansion"
down_revision: str | Sequence[str] | None = "0012_phase5_discovery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "discovery_sources",
        sa.Column(
            "url_entry_filter",
            sa.String(length=32),
            server_default=sa.text("'all'"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_discovery_sources_url_entry_filter",
        "discovery_sources",
        "url_entry_filter IN ('all', 'has_image')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_discovery_sources_url_entry_filter",
        "discovery_sources",
        type_="check",
    )
    op.drop_column("discovery_sources", "url_entry_filter")
