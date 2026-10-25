"""Add support knowledge, cases, scoped context, preferences and event reporting."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0022_cs_agent_platform"
down_revision = "0021_cs_cancel_proposals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customer_service_contexts",
        sa.Column("consultation_id", sa.Uuid(), sa.ForeignKey("customer_service_consultations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "customer_service_cases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("buyer_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("request_key", sa.String(160), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("priority", sa.String(16), nullable=False),
        sa.Column("order_id", sa.Uuid(), sa.ForeignKey("orders.id", ondelete="SET NULL")),
        sa.Column("assigned_to", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("summary", postgresql.JSONB(), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        sa.Column("messages", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("buyer_id", "request_key", name="uq_cs_case_request"),
        sa.CheckConstraint("status IN ('open','in_progress','waiting_buyer','resolved','rejected')", name="ck_cs_case_status"),
        sa.CheckConstraint("priority IN ('normal','urgent')", name="ck_cs_case_priority"),
    )
    op.create_index("ix_customer_service_cases_buyer_id", "customer_service_cases", ["buyer_id"])
    op.create_index("ix_customer_service_cases_expires_at", "customer_service_cases", ["expires_at"])
    op.create_table(
        "customer_service_preferences",
        sa.Column("buyer_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_customer_service_preferences_expires_at", "customer_service_preferences", ["expires_at"])
    op.create_table(
        "customer_service_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("consultation_id", sa.Uuid()), sa.Column("buyer_id", sa.Uuid()), sa.Column("case_id", sa.Uuid()),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for field in ("consultation_id", "kind", "created_at"):
        op.create_index(f"ix_customer_service_events_{field}", "customer_service_events", [field])
    op.create_table(
        "customer_service_channels",
        sa.Column("name", sa.String(24), primary_key=True),
        sa.Column("settings", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("name IN ('storefront','taobao','jd','douyin','pinduoduo')", name="ck_cs_channel_name"),
    )
    op.create_table(
        "customer_service_notifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("buyer_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_key", sa.String(160), nullable=False),
        sa.Column("text", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("buyer_id", "source_key", name="uq_cs_notification_source"),
    )
    op.create_index("ix_customer_service_notifications_buyer_id", "customer_service_notifications", ["buyer_id"])
    op.create_table(
        "customer_service_knowledge",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("topic", sa.String(100), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("keywords", postgresql.JSONB(), nullable=False),
        sa.Column("attributes", postgresql.JSONB(), nullable=False),
        sa.Column("product_id", sa.Uuid(), sa.ForeignKey("products.id", ondelete="CASCADE")),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("source", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('faq','product','policy','promotion')", name="ck_cs_knowledge_kind"),
        sa.CheckConstraint("state IN ('draft','published','retired')", name="ck_cs_knowledge_state"),
        sa.CheckConstraint("version > 0", name="ck_cs_knowledge_version"),
        sa.CheckConstraint("valid_until IS NULL OR valid_until > valid_from", name="ck_cs_knowledge_dates"),
    )


def downgrade() -> None:
    for name in ("knowledge", "notifications", "channels", "events", "preferences", "cases", "contexts"):
        op.drop_table("customer_service_" + name)
