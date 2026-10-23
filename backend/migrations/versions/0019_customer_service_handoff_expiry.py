"""Allow expired handoff secrets to be erased independently of active pages."""

from alembic import op
import sqlalchemy as sa

revision = "0019_cs_handoff_expiry"
down_revision = "0018_cs_model_slot_ttl"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("customer_service_pages", "handoff_hash", existing_type=sa.LargeBinary(32), nullable=True)


def downgrade() -> None:
    # Pages whose secret was erased cannot regain handoff eligibility.
    op.execute("DELETE FROM customer_service_pages WHERE handoff_hash IS NULL")
    op.alter_column("customer_service_pages", "handoff_hash", existing_type=sa.LargeBinary(32), nullable=False)
