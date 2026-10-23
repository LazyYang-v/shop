"""Add bounded local admission slots and explicit metering/settlement metadata."""

from alembic import op
import sqlalchemy as sa

revision = "0018_cs_model_slot_ttl"
down_revision = "0017_cs_model_budget"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = "customer_service_model_reservations"
    op.add_column(table, sa.Column("metering_mode", sa.String(16), nullable=False,
                                   server_default="verified"))
    op.add_column(table, sa.Column("expires_at", sa.DateTime(timezone=True)))
    op.add_column(table, sa.Column("settlement_reason", sa.String(16)))
    op.execute("""UPDATE customer_service_model_reservations
        SET expires_at=created_at + interval '90 seconds',
            settlement_reason=CASE WHEN ended_at IS NOT NULL THEN 'legacy' ELSE NULL END""")
    op.alter_column(table, "expires_at", nullable=False)
    op.create_check_constraint("ck_cs_model_metering_mode", table,
                               "metering_mode IN ('estimated', 'verified')")
    op.create_check_constraint("ck_cs_model_settlement_reason", table,
                               "settlement_reason IN ('assumed_max', 'actual_usage', 'legacy')")
    op.create_index("ix_cs_model_slot_expiry", table, ["expires_at"],
                    postgresql_where=sa.text("ended_at IS NULL"))


def downgrade() -> None:
    table = "customer_service_model_reservations"
    op.drop_index("ix_cs_model_slot_expiry", table_name=table)
    op.drop_constraint("ck_cs_model_settlement_reason", table, type_="check")
    op.drop_constraint("ck_cs_model_metering_mode", table, type_="check")
    op.drop_column(table, "settlement_reason")
    op.drop_column(table, "expires_at")
    op.drop_column(table, "metering_mode")
