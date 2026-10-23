"""Buyer-scoped order reads through the customer-service message seam."""

import hashlib
import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text, update

from shop_api.customer_service import ProductFixture, SafeLogWriter
from shop_api.customer_service_consultations import ConsultationPage
from shop_api.identity import AuthSession
from shop_api.orders import Order
from test_catalog_api import register_and_login_buyer
from test_customer_service_consultations import assert_error, message_payload, page

PREFIX = "/api/customer-service"
PRODUCT_ID = "00000000-0000-0000-0000-000000000001"
ORDER_FIELDS = {"order_number", "created_at", "product_summary", "total", "status"}
DETAIL_FIELDS = {"order_number", "created_at", "status", "total", "product_summary", "items",
                 "expires_at", "close_reason", "shipping_company", "tracking_number", "shipped_at"}


def clear_testserver_rate(client):
    key = "ip:" + hashlib.sha256(b"testclient").hexdigest()
    with client.app.state.session_factory.begin() as db:
        db.execute(text("DELETE FROM customer_service_rate_limit_events WHERE bucket_key=:key"), {"key": key})
        db.execute(text("DELETE FROM customer_service_rate_limits WHERE bucket_key=:key"), {"key": key})


@pytest.fixture
def order_client(client, tmp_path):
    client.app.state.customer_service_enabled = True
    logs = tmp_path / "customer-service-logs"
    logs.mkdir(mode=0o700)
    client.app.state.customer_service_log_writer = SafeLogWriter(str(logs))
    buyer_id = register_and_login_buyer(client, f"checkout-cs-orders-{uuid4().hex}@example.com")
    client.app.state.customer_service_buyer_ids = {UUID(buyer_id)}
    client.app.state.customer_service_fixtures = {
        PRODUCT_ID: ProductFixture(PRODUCT_ID, "春日轻盈针织开衫", "女装", "129.00", 24, True)}
    client.headers.update({"Origin": "http://testserver",
                           "X-CSRF-Token": client.get("/api/auth/csrf").json()["csrf_token"]})
    client.customer_service_buyer_id = buyer_id
    clear_testserver_rate(client)
    yield client
    clear_testserver_rate(client)


def make_order(client, *, status="pending_payment"):
    address = client.post("/api/addresses", json={
        "recipient_name": "林女士", "phone": "13800138000", "province": "浙江省",
        "city": "杭州市", "district": "西湖区", "detail": "文三路 1 号"}).json()
    assert client.post("/api/cart/items", json={"product_id": PRODUCT_ID, "quantity": 1}).status_code == 201
    response = client.post("/api/orders", headers={"Idempotency-Key": str(uuid4())},
                           json={"address_id": address["id"]})
    assert response.status_code == 201, response.text
    order_id = response.json()["id"]
    if status != "pending_payment":
        with client.app.state.session_factory.begin() as db:
            db.execute(update(Order).where(Order.id == UUID(order_id)).values(status=status))
    return order_id


def make_other_buyer(client):
    other = client.__class__(client.app)
    buyer_id = register_and_login_buyer(other, f"checkout-cs-other-{uuid4().hex}@example.com")
    client.app.state.customer_service_buyer_ids.add(UUID(buyer_id))
    other.headers.update({"Origin": "http://testserver",
                          "X-CSRF-Token": other.get("/api/auth/csrf").json()["csrf_token"]})
    return other


def test_anonymous_order_questions_require_login_without_order_data(order_client):
    client = order_client
    order_id = make_order(client)
    client.cookies.clear()
    client.headers["X-CSRF-Token"] = client.get("/api/auth/csrf").json()["csrf_token"]
    created = page(client)
    for payload in [message_payload(created, text="查询我的订单"),
                    message_payload(created, text=None, selected_order_id=order_id)]:
        response = client.post(PREFIX + "/messages", json=payload)
        assert_error(response, 401, "authentication_required")
        assert "登录" in response.json()["message"]
        assert order_id not in response.text


