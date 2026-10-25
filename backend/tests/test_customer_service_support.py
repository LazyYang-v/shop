"""Exercise real session, orchestration, handoff and human review HTTP seams."""

from datetime import timedelta
import os
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from shop_api.customer_service_support import SupportCase, SupportContext, SupportPreference
from shop_api.identity import now_utc
from shop_api.orders import Order
from test_catalog_api import register_and_login_buyer
from test_customer_service_consultations import message_payload, page
from test_customer_service_orders import clear_testserver_rate, make_order


@pytest.fixture
def integrated(client):
    client.app.state.customer_service_mode = "integrated"
    client.app.state.customer_service_enabled = True
    register_and_login_buyer(client, f"checkout-support-{uuid4().hex}@example.com")
    client.headers.update({"Origin": "http://testserver", "X-CSRF-Token": client.get("/api/auth/csrf").json()["csrf_token"]})
    clear_testserver_rate(client)
    yield client
    clear_testserver_rate(client)


def send(client, created, text=None, **extra):
    payload = message_payload(created, **extra)
    if text is None:
        payload.pop("text", None)
    else:
        payload["text"] = text
    response = client.post("/api/customer-service/messages", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def admin_client(client):
    result = TestClient(client.app)
    token = result.get("/api/auth/csrf").json()["csrf_token"]
    login = result.post("/api/auth/login", headers={"Origin": "http://testserver", "X-CSRF-Token": token},
                        json={"email": "admin@example.com", "password": os.environ["SHOP_TEST_ADMIN_PASSWORD"]})
    assert login.status_code == 200, login.text
    result.headers.update({"Origin": "http://testserver", "X-CSRF-Token": result.get("/api/auth/csrf").json()["csrf_token"]})
    return result


def create_request(client, created, kind, **extra):
    if "selected_order_id" not in extra:
        from shop_api.customer_service_consultations import ConsultationPage
        with client.app.state.session_factory() as db:
            selected = db.get(ConsultationPage, UUID(created["page_instance_id"])).selected_order_id
            extra["selected_order_id"] = str(selected) if selected else None
    return client.post("/api/customer-service/requests", json={
        "page_instance_id": created["page_instance_id"], "consultation_id": created["consultation_id"],
        "client_request_id": str(uuid4()), "kind": kind, "concern": "请核实并帮助处理这笔订单", "consent": True, **extra})


def test_explicit_handoff_creates_one_case_without_raw_history_then_shares_by_consent(integrated):
    client = integrated
    created = page(client)
    send(client, created, "请问春日轻盈针织开衫的价格和库存？")
    data = send(client, created, "我要人工客服，联系电话13800138000，密码 private-secret")
    case = next(card["case"] for card in data["cards"] if card["type"] == "support_case")
    assert case["status"] == "open" and case["assigned"] is False
    assert case["summary"]["history"] == []
    assert "13800138000" not in str(case) and "private-secret" not in str(case)
    assert "退款成功" not in data["reply"]
    again = send(client, created, "转人工")
    assert next(card["case"]["id"] for card in again["cards"] if card["type"] == "support_case") == case["id"]
    shared = client.post(f"/api/customer-service/cases/{case['id']}/share-context", json={
        "consultation_id": created["consultation_id"], "consent": True})
    assert shared.status_code == 200, shared.text
    assert shared.json()["case"]["summary"]["history_shared"] is True
    assert shared.json()["case"]["summary"]["history"]


def test_two_consecutive_corrections_trigger_handoff_and_low_confidence_is_not_product(integrated):
    client = integrated
    created = page(client)
    send(client, created, "查看商城在售商品")
    first = send(client, created, "答错了")
    assert not any(card["type"] == "support_case" for card in first["cards"])
    second = send(client, created, "还是答非所问")
    assert any(card["type"] == "support_case" for card in second["cards"])
    other = page(client)
    unknown = send(client, other, "zxq938 zz9")
    assert not any(card["type"] == "product" for card in unknown["cards"])
    assert any(card["type"] == "handoff_preview" for card in unknown["cards"])


def test_request_needs_explicit_selection_and_admin_review_does_not_refund(integrated):
    client = integrated
    order_id = make_order(client, status="pending_shipment")
    created = page(client)
    data = send(client, created, "我要申请退款")
    assert any(card["type"] == "order" for card in data["cards"])
    assert create_request(client, created, "refund").status_code == 409
    data = send(client, created, selected_order_id=order_id)
    assert any(card["type"] == "service_request" and card["kind"] == "refund" for card in data["cards"])
    result = create_request(client, created, "refund")
    assert result.status_code == 201, result.text
    case = result.json()["case"]
    assert client.patch(f"/api/admin/customer-service/cases/{case['id']}", json={
        "status": "resolved", "reply": "不能由买家审核", "expected_updated_at": case["updated_at"]}).status_code == 403
    admin = admin_client(client)
    reviewed = admin.patch(f"/api/admin/customer-service/cases/{case['id']}", json={
        "status": "in_progress", "reply": "已经接手，正在核实申请", "expected_updated_at": case["updated_at"]})
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["case"]["assigned"] is True
    assert admin.patch(f"/api/admin/customer-service/cases/{case['id']}", json={
        "status": "resolved", "reply": "旧版本不得覆盖", "expected_updated_at": case["updated_at"]}).status_code == 409
    with client.app.state.session_factory() as db:
        assert db.get(Order, UUID(order_id)).status == "pending_shipment"
    notifications = client.get("/api/customer-service/notifications").json()["items"]
    assert any("新回复" in item["text"] for item in notifications)


def test_address_approval_rechecks_snapshot_and_order_state(integrated):
    client = integrated
    order_id = make_order(client, status="pending_shipment")
    address = client.post("/api/addresses", json={"recipient_name": "买家", "phone": "13800138000",
        "province": "浙江省", "city": "杭州市", "district": "滨江区", "detail": "测试街道 2 号"}).json()
    created = page(client)
    send(client, created, selected_order_id=order_id)
    case_response = create_request(client, created, "address_change", address_id=address["id"])
    assert case_response.status_code == 201, case_response.text
    case = case_response.json()["case"]
    admin = admin_client(client)
    client.patch("/api/addresses/" + address["id"], json={"detail": "另一个地址"})
    denied = admin.patch(f"/api/admin/customer-service/cases/{case['id']}", json={
        "status": "resolved", "reply": "审核地址", "expected_updated_at": case["updated_at"], "apply_address": True})
    assert denied.status_code == 409, denied.text
    client.patch("/api/addresses/" + address["id"], json={"detail": "测试街道 2 号"})
    applied = admin.patch(f"/api/admin/customer-service/cases/{case['id']}", json={
        "status": "resolved", "reply": "已核对申请并更新待发货订单地址", "expected_updated_at": case["updated_at"], "apply_address": True})
    assert applied.status_code == 200, applied.text
    order = client.get("/api/orders/" + order_id).json()
    assert order["address"]["detail"] == "测试街道 2 号"
    assert applied.json()["case"]["summary"]["executed_actions"][0]["action"] == "address_change"


def test_preferences_can_be_deleted_and_context_is_not_shared_between_buyers(integrated):
    client = integrated
    assert client.put("/api/customer-service/preferences", json={"consent": True,
        "categories": ["女装"], "occasion": "通勤", "budget_max": "200"}).status_code == 200
    assert client.get("/api/customer-service/preferences").json()["data"]["categories"] == ["女装"]
    assert client.delete("/api/customer-service/preferences").status_code == 204
    assert client.get("/api/customer-service/preferences").json()["data"] == {}
    created = page(client)
    send(client, created, "转人工")
    case_id = client.get("/api/customer-service/cases").json()["items"][0]["id"]
    other = TestClient(client.app)
    register_and_login_buyer(other, f"checkout-support-other-{uuid4().hex}@example.com")
    other.headers.update({"Origin": "http://testserver", "X-CSRF-Token": other.get("/api/auth/csrf").json()["csrf_token"]})
    assert other.get("/api/customer-service/history", params={"consultation_id": created["consultation_id"]}).status_code == 403
    assert other.post(f"/api/customer-service/cases/{case_id}/replies", json={"text": "越权"}).status_code == 403
    assert other.get("/api/customer-service/cases").json()["items"] == []


def test_metrics_count_feedback_and_never_treat_an_answer_as_resolved(integrated):
    client = integrated
    created = page(client)
    send(client, created, "查询我的订单")
    admin = admin_client(client)
    before = admin.get("/api/admin/customer-service/metrics").json()
    assert before["tool_success_rate"]["denominator"] >= 1
    first = client.post("/api/customer-service/feedback", json={"consultation_id": created["consultation_id"], "rating": 2, "resolved": False})
    assert first.status_code == 200, first.text
    second = client.post("/api/customer-service/feedback", json={"consultation_id": created["consultation_id"], "rating": 5, "resolved": True})
    assert second.status_code == 200
    after = admin.get("/api/admin/customer-service/metrics").json()
    assert after["resolution_rate"]["denominator"] == before["resolution_rate"]["denominator"] + 1
    assert after["resolution_rate"]["numerator"] == before["resolution_rate"]["numerator"] + 1


def test_published_knowledge_answers_with_source_and_version(integrated):
    client = integrated
    admin = admin_client(client)
    topic = f"shipping-{uuid4().hex}"
    body = {"kind": "policy", "topic": topic, "title": "测试运费规则", "body": "这是测试商城运费的有效条款。",
            "source": "测试管理员发布", "keywords": ["测试运费"], "valid_from": (now_utc() - timedelta(minutes=1)).isoformat(),
            "state": "published"}
    response = admin.post("/api/admin/customer-service/knowledge", json=body)
    assert response.status_code == 201, response.text
    assert admin.post("/api/admin/customer-service/knowledge", json=body).status_code == 409
    created = page(client)
    data = send(client, created, "测试运费规则")
    assert any(citation["id"] == response.json()["id"] for citation in data["citations"])
    assert "这是测试商城运费的有效条款" in data["reply"]
    assert admin.post(f"/api/admin/customer-service/knowledge/{response.json()['id']}/retire", json={}).status_code == 200
    data = send(client, created, "测试运费规则")
    assert not data["citations"]


def publish(client, *, kind="product", product_id=None, attributes=None, title="客服场景依据", keywords=None):
    response = admin_client(client).post("/api/admin/customer-service/knowledge", json={
        "kind": kind, "topic": f"scenario-{uuid4().hex}", "title": title, "body": "客服场景中已核验的商品资料或流程说明。",
        "source": "合成场景资料", "keywords": keywords or [], "attributes": attributes or {},
        "product_id": product_id, "state": "published", "valid_from": (now_utc() - timedelta(minutes=1)).isoformat()})
    assert response.status_code == 201, response.text
    return response.json()


def test_faq_hints_list_only_current_published_entries(integrated):
    client = integrated
    # Titles carry a per-run suffix: knowledge rows persist across suite runs,
    # and stale rows from older runs must never satisfy these assertions.
    suffix = uuid4().hex[:8]
    published_title = f"已发布的常见问题{suffix}"
    publish(client, kind="faq", title=published_title, keywords=["已发布"])
    admin = admin_client(client)
    drafts = [
        {"kind": "faq", "topic": f"draft-{uuid4().hex}", "title": f"草稿不展示{suffix}", "body": "草稿内容。",
         "source": "合成场景资料", "state": "draft", "valid_from": (now_utc() - timedelta(minutes=1)).isoformat()},
        {"kind": "faq", "topic": f"future-{uuid4().hex}", "title": f"未生效不展示{suffix}", "body": "未来内容。",
         "source": "合成场景资料", "state": "published", "valid_from": (now_utc() + timedelta(minutes=5)).isoformat()},
    ]
    for payload in drafts:
        assert admin.post("/api/admin/customer-service/knowledge", json=payload).status_code == 201
    hints = client.get("/api/customer-service/faq-hints").json()["items"]
    titles = [item["title"] for item in hints]
    assert published_title in titles
    assert f"草稿不展示{suffix}" not in titles and f"未生效不展示{suffix}" not in titles
    assert len(hints) <= 5 and all(item["title"] for item in hints)
    anonymous = TestClient(client.app)
    assert anonymous.get("/api/customer-service/faq-hints").status_code == 200


def test_unknown_question_uses_published_faq_before_low_confidence_handoff(integrated):
    client = integrated
    publish(client, kind="faq", title="如何联系营业部", keywords=["营业部"])
    data = send(client, page(client), "营业部联系方式")
    assert data["decision"]["task"] == "faq"
    assert data["citations"] and not any(card["type"] == "support_case" for card in data["cards"])


def test_size_follows_selection_then_collects_measurements_across_turns(integrated):
    client = integrated
    from shop_api.catalog import Product
    with client.app.state.session_factory() as db:
        product = db.scalar(select(Product).where(Product.id == UUID("00000000-0000-0000-0000-000000000001")))
        product_id = str(product.id)
    publish(client, product_id=product_id, attributes={"size_chart": {
        "M": {"height_cm": [160, 170], "weight_kg": [50, 60]}}})
    created = page(client)
    send(client, created, "查看商品：" + product_id)
    first = send(client, created, "尺码怎么选，身高168厘米")
    assert first["decision"]["task"] == "size"
    assert any("体重" in card["advice"]["needs"][0] for card in first["cards"] if card["type"] == "size_advice")
    second = send(client, created, "110斤")
    assert second["decision"]["task"] == "size"
    assert any("匹配 M" in item for card in second["cards"] if card["type"] == "size_advice"
               for item in card["advice"]["recommendations"])
    assert client.get("/api/customer-service/preferences").json()["data"] == {}
    send(client, created, "转人工")
    case = client.get("/api/customer-service/cases").json()["items"][0]
    assert any(fact["source"] == "public_product_knowledge" for fact in case["summary"]["verified_facts"])


def test_budget_followup_preserves_product_request_and_uses_controlled_tool(integrated):
    client = integrated
    created = page(client)
    send(client, created, "推荐针织开衫")
    data = send(client, created, "预算200元")
    assert data["decision"]["task"] == "recommendation"
    assert any(card["type"] == "product" for card in data["cards"])
    assert any(part["source"] == "recommend_products" for part in data["parts"])
    with client.app.state.session_factory() as db:
        state = db.get(SupportContext, UUID(created["consultation_id"])).data
        assert "针织开衫" in state["recommendation_query"] and "预算200元" in state["recommendation_query"]


def test_progress_dialogue_requires_selection_then_reads_same_request_without_new_case(integrated):
    client = integrated
    order_id = make_order(client, status="pending_shipment")
    created = page(client)
    send(client, created, selected_order_id=order_id)
    case = create_request(client, created, "refund").json()["case"]
    data = send(client, created, "退款到哪一步了")
    progress = next(card["progress"] for card in data["cards"] if card["type"] == "service_progress")
    assert progress["kind"] == "refund" and progress["items"][0]["case_id"] == case["id"]
    assert progress["items"][0]["execution_status"] == "not_connected"
    assert not any(card["type"] == "service_request" for card in data["cards"])
    assert len(client.get("/api/customer-service/cases").json()["items"]) == 1
    another = page(client)
    ask = send(client, another, "退款进度")
    assert any(card["type"] == "order" for card in ask["cards"])
    selected = send(client, another, selected_order_id=order_id)
    assert selected["decision"]["task"] == "refund_progress"
    assert any(card["type"] == "service_progress" for card in selected["cards"])
