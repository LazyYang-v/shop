"""Persist session-bound deterministic product consultations."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0016_cs_consultations"
down_revision = "0015_cs_rolling_window"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customer_service_consultations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("auth_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_cs_consultations_session", "customer_service_consultations", ["session_id"])
    op.create_table(
        "customer_service_pages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("auth_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("consultation_id", sa.Uuid(), sa.ForeignKey("customer_service_consultations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("handoff_hash", sa.LargeBinary(32), nullable=False, unique=True),
        sa.Column("handoff_expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_cs_pages_session", "customer_service_pages", ["session_id"])
    op.create_table(
        "customer_service_messages",
        sa.Column("consultation_id", sa.Uuid(), sa.ForeignKey("customer_service_consultations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("page_id", sa.Uuid(), primary_key=True),
        sa.Column("client_message_id", sa.Uuid(), primary_key=True),
        sa.Column("body_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("response", postgresql.JSONB(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("customer_service_messages")
    op.drop_table("customer_service_pages")
    op.drop_table("customer_service_consultations")