def test_zero_one_and_multiple_orders_require_explicit_selection(order_client):
    client = order_client
    created = page(client)
    empty = client.post(PREFIX + "/messages", json=message_payload(created, text="查询我的订单"))
    assert empty.status_code == 200
    assert empty.json()["status"] == "empty"
    assert empty.json()["data"]["reply"] == "未找到可访问订单"
    assert empty.json()["data"]["cards"] == []

    first = make_order(client)
    one = client.post(PREFIX + "/messages", json=message_payload(created, text="我的订单"))
    assert one.status_code == 200
    assert one.json()["status"] == "ok"
    assert one.json()["data"]["reply"] == "请选择要查询的订单"
    assert [card["type"] for card in one.json()["data"]["cards"]] == ["order"]
    candidate = one.json()["data"]["cards"][0]["order"]
    assert set(candidate) == ORDER_FIELDS
    assert candidate == {"order_number": first, "created_at": candidate["created_at"],
                         "product_summary": "春日轻盈针织开衫 ×1", "total": "129.00",
                         "status": "pending_payment"}

    second = make_order(client)
    multiple = client.post(PREFIX + "/messages", json=message_payload(created, text="查询我的订单"))
    assert multiple.status_code == 200
    numbers = {card["order"]["order_number"] for card in multiple.json()["data"]["cards"]}
    assert numbers == {first, second}
    assert all(set(card["order"]) == ORDER_FIELDS for card in multiple.json()["data"]["cards"])

    selected = client.post(PREFIX + "/messages",
                           json=message_payload(created, text=None, selected_order_id=second))
    assert selected.status_code == 200, selected.text
    assert selected.json()["status"] == "ok"
    assert [card["type"] for card in selected.json()["data"]["cards"]] == ["order_detail"]
    assert selected.json()["data"]["cards"][0]["order"]["order_number"] == second


def test_order_number_filter_is_buyer_scoped_and_probe_limited(order_client):
    client = order_client
    own = make_order(client)
    other_client = make_other_buyer(client)
    foreign = make_order(other_client)
    other_client.close()
    created = page(client)

    for number in [own, foreign, str(uuid4())]:
        response = client.post(PREFIX + "/messages",
                               json=message_payload(created, text=f"订单号 {number}"))
        assert response.status_code == 200
        cards = response.json()["data"]["cards"]
        if number == own:
            assert [card["order"]["order_number"] for card in cards] == [own]
        else:
            assert response.json()["status"] == "empty"
            assert response.json()["data"]["reply"] == "未找到可访问订单"
            assert cards == []

    # Seven more probes consume the frozen ten-per-minute buyer budget.
    for _ in range(7):
        assert client.post(PREFIX + "/messages",
                           json=message_payload(created, text=f"订单号 {uuid4()}")).status_code == 200
    limited = client.post(PREFIX + "/messages", json=message_payload(created, text=f"订单号 {uuid4()}"))
    assert_error(limited, 429, "rate_limited")
    assert int(limited.headers["retry-after"]) >= 1


def test_order_detail_returns_only_trimmed_saved_facts(order_client):
    client = order_client
    order_id = make_order(client, status="pending_receipt")
    with client.app.state.session_factory.begin() as db:
        db.execute(update(Order).where(Order.id == UUID(order_id)).values(
            shipping_company="虚构速运", tracking_number="DEMO-TRACK-001",
            close_reason=None, shipped_at=client.app.state.clock(),
            phone="PRIVATE_PHONE_SENTINEL", detail="PRIVATE_ADDRESS_SENTINEL"))
    created = page(client)
    response = client.post(PREFIX + "/messages",
                           json=message_payload(created, text=None, selected_order_id=order_id))
    assert response.status_code == 200, response.text
    detail = response.json()["data"]["cards"][0]["order"]
    assert set(detail) == DETAIL_FIELDS
    assert detail["order_number"] == order_id
    assert detail["status"] == "pending_receipt"
    assert detail["total"] == "129.00"
    assert detail["items"] == [{"name": "春日轻盈针织开衫", "quantity": 1}]
    assert detail["product_summary"] == "春日轻盈针织开衫 ×1"
    assert detail["shipping_company"] == "虚构速运"
    assert detail["tracking_number"] == "DEMO-TRACK-001"
    assert detail["shipped_at"] is not None
    assert detail["expires_at"]
    assert detail["close_reason"] is None
    for forbidden in ["PRIVATE_PHONE_SENTINEL", "PRIVATE_ADDRESS_SENTINEL", "13800138000",
                      "文三路", "预计送达", "实时轨迹", "recipient_name", "phone"]:
        assert forbidden not in response.text


def test_cross_buyer_selection_and_nonexistent_orders_are_uniformly_unavailable(order_client):
    client = order_client
    other_client = make_other_buyer(client)
    foreign = make_order(other_client)
    other_client.close()
    created = page(client)
    for order_id in [foreign, str(uuid4())]:
        response = client.post(PREFIX + "/messages",
                               json=message_payload(created, text=None, selected_order_id=order_id))
        assert_error(response, 403, "resource_unavailable")
        assert response.json()["message"] == "未找到可访问订单"
    malformed = client.post(PREFIX + "/messages",
                            json=message_payload(created, text=None, selected_order_id="not-an-order"))
    assert_error(malformed, 422, "invalid_input")
    injected = client.post(PREFIX + "/messages",
                           json={**message_payload(created, text=None, selected_order_id=foreign),
                                 "user_id": client.customer_service_buyer_id})
    assert_error(injected, 422, "invalid_input")


