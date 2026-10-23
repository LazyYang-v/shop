"""Track expiry for customer-service shared rate-limit buckets."""

from alembic import op
import sqlalchemy as sa

revision = "0014_cs_rate_expiry"
down_revision = "0013_customer_service_guards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("customer_service_rate_limits", sa.Column("expires_at", sa.Float(), nullable=True))
    op.execute("UPDATE customer_service_rate_limits SET expires_at = window_started_at + 3600")
    op.alter_column("customer_service_rate_limits", "expires_at", nullable=False)
    op.create_index("ix_customer_service_rate_limits_expires_at", "customer_service_rate_limits", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_customer_service_rate_limits_expires_at", table_name="customer_service_rate_limits")
    op.drop_column("customer_service_rate_limits", "expires_at")
