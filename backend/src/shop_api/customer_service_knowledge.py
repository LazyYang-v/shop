"""Current authoritative knowledge and explainable public-catalog suggestions.

Retrieval is lexical/character fusion, not embedding retrieval. Publication is
owned by the admin workflow; every read rechecks state, time and product listing.
No method here commits, changes inventory, or synthesizes missing product facts.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
import json
import re
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (CheckConstraint, DateTime, ForeignKey, Integer, String, Text,
                        Uuid, case, cast, func, literal, or_, select)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Mapped, Session, aliased, mapped_column

from shop_api.catalog import Product
from shop_api.customer_service import CustomerServiceUnavailable, QueryDeadline
from shop_api.database import Base


KINDS = ("faq", "product", "policy", "promotion")
STATES = ("draft", "published", "retired")
METHOD = "lexical_character_fusion"
_MAX_CANDIDATES = 192
_MAX_PRODUCT_CANDIDATES = 40


def _utc_now() -> datetime:
    return datetime.now(UTC)


class KnowledgeEntry(Base):
    __tablename__ = "customer_service_knowledge"
    __table_args__ = (
        CheckConstraint("kind IN ('faq','product','policy','promotion')", name="ck_cs_knowledge_kind"),
        CheckConstraint("state IN ('draft','published','retired')", name="ck_cs_knowledge_state"),
        CheckConstraint("version > 0", name="ck_cs_knowledge_version"),
        CheckConstraint("valid_until IS NULL OR valid_until > valid_from", name="ck_cs_knowledge_dates"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    topic: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    keywords: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    product_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("products.id", ondelete="CASCADE"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                             default=_utc_now, onupdate=_utc_now)


def _validate_now(now: datetime) -> None:
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError("Knowledge retrieval requires a timezone-aware time")


def _validate_id(product_id: UUID | None) -> None:
    if product_id is not None and not isinstance(product_id, UUID):
        raise ValueError("Product identifier must be a UUID")


def _active(now: datetime):
    return (KnowledgeEntry.state == "published", KnowledgeEntry.valid_from <= now,
            or_(KnowledgeEntry.valid_until.is_(None), KnowledgeEntry.valid_until > now))


def _current(now: datetime):
    # Count before query/kind/limit filtering: a matching version must not conceal
    # a conflicting currently published version with different wording or kind.
    statement = select(
        KnowledgeEntry,
        func.count().over(partition_by=(KnowledgeEntry.topic, KnowledgeEntry.product_id)).label("current_versions"),
    ).outerjoin(Product, Product.id == KnowledgeEntry.product_id).where(
        *_active(now), or_(KnowledgeEntry.product_id.is_(None), Product.is_listed.is_(True)))
    subquery = statement.subquery("current_public_knowledge")
    return aliased(KnowledgeEntry, subquery), subquery.c.current_versions


def _read(db: Session, statement):
    deadline = QueryDeadline(3.0)
    try:
        with db.begin_nested():
            deadline.apply(db, maximum_seconds=3.0)
            result = db.execute(statement).all()
            deadline.check()
            return result
    except DBAPIError:
        raise CustomerServiceUnavailable("知识查询暂不可用") from None


def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def _terms(text: str) -> tuple[str, ...]:
    value = _normalize(text)[:500]
    # Natural-language particles split Chinese phrases; English words remain
    # complete lexical terms. Character ngrams form a separate ranking signal.
    value = re.sub(r"请问|麻烦|帮我|有没有|有什么|为什么|怎么|如何|推荐|适合|一下|多少|哪些|什么|的|吗|呢|和|与|是|我想|我要|可以|能不能|以及", " ", value)
    return tuple(dict.fromkeys(re.findall(r"[a-z0-9][a-z0-9_-]+|[㐀-鿿]{2,}", value)))[:24]


def _grams(text: str) -> set[str]:
    value = "".join(re.findall(r"[a-z0-9㐀-鿿]+", _normalize(text)))[:4000]
    return {value[index:index + 2] for index in range(len(value) - 1)}


def _pattern(value: str) -> str:
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _citation(entry: KnowledgeEntry) -> dict:
    return {"id": str(entry.id), "kind": entry.kind, "topic": entry.topic, "title": entry.title,
            "body": entry.body, "source": entry.source, "version": entry.version,
            "attributes": dict(entry.attributes),
            "product_id": str(entry.product_id) if entry.product_id else None}


def _result(status: str, items: list[dict] | None = None) -> dict:
    return {"status": status, "items": items or [], "method": METHOD}


def _rank(query: str, entries: list[tuple[KnowledgeEntry, int]]) -> list[tuple[KnowledgeEntry, int]]:
    # One shared bigram (e.g. inside an identifier) is not relevance: a candidate
    # needs lexical evidence or a third of the query's bigrams covered.
    normalized, terms, query_grams = _normalize(query), _terms(query), _grams(query)
    lexical, characters = [], []
    by_id = {str(entry.id): (entry, versions) for entry, versions in entries}
    for entry, _versions in entries:
        key = str(entry.id)
        text = _normalize(" ".join((entry.title, entry.body, entry.topic)))
        keywords = [_normalize(word) for word in entry.keywords if isinstance(word, str) and word.strip()]
        lex = sum(3 if term in _normalize(entry.title) else 1 for term in terms if term in text)
        lex += sum(4 for word in keywords if word in normalized)
        if normalized and normalized in text:
            lex += 5
        doc_grams = _grams(text + " " + " ".join(keywords))
        overlap = len(query_grams & doc_grams)
        similarity = overlap / max(1, len(query_grams | doc_grams))
        if lex:
            lexical.append((lex, key))
        if overlap and (lex or overlap / max(1, len(query_grams)) >= 1 / 3):
            characters.append((similarity, key))
    scores: dict[str, float] = defaultdict(float)
    for ranking in (lexical, characters):
        for rank, (_score, key) in enumerate(sorted(ranking, key=lambda item: (-item[0], item[1])), 1):
            scores[key] += 1 / (60 + rank)
    return [by_id[key] for key in sorted(scores, key=lambda key: (-scores[key], key))]


def search_knowledge(db: Session, query: str, now: datetime, *, product_id: UUID | None = None,
                     kinds: tuple[str, ...] | None = None, limit: int = 3) -> dict:
    """Fuse lexical and character-bigram ranks, citing only current public rows.

    At most 192 candidates and three citations by default are materialized. A
    topic/product conflict returns no citations, even if only one version matches
    the question. The bounded shortlist uses the same two signals as reranking.
    """
    _validate_now(now)
    _validate_id(product_id)
    if not isinstance(query, str) or len(query) > 2000:
        raise ValueError("Knowledge query must contain at most 2000 characters")
    if type(limit) is not int or not 1 <= limit <= 10:
        raise ValueError("Knowledge result limit must be between 1 and 10")
    if kinds is not None and (not isinstance(kinds, tuple) or not kinds or any(kind not in KINDS for kind in kinds)):
        raise ValueError("Unknown knowledge kind")
    if not query.strip():
        return _result("empty")
    entry, versions = _current(now)
    haystack = func.lower(entry.title + literal(" ") + entry.body + literal(" ") + entry.topic +
                          literal(" ") + cast(entry.keywords, Text))
    terms = _terms(query)
    signals = tuple(dict.fromkeys((*terms, *sorted(_grams(query))[:64])))
    if not signals:
        return _result("empty")
    matches = [haystack.like(_pattern(term), escape="\\") for term in signals]
    relevance = sum((case((match, 3 if signal in terms else 1), else_=0)
                     for signal, match in zip(signals, matches)), literal(0))
    statement = select(entry, versions).where(or_(*matches))
    if product_id is not None:
        statement = statement.where(entry.product_id == product_id)
    if kinds is not None:
        statement = statement.where(entry.kind.in_(kinds))
    rows = _read(db, statement.order_by(relevance.desc(), entry.id).limit(_MAX_CANDIDATES))
    ranked = _rank(query, [(row[0], row[1]) for row in rows])
    if any(count > 1 for _entry, count in ranked):
        return _result("conflict")
    return _result("ok", [_citation(item) for item, _count in ranked[:limit]]) if ranked else _result("empty")


def public_product_knowledge(db: Session, product_id: UUID, now: datetime) -> dict:
    _validate_now(now)
    _validate_id(product_id)
    if product_id is None:
        raise ValueError("Product identifier is required")
    entry, versions = _current(now)
    rows = _read(db, select(entry, versions).where(entry.product_id == product_id)
                 .order_by(entry.topic, entry.id).limit(_MAX_CANDIDATES + 1))
    if len(rows) > _MAX_CANDIDATES:
        raise CustomerServiceUnavailable("商品知识过多，请缩小范围")
    if any(row[1] > 1 for row in rows):
        return _result("conflict")
    return _result("ok", [_citation(row[0]) for row in rows]) if rows else _result("empty")


def _number(value: Any, *, maximum: str, positive: bool = False) -> Decimal:
    if type(value) not in (str, int, float, Decimal) or isinstance(value, bool):
        raise ValueError("Expected a finite number")
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Expected a finite number") from None
    if not number.is_finite() or number < 0 or number > Decimal(maximum) or (positive and not number):
        raise ValueError("Numeric value is outside the supported range")
    return number


def _preferences(text: str, preferences: dict | None) -> dict:
    if preferences is not None and not isinstance(preferences, dict):
        raise ValueError("Preferences must be an object")
    values = dict(preferences or {})
    result = {}
    # Both an upper budget and a min/max range are accepted. Unknown fields never
    # become product claims or identity hints.
    for key in ("budget", "budget_min", "budget_max"):
        if key in values and values[key] is not None:
            result[key] = _number(values[key], maximum="99999999.99")
    if "budget" in result:
        result.setdefault("budget_max", result.pop("budget"))
    budget_matches = [match for pattern in (
        r"(?:预算|不超过|不超|最多|低于|小于|以内)\s*[¥￥]?\s*([0-9]+(?:\.[0-9]{1,2})?)\s*(?:元|块)?",
        r"([0-9]+(?:\.[0-9]{1,2})?)\s*(?:元|块)?(?:以内|以下|左右)",
    ) for match in re.finditer(pattern, text)]
    if budget_matches:
        latest_budget = max(budget_matches, key=lambda match: match.start())
        result["budget_max"] = _number(latest_budget.group(1), maximum="99999999.99")
    if result.get("budget_min", 0) > result.get("budget_max", Decimal("99999999.99")):
        raise ValueError("Minimum budget exceeds maximum budget")
    categories = values.get("categories", [])
    if isinstance(categories, str):
        categories = [categories]
    if not isinstance(categories, (tuple, list)) or len(categories) > 6 or any(
            not isinstance(item, str) or not 1 <= len(item.strip()) <= 80 for item in categories):
        raise ValueError("Categories must contain at most six nonempty names")
    if categories:
        result["categories"] = list(dict.fromkeys(item.strip() for item in categories))
    occasion = values.get("occasion")
    if occasion is not None and (not isinstance(occasion, str) or len(occasion.strip()) > 100):
        raise ValueError("Occasion must contain at most 100 characters")
    if isinstance(occasion, str) and occasion.strip():
        result["occasion"] = occasion.strip()
    else:
        occasion_match = re.search(r"通勤|送礼|生日|出游|户外|家用|运动|办公|旅行|上班|春秋|夏天|冬天|远足", text)
        if occasion_match:
            result["occasion"] = occasion_match.group()
    return result


def _product_facts(product: Product) -> dict:
    return {"id": str(product.id), "name": product.name, "category": product.category,
            "price": str(product.price), "stock": product.stock, "is_listed": product.is_listed}


def _fit_requirements(text: str) -> list[tuple[str, str, tuple[str, ...]]]:
    requirements = []
    for field, title, groups in (
        ("skin_types", "适用肤质", (("敏感肌", "敏感性肌肤"), ("干皮", "干性", "干性肌肤"),
                               ("油皮", "油性", "油性肌肤"), ("混合肌", "混合性肌肤"), ("中性肌", "中性肌肤"))),
        ("skin_tones", "适用肤色", (("冷白皮", "冷调肤色"), ("暖黄皮", "暖调肤色"),
                               ("黄皮", "黄色肤色"), ("白皮", "白皙肤色"), ("深肤色", "深色肤色"))),
    ):
        matches = [(match.end(), len(alias), aliases) for aliases in groups
                   for alias in aliases for match in re.finditer(re.escape(alias), text)]
        if matches:
            # A later explicit preference replaces an earlier one in this conversation.
            _position, _length, aliases = max(matches, key=lambda item: (item[0], item[1]))
            requirements.append((field, title, aliases))
    return requirements


def recommend_products(db: Session, text: str, now: datetime, preferences: dict | None = None) -> dict:
    """Return up to three explainable suggestions, with at most two bounded reads.

    Catalog text supports discovery; authoritative attributes support additional
    explanations. Price/stock/listing always come from Product, never knowledge.
    Missing fit/ingredient facts are requested rather than guessed.
    """
    _validate_now(now)
    if not isinstance(text, str) or len(text) > 2000:
        raise ValueError("Recommendation request must be short text")
    prefs = _preferences(text, preferences)
    query = text + " " + prefs.get("occasion", "")
    terms = tuple(dict.fromkeys((*_terms(query), *sorted(_grams(query))[:48])))
    text_expression = func.lower(Product.name + literal(" ") + Product.description + literal(" ") + Product.category)
    catalog_matches = [text_expression.like(_pattern(term), escape="\\") for term in terms]
    authoritative_attributes = select(KnowledgeEntry.id).where(
        KnowledgeEntry.product_id == Product.id, *_active(now),
        or_(*(func.lower(cast(KnowledgeEntry.attributes, Text)).like(_pattern(term), escape="\\") for term in terms)),
    ).exists() if terms else literal(False)
    score = sum((case((match, 1), else_=0) for match in catalog_matches), literal(0))
    statement = select(Product).where(Product.is_listed.is_(True), Product.stock > 0)
    if "budget_min" in prefs:
        statement = statement.where(Product.price >= prefs["budget_min"])
    if "budget_max" in prefs:
        statement = statement.where(Product.price <= prefs["budget_max"])
    if prefs.get("categories"):
        statement = statement.where(Product.category.in_(prefs["categories"]))
    elif catalog_matches:
        statement = statement.where(or_(*catalog_matches, authoritative_attributes))
    elif not any(key in prefs for key in ("budget_min", "budget_max")):
        return {"items": [], "needs": ["请提供想买的商品分类、用途或预算"], "based_on": []}
    rows = _read(db, statement.order_by(score.desc(), Product.listed_at.desc(), Product.id)
                 .limit(_MAX_PRODUCT_CANDIDATES))
    products = [row[0] for row in rows]
    if not products:
        return {"items": [], "needs": ["当前未找到符合条件的在售有货商品，请调整分类、用途或预算"],
                "based_on": ["当前在售商品目录"]}
    entry, versions = _current(now)
    knowledge_rows = _read(db, select(entry, versions).where(entry.product_id.in_([product.id for product in products]))
                           .order_by(entry.product_id, entry.topic, entry.id).limit(_MAX_CANDIDATES + 1))
    if len(knowledge_rows) > _MAX_CANDIDATES:
        raise CustomerServiceUnavailable("候选商品知识过多，请缩小分类")
    by_product: dict[str, list[dict]] = defaultdict(list)
    conflicted = set()
    for item, count in knowledge_rows:
        if count > 1:
            conflicted.add(str(item.product_id))
        else:
            by_product[str(item.product_id)].append(_citation(item))
    ranked = []
    needs = []
    fit_requirements = _fit_requirements(text)
    for product in products:
        key = str(product.id)
        if key in conflicted:
            needs.append("部分商品知识存在当前版本冲突，暂不据此推荐")
            continue
        citations = by_product[key]
        fit_reasons = []
        for field, title, aliases in fit_requirements:
            values = [value for citation in citations
                      for value in _attribute_values(citation["attributes"].get(field, []))]
            if not any(_normalize(value) == _normalize(alias) for value in values for alias in aliases):
                needs.append("只推荐有已发布" + title + "依据的商品；当前部分候选缺少匹配资料")
                break
            fit_reasons.append("已发布商品知识的" + title + "包含：" + aliases[0])
        if len(fit_reasons) != len(fit_requirements):
            continue
        catalog = _normalize(product.name + " " + product.description + " " + product.category)
        matches = [term for term in _terms(query) if term in catalog]
        grams = len(_grams(query) & _grams(catalog))
        reasons = list(fit_reasons)
        if prefs.get("categories") or product.category in text:
            reasons.append("在售分类：" + product.category)
        if matches or grams:
            reasons.append("商品目录名称、描述或分类与需求相符")
        if "budget_max" in prefs:
            reasons.append("当前价格 " + str(product.price) + " 元，不超过预算 " + str(prefs["budget_max"]) + " 元")
        occasion = prefs.get("occasion")
        attribute_match = False
        attribute_values = " ".join(value for citation in citations
                                    for value in _attribute_values(citation["attributes"]))
        if occasion:
            # Match values, never keys: a field named sensitive_skin alone is
            # not evidence that a product suits sensitive skin.
            if _normalize(occasion) in _normalize(attribute_values):
                reasons.append("已发布商品知识记录的用途：" + occasion)
                attribute_match = True
            if _normalize(occasion) in catalog:
                reasons.append("商品目录描述提到的用途：" + occasion)
        attribute_terms = [term for term in _terms(query) if term in _normalize(attribute_values)]
        if attribute_terms and not attribute_match:
            reasons.append("已发布商品属性与需求关键词相符")
        if not prefs.get("categories") and not matches and not grams and not attribute_terms:
            # SQL's bounded shortlist may match a JSON key or punctuation. Such a
            # match cannot explain a recommendation to the buyer.
            continue
        ranked.append((len(matches) * 4 + grams + len(attribute_terms) * 4 + (8 if attribute_match else 0), product,
                       reasons or ["当前在售且有可售库存"], citations))
    ranked.sort(key=lambda row: (-row[0], str(row[1].id)))
    items: list[dict] = [{"product": _product_facts(product), "reasons": reasons, "knowledge": citations}
                        for _score, product, reasons, citations in ranked[:3]]
    if re.search(r"尺码|身高|体重|胸围|腰围", text) and not any(
            citation["attributes"].get("size_chart") for item in items for citation in item["knowledge"]):
        needs.append("缺少当前有效尺码表，请补充权威尺码资料后确认")
    if re.search(r"成分|敏感肌|肤质|过敏", text) and not any(
            set(citation["attributes"]) & {"ingredients", "skin_types", "skin_suitability"}
            for item in items for citation in item["knowledge"]):
        needs.append("缺少已发布的成分或适用肤质依据，暂无法确认适用性")
    based_on = ["当前在售商品目录"]
    if any(item["knowledge"] for item in items):
        based_on.append("当前有效的已发布商品知识")
    return {"items": items, "needs": list(dict.fromkeys(needs)), "based_on": based_on}


def faq_hints(session: Session, now: datetime, limit: int = 5) -> list[dict]:
    """Current FAQ titles for the entry quick panel: no bodies, no product data."""
    _validate_now(now)
    bounded = min(max(int(limit), 1), 5)
    entry, versions = _current(now)
    rows = _read(session, select(entry, versions).where(entry.kind == "faq")
                 .order_by(entry.updated_at.desc(), entry.id).limit(bounded * 4))
    hints: list[dict] = []
    seen: set[str] = set()
    for row, count in rows:
        if count > 1 or row.topic in seen:
            continue
        seen.add(row.topic)
        hints.append({"topic": row.topic, "title": row.title})
        if len(hints) == bounded:
            break
    return hints


def _attribute_values(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _attribute_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _attribute_values(item)


def _verified_citations(knowledge: list[dict]) -> list[dict]:
    """Pure helpers accept only citations already checked by retrieval this turn."""
    if not isinstance(knowledge, list) or len(knowledge) > _MAX_CANDIDATES:
        raise ValueError("Expected a bounded list of verified citations")
    keys = {"id", "kind", "topic", "title", "body", "source", "version", "attributes", "product_id"}
    for citation in knowledge:
        if not isinstance(citation, dict) or set(citation) != keys or not isinstance(citation["attributes"], dict):
            raise ValueError("Expected verified knowledge citations")
    return knowledge


def _citation_conflict(citations: list[dict]) -> bool:
    seen = {}
    for citation in citations:
        key = (citation["topic"], citation["product_id"])
        if key in seen and seen[key] != citation["id"]:
            return True
        seen[key] = citation["id"]
    return False


_MEASUREMENTS = {"height_cm": "250", "weight_kg": "400", "chest_cm": "250", "waist_cm": "250"}
_MEASUREMENT_LABELS = {"height_cm": "身高（厘米）", "weight_kg": "体重（公斤）",
                       "chest_cm": "胸围（厘米）", "waist_cm": "腰围（厘米）"}


def validate_product_attributes(attributes: dict) -> dict:
    """Reject unusable operational data when it is published, before a buyer asks."""
    if "size_chart" not in attributes:
        return attributes
    chart = attributes["size_chart"]
    if not isinstance(chart, dict) or not 1 <= len(chart) <= 30:
        raise ValueError('尺码表须为对象，例如 {"M":{"height_cm":[160,170],"weight_kg":[50,60]}}')
    for label, dimensions in chart.items():
        if not isinstance(label, str) or not 1 <= len(label.strip()) <= 40 or not isinstance(dimensions, dict) or not dimensions:
            raise ValueError("每个尺码须有名称和测量范围")
        for key, interval in dimensions.items():
            if key not in _MEASUREMENTS or not isinstance(interval, list) or len(interval) != 2:
                raise ValueError("尺码范围使用 height_cm、weight_kg、chest_cm 或 waist_cm，每项为 [下限,上限]")
            lower, upper = (_number(value, maximum=_MEASUREMENTS[key], positive=True) for value in interval)
            if lower > upper:
                raise ValueError("尺码范围下限不能高于上限")
    return attributes


def parse_measurements(text: str) -> dict[str, float]:
    """Only explicit units are accepted; numbers without cm/kg/斤 are ambiguous."""
    result = {}
    for key, label in (("height_cm", "身高"), ("chest_cm", "胸围"), ("waist_cm", "腰围")):
        pattern = rf"{label}\s*(\d{{2,3}}(?:\.\d)?)\s*(?:厘米|cm)"
        match = re.search(pattern, text, re.I)
        if key == "height_cm" and not match:
            match = re.search(r"(?<![\d.])(1[0-9]{2}|2[0-2][0-9])\s*(?:厘米|cm)", text, re.I)
        if match and 0 < float(match.group(1)) <= float(_MEASUREMENTS[key]):
            result[key] = float(match.group(1))
    weight = re.search(r"(?:体重\s*)?(?<![\d.])(\d{2,3}(?:\.\d)?)\s*(公斤|千克|kg|斤)", text, re.I)
    if weight:
        value = float(weight.group(1)) / (2 if weight.group(2) == "斤" else 1)
        if 0 < value <= float(_MEASUREMENTS["weight_kg"]):
            result["weight_kg"] = value
    return result


def explain_size(knowledge: list[dict], measurements: dict | None = None) -> dict:
    """Explain one product's verified size_chart; measurements use cm and kg.

    Chart format: {"M": {"height_cm": [160, 170], "weight_kg": [50, 60]}}.
    A size is suggested only when every chart dimension was provided and matched.
    These are chart matches, never guarantees of fit.
    """
    citations = _verified_citations(knowledge)
    if measurements is not None and not isinstance(measurements, dict):
        raise ValueError("Measurements must be an object")
    if any(key not in _MEASUREMENTS for key in (measurements or {})):
        raise ValueError("Unsupported measurement; use explicit cm/kg fields")
    measured = {key: _number(value, maximum=_MEASUREMENTS[key], positive=True)
                for key, value in (measurements or {}).items()}
    result = {"status": "empty", "sizes": [], "recommendations": [], "needs": [], "citations": []}
    if _citation_conflict(citations):
        return {**result, "status": "conflict", "needs": ["当前尺码知识存在版本冲突"]}
    charts = [citation for citation in citations if citation["attributes"].get("size_chart")]
    if not charts:
        return {**result, "needs": ["暂无当前有效尺码表，不能根据身高体重推测尺码"]}
    if len({citation["product_id"] for citation in charts}) != 1:
        return {**result, "status": "conflict", "needs": ["请先明确一个商品再确认尺码"]}
    labels = {}
    for citation in charts:
        chart = citation["attributes"]["size_chart"]
        if not isinstance(chart, dict) or len(chart) > 30:
            return {**result, "needs": ["已发布尺码资料缺少可核验的范围"]}
        for label, dimensions in chart.items():
            if not isinstance(label, str) or not 1 <= len(label) <= 40 or not isinstance(dimensions, dict) or not dimensions:
                return {**result, "needs": ["已发布尺码资料格式无法确认"]}
            bounds = {}
            try:
                for key, interval in dimensions.items():
                    if key not in _MEASUREMENTS or not isinstance(interval, list) or len(interval) != 2:
                        raise ValueError
                    lower, upper = (_number(value, maximum=_MEASUREMENTS[key], positive=True) for value in interval)
                    if lower > upper:
                        raise ValueError
                    bounds[key] = [float(lower), float(upper)]
            except ValueError:
                return {**result, "needs": ["已发布尺码范围无法确认"]}
            if label in labels and labels[label] != bounds:
                return {**result, "status": "conflict", "needs": ["不同尺码依据对同一码数记录不一致"]}
            labels[label] = bounds
    needed = set()
    recommendations = []
    for label, bounds in labels.items():
        needed.update(set(bounds) - set(measured))
        if all(key in measured and Decimal(str(interval[0])) <= measured[key] <= Decimal(str(interval[1]))
               for key, interval in bounds.items()):
            recommendations.append("已发布尺码表范围匹配 " + label + "，实际穿着需结合版型确认")
    return {"status": "ok", "sizes": [{"label": label, "measurements": bounds} for label, bounds in labels.items()],
            "recommendations": recommendations,
            "needs": ["请补充 " + _MEASUREMENT_LABELS[key] + "（" + key + "）" for key in sorted(needed)] or
                     (["提供的尺寸未匹配尺码表范围，请核实测量或咨询客服"] if measured and not recommendations else []),
            "citations": charts}


def explain_comparison(products: list[dict], knowledge: list[dict]) -> dict:
    """Compare two or three already verified six-field public product facts."""
    citations = _verified_citations(knowledge)
    required = {"id", "name", "category", "price", "stock", "is_listed"}
    if not isinstance(products, list) or not 2 <= len(products) <= 3 or any(
            not isinstance(product, dict) or set(product) != required or product["is_listed"] is not True
            for product in products):
        raise ValueError("Compare two or three verified public products")
    ids = [product["id"] for product in products]
    if len(set(ids)) != len(ids):
        raise ValueError("Comparison products must be distinct")
    selected = [citation for citation in citations if citation["product_id"] in ids]
    if _citation_conflict(selected):
        return {"status": "conflict", "items": [], "differences": [], "needs": ["商品知识存在当前版本冲突"]}
    items, needs = [], []
    for product in products:
        relevant = [citation for citation in selected if citation["product_id"] == product["id"]]
        attributes = {}
        for citation in relevant:
            for key, value in citation["attributes"].items():
                if key in attributes and attributes[key] != value:
                    return {"status": "conflict", "items": [], "differences": [], "needs": ["商品属性依据不一致"]}
                attributes[key] = value
        # Catalog facts cannot be overwritten by an attribute named price/stock.
        attributes = {key: value for key, value in attributes.items() if key not in required}
        items.append({"product": dict(product), "attributes": attributes, "citations": relevant})
        if not relevant:
            needs.append(product["name"] + " 缺少当前有效属性资料，仅可比较目录事实")
    fields = ["category", "price", "stock"] + sorted({key for item in items for key in item["attributes"]})
    differences = []
    for field in fields:
        values = {item["product"]["id"]: item["product"][field] if field in required else item["attributes"].get(field)
                  for item in items}
        if len({json.dumps(value, ensure_ascii=False, sort_keys=True) for value in values.values()}) > 1:
            differences.append({"attribute": field, "values": values})
    return {"status": "ok", "items": items, "differences": differences, "needs": needs}
