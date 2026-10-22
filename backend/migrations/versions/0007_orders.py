"""Add checkout orders and item snapshots."""

from alembic import op
import sqlalchemy as sa

revision = "0007_orders"
down_revision = "0006_addresses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("orders",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("address_id", sa.Uuid(), nullable=False), sa.Column("recipient_name", sa.String(80), nullable=False),
        sa.Column("phone", sa.String(32), nullable=False), sa.Column("province", sa.String(80), nullable=False),
        sa.Column("city", sa.String(80), nullable=False), sa.Column("district", sa.String(80), nullable=False),
        sa.Column("detail", sa.String(240), nullable=False), sa.Column("status", sa.String(24), nullable=False),
        sa.Column("total", sa.Numeric(12, 2), nullable=False), sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_orders_user_idempotency"))
    op.create_table("order_items",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False), sa.Column("name", sa.String(160), nullable=False),
        sa.Column("image_url", sa.String(500), nullable=False), sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False), sa.Column("line_total", sa.Numeric(12, 2), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"))


def downgrade() -> None:
    op.drop_table("order_items")
    op.drop_table("orders")
