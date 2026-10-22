import os
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def admin_login(client):
    token = client.get("/api/auth/csrf").json()["csrf_token"]
    response = client.post("/api/auth/login", headers={"X-CSRF-Token": token, "Origin": "http://testserver"},
                           json={"email": "admin@example.com", "password": os.environ["SHOP_TEST_ADMIN_PASSWORD"]})
    assert response.status_code == 200
    return {"X-CSRF-Token": response.headers["X-CSRF-Token"], "Origin": "http://testserver"}


def product_payload(**changes):
    return {"name": f"管理商品-{uuid4().hex}", "category": "测试分类", "description": "商品说明",
            "image_url": "/images/cardigan.svg", "price": "12.30", "is_listed": False, **changes}


def test_admin_creates_reads_and_searches_unlisted_product_with_zero_stock(client):
    headers = admin_login(client)
    payload = product_payload()
    response = client.post("/api/admin/products", headers=headers, json=payload)
    assert response.status_code == 201
    product = response.json()
    assert product == {**payload, "id": product["id"], "stock": 0, "created_at": product["created_at"]}
    assert client.get(f"/api/admin/products/{product['id']}").json() == product
    listing = client.get("/api/admin/products", params={"q": payload["name"], "page_size": 1}).json()
    assert listing == {"items": [product], "total": 1, "page": 1, "page_size": 1}
    assert client.get(f"/api/products/{product['id']}").status_code == 404


def test_product_writes_require_csrf_and_same_origin(client):
    headers = admin_login(client)
    for invalid in ({}, {"Origin": "http://testserver"}, {**headers, "Origin": "https://evil.example"}):
        assert client.post("/api/admin/products", headers=invalid, json=product_payload()).status_code == 403


def test_admin_can_edit_and_list_product_but_cannot_patch_stock(client):
    headers = admin_login(client)
    product = client.post("/api/admin/products", headers=headers, json=product_payload()).json()
    url = f"/api/admin/products/{product['id']}"
    updated = client.patch(url, headers=headers, json={"name": "新版商品", "price": "25.90", "is_listed": True})
    assert updated.status_code == 200
    assert updated.json()["name"] == "新版商品"
    assert updated.json()["price"] == "25.90"
    assert client.get(f"/api/products/{product['id']}").status_code == 200
    assert client.patch(url, headers=headers, json={"stock": 30}).status_code == 422
    assert client.get(url).json()["stock"] == 0


@pytest.mark.parametrize("changes", [
    {"name": "  "}, {"category": "\t"}, {"price": "0"}, {"price": "-1.00"},
    {"price": "1.234"}, {"price": "NaN"}, {"price": "100000000.00"},
    {"stock": 1}, {"unexpected": True}, {"image_url": "javascript:alert(1)"},
    {"image_url": "data:image/svg+xml,test"}, {"image_url": "//evil.example/image"},
    {"image_url": "/images/../secret"}, {"image_url": "https:///image"},
])
def test_product_validation_rejects_invalid_create_and_patch(client, changes):
    headers = admin_login(client)
    product = client.post("/api/admin/products", headers=headers, json=product_payload()).json()
    assert client.post("/api/admin/products", headers=headers, json=product_payload(**changes)).status_code == 422
    assert client.patch(f"/api/admin/products/{product['id']}", headers=headers, json=changes).status_code == 422


def test_product_patch_rejects_explicit_null(client):
    headers = admin_login(client)
    product = client.post("/api/admin/products", headers=headers, json=product_payload()).json()
    for field in ("name", "category", "description", "image_url", "price", "is_listed"):
        assert client.patch(f"/api/admin/products/{product['id']}", headers=headers, json={field: None}).status_code == 422


def test_inventory_adjustment_is_audited_and_rejected_reduction_is_atomic(client):
    headers = admin_login(client)
    product = client.post("/api/admin/products", headers=headers, json=product_payload()).json()
    url = f"/api/admin/products/{product['id']}/inventory-adjustments"
    admin_id = client.get("/api/auth/me").json()["id"]
    added = client.post(url, headers=headers, json={"delta": 5, "reason": " 首次入库 "})
    assert added.status_code == 201
    audit = added.json()
    assert audit == {"id": audit["id"], "product_id": product["id"], "delta": 5,
                     "before_stock": 0, "after_stock": 5, "reason": "首次入库",
                     "admin_id": admin_id, "created_at": audit["created_at"]}
    removed = client.post(url, headers=headers, json={"delta": -2, "reason": "损坏"})
    assert removed.status_code == 201
    assert removed.json()["before_stock"] == 5
    assert removed.json()["after_stock"] == 3
    assert client.post(url, headers=headers, json={"delta": -4, "reason": "过量扣减"}).status_code == 409
    assert client.get(f"/api/admin/products/{product['id']}").json()["stock"] == 3
    assert client.get(url).json() == {"items": [removed.json(), audit], "total": 2, "page": 1, "page_size": 20}


@pytest.mark.parametrize("payload", [
    {"delta": 0, "reason": "无变化"}, {"delta": True, "reason": "错误数量"},
    {"delta": 1.5, "reason": "错误数量"}, {"delta": "1", "reason": "错误类型"},
    {"delta": 1, "reason": "  "}, {"delta": 1, "reason": "原因", "admin_id": str(uuid4())},
])
def test_inventory_adjustment_rejects_invalid_input(client, payload):
    headers = admin_login(client)
    product = client.post("/api/admin/products", headers=headers, json=product_payload()).json()
    url = f"/api/admin/products/{product['id']}/inventory-adjustments"
    assert client.post(url, headers=headers, json=payload).status_code == 422
    assert client.get(url).json()["total"] == 0


