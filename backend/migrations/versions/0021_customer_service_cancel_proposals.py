"""Add server-side order selection and cancellation proposals.

Only pending operations carry a credential hash. Page, consultation and session
links deliberately have no cascade so terminal evidence survives chat cleanup.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0021_cs_cancel_proposals"
down_revision = "0020_cs_paid_budget"
branch_labels = None
depends_on = None

OPERATIONS = "customer_service_cancel_operations"


def upgrade() -> None:
    op.add_column("customer_service_pages", sa.Column("selected_order_id", sa.Uuid(), nullable=True))
    op.add_column("customer_service_pages", sa.Column("selected_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        OPERATIONS,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("buyer_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("consultation_id", sa.Uuid(), nullable=False),
        sa.Column("page_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(16), nullable=False, server_default="cancel"),
        sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("credential_hash", sa.LargeBinary(32), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint("action = 'cancel'", name="ck_cs_cancel_ops_action"),
        sa.CheckConstraint("state IN ('pending', 'executed', 'rejected', 'expired')",
                           name="ck_cs_cancel_ops_state"),
        sa.CheckConstraint("state = 'pending' OR credential_hash IS NULL",
                           name="ck_cs_cancel_ops_terminal_secret"),
        sa.CheckConstraint("state <> 'pending' OR credential_hash IS NOT NULL",
                           name="ck_cs_cancel_ops_pending_secret"),
        sa.CheckConstraint("state = 'pending' OR terminal_at IS NOT NULL",
                           name="ck_cs_cancel_ops_terminal_at"),
    )
    op.create_index("ix_cs_cancel_ops_buyer", OPERATIONS, ["buyer_id"])
    op.create_index("ix_cs_cancel_ops_expires", OPERATIONS, ["expires_at"])
    op.create_index("uq_cs_cancel_ops_page_pending", OPERATIONS, ["page_id"], unique=True,
                    postgresql_where=sa.text("state = 'pending'"))


def downgrade() -> None:
    op.drop_index("uq_cs_cancel_ops_page_pending", table_name=OPERATIONS)
    op.drop_index("ix_cs_cancel_ops_expires", table_name=OPERATIONS)
    op.drop_index("ix_cs_cancel_ops_buyer", table_name=OPERATIONS)
    op.drop_table(OPERATIONS)
    op.drop_column("customer_service_pages", "selected_at")
    op.drop_column("customer_service_pages", "selected_order_id")
