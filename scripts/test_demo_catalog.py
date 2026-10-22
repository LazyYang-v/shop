"""Pure, in-memory reconciliation regression tests; no shop database access.

Run: uv run --project backend python scripts/test_demo_catalog.py
"""
import unittest
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import Column, ForeignKey, MetaData, Table, Uuid, create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from shop_api.catalog import Product
from shop_api.demo_catalog import PRODUCT_MANIFEST, seed_demo_catalog, update_demo_metadata
from shop_api.identity import now_utc
import shop_api.reconcile_demo_catalog as reconciliation


class TestSession(Session):
    def execute(self, statement, *args, **kwargs):
        # SQLite has no table locks. This adapter exists only in this in-memory test.
        if str(statement).startswith("LOCK TABLE"):
            return None
        return super().execute(statement, *args, **kwargs)


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        @event.listens_for(self.engine, "connect")
        def configure(connection, record):
            connection.create_function("current_database", 0, lambda: "shop_dev")
            connection.execute("PRAGMA foreign_keys=ON")
        metadata = MetaData()
        Product.__table__.to_metadata(metadata)
        self.references = Table("history", metadata, Column("product_id", Uuid, ForeignKey("products.id")))
        metadata.create_all(self.engine)
        self.factory = sessionmaker(self.engine, class_=TestSession, expire_on_commit=False)
        # Production disposes after each call; retain the single in-memory database for assertions.
        self.dispose_patch = patch.object(self.engine, "dispose")
        self.dispose_patch.start()
        self.factory_patch = patch.object(reconciliation, "make_session_factory", return_value=self.factory)
        self.factory_patch.start()
        with self.factory.begin() as session:
            for name, row in PRODUCT_MANIFEST.items():
                product = self.product(name)
                update_demo_metadata(product, row)
                session.add(product)
            self.referenced = self.product("春日轻盈针织开衫")
            self.unreferenced = self.product("透气轻跑运动上衣")
            self.custom = self.product("管理员自己的商品")
            session.add_all([self.referenced, self.unreferenced, self.custom])
            session.flush()
            session.execute(self.references.insert().values(product_id=self.referenced.id))

    def tearDown(self):
        self.factory_patch.stop()
        self.dispose_patch.stop()
        self.engine.dispose()

    def product(self, name):
        return Product(id=uuid4(), name=name, category="旧分类", description="原描述", image_url="/old.jpg", price=9, stock=0, is_listed=True, created_at=now_utc(), listed_at=now_utc())

    def run_plan(self, **kwargs):
        return reconciliation.reconcile("postgresql://shop@127.0.0.1:55444/shop_dev", **kwargs)

    def test_dry_run_does_not_change_rows(self):
        plan = self.run_plan()
        self.assertEqual(len(plan["archive"]), 1)
        self.assertEqual(len(plan["delete"]), 1)
        with self.factory() as session:
            self.assertTrue(session.get(Product, self.referenced.id).is_listed)
            self.assertIsNotNone(session.get(Product, self.unreferenced.id))

    def test_apply_preserves_history_custom_stock_and_is_idempotent(self):
        self.run_plan(apply=True)
        self.run_plan(apply=True)
        with self.factory() as session:
            self.assertFalse(session.get(Product, self.referenced.id).is_listed)
            self.assertIsNone(session.get(Product, self.unreferenced.id))
            self.assertEqual(session.get(Product, self.custom.id).image_url, "/old.jpg")
            self.assertTrue(session.get(Product, self.custom.id).is_listed)
            self.assertEqual(session.scalar(select(func.count()).select_from(self.references)), 1)
            self.assertEqual(session.scalar(select(func.sum(Product.stock))), 0)
            self.assertEqual(session.scalar(select(func.count()).select_from(Product).where(Product.is_listed.is_(True))), len(PRODUCT_MANIFEST) + 1)

    def test_seed_existing_products_never_restocks(self):
        with self.factory.begin() as session:
            self.assertEqual(seed_demo_catalog(session, None), 0)
            self.assertEqual(session.scalar(select(func.sum(Product.stock))), 0)

    def test_archive_only_preserves_all_rows(self):
        plan = self.run_plan(apply=True, archive_only=True)
        self.assertEqual(plan["delete"], [])
        with self.factory() as session:
            self.assertFalse(session.get(Product, self.unreferenced.id).is_listed)
            self.assertEqual(session.scalar(select(func.count()).select_from(Product)), len(PRODUCT_MANIFEST) + 3)
            self.assertTrue(session.get(Product, self.custom.id).is_listed)

    def test_metadata_only_archives_without_deleting(self):
        plan = self.run_plan(apply=True, metadata_only=True)
        self.assertEqual(plan["delete"], [])
        with self.factory() as session:
            self.assertFalse(session.get(Product, self.unreferenced.id).is_listed)
            self.assertEqual(session.scalar(select(func.sum(Product.stock))), 0)

    def test_rejects_nonlocal_or_wrong_database_before_connection(self):
        for url in ("postgresql://shop@prod/shop_dev", "postgresql://shop@localhost/shop_test", "postgresql://shop@localhost/shop_dev?host=prod", "sqlite:///shop_dev"):
            with self.assertRaises(ValueError):
                reconciliation.reconcile(url, apply=True)


if __name__ == "__main__":
    unittest.main()
