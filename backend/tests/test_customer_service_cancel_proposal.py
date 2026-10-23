"""Cancellation proposals, confirmations, and evidence over PostgreSQL."""

import hashlib
import json
import time
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text, update

from shop_api.customer_service import ProductFixture, SafeLogWriter
from shop_api.customer_service_cancel import (
    CANCEL_TRIGGER_TEXT,
    CancelOperation,
    expire_due_cancel_operations,
)
from shop_api.customer_service_consultations import ConsultationMessage, ConsultationPage
from shop_api.identity import User
from shop_api.orders import Order, OrderItem
from test_catalog_api import register_and_login_buyer
from test_customer_service_consultations import assert_error, message_payload, page

PREFIX = "/api/customer-service"
PRODUCT_ID = "00000000-0000-0000-0000-000000000001"


def clear_testserver_rate(client):
    key = "ip:" + hashlib.sha256(b"testclient").hexdigest()
    with client.app.state.session_factory.begin() as db:
        db.execute(text("DELETE FROM customer_service_rate_limit_events WHERE bucket_key=:key"), {"key": key})
        db.execute(text("DELETE FROM customer_service_rate_limits WHERE bucket_key=:key"), {"key": key})


@pytest.fixture
def cancel_client(client, tmp_path):
    client.app.state.customer_service_enabled = True
    logs = tmp_path / "customer-service-logs"
    logs.mkdir(mode=0o700)
    client.app.state.customer_service_log_writer = SafeLogWriter(str(logs))
    buyer_id = register_and_login_buyer(client, f"checkout-cs-cancel-{uuid4().hex}@example.com")
    client.app.state.customer_service_buyer_ids = {UUID(buyer_id)}
    client.app.state.customer_service_fixtures = {
        PRODUCT_ID: ProductFixture(PRODUCT_ID, "春日轻盈针织开衫", "女装", "129.00", 24, True)}
    client.headers.update({"Origin": "http://testserver",
                           "X-CSRF-Token": client.get("/api/auth/csrf").json()["csrf_token"]})
    client.customer_service_buyer_id = buyer_id
    with client.app.state.session_factory.begin() as db:
        db.execute(text("DELETE FROM customer_service_rate_limit_events"))
        db.execute(text("DELETE FROM customer_service_rate_limits"))
    yield client


def make_order(client, *, status="pending_payment", expires_in=None):
    address = client.post("/api/addresses", json={
        "recipient_name": "林女士", "phone": "13800138000", "province": "浙江省",
        "city": "杭州市", "district": "西湖区", "detail": "文三路 1 号"}).json()
    assert client.post("/api/cart/items", json={"product_id": PRODUCT_ID, "quantity": 1}).status_code == 201
    response = client.post("/api/orders", headers={"Idempotency-Key": str(uuid4())},
                           json={"address_id": address["id"]})
    assert response.status_code == 201, response.text
    order_id = response.json()["id"]
    changes = {}
    if status != "pending_payment":
        changes["status"] = status
    if expires_in is not None:
        changes["expires_at"] = client.app.state.clock() + expires_in
    if changes:
        with client.app.state.session_factory.begin() as db:
            db.execute(update(Order).where(Order.id == UUID(order_id)).values(**changes))
    return order_id


def make_other_buyer(client):
    other = client.__class__(client.app)
    buyer_id = register_and_login_buyer(other, f"checkout-cs-cancel-other-{uuid4().hex}@example.com")
    client.app.state.customer_service_buyer_ids.add(UUID(buyer_id))
    other.headers.update({"Origin": "http://testserver",
                          "X-CSRF-Token": other.get("/api/auth/csrf").json()["csrf_token"]})
    return other


def select_order(client, created, order_id):
    response = client.post(PREFIX + "/messages", json=message_payload(created, text=None, selected_order_id=order_id))
    assert response.status_code == 200, response.text
    return response


def propose(client, created, order_id=None, *, client_message_id=None):
    payload = message_payload(created, text=CANCEL_TRIGGER_TEXT)
    if order_id is not None:
        payload["selected_order_id"] = order_id
    if client_message_id is not None:
        payload["client_message_id"] = client_message_id
    return client.post(PREFIX + "/messages", json=payload)


def test_reconcile_pending_revokes_credential_and_late_confirmation_cannot_cancel(cancel_client):
    client = cancel_client
    order_id = make_order(client)
    created = page(client)
    card = propose(client, created, order_id).json()["confirmation_card"]
    payload = {"page_instance_id": created["page_instance_id"],
               "consultation_id": created["consultation_id"],
               "operation_id": card["operation_id"]}

    reconciled = client.post(PREFIX + "/cancel/reconcile", json=payload)
    repeated = client.post(PREFIX + "/cancel/reconcile", json=payload)
    late_confirmation = client.post(PREFIX + "/cancel/confirm", json={
        **payload, "confirmation_token": card["confirmation_token"]})

    assert reconciled.status_code == 200, reconciled.text
    assert reconciled.json()["status"] == "expired"
    assert reconciled.json()["data"]["operation_id"] == card["operation_id"]
    assert reconciled.json()["data"]["evidence"]["reason"] == "reconciled_unknown_result"
    assert repeated.status_code == 200
    assert repeated.json()["data"] == reconciled.json()["data"]
    assert late_confirmation.status_code == 409
    order = client.get(f"/api/orders/{order_id}")
    product = client.get(f"/api/products/{PRODUCT_ID}")
    assert order.status_code == 200
    assert order.json()["status"] == "pending_payment" and order.json()["close_reason"] is None
    assert product.status_code == 200 and product.json()["stock"] == 23


