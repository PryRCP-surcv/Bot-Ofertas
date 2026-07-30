"""Add Phase 6.1 manual subscriber and commercial beta administration.

Revision ID: 0014_phase6_1_commercial_beta
Revises: 0013_phase5_2_store_expansion
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_phase6_1_commercial_beta"
down_revision: str | Sequence[str] | None = "0013_phase5_2_store_expansion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECKLIST_ITEMS = (
    {
        "item_key": "approve_initial_catalog",
        "position": 1,
        "title": "Aprobar el catálogo inicial",
        "description": (
            "Revisar una muestra útil de productos por tienda antes de invitar "
            "a los primeros usuarios."
        ),
        "category": "catalog",
        "required": True,
    },
    {
        "item_key": "validate_telegram_delivery",
        "position": 2,
        "title": "Validar una alerta real en Telegram",
        "description": (
            "Comprobar formato, enlace y precio con el mismo grupo privado que "
            "recibirá las ofertas."
        ),
        "category": "distribution",
        "required": True,
    },
    {
        "item_key": "configure_private_group",
        "position": 3,
        "title": "Configurar el grupo como privado",
        "description": (
            "Usar un enlace de invitación controlado y confirmar que solo el "
            "administrador puede incorporar miembros."
        ),
        "category": "distribution",
        "required": True,
    },
    {
        "item_key": "publish_group_rules",
        "position": 4,
        "title": "Publicar reglas del grupo",
        "description": (
            "Indicar frecuencia de mensajes, soporte, vigencia de la membresía "
            "y comportamiento esperado."
        ),
        "category": "commercial",
        "required": True,
    },
    {
        "item_key": "publish_offer_disclaimer",
        "position": 5,
        "title": "Publicar advertencia sobre las ofertas",
        "description": (
            "Aclarar que precios, stock y condiciones pertenecen a cada tienda "
            "y pueden cambiar o ser cancelados."
        ),
        "category": "commercial",
        "required": True,
    },
    {
        "item_key": "verify_backup_restore",
        "position": 6,
        "title": "Comprobar recuperación de respaldo",
        "description": (
            "Verificar que el historial y los registros comerciales se puedan "
            "restaurar antes de aceptar pagos."
        ),
        "category": "operations",
        "required": True,
    },
    {
        "item_key": "complete_24h_smoke",
        "position": 7,
        "title": "Completar una prueba continua de 24 horas",
        "description": (
            "Mantener el trabajador activo un día completo y revisar rastreos, "
            "bloqueos y entregas."
        ),
        "category": "operations",
        "required": True,
    },
    {
        "item_key": "invite_pilot_users",
        "position": 8,
        "title": "Invitar al grupo piloto",
        "description": (
            "Comenzar con pocos usuarios identificados, registrar su vigencia "
            "y recoger comentarios."
        ),
        "category": "launch",
        "required": False,
    },
)


def upgrade() -> None:
    op.create_table(
        "beta_subscribers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("telegram_username", sa.String(length=32), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'trial'"),
            nullable=False,
        ),
        sa.Column(
            "telegram_membership_status",
            sa.String(length=16),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            sa.String(length=200),
            server_default=sa.text("'local-admin'"),
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
            "btrim(full_name) <> ''",
            name="ck_beta_subscribers_full_name_non_empty",
        ),
        sa.CheckConstraint(
            "telegram_username = lower(telegram_username) "
            "AND telegram_username ~ '^[a-z][a-z0-9_]{4,31}$'",
            name="ck_beta_subscribers_telegram_username",
        ),
        sa.CheckConstraint(
            "status IN ('trial', 'active', 'expired', 'suspended')",
            name="ck_beta_subscribers_status",
        ),
        sa.CheckConstraint(
            "telegram_membership_status IN ('pending', 'in_group', 'removed')",
            name="ck_beta_subscribers_membership_status",
        ),
        sa.CheckConstraint(
            "expires_at > starts_at",
            name="ck_beta_subscribers_validity_order",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_beta_subscribers_version_positive",
        ),
        sa.CheckConstraint(
            "email IS NULL OR btrim(email) <> ''",
            name="ck_beta_subscribers_email_non_empty",
        ),
        sa.CheckConstraint(
            "phone IS NULL OR btrim(phone) <> ''",
            name="ck_beta_subscribers_phone_non_empty",
        ),
        sa.CheckConstraint(
            "notes IS NULL OR btrim(notes) <> ''",
            name="ck_beta_subscribers_notes_non_empty",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_beta_subscribers"),
        sa.UniqueConstraint(
            "telegram_username",
            name="uq_beta_subscribers_telegram_username",
        ),
    )
    op.create_index(
        "ix_beta_subscribers_status_expiry",
        "beta_subscribers",
        ["status", "expires_at"],
    )
    op.create_index(
        "ix_beta_subscribers_membership",
        "beta_subscribers",
        ["telegram_membership_status", "updated_at"],
    )
    op.create_index(
        "ix_beta_subscribers_created",
        "beta_subscribers",
        ["created_at", "id"],
    )

    op.create_table(
        "beta_payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "subscriber_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "currency",
            sa.String(length=3),
            server_default=sa.text("'PEN'"),
            nullable=False,
        ),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("reference", sa.String(length=200), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "coverage_starts_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "coverage_ends_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("renewal_days", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("recorded_by", sa.String(length=200), nullable=False),
        sa.Column("idempotency_key_hash", sa.String(length=64), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "amount > 0",
            name="ck_beta_payments_amount_positive",
        ),
        sa.CheckConstraint(
            "currency = 'PEN'",
            name="ck_beta_payments_currency_pen",
        ),
        sa.CheckConstraint(
            "method IN ('yape', 'plin', 'bank_transfer', 'cash', 'other')",
            name="ck_beta_payments_method",
        ),
        sa.CheckConstraint(
            "coverage_ends_at > coverage_starts_at",
            name="ck_beta_payments_coverage_order",
        ),
        sa.CheckConstraint(
            "renewal_days BETWEEN 1 AND 366",
            name="ck_beta_payments_renewal_days",
        ),
        sa.CheckConstraint(
            "reference IS NULL OR btrim(reference) <> ''",
            name="ck_beta_payments_reference_non_empty",
        ),
        sa.CheckConstraint(
            "notes IS NULL OR btrim(notes) <> ''",
            name="ck_beta_payments_notes_non_empty",
        ),
        sa.CheckConstraint(
            "idempotency_key_hash ~ '^[0-9a-f]{64}$' "
            "AND request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_beta_payments_idempotency_hashes",
        ),
        sa.ForeignKeyConstraint(
            ["subscriber_id"],
            ["beta_subscribers.id"],
            name="fk_beta_payments_subscriber_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_beta_payments"),
        sa.UniqueConstraint(
            "idempotency_key_hash",
            name="uq_beta_payments_idempotency_hash",
        ),
    )
    op.create_index(
        "ix_beta_payments_subscriber_paid",
        "beta_payments",
        ["subscriber_id", "paid_at", "id"],
    )
    op.create_index(
        "ix_beta_payments_paid",
        "beta_payments",
        ["paid_at", "id"],
    )

    checklist = op.create_table(
        "beta_launch_checklist_items",
        sa.Column("item_key", sa.String(length=64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=600), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column(
            "required",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "completed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by", sa.String(length=200), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(item_key) <> '' AND btrim(title) <> '' "
            "AND btrim(description) <> '' AND btrim(category) <> ''",
            name="ck_beta_launch_checklist_text_non_empty",
        ),
        sa.CheckConstraint(
            "position >= 1",
            name="ck_beta_launch_checklist_position_positive",
        ),
        sa.CheckConstraint(
            "(completed = false AND completed_at IS NULL "
            "AND completed_by IS NULL) OR "
            "(completed = true AND completed_at IS NOT NULL "
            "AND btrim(completed_by) <> '')",
            name="ck_beta_launch_checklist_completion_shape",
        ),
        sa.PrimaryKeyConstraint(
            "item_key",
            name="pk_beta_launch_checklist_items",
        ),
        sa.UniqueConstraint(
            "position",
            name="uq_beta_launch_checklist_position",
        ),
    )
    op.create_index(
        "ix_beta_launch_checklist_category_position",
        "beta_launch_checklist_items",
        ["category", "position"],
    )
    op.bulk_insert(checklist, list(_CHECKLIST_ITEMS))


def downgrade() -> None:
    op.drop_index(
        "ix_beta_launch_checklist_category_position",
        table_name="beta_launch_checklist_items",
    )
    op.drop_table("beta_launch_checklist_items")
    op.drop_index("ix_beta_payments_paid", table_name="beta_payments")
    op.drop_index(
        "ix_beta_payments_subscriber_paid",
        table_name="beta_payments",
    )
    op.drop_table("beta_payments")
    op.drop_index("ix_beta_subscribers_created", table_name="beta_subscribers")
    op.drop_index(
        "ix_beta_subscribers_membership",
        table_name="beta_subscribers",
    )
    op.drop_index(
        "ix_beta_subscribers_status_expiry",
        table_name="beta_subscribers",
    )
    op.drop_table("beta_subscribers")
