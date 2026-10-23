"""Initializer boundary tests. Run only with coordinated shop_test reset authorization."""
import hashlib
import json
import secrets
from pathlib import Path
from uuid import uuid4

import pytest
from pwdlib import PasswordHash
from sqlalchemy import create_engine, text

from shop_api.customer_service_demo import (
    DEMO_IDENTITIES,
    initialize_customer_service_demo,
    initialize_customer_service_demo_for_test,
    read_demo_passwords,
)
from shop_api.testing import validate_test_database_url


FIXTURE = Path(__file__).resolve().parents[2] / "deploy/customer-service-demo/products.v1.json"
DIGEST = "b730b65266d096918f8f5e085c960ed5acccf6378b3b1e222bfa379141169b1b"


@pytest.fixture
def passwords():
    return {identity.email: secrets.token_urlsafe(24) for identity in DEMO_IDENTITIES}


@pytest.fixture
def isolated_schema(database_url):
    validate_test_database_url(database_url)
    schema = f"demo_initializer_test_{uuid4().hex}"
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            assert connection.scalar(text("SELECT current_database()")) == "shop_test"
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            for name in ("products", "users", "auth_sessions"):
                connection.execute(text(f'CREATE TABLE "{schema}".{name} (LIKE public.{name} INCLUDING ALL)'))
            connection.execute(text(f'CREATE TABLE "{schema}".unexpected_application_rows (id integer)'))
        yield engine, schema
    finally:
        validate_test_database_url(database_url)
        with engine.begin() as connection:
            assert connection.scalar(text("SELECT current_database()")) == "shop_test"
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def initialize(database_url, schema, passwords, **kwargs):
    return initialize_customer_service_demo_for_test(
        database_url, str(FIXTURE), DIGEST, passwords, schema=schema, **kwargs,
    )


def test_atomic_creation_matches_startup_fixture(database_url, isolated_schema, passwords):
    engine, schema = isolated_schema
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == DIGEST
    assert initialize(database_url, schema, passwords) == 4
    with engine.connect() as connection:
        rows = connection.execute(text(f'SELECT id, email, role, password_hash, is_active FROM "{schema}".users')).mappings().all()
        assert len(rows) == 3
        for identity in DEMO_IDENTITIES:
            row = next(row for row in rows if row["id"] == identity.id)
            assert (row["email"], row["role"], row["is_active"]) == (identity.email, identity.role, True)
            assert PasswordHash.recommended().verify(passwords[identity.email], row["password_hash"])
        assert connection.scalar(text(f'SELECT count(*) FROM "{schema}".products')) == 4
        before = connection.execute(text(f'SELECT * FROM "{schema}".users ORDER BY id')).all()
    with pytest.raises(ValueError, match="empty application"):
        initialize(database_url, schema, passwords)
    with engine.connect() as connection:
        assert connection.execute(text(f'SELECT * FROM "{schema}".users ORDER BY id')).all() == before


@pytest.mark.parametrize("table", ["unexpected_application_rows", "products"])
def test_refuses_existing_rows(database_url, isolated_schema, passwords, table):
    engine, schema = isolated_schema
    with engine.begin() as connection:
        if table == "unexpected_application_rows":
            connection.execute(text(f'INSERT INTO "{schema}".{table} VALUES (1)'))
        else:
            connection.execute(text(f'''INSERT INTO "{schema}".products
                (id, name, category, description, image_url, price, stock, is_listed, created_at, listed_at)
                VALUES ('00000000-0000-0000-0000-000000000001', '春日轻盈针织开衫', '女装',
                '柔软亲肤的日常针织开衫，适合春秋叠穿。', '/images/cardigan.svg', 129, 24, true, now(), now())'''))
    with pytest.raises(ValueError, match="empty application"):
        initialize(database_url, schema, passwords)
    with engine.connect() as connection:
        assert connection.scalar(text(f'SELECT count(*) FROM "{schema}".users')) == 0


def test_explicit_exact_migration_baseline_reused(database_url, isolated_schema, passwords):
    engine, schema = isolated_schema
    with engine.begin() as connection:
        connection.execute(text(f'''INSERT INTO "{schema}".products
            (id, name, category, description, image_url, price, stock, is_listed, created_at, listed_at)
            VALUES ('00000000-0000-0000-0000-000000000001', '春日轻盈针织开衫', '女装',
            '柔软亲肤的日常针织开衫，适合春秋叠穿。', '/images/cardigan.svg', 129, 24, true, now(), now())'''))
        before = connection.execute(text(f'SELECT * FROM "{schema}".products')).one()
    assert initialize(database_url, schema, passwords, allow_migration_seed=True) == 4
    with engine.connect() as connection:
        assert connection.execute(text(f'SELECT * FROM "{schema}".products WHERE id=:id'), {"id": before.id}).one() == before


@pytest.mark.parametrize("column,value", [("description", "changed"), ("image_url", "/images/changed.svg"), ("stock", 25)])
def test_modified_baseline_rejected(database_url, isolated_schema, passwords, column, value):
    engine, schema = isolated_schema
    with engine.begin() as connection:
        connection.execute(text(f'''INSERT INTO "{schema}".products
            (id, name, category, description, image_url, price, stock, is_listed, created_at, listed_at)
            VALUES ('00000000-0000-0000-0000-000000000001', '春日轻盈针织开衫', '女装',
            '柔软亲肤的日常针织开衫，适合春秋叠穿。', '/images/cardigan.svg', 129, 24, true, now(), now())'''))
        connection.execute(text(f'UPDATE "{schema}".products SET {column}=:value'), {"value": value})
    with pytest.raises(ValueError, match="exact approved"):
        initialize(database_url, schema, passwords, allow_migration_seed=True)


