import pytest


def test_catalog_lists_products_from_database(client):
    response = client.get("/api/products", params={"category": "女装", "q": "春日轻盈针织开衫"})

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "name": "春日轻盈针织开衫",
                "category": "女装",
                "description": "柔软亲肤的日常针织开衫，适合春秋叠穿。",
                "image_url": "/images/cardigan.svg",
                "price": "129.00",
                "stock": 24,
            }
        ],
        "total": 1,
        "page": 1,
        "page_size": 20,
    }


def test_catalog_searches_filters_sorts_and_paginates_from_server(client):
    response = client.get("/api/products", params={"q": "针织", "category": "女装", "sort": "price_desc", "page": 1, "page_size": 10})
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["id"] == "00000000-0000-0000-0000-000000000001"


def test_catalog_rejects_unknown_sort_order(client):
    assert client.get("/api/products", params={"sort": "random"}).status_code == 422


def enable_customer_service_for_test(client, tmp_path):
    from uuid import uuid4
    from shop_api.customer_service import ProductFixture, SafeLogWriter

    client.app.state.customer_service_enabled = True
    log_directory = tmp_path / "customer-service-logs"
    log_directory.mkdir(mode=0o700)
    client.app.state.customer_service_log_writer = SafeLogWriter(str(log_directory))
    buyer_id = register_and_login_buyer(client, f"customer-service-{uuid4().hex}@example.com")
    from uuid import UUID
    client.app.state.customer_service_buyer_ids = {UUID(buyer_id)}
    client.app.state.customer_service_fixtures = {
        "00000000-0000-0000-0000-000000000001": ProductFixture(
            "00000000-0000-0000-0000-000000000001", "春日轻盈针织开衫", "女装", "129.00", 24, True
        )
    }


def register_and_login_buyer(client, email):
    csrf = client.get("/api/auth/csrf").json()["csrf_token"]
    headers = {"X-CSRF-Token": csrf, "Origin": "http://testserver"}
    registered = client.post("/api/auth/register", headers=headers, json={"email": email, "password": "portfolio-demo-pass-123"})
    assert registered.status_code == 201
    login_csrf = client.get("/api/auth/csrf").json()["csrf_token"]
    logged_in = client.post("/api/auth/login", headers={"X-CSRF-Token": login_csrf, "Origin": "http://testserver"}, json={"email": email, "password": "portfolio-demo-pass-123"})
    assert logged_in.status_code == 200
    return client.get("/api/auth/me").json()["id"]


def test_customer_service_product_search_returns_bounded_citable_catalog_facts(client, tmp_path):
    enable_customer_service_for_test(client, tmp_path)
    response = client.get("/api/customer-service/products", params={"q": "针织", "page": 1, "page_size": 10})

    assert response.status_code == 200
    result = response.json()
    assert result["request_id"]
    assert result["queried_at"].endswith("+00:00")
    assert result["status"] == "ok"
    assert response.headers["cache-control"] == "no-store"
    assert result["data"] == {
        "items": [{
            "id": "00000000-0000-0000-0000-000000000001",
            "name": "春日轻盈针织开衫",
            "category": "女装",
            "price": "129.00",
            "stock": 24,
            "is_listed": True,
        }],
        "total": 1,
        "page": 1,
        "page_size": 10,
        "has_more": False,
    }


def test_customer_service_product_search_distinguishes_empty_and_rejects_unknown_arguments(client, tmp_path):
    enable_customer_service_for_test(client, tmp_path)
    empty = client.get("/api/customer-service/products", params={"q": "不存在的商品"})
    assert empty.status_code == 200
    assert empty.json()["status"] == "empty"
    assert empty.json()["data"]["items"] == []
    assert client.get("/api/customer-service/products", params={"q": "针织", "sort": "popular"}).status_code == 422
    assert client.get("/api/customer-service/products", params={"q": "针织", "page_size": 21}).status_code == 422
    assert client.get("/api/customer-service/products", params={"q": "%"}).json()["status"] == "empty"


def test_customer_service_rejects_changed_fixture_facts(client, tmp_path):
    from sqlalchemy import text

    enable_customer_service_for_test(client, tmp_path)
    with client.app.state.session_factory.begin() as session:
        session.execute(text("UPDATE products SET stock = 23 WHERE id = '00000000-0000-0000-0000-000000000001'"))

    listing = client.get("/api/customer-service/products")
    detail = client.get("/api/customer-service/products/00000000-0000-0000-0000-000000000001")
    assert_customer_service_error(listing, 503, "dependency_unavailable")
    assert_customer_service_error(detail, 503, "dependency_unavailable")
    assert listing.json()["data"] is None
    assert detail.json()["data"] is None


