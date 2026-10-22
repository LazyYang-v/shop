"""Audit manual inventory adjustments and enforce catalog invariants."""

from alembic import op
import sqlalchemy as sa

revision = "0011_admin_inventory"
down_revision = "0010_order_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("listed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.execute("UPDATE products SET listed_at = created_at")
    op.create_check_constraint("ck_products_price_positive", "products", "price > 0")
    op.create_check_constraint("ck_products_name_nonempty", "products", "length(btrim(name)) > 0")
    op.create_check_constraint("ck_products_category_nonempty", "products", "length(btrim(category)) > 0")
    op.create_table(
        "inventory_adjustments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("before_stock", sa.Integer(), nullable=False),
        sa.Column("after_stock", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("admin_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["admin_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("delta <> 0", name="ck_inventory_adjustments_delta"),
        sa.CheckConstraint("before_stock >= 0 AND after_stock >= 0", name="ck_inventory_adjustments_stock"),
        sa.CheckConstraint("before_stock::bigint + delta::bigint = after_stock::bigint", name="ck_inventory_adjustments_balance"),
        sa.CheckConstraint("length(btrim(reason)) > 0", name="ck_inventory_adjustments_reason"),
    )
    op.create_index("ix_inventory_adjustments_product_created", "inventory_adjustments", ["product_id", "created_at", "id"])


def downgrade() -> None:
    op.drop_column("products", "listed_at")
    op.drop_index("ix_inventory_adjustments_product_created", "inventory_adjustments")
    op.drop_table("inventory_adjustments")
    for name in ("ck_products_category_nonempty", "ck_products_name_nonempty", "ck_products_price_positive"):
        op.drop_constraint(name, "products", type_="check")
