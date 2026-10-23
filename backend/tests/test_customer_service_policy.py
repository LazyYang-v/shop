"""Synthetic-only policy authority path. Real mall policy and WeKnora stay closed."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest


def record(**changes):
    content = changes.pop("canonical_content", "虚构演示规则：订单在付款后 48 小时内发出。")
    value = {
        "policy_id": "00000000-0000-4000-8000-000000000101",
        "version": 1,
        "scope_key": "demo_shipping",
        "source_label": "虚构演示政策 · 发货时限 v1",
        "source_ref": "synthetic://policies/demo-shipping-v1",
        "effective_from": "2025-01-01T00:00:00+00:00",
        "effective_to": "2025-06-01T00:00:00+00:00",
        "status": "withdrawn",
        "knowledge_base_id": "synthetic-demo-kb",
        "knowledge_id": "doc-demo-shipping-v1",
        "canonical_content": content,
        "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
    }
    value.update(changes)
    return value


def fixture(*, policies=None, policy_index=None, research_articles=None, **changes):
    value = {
        "synthetic": True,
        "label": "虚构演示政策（非真实商城政策）",
        "knowledge_base_id": "synthetic-demo-kb",
        "policies": policies or [record()],
        "policy_index": policy_index if policy_index is not None else [
            {"knowledge_base_id": "synthetic-demo-kb", "knowledge_id": "doc-demo-shipping-v1",
             "title": "演示商城发货时限", "text": "演示商城订单在付款后 48 小时内发出。",
             "source_type": "synthetic_mall_policy"},
        ],
        "research_articles": research_articles or [],
    }
    value.update(changes)
    return value


def test_publication_rejects_overlapping_active_intervals():
    from shop_api.customer_service_policy import PolicyPublicationError, load_policy_data

    first = record(status="active", effective_to="2026-01-01T00:00:00+00:00")
    second = record(policy_id="00000000-0000-4000-8000-000000000102", version=2,
                    knowledge_id="doc-demo-shipping-v2", source_ref="synthetic://policies/demo-shipping-v2",
                    status="active", effective_from="2025-12-01T00:00:00+00:00", effective_to=None)
    with pytest.raises(PolicyPublicationError):
        load_policy_data(fixture(policies=[first, second]))


def test_publication_accepts_non_overlapping_versions_and_verifies_canonical_content():
    from shop_api.customer_service_policy import PolicyPublicationError, load_policy_data

    old = record()
    new = record(policy_id="00000000-0000-4000-8000-000000000102", version=2,
                 knowledge_id="doc-demo-shipping-v2", source_ref="synthetic://policies/demo-shipping-v2",
                 status="active", effective_from="2025-06-01T00:00:00+00:00", effective_to=None)
    registry, index = load_policy_data(fixture(policies=[old, new], policy_index=[
        policy_index_document("doc-demo-shipping-v1", "旧的 72 小时规则。"),
        policy_index_document("doc-demo-shipping-v2", "演示商城订单在付款后 48 小时内发出。"),
    ]))
    assert registry.lookup("synthetic-demo-kb", "doc-demo-shipping-v2").version == 2
    assert index.knowledge_base_id == "synthetic-demo-kb"

    bad = record(content_sha256="0" * 64)
    with pytest.raises(PolicyPublicationError):
        load_policy_data(fixture(policies=[bad]))


NOW = datetime(2026, 10, 23, tzinfo=UTC)


def active_shipping(content="虚构演示规则：演示商城订单在付款后 48 小时内发出。", *,
                    policy_id="00000000-0000-4000-8000-000000000102", version=2,
                    knowledge_id="doc-demo-shipping-v2", source_ref="synthetic://policies/demo-shipping-v2"):
    return record(policy_id=policy_id, version=version, knowledge_id=knowledge_id, source_ref=source_ref,
                  status="active", effective_from="2025-06-01T00:00:00+00:00",
                  effective_to=None, canonical_content=content)


def policy_index_document(knowledge_id="doc-demo-shipping-v1",
                          text="演示商城订单在付款后 48 小时内发出。"):
    return {"knowledge_base_id": "synthetic-demo-kb", "knowledge_id": knowledge_id,
            "title": "演示商城发货时限", "text": text, "source_type": "synthetic_mall_policy"}


def test_current_version_is_cited_with_source_version_and_effective_basis():
    from shop_api.customer_service_policy import SYNTHETIC_LABEL, answer_policy_question, load_policy_data

    old = record(canonical_content="旧的 72 小时规则。")
    new = active_shipping()
    registry, index = load_policy_data(fixture(policies=[old, new], policy_index=[
        policy_index_document("doc-demo-shipping-v1", "旧的 72 小时规则。"),
        policy_index_document("doc-demo-shipping-v2", "演示商城订单在付款后 48 小时内发出。"),
    ]))

    answer = answer_policy_question("演示商城多久发货？", registry, index, NOW)

    assert answer is not None and answer.status == "ok" and answer.code is None
    assert "48 小时" in answer.reply and "72 小时" not in answer.reply
    assert "v2" in answer.reply and SYNTHETIC_LABEL in answer.reply
    assert len(answer.citations) == 1
    citation = answer.citations[0]
    assert citation["version"] == 2
    assert citation["source_ref"] == "synthetic://policies/demo-shipping-v2"
    assert citation["effective_from"] == "2025-06-01T00:00:00+00:00"
    assert citation["effective_to"] is None
    assert citation["synthetic"] is True and citation["label"] == SYNTHETIC_LABEL


def test_withdrawn_expired_future_and_deleted_residue_are_never_current_basis():
    from shop_api.customer_service_policy import answer_policy_question, load_policy_data

    expired = record(policy_id="00000000-0000-4000-8000-000000000201", scope_key="demo_free_shipping",
                     knowledge_id="doc-demo-free-shipping-v1", source_ref="synthetic://policies/demo-free-shipping-v1",
                     status="active", effective_from="2025-01-01T00:00:00+00:00",
                     effective_to="2025-09-01T00:00:00+00:00",
                     canonical_content="演示商城满 99.00 元包邮。")
    future = record(policy_id="00000000-0000-4000-8000-000000000202", version=2, scope_key="demo_free_shipping",
                    knowledge_id="doc-demo-free-shipping-v2", source_ref="synthetic://policies/demo-free-shipping-v2",
                    status="active", effective_from="2026-12-01T00:00:00+00:00", effective_to=None,
                    canonical_content="演示商城满 129.00 元包邮。")
    registry, index = load_policy_data(fixture(policies=[expired, future], policy_index=[
        policy_index_document("doc-demo-free-shipping-v1", "演示商城满 99.00 元包邮。"),
        policy_index_document("doc-demo-free-shipping-v2", "演示商城满 129.00 元包邮。"),
        policy_index_document("doc-deleted-residue", "演示商城包邮门槛已删除的旧条目。"),
    ]))

    answer = answer_policy_question("演示商城包邮门槛是多少？", registry, index, NOW)

    assert answer is not None
    assert answer.status == "unavailable" and answer.code == "policy_unavailable"
    assert answer.citations == ()
    assert "失效或待维护" in answer.reply


def test_no_match_is_distinct_from_research_material_which_is_not_cited():
    from shop_api.customer_service_policy import answer_policy_question, load_policy_data

    registry, index = load_policy_data(fixture(research_articles=[
        {"knowledge_base_id": "synthetic-research-kb", "knowledge_id": "article-packaging",
         "title": "行业观察：礼品包装", "text": "非商城政策研究资料：礼品包装众包观察。",
         "source_label": "非商城政策 · 行业研究资料"},
    ]))
    answer = answer_policy_question("演示商城礼品包装政策是什么？", registry, index, NOW)

    assert answer is not None
    assert answer.status == "no_match" and answer.code == "policy_no_match"
    assert answer.citations == ()
    assert "未检索到足够相关的政策依据" in answer.reply
    assert "非商城政策" in answer.reply
    assert "众包观察" not in answer.reply

    no_candidates = answer_policy_question("演示商城礼品包装政策是什么？", registry, index, NOW)
    assert no_candidates is not None and no_candidates.status == "no_match"


def test_ambiguous_policy_question_requests_clarification_and_ordinary_text_is_ignored():
    from shop_api.customer_service_policy import answer_policy_question, load_policy_data

    registry, index = load_policy_data(fixture())
    ambiguous = answer_policy_question("演示商城周末发货政策是什么？", registry, index, NOW)
    assert ambiguous is not None
    assert ambiguous.status == "needs_clarification" and ambiguous.code is None
    assert ambiguous.citations == ()
    assert "暂无法确定适用的政策主题或条件" in ambiguous.reply
    assert answer_policy_question("今天天气怎么样？", registry, index, NOW) is None


def test_conflicting_authoritative_registrations_stop_the_answer():
    from shop_api.customer_service_policy import PolicyRegistry, answer_policy_question, load_policy_data

    _, index = load_policy_data(fixture())
    first = active_shipping()
    second = record(policy_id="00000000-0000-4000-8000-000000000103", version=1,
                    knowledge_id="doc-demo-shipping-conflict", source_ref="synthetic://policies/demo-shipping-conflict",
                    status="active", effective_from="2025-06-01T00:00:00+00:00", effective_to=None,
                    canonical_content="另一条相互冲突的虚构规则。")
    corrupt = PolicyRegistry.from_registrations((first, second), publication_validated=False)

    answer = answer_policy_question("演示商城多久发货？", corrupt, index, NOW)

    assert answer is not None
    assert answer.status == "conflict" and answer.code == "policy_conflict"
    assert answer.citations == ()
    assert "冲突" in answer.reply


def test_index_failure_is_unavailable_not_no_match():
    from shop_api.customer_service_policy import answer_policy_question, load_policy_data

    class FailingIndex:
        def search(self, question, scope_key=None, limit=5):
            raise RuntimeError("private upstream detail")

    registry, _ = load_policy_data(fixture())
    answer = answer_policy_question("演示商城多久发货？", registry, FailingIndex(), NOW)
    assert answer is not None
    assert answer.status == "unavailable" and answer.code == "policy_unavailable"
    assert "private upstream detail" not in answer.reply


def test_withdrawal_between_retrieval_and_delivery_removes_the_answer(monkeypatch):
    from shop_api.customer_service_policy import answer_policy_question, load_policy_data

    registry, index = load_policy_data(fixture(policies=[active_shipping()], policy_index=[
        policy_index_document("doc-demo-shipping-v2", "演示商城订单在付款后 48 小时内发出。")]))
    original_search = index.search

    def search_then_withdraw(question, scope_key=None, limit=5):
        result = original_search(question, scope_key, limit)
        registry.withdraw("00000000-0000-4000-8000-000000000102", 2)
        return result

    monkeypatch.setattr(index, "search", search_then_withdraw)
    answer = answer_policy_question("演示商城多久发货？", registry, index, NOW)
    assert answer is not None
    assert answer.status == "unavailable" and answer.code == "policy_unavailable"
    assert answer.citations == ()


def test_demo_fixture_is_synthetic_and_answers_its_current_shipping_version():
    from pathlib import Path
    from shop_api.customer_service_policy import SYNTHETIC_LABEL, answer_policy_question, load_synthetic_policy_fixture

    path = Path(__file__).resolve().parents[2] / "deploy/customer-service-demo/policies.synthetic.v1.json"
    import hashlib
    registry, index = load_synthetic_policy_fixture(str(path), hashlib.sha256(path.read_bytes()).hexdigest())

    answer = answer_policy_question("演示商城多久发货？", registry, index, NOW)
    assert answer is not None and answer.status == "ok"
    assert answer.citations[0]["version"] == 2
    assert answer.citations[0]["label"] == SYNTHETIC_LABEL
    assert "PRIVATE_POLICY_SENTINEL" not in answer.reply
    assert all("PRIVATE_POLICY_SENTINEL" not in citation["content"] for citation in answer.citations)

    free_shipping = answer_policy_question("演示商城包邮门槛是多少？", registry, index, NOW)
    assert free_shipping is not None and free_shipping.status == "unavailable"
    research_only = answer_policy_question("演示商城礼品包装政策是什么？", registry, index, NOW)
    assert research_only is not None and research_only.status == "no_match"
    assert "非商城政策" in research_only.reply
    assert "PRIVATE_RESEARCH_SENTINEL" not in research_only.reply


@pytest.mark.parametrize("changes", [
    {"synthetic": False},
    {"label": "商城真实政策"},
    {"knowledge_base_id": "real-mall-kb"},
])
def test_loader_rejects_unlabelled_or_non_synthetic_sources(changes):
    from shop_api.customer_service_policy import PolicyPublicationError, load_policy_data

    with pytest.raises(PolicyPublicationError):
        load_policy_data(fixture(**changes))


def test_loader_rejects_real_urls_duplicate_versions_and_research_in_policy_index():
    from shop_api.customer_service_policy import PolicyPublicationError, load_policy_data

    with pytest.raises(PolicyPublicationError):
        load_policy_data(fixture(policies=[record(source_ref="https://example.com/policy")]))
    with pytest.raises(PolicyPublicationError):
        load_policy_data(fixture(policies=[
            record(),
            record(knowledge_id="doc-other"),
        ]))
    with pytest.raises(PolicyPublicationError):
        load_policy_data(fixture(policy_index=[{
            "knowledge_base_id": "synthetic-demo-kb", "knowledge_id": "doc-demo-shipping-v1",
            "title": "外部文章", "text": "外部内容", "source_type": "external_article",
        }]))
    with pytest.raises(PolicyPublicationError):
        load_policy_data(fixture(research_articles=[{
            "knowledge_base_id": "synthetic-demo-kb", "knowledge_id": "article-1",
            "title": "外部文章", "text": "外部内容", "source_label": "非商城政策",
        }]))
    with pytest.raises(PolicyPublicationError):
        load_policy_data(fixture(policies=[record(status="active")], policy_index=[]))


PREFIX = "/api/customer-service"


def enable_synthetic_policy_for_test(client):
    import hashlib
    from pathlib import Path
    from shop_api.customer_service_policy import load_synthetic_policy_fixture

    path = Path(__file__).resolve().parents[2] / "deploy/customer-service-demo/policies.synthetic.v1.json"
    registry, index = load_synthetic_policy_fixture(str(path), hashlib.sha256(path.read_bytes()).hexdigest())
    client.app.state.customer_service_policy_registry = registry
    client.app.state.customer_service_policy_index = index
    return registry, index


@pytest.fixture
def policy_client(client, tmp_path):
    from test_catalog_api import enable_customer_service_for_test
    from uuid import uuid4

    enable_customer_service_for_test(client, tmp_path)
    enable_synthetic_policy_for_test(client)
    client.headers.update({"Origin": "http://testserver",
                           "X-CSRF-Token": client.get("/api/auth/csrf").json()["csrf_token"]})
    return client


def _page(client):
    response = client.post(PREFIX + "/pages", json={})
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _ask(client, created, text):
    from uuid import uuid4
    return client.post(PREFIX + "/messages", json={
        "page_instance_id": created["page_instance_id"], "consultation_id": created["consultation_id"],
        "client_message_id": str(uuid4()), "text": text,
    })


def test_policy_message_returns_citation_without_calling_a_model(policy_client):
    class ForbiddenTransport:
        def close(self):
            pass

        def execute(self, *args, **kwargs):
            raise AssertionError("Policy path must not call the model")

    client = policy_client
    client.app.state.customer_service_synthetic_transport = ForbiddenTransport()
    created = _page(client)
    response = _ask(client, created, "演示商城多久发货？")

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "ok"
    assert result["data"]["cards"] == []
    assert result["data"]["synthetic"] is True
    assert result["data"]["policy_notice"] == "虚构演示政策（非真实商城政策）"
    citation = result["data"]["citations"][0]
    assert citation["version"] == 2
    assert citation["source_ref"] == "synthetic://policies/demo-shipping-v2"
    assert "48 小时" in citation["content"]
    assert "PRIVATE_POLICY_SENTINEL" not in response.text
    records = [json.loads(line) for path in client.app.state.customer_service_log_writer._directory.glob("*.jsonl")
               for line in path.read_text().splitlines()]
    policy_records = [record for record in records if record["tool"] == "search_policy"]
    assert policy_records and policy_records[-1]["error"] == "" and policy_records[-1]["count"] == 1
    assert all("演示商城" not in path.read_text() and "PRIVATE_POLICY_SENTINEL" not in path.read_text()
               for path in client.app.state.customer_service_log_writer._directory.glob("*.jsonl"))


def test_policy_message_keeps_no_match_conflict_and_unavailable_distinct(policy_client):
    from shop_api.customer_service_policy import PolicyRegistry, load_policy_data
    from shop_api.customer_service_policy import load_synthetic_policy_fixture
    import hashlib
    from pathlib import Path

    client = policy_client
    created = _page(client)

    no_match = _ask(client, created, "演示商城礼品包装政策是什么？")
    assert no_match.status_code == 200
    assert no_match.json()["status"] == "no_match"
    assert no_match.json()["code"] == "policy_no_match"
    assert no_match.json()["data"]["citations"] == []
    assert "非商城政策" in no_match.json()["data"]["reply"]

    filtered = _ask(client, created, "演示商城包邮门槛是多少？")
    assert filtered.json()["status"] == "unavailable"
    assert filtered.json()["code"] == "policy_unavailable"

    path = Path(__file__).resolve().parents[2] / "deploy/customer-service-demo/policies.synthetic.v1.json"
    registry, index = load_synthetic_policy_fixture(str(path), hashlib.sha256(path.read_bytes()).hexdigest())
    corrupt = PolicyRegistry.from_registrations([
        active_shipping(),
        record(policy_id="00000000-0000-4000-8000-000000000103", version=1,
               knowledge_id="doc-demo-shipping-conflict",
               source_ref="synthetic://policies/demo-shipping-conflict",
               status="active", effective_from="2025-06-01T00:00:00+00:00", effective_to=None,
               canonical_content="另一条相互冲突的虚构规则。"),
    ], publication_validated=False)
    client.app.state.customer_service_policy_registry = corrupt
    conflict = _ask(client, created, "演示商城多久发货？")
    assert conflict.json()["status"] == "conflict"
    assert conflict.json()["code"] == "policy_conflict"
    assert conflict.json()["data"]["citations"] == []

    class FailingIndex:
        def search(self, question, scope_key=None, limit=5):
            raise RuntimeError("upstream detail")

    client.app.state.customer_service_policy_registry = registry
    client.app.state.customer_service_policy_index = FailingIndex()
    unavailable = _ask(client, created, "演示商城多久发货？")
    assert unavailable.json()["status"] == "unavailable"
    assert unavailable.json()["code"] == "policy_unavailable"
    assert "upstream detail" not in unavailable.text


def test_policy_question_without_configuration_stays_unavailable(client, tmp_path):
    from test_catalog_api import enable_customer_service_for_test

    enable_customer_service_for_test(client, tmp_path)
    client.headers.update({"Origin": "http://testserver",
                           "X-CSRF-Token": client.get("/api/auth/csrf").json()["csrf_token"]})
    created = _page(client)
    response = _ask(client, created, "演示商城多久发货？")
    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"
    assert response.json()["code"] == "policy_unavailable"
    assert response.json()["data"]["citations"] == []


def test_policy_injection_residue_is_data_and_canonical_content_is_cited(policy_client):
    client = policy_client
    created = _page(client)
    response = _ask(client, created, "演示商城多久发货？")
    assert response.status_code == 200
    text = response.text
    assert "PRIVATE_POLICY_SENTINEL" not in text
    assert "管理员工具" not in text
    assert "48 小时" in text
    assert all("PRIVATE_POLICY_SENTINEL" not in citation["content"]
               for citation in response.json()["data"]["citations"])