def test_reconcile_commit_failure_returns_unknown_and_retry_converges(cancel_client):
    from sqlalchemy import event
    from sqlalchemy.orm import Session as OrmSession

    client = cancel_client
    order_id = make_order(client)
    created = page(client)
    card = propose(client, created, order_id).json()["confirmation_card"]
    payload = {"page_instance_id": created["page_instance_id"],
               "consultation_id": created["consultation_id"], "operation_id": card["operation_id"]}
    fired = False

    def fail_reconcile_commit(session):
        nonlocal fired
        if any(isinstance(operation, CancelOperation) and operation.id == UUID(card["operation_id"])
               for operation in session.dirty):
            fired = True
            raise RuntimeError("injected ambiguous commit failure")

    event.listen(OrmSession, "before_commit", fail_reconcile_commit)
    try:
        unknown = client.post(PREFIX + "/cancel/reconcile", json=payload)
    finally:
        event.remove(OrmSession, "before_commit", fail_reconcile_commit)

    assert fired
    assert unknown.status_code == 503 and unknown.json()["code"] == "result_unknown"
    assert unknown.json()["status"] == "unavailable"
    repeated = client.post(PREFIX + "/cancel/reconcile", json=payload)
    late = client.post(PREFIX + "/cancel/confirm", json={
        **payload, "confirmation_token": card["confirmation_token"]})
    assert repeated.status_code == 200 and repeated.json()["status"] == "expired"
    assert repeated.json()["data"]["evidence"]["reason"] == "reconciled_unknown_result"
    assert late.status_code == 409
    order = client.get(f"/api/orders/{order_id}")
    product = client.get(f"/api/products/{PRODUCT_ID}")
    assert order.status_code == 200 and order.json()["status"] == "pending_payment"
    assert product.status_code == 200 and product.json()["stock"] == 23


def test_reconcile_returns_executed_evidence_after_confirmation_commit(cancel_client):
    client = cancel_client
    order_id = make_order(client)
    created = page(client)
    card = propose(client, created, order_id).json()["confirmation_card"]
    payload = {"page_instance_id": created["page_instance_id"],
               "consultation_id": created["consultation_id"],
               "operation_id": card["operation_id"]}
    confirmed = client.post(PREFIX + "/cancel/confirm", json={
        **payload, "confirmation_token": card["confirmation_token"]})

    reconciled = client.post(PREFIX + "/cancel/reconcile", json=payload)

    assert confirmed.status_code == 200 and confirmed.json()["status"] == "executed"
    assert reconciled.status_code == 200 and reconciled.json()["status"] == "executed"
    assert reconciled.json()["data"]["evidence"] == confirmed.json()["data"]["evidence"]
    assert reconciled.json()["data"]["evidence"]["close_reason"] == "buyer_cancelled"


def test_reconcile_returns_rejected_evidence(cancel_client):
    client = cancel_client
    order_id = make_order(client)
    created = page(client)
    card = propose(client, created, order_id).json()["confirmation_card"]
    canceled = client.post(f"/api/orders/{order_id}/cancel")
    payload = {"page_instance_id": created["page_instance_id"],
               "consultation_id": created["consultation_id"],
               "operation_id": card["operation_id"], "confirmation_token": card["confirmation_token"]}
    rejected = client.post(PREFIX + "/cancel/confirm", json=payload)
    reconciled = client.post(PREFIX + "/cancel/reconcile", json={key: value for key, value in payload.items()
                                                                    if key != "confirmation_token"})

    assert canceled.status_code == 200 and canceled.json()["close_reason"] == "buyer_cancelled"
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
    assert reconciled.status_code == 200 and reconciled.json()["status"] == "rejected"
    assert reconciled.json()["data"]["evidence"] == rejected.json()["data"]["evidence"]
    assert reconciled.json()["data"]["evidence"]["reason"] == "order_state_changed"
    order = client.get(f"/api/orders/{order_id}")
    assert order.status_code == 200 and order.json()["status"] == "closed"


def test_reconcile_expiry_evidence_survives_application_restart(cancel_client, tmp_path):
    from fastapi.testclient import TestClient
    from shop_api.app import create_app

    client = cancel_client
    order_id = make_order(client)
    created = page(client)
    card = propose(client, created, order_id).json()["confirmation_card"]
    payload = {"page_instance_id": created["page_instance_id"],
               "consultation_id": created["consultation_id"], "operation_id": card["operation_id"]}
    first = client.post(PREFIX + "/cancel/reconcile", json=payload)
    assert first.status_code == 200 and first.json()["status"] == "expired"

    restarted_app = create_app(database_url=client.app.state.session_factory.kw["bind"].url.render_as_string(hide_password=False))
    restarted_app.state.customer_service_enabled = True
    restarted_app.state.customer_service_buyer_ids = client.app.state.customer_service_buyer_ids
    restarted_app.state.customer_service_fixtures = client.app.state.customer_service_fixtures
    log_directory = tmp_path / "restart-logs"
    log_directory.mkdir(mode=0o700)
    restarted_app.state.customer_service_log_writer = SafeLogWriter(str(log_directory))
    with TestClient(restarted_app) as restarted:
        restarted.cookies.update(client.cookies)
        csrf = restarted.get("/api/auth/csrf").json()["csrf_token"]
        after_restart = restarted.post(PREFIX + "/cancel/reconcile", json=payload, headers={
            "Origin": "http://testserver", "X-CSRF-Token": csrf})

    assert after_restart.status_code == 200 and after_restart.json()["status"] == "expired"
    assert after_restart.json()["data"] == first.json()["data"]


def test_reconcile_returns_expired_evidence(cancel_client):
    client = cancel_client
    order_id = make_order(client)
    created = page(client)
    card = propose(client, created, order_id).json()["confirmation_card"]
    later = client.app.state.clock() + timedelta(minutes=3)
    client.app.state.clock = lambda: later
    expire_due_cancel_operations(client.app.state.session_factory, later)
    reconcile_payload = {"page_instance_id": created["page_instance_id"],
                         "consultation_id": created["consultation_id"], "operation_id": card["operation_id"]}
    reconciled = client.post(PREFIX + "/cancel/reconcile", json=reconcile_payload)
    late = client.post(PREFIX + "/cancel/confirm", json={
        **reconcile_payload, "confirmation_token": card["confirmation_token"]})

    assert reconciled.status_code == 200 and reconciled.json()["status"] == "expired"
    assert reconciled.json()["data"]["evidence"]["reason"] == "credential_expired"
    assert late.status_code == 409