def test_concurrent_inventory_reductions_serialize_without_negative_stock(client):
    headers = admin_login(client)
    product = client.post("/api/admin/products", headers=headers, json=product_payload()).json()
    url = f"/api/admin/products/{product['id']}/inventory-adjustments"
    assert client.post(url, headers=headers, json={"delta": 5, "reason": "入库"}).status_code == 201
    cookie = client.cookies.get("shop_session")
    barrier = threading.Barrier(2)

    def reduce_stock(_):
        with client.__class__(client.app, cookies={"shop_session": cookie}) as local:
            barrier.wait()
            return local.post(url, headers=headers, json={"delta": -4, "reason": "并发扣减"})

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(reduce_stock, range(2)))
    assert sorted(response.status_code for response in responses) == [201, 409]
    assert client.get(f"/api/admin/products/{product['id']}").json()["stock"] == 1
    audit = client.get(url).json()
    assert audit["total"] == 2
    assert audit["items"][0]["before_stock"] == 5
    assert audit["items"][0]["after_stock"] == 1


def test_all_admin_catalog_routes_reject_guests_and_buyers(client):
    product_id = "00000000-0000-0000-0000-000000000001"
    base = f"/api/admin/products/{product_id}"
    routes = [("GET", "/api/admin/products", None), ("POST", "/api/admin/products", product_payload()),
              ("GET", base, None), ("PATCH", base, {"name": "越权"}),
              ("GET", base + "/inventory-adjustments", None),
              ("POST", base + "/inventory-adjustments", {"delta": 1, "reason": "越权"})]
    for method, url, payload in routes:
        assert client.request(method, url, json=payload).status_code == 401
    token = client.get("/api/auth/csrf").json()["csrf_token"]
    headers = {"X-CSRF-Token": token, "Origin": "http://testserver"}
    credentials = {"email": f"admin-denied-{uuid4().hex}@example.com", "password": "portfolio-demo-pass-123"}
    assert client.post("/api/auth/register", headers=headers, json=credentials).status_code == 201
    login = client.post("/api/auth/login", headers=headers, json=credentials)
    headers["X-CSRF-Token"] = login.headers["X-CSRF-Token"]
    for method, url, payload in routes:
        assert client.request(method, url, headers=headers, json=payload).status_code == 403


def test_relisting_product_moves_it_to_top_of_popular_catalog(client):
    headers = admin_login(client)
    marker = uuid4().hex
    first = client.post("/api/admin/products", headers=headers, json=product_payload(name=marker + "甲", is_listed=True)).json()
    second = client.post("/api/admin/products", headers=headers, json=product_payload(name=marker + "乙", is_listed=True)).json()
    url = f"/api/admin/products/{first['id']}"
    assert client.get("/api/products", params={"q": marker}).json()["items"][0]["id"] == second["id"]
    assert client.patch(url, headers=headers, json={"is_listed": False}).status_code == 200
    assert client.patch(url, headers=headers, json={"is_listed": True}).status_code == 200
    assert client.get("/api/products", params={"q": marker}).json()["items"][0]["id"] == first["id"]


def test_inventory_writes_require_csrf_origin_and_pagination_is_bounded(client):
    headers = admin_login(client)
    product = client.post("/api/admin/products", headers=headers, json=product_payload()).json()
    base = f"/api/admin/products/{product['id']}"
    for invalid in ({}, {"Origin": "http://testserver"}, {**headers, "Origin": "https://evil.example"}):
        assert client.patch(base, headers=invalid, json={"name": "不应修改"}).status_code == 403
        assert client.post(base + "/inventory-adjustments", headers=invalid, json={"delta": 1, "reason": "不应修改"}).status_code == 403
    for path in ("/api/admin/products", base + "/inventory-adjustments"):
        for params in ({"page": 0}, {"page_size": 101}, {"page_size": 0}):
            assert client.get(path, params=params).status_code == 422
    missing = f"/api/admin/products/{uuid4()}"
    assert client.get(missing).status_code == 404
    assert client.patch(missing, headers=headers, json={"name": "不存在"}).status_code == 404
    assert client.get(missing + "/inventory-adjustments").status_code == 404
    assert client.post(missing + "/inventory-adjustments", headers=headers, json={"delta": 1, "reason": "不存在"}).status_code == 404


@pytest.mark.parametrize("changes", [
    {"delta": 0}, {"before_stock": -1}, {"after_stock": -1},
    {"after_stock": 2}, {"reason": "   "},
    {"product_id": str(uuid4())}, {"admin_id": str(uuid4())},
])
def test_postgresql_rejects_invalid_inventory_audit_rows(client, changes):
    headers = admin_login(client)
    product = client.post("/api/admin/products", headers=headers, json=product_payload()).json()
    values = {"id": str(uuid4()), "product_id": product["id"], "admin_id": client.get("/api/auth/me").json()["id"],
              "delta": 1, "before_stock": 0, "after_stock": 1, "reason": "入库", **changes}
    with client.app.state.session_factory() as session:
        with pytest.raises(IntegrityError):
            session.execute(text("""INSERT INTO inventory_adjustments
                (id, product_id, admin_id, delta, before_stock, after_stock, reason)
                VALUES (:id, :product_id, :admin_id, :delta, :before_stock, :after_stock, :reason)"""), values)
            session.commit()
        session.rollback()
