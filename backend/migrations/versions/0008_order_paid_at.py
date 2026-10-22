"""Record simulated payment time."""

from alembic import op
import sqlalchemy as sa

revision = "0008_order_paid_at"
down_revision = "0007_orders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "paid_at")