def test_reconcile_is_protected_and_bound_to_original_buyer_page(cancel_client):
    client = cancel_client
    order_id = make_order(client)
    created = page(client)
    card = propose(client, created, order_id).json()["confirmation_card"]
    payload = {"page_instance_id": created["page_instance_id"],
               "consultation_id": created["consultation_id"], "operation_id": card["operation_id"]}
    csrf = client.headers.pop("X-CSRF-Token")
    try:
        assert client.post(PREFIX + "/cancel/reconcile", json=payload).status_code == 403
    finally:
        client.headers["X-CSRF-Token"] = csrf
    origin = client.headers["Origin"]
    client.headers["Origin"] = "http://attacker.test"
    try:
        assert client.post(PREFIX + "/cancel/reconcile", json=payload).status_code == 403
    finally:
        client.headers["Origin"] = origin
    payload["consultation_id"] = str(uuid4())
    assert client.post(PREFIX + "/cancel/reconcile", json=payload).status_code == 403
    other = make_other_buyer(client)
    other_page = page(other)
    foreign = other.post(PREFIX + "/cancel/reconcile", json={
        "page_instance_id": other_page["page_instance_id"],
        "consultation_id": other_page["consultation_id"], "operation_id": card["operation_id"]})
    assert foreign.status_code == 403


def test_reconcile_row_lock_contention_returns_processing(cancel_client):
    client = cancel_client
    order_id = make_order(client)
    created = page(client)
    card = propose(client, created, order_id).json()["confirmation_card"]
    from sqlalchemy import text as sql_text
    from threading import Event, Thread
    locked = Event()
    release = Event()

    def hold_operation_lock():
        with client.app.state.session_factory.begin() as db:
            db.execute(sql_text("SELECT id FROM customer_service_cancel_operations WHERE id=:id FOR UPDATE"),
                       {"id": card["operation_id"]})
            locked.set()
            release.wait(timeout=3)

    worker = Thread(target=hold_operation_lock)
    worker.start()
    assert locked.wait(timeout=2)
    try:
        started = time.monotonic()
        response = client.post(PREFIX + "/cancel/reconcile", json={
            "page_instance_id": created["page_instance_id"], "consultation_id": created["consultation_id"],
            "operation_id": card["operation_id"]})
        elapsed = time.monotonic() - started
    finally:
        release.set()
        worker.join(timeout=3)
    assert not worker.is_alive()
    assert response.status_code == 425
    assert response.json()["status"] == "processing"
    assert elapsed < 1.5
    completed = client.post(PREFIX + "/cancel/reconcile", json={
        "page_instance_id": created["page_instance_id"], "consultation_id": created["consultation_id"],
        "operation_id": card["operation_id"]})
    late = client.post(PREFIX + "/cancel/confirm", json={
        "page_instance_id": created["page_instance_id"],
        "consultation_id": created["consultation_id"], "operation_id": card["operation_id"],
        "confirmation_token": card["confirmation_token"]})
    assert completed.status_code == 200 and completed.json()["status"] == "expired"
    assert late.status_code == 409
    assert client.get(f"/api/orders/{order_id}").json()["status"] == "pending_payment"


def test_reconcile_waits_for_confirmation_and_returns_committed_evidence(cancel_client):
    from threading import Event, Thread

    client = cancel_client
    order_id = make_order(client)
    created = page(client)
    card = propose(client, created, order_id).json()["confirmation_card"]
    operation_id = UUID(card["operation_id"])
    payload = {"page_instance_id": created["page_instance_id"],
               "consultation_id": created["consultation_id"], "operation_id": card["operation_id"]}
    lock_ready = Event()
    allow_commit = Event()
    result = {}

    def pause_confirmation_before_commit(session):
        if session.get(CancelOperation, operation_id) is not None:
            lock_ready.set()
            assert allow_commit.wait(timeout=3)

    from sqlalchemy import event
    from sqlalchemy.orm import Session as OrmSession
    event.listen(OrmSession, "before_commit", pause_confirmation_before_commit)
    try:
        confirmer = Thread(target=lambda: result.setdefault("confirm", client.post(
            PREFIX + "/cancel/confirm", json={**payload, "confirmation_token": card["confirmation_token"]})))
        confirmer.start()
        assert lock_ready.wait(timeout=3)
        reconciler = Thread(target=lambda: result.setdefault("reconcile", client.post(
            PREFIX + "/cancel/reconcile", json=payload)))
        reconciler.start()
        time.sleep(0.15)
        allow_commit.set()
        confirmer.join(timeout=3)
        reconciler.join(timeout=3)
    finally:
        allow_commit.set()
        event.remove(OrmSession, "before_commit", pause_confirmation_before_commit)
    assert not confirmer.is_alive() and not reconciler.is_alive()
    assert result["confirm"].status_code == 200
    assert result["confirm"].json()["status"] == "executed"
    assert result["reconcile"].status_code == 200
    assert result["reconcile"].json()["status"] == "executed"
    assert result["reconcile"].json()["data"]["evidence"] == result["confirm"].json()["data"]["evidence"]
    order = client.get(f"/api/orders/{order_id}")
    product = client.get(f"/api/products/{PRODUCT_ID}")
    assert order.status_code == 200 and order.json()["close_reason"] == "buyer_cancelled"
    assert product.status_code == 200 and product.json()["stock"] == 24


