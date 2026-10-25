"""Service progress keeps buyer review records separate from business execution.

These tests use the existing database fixtures and are intended for a separately
approved database test run. Merely compiling this file does not run the fixtures.
"""

from copy import deepcopy
from datetime import timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from shop_api.customer_service import CustomerServiceUnavailable
from shop_api.customer_service_consultations import Consultation, ConsultationPage
from shop_api.customer_service_product_mcp import CustomerServiceMCP, CustomerServiceMCPFailure
from shop_api.customer_service_progress import (
    MAX_PROGRESS_CASES, MAX_PROGRESS_REPLY, ServiceProgressTools, verify_service_progress_result,
)
from shop_api.customer_service_support import REQUEST_KINDS, SupportCase
from shop_api.identity import User
from shop_api.orders import Order
from test_catalog_api import register_and_login_buyer
from test_customer_service_consultations import page
from test_customer_service_orders import make_order
from test_customer_service_support import admin_client, create_request, integrated as integrated, send

PROGRESS_URL = "/api/customer-service/service-progress"


def selected_page(client, order_id):
    created = page(client)
    send(client, created, selected_order_id=order_id)
    return created


def read_progress(client, created, order_id, **params):
    return client.get(PROGRESS_URL, params={
        "page_instance_id": created["page_instance_id"], "consultation_id": created["consultation_id"],
        "order_id": order_id, **params,
    })


def add_case(client, order_id, *, kind="refund", status="open", buyer_id=None,
             expires_at=None, updated_at=None, summary=None, messages=None):
    now = client.app.state.clock()
    case_id = uuid4()
    with client.app.state.session_factory.begin() as db:
        order = db.get(Order, UUID(order_id))
        db.add(SupportCase(
            id=case_id, buyer_id=buyer_id or order.user_id, request_key=f"progress-test:{uuid4()}",
            kind=kind, status=status, priority="normal", order_id=order.id,
            summary=summary if summary is not None else {"executed_actions": []},
            details={"invoice_title": "PRIVATE_INVOICE", "requested_address": "PRIVATE_ADDRESS"},
            messages=messages or [], created_at=now - timedelta(days=1), updated_at=updated_at or now,
            expires_at=expires_at or now + timedelta(days=29),
        ))
    return str(case_id)


def other_buyer(client):
    other = TestClient(client.app)
    buyer_id = register_and_login_buyer(other, f"checkout-progress-other-{uuid4().hex}@example.com")
    other.headers.update({"Origin": "http://testserver", "X-CSRF-Token": other.get("/api/auth/csrf").json()["csrf_token"]})
    return other, UUID(buyer_id)


def test_progress_requires_login_and_buyer_role(integrated):
    client = integrated
    order_id = make_order(client, status="pending_shipment")
    created = selected_page(client, order_id)
    anonymous = TestClient(client.app)
    assert read_progress(anonymous, created, order_id).status_code == 401
    assert read_progress(admin_client(client), created, order_id).status_code == 403
    with client.app.state.session_factory() as db:
        with pytest.raises(HTTPException) as error:
            ServiceProgressTools(db, None, str(uuid4()), client.app.state.clock)
        assert error.value.status_code == 401


def test_progress_requires_explicit_matching_order_selection(integrated):
    client = integrated
    order_id = make_order(client, status="pending_shipment")
    created = page(client)
    assert read_progress(client, created, order_id).status_code == 409
    send(client, created, selected_order_id=order_id)
    assert read_progress(client, created, str(uuid4())).status_code == 409
    assert client.get(PROGRESS_URL, params={"order_id": order_id}).status_code == 422
    response = read_progress(client, created, order_id)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "empty"
    assert response.json()["data"]["items"] == []
    assert response.headers["cache-control"] == "no-store"


def test_progress_binds_page_and_consultation_to_current_session(integrated):
    client = integrated
    order_id = make_order(client, status="pending_shipment")
    created = selected_page(client, order_id)
    other, _ = other_buyer(client)
    assert read_progress(other, created, order_id).status_code == 403
    mismatched = {**created, "consultation_id": page(client)["consultation_id"]}
    assert read_progress(client, mismatched, order_id).status_code == 403
    other_created = page(other)
    with client.app.state.session_factory.begin() as db:
        db.get(Consultation, UUID(created["consultation_id"])).session_id = db.get(
            ConsultationPage, UUID(other_created["page_instance_id"])).session_id
    assert read_progress(client, created, order_id).status_code == 403


@pytest.mark.parametrize("age", [timedelta(minutes=10), timedelta(minutes=11), -timedelta(seconds=1), None])
def test_progress_rejects_expired_missing_or_future_selection(integrated, age):
    client = integrated
    order_id = make_order(client, status="pending_shipment")
    created = selected_page(client, order_id)
    now = client.app.state.clock()
    with client.app.state.session_factory.begin() as db:
        db.get(ConsultationPage, UUID(created["page_instance_id"])).selected_at = None if age is None else now - age
    assert read_progress(client, created, order_id).status_code == 409


