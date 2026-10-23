"""Add a durable lifetime paid-call budget and per-attempt money evidence."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0020_cs_paid_budget"
down_revision = "0019_cs_handoff_expiry"
branch_labels = None
depends_on = None

TABLE = "customer_service_paid_budget"
RESERVATIONS = "customer_service_model_reservations"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("state", sa.String(16), nullable=False, server_default="disabled"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="200"),
        sa.Column("attempts_committed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cap_fen", sa.BigInteger(), nullable=False, server_default="2000"),
        sa.Column("charged_fen", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("price_card_sha256", sa.String(64)),
        sa.Column("price_card", postgresql.JSONB()),
        sa.Column("stopped_reason", sa.String(32)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("clock_timestamp()")),
        sa.Column("armed_at", sa.DateTime(timezone=True)),
        sa.Column("stopped_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("id = 1", name="ck_cs_paid_budget_singleton"),
        sa.CheckConstraint("state IN ('disabled', 'armed', 'stopped', 'blocked')",
                           name="ck_cs_paid_budget_state"),
        sa.CheckConstraint("max_attempts = 200", name="ck_cs_paid_budget_max_attempts"),
        sa.CheckConstraint("attempts_committed BETWEEN 0 AND max_attempts",
                           name="ck_cs_paid_budget_attempts"),
        sa.CheckConstraint("cap_fen = 2000", name="ck_cs_paid_budget_cap"),
        sa.CheckConstraint("charged_fen BETWEEN 0 AND cap_fen", name="ck_cs_paid_budget_charged"),
    )
    op.execute(f"INSERT INTO {TABLE} (id, state, max_attempts, attempts_committed, cap_fen, charged_fen)"
               " VALUES (1, 'disabled', 200, 0, 2000, 0)")

    op.add_column(RESERVATIONS, sa.Column("paid_reserved_fen", sa.BigInteger()))
    op.add_column(RESERVATIONS, sa.Column("paid_charged_fen", sa.BigInteger()))
    op.add_column(RESERVATIONS, sa.Column("paid_price_card_sha256", sa.String(64)))
    op.add_column(RESERVATIONS, sa.Column("paid_settled_at", sa.DateTime(timezone=True)))
    op.add_column(RESERVATIONS, sa.Column("dispatch_claimed_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        "ck_cs_model_paid_money", RESERVATIONS,
        "paid_reserved_fen IS NULL OR (paid_reserved_fen >= 0 AND "
        "(paid_charged_fen IS NULL OR (paid_charged_fen >= 0 AND paid_charged_fen <= paid_reserved_fen)))")
    op.create_index("ix_cs_model_dispatch_claim", RESERVATIONS, ["dispatch_claimed_at"],
                    postgresql_where=sa.text("dispatch_claimed_at IS NULL"))


def downgrade() -> None:
    op.drop_index("ix_cs_model_dispatch_claim", table_name=RESERVATIONS)
    op.drop_constraint("ck_cs_model_paid_money", RESERVATIONS, type_="check")
    op.drop_column(RESERVATIONS, "dispatch_claimed_at")
    op.drop_column(RESERVATIONS, "paid_settled_at")
    op.drop_column(RESERVATIONS, "paid_price_card_sha256")
    op.drop_column(RESERVATIONS, "paid_charged_fen")
    op.drop_column(RESERVATIONS, "paid_reserved_fen")
    op.drop_table(TABLE)
