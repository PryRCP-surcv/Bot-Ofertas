"""Add auditable multi-destination notification routing.

Revision ID: 0018_multichannel_delivery
Revises: 0017_discovery_slug_filter
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_multichannel_delivery"
down_revision: str | Sequence[str] | None = "0017_discovery_slug_filter"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notification_deliveries",
        sa.Column(
            "provider",
            sa.String(length=32),
            nullable=False,
            server_default="telegram",
        ),
    )
    op.add_column(
        "notification_deliveries",
        sa.Column(
            "audience",
            sa.String(length=32),
            nullable=False,
            server_default="free",
        ),
    )
    op.add_column(
        "notification_deliveries",
        sa.Column(
            "dispatch_mode",
            sa.String(length=16),
            nullable=False,
            server_default="immediate",
        ),
    )
    op.add_column(
        "notification_deliveries",
        sa.Column(
            "routing_rule",
            sa.String(length=100),
            nullable=False,
            server_default="legacy_single_chat",
        ),
    )
    op.add_column(
        "notification_deliveries",
        sa.Column("routing_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "notification_deliveries",
        sa.Column(
            "routed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.add_column(
        "notification_deliveries",
        sa.Column(
            "scheduled_for",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.execute(
        """
        UPDATE notification_deliveries
        SET channel = 'telegram_free',
            provider = 'telegram',
            audience = 'free',
            dispatch_mode = 'immediate',
            routing_rule = 'phase6.7a_legacy_free_migration',
            routing_reason = 'destino histórico migrado al canal gratuito',
            routed_at = created_at,
            scheduled_for = created_at
        WHERE channel = 'telegram'
        """
    )
    op.execute(
        """
        UPDATE offer_alert_states
        SET channel = 'telegram_free'
        WHERE channel = 'telegram'
        """
    )
    op.create_check_constraint(
        "ck_notification_deliveries_route_non_empty",
        "notification_deliveries",
        "provider <> '' AND audience <> ''",
    )
    op.create_check_constraint(
        "ck_notification_deliveries_dispatch_mode",
        "notification_deliveries",
        "dispatch_mode IN ('immediate', 'mirrored', 'delayed')",
    )
    op.create_check_constraint(
        "ck_notification_deliveries_routing_rule_non_empty",
        "notification_deliveries",
        "routing_rule <> ''",
    )
    op.create_check_constraint(
        "ck_notification_deliveries_schedule_order",
        "notification_deliveries",
        "scheduled_for >= routed_at",
    )
    op.create_index(
        "ix_notification_deliveries_audience_sent",
        "notification_deliveries",
        ["provider", "audience", "sent_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notification_deliveries_audience_sent",
        table_name="notification_deliveries",
    )
    op.drop_constraint(
        "ck_notification_deliveries_schedule_order",
        "notification_deliveries",
        type_="check",
    )
    op.drop_constraint(
        "ck_notification_deliveries_routing_rule_non_empty",
        "notification_deliveries",
        type_="check",
    )
    op.drop_constraint(
        "ck_notification_deliveries_dispatch_mode",
        "notification_deliveries",
        type_="check",
    )
    op.drop_constraint(
        "ck_notification_deliveries_route_non_empty",
        "notification_deliveries",
        type_="check",
    )
    op.execute(
        """
        DELETE FROM notification_deliveries
        WHERE channel = 'telegram_vip'
        """
    )
    op.execute(
        """
        DELETE FROM offer_alert_states
        WHERE channel = 'telegram_vip'
        """
    )
    op.execute(
        """
        UPDATE notification_deliveries
        SET channel = 'telegram'
        WHERE channel = 'telegram_free'
        """
    )
    op.execute(
        """
        UPDATE offer_alert_states
        SET channel = 'telegram'
        WHERE channel = 'telegram_free'
        """
    )
    op.drop_column("notification_deliveries", "scheduled_for")
    op.drop_column("notification_deliveries", "routed_at")
    op.drop_column("notification_deliveries", "routing_reason")
    op.drop_column("notification_deliveries", "routing_rule")
    op.drop_column("notification_deliveries", "dispatch_mode")
    op.drop_column("notification_deliveries", "audience")
    op.drop_column("notification_deliveries", "provider")
