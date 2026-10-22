"""Complete order lifecycle and enforce order invariants."""
from alembic import op
import sqlalchemy as sa

revision = "0010_order_lifecycle"
down_revision = "0009_product_created_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in ("closed_at", "shipped_at", "completed_at"):
        op.add_column("orders", sa.Column(name, sa.DateTime(timezone=True), nullable=True))
    op.add_column("orders", sa.Column("close_reason", sa.String(32), nullable=True))
    op.add_column("orders", sa.Column("shipping_company", sa.String(100), nullable=True))
    op.add_column("orders", sa.Column("tracking_number", sa.String(100), nullable=True))
    op.create_check_constraint("ck_orders_status", "orders", "status IN ('pending_payment', 'pending_shipment', 'pending_receipt', 'completed', 'closed')")
    op.create_check_constraint("ck_orders_total", "orders", "total >= 0")
    op.create_check_constraint("ck_order_items_quantity", "order_items", "quantity > 0")
    op.create_check_constraint("ck_order_items_amounts", "order_items", "unit_price >= 0 AND line_total >= 0")
    op.create_index("ix_orders_user_created", "orders", ["user_id", "created_at", "id"])
    op.create_index("ix_orders_status_expires", "orders", ["status", "expires_at"])


def downgrade() -> None:
    op.drop_index("ix_orders_status_expires", "orders")
    op.drop_index("ix_orders_user_created", "orders")
    op.drop_constraint("ck_order_items_amounts", "order_items", type_="check")
    op.drop_constraint("ck_order_items_quantity", "order_items", type_="check")
    op.drop_constraint("ck_orders_total", "orders", type_="check")
    op.drop_constraint("ck_orders_status", "orders", type_="check")
    for name in ("tracking_number", "shipping_company", "close_reason", "completed_at", "shipped_at", "closed_at"):
        op.drop_column("orders", name)
