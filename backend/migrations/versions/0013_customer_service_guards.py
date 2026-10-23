"""Shared customer-service rate-limit counters."""

from alembic import op
import sqlalchemy as sa

revision = "0013_customer_service_guards"
down_revision = "0012_inventory_capacity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customer_service_rate_limits",
        sa.Column("bucket_key", sa.String(length=160), primary_key=True),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.Column("window_started_at", sa.Float(), nullable=False),
        sa.CheckConstraint("hits > 0", name="ck_customer_service_rate_limit_hits"),
    )


def downgrade() -> None:
    op.drop_table("customer_service_rate_limits")
