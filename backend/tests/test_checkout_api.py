import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import text


def register_and_login(client, email: str) -> str:
    token = client.get("/api/auth/csrf").json()["csrf_token"]
    headers = {"X-CSRF-Token": token, "Origin": "http://testserver"}
    assert client.post("/api/auth/register", headers=headers, json={"email": email, "password": "portfolio-demo-pass-123"}).status_code == 201
    assert client.post("/api/auth/login", headers=headers, json={"email": email, "password": "portfolio-demo-pass-123"}).status_code == 200
    return client.get("/api/auth/csrf").json()["csrf_token"]


@pytest.mark.usefixtures("reset_seed_product")
def test_checkout_creates_order_snapshot_decrements_stock_and_removes_selected_cart_items(client):
    token = register_and_login(client, f"checkout-{uuid4().hex}@example.com")
    headers = {"X-CSRF-Token": token, "Origin": "http://testserver", "Idempotency-Key": str(uuid4())}
    address = client.post("/api/addresses", headers=headers, json={"recipient_name": "林女士", "phone": "13800138000", "province": "浙江省", "city": "杭州市", "district": "西湖区", "detail": "文三路 1 号"}).json()
    product_id = "00000000-0000-0000-0000-000000000001"
    client.post("/api/cart/items", headers=headers, json={"product_id": product_id, "quantity": 2})
    order = client.post("/api/orders", headers=headers, json={"address_id": address["id"]})

    assert order.status_code == 201
    body = order.json()
    assert body["total"] == "258.00"
    assert body["items"][0]["name"] == "春日轻盈针织开衫"
    assert body["items"][0]["unit_price"] == "129.00"
    assert body["address"]["detail"] == "文三路 1 号"
    assert client.get("/api/cart").json() == {"items": [], "total": "0.00"}
    assert client.get(f"/api/products/{product_id}").json()["stock"] == 22
    replay = client.post("/api/orders", headers=headers, json={"address_id": address["id"]})
    assert replay.status_code == 201
    assert replay.json()["id"] == body["id"]
    conflicting_replay = client.post("/api/orders", headers=headers, json={"address_id": str(uuid4())})
    assert conflicting_replay.status_code == 409


@pytest.mark.usefixtures("reset_seed_product")
def test_checkout_rejects_address_deleted_before_order_creation(client):
    token = register_and_login(client, f"checkout-address-{uuid4().hex}@example.com")
    headers = {"X-CSRF-Token": token, "Origin": "http://testserver", "Idempotency-Key": str(uuid4())}
    address = client.post("/api/addresses", headers=headers, json={"recipient_name": "林女士", "phone": "13800138000", "province": "浙江省", "city": "杭州市", "district": "西湖区", "detail": "文三路 1 号"}).json()
    client.post("/api/cart/items", headers=headers, json={"product_id": "00000000-0000-0000-0000-000000000001", "quantity": 1})
    assert client.delete(f"/api/addresses/{address['id']}", headers=headers).status_code == 204
    response = client.post("/api/orders", headers=headers, json={"address_id": address["id"]})
    assert response.status_code == 404
    assert client.get("/api/cart").json()["items"]


@pytest.mark.usefixtures("reset_seed_product")
def test_checkout_insufficient_stock_rolls_back_everything(client):
    token = register_and_login(client, f"checkout-stock-{uuid4().hex}@example.com")
    headers = {"X-CSRF-Token": token, "Origin": "http://testserver", "Idempotency-Key": str(uuid4())}
    address = client.post("/api/addresses", headers=headers, json={"recipient_name": "林女士", "phone": "13800138000", "province": "浙江省", "city": "杭州市", "district": "西湖区", "detail": "文三路 1 号"}).json()
    product_id = "00000000-0000-0000-0000-000000000001"
    assert client.post("/api/cart/items", headers=headers, json={"product_id": product_id, "quantity": 3}).status_code == 201
    with client.app.state.session_factory() as session:
        session.execute(text("UPDATE products SET stock = 2 WHERE id = :id"), {"id": product_id})
        session.commit()
    failed = client.post("/api/orders", headers=headers, json={"address_id": address["id"]})

    assert failed.status_code == 409
    assert client.get("/api/cart").json()["items"][0]["quantity"] == 3
    assert client.get(f"/api/products/{product_id}").json()["stock"] == 2


