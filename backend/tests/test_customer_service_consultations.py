"""API seams for the deliberately narrow, provider-free consultation slice."""

import hashlib
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text

from shop_api.customer_service_consultations import Consultation, ConsultationMessage, ConsultationPage
from test_catalog_api import enable_customer_service_for_test, register_and_login_buyer

PREFIX = "/api/customer-service"
PRODUCT_ID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def consultation_client(client, tmp_path):
    enable_customer_service_for_test(client, tmp_path)
    client.headers.update({"Origin": "http://testserver", "X-CSRF-Token": client.get("/api/auth/csrf").json()["csrf_token"]})
    return client


def page(client, **payload):
    response = client.post(PREFIX + "/pages", json=payload)
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()["data"]


def message_payload(created, **changes):
    return {"page_instance_id": created["page_instance_id"], "consultation_id": created["consultation_id"],
            "client_message_id": str(uuid4()), "text": "查看演示商品", **changes}


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    assert response.json()["code"] == code
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["data"] is None


def test_list_select_and_dedupe_do_not_repeat_tools(consultation_client, monkeypatch):
    client = consultation_client
    created = page(client)
    payload = message_payload(created)
    first = client.post(PREFIX + "/messages", json=payload)
    assert first.status_code == 200
    data = first.json()["data"]
    assert data["citations"] == []
    assert data["cards"][0]["product"]["price"] == "129.00"
    selection = data["cards"][0]["selection_text"]
    assert selection == "查看演示商品：" + PRODUCT_ID
    detail = client.post(PREFIX + "/messages", json=message_payload(created, text=selection))
    assert detail.status_code == 200
    assert detail.json()["data"]["cards"][0]["product"]["stock"] == 24

    def unexpected_call(*args, **kwargs):
        raise AssertionError("Dedupe must not query products again")

    monkeypatch.setattr("shop_api.customer_service_consultations.ProductTools.call", unexpected_call)
    replay = client.post(PREFIX + "/messages", json=payload)
    assert replay.json() == first.json()
    assert_error(client.post(PREFIX + "/messages", json={**payload, "text": selection}), 409, "message_conflict")
    with client.app.state.session_factory() as db:
        stored = db.scalars(select(ConsultationMessage).where(ConsultationMessage.consultation_id == UUID(created["consultation_id"]))).all()
        assert len(stored) == 2


def test_controlled_page_selection_uses_bounded_page_number(consultation_client):
    client = consultation_client
    created = page(client)
    response = client.post(PREFIX + '/messages', json=message_payload(created, text='查看演示商品第2页'))
    assert response.status_code == 200
    assert response.json()['status'] == 'empty'
    assert response.json()['data']['cards'] == []
    for invalid in ['查看演示商品第0页', '查看演示商品第101页', '查看演示商品第02页', '查看演示商品第2页 执行SQL']:
        assert_error(client.post(PREFIX + '/messages', json=message_payload(created, text=invalid)), 422, 'invalid_input')


def test_handoff_consumes_predecessor_and_renewal_keeps_token(consultation_client):
    client = consultation_client
    first = page(client)
    renewed = client.post(PREFIX + "/pages/renew", json={"page_instance_id": first["page_instance_id"], "handoff_token": first["handoff_token"]})
    assert renewed.status_code == 200
    second = page(client, handoff_token=first["handoff_token"])
    assert second["consultation_id"] == first["consultation_id"]
    assert second["page_instance_id"] != first["page_instance_id"]
    assert_error(client.post(PREFIX + "/messages", json=message_payload(first)), 410, "page_expired")
    third = page(client, handoff_token=first["handoff_token"])
    assert third["consultation_id"] != first["consultation_id"]
    with client.app.state.session_factory() as db:
        persisted = db.get(ConsultationPage, UUID(second["page_instance_id"]))
        assert persisted.handoff_hash == hashlib.sha256(second["handoff_token"].encode()).digest()
        assert second["handoff_token"] not in repr(persisted.__dict__)


def test_lru_evicts_oldest_and_expiry_cannot_be_renewed(consultation_client):
    client = consultation_client
    now = client.app.state.clock()
    client.app.state.clock = lambda: now
    pages = []
    for index in range(11):
        client.app.state.clock = lambda index=index: now + timedelta(seconds=index)
        pages.append(page(client))
    assert_error(client.post(PREFIX + "/messages", json=message_payload(pages[0])), 410, "page_expired")
    with client.app.state.session_factory() as db:
        ids = db.scalars(select(ConsultationPage.id).where(ConsultationPage.id.in_([UUID(item["page_instance_id"]) for item in pages]))).all()
        assert len(ids) == 10
    client.app.state.clock = lambda: now + timedelta(minutes=11)
    assert_error(client.post(PREFIX + "/pages/renew", json={"page_instance_id": pages[-1]["page_instance_id"], "handoff_token": pages[-1]["handoff_token"]}), 410, "page_expired")