def test_confirmation_retry_returns_evidence_without_double_stock_restore(cancel_client):
    client = cancel_client
    order_id = make_order(client)
    created = page(client)
    card = propose(client, created, order_id).json()["confirmation_card"]
    payload = {"page_instance_id": created["page_instance_id"],
               "consultation_id": created["consultation_id"],
               "operation_id": card["operation_id"],
               "confirmation_token": card["confirmation_token"]}

    first = client.post(PREFIX + "/cancel/confirm", json=payload)
    second = client.post(PREFIX + "/cancel/confirm", json=payload)
    invalid_replay = client.post(PREFIX + "/cancel/confirm", json={**payload, "confirmation_token": "z" * 43})

    assert first.status_code == 200 and first.json()["status"] == "executed"
    assert first.json()["data"]["evidence"]["close_reason"] == "buyer_cancelled"
    assert second.status_code == 200 and second.json()["status"] == "executed"
    assert second.json()["data"] == first.json()["data"]
    assert invalid_replay.status_code == 200 and invalid_replay.json()["data"] == first.json()["data"]
    with client.app.state.session_factory() as db:
        order = db.get(Order, UUID(order_id))
        operation = db.get(CancelOperation, UUID(card["operation_id"]))
        stock = db.scalar(text("SELECT stock FROM products WHERE id=:id"), {"id": PRODUCT_ID})
        assert order.status == "closed" and order.close_reason == "buyer_cancelled"
        assert operation.state == "executed" and operation.credential_hash is None
        assert stock == 24


def test_concurrent_confirmation_requests_cancel_once(cancel_client):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    client = cancel_client
    order_id = make_order(client)
    created = page(client)
    card = propose(client, created, order_id).json()["confirmation_card"]
    payload = {"page_instance_id": created["page_instance_id"],
               "consultation_id": created["consultation_id"],
               "operation_id": card["operation_id"],
               "confirmation_token": card["confirmation_token"]}
    second_client = client.__class__(client.app)
    second_client.cookies.update(client.cookies)
    second_client.headers.update(client.headers)
    barrier = Barrier(2)

    def confirm(target):
        barrier.wait()
        return target.post(PREFIX + "/cancel/confirm", json=payload)

    with ThreadPoolExecutor(max_workers=2) as workers:
        responses = list(workers.map(confirm, (client, second_client)))

    assert [response.status_code for response in responses] == [200, 200]
    assert all(response.json().get("status") == "executed" for response in responses)
    assert responses[0].json()["data"] == responses[1].json()["data"]
    with client.app.state.session_factory() as db:
        order = db.get(Order, UUID(order_id))
        operation = db.get(CancelOperation, UUID(card["operation_id"]))
        stock = db.scalar(text("SELECT stock FROM products WHERE id=:id"), {"id": PRODUCT_ID})
        assert order.status == "closed" and order.close_reason == "buyer_cancelled"
        assert operation.state == "executed"
        assert stock == 24


def test_invalid_confirmation_token_does_not_consume_or_change_order(cancel_client):
    client = cancel_client
    order_id = make_order(client)
    created = page(client)
    card = propose(client, created, order_id).json()["confirmation_card"]
    response = client.post(PREFIX + "/cancel/confirm", json={
        "page_instance_id": created["page_instance_id"], "consultation_id": created["consultation_id"],
        "operation_id": card["operation_id"], "confirmation_token": "x" * 43,
    })
    assert response.status_code == 409
    with client.app.state.session_factory() as db:
        operation = db.get(CancelOperation, UUID(card["operation_id"]))
        order = db.get(Order, UUID(order_id))
        assert operation.state == "pending" and operation.credential_hash is not None
        assert order.status == "pending_payment"


def test_rejection_consumes_token_with_evidence_when_order_state_changes(cancel_client):
    client = cancel_client
    order_id = make_order(client)
    created = page(client)
    card = propose(client, created, order_id).json()["confirmation_card"]
    with client.app.state.session_factory.begin() as db:
        db.execute(update(Order).where(Order.id == UUID(order_id)).values(status="pending_shipment"))
    response = client.post(PREFIX + "/cancel/confirm", json={
        "page_instance_id": created["page_instance_id"], "consultation_id": created["consultation_id"],
        "operation_id": card["operation_id"], "confirmation_token": card["confirmation_token"],
    })
    assert response.status_code == 200 and response.json()["status"] == "rejected"
    with client.app.state.session_factory() as db:
        operation = db.get(CancelOperation, UUID(card["operation_id"]))
        order = db.get(Order, UUID(order_id))
        assert operation.state == "rejected" and operation.credential_hash is None
        assert operation.evidence["reason"] == "order_state_changed"
        assert order.status == "pending_shipment"


def test_confirmation_rolls_back_operation_order_and_stock_on_domain_failure(cancel_client, monkeypatch):
    import shop_api.customer_service_cancel as cancellation

    client = cancel_client
    order_id = make_order(client)
    created = page(client)
    card = propose(client, created, order_id).json()["confirmation_card"]
    def fail_after_stock_write(*args, **kwargs):
        from sqlalchemy import update as sql_update
        args[0].execute(sql_update(Order).where(Order.id == UUID(order_id)).values(status="closed"))
        raise RuntimeError("injected order transition failure")
    monkeypatch.setattr(cancellation, "cancel_order", fail_after_stock_write)
    response = client.post(PREFIX + "/cancel/confirm", json={
        "page_instance_id": created["page_instance_id"], "consultation_id": created["consultation_id"],
        "operation_id": card["operation_id"], "confirmation_token": card["confirmation_token"],
    })
    assert response.status_code == 200
    assert response.json()["status"] == "rolled_back"
    assert response.json()["code"] == "transaction_rolled_back"
    with client.app.state.session_factory() as db:
        operation = db.get(CancelOperation, UUID(card["operation_id"]))
        order = db.get(Order, UUID(order_id))
        stock = db.scalar(text("SELECT stock FROM products WHERE id=:id"), {"id": PRODUCT_ID})
        assert operation.state == "pending" and operation.credential_hash is not None
        assert order.status == "pending_payment" and order.close_reason is None
        assert stock == 23


