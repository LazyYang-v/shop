import os
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

from datetime import datetime

import pytest

from shop_api.expiry import expire_orders
from shop_api.identity import User
from shop_api.orders import cancel_order
from test_order_payment_api import buyer, make_order


def test_cancel_closes_order_and_restores_stock_only_once(client):
    token = buyer(client, f"checkout-cancel-{uuid4().hex}@example.com")
    order_id = make_order(client, token)
    headers = {"X-CSRF-Token": token, "Origin": "http://testserver"}
    response = client.post(f"/api/orders/{order_id}/cancel", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "closed"
    assert response.json()["close_reason"] == "buyer_cancelled"
    assert response.json()["closed_at"] is not None
    assert client.post(f"/api/orders/{order_id}/cancel", headers=headers).status_code == 409
    assert client.post(f"/api/orders/{order_id}/pay", headers=headers).status_code == 409
    assert client.get("/api/products/00000000-0000-0000-0000-000000000001").json()["stock"] == 24
    assert client.get("/api/cart").json()["items"] == []


def test_caller_failure_rolls_back_cancellation_and_stock_restoration(client):
    token = buyer(client, f"checkout-cancel-rollback-{uuid4().hex}@example.com")
    order_id = make_order(client, token)
    user_id = UUID(client.get("/api/auth/me").json()["id"])

    with client.app.state.session_factory() as session:
        with pytest.raises(RuntimeError, match="caller failed after cancellation"):
            try:
                user = session.get(User, user_id)
                cancelled = cancel_order(session, user, UUID(order_id))
                assert cancelled.status == "closed"
                assert cancelled.close_reason == "buyer_cancelled"
                raise RuntimeError("caller failed after cancellation")
            except Exception:
                session.rollback()
                raise

    order = client.get(f"/api/orders/{order_id}").json()
    assert order["status"] == "pending_payment"
    assert order["close_reason"] is None
    assert order["closed_at"] is None
    assert client.get("/api/products/00000000-0000-0000-0000-000000000001").json()["stock"] == 23
    headers = {"X-CSRF-Token": token, "Origin": "http://testserver"}
    assert client.post(f"/api/orders/{order_id}/cancel", headers=headers).status_code == 200
    assert client.get("/api/products/00000000-0000-0000-0000-000000000001").json()["stock"] == 24


def test_expired_order_cannot_be_cancelled_before_expiry_scan(client, monkeypatch):
    token = buyer(client, f"checkout-cancel-expired-{uuid4().hex}@example.com")
    order_id = make_order(client, token)
    deadline = datetime.fromisoformat(client.get(f"/api/orders/{order_id}").json()["expires_at"])
    monkeypatch.setattr(client.app.state, "clock", lambda: deadline)

    response = client.post(
        f"/api/orders/{order_id}/cancel",
        headers={"X-CSRF-Token": token, "Origin": "http://testserver"},
    )

    assert response.status_code == 409
    order = client.get(f"/api/orders/{order_id}").json()
    assert order["status"] == "pending_payment"
    assert order["close_reason"] is None
    assert order["closed_at"] is None
    assert client.get("/api/products/00000000-0000-0000-0000-000000000001").json()["stock"] == 23
    assert expire_orders(client.app.state.session_factory, deadline) == 1
    order = client.get(f"/api/orders/{order_id}").json()
    assert order["status"] == "closed"
    assert order["close_reason"] == "payment_timeout"
    assert client.get("/api/products/00000000-0000-0000-0000-000000000001").json()["stock"] == 24


def admin_login(client):
    admin = client.__class__(client.app)
    token = admin.get("/api/auth/csrf").json()["csrf_token"]
    response = admin.post("/api/auth/login", headers={"X-CSRF-Token": token, "Origin": "http://testserver"}, json={"email": "admin@example.com", "password": os.environ["SHOP_TEST_ADMIN_PASSWORD"]})
    assert response.status_code == 200
    return admin, {"X-CSRF-Token": response.headers["X-CSRF-Token"], "Origin": "http://testserver"}


def test_buyer_can_list_only_own_orders_and_filter_by_status(client):
    first_token = buyer(client, f"checkout-list-first-{uuid4().hex}@example.com")
    first_id = make_order(client, first_token)
    client.post("/api/auth/logout", headers={"X-CSRF-Token": first_token, "Origin": "http://testserver"})
    token = buyer(client, f"checkout-list-second-{uuid4().hex}@example.com")
    second_id = make_order(client, token)
    response = client.get("/api/orders?page_size=1")
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert [item["id"] for item in response.json()["items"]] == [second_id]
    assert response.json()["items"][0]["created_at"]
    assert client.get("/api/orders?status=completed").json()["items"] == []
    assert client.get("/api/orders?status=invalid").status_code == 422
    assert client.get("/api/orders?page=0").status_code == 422
    assert client.get(f"/api/orders/{first_id}").status_code == 404


def test_paid_order_can_be_shipped_by_admin_and_received_by_owner(client):
    token = buyer(client, f"checkout-fulfillment-{uuid4().hex}@example.com")
    order_id = make_order(client, token)
    headers = {"X-CSRF-Token": token, "Origin": "http://testserver"}
    assert client.post(f"/api/orders/{order_id}/confirm-receipt", headers=headers).status_code == 409
    assert client.post(f"/api/orders/{order_id}/pay", headers=headers).status_code == 200
    admin, admin_headers = admin_login(client)
    payload = {"shipping_company": "顺丰", "tracking_number": "SF123456789"}
    assert client.post(f"/api/admin/orders/{order_id}/ship", headers=headers, json=payload).status_code == 403
    assert admin.post(f"/api/admin/orders/{order_id}/ship", json=payload).status_code == 403
    shipped = admin.post(f"/api/admin/orders/{order_id}/ship", headers=admin_headers, json=payload)
    assert shipped.status_code == 200
    assert shipped.json()["status"] == "pending_receipt"
    assert shipped.json()["tracking_number"] == "SF123456789"
    assert shipped.json()["shipped_at"]
    assert admin.get(f"/api/admin/orders/{order_id}").json()["id"] == order_id
    assert order_id in [o["id"] for o in admin.get("/api/admin/orders?status=pending_receipt").json()["items"]]
    assert admin.post(f"/api/admin/orders/{order_id}/ship", headers=admin_headers, json=payload).status_code == 409
    received = client.post(f"/api/orders/{order_id}/confirm-receipt", headers=headers)
    assert received.status_code == 200
    assert received.json()["status"] == "completed"
    assert received.json()["completed_at"]
    assert client.post(f"/api/orders/{order_id}/confirm-receipt", headers=headers).status_code == 409


def test_payment_and_cancellation_race_has_one_winner(client):
    token = buyer(client, f"checkout-race-payment-{uuid4().hex}@example.com")
    order_id = make_order(client, token)
    cookie = client.cookies.get("shop_session")
    headers = {"X-CSRF-Token": token, "Origin": "http://testserver"}
    barrier = threading.Barrier(2)

    def action(name):
        local = client.__class__(client.app, cookies={"shop_session": cookie})
        try:
            barrier.wait()
            return local.post(f"/api/orders/{order_id}/{name}", headers=headers)
        finally:
            local.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(action, ["pay", "cancel"]))
    assert sorted(response.status_code for response in responses) == [200, 409]
    status = client.get(f"/api/orders/{order_id}").json()["status"]
    assert status in {"pending_shipment", "closed"}
    stock = client.get("/api/products/00000000-0000-0000-0000-000000000001").json()["stock"]
    assert stock == (24 if status == "closed" else 23)


