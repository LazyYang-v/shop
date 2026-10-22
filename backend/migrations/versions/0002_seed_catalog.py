"""Seed one demo catalog product."""

from alembic import op
import sqlalchemy as sa


revision = "0002_seed_catalog"
down_revision = "0001_catalog"
branch_labels = None
depends_on = None

PRODUCT_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    products = sa.table(
        "products",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("category", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("image_url", sa.String()),
        sa.column("price", sa.Numeric(10, 2)),
        sa.column("stock", sa.Integer()),
        sa.column("is_listed", sa.Boolean()),
    )
    op.bulk_insert(
        products,
        [
            {
                "id": PRODUCT_ID,
                "name": "春日轻盈针织开衫",
                "category": "女装",
                "description": "柔软亲肤的日常针织开衫，适合春秋叠穿。",
                "image_url": "/images/cardigan.svg",
                "price": 129.00,
                "stock": 24,
                "is_listed": True,
            }
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM products WHERE id = :product_id").bindparams(
            product_id=PRODUCT_ID
        )
    )
