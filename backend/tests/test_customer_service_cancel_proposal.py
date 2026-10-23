"""Cancellation proposals: selection, one-time credentials and expiry.

Only isolated PostgreSQL fixtures; the frozen proposal slice never changes an
order or stock and never executes a cancellation.
"""

import hashlib
import json
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