def test_invalid_session_logout_and_account_switch_invalidate_old_authorization(order_client):
    client = order_client
    order_id = make_order(client)
    created = page(client)
    with client.app.state.session_factory() as db:
        session_id = db.get(ConsultationPage, UUID(created["page_instance_id"])).session_id
    revoked = {"X-CSRF-Token": client.get("/api/auth/csrf").json()["csrf_token"],
               "Origin": "http://testserver"}
    assert client.post("/api/auth/logout", headers=revoked).status_code == 204
    assert_error(client.post(PREFIX + "/messages", json=message_payload(created)), 401,
                 "authentication_required")

    other = make_other_buyer(client)
    switched = other.post(PREFIX + "/messages", json=message_payload(created))
    assert_error(switched, 403, "resource_unavailable")
    other_page = page(other)
    lost = other.post(PREFIX + "/messages",
                      json=message_payload(other_page, text=None, selected_order_id=order_id))
    assert_error(lost, 403, "resource_unavailable")
    assert lost.json()["message"] == "未找到可访问订单"
    with client.app.state.session_factory() as db:
        assert db.get(AuthSession, session_id).revoked_at is not None
    other.close()


def test_order_mcp_tool_schemas_dispatch_and_argument_validation(order_client):
    from shop_api.customer_service_product_mcp import CustomerServiceMCP, ProductMCPFailure
    from shop_api.customer_service_orders import OrderTools
    from shop_api.identity import User

    client = order_client
    order_id = make_order(client)
    with client.app.state.session_factory() as db:
        buyer = db.get(User, UUID(client.customer_service_buyer_id))
        mcp = CustomerServiceMCP(OrderTools(db, buyer, str(uuid4()), client.app.state.clock))
        mcp.initialize()
        tools = mcp.tools()
        assert [tool["name"] for tool in tools] == ["list_my_orders", "get_my_order"]
        for tool in tools:
            assert "user_id" not in json.dumps(tool)
            assert tool["inputSchema"]["additionalProperties"] is False
        listing = mcp.call("list_my_orders", {})
        assert [item["order_number"] for item in listing["data"]["items"]] == [order_id]
        detail = mcp.call("get_my_order", {"order_id": order_id})
        assert detail["data"]["order_number"] == order_id
        for bad in [{"user_id": str(uuid4())}, {"order_id": order_id, "buyer_id": str(uuid4())},
                    {"order_id": "not-a-uuid"}]:
            name = "get_my_order" if "order_id" in bad else "list_my_orders"
            with pytest.raises(ProductMCPFailure):
                mcp.call(name, bad)
        with pytest.raises(ProductMCPFailure):
            mcp.call("get_my_order", {"order_id": str(uuid4())})


def test_unsupported_actions_never_claim_completion(order_client):
    client = order_client
    created = page(client)
    for text in ["订单退款", "帮我退款", "给我发一张优惠券", "催发货", "转人工"]:
        response = client.post(PREFIX + "/messages", json=message_payload(created, text=text))
        assert response.status_code == 200
        assert response.json()["status"] != "ok"
        assert response.json()["data"]["cards"] == []
        for claim in ["已退款", "已办理", "已转人工", "已发券", "已催发货"]:
            assert claim not in response.text


def test_order_reads_write_only_allowlisted_safe_log_fields(order_client, tmp_path):
    client = order_client
    order_id = make_order(client)
    with client.app.state.session_factory.begin() as db:
        db.execute(update(Order).where(Order.id == UUID(order_id)).values(
            phone="PRIVATE_PHONE_SENTINEL", tracking_number="PRIVATE_TRACK_SENTINEL"))
    created = page(client)
    assert client.post(PREFIX + "/messages", json=message_payload(created, text="我的订单")).status_code == 200
    assert client.post(PREFIX + "/messages",
                       json=message_payload(created, text=None, selected_order_id=order_id)).status_code == 200
    records = [json.loads(line) for path in tmp_path.glob("customer-service-logs/*.jsonl")
               for line in path.read_text().splitlines()]
    assert {record["tool"] for record in records} == {"list_my_orders", "get_my_order"}
    assert all(set(record) == {"request_id", "tool", "error", "duration_ms", "count", "recorded_at"}
               for record in records)
    text = "".join(path.read_text() for path in tmp_path.glob("customer-service-logs/*.jsonl"))
    for forbidden in [order_id, "PRIVATE_PHONE_SENTINEL", "PRIVATE_TRACK_SENTINEL",
                      "春日轻盈针织开衫", client.customer_service_buyer_id]:
        assert forbidden not in text
