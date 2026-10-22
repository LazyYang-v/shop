"""Dry-run first cleanup of the exact historical demo-name allowlist."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import struct

from sqlalchemy import MetaData, Table, func, inspect, select, text
from sqlalchemy.engine import make_url

from shop_api.catalog import Product
from shop_api.database import make_session_factory
from shop_api.demo_catalog import PRODUCT_MANIFEST, update_demo_metadata
from shop_api.identity import Role, User


def jpeg_dimensions(data: bytes) -> tuple[int, int]:
    if data[:2] != b"\xff\xd8":
        raise ValueError("Expected JPEG image")
    offset = 2
    while offset < len(data):
        if data[offset] != 255:
            raise ValueError("Invalid JPEG marker")
        while data[offset] == 255:
            offset += 1
        marker = data[offset]
        offset += 1
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        length = struct.unpack_from(">H", data, offset)[0]
        if marker in {0xC0, 0xC1, 0xC2}:
            height, width = struct.unpack_from(">HH", data, offset + 3)
            return width, height
        if length < 2:
            break
        offset += length
    raise ValueError("JPEG dimensions missing")


def validate_images(public_dir: Path) -> dict:
    seen = set()
    paths = set()
    categories = Counter()
    for name, row in PRODUCT_MANIFEST.items():
        path = (public_dir / row["image_url"].lstrip("/")).resolve()
        if not path.is_relative_to(public_dir.resolve()):
            raise ValueError(f"Image path escapes public directory: {name}")
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        dimensions = jpeg_dimensions(data)
        if digest != row["sha256"] or dimensions != (row["width"], row["height"]):
            raise ValueError(f"Image changed: {name}")
        if digest in seen or path in paths or min(dimensions) < 200:
            raise ValueError(f"Duplicate or undersized image: {name}")
        seen.add(digest)
        paths.add(path)
        categories[row["category"]] += 1
    return {"products": len(seen), "categories": dict(categories)}


def reconcile(database_url: str, *, apply: bool = False, metadata_only: bool = False, archive_only: bool = False) -> dict:
    url = make_url(database_url)
    if (url.get_backend_name() != "postgresql" or url.database != "shop_dev"
            or url.host not in {"localhost", "127.0.0.1", "::1"} or url.query):
        raise ValueError("Reconciliation requires PostgreSQL shop_dev on a loopback host, without URL query overrides")
    retired = set(json.loads(Path(__file__).with_name("retired_demo_names.json").read_text()))
    known = retired | set(PRODUCT_MANIFEST)
    factory = make_session_factory(database_url)
    report = {"mode": "apply" if apply else "dry-run", "metadata_only": metadata_only, "archive_only": archive_only,
              "update": [], "create": [], "delete": [], "archive": [], "missing": []}
    try:
        with factory() as session:
            if session.scalar(text("SELECT current_database()")) != "shop_dev":
                raise ValueError("Connected database is not shop_dev")
            if apply:
                session.execute(text("LOCK TABLE products IN SHARE ROW EXCLUSIVE MODE"))
            connection = session.connection()
            inspector = inspect(connection)
            metadata = MetaData()
            references = []
            # Discover every inbound FK, including future audit or feature tables.
            for table_name in inspector.get_table_names():
                for fk in inspector.get_foreign_keys(table_name):
                    if fk["referred_table"] != "products":
                        continue
                    if fk["referred_columns"] != ["id"] or len(fk["constrained_columns"]) != 1:
                        raise ValueError(f"Unsupported product foreign key in {table_name}")
                    table = Table(table_name, metadata, autoload_with=connection, extend_existing=True)
                    references.append((table, table.c[fk["constrained_columns"][0]]))
            products = session.scalars(select(Product).where(Product.name.in_(known)).order_by(Product.created_at, Product.id)).all()
            groups = {}
            for product in products:
                groups.setdefault(product.name, []).append(product)
            for name, matches in groups.items():
                for index, product in enumerate(matches):
                    if name in PRODUCT_MANIFEST and index == 0:
                        report["update"].append({"id": str(product.id), "name": name})
                        if apply:
                            update_demo_metadata(product, PRODUCT_MANIFEST[name])
                        continue
                    refs = {table.name: session.scalar(select(func.count()).select_from(table).where(column == product.id))
                            for table, column in references}
                    refs = {table: count for table, count in refs.items() if count}
                    action = "archive" if refs or metadata_only or archive_only else "delete"
                    report[action].append({"id": str(product.id), "name": name, "references": refs})
                    if apply:
                        if refs or metadata_only or archive_only:
                            product.is_listed = False
                        else:
                            session.delete(product)
            missing = sorted(set(PRODUCT_MANIFEST) - set(groups))
            report["missing" if metadata_only else "create"] = missing
            report["foreign_key_tables"] = sorted({table.name for table, _ in references})
            if apply:
                session.flush()
                if missing and not metadata_only:
                    admin_id = session.scalar(select(User.id).where(User.role == Role.ADMIN.value, User.is_active.is_(True)).order_by(User.id).limit(1))
                    if admin_id is None:
                        raise ValueError("An active admin is required to audit initial stock for new products")
                    # Duplicate canonical-name rows were already archived. Insert only missing names.
                    from uuid import uuid4
                    from decimal import Decimal
                    from shop_api.admin_catalog import InventoryAdjustment
                    from shop_api.identity import now_utc
                    for name in missing:
                        row = PRODUCT_MANIFEST[name]
                        now = now_utc()
                        stock = row["initial_stock"]
                        product = Product(id=uuid4(), name=name, category=row["category"], description=row["description"], image_url=row["image_url"], price=Decimal(row["price"]), stock=stock, is_listed=True, created_at=now, listed_at=now)
                        session.add(product)
                        session.flush()
                        session.add(InventoryAdjustment(product_id=product.id, delta=stock, before_stock=0, after_stock=stock, reason="演示商品初始入库", admin_id=admin_id, created_at=now))
                session.commit()
            else:
                session.rollback()
    finally:
        factory.kw["bind"].dispose()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Commit the plan; default only reads")
    parser.add_argument("--archive-only", action="store_true", help="Retire surplus products without deleting any rows; still create missing products")
    parser.add_argument("--metadata-only", action="store_true", help="Update metadata/listing and retire surplus rows; never insert products or inventory audits")
    parser.add_argument("--validate-images", type=Path, metavar="PUBLIC_DIR", help="Validate local files without connecting to a database")
    args = parser.parse_args()
    if args.validate_images:
        if args.apply:
            parser.error("--validate-images cannot be combined with --apply")
        result = validate_images(args.validate_images)
    else:
        database_url = os.getenv("SHOP_DATABASE_URL")
        if not database_url:
            parser.error("SHOP_DATABASE_URL must be configured")
        result = reconcile(database_url, apply=args.apply, metadata_only=args.metadata_only, archive_only=args.archive_only)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
