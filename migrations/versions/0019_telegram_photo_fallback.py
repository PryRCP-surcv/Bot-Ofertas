"""Audit Telegram photo URL, upload, and text fallback deliveries.

Revision ID: 0019_telegram_photo_fallback
Revises: 0018_multichannel_delivery
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_telegram_photo_fallback"
down_revision: str | Sequence[str] | None = "0018_multichannel_delivery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notification_deliveries",
        sa.Column("delivery_method", sa.String(length=32), nullable=True),
    )
    op.create_check_constraint(
        "ck_notification_deliveries_method",
        "notification_deliveries",
        "delivery_method IS NULL OR delivery_method IN "
        "('photo_url', 'photo_upload', 'text', 'text_fallback')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_notification_deliveries_method",
        "notification_deliveries",
        type_="check",
    )
    op.drop_column("notification_deliveries", "delivery_method")
