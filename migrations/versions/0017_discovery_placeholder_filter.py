"""Allow discovery sources to reject placeholder URL slugs.

Revision ID: 0017_discovery_slug_filter
Revises: 0016_product_image_url
Create Date: 2026-07-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0017_discovery_slug_filter"
down_revision: str | Sequence[str] | None = "0016_product_image_url"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_discovery_sources_url_entry_filter",
        "discovery_sources",
        type_="check",
    )
    op.create_check_constraint(
        "ck_discovery_sources_url_entry_filter",
        "discovery_sources",
        "url_entry_filter IN "
        "('all', 'has_image', 'exclude_placeholder_slugs')",
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE discovery_sources
        SET url_entry_filter = 'all'
        WHERE url_entry_filter = 'exclude_placeholder_slugs'
        """
    )
    op.drop_constraint(
        "ck_discovery_sources_url_entry_filter",
        "discovery_sources",
        type_="check",
    )
    op.create_check_constraint(
        "ck_discovery_sources_url_entry_filter",
        "discovery_sources",
        "url_entry_filter IN ('all', 'has_image')",
    )
