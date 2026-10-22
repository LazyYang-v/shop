import os
import secrets
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from pwdlib import PasswordHash

from shop_api.app import create_app
from shop_api.identity import Role, User, now_utc
from shop_api.testing import UnsafeTestDatabaseError, validate_test_database_url


@pytest.fixture(scope="session")
def database_url() -> str:
    value = os.getenv("SHOP_TEST_DATABASE_URL", "")
    if not value:
        pytest.skip("SHOP_TEST_DATABASE_URL must point to a dedicated test database")
    try:
        validate_test_database_url(value)
    except UnsafeTestDatabaseError as error:
        pytest.fail(str(error))
    return value


@pytest.fixture(scope="session", autouse=True)
def migrated_test_database(database_url: str) -> Generator[None, None, None]:
    from alembic import command
    from alembic.config import Config

    url = make_url(database_url)
    engine = create_engine(url, pool_pre_ping=True)
    with engine.connect() as connection:
        actual_database = connection.execute(text("select current_database()")).scalar_one()
        if actual_database != url.database or actual_database != "shop_test":
            pytest.fail("Connected PostgreSQL database does not match the explicit test target")

    config = Config("backend/alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    ensure_baseline_seed(engine, url.database)
    ensure_demo_admin(engine, url.database)
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def reset_seed_product(database_url: str) -> Generator[None, None, None]:
    engine = create_engine(make_url(database_url), pool_pre_ping=True)
    with engine.begin() as connection:
        database_name = connection.execute(text("select current_database()")).scalar_one()
        if database_name != "shop_test":
            pytest.fail("Refusing to modify an unexpected PostgreSQL database")
        connection.execute(text("DELETE FROM order_items WHERE order_id IN (SELECT id FROM orders WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'checkout-%@example.com' OR email LIKE 'payment-%@example.com' OR email LIKE 'race-%@example.com'))"))
        connection.execute(text("DELETE FROM orders WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'checkout-%@example.com' OR email LIKE 'payment-%@example.com' OR email LIKE 'race-%@example.com')"))
        connection.execute(text("UPDATE products SET stock = 24, is_listed = true WHERE id = '00000000-0000-0000-0000-000000000001'"))
    yield
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM order_items WHERE order_id IN (SELECT id FROM orders WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'checkout-%@example.com' OR email LIKE 'payment-%@example.com' OR email LIKE 'race-%@example.com'))"))
        connection.execute(text("DELETE FROM orders WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'checkout-%@example.com' OR email LIKE 'payment-%@example.com' OR email LIKE 'race-%@example.com')"))
        connection.execute(text("UPDATE products SET stock = 24, is_listed = true WHERE id = '00000000-0000-0000-0000-000000000001'"))
    engine.dispose()


def ensure_baseline_seed(engine, expected_database: str) -> None:
    with engine.begin() as connection:
        actual_database = connection.execute(text("select current_database()")).scalar_one()
        if actual_database != expected_database or actual_database != "shop_test":
            pytest.fail("Refusing to modify an unexpected PostgreSQL database")
        connection.execute(text("""INSERT INTO products (id, name, category, description, image_url, price, stock, is_listed)
            VALUES ('00000000-0000-0000-0000-000000000001', '春日轻盈针织开衫', '女装',
            '柔软亲肤的日常针织开衫，适合春秋叠穿。', '/images/cardigan.svg', 129.00, 24, true)
            ON CONFLICT (id) DO NOTHING"""))


def ensure_demo_admin(engine, expected_database: str) -> None:
    email = "admin@example.com"
    password = os.environ.setdefault("SHOP_TEST_ADMIN_PASSWORD", secrets.token_urlsafe(24))
    with Session(engine) as session:
        actual_database = session.execute(text("select current_database()")).scalar_one()
        if actual_database != expected_database or actual_database != "shop_test":
            pytest.fail("Refusing to create a fixture in an unexpected PostgreSQL database")
        user = session.query(User).filter_by(email=email).one_or_none()
        if user is None:
            user = User(email=email, password_hash=PasswordHash.recommended().hash(password), role=Role.ADMIN.value, is_active=True, created_at=now_utc())
            session.add(user)
        else:
            user.password_hash = PasswordHash.recommended().hash(password)
            user.role = Role.ADMIN.value
            user.is_active = True
        session.commit()


@pytest.fixture
def client(database_url: str, migrated_test_database: None):
    app = create_app(database_url=database_url)
    with TestClient(app) as test_client:
        yield test_client
