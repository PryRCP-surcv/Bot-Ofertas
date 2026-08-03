"""Persist the product image used by offer notifications.

Revision ID: 0016_product_image_url
Revises: 0015_offer_episode_deduplication
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_product_image_url"
down_revision: str | Sequence[str] | None = "0015_offer_episode_deduplication"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "price_observations",
        sa.Column("image_url", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_price_observations_image_https",
        "price_observations",
        "image_url IS NULL OR image_url ~ '^https://[^[:space:]]+$'",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_price_observations_image_https",
        "price_observations",
        type_="check",
    )
    op.drop_column("price_observations", "image_url")