def test_confirmation_commit_failure_returns_unknown_result_and_rolls_back(cancel_client):
    from sqlalchemy import event
    from sqlalchemy.orm import Session as OrmSession

    client = cancel_client
    order_id = make_order(client)
    created = page(client)
    card = propose(client, created, order_id).json()["confirmation_card"]
    fired = False

    def fail_commit(session):
        nonlocal fired
        fired = True
        raise RuntimeError("injected commit failure")

    event.listen(OrmSession, "before_commit", fail_commit)
    client.app.state.customer_service_limiter.allow = lambda *args, **kwargs: (True, 0)
    try:
        response = client.post(PREFIX + "/cancel/confirm", json={
            "page_instance_id": created["page_instance_id"], "consultation_id": created["consultation_id"],
            "operation_id": card["operation_id"], "confirmation_token": card["confirmation_token"]})
    finally:
        event.remove(OrmSession, "before_commit", fail_commit)

    assert fired
    assert response.status_code == 503 and response.json()["code"] == "result_unknown"
    with client.app.state.session_factory() as db:
        operation = db.get(CancelOperation, UUID(card["operation_id"]))
        order = db.get(Order, UUID(order_id))
        stock = db.scalar(text("SELECT stock FROM products WHERE id=:id"), {"id": PRODUCT_ID})
        assert operation.state == "pending" and operation.credential_hash is not None
        assert order.status == "pending_payment" and order.close_reason is None
        assert stock == 23


def test_confirmation_rejects_a_replayed_token_without_affecting_another_order(cancel_client):
    client = cancel_client
    first_order_id = make_order(client)
    second_order_id = make_order(client)
    created = page(client)
    first_card = propose(client, created, first_order_id).json()["confirmation_card"]
    first_payload = {"page_instance_id": created["page_instance_id"],
                     "consultation_id": created["consultation_id"],
                     "operation_id": first_card["operation_id"],
                     "confirmation_token": first_card["confirmation_token"]}
    assert client.post(PREFIX + "/cancel/confirm", json=first_payload).json()["status"] == "executed"

    second_card = propose(client, created, second_order_id).json()["confirmation_card"]
    replay = client.post(PREFIX + "/cancel/confirm", json={**first_payload,
        "operation_id": second_card["operation_id"]})

    assert replay.status_code == 409
    with client.app.state.session_factory() as db:
        second_order = db.get(Order, UUID(second_order_id))
        second_operation = db.get(CancelOperation, UUID(second_card["operation_id"]))
        assert second_order.status == "pending_payment"
        assert second_operation.state == "pending" and second_operation.credential_hash is not None


def test_confirmation_rejects_missing_csrf_wrong_origin_and_wrong_binding(cancel_client):
    client = cancel_client
    order_id = make_order(client)
    created = page(client)
    card = propose(client, created, order_id).json()["confirmation_card"]
    payload = {"page_instance_id": created["page_instance_id"], "consultation_id": created["consultation_id"],
               "operation_id": card["operation_id"], "confirmation_token": card["confirmation_token"]}
    csrf = client.headers.pop("X-CSRF-Token")
    try:
        assert client.post(PREFIX + "/cancel/confirm", json=payload).status_code == 403
    finally:
        client.headers["X-CSRF-Token"] = csrf
    origin = client.headers["Origin"]
    client.headers["Origin"] = "http://attacker.test"
    try:
        assert client.post(PREFIX + "/cancel/confirm", json=payload).status_code == 403
    finally:
        client.headers["Origin"] = origin
    payload["consultation_id"] = str(uuid4())
    assert client.post(PREFIX + "/cancel/confirm", json=payload).status_code == 403
    with client.app.state.session_factory() as db:
        operation = db.get(CancelOperation, UUID(card["operation_id"]))
        assert operation.state == "pending" and operation.credential_hash is not None


def test_confirmation_rejects_a_different_buyers_session_and_page(cancel_client):
    client = cancel_client
    order_id = make_order(client)
    created = page(client)
    card = propose(client, created, order_id).json()["confirmation_card"]
    other_client = make_other_buyer(client)
    other_page = page(other_client)

    response = other_client.post(PREFIX + "/cancel/confirm", json={
        "page_instance_id": other_page["page_instance_id"],
        "consultation_id": other_page["consultation_id"],
        "operation_id": card["operation_id"],
        "confirmation_token": card["confirmation_token"],
    })

    assert response.status_code == 403 and response.json()["code"] == "resource_unavailable"
    with client.app.state.session_factory() as db:
        operation = db.get(CancelOperation, UUID(card["operation_id"]))
        order = db.get(Order, UUID(order_id))
        assert operation.state == "pending" and operation.credential_hash is not None
        assert order.status == "pending_payment"


def test_confirmation_rechecks_payment_deadline_before_order_cancellation(cancel_client):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    client = cancel_client
    now = client.app.state.clock()
    order_id = make_order(client, expires_in=timedelta(seconds=10))
    created = page(client)
    card = propose(client, created, order_id).json()["confirmation_card"]
    with client.app.state.session_factory.begin() as db:
        db.execute(update(CancelOperation).where(CancelOperation.id == UUID(card["operation_id"])).values(
            expires_at=now + timedelta(minutes=2)))
    calls = 0

    def clock():
        nonlocal calls
        calls += 1
        return now if calls == 1 else now + timedelta(seconds=11)

    client.app.state.clock = clock
    response = client.post(PREFIX + "/cancel/confirm", json={
        "page_instance_id": created["page_instance_id"], "consultation_id": created["consultation_id"],
        "operation_id": card["operation_id"], "confirmation_token": card["confirmation_token"]})

    assert response.status_code == 200 and response.json()["status"] == "rejected"
    with client.app.state.session_factory() as db:
        order = db.get(Order, UUID(order_id))
        operation = db.get(CancelOperation, UUID(card["operation_id"]))
        assert order.status == "pending_payment"
        assert operation.state == "rejected"
        assert operation.evidence["reason"] == "payment_deadline_passed"


def test_confirmation_expiry_is_persisted_and_does_not_change_the_order(cancel_client):
    client = cancel_client
    now = client.app.state.clock()
    client.app.state.clock = lambda: now
    order_id = make_order(client)
    created = page(client)
    card = propose(client, created, order_id).json()["confirmation_card"]
    client.app.state.clock = lambda: now + timedelta(seconds=121)

    response = client.post(PREFIX + "/cancel/confirm", json={
        "page_instance_id": created["page_instance_id"], "consultation_id": created["consultation_id"],
        "operation_id": card["operation_id"], "confirmation_token": card["confirmation_token"]})

    assert response.status_code == 200 and response.json()["status"] == "expired"
    with client.app.state.session_factory() as db:
        operation = db.get(CancelOperation, UUID(card["operation_id"]))
        order = db.get(Order, UUID(order_id))
        assert operation.state == "expired" and operation.credential_hash is None
        assert order.status == "pending_payment"


