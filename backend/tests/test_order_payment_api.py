from datetime import timedelta
from uuid import uuid4

from shop_api.identity import now_utc


def buyer(client, email: str) -> str:
    token = client.get("/api/auth/csrf").json()["csrf_token"]
    headers = {"X-CSRF-Token": token, "Origin": "http://testserver"}
    assert client.post("/api/auth/register", headers=headers, json={"email": email, "password": "portfolio-demo-pass-123"}).status_code == 201
    assert client.post("/api/auth/login", headers=headers, json={"email": email, "password": "portfolio-demo-pass-123"}).status_code == 200
    return client.get("/api/auth/csrf").json()["csrf_token"]


def make_order(client, token: str) -> str:
    headers = {"X-CSRF-Token": token, "Origin": "http://testserver"}
    address = client.post("/api/addresses", headers=headers, json={"recipient_name": "林女士", "phone": "13800138000", "province": "浙江省", "city": "杭州市", "district": "西湖区", "detail": "文三路 1 号"}).json()
    client.post("/api/cart/items", headers=headers, json={"product_id": "00000000-0000-0000-0000-000000000001", "quantity": 1})
    order = client.post("/api/orders", headers={**headers, "Idempotency-Key": str(uuid4())}, json={"address_id": address["id"]})
    assert order.status_code == 201
    return order.json()["id"]


def test_buyer_can_simulate_payment_once_and_reload_order(client):
    token = buyer(client, f"checkout-payment-{uuid4().hex}@example.com")
    order_id = make_order(client, token)
    headers = {"X-CSRF-Token": token, "Origin": "http://testserver"}

    paid = client.post(f"/api/orders/{order_id}/pay", headers=headers)
    assert paid.status_code == 200
    assert paid.json()["id"] == order_id
    assert paid.json()["status"] == "pending_shipment"
    assert paid.json()["paid_at"] is not None
    assert client.get(f"/api/orders/{order_id}").json()["status"] == "pending_shipment"
    repeated = client.post(f"/api/orders/{order_id}/pay", headers=headers)
    assert repeated.status_code == 409


def test_expired_order_cannot_be_paid(client):
    token = buyer(client, f"checkout-payment-expired-{uuid4().hex}@example.com")
    order_id = make_order(client, token)
    client.app.state.clock = lambda: now_utc() + timedelta(minutes=31)
    response = client.post(f"/api/orders/{order_id}/pay", headers={"X-CSRF-Token": token, "Origin": "http://testserver"})
    assert response.status_code == 409
    assert response.json()["detail"] == "订单已超时，暂不可支付"


def test_buyer_cannot_read_or_pay_another_buyers_order(client):
    first_token = buyer(client, f"checkout-payment-owner-{uuid4().hex}@example.com")
    order_id = make_order(client, first_token)
    client.post("/api/auth/logout", headers={"X-CSRF-Token": first_token, "Origin": "http://testserver"})

    second_token = buyer(client, f"checkout-payment-other-{uuid4().hex}@example.com")
    headers = {"X-CSRF-Token": second_token, "Origin": "http://testserver"}
    assert client.get(f"/api/orders/{order_id}").status_code == 404
    assert client.post(f"/api/orders/{order_id}/pay", headers=headers).status_code == 404


def test_payment_requires_csrf_and_same_origin(client):
    token = buyer(client, f"checkout-payment-csrf-{uuid4().hex}@example.com")
    order_id = make_order(client, token)
    assert client.post(f"/api/orders/{order_id}/pay").status_code == 403
    response = client.post(f"/api/orders/{order_id}/pay", headers={"X-CSRF-Token": token, "Origin": "https://attacker.example"})
    assert response.status_code == 403
