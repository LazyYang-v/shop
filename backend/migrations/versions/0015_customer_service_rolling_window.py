"""Add event storage for atomic customer-service rolling limits."""

from alembic import op
import sqlalchemy as sa

revision = "0015_cs_rolling_window"
down_revision = "0014_cs_rate_expiry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customer_service_rate_limit_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("bucket_key", sa.String(length=160), nullable=False),
        sa.Column("event_at", sa.Float(), nullable=False),
    )
    op.create_index(
        "ix_customer_service_rate_limit_events_bucket_time",
        "customer_service_rate_limit_events",
        ["bucket_key", "event_at"],
    )
    op.create_index(
        "ix_customer_service_rate_limit_events_time",
        "customer_service_rate_limit_events",
        ["event_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_customer_service_rate_limit_events_time", table_name="customer_service_rate_limit_events")
    op.drop_index("ix_customer_service_rate_limit_events_bucket_time", table_name="customer_service_rate_limit_events")
    op.drop_table("customer_service_rate_limit_events")
