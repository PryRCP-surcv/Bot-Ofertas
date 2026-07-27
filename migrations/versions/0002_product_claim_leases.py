"""Add scheduler leases and product failure tracking.

Revision ID: 0002_product_claim_leases
Revises: 0001_initial_schema
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_product_claim_leases"
down_revision: str | Sequence[str] | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tracked_products",
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "tracked_products",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tracked_products",
        sa.Column(
            "consecutive_failures",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_tracked_products_consecutive_failures_non_negative",
        "tracked_products",
        "consecutive_failures >= 0",
    )
    op.create_check_constraint(
        "ck_tracked_products_lease_pair",
        "tracked_products",
        "(lease_token IS NULL) = (lease_expires_at IS NULL)",
    )

    op.drop_index("ix_tracked_products_scheduler", table_name="tracked_products")
    op.create_index(
        "ix_tracked_products_scheduler",
        "tracked_products",
        ["store_slug", "last_checked_at", "lease_expires_at"],
        unique=False,
        postgresql_where=sa.text("active"),
    )


def downgrade() -> None:
    op.drop_index("ix_tracked_products_scheduler", table_name="tracked_products")
    op.create_index(
        "ix_tracked_products_scheduler",
        "tracked_products",
        ["active", "last_checked_at"],
        unique=False,
    )

    op.drop_constraint(
        "ck_tracked_products_lease_pair",
        "tracked_products",
        type_="check",
    )
    op.drop_constraint(
        "ck_tracked_products_consecutive_failures_non_negative",
        "tracked_products",
        type_="check",
    )
    op.drop_column("tracked_products", "consecutive_failures")
    op.drop_column("tracked_products", "lease_expires_at")
    op.drop_column("tracked_products", "lease_token")