def test_confirmation_limiter_failure_returns_unavailable_without_cancelling(cancel_client):
    from shop_api.customer_service import CustomerServiceUnavailable

    client = cancel_client
    order_id = make_order(client)
    created = page(client)
    card = propose(client, created, order_id).json()["confirmation_card"]
    client.app.state.customer_service_limiter.allow = lambda *args, **kwargs: (_ for _ in ()).throw(
        CustomerServiceUnavailable())
    payload = {"page_instance_id": created["page_instance_id"],
               "consultation_id": created["consultation_id"],
               "operation_id": card["operation_id"],
               "confirmation_token": card["confirmation_token"]}

    response = client.post(PREFIX + "/cancel/confirm", json=payload)

    assert response.status_code == 503
    with client.app.state.session_factory() as db:
        order = db.get(Order, UUID(order_id))
        operation = db.get(CancelOperation, UUID(card["operation_id"]))
        assert order.status == "pending_payment"
        assert operation.state == "pending" and operation.credential_hash is not None


def test_confirmation_is_limited_to_ten_attempts_per_minute_per_buyer(cancel_client):
    client = cancel_client
    order_id = make_order(client)
    created = page(client)
    card = propose(client, created, order_id).json()["confirmation_card"]
    payload = {"page_instance_id": created["page_instance_id"],
               "consultation_id": created["consultation_id"],
               "operation_id": card["operation_id"],
               "confirmation_token": card["confirmation_token"]}

    responses = [client.post(PREFIX + "/cancel/confirm", json=payload) for _ in range(10)]
    limited = client.post(PREFIX + "/cancel/confirm", json=payload)

    assert responses[0].status_code == 200
    assert all(response.status_code == 200 for response in responses[1:])
    assert all(response.json()["data"] == responses[0].json()["data"] for response in responses[1:])
    assert limited.status_code == 429 and limited.json()["code"] == "rate_limited"
    assert int(limited.headers["retry-after"]) >= 1


def test_explicit_selection_and_fixed_text_issue_a_confirmation_card(cancel_client):
    client = cancel_client
    order_id = make_order(client)
    created = page(client)
    now = client.app.state.clock()
    client.app.state.clock = lambda: now

    select_order(client, created, order_id)
    response = propose(client, created, order_id)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "ok"
    assert result["data"]["cards"] == []
    card = result["confirmation_card"]
    assert set(card) == {"operation_id", "order_number", "status", "product_summary", "total",
                         "currency", "expires_at", "confirmation_token"}
    assert card["order_number"] == order_id
    assert card["status"] == "pending_payment"
    assert card["product_summary"] == "春日轻盈针织开衫 ×1"
    assert card["total"] == "129.00"
    assert card["currency"] == "CNY"
    assert len(card["confirmation_token"]) == 43
    assert card["expires_at"] == (now + timedelta(seconds=120)).isoformat()
    for consequence in ["恢复商品库存", "不可撤销", "购物车不会恢复"]:
        assert consequence in result["data"]["reply"]

    with client.app.state.session_factory() as db:
        order = db.get(Order, UUID(order_id))
        assert order.status == "pending_payment"
        assert order.close_reason is None
    with client.app.state.session_factory() as db:
        product_stock = db.scalar(text("SELECT stock FROM products WHERE id=:id"), {"id": PRODUCT_ID})
    assert product_stock == 23


def test_operation_is_bound_and_only_the_credential_hash_is_persisted(cancel_client):
    client = cancel_client
    order_id = make_order(client)
    created = page(client)
    response = propose(client, created, order_id)
    token = response.json()["confirmation_card"]["confirmation_token"]

    with client.app.state.session_factory() as db:
        operation = db.scalar(select(CancelOperation))
        page_record = db.get(ConsultationPage, UUID(created["page_instance_id"]))
        assert operation.buyer_id == UUID(client.customer_service_buyer_id)
        assert operation.session_id == page_record.session_id
        assert operation.consultation_id == UUID(created["consultation_id"])
        assert operation.page_id == page_record.id
        assert operation.order_id == UUID(order_id)
        assert operation.action == "cancel"
        assert operation.state == "pending"
        assert operation.credential_hash == hashlib.sha256(token.encode()).digest()
        assert operation.terminal_at is None
        assert token not in repr(operation.__dict__)
        raw = db.scalar(text("SELECT row_to_json(o)::text FROM customer_service_cancel_operations o"))
        assert token not in raw


def test_replay_returns_card_unavailable_without_reissuing_or_creating(cancel_client):
    client = cancel_client
    order_id = make_order(client)
    created = page(client)
    payload = message_payload(created, text=CANCEL_TRIGGER_TEXT, selected_order_id=order_id)
    first = client.post(PREFIX + "/messages", json=payload)
    assert first.status_code == 200, first.text
    token = first.json()["confirmation_card"]["confirmation_token"]
    message_id = UUID(payload["client_message_id"])

    with client.app.state.session_factory() as db:
        stored = db.get(ConsultationMessage, (UUID(created["consultation_id"]),
                                              UUID(created["page_instance_id"]), message_id))
        stored_text = json.dumps(stored.response, ensure_ascii=False)
        assert token not in stored_text
        assert stored.response["code"] == "card_unavailable"
        assert "confirmation_token" not in stored.response["confirmation_card"]
        operations = db.scalars(select(CancelOperation)).all()
        assert len(operations) == 1
        original_hash = operations[0].credential_hash

    replay = client.post(PREFIX + "/messages", json=payload)
    assert replay.status_code == 200, replay.text
    assert replay.json()["code"] == "card_unavailable"
    assert "confirmation_token" not in replay.json()["confirmation_card"]
    assert token not in replay.text
    with client.app.state.session_factory() as db:
        operations = db.scalars(select(CancelOperation)).all()
        assert len(operations) == 1
        assert operations[0].credential_hash == original_hash


