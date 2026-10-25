"""Authoritative-time/version checks against the dedicated test PostgreSQL DB."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from unittest.mock import Mock

import pytest
from sqlalchemy import Table, create_engine, event, text
from sqlalchemy.orm import Session

from shop_api.catalog import Product
from shop_api.customer_service_knowledge import (
    KnowledgeEntry, explain_comparison, explain_size, public_product_knowledge,
    recommend_products, search_knowledge,
)


NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)


@pytest.fixture
def knowledge_db(database_url):
    # database_url is validated by conftest before any engine is constructed.
    # All rows (and an as-yet-unmigrated knowledge table) roll back on teardown.
    engine = create_engine(database_url)
    with Session(engine) as db:
        assert db.scalar(text("SELECT current_database()")) == "shop_test"
        table = KnowledgeEntry.__table__
        assert isinstance(table, Table)
        table.create(db.connection(), checkfirst=True)
        yield db
        db.rollback()
    engine.dispose()


def _product(db, **changes):
    values = {"id": uuid4(), "name": "测试轻量通勤背包", "category": "测试箱包",
              "description": "日常通勤、办公使用的轻量背包", "image_url": "/images/backpack.svg",
              "price": Decimal("159.00"), "stock": 8, "is_listed": True,
              "created_at": NOW - timedelta(days=30), "listed_at": NOW - timedelta(days=1)}
    product = Product(**{**values, **changes})
    db.add(product)
    db.flush()
    return product


def _entry(db, product=None, **changes):
    values = {"id": uuid4(), "kind": "product", "topic": "test-material-" + uuid4().hex,
              "title": "通勤背包材质说明", "body": "已确认面料为棉帆布，不提供防水承诺。",
              "keywords": ["背包", "帆布", "通勤"], "attributes": {"material": "棉帆布"},
              "product_id": product.id if product else None, "version": 1, "state": "published",
              "valid_from": NOW - timedelta(days=1), "valid_until": None,
              "source": "fixture://merchant/knowledge", "created_at": NOW, "updated_at": NOW}
    entry = KnowledgeEntry(**{**values, **changes})
    db.add(entry)
    db.flush()
    return entry


def _cite(entry):
    return {"id": str(entry.id), "kind": entry.kind, "topic": entry.topic, "title": entry.title,
            "body": entry.body, "source": entry.source, "version": entry.version,
            "attributes": entry.attributes, "product_id": str(entry.product_id) if entry.product_id else None}


def _facts(product):
    return {"id": str(product.id), "name": product.name, "category": product.category,
            "price": str(product.price), "stock": product.stock, "is_listed": product.is_listed}


def test_retrieval_only_cites_current_published_version_and_boundary_is_exclusive(knowledge_db):
    db = knowledge_db
    product = _product(db)
    topic = "test-current-" + uuid4().hex
    current = _entry(db, product, topic=topic, version=2, valid_from=NOW,
                     title="远足背包面料", body="商家确认的当前棉帆布面料说明")
    _entry(db, product, topic=topic, version=1, valid_until=NOW, body="已过期的旧面料说明")
    _entry(db, product, topic=topic, version=3, valid_from=NOW + timedelta(seconds=1), body="未来版本")
    _entry(db, product, state="draft", body="未审核的草稿内容")
    _entry(db, product, state="retired", body="被撤回的内容")
    result = search_knowledge(db, "背包面料", NOW, product_id=product.id)
    assert result["status"] == "ok"
    assert result["method"] == "lexical_character_fusion"
    assert [item["id"] for item in result["items"]] == [str(current.id)]
    assert result["items"][0]["version"] == 2
    assert set(result["items"][0]) == {"id", "kind", "topic", "title", "body", "source", "version", "attributes", "product_id"}


def test_matching_one_version_does_not_hide_a_current_conflict_by_kind_or_limit(knowledge_db):
    db = knowledge_db
    product = _product(db)
    topic = "test-overlap-" + uuid4().hex
    _entry(db, product, topic=topic, version=1, kind="policy", title="破损赔付", body="破损可以咨询商家",
           keywords=["破损"], attributes={})
    _entry(db, product, topic=topic, version=2, kind="faq", title="完全不同措辞", body="第二条权威记录",
           keywords=[], attributes={})
    result = search_knowledge(db, "破损赔付", NOW, product_id=product.id, kinds=("policy",), limit=1)
    assert result == {"status": "conflict", "items": [], "method": "lexical_character_fusion"}
    assert public_product_knowledge(db, product.id, NOW)["status"] == "conflict"


def test_same_topic_for_different_products_is_not_a_conflict(knowledge_db):
    db = knowledge_db
    first, second = _product(db), _product(db, name="第二款测试背包")
    topic = "test-material-" + uuid4().hex
    one = _entry(db, first, topic=topic)
    two = _entry(db, second, topic=topic)
    result = search_knowledge(db, "棉帆布", NOW)
    ids = {item["id"] for item in result["items"]}
    assert result["status"] == "ok"
    assert {str(one.id), str(two.id)} <= ids


def test_unlisted_product_knowledge_never_appears_in_any_public_path(knowledge_db):
    db = knowledge_db
    hidden = _product(db, name="密藏紫榕背包", is_listed=False)
    entry = _entry(db, hidden, title="密藏紫榕保密材质", body="紫榕纤维", keywords=["密藏紫榕"])
    assert search_knowledge(db, "密藏紫榕", NOW)["status"] == "empty"
    assert search_knowledge(db, "密藏紫榕", NOW, product_id=hidden.id)["status"] == "empty"
    assert public_product_knowledge(db, hidden.id, NOW)["status"] == "empty"
    recommended = recommend_products(db, "密藏紫榕", NOW, {"categories": [hidden.category]})
    assert str(hidden.id) not in {item["product"]["id"] for item in recommended["items"]}
    assert str(entry.id) not in {citation["id"] for item in recommended["items"] for citation in item["knowledge"]}
    hidden.is_listed = True
    db.flush()
    assert public_product_knowledge(db, hidden.id, NOW)["status"] == "ok"
    hidden.is_listed = False
    db.flush()
    assert public_product_knowledge(db, hidden.id, NOW)["status"] == "empty"


def test_character_similarity_and_lexical_keywords_both_find_authoritative_text(knowledge_db):
    db = knowledge_db
    product = _product(db)
    exact = _entry(db, product, title="手冲咖啡壶", body="手冲壶可手洗。", keywords=["冲泡器具"], attributes={})
    fuzzy = _entry(db, product, title="咖啡器具的清洁", body="咖啡器具宜用软布。", keywords=[], attributes={})
    lexical = search_knowledge(db, "冲泡器具", NOW, product_id=product.id)
    assert lexical["items"][0]["id"] == str(exact.id)
    character = search_knowledge(db, "咖啡器具如何清洁", NOW, product_id=product.id)
    assert character["items"][0]["id"] == str(fuzzy.id)
    assert character["method"] == "lexical_character_fusion"
    assert "embedding" not in str(character).lower()


def test_nonmatching_and_empty_queries_do_not_return_arbitrary_knowledge(knowledge_db):
    db = knowledge_db
    product = _product(db)
    _entry(db, product)
    assert search_knowledge(db, "zxqv_2847_gibberish", NOW, product_id=product.id)["status"] == "empty"
    assert search_knowledge(db, "  ", NOW, product_id=product.id)["items"] == []


def test_catalog_use_case_category_and_budget_produce_useful_bounded_recommendations(knowledge_db):
    db = knowledge_db
    category = "测试通勤箱包-" + uuid4().hex[:8]
    good = _product(db, category=category)
    _entry(db, good, attributes={"occasion": ["通勤", "办公"], "material": "棉帆布"})
    _product(db, category=category, name="昂贵测试背包", price=Decimal("899.00"))
    _product(db, category=category, name="售罄测试背包", stock=0)
    _product(db, category=category, name="下架测试背包", is_listed=False)
    statements = []
    connection = db.connection()
    def record(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT") and "set_config" not in statement:
            statements.append(statement)
    event.listen(connection, "before_cursor_execute", record)
    try:
        result = recommend_products(db, "想买通勤背包，预算200元", NOW, {"categories": [category]})
    finally:
        event.remove(connection, "before_cursor_execute", record)
    assert len(statements) == 2
    assert [item["product"]["id"] for item in result["items"]] == [str(good.id)]
    assert any("预算" in reason for reason in result["items"][0]["reasons"])
    assert any("用途：通勤" in reason for reason in result["items"][0]["reasons"])
    assert result["items"][0]["knowledge"]
    assert result["needs"] == []
    assert "当前有效的已发布商品知识" in result["based_on"]


def test_catalog_category_is_useful_without_any_published_knowledge(knowledge_db):
    db = knowledge_db
    category = "测试陶瓷-" + uuid4().hex[:8]
    product = _product(db, name="手作陶瓷水杯", category=category, description="日常喝水用杯")
    result = recommend_products(db, category, NOW)
    assert result["items"][0]["product"]["id"] == str(product.id)
    assert result["items"][0]["knowledge"] == []
    assert any(category in reason for reason in result["items"][0]["reasons"])


def test_authoritative_use_case_can_find_products_beyond_catalog_wording(knowledge_db):
    db = knowledge_db
    product = _product(db, name="测试轻量随身袋", category="测试布艺", description="棉质随身袋")
    entry = _entry(db, product, title="已核验用途", body="商家确认用途见属性", keywords=[],
                   attributes={"occasion": "远足"})
    result = recommend_products(db, "远足", NOW)
    assert str(product.id) in {item["product"]["id"] for item in result["items"]}
    item = next(item for item in result["items"] if item["product"]["id"] == str(product.id))
    assert str(entry.id) in {citation["id"] for citation in item["knowledge"]}
    assert any("远足" in reason for reason in item["reasons"])


def test_missing_size_and_ingredient_evidence_is_not_fabricated(knowledge_db):
    db = knowledge_db
    category = "测试护肤-" + uuid4().hex[:8]
    _product(db, category=category, name="测试面霜", description="商家在售面霜")
    result = recommend_products(db, "敏感肌用的面霜，成分是什么", NOW, {"categories": [category]})
    assert result["items"] == []
    assert any("缺少" in need for need in result["needs"])
    assert any("适用肤质" in need for need in result["needs"])
    assert explain_size([],{"height_cm": 168, "weight_kg": 55})["recommendations"] == []


def test_recommendation_does_not_use_conflicted_attributes(knowledge_db):
    db = knowledge_db
    category = "测试冲突-" + uuid4().hex[:8]
    product = _product(db, category=category)
    topic = "test-conflict-" + uuid4().hex
    _entry(db, product, topic=topic, version=1, attributes={"occasion": "通勤"})
    _entry(db, product, topic=topic, version=2, attributes={"occasion": "露营"})
    result = recommend_products(db, "通勤", NOW, {"categories": [category]})
    assert result["items"] == []
    assert any("冲突" in need for need in result["needs"])


@pytest.mark.parametrize("preferences", [
    {"budget": True}, {"budget": "nan"}, {"budget": "inf"}, {"budget": -10},
    {"budget": "1e100"}, {"budget_min": 200, "budget_max": 100},
    {"categories": [False]}, {"categories": ["x"] * 7}, {"occasion": {"sql": "query"}},
])
def test_invalid_preferences_are_rejected_before_database_access(preferences):
    with pytest.raises(ValueError):
        recommend_products(Mock(spec=Session), "推荐", NOW, preferences)


def test_invalid_query_times_and_limits_are_rejected_before_database_access():
    with pytest.raises(ValueError):
        search_knowledge(Mock(spec=Session), "运费", datetime(2026, 10, 25))
    with pytest.raises(ValueError):
        search_knowledge(Mock(spec=Session), "运费", NOW, limit=True)
    with pytest.raises(ValueError):
        search_knowledge(Mock(spec=Session), "运费", NOW, kinds=("research",))


def test_size_explanation_uses_only_verified_chart_and_all_dimensions(knowledge_db):
    db = knowledge_db
    product = _product(db)
    entry = _entry(db, product, topic="test-size-" + uuid4().hex, attributes={"size_chart": {
        "M": {"height_cm": [160, 170], "weight_kg": [50, 60]},
        "L": {"height_cm": [170, 180], "weight_kg": [60, 75]},
    }})
    retrieved = public_product_knowledge(db, product.id, NOW)["items"]
    incomplete = explain_size(retrieved, {"height_cm": 168})
    assert incomplete["recommendations"] == []
    assert any("weight_kg" in need for need in incomplete["needs"])
    complete = explain_size(retrieved, {"height_cm": 168, "weight_kg": 55})
    assert complete["status"] == "ok"
    assert len(complete["recommendations"]) == 1
    assert " M" in complete["recommendations"][0]
    assert complete["citations"][0]["id"] == str(entry.id)
    outside = explain_size(retrieved, {"height_cm": 190, "weight_kg": 90})
    assert outside["recommendations"] == []
    assert outside["needs"]


@pytest.mark.parametrize("measurements", [
    {"height_cm": True}, {"height_cm": "nan"}, {"weight_kg": -1}, {"height_cm": 999},
    {"weight_kg": "1e999"}, {"height": 168},
])
def test_measurements_require_valid_numbers_and_explicit_units(measurements):
    with pytest.raises(ValueError):
        explain_size([], measurements)


def test_comparison_uses_catalog_prices_and_verified_attributes_without_inventing_winner(knowledge_db):
    db = knowledge_db
    first = _product(db, price=Decimal("159.00"))
    second = _product(db, name="测试皮质背包", price=Decimal("299.00"))
    one = _entry(db, first, attributes={"material": "棉帆布", "price": "0.01"})
    two = _entry(db, second, attributes={"material": "商家登记的皮革"})
    result = explain_comparison([_facts(first), _facts(second)], [_cite(one), _cite(two)])
    assert result["status"] == "ok"
    differences = {item["attribute"]: item["values"] for item in result["differences"]}
    assert differences["material"][str(first.id)] == "棉帆布"
    assert differences["price"][str(first.id)] == "159.00"
    assert "price" not in result["items"][0]["attributes"]
    assert "winner" not in result
    partial = explain_comparison([_facts(first), _facts(second)], [_cite(one)])
    assert any(second.name in need for need in partial["needs"])


def test_helpers_surface_conflicting_citations_instead_of_selecting_one(knowledge_db):
    db = knowledge_db
    first, second = _product(db), _product(db)
    topic = "test-helper-conflict-" + uuid4().hex
    one = _entry(db, first, topic=topic, version=1, attributes={"size_chart": {"M": {"height_cm": [160, 170]}}})
    two = _entry(db, first, topic=topic, version=2, attributes={"size_chart": {"M": {"height_cm": [165, 175]}}})
    citations = [_cite(one), _cite(two)]
    assert explain_size(citations)["status"] == "conflict"
    assert explain_comparison([_facts(first), _facts(second)], citations)["status"] == "conflict"


def test_publishing_size_charts_validates_ranges_and_requires_the_explained_format():
    from shop_api.customer_service_knowledge import validate_product_attributes
    chart = {"size_chart": {"M": {"height_cm": [160, 170], "weight_kg": [50, 60]}}}
    assert validate_product_attributes(chart) == chart
    for invalid in ([{"尺码": "M", "胸围_cm": 96}], {}, {"M": {"height_cm": [170, 160]}},
                    {"M": {"weight_kg": [True, 60]}}, {"M": {"unknown": [1, 2]}}):
        with pytest.raises(ValueError):
            validate_product_attributes({"size_chart": invalid})


def test_explicit_measurements_support_incremental_inputs_and_jin_conversion():
    from shop_api.customer_service_knowledge import parse_measurements
    assert parse_measurements("身高168厘米，体重110斤，胸围90cm，腰围70厘米") == {
        "height_cm": 168, "weight_kg": 55, "chest_cm": 90, "waist_cm": 70}
    assert parse_measurements("55公斤") == {"weight_kg": 55}
    assert parse_measurements("168 55") == {}


def test_current_budget_overrides_saved_preference_and_fit_uses_published_values(knowledge_db):
    db = knowledge_db
    category = "测试护肤-" + uuid4().hex[:8]
    good = _product(db, name="测试敏感肌面霜", category=category, price=Decimal("159.00"))
    wrong = _product(db, name="测试另一款面霜", category=category, price=Decimal("149.00"))
    _entry(db, good, attributes={"skin_types": ["敏感肌"], "skin_tones": ["暖黄皮"]})
    _entry(db, wrong, attributes={"skin_types": ["不适合敏感肌"], "skin_tones": ["冷白皮"]})
    result = recommend_products(db, "推荐敏感肌暖黄皮用的面霜，预算200元", NOW,
                                {"categories": [category], "budget_max": "100"})
    assert [item["product"]["id"] for item in result["items"]] == [str(good.id)]
    assert any("敏感肌" in reason for reason in result["items"][0]["reasons"])
    assert any("暖黄皮" in reason for reason in result["items"][0]["reasons"])