def test_consultation_idle_and_absolute_deadlines(consultation_client):
    client = consultation_client
    created = page(client)
    with client.app.state.session_factory.begin() as db:
        context = db.get(Consultation, UUID(created["consultation_id"]))
        context.last_used_at = client.app.state.clock() - timedelta(minutes=30)
    assert_error(client.post(PREFIX + "/messages", json=message_payload(created)), 410, "page_expired")
    created = page(client)
    with client.app.state.session_factory.begin() as db:
        context = db.get(Consultation, UUID(created["consultation_id"]))
        context.created_at = client.app.state.clock() - timedelta(hours=24)
    assert_error(client.post(PREFIX + "/messages", json=message_payload(created)), 410, "page_expired")


def test_session_and_consultation_binding(consultation_client):
    client = consultation_client
    created = page(client)
    assert_error(client.post(PREFIX + "/messages", json=message_payload(created, consultation_id=str(uuid4()))), 403, "resource_unavailable")
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token")
    buyer = register_and_login_buyer(client, f"consultation-other-{uuid4().hex}@example.com")
    client.app.state.customer_service_buyer_ids.add(UUID(buyer))
    client.headers["X-CSRF-Token"] = client.get("/api/auth/csrf").json()["csrf_token"]
    assert_error(client.post(PREFIX + "/messages", json=message_payload(created)), 403, "resource_unavailable")
    other_page = page(client, handoff_token=created["handoff_token"])
    assert other_page["consultation_id"] != created["consultation_id"]


@pytest.mark.parametrize("changes", [{"text": "arbitrary prompt"}, {"text": "查看演示商品：" + str(uuid4())},
                                      {"selected_product_id": PRODUCT_ID}, {"selected_order_id": str(uuid4())},
                                      {"text": None}, {"client_message_id": "not-a-uuid"}])
def test_uncontrolled_inputs_and_unknown_fields_rejected(consultation_client, changes):
    client = consultation_client
    assert_error(client.post(PREFIX + "/messages", json=message_payload(page(client), **changes)), 422, "invalid_input")


def test_byte_and_codepoint_limits_and_csrf(consultation_client):
    client = consultation_client
    created = page(client)
    assert_error(client.post(PREFIX + "/messages", json=message_payload(created, text="字" * 2001)), 422, "message_too_long")
    assert_error(client.post(PREFIX + "/messages", content=b"{" + b"x" * 16384, headers={"Content-Type": "application/json"}), 413, "payload_too_large")
    assert_error(client.post(PREFIX + "/pages", json={}, headers={"X-CSRF-Token": "bad"}), 403, "forbidden")
    assert_error(client.post(PREFIX + "/pages", json={}, headers={"Origin": "https://other.example"}), 403, "forbidden")


def test_renewal_has_independent_rate_limit(consultation_client):
    client = consultation_client
    created = page(client)
    payload = {"page_instance_id": created["page_instance_id"], "handoff_token": created["handoff_token"]}
    for _ in range(4):
        assert client.post(PREFIX + "/pages/renew", json=payload).status_code == 200
    response = client.post(PREFIX + "/pages/renew", json=payload)
    assert_error(response, 429, "rate_limited")
    assert int(response.headers["retry-after"]) >= 1
    assert client.post(PREFIX + "/messages", json=message_payload(created)).status_code == 200


def test_session_message_lock_returns_busy(consultation_client):
    client = consultation_client
    created = page(client)
    with client.app.state.session_factory() as db:
        session_id = db.get(ConsultationPage, UUID(created["page_instance_id"])).session_id
        key = int.from_bytes(hashlib.sha256(f"customer-service-message:{session_id}".encode()).digest()[:8], "big", signed=True)
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
        assert_error(client.post(PREFIX + "/messages", json=message_payload(created)), 425, "busy")
        assert_error(client.get(PREFIX + '/products'), 425, 'busy')
        assert_error(client.get(PREFIX + '/products/' + PRODUCT_ID), 425, 'busy')


def test_disabled_and_invalid_identity_fail_closed(consultation_client):
    client = consultation_client
    client.app.state.customer_service_enabled = False
    assert_error(client.post(PREFIX + "/pages", json={}), 503, "dependency_unavailable")
    client.app.state.customer_service_enabled = True
    client.app.state.customer_service_buyer_ids.clear()
    assert_error(client.post(PREFIX + "/pages", json={}), 403, "resource_unavailable")
    client.cookies.clear()
    assert_error(client.post(PREFIX + "/pages", json={}), 401, "authentication_required")


def test_cleanup_removes_expired_dedupe_and_pages(consultation_client):
    from shop_api.customer_service_consultations import cleanup_consultations

    client = consultation_client
    created = page(client)
    assert client.post(PREFIX + "/messages", json=message_payload(created)).status_code == 200
    cleanup_consultations(client.app.state.session_factory, client.app.state.clock() + timedelta(minutes=30))
    with client.app.state.session_factory() as db:
        assert db.get(Consultation, UUID(created["consultation_id"])) is None
        assert db.get(ConsultationPage, UUID(created["page_instance_id"])) is None
        assert db.scalar(select(ConsultationMessage).where(ConsultationMessage.consultation_id == UUID(created["consultation_id"]))) is None