@pytest.mark.parametrize("expired", ["page", "consultation"])
def test_progress_reuses_page_and_consultation_expiry(integrated, expired):
    client = integrated
    order_id = make_order(client, status="pending_shipment")
    created = selected_page(client, order_id)
    now = client.app.state.clock()
    with client.app.state.session_factory.begin() as db:
        if expired == "page":
            db.get(ConsultationPage, UUID(created["page_instance_id"])).last_used_at = now - timedelta(minutes=10)
        else:
            db.get(Consultation, UUID(created["consultation_id"])).last_used_at = now - timedelta(minutes=30)
    assert read_progress(client, created, order_id).status_code == 410


def test_progress_rechecks_order_ownership_even_with_matching_server_selection(integrated):
    client = integrated
    order_id = make_order(client, status="pending_shipment")
    created = selected_page(client, order_id)
    other, other_id = other_buyer(client)
    other_created = page(other)
    with client.app.state.session_factory.begin() as db:
        selection = db.get(ConsultationPage, UUID(other_created["page_instance_id"]))
        selection.selected_order_id, selection.selected_at = UUID(order_id), client.app.state.clock()
    assert read_progress(other, other_created, order_id).status_code == 403
    with client.app.state.session_factory() as db:
        tools = ServiceProgressTools(db, db.get(User, other_id), str(uuid4()), client.app.state.clock)
        with pytest.raises(HTTPException) as error:
            tools.call("get_service_progress", {"order_id": order_id})
        assert error.value.status_code == 403
    assert read_progress(client, created, order_id).status_code == 200


def test_progress_scopes_cases_by_buyer_order_and_strict_expiry(integrated):
    client = integrated
    order_id = make_order(client, status="pending_shipment")
    created = selected_page(client, order_id)
    current_id = add_case(client, order_id)
    now = client.app.state.clock()
    add_case(client, order_id, expires_at=now)
    add_case(client, order_id, expires_at=now - timedelta(seconds=1))
    second_order = make_order(client, status="pending_shipment")
    add_case(client, second_order)
    _, other_id = other_buyer(client)
    add_case(client, order_id, buyer_id=other_id)
    response = read_progress(client, created, order_id)
    assert response.status_code == 200, response.text
    assert [item["case_id"] for item in response.json()["data"]["items"]] == [current_id]


@pytest.mark.parametrize("kind", ["refund", "replacement", "invoice"])
def test_progress_kind_filter_and_resolved_never_claim_external_execution(integrated, kind):
    client = integrated
    order_id = make_order(client, status="pending_receipt")
    created = selected_page(client, order_id)
    expected = None
    now = client.app.state.clock()
    for request_kind in ("refund", "replacement", "invoice"):
        case_id = add_case(client, order_id, kind=request_kind, status="resolved", summary={
            "executed_actions": [
                {"action": request_kind, "order_id": order_id, "at": now.isoformat(), "external_status": "completed"},
                {"action": "address_change", "order_id": order_id, "at": now.isoformat()},
            ]}, messages=[{"role": "staff", "text": "工单审核已结束，请查看业务执行状态。", "at": now.isoformat()}])
        if request_kind == kind:
            expected = case_id
    before = read_progress(client, created, order_id).json()
    response = read_progress(client, created, order_id, kind=kind)
    assert response.status_code == 200, response.text
    result = response.json()
    assert {item["kind"] for item in before["data"]["items"]} == {"refund", "replacement", "invoice"}
    items = result["data"]["items"]
    assert len(items) == 1 and items[0]["case_id"] == expected
    assert items[0]["kind"] == kind and items[0]["status"] == "resolved"
    assert items[0]["execution_status"] == "not_connected" and items[0]["executed_actions"] == []
    assert "不代表退款到账、补发完成或发票开具" in result["data"]["notice"]
    assert "external_status" not in response.text
    with client.app.state.session_factory() as db:
        assert db.get(Order, UUID(order_id)).status == "pending_receipt"


def test_progress_absent_external_records_stays_not_connected(integrated):
    client = integrated
    order_id = make_order(client, status="pending_shipment")
    created = selected_page(client, order_id)
    add_case(client, order_id, kind="invoice", status="in_progress")
    response = read_progress(client, created, order_id)
    assert response.status_code == 200, response.text
    item = response.json()["data"]["items"][0]
    assert item["latest_reply"] is None
    assert item["execution_status"] == "not_connected" and item["executed_actions"] == []
    empty = read_progress(client, created, order_id, kind="replacement")
    assert empty.status_code == 200 and empty.json()["status"] == "empty"
    assert empty.json()["data"]["items"] == []
    assert "not_connected" in empty.json()["data"]["notice"]


