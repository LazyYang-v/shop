from uuid import uuid4

from sqlalchemy import text


def register_and_login(client, email: str) -> str:
    token = client.get("/api/auth/csrf").json()["csrf_token"]
    assert client.post(
        "/api/auth/register",
        headers={"X-CSRF-Token": token, "Origin": "http://testserver"},
        json={"email": email, "password": "portfolio-demo-pass-123"},
    ).status_code == 201
    assert client.post(
        "/api/auth/login",
        headers={"X-CSRF-Token": token, "Origin": "http://testserver"},
        json={"email": email, "password": "portfolio-demo-pass-123"},
    ).status_code == 200
    return client.get("/api/auth/csrf").json()["csrf_token"]


def test_buyer_can_add_update_select_and_remove_persistent_cart_items(client):
    email = f"cart-{uuid4().hex}@example.com"
    token = register_and_login(client, email)
    headers = {"X-CSRF-Token": token, "Origin": "http://testserver"}
    product_id = "00000000-0000-0000-0000-000000000001"

    added = client.post("/api/cart/items", headers=headers, json={"product_id": product_id, "quantity": 2})
    assert added.status_code == 201
    assert added.json() == {
        "items": [{"product_id": product_id, "name": "春日轻盈针织开衫", "image_url": "/images/cardigan.svg", "unit_price": "129.00", "quantity": 2, "selected": True, "stock": 24}],
        "total": "258.00",
    }

    changed = client.patch(f"/api/cart/items/{product_id}", headers=headers, json={"quantity": 3, "selected": False})
    assert changed.status_code == 200
    assert changed.json()["items"][0]["quantity"] == 3
    assert changed.json()["items"][0]["selected"] is False

    persisted = client.get("/api/cart")
    assert persisted.status_code == 200
    assert persisted.json()["items"][0]["quantity"] == 3

    removed = client.delete(f"/api/cart/items/{product_id}", headers=headers)
    assert removed.status_code == 204
    assert client.get("/api/cart").json() == {"items": [], "total": "0.00"}


def test_cart_requires_login_and_rejects_unavailable_quantities(client):
    assert client.get("/api/cart").status_code == 401
    email = f"cart-{uuid4().hex}@example.com"
    token = register_and_login(client, email)
    headers = {"X-CSRF-Token": token, "Origin": "http://testserver"}

    assert client.post("/api/cart/items", headers=headers, json={"product_id": "00000000-0000-0000-0000-000000000001", "quantity": 0}).status_code == 422
    assert client.post("/api/cart/items", headers=headers, json={"product_id": "00000000-0000-0000-0000-000000000001", "quantity": 25}).status_code == 409


def test_buyer_cannot_update_cart_quantity_for_unlisted_product(client):
    token = register_and_login(client, f"cart-unlisted-{uuid4().hex}@example.com")
    headers = {"X-CSRF-Token": token, "Origin": "http://testserver"}
    product_id = "00000000-0000-0000-0000-000000000001"
    assert client.post("/api/cart/items", headers=headers, json={"product_id": product_id, "quantity": 1}).status_code == 201
    with client.app.state.session_factory() as session:
        session.execute(text("UPDATE products SET is_listed = false WHERE id = :id"), {"id": product_id})
        session.commit()
    response = client.patch(f"/api/cart/items/{product_id}", headers=headers, json={"quantity": 2})
    assert response.status_code == 409