def test_buyer_cannot_cancel_or_receive_another_buyers_order(client):
    first = buyer(client, f"checkout-private-first-{uuid4().hex}@example.com")
    order_id = make_order(client, first)
    headers = {"X-CSRF-Token": first, "Origin": "http://testserver"}
    assert client.post(f"/api/orders/{order_id}/cancel").status_code == 403
    assert client.post("/api/auth/logout", headers=headers).status_code == 204
    second = buyer(client, f"checkout-private-second-{uuid4().hex}@example.com")
    headers["X-CSRF-Token"] = second
    assert client.post(f"/api/orders/{order_id}/cancel", headers=headers).status_code == 404
    assert client.post(f"/api/orders/{order_id}/confirm-receipt", headers=headers).status_code == 404
    assert client.get("/api/admin/orders").status_code == 403


def test_cancellation_can_restore_stock_after_admin_fills_inventory_to_limit(client):
    token = buyer(client, f"checkout-capacity-{uuid4().hex}@example.com")
    order_id = make_order(client, token)
    admin, admin_headers = admin_login(client)
    product_id = "00000000-0000-0000-0000-000000000001"
    adjusted = admin.post(f"/api/admin/products/{product_id}/inventory-adjustments", headers=admin_headers, json={"delta": 2147483624, "reason": "容量边界验证"})
    assert adjusted.status_code == 201
    headers = {"X-CSRF-Token": token, "Origin": "http://testserver"}
    closed = client.post(f"/api/orders/{order_id}/cancel", headers=headers)
    assert closed.status_code == 200
    assert client.get(f"/api/products/{product_id}").json()["stock"] == 2147483648
    restored = admin.post(f"/api/admin/products/{product_id}/inventory-adjustments", headers=admin_headers, json={"delta": -1, "reason": "减少可售库存"})
    assert restored.status_code == 201
    assert restored.json()["before_stock"] == 2147483648
    assert restored.json()["after_stock"] == 2147483647


def test_two_scanners_and_cancellation_restore_inventory_once(client, monkeypatch):
    token = buyer(client, f"checkout-expiry-race-{uuid4().hex}@example.com")
    order_id = make_order(client, token)
    current = datetime.fromisoformat(client.get(f"/api/orders/{order_id}").json()["expires_at"])
    monkeypatch.setattr(client.app.state, "clock", lambda: current)
    factory = client.app.state.session_factory
    barrier = threading.Barrier(3)
    cookie = client.cookies.get("shop_session")

    def scan():
        barrier.wait()
        return expire_orders(factory, current)

    def cancel():
        local = client.__class__(client.app, cookies={"shop_session": cookie})
        try:
            barrier.wait()
            return local.post(f"/api/orders/{order_id}/cancel", headers={"X-CSRF-Token": token, "Origin": "http://testserver"}).status_code
        finally:
            local.close()

    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(scan)
        second = pool.submit(scan)
        cancellation = pool.submit(cancel)
        counts = first.result(timeout=10) + second.result(timeout=10)
        cancelled = cancellation.result(timeout=10)
    assert cancelled == 409
    assert counts + expire_orders(factory, current) == 1
    order = client.get(f"/api/orders/{order_id}").json()
    assert order["status"] == "closed"
    assert order["close_reason"] == "payment_timeout"
    assert expire_orders(factory, current) == 0
    assert client.get("/api/products/00000000-0000-0000-0000-000000000001").json()["stock"] == 24