def test_progress_only_returns_bounded_redacted_latest_staff_reply(integrated):
    client = integrated
    order_id = make_order(client, status="pending_shipment")
    created = selected_page(client, order_id)
    now = client.app.state.clock()
    add_case(client, order_id, summary={"concern": "PRIVATE_CONCERN", "history": ["PRIVATE_HISTORY"]}, messages=[
        {"role": "staff", "text": "旧回复", "at": (now - timedelta(minutes=1)).isoformat()},
        {"role": "staff", "text": "联系13800138000 或 buyer@example.com token: private-token " + "人工核验" * 200,
         "at": now.isoformat(), "staff_id": str(uuid4())},
        {"role": "buyer", "text": "PRIVATE_BUYER_MESSAGE", "at": now.isoformat()},
    ])
    response = read_progress(client, created, order_id)
    assert response.status_code == 200, response.text
    item = response.json()["data"]["items"][0]
    reply = item["latest_reply"]
    assert set(item) == {"case_id", "kind", "kind_label", "status", "latest_reply", "updated_at",
                         "execution_status", "executed_actions"}
    assert set(reply) == {"role", "text", "at"} and reply["role"] == "staff"
    assert len(reply["text"]) <= MAX_PROGRESS_REPLY
    assert "[电话已隐藏]" in reply["text"] and "[邮箱已隐藏]" in reply["text"]
    for secret in ("13800138000", "buyer@example.com", "private-token", "PRIVATE_", "staff_id", "buyer_id"):
        assert secret not in response.text


def test_progress_is_bounded_and_sorted_by_latest_case_update(integrated):
    client = integrated
    order_id = make_order(client, status="pending_shipment")
    created = selected_page(client, order_id)
    now = client.app.state.clock()
    expected = [add_case(client, order_id, updated_at=now - timedelta(seconds=index))
                for index in range(MAX_PROGRESS_CASES + 2)]
    response = read_progress(client, created, order_id)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert [item["case_id"] for item in data["items"]] == expected[:MAX_PROGRESS_CASES]
    assert data["has_more"] is True


@pytest.mark.parametrize("apply_address", [False, True])
def test_progress_verifies_only_address_review_execution_evidence(integrated, apply_address):
    client = integrated
    order_id = make_order(client, status="pending_shipment")
    created = selected_page(client, order_id)
    address = client.post("/api/addresses", json={
        "recipient_name": "买家", "phone": "13800138000", "province": "浙江省", "city": "杭州市",
        "district": "滨江区", "detail": "PRIVATE_ADDRESS_DETAIL",
    }).json()
    requested = create_request(client, created, "address_change", address_id=address["id"])
    assert requested.status_code == 201, requested.text
    case = requested.json()["case"]
    reviewed = admin_client(client).patch(f"/api/admin/customer-service/cases/{case['id']}", json={
        "status": "resolved", "reply": "工单审核结束", "expected_updated_at": case["updated_at"],
        "apply_address": apply_address,
    })
    assert reviewed.status_code == 200, reviewed.text
    response = read_progress(client, created, order_id, kind="address_change")
    assert response.status_code == 200, response.text
    item = response.json()["data"]["items"][0]
    assert item["status"] == "resolved"
    assert item["execution_status"] == ("verified" if apply_address else "not_connected")
    if apply_address:
        assert item["executed_actions"] == reviewed.json()["case"]["summary"]["executed_actions"]
        assert item["executed_actions"][0]["action"] == "address_change"
        assert item["executed_actions"][0]["order_id"] == order_id
    else:
        assert item["executed_actions"] == []
    assert "PRIVATE_ADDRESS_DETAIL" not in response.text and "13800138000" not in response.text


@pytest.mark.parametrize("invalid", ["wrong_order", "missing_time", "naive_time", "bad_time", "future", "before_case", "wrong_action"])
def test_progress_does_not_verify_invalid_address_evidence(integrated, invalid):
    client = integrated
    order_id = make_order(client, status="pending_shipment")
    created = selected_page(client, order_id)
    now = client.app.state.clock()
    action = {"action": "address_change", "order_id": order_id, "at": now.isoformat()}
    if invalid == "wrong_order":
        action["order_id"] = str(uuid4())
    elif invalid == "missing_time":
        action.pop("at")
    elif invalid == "naive_time":
        action["at"] = now.replace(tzinfo=None).isoformat()
    elif invalid == "bad_time":
        action["at"] = "not-a-timestamp"
    elif invalid == "future":
        action["at"] = (now + timedelta(minutes=1)).isoformat()
    elif invalid == "before_case":
        action["at"] = (now - timedelta(days=2)).isoformat()
    else:
        action["action"] = "refund"
    add_case(client, order_id, kind="address_change", status="resolved", summary={"executed_actions": [action]})
    response = read_progress(client, created, order_id)
    assert response.status_code == 200, response.text
    item = response.json()["data"]["items"][0]
    assert item["execution_status"] == "not_connected" and item["executed_actions"] == []