def test_full_migration_baseline_initializes(database_url, isolated_schema, passwords, monkeypatch):
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory

    engine, schema = isolated_schema
    monkeypatch.delenv("SHOP_ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("SHOP_ADMIN_PASSWORD_HASH", raising=False)
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "migrations"))
    scripts = ScriptDirectory.from_config(config)
    with engine.begin() as connection:
        connection.execute(text(f'DROP TABLE "{schema}".products, "{schema}".users, "{schema}".auth_sessions'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        with Operations.context(MigrationContext.configure(connection)):
            for revision in reversed(list(scripts.walk_revisions())):
                revision.module.upgrade()
        before = connection.execute(text(f'SELECT * FROM "{schema}".customer_service_model_guard')).all()
    assert initialize(database_url, schema, passwords, allow_migration_seed=True) == 4
    with engine.connect() as connection:
        assert connection.execute(text(f'SELECT * FROM "{schema}".customer_service_model_guard')).all() == before


@pytest.mark.parametrize("blocked", [False, True])
def test_model_guard_baseline_is_explicit_and_exact(database_url, isolated_schema, passwords, blocked):
    engine, schema = isolated_schema
    with engine.begin() as connection:
        connection.execute(text(f'CREATE TABLE "{schema}".customer_service_model_guard (id integer, metering_blocked boolean)'))
        connection.execute(text(f'INSERT INTO "{schema}".customer_service_model_guard VALUES (1, :blocked)'), {"blocked": blocked})
    if blocked:
        with pytest.raises(ValueError, match="empty application"):
            initialize(database_url, schema, passwords, allow_migration_seed=True)
    else:
        with pytest.raises(ValueError, match="empty application"):
            initialize(database_url, schema, passwords)
        assert initialize(database_url, schema, passwords, allow_migration_seed=True) == 4


def test_post_insert_failure_rolls_back(database_url, isolated_schema, passwords, monkeypatch):
    engine, schema = isolated_schema

    def reject(*args):
        raise RuntimeError("synthetic verification failure")

    monkeypatch.setattr("shop_api.customer_service_demo.check_fixture", reject)
    with pytest.raises(RuntimeError, match="synthetic verification"):
        initialize(database_url, schema, passwords)
    with engine.connect() as connection:
        for name in ("products", "users"):
            assert connection.scalar(text(f'SELECT count(*) FROM "{schema}".{name}')) == 0


@pytest.mark.parametrize("url", [
    "postgresql+psycopg://u:p@localhost/shop_dev",
    "postgresql+psycopg://u:p@localhost/shop_test",
    "postgresql+psycopg://u:p@db/shop_customer_service_demo",
    "postgresql+psycopg://u:p@remote.example/shop_customer_service_demo",
    "postgresql+psycopg://u:p@shop-db/shop_customer_service_demo?host=remote.example",
    "sqlite:///:memory:",
])
def test_production_boundary_rejects_unsafe_targets(url, passwords):
    with pytest.raises(ValueError, match="isolated local"):
        initialize_customer_service_demo(url, str(FIXTURE), DIGEST, passwords)


def test_hash_mismatch_rejected_before_writes(database_url, isolated_schema, passwords):
    engine, schema = isolated_schema
    with pytest.raises(ValueError, match="SHA256"):
        initialize_customer_service_demo_for_test(database_url, str(FIXTURE), "0" * 64, passwords, schema=schema)
    with engine.connect() as connection:
        assert connection.scalar(text(f'SELECT count(*) FROM "{schema}".users')) == 0


def test_test_boundary_requires_reset_gate(database_url, passwords, monkeypatch):
    monkeypatch.delenv("SHOP_ALLOW_TEST_DATABASE_RESET", raising=False)
    with pytest.raises(RuntimeError, match="SHOP_ALLOW_TEST_DATABASE_RESET"):
        initialize_customer_service_demo_for_test(database_url, str(FIXTURE), DIGEST, passwords,
                                                 schema=f"demo_initializer_test_{uuid4().hex}")


@pytest.mark.parametrize("mutation", ["too_many", "duplicate", "extra_field", "negative_stock"])
def test_invalid_fixture_rejected(database_url, isolated_schema, passwords, tmp_path, mutation):
    _, schema = isolated_schema
    data = json.loads(FIXTURE.read_text())
    if mutation == "too_many":
        data = data * 6
    elif mutation == "duplicate":
        data.append(data[0])
    elif mutation == "extra_field":
        data[0]["description"] = "unapproved"
    else:
        data[0]["stock"] = -1
    path = tmp_path / "fixture.json"
    raw = json.dumps(data).encode()
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="fixture"):
        initialize_customer_service_demo_for_test(database_url, str(path), hashlib.sha256(raw).hexdigest(),
                                                 passwords, schema=schema)


def test_private_password_file(tmp_path, passwords):
    path = tmp_path / "private.json"
    path.write_text(json.dumps(passwords))
    path.chmod(0o600)
    assert read_demo_passwords(str(path)) == passwords
    path.chmod(0o644)
    with pytest.raises(ValueError, match="owner-only"):
        read_demo_passwords(str(path))
    path.chmod(0o600)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="owner-only"):
        read_demo_passwords(str(link))
