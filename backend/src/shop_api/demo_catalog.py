"""Explicit photo catalog. Existing inventory is never replenished by seeding."""
import json
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from shop_api.admin_catalog import InventoryAdjustment
from shop_api.catalog import Product
from shop_api.identity import now_utc

_DATA = json.loads(Path(__file__).with_name("demo_product_manifest.json").read_text())
PRODUCT_MANIFEST = MappingProxyType({name: MappingProxyType(row) for name, row in _DATA.items()})
PRODUCT_IMAGES = MappingProxyType({name: row["image_url"] for name, row in PRODUCT_MANIFEST.items()})
DEMO_PRODUCTS = tuple(
    (row["category"], name, row["description"], row["image_url"], row["price"], row["initial_stock"])
    for name, row in PRODUCT_MANIFEST.items()
)


def update_demo_metadata(product: Product, row) -> None:
    product.category = row["category"]
    product.description = row["description"]
    product.image_url = row["image_url"]
    product.price = Decimal(row["price"])
    if not product.is_listed:
        product.listed_at = now_utc()
    product.is_listed = True


def seed_demo_catalog(session: Session, admin_id) -> int:
    created = 0
    for name, row in PRODUCT_MANIFEST.items():
        matches = session.scalars(select(Product).where(Product.name == name)).all()
        if len(matches) > 1:
            raise ValueError(f"Ambiguous demo name: {name}; reconcile duplicates first")
        if matches:
            update_demo_metadata(matches[0], row)
            continue
        now = now_utc()
        stock = row["initial_stock"]
        product = Product(
            id=uuid4(), name=name, category=row["category"], description=row["description"],
            image_url=row["image_url"], price=Decimal(row["price"]), stock=stock,
            is_listed=True, created_at=now, listed_at=now,
        )
        session.add(product)
        session.flush()
        session.add(InventoryAdjustment(
            product_id=product.id, delta=stock, before_stock=0, after_stock=stock,
            reason="演示商品初始入库", admin_id=admin_id, created_at=now,
        ))
        created += 1
    return created
