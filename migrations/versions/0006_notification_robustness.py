"""Harden channel deduplication and notification state constraints.

Revision ID: 0006_notification_robustness
Revises: 0005_phase1_detection_alerts
Create Date: 2026-07-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_notification_robustness"
down_revision: str | Sequence[str] | None = "0005_phase1_detection_alerts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "offer_alert_states",
        sa.Column(
            "channel",
            sa.String(length=32),
            server_default=sa.text("'telegram'"),
            nullable=False,
        ),
    )
    op.drop_constraint(
        "offer_alert_states_pkey",
        "offer_alert_states",
        type_="primary",
    )
    op.create_primary_key(
        "offer_alert_states_pkey",
        "offer_alert_states",
        ["offer_key", "channel"],
    )
    op.create_check_constraint(
        "ck_offer_alert_states_channel_non_empty",
        "offer_alert_states",
        "channel <> ''",
    )

    op.create_check_constraint(
        "ck_deal_detections_classification",
        "deal_detections",
        "classification IN "
        "('none', 'good_deal', 'exceptional_deal', 'possible_price_error')",
    )
    op.create_check_constraint(
        "ck_deal_detections_notification_status",
        "deal_detections",
        "notification_status IN "
        "('not_applicable', 'pending', 'suppressed', 'retrying', "
        "'sent', 'failed', 'superseded')",
    )
    op.create_check_constraint(
        "ck_notification_deliveries_status",
        "notification_deliveries",
        "status IN ('pending', 'retrying', 'sent', 'failed', 'superseded')",
    )
    op.create_check_constraint(
        "ck_notification_deliveries_sent_pair",
        "notification_deliveries",
        "(status = 'sent') = (sent_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_notification_deliveries_channel_non_empty",
        "notification_deliveries",
        "channel <> ''",
    )

    op.drop_index(
        "ix_notification_deliveries_scheduler",
        table_name="notification_deliveries",
    )
    op.create_index(
        "ix_notification_deliveries_scheduler",
        "notification_deliveries",
        ["channel", "status", "next_attempt_at", "lease_expires_at"],
        unique=False,
        postgresql_where=sa.text("status IN ('pending', 'retrying')"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notification_deliveries_scheduler",
        table_name="notification_deliveries",
    )
    op.create_index(
        "ix_notification_deliveries_scheduler",
        "notification_deliveries",
        ["status", "next_attempt_at", "lease_expires_at"],
        unique=False,
        postgresql_where=sa.text("status IN ('pending', 'retrying')"),
    )
    op.drop_constraint(
        "ck_notification_deliveries_channel_non_empty",
        "notification_deliveries",
        type_="check",
    )
    op.drop_constraint(
        "ck_notification_deliveries_sent_pair",
        "notification_deliveries",
        type_="check",
    )
    op.drop_constraint(
        "ck_notification_deliveries_status",
        "notification_deliveries",
        type_="check",
    )
    op.drop_constraint(
        "ck_deal_detections_notification_status",
        "deal_detections",
        type_="check",
    )
    op.drop_constraint(
        "ck_deal_detections_classification",
        "deal_detections",
        type_="check",
    )
    op.drop_constraint(
        "ck_offer_alert_states_channel_non_empty",
        "offer_alert_states",
        type_="check",
    )
    op.drop_constraint(
        "offer_alert_states_pkey",
        "offer_alert_states",
        type_="primary",
    )
    op.create_primary_key(
        "offer_alert_states_pkey",
        "offer_alert_states",
        ["offer_key"],
    )
    op.drop_column("offer_alert_states", "channel")
