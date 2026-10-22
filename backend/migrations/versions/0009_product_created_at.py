"""Add catalog publication ordering timestamp."""

from alembic import op
import sqlalchemy as sa

revision = "0009_product_created_at"
down_revision = "0008_order_paid_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))


def downgrade() -> None:
    op.drop_column("products", "created_at")
