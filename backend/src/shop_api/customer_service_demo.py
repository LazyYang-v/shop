"""Explicit, insert-only initialization of the isolated fictional demo database."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from pwdlib import PasswordHash
from sqlalchemy import MetaData, inspect, select, text
from sqlalchemy.engine import make_url

from shop_api.catalog import Product
from shop_api.customer_service import check_fixture
from shop_api.database import make_session_factory
from shop_api.identity import Role, User, now_utc


@dataclass(frozen=True)
class DemoIdentity:
    id: UUID
    email: str
    role: str


DEMO_IDENTITIES = (
    DemoIdentity(UUID("de100000-0000-4000-8000-000000000001"), "buyer-one@customer-service.example", Role.BUYER.value),
    DemoIdentity(UUID("de100000-0000-4000-8000-000000000002"), "buyer-two@customer-service.example", Role.BUYER.value),
    DemoIdentity(UUID("de100000-0000-4000-8000-000000000003"), "admin@customer-service.example", Role.ADMIN.value),
)
SEED_ID = UUID("00000000-0000-0000-0000-000000000001")
SEED_DESCRIPTION = "柔软亲肤的日常针织开衫，适合春秋叠穿。"
SEED_IMAGE = "/images/cardigan.svg"


def _validate_target(database_url: str, expected_database: str) -> None:
    try:
        url = make_url(database_url)
        valid = (url.drivername in {"postgresql", "postgresql+psycopg"}
                 and url.database == expected_database
                 and url.host in {"shop-db", "localhost", "127.0.0.1", "::1"}
                 and not url.query)
    except Exception:
        valid = False
    if not valid:
        raise ValueError("Initializer requires the isolated local demo database without URL options")


def read_demo_passwords(secrets_file: str) -> dict[str, str]:
    """Read a private external JSON object keyed by the three fixed email addresses."""
    try:
        fd = os.open(secrets_file, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077
                    or info.st_uid != os.geteuid() or info.st_size > 8192):
                raise ValueError
            data = json.loads(stream.read(8193))
        _validate_passwords(data)
        return data
    except Exception:
        raise ValueError("Demo secrets must be an owner-only regular JSON file with three valid passwords") from None


def _validate_passwords(passwords: dict[str, str]) -> None:
    if (not isinstance(passwords, dict) or set(passwords) != {identity.email for identity in DEMO_IDENTITIES}
            or any(not isinstance(value, str) or not 12 <= len(value) <= 128 for value in passwords.values())
            or len(set(passwords.values())) != 3):
        raise ValueError("Provide three distinct passwords of 12 to 128 characters for the fixed demo identities")


def _load_fixture(path: str, expected_sha256: str) -> list[dict]:
    try:
        fixture = Path(path)
        if fixture.is_symlink() or not fixture.is_file() or fixture.stat().st_size > 65536:
            raise ValueError
        raw = fixture.read_bytes()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256) or not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), expected_sha256):
            raise ValueError
        data = json.loads(raw)
        if not isinstance(data, list) or not 1 <= len(data) <= 20:
            raise ValueError
        ids = set()
        for item in data:
            if not isinstance(item, dict) or set(item) != {"id", "name", "category", "price", "stock", "is_listed"}:
                raise ValueError
            product_id = UUID(item["id"])
            if str(product_id) != item["id"] or product_id in ids:
                raise ValueError
            ids.add(product_id)
            if (not isinstance(item["name"], str) or not 1 <= len(item["name"]) <= 160
                    or not isinstance(item["category"], str) or not 1 <= len(item["category"]) <= 80
                    or not isinstance(item["price"], str) or not re.fullmatch(r"[0-9]{1,8}\.[0-9]{2}", item["price"])
                    or Decimal(item["price"]) <= 0 or type(item["stock"]) is not int
                    or not 0 <= item["stock"] <= 2147483647 or item["is_listed"] is not True):
                raise ValueError
        return data
    except Exception:
        raise ValueError("Demo fixture or SHA256 is invalid") from None


def initialize_customer_service_demo(database_url: str, fixture_path: str, expected_sha256: str,
                                     passwords: dict[str, str], *, allow_migration_seed: bool = False) -> int:
    """Create all identities/products atomically; never update or delete any row.

    Normally every application table must be empty. Explicit migration-seed mode
    permits only the unchanged product from 0002 and guard singleton from 0017.
    """
    _validate_target(database_url, "shop_customer_service_demo")
    return _initialize(database_url, fixture_path, expected_sha256, passwords,
                       "shop_customer_service_demo", "public", allow_migration_seed)


def initialize_customer_service_demo_for_test(database_url: str, fixture_path: str, expected_sha256: str,
                                              passwords: dict[str, str], *, schema: str,
                                              allow_migration_seed: bool = False) -> int:
    """Test-only boundary: existing reset gate plus a fresh explicitly named schema."""
    from shop_api.testing import validate_test_database_url

    validate_test_database_url(database_url)
    url = make_url(database_url)
    if url.query or not re.fullmatch(r"demo_initializer_test_[0-9a-f]{32}", schema):
        raise ValueError("Initializer tests require an isolated test schema without URL options")
    return _initialize(database_url, fixture_path, expected_sha256, passwords, "shop_test", schema, allow_migration_seed)


def _initialize(database_url, fixture_path, expected_sha256, passwords, expected_database, schema, allow_migration_seed):
    _validate_passwords(passwords)
    fixtures = _load_fixture(fixture_path, expected_sha256)
    # Hash before opening the transaction; plaintext never enters SQL parameters.
    hasher = PasswordHash.recommended()
    hashes = {email: hasher.hash(password) for email, password in passwords.items()}
    factory = make_session_factory(database_url)
    try:
        with factory.begin() as session:
            if session.scalar(text("SELECT current_database()")) != expected_database:
                raise ValueError("Connected database does not match the explicit initialization target")
            session.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            connection = session.connection()
            names = inspect(connection).get_table_names(schema=schema)
            if not {"users", "products"}.issubset(names):
                raise ValueError("Apply the reviewed schema migrations before initialization")
            application_tables = sorted(name for name in names if name != "alembic_version")
            quote = connection.dialect.identifier_preparer.quote
            # Strong table locks serialize initializers and prevent concurrent inserts
            # between the emptiness check and commit, including unknown app tables.
            session.execute(text("LOCK TABLE " + ", ".join(f'{quote(schema)}.{quote(name)}' for name in application_tables) + " IN EXCLUSIVE MODE"))
            metadata = MetaData()
            metadata.reflect(bind=connection, schema=schema, only=application_tables)
            seed = None
            for name in application_tables:
                table = metadata.tables[f"{schema}.{name}"]
                rows = session.execute(select(table).limit(2)).mappings().all()
                if not rows:
                    continue
                row = dict(rows[0])
                if (allow_migration_seed and name == "customer_service_model_guard"
                        and len(rows) == 1 and row == {"id": 1, "metering_blocked": False}):
                    # Migration 0017 creates this singleton; it contains no usage.
                    continue
                if (allow_migration_seed and name == "customer_service_paid_budget"
                        and len(rows) == 1 and row.pop("created_at", None) is not None
                        and row == {
                            "id": 1, "state": "disabled", "max_attempts": 200,
                            "attempts_committed": 0, "cap_fen": 2000, "charged_fen": 0,
                            "price_card_sha256": None, "price_card": None,
                            "stopped_reason": None, "armed_at": None, "stopped_at": None}):
                    # Migration 0020 creates this singleton with no paid usage.
                    continue
                if name != "products" or not allow_migration_seed or len(rows) != 1:
                    raise ValueError("Demo initialization requires empty application tables")
                seed = dict(rows[0])
            if seed is not None:
                expected_seed = {"id": SEED_ID, "name": "春日轻盈针织开衫", "category": "女装",
                                 "description": SEED_DESCRIPTION, "image_url": SEED_IMAGE,
                                 "price": Decimal("129.00"), "stock": 24, "is_listed": True}
                if (set(seed) != set(expected_seed) | {"created_at", "listed_at"}
                        or any(seed[key] != value for key, value in expected_seed.items())
                        or seed["created_at"] is None or seed["listed_at"] != seed["created_at"]
                        or not any(all(item.get(key) == value for key, value in {
                            "id": str(SEED_ID), "name": expected_seed["name"], "category": "女装",
                            "price": "129.00", "stock": 24, "is_listed": True}.items()) for item in fixtures)):
                    raise ValueError("Existing product is not the exact approved migration baseline")
            current = now_utc()
            for identity in DEMO_IDENTITIES:
                session.add(User(id=identity.id, email=identity.email, role=identity.role,
                                 password_hash=hashes[identity.email], is_active=True, created_at=current))
            for item in fixtures:
                product_id = UUID(item["id"])
                if seed is not None and product_id == SEED_ID:
                    continue
                session.add(Product(id=product_id, name=item["name"], category=item["category"],
                                    description=SEED_DESCRIPTION if product_id == SEED_ID else "仅供客服隔离演示的虚构商品，不代表实际销售承诺。",
                                    image_url=SEED_IMAGE, price=Decimal(item["price"]), stock=item["stock"],
                                    is_listed=True, created_at=current, listed_at=current))
            session.flush()
            # Re-read both file digest and persisted rows through the startup boundary.
            check_fixture(session, fixture_path, expected_sha256)
        return len(fixtures)
    finally:
        factory.kw["bind"].dispose()