def test_selection_is_required_and_foreign_or_unknown_orders_are_unavailable(cancel_client):
    client = cancel_client
    created = page(client)
    missing = propose(client, created)
    assert_error(missing, 409, "state_conflict")
    assert "订单" in missing.json()["message"]

    other_client = make_other_buyer(client)
    foreign = make_order(other_client)
    other_client.close()
    unavailable = propose(client, created, foreign)
    assert_error(unavailable, 403, "resource_unavailable")
    assert unavailable.json()["message"] == "未找到可访问订单"
    unknown = propose(client, created, str(uuid4()))
    assert_error(unknown, 403, "resource_unavailable")
    malformed = propose(client, created, "not-an-order")
    assert_error(malformed, 422, "invalid_input")
    with client.app.state.session_factory() as db:
        assert db.scalars(select(CancelOperation)).all() == []
        assert db.get(ConsultationPage, UUID(created["page_instance_id"])).selected_order_id is None


def test_non_pending_or_expired_orders_conflict_without_creating_an_operation(cancel_client):
    client = cancel_client
    now = client.app.state.clock()
    client.app.state.clock = lambda: now
    created = page(client)

    paid = make_order(client, status="pending_shipment")
    select_order(client, created, paid)
    assert_error(propose(client, created, paid), 409, "state_conflict")

    expired = make_order(client)
    with client.app.state.session_factory.begin() as db:
        db.execute(update(Order).where(Order.id == UUID(expired)).values(
            expires_at=now - timedelta(seconds=1)))
    select_order(client, created, expired)
    assert_error(propose(client, created, expired), 409, "state_conflict")
    with client.app.state.session_factory() as db:
        assert db.scalars(select(CancelOperation)).all() == []


def test_deadline_is_the_earlier_of_two_minutes_and_the_order_deadline(cancel_client):
    client = cancel_client
    now = client.app.state.clock()
    client.app.state.clock = lambda: now
    created = page(client)

    soon = make_order(client, expires_in=timedelta(seconds=60))
    soon_card = propose(client, created, soon).json()["confirmation_card"]
    assert soon_card["expires_at"] == (now + timedelta(seconds=60)).isoformat()

    later = make_order(client, expires_in=timedelta(minutes=30))
    select_order(client, created, later)
    later_card = propose(client, created, later).json()["confirmation_card"]
    assert later_card["expires_at"] == (now + timedelta(seconds=120)).isoformat()

    with client.app.state.session_factory() as db:
        pending = db.scalars(select(CancelOperation).where(CancelOperation.state == "pending")).all()
        assert len(pending) == 1
        assert pending[0].order_id == UUID(later)


def test_entry_and_periodic_expiry_only_move_pending_rows(cancel_client):
    client = cancel_client
    now = client.app.state.clock()
    client.app.state.clock = lambda: now
    order_id = make_order(client)
    created = page(client)
    first = propose(client, created, order_id)
    token = first.json()["confirmation_card"]["confirmation_token"]
    with client.app.state.session_factory() as db:
        operation_id = db.scalar(select(CancelOperation.id))

    later = now + timedelta(seconds=121)
    client.app.state.clock = lambda: later
    expire_due_cancel_operations(client.app.state.session_factory, later)
    with client.app.state.session_factory() as db:
        operation = db.get(CancelOperation, operation_id)
        assert operation.state == "expired"
        assert operation.credential_hash is None
        assert operation.terminal_at == later
    expire_due_cancel_operations(client.app.state.session_factory, later + timedelta(minutes=5))
    with client.app.state.session_factory() as db:
        operation = db.get(CancelOperation, operation_id)
        assert operation.state == "expired"
        assert operation.terminal_at == later

    fresh = later + timedelta(seconds=1)
    client.app.state.clock = lambda: fresh
    second = propose(client, created, order_id)
    assert second.status_code == 200, second.text
    with client.app.state.session_factory() as db:
        operations = db.scalars(select(CancelOperation).order_by(CancelOperation.issued_at)).all()
        assert [operation.state for operation in operations] == ["expired", "pending"]
        assert operations[0].terminal_at is not None
        assert token not in json.dumps([operation.__dict__ for operation in operations], default=str)


def test_proposal_rate_limit_is_five_per_minute_per_buyer(cancel_client):
    client = cancel_client
    now = client.app.state.clock()
    client.app.state.clock = lambda: now
    order_id = make_order(client)
    created = page(client)
    select_order(client, created, order_id)
    for _ in range(5):
        assert propose(client, created).status_code == 200
    limited = propose(client, created)
    assert_error(limited, 429, "rate_limited")
    assert int(limited.headers["retry-after"]) >= 1
    with client.app.state.session_factory() as db:
        assert len(db.scalars(select(CancelOperation)).all()) == 5
    client.app.state.clock = lambda: now + timedelta(seconds=60)
    assert propose(client, created).status_code == 200


def test_new_proposal_and_selection_change_invalidate_the_prior_card(cancel_client):
    client = cancel_client
    order_id = make_order(client)
    second_order = make_order(client)
    created = page(client)
    assert propose(client, created, order_id).status_code == 200
    assert propose(client, created, order_id).status_code == 200
    with client.app.state.session_factory() as db:
        states = db.scalars(select(CancelOperation.state).order_by(CancelOperation.issued_at)).all()
        assert states == ["expired", "pending"]

    select_order(client, created, second_order)
    with client.app.state.session_factory() as db:
        operations = db.scalars(select(CancelOperation).order_by(CancelOperation.issued_at)).all()
        assert [operation.state for operation in operations] == ["expired", "expired"]
        assert all(operation.credential_hash is None for operation in operations)
        assert db.get(ConsultationPage, UUID(created["page_instance_id"])).selected_order_id == UUID(second_order)


