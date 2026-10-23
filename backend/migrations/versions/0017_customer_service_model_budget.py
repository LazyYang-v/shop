"""Persist atomic model budgets and outstanding requests (no expiring leases)."""

from alembic import op
import sqlalchemy as sa

revision = "0017_cs_model_budget"
down_revision = "0016_cs_consultations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customer_service_model_guard",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("metering_blocked", sa.Boolean(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_cs_model_single_guard"),
    )
    op.execute("INSERT INTO customer_service_model_guard VALUES (1, false)")
    op.create_table(
        "customer_service_model_days",
        sa.Column("scope", sa.String(36), primary_key=True),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("tokens", sa.Integer(), nullable=False),
        sa.CheckConstraint("tokens >= 0 AND tokens <= 500000", name="ck_cs_model_day_tokens"),
    )
    op.create_table(
        "customer_service_model_reservations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        # Intentionally no cascading FK: logout/session deletion must not erase usage or slots.
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("charged_tokens", sa.Integer(), nullable=False),
        sa.Column("caller_timed_out", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("input_tokens >= 0 AND input_tokens <= 12000", name="ck_cs_model_input"),
        sa.CheckConstraint("charged_tokens >= 0 AND charged_tokens <= 13500", name="ck_cs_model_charge"),
    )
    op.create_index("ix_cs_model_outstanding", "customer_service_model_reservations", ["id"],
                    postgresql_where=sa.text("ended_at IS NULL"))


def downgrade() -> None:
    op.drop_table("customer_service_model_reservations")
    op.drop_table("customer_service_model_days")
    op.drop_table("customer_service_model_guard")
