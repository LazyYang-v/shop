"""Leave inventory capacity for restoring outstanding orders."""
from alembic import op
import sqlalchemy as sa

revision = "0012_inventory_capacity"
down_revision = "0011_admin_inventory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("products", "stock", type_=sa.BigInteger(), existing_type=sa.Integer())
    for name in ("before_stock", "after_stock"):
        op.alter_column("inventory_adjustments", name, type_=sa.BigInteger(), existing_type=sa.Integer())


def downgrade() -> None:
    # PostgreSQL rejects narrowing if existing inventory no longer fits.
    for name in ("before_stock", "after_stock"):
        op.alter_column("inventory_adjustments", name, type_=sa.Integer(), existing_type=sa.BigInteger())
    op.alter_column("products", "stock", type_=sa.Integer(), existing_type=sa.BigInteger())