@pytest.mark.usefixtures("reset_seed_product")
def test_multi_item_checkout_rolls_back_all_stock_when_one_item_is_short(client):
    first_id = "00000000-0000-0000-0000-000000000001"
    second_id = str(uuid4())
    with client.app.state.session_factory() as session:
        session.execute(text("INSERT INTO products (id,name,category,description,image_url,price,stock,is_listed) VALUES (:id,'第二件商品','测试','描述','/images/cardigan.svg',20,5,true)"), {"id": second_id})
        session.commit()
    token = register_and_login(client, f"checkout-multi-{uuid4().hex}@example.com")
    headers = {"X-CSRF-Token": token, "Origin": "http://testserver", "Idempotency-Key": str(uuid4())}
    address = client.post("/api/addresses", headers=headers, json={"recipient_name": "林女士", "phone": "13800138000", "province": "浙江省", "city": "杭州市", "district": "西湖区", "detail": "文三路 1 号"}).json()
    assert client.post("/api/cart/items", headers=headers, json={"product_id": first_id, "quantity": 2}).status_code == 201
    assert client.post("/api/cart/items", headers=headers, json={"product_id": second_id, "quantity": 6}).status_code == 409
    with client.app.state.session_factory() as session:
        session.execute(text("UPDATE products SET stock = 1 WHERE id = :id"), {"id": second_id})
        session.commit()
    assert client.post("/api/cart/items", headers=headers, json={"product_id": second_id, "quantity": 1}).status_code == 201
    with client.app.state.session_factory() as session:
        session.execute(text("UPDATE products SET stock = 0, is_listed = false WHERE id = :id"), {"id": second_id})
        session.commit()
    response = client.post("/api/orders", headers=headers, json={"address_id": address["id"]})
    assert response.status_code == 409
    assert client.get("/api/cart").json()["items"]
    with client.app.state.session_factory() as session:
        session.execute(text("UPDATE products SET is_listed = true WHERE id = :id"), {"id": second_id})
        session.commit()
    assert client.get(f"/api/products/{first_id}").json()["stock"] == 24
    with client.app.state.session_factory() as session:
        session.execute(text("DELETE FROM cart_items WHERE product_id = :id"), {"id": second_id})
        session.execute(text("DELETE FROM products WHERE id = :id"), {"id": second_id})
        session.commit()


@pytest.mark.usefixtures("reset_seed_product")
def test_two_buyers_cannot_oversell_inventory(client):
    product_id = "00000000-0000-0000-0000-000000000001"
    users = []
    for suffix in ("a", "b"):
        buyer_client = client.__class__(client.app)
        token = register_and_login(buyer_client, f"race-{suffix}-{uuid4().hex}@example.com")
        headers = {"X-CSRF-Token": token, "Origin": "http://testserver"}
        address = buyer_client.post("/api/addresses", headers=headers, json={"recipient_name": suffix, "phone": "13800138000", "province": "浙江省", "city": "杭州市", "district": "西湖区", "detail": suffix}).json()
        assert buyer_client.post("/api/cart/items", headers=headers, json={"product_id": product_id, "quantity": 15}).status_code == 201
        users.append((address["id"], headers["X-CSRF-Token"], buyer_client.cookies.get("shop_session")))

    with client.app.state.session_factory() as session:
        session.execute(text("UPDATE products SET stock = 20 WHERE id = :id"), {"id": product_id})
        session.commit()

    barrier = threading.Barrier(2)
    def checkout(user):
        address_id, token, cookie = user
        barrier.wait()
        local = client.__class__(client.app, cookies={"shop_session": cookie})
        return local.post("/api/orders", headers={"X-CSRF-Token": token, "Origin": "http://testserver", "Idempotency-Key": str(uuid4())}, json={"address_id": address_id})

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(checkout, users))
    assert sorted(response.status_code for response in responses) == [201, 409]
    assert client.get(f"/api/products/{product_id}").json()["stock"] == 5


def test_concurrent_replay_returns_the_same_order(client):
    token = register_and_login(client, f"checkout-replay-{uuid4().hex}@example.com")
    headers = {"X-CSRF-Token": token, "Origin": "http://testserver", "Idempotency-Key": str(uuid4())}
    address = client.post("/api/addresses", headers=headers, json={"recipient_name": "林女士", "phone": "13800138000", "province": "浙江省", "city": "杭州市", "district": "西湖区", "detail": "文三路 1 号"}).json()
    product_id = "00000000-0000-0000-0000-000000000001"
    assert client.post("/api/cart/items", headers=headers, json={"product_id": product_id, "quantity": 2}).status_code == 201
    cookie = client.cookies.get("shop_session")
    barrier = threading.Barrier(2)

    def checkout(_):
        with client.__class__(client.app, cookies={"shop_session": cookie}) as local:
            barrier.wait()
            return local.post("/api/orders", headers=headers, json={"address_id": address["id"]})

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(checkout, range(2)))
    assert [response.status_code for response in responses] == [201, 201]
    assert responses[0].json()["id"] == responses[1].json()["id"]
    assert client.get("/api/orders").json()["total"] == 1
    assert client.get(f"/api/products/{product_id}").json()["stock"] == 22