@pytest.mark.parametrize("field", ["buyer_id", "user_id", "identity", "url", "sql"])
def test_progress_route_rejects_identity_overrides_and_generic_queries(integrated, field):
    client = integrated
    order_id = make_order(client, status="pending_shipment")
    created = selected_page(client, order_id)
    assert read_progress(client, created, order_id, **{field: "forbidden"}).status_code == 422
    assert read_progress(client, created, order_id, kind="unknown").status_code == 422


def test_progress_mcp_allowlist_closed_kinds_and_no_identity_arguments(integrated):
    client = integrated
    order_id = make_order(client, status="pending_shipment")
    add_case(client, order_id)
    with client.app.state.session_factory() as db:
        buyer = db.get(User, db.get(Order, UUID(order_id)).user_id)
        tools = ServiceProgressTools(db, buyer, str(uuid4()), client.app.state.clock)
        mcp = CustomerServiceMCP(tools)
        try:
            mcp.initialize()
            assert [tool["name"] for tool in mcp.tools()] == ["get_service_progress"]
            schema = mcp.tools()[0]["inputSchema"]
            assert schema["additionalProperties"] is False and schema["required"] == ["order_id"]
            assert set(schema["properties"]) == {"order_id", "kind"}
            assert set(schema["properties"]["kind"]["enum"]) == set(REQUEST_KINDS)
            result = mcp.call("get_service_progress", {"order_id": order_id})
            assert result["data"]["items"][0]["kind"] == "refund"
            for arguments in ({"order_id": order_id, "buyer_id": str(uuid4())},
                              {"order_id": order_id, "kind": "unknown"}, {"order_id": "bad"}):
                with pytest.raises(CustomerServiceMCPFailure) as error:
                    mcp.call("get_service_progress", arguments)
                assert error.value.code == "invalid_input"
            with pytest.raises(CustomerServiceUnavailable):
                mcp.call("refund", {"order_id": order_id})
        finally:
            mcp.close()


def test_progress_tools_bound_calls_and_reject_duplicate_reads(integrated):
    client = integrated
    order_id = make_order(client, status="pending_shipment")
    with client.app.state.session_factory() as db:
        buyer = db.get(User, db.get(Order, UUID(order_id)).user_id)
        tools = ServiceProgressTools(db, buyer, str(uuid4()), client.app.state.clock)
        tools.call("get_service_progress", {"order_id": order_id, "kind": "refund"})
        with pytest.raises(HTTPException) as duplicate:
            tools.call("get_service_progress", {"order_id": order_id, "kind": "refund"})
        assert duplicate.value.status_code == 422
        tools.call("get_service_progress", {"order_id": order_id, "kind": "invoice"})
        with pytest.raises(HTTPException) as exhausted:
            tools.call("get_service_progress", {"order_id": order_id, "kind": "replacement"})
        assert exhausted.value.status_code == 503


@pytest.mark.parametrize("invalid", ["extra", "case_extra", "false_verified", "refund_action", "pii_reply", "too_many", "naive_time"])
def test_progress_mcp_result_validation_rejects_leaks_and_false_execution(integrated, invalid):
    client = integrated
    order_id = make_order(client, status="pending_shipment")
    created = selected_page(client, order_id)
    add_case(client, order_id, status="resolved")
    response = read_progress(client, created, order_id)
    assert response.status_code == 200, response.text
    value = deepcopy(response.json())
    item = value["data"]["items"][0]
    if invalid == "extra":
        value["buyer_id"] = str(uuid4())
    elif invalid == "case_extra":
        item["details"] = {"address": "private"}
    elif invalid == "false_verified":
        item["execution_status"] = "verified"
    elif invalid == "refund_action":
        item["execution_status"] = "verified"
        item["executed_actions"] = [{"action": "refund", "order_id": order_id, "at": item["updated_at"]}]
    elif invalid == "pii_reply":
        item["latest_reply"] = {"role": "staff", "text": "联系电话13800138000", "at": item["updated_at"]}
    elif invalid == "too_many":
        value["data"]["items"] = [deepcopy(item) for _ in range(MAX_PROGRESS_CASES + 1)]
    else:
        value["queried_at"] = client.app.state.clock().replace(tzinfo=None).isoformat()
    with pytest.raises(CustomerServiceUnavailable):
        verify_service_progress_result("get_service_progress", value)