def test_customer_service_product_routes_fail_closed_by_default(client):
    assert client.app.state.customer_service_enabled is False
    assert client.get("/api/customer-service/products", params={"q": "针织"}).status_code == 401
    assert client.get("/api/customer-service/products/00000000-0000-0000-0000-000000000001").status_code == 401


def test_customer_service_products_require_an_allowlisted_demo_buyer(client, tmp_path):
    enable_customer_service_for_test(client, tmp_path)
    client.app.state.customer_service_buyer_ids.clear()
    assert client.get("/api/customer-service/products", params={"q": "针织"}).status_code == 403


def test_customer_service_product_detail_returns_only_listed_products(client, tmp_path):
    enable_customer_service_for_test(client, tmp_path)
    product_id = "00000000-0000-0000-0000-000000000001"
    response = client.get(f"/api/customer-service/products/{product_id}")

    assert response.status_code == 200
    result = response.json()
    assert result["request_id"]
    assert result["queried_at"].endswith("+00:00")
    assert result["status"] == "ok"
    assert result["data"]["id"] == product_id
    assert result["data"]["price"] == "129.00"
    assert result["data"]["stock"] == 24
    assert "image_url" not in result["data"]
    assert "description" not in result["data"]
    assert client.get("/api/customer-service/products/not-a-uuid").status_code == 422


CUSTOMER_SERVICE_PATHS = [
    "/api/customer-service/products",
    "/api/customer-service/products/00000000-0000-0000-0000-000000000001",
]


def assert_customer_service_error(response, status_code, code):
    from datetime import datetime, timedelta
    from uuid import UUID

    assert response.status_code == status_code
    assert response.headers["cache-control"] == "no-store"
    result = response.json()
    assert set(result) == {"request_id", "queried_at", "status", "data", "code", "message"}
    assert UUID(result["request_id"]).version == 4
    assert datetime.fromisoformat(result["queried_at"]).utcoffset() == timedelta(0)
    assert result["status"] == ("unavailable" if status_code == 503 else "error")
    assert result["data"] is None
    assert result["code"] == code
    assert isinstance(result["message"], str) and result["message"]
    return result


@pytest.mark.parametrize("path", CUSTOMER_SERVICE_PATHS)
def test_customer_service_authentication_errors_use_contract(client, path):
    assert_customer_service_error(client.get(path), 401, "authentication_required")
    client.cookies.set("shop_session", "invalid-session")
    assert_customer_service_error(client.get(path), 401, "authentication_required")
    # Route-scoped handling must preserve the ordinary shop API contract.
    ordinary = client.get("/api/auth/me")
    assert ordinary.status_code == 401
    assert ordinary.json() == {"detail": "需要登录"}


@pytest.mark.parametrize("path", CUSTOMER_SERVICE_PATHS)
def test_customer_service_disabled_and_unauthorized_errors_use_contract(client, tmp_path, path):
    enable_customer_service_for_test(client, tmp_path)
    client.app.state.customer_service_enabled = False
    assert_customer_service_error(client.get(path), 503, "dependency_unavailable")
    client.app.state.customer_service_enabled = True
    client.app.state.customer_service_buyer_ids.clear()
    assert_customer_service_error(client.get(path), 403, "resource_unavailable")


@pytest.mark.parametrize("path,params", [
    (CUSTOMER_SERVICE_PATHS[0], {"page": 0}),
    (CUSTOMER_SERVICE_PATHS[0], {"page": "invalid"}),
    (CUSTOMER_SERVICE_PATHS[0], {"page": 101}),
    (CUSTOMER_SERVICE_PATHS[0], {"page_size": 21}),
    (CUSTOMER_SERVICE_PATHS[0], {"q": "x" * 101}),
    (CUSTOMER_SERVICE_PATHS[0], {"category": "x" * 65}),
    (CUSTOMER_SERVICE_PATHS[0], {"identity": "someone-else"}),
    (CUSTOMER_SERVICE_PATHS[1], {"identity": "someone-else"}),
    ("/api/customer-service/products/not-a-uuid", {}),
])
def test_customer_service_validation_errors_use_contract(client, tmp_path, path, params):
    enable_customer_service_for_test(client, tmp_path)
    response = client.get(path, params=params)
    assert_customer_service_error(response, 422, "invalid_input")
    assert "someone-else" not in response.text


