import asyncio
import hashlib
import json
from sqlalchemy import select
from shop_api.identity import Role, User

from shop_api.app import create_app


def test_demo_mode_disables_public_registration(client, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("SHOP_CUSTOMER_SERVICE_DEMO_MODE", "1")
    app = create_app(database_url=client.app.state.session_factory.kw["bind"].url.render_as_string(hide_password=False))
    with TestClient(app) as demo:
        csrf = demo.get("/api/auth/csrf").json()["csrf_token"]
        result = demo.post(
            "/api/auth/register",
            json={"email": "blocked-demo@example.com", "password": "fictional-password-123"},
            headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
        )
        assert result.status_code == 403
        assert result.json()["detail"] == "演示环境不开放注册"


def configured_fixture(tmp_path, client):
    fixture_path = tmp_path / "fixture.json"
    fixture = [{"id": "00000000-0000-0000-0000-000000000001", "name": "春日轻盈针织开衫", "category": "女装", "price": "129.00", "stock": 24, "is_listed": True}]
    raw = json.dumps(fixture, ensure_ascii=False).encode()
    fixture_path.write_bytes(raw)
    log_directory = tmp_path / "logs"
    log_directory.mkdir(mode=0o700)
    with client.app.state.session_factory() as session:
        buyer_ids = session.scalars(select(User.id).where(User.role == Role.BUYER.value, User.is_active.is_(True)).order_by(User.id).limit(2)).all()
    return str(fixture_path), hashlib.sha256(raw).hexdigest(), str(log_directory), ",".join(str(value) for value in buyer_ids)


def test_customer_service_startup_enables_only_with_verified_fixture_and_private_logs(client, tmp_path, monkeypatch):
    fixture_path, digest, log_directory, buyer_ids = configured_fixture(tmp_path, client)
    monkeypatch.setenv("SHOP_CUSTOMER_SERVICE_DEMO_MODE", "1")
    monkeypatch.setenv("SHOP_CUSTOMER_SERVICE_FIXTURE_PATH", fixture_path)
    monkeypatch.setenv("SHOP_CUSTOMER_SERVICE_FIXTURE_SHA256", digest)
    monkeypatch.setenv("SHOP_CUSTOMER_SERVICE_LOG_DIRECTORY", log_directory)
    monkeypatch.setenv("SHOP_CUSTOMER_SERVICE_BUYER_IDS", buyer_ids)

    app = create_app(database_url=client.app.state.session_factory.kw["bind"].url.render_as_string(hide_password=False))

    async def check_lifespan():
        async with app.router.lifespan_context(app):
            assert app.state.customer_service_enabled is True
            assert set(app.state.customer_service_fixtures) == {"00000000-0000-0000-0000-000000000001"}

    asyncio.run(check_lifespan())


def test_customer_service_startup_fails_closed_without_demo_mode_or_matching_digest(client, tmp_path, monkeypatch):
    fixture_path, digest, log_directory, buyer_ids = configured_fixture(tmp_path, client)
    monkeypatch.delenv("SHOP_CUSTOMER_SERVICE_DEMO_MODE", raising=False)
    monkeypatch.setenv("SHOP_CUSTOMER_SERVICE_FIXTURE_PATH", fixture_path)
    monkeypatch.setenv("SHOP_CUSTOMER_SERVICE_FIXTURE_SHA256", digest)
    monkeypatch.setenv("SHOP_CUSTOMER_SERVICE_LOG_DIRECTORY", log_directory)
    monkeypatch.setenv("SHOP_CUSTOMER_SERVICE_BUYER_IDS", buyer_ids)

    app = create_app(database_url=client.app.state.session_factory.kw["bind"].url.render_as_string(hide_password=False))

    async def check_disabled_lifespan():
        async with app.router.lifespan_context(app):
            assert app.state.customer_service_enabled is False

    asyncio.run(check_disabled_lifespan())

    monkeypatch.setenv("SHOP_CUSTOMER_SERVICE_DEMO_MODE", "1")
    monkeypatch.setenv("SHOP_CUSTOMER_SERVICE_FIXTURE_SHA256", "0" * 64)
    app = create_app(database_url=client.app.state.session_factory.kw["bind"].url.render_as_string(hide_password=False))

    async def check_invalid_lifespan():
        async with app.router.lifespan_context(app):
            assert app.state.customer_service_enabled is False

    asyncio.run(check_invalid_lifespan())
