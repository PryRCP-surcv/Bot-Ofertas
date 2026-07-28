"""Allow useful conditioned offers under the Phase 3 v2 detector.

Revision ID: 0008_conditioned_offers
Revises: 0007_phase3_detection
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_conditioned_offers"
down_revision: str | Sequence[str] | None = "0007_phase3_detection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "deal_detections",
        "detector_version",
        existing_type=sa.String(length=40),
        existing_nullable=False,
        server_default=sa.text("'phase3-v2'"),
    )


def downgrade() -> None:
    op.alter_column(
        "deal_detections",
        "detector_version",
        existing_type=sa.String(length=40),
        existing_nullable=False,
        server_default=sa.text("'phase3-v1'"),
    )