@pytest.mark.parametrize("path", CUSTOMER_SERVICE_PATHS)
def test_customer_service_limiter_errors_preserve_contract_and_retry_after(client, tmp_path, monkeypatch, path):
    from shop_api.customer_service import CustomerServiceUnavailable

    enable_customer_service_for_test(client, tmp_path)
    limiter = client.app.state.customer_service_limiter
    monkeypatch.setattr(limiter, "allow", lambda *args: (False, 17))
    limited = client.get(path)
    assert_customer_service_error(limited, 429, "rate_limited")
    assert limited.headers["retry-after"] == "17"

    def fail(*args):
        raise CustomerServiceUnavailable("private-dependency-sentinel")

    monkeypatch.setattr(limiter, "allow", fail)
    unavailable = client.get(path)
    assert_customer_service_error(unavailable, 503, "dependency_unavailable")
    assert "private-dependency-sentinel" not in unavailable.text


@pytest.mark.parametrize("path", CUSTOMER_SERVICE_PATHS)
@pytest.mark.parametrize("query_fails", [False, True])
def test_customer_service_log_failure_returns_controlled_503_without_traceback(
    client, tmp_path, monkeypatch, caplog, path, query_fails
):
    from shop_api.customer_service import QueryDeadline

    enable_customer_service_for_test(client, tmp_path)

    def fail_write(*args):
        raise OSError("private-log-path-sentinel")

    def fail_query(*args):
        raise RuntimeError("private-query-sentinel")

    monkeypatch.setattr(client.app.state.customer_service_log_writer, "write", fail_write)
    if query_fails:
        monkeypatch.setattr(QueryDeadline, "apply", fail_query)
    # TestClient raises unhandled application exceptions by default.
    response = client.get(path)
    result = assert_customer_service_error(response, 503, "dependency_unavailable")
    assert "private-log-path-sentinel" not in response.text + caplog.text
    assert "private-query-sentinel" not in response.text + caplog.text
    assert all(record.exc_info is None for record in caplog.records)
    assert result["request_id"] in caplog.text


@pytest.mark.parametrize("path", CUSTOMER_SERVICE_PATHS)
def test_customer_service_query_failure_uses_same_request_id_in_safe_log(client, tmp_path, monkeypatch, path):
    import json
    from shop_api.customer_service_products import ProductTools

    enable_customer_service_for_test(client, tmp_path)

    def fail_query(*args):
        raise RuntimeError("private-query-sentinel")

    monkeypatch.setattr(ProductTools, "_read_products", fail_query)
    response = client.get(path)
    result = assert_customer_service_error(response, 503, "dependency_unavailable")
    log_file, = (tmp_path / "customer-service-logs").glob("*.jsonl")
    log = json.loads(log_file.read_text())
    assert log["request_id"] == result["request_id"]
    assert log["error"] == "dependency_unavailable"
    assert "private-query-sentinel" not in log_file.read_text() + response.text


def test_customer_service_applies_ip_limit_and_ignores_forwarded_headers(client, tmp_path, monkeypatch):
    import hashlib

    enable_customer_service_for_test(client, tmp_path)
    calls = []

    def allow(key, limit, window, now):
        calls.append((key, limit, window))
        return (False, 23) if key.startswith('ip:') else (True, 0)

    monkeypatch.setattr(client.app.state.customer_service_limiter, 'allow', allow)
    for path in CUSTOMER_SERVICE_PATHS:
        response = client.get(path, headers={'X-Forwarded-For': '203.0.113.7', 'Forwarded': 'for=203.0.113.8'})
        assert_customer_service_error(response, 429, 'rate_limited')
        assert response.headers['retry-after'] == '23'
    ip_calls = [call for call in calls if call[0].startswith('ip:')]
    assert ip_calls == [('ip:' + hashlib.sha256(b'testclient').hexdigest(), 60, 60)] * 2
    assert '203.0.113' not in str(calls)


def test_customer_service_unknown_and_unlisted_details_are_indistinguishable(client, tmp_path):
    from sqlalchemy import text

    enable_customer_service_for_test(client, tmp_path)
    unknown = client.get("/api/customer-service/products/ffffffff-ffff-4fff-8fff-ffffffffffff")
    with client.app.state.session_factory.begin() as session:
        session.execute(text("UPDATE products SET is_listed = false WHERE id = '00000000-0000-0000-0000-000000000001'"))
    unlisted = client.get(CUSTOMER_SERVICE_PATHS[1])
    first = assert_customer_service_error(unknown, 403, "resource_unavailable")
    assert first["message"] == "未找到可访问的记录"
    assert_customer_service_error(unlisted, 503, "dependency_unavailable")