def test_handoff_and_page_cleanup_expire_pending_proposals(cancel_client):
    from shop_api.customer_service_consultations import cleanup_consultations

    client = cancel_client
    now = client.app.state.clock()
    client.app.state.clock = lambda: now
    order_id = make_order(client)
    first = page(client)
    assert propose(client, first, order_id).status_code == 200
    successor = page(client, handoff_token=first["handoff_token"])
    assert successor["consultation_id"] == first["consultation_id"]
    with client.app.state.session_factory() as db:
        operation = db.scalar(select(CancelOperation).where(CancelOperation.page_id == UUID(first["page_instance_id"])))
        assert operation.state == "expired"
        assert operation.credential_hash is None

    second_order = make_order(client)
    second = page(client)
    assert propose(client, second, second_order).status_code == 200
    cleanup_consultations(client.app.state.session_factory, now + timedelta(minutes=31))
    with client.app.state.session_factory() as db:
        operation = db.scalar(select(CancelOperation).where(CancelOperation.page_id == UUID(second["page_instance_id"])))
        assert operation.state == "expired"
        assert operation.credential_hash is None
        assert operation.terminal_at is not None
        assert db.scalar(select(CancelOperation).where(CancelOperation.page_id == UUID(first["page_instance_id"]))) is not None


def test_page_lru_eviction_expires_the_evicted_pages_proposal(cancel_client):
    client = cancel_client
    now = client.app.state.clock()
    client.app.state.clock = lambda: now
    order_id = make_order(client)
    doomed = page(client)
    assert propose(client, doomed, order_id).status_code == 200
    for index in range(10):
        client.app.state.clock = lambda index=index: now + timedelta(seconds=index + 1)
        page(client)
    with client.app.state.session_factory() as db:
        operation = db.scalar(select(CancelOperation))
        assert operation.state == "expired"
        assert operation.credential_hash is None


def test_handoff_renewal_does_not_extend_the_confirmation_deadline(cancel_client):
    client = cancel_client
    now = client.app.state.clock()
    client.app.state.clock = lambda: now
    order_id = make_order(client)
    created = page(client)
    card = propose(client, created, order_id).json()["confirmation_card"]
    with client.app.state.session_factory() as db:
        before = db.scalar(select(CancelOperation).where(CancelOperation.state == "pending"))
        original_expiry = before.expires_at
        original_hash = before.credential_hash
    renewed = client.post(PREFIX + "/pages/renew", json={
        "page_instance_id": created["page_instance_id"], "handoff_token": created["handoff_token"]})
    assert renewed.status_code == 200
    assert renewed.json()["data"]["handoff_expires_at"] != card["expires_at"]
    with client.app.state.session_factory() as db:
        after = db.scalar(select(CancelOperation).where(CancelOperation.state == "pending"))
        assert after.expires_at == original_expiry
        assert after.credential_hash == original_hash


def test_mcp_exposes_only_propose_cancel_and_rejects_extras_or_mismatches(cancel_client):
    from shop_api.customer_service_product_mcp import CustomerServiceMCP, ProductMCPFailure
    from shop_api.customer_service_cancel import CancellationTools

    client = cancel_client
    order_id = make_order(client)
    other_order = make_order(client)
    created = page(client)
    select_order(client, created, order_id)
    with client.app.state.session_factory() as db:
        buyer = db.get(User, UUID(client.customer_service_buyer_id))
        page_record = db.get(ConsultationPage, UUID(created["page_instance_id"]))
        tools = CancellationTools(db, buyer, page_record, str(uuid4()), client.app.state.clock)
        mcp = CustomerServiceMCP(tools)
        mcp.initialize()
        listed = mcp.tools()
        assert [tool["name"] for tool in listed] == ["propose_cancel"]
        assert listed[0]["inputSchema"]["additionalProperties"] is False
        assert "user_id" not in json.dumps(listed)
        with pytest.raises(ProductMCPFailure) as mismatch:
            mcp.call("propose_cancel", {"order_id": other_order})
        assert mismatch.value.code == "state_conflict"
        with pytest.raises(ProductMCPFailure) as extra:
            mcp.call("propose_cancel", {"order_id": order_id, "buyer_id": str(uuid4())})
        assert extra.value.code == "invalid_input"
        with pytest.raises(Exception):
            mcp.call("confirm", {})
        result = mcp.call("propose_cancel", {"order_id": order_id})
        token = tools.take_confirmation_token()
        assert token is not None and len(token) == 43
        assert set(result) == {"request_id", "queried_at", "status", "data"}
        assert result["status"] == "proposed"
        assert set(result["data"]) == {"operation_id", "status", "product_summary",
                                       "total", "currency", "expires_at"}
        assert order_id not in json.dumps(result)
        assert token not in json.dumps(result)
        db.commit()
    paths = {getattr(route, "path", "") for route in client.app.routes}
    assert "/api/customer-service/cancel/confirm" not in paths
    assert "/api/customer-service/cancel/reconcile" not in paths


def test_ordinary_chat_text_is_not_consent_and_proposal_logs_are_allowlisted(cancel_client, tmp_path):
    client = cancel_client
    order_id = make_order(client)
    created = page(client)
    select_order(client, created, order_id)
    ordinary = client.post(PREFIX + "/messages", json=message_payload(created, text="好的"))
    assert ordinary.status_code == 200
    assert "confirmation_card" not in ordinary.json()
    with client.app.state.session_factory() as db:
        assert db.scalars(select(CancelOperation)).all() == []

    response = propose(client, created, order_id)
    token = response.json()["confirmation_card"]["confirmation_token"]
    with client.app.state.session_factory() as db:
        operation_id = str(db.scalar(select(CancelOperation.id)))
    records = [json.loads(line) for path in tmp_path.glob("customer-service-logs/*.jsonl")
               for line in path.read_text().splitlines()]
    assert {"propose_cancel"} <= {record["tool"] for record in records}
    assert all(set(record) == {"request_id", "tool", "error", "duration_ms", "count", "recorded_at"}
               for record in records)
    text_log = "".join(path.read_text() for path in tmp_path.glob("customer-service-logs/*.jsonl"))
    for forbidden in [token, operation_id, order_id, "春日轻盈针织开衫", client.customer_service_buyer_id]:
        assert forbidden not in text_log

