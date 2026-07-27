"""Scope observation identity and history lookups to a tracked product.

Revision ID: 0003_observation_target_identity
Revises: 0002_product_claim_leases
Create Date: 2026-07-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_observation_target_identity"
down_revision: str | Sequence[str] | None = "0002_product_claim_leases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_price_observations_run_sku_seller",
        "price_observations",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_price_observations_run_target_sku_seller",
        "price_observations",
        ["run_id", "tracked_product_id", "sku", "seller_id"],
    )

    op.drop_index(
        "ix_price_observations_offer_history",
        table_name="price_observations",
    )
    op.create_index(
        "ix_price_observations_offer_history",
        "price_observations",
        ["tracked_product_id", "store_slug", "sku", "seller_id", "observed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_price_observations_offer_history",
        table_name="price_observations",
    )
    op.create_index(
        "ix_price_observations_offer_history",
        "price_observations",
        ["store_slug", "sku", "seller_id", "observed_at"],
        unique=False,
    )

    op.drop_constraint(
        "uq_price_observations_run_target_sku_seller",
        "price_observations",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_price_observations_run_sku_seller",
        "price_observations",
        ["run_id", "sku", "seller_id"],
    )
