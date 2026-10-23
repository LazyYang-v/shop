"""Synthetic-only policy authority boundary.

The synthetic registry is the only source of citable policy facts. A separate
synthetic index mirrors a retrieval service: it can still contain withdrawn,
future or deleted residue, and its text is never treated as authoritative.
No WeKnora endpoint, token, network client or real mall policy exists here.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
import hashlib
import hmac
import json
from pathlib import Path
import re
from uuid import UUID

SYNTHETIC_LABEL = "虚构演示政策（非真实商城政策）"
SYNTHETIC_POLICY_KB = "synthetic-demo-kb"
_SOURCE_REF = re.compile(r"synthetic://[a-z0-9][a-z0-9/_-]{0,160}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


class PolicyPublicationError(ValueError):
    """The registration itself is invalid; nothing may be published."""


@dataclass(frozen=True)
class PolicyRecord:
    policy_id: str
    version: int
    scope_key: str
    source_label: str
    source_ref: str
    effective_from: datetime
    effective_to: datetime | None
    status: str
    knowledge_base_id: str
    knowledge_id: str
    canonical_content: str
    content_sha256: str

    def active_at(self, now: datetime) -> bool:
        return (self.status == "active"
                and self.effective_from <= now
                and (self.effective_to is None or now < self.effective_to))


@dataclass(frozen=True)
class IndexDocument:
    knowledge_base_id: str
    knowledge_id: str
    title: str
    text: str
    source_type: str = "synthetic_mall_policy"


@dataclass(frozen=True)
class ResearchArticle:
    knowledge_base_id: str
    knowledge_id: str
    title: str
    text: str
    source_label: str


@dataclass(frozen=True)
class PolicySearchResult:
    policy_documents: tuple[IndexDocument, ...]
    research_documents: tuple[ResearchArticle, ...]


class PolicyRegistry:
    def __init__(self, records: tuple[PolicyRecord, ...]):
        self._records = tuple(records)
        self._by_document = {(record.knowledge_base_id, record.knowledge_id): record
                             for record in records}
        self._by_key = {(record.policy_id, record.version): record for record in records}
        if len(self._by_document) != len(records) or len(self._by_key) != len(records):
            raise PolicyPublicationError("Policy identity and index mapping must be unique")
        _validate_publication(self._records)

    def lookup(self, knowledge_base_id: str, knowledge_id: str) -> PolicyRecord | None:
        return self._by_document.get((knowledge_base_id, knowledge_id))

    def records_for_scope(self, scope_key: str) -> tuple[PolicyRecord, ...]:
        return tuple(record for record in self._records if record.scope_key == scope_key)

    def withdraw(self, policy_id: str, version: int) -> None:
        key = (policy_id, version)
        record = self._by_key.get(key)
        if record is None:
            raise PolicyPublicationError("Unknown policy version")
        withdrawn = replace(record, status="withdrawn")
        self._records = tuple(withdrawn if item is record else item for item in self._records)
        self._by_key[key] = withdrawn
        self._by_document[(withdrawn.knowledge_base_id, withdrawn.knowledge_id)] = withdrawn

    def assert_deliverable(self, record: PolicyRecord, now: datetime) -> None:
        current = self._by_key.get((record.policy_id, record.version))
        if (current is None or current != record or not current.active_at(now)
                or not hmac.compare_digest(
                    hashlib.sha256(current.canonical_content.encode()).hexdigest(),
                    current.content_sha256)):
            raise PolicyPublicationError("Citation is no longer current")


class SyntheticPolicyIndex:
    """Deterministic in-process stand-in for the retrieval index. Never WeKnora."""

    def __init__(self, knowledge_base_id: str, documents: tuple[IndexDocument, ...],
                 research: tuple[ResearchArticle, ...]):
        self.knowledge_base_id = knowledge_base_id
        self._documents = documents
        self._research = research

    def search(self, question: str, scope_key: str | None = None, limit: int = 5) -> PolicySearchResult:
        signals = _SCOPE_SIGNALS.get(scope_key, ()) if scope_key else ()
        return PolicySearchResult(
            policy_documents=tuple(sorted(
                (document for document in self._documents
                 if (not signals or any(signal in document.title + document.text for signal in signals))
                 and _score(question, document.title, document.text) > 0),
                key=lambda document: (-_score(question, document.title, document.text), document.knowledge_id),
            )[:limit]),
            research_documents=tuple(sorted(
                (article for article in self._research
                 if (not signals or any(signal in article.title + article.text for signal in signals))
                 and _score(question, article.title, article.text) > 0),
                key=lambda article: (-_score(question, article.title, article.text), article.knowledge_id),
            )[:limit]),
        )


_SCOPE_SIGNALS = {
    "demo_shipping": ("发货", "发出", "发货时限", "发货时间"),
    "demo_free_shipping": ("包邮", "邮费", "包邮门槛"),
    "demo_price_protection": ("价格保护", "价保"),
    "demo_gift_packaging": ("礼品包装", "包装"),
}


def _score(question: str, title: str, text: str) -> int:
    normalized = "".join(question.split()).casefold()
    haystack = (title + text).casefold()
    grams = {normalized[index:index + 2] for index in range(max(0, len(normalized) - 1))}
    return sum(1 for gram in grams if gram in haystack)


def _timestamp(value, *, nullable: bool = False) -> datetime | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise PolicyPublicationError("Policy time must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise PolicyPublicationError("Policy time must be an ISO-8601 string") from None
    if parsed.utcoffset() is None:
        raise PolicyPublicationError("Policy time must include an offset")
    return parsed.astimezone(UTC)


def _parse_record(value) -> PolicyRecord:
    keys = {"policy_id", "version", "scope_key", "source_label", "source_ref", "effective_from",
            "effective_to", "status", "knowledge_base_id", "knowledge_id", "canonical_content",
            "content_sha256"}
    if not isinstance(value, dict) or set(value) != keys:
        raise PolicyPublicationError("Policy registration has an invalid shape")
    try:
        policy_id = str(UUID(value["policy_id"]))
    except (TypeError, ValueError):
        raise PolicyPublicationError("Policy identifier must be a UUID") from None
    if policy_id != value["policy_id"]:
        raise PolicyPublicationError("Policy identifier must be canonical")
    if type(value["version"]) is not int or value["version"] < 1:
        raise PolicyPublicationError("Policy version must be a positive integer")
    if not isinstance(value["scope_key"], str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value["scope_key"]):
        raise PolicyPublicationError("Policy scope is invalid")
    if not isinstance(value["source_label"], str) or not 1 <= len(value["source_label"]) <= 160:
        raise PolicyPublicationError("Policy source label is invalid")
    if not isinstance(value["source_ref"], str) or not _SOURCE_REF.fullmatch(value["source_ref"]):
        raise PolicyPublicationError("Only synthetic policy sources are allowed")
    effective_from = _timestamp(value["effective_from"])
    assert effective_from is not None
    effective_to = _timestamp(value["effective_to"], nullable=True)
    if effective_to is not None and effective_to <= effective_from:
        raise PolicyPublicationError("Policy effective interval is empty")
    if value["status"] not in {"active", "withdrawn"}:
        raise PolicyPublicationError("Policy status is invalid")
    if not isinstance(value["knowledge_base_id"], str) or not _IDENTIFIER.fullmatch(value["knowledge_base_id"]):
        raise PolicyPublicationError("Policy knowledge base is invalid")
    if not isinstance(value["knowledge_id"], str) or not _IDENTIFIER.fullmatch(value["knowledge_id"]):
        raise PolicyPublicationError("Policy knowledge identifier is invalid")
    content = value["canonical_content"]
    digest = value["content_sha256"]
    if not isinstance(content, str) or not 1 <= len(content) <= 4000:
        raise PolicyPublicationError("Policy canonical content is invalid")
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise PolicyPublicationError("Policy content digest is invalid")
    if not hmac.compare_digest(hashlib.sha256(content.encode()).hexdigest(), digest):
        raise PolicyPublicationError("Policy canonical content does not match its digest")
    return PolicyRecord(policy_id, value["version"], value["scope_key"], value["source_label"],
                        value["source_ref"], effective_from, effective_to, value["status"],
                        value["knowledge_base_id"], value["knowledge_id"], content, digest)


def _parse_document(value) -> IndexDocument:
    keys = {"knowledge_base_id", "knowledge_id", "title", "text", "source_type"}
    if not isinstance(value, dict) or set(value) != keys:
        raise PolicyPublicationError("Policy index document has an invalid shape")
    if value["source_type"] != "synthetic_mall_policy":
        raise PolicyPublicationError("Only synthetic mall-policy documents enter the policy index")
    if (not isinstance(value["knowledge_base_id"], str) or not _IDENTIFIER.fullmatch(value["knowledge_base_id"])
            or not isinstance(value["knowledge_id"], str) or not _IDENTIFIER.fullmatch(value["knowledge_id"])
            or not isinstance(value["title"], str) or not 1 <= len(value["title"]) <= 200
            or not isinstance(value["text"], str) or not 1 <= len(value["text"]) <= 4000):
        raise PolicyPublicationError("Policy index document is invalid")
    return IndexDocument(value["knowledge_base_id"], value["knowledge_id"], value["title"], value["text"])


def _parse_research(value) -> ResearchArticle:
    keys = {"knowledge_base_id", "knowledge_id", "title", "text", "source_label"}
    if not isinstance(value, dict) or set(value) != keys:
        raise PolicyPublicationError("Research article has an invalid shape")
    if (not isinstance(value["knowledge_base_id"], str) or not _IDENTIFIER.fullmatch(value["knowledge_base_id"])
            or not isinstance(value["knowledge_id"], str) or not _IDENTIFIER.fullmatch(value["knowledge_id"])
            or not isinstance(value["title"], str) or not 1 <= len(value["title"]) <= 200
            or not isinstance(value["text"], str) or not 1 <= len(value["text"]) <= 4000
            or not isinstance(value["source_label"], str) or not 1 <= len(value["source_label"]) <= 160):
        raise PolicyPublicationError("Research article is invalid")
    return ResearchArticle(value["knowledge_base_id"], value["knowledge_id"], value["title"],
                           value["text"], value["source_label"])


def _validate_publication(records: tuple[PolicyRecord, ...]) -> None:
    identities = set()
    documents = set()
    for record in records:
        identity = (record.policy_id, record.version)
        document = (record.knowledge_base_id, record.knowledge_id)
        if identity in identities or document in documents:
            raise PolicyPublicationError("Policy identity and index mapping must be unique")
        identities.add(identity)
        documents.add(document)
    active = [record for record in records if record.status == "active"]
    for index, left in enumerate(active):
        for right in active[index + 1:]:
            if left.scope_key != right.scope_key:
                continue
            left_end = left.effective_to
            right_end = right.effective_to
            if ((left_end is None or right.effective_from < left_end)
                    and (right_end is None or left.effective_from < right_end)):
                raise PolicyPublicationError("Active policy intervals overlap in one scope")


def load_policy_data(data) -> tuple[PolicyRegistry, SyntheticPolicyIndex]:
    if not isinstance(data, dict) or set(data) != {"synthetic", "label", "knowledge_base_id",
                                                    "policies", "policy_index", "research_articles"}:
        raise PolicyPublicationError("Policy fixture has an invalid shape")
    if data["synthetic"] is not True or data["label"] != SYNTHETIC_LABEL:
        raise PolicyPublicationError("Only clearly labelled synthetic policies are accepted")
    knowledge_base_id = data["knowledge_base_id"]
    if knowledge_base_id != SYNTHETIC_POLICY_KB:
        raise PolicyPublicationError("Policy fixture must use the synthetic knowledge base")
    if not isinstance(data["policies"], list) or not data["policies"]:
        raise PolicyPublicationError("Policy fixture must contain registrations")
    if not isinstance(data["policy_index"], list) or not isinstance(data["research_articles"], list):
        raise PolicyPublicationError("Policy fixture collections are invalid")
    records = tuple(_parse_record(value) for value in data["policies"])
    documents = tuple(_parse_document(value) for value in data["policy_index"])
    research = tuple(_parse_research(value) for value in data["research_articles"])
    if any(record.knowledge_base_id != knowledge_base_id for record in records):
        raise PolicyPublicationError("Registration knowledge base does not match the fixture")
    if any(document.knowledge_base_id != knowledge_base_id for document in documents):
        raise PolicyPublicationError("Index document is outside the approved knowledge base")
    if any(article.knowledge_base_id == knowledge_base_id for article in research):
        raise PolicyPublicationError("External research must not enter the policy knowledge base")
    indexed = {(document.knowledge_base_id, document.knowledge_id) for document in documents}
    for record in records:
        if record.status == "active" and (record.knowledge_base_id, record.knowledge_id) not in indexed:
            raise PolicyPublicationError("Active policy has no verified index document")
    return PolicyRegistry(records), SyntheticPolicyIndex(knowledge_base_id, documents, research)


def load_synthetic_policy_fixture(path: str, expected_sha256: str) -> tuple[PolicyRegistry, SyntheticPolicyIndex]:
    try:
        fixture = Path(path)
        if fixture.is_symlink() or not fixture.is_file() or fixture.stat().st_size > 128 * 1024:
            raise PolicyPublicationError("Policy fixture is unavailable")
        raw = fixture.read_bytes()
        if (not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
                or not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), expected_sha256)):
            raise PolicyPublicationError("Policy fixture digest does not match")
        data = json.loads(raw)
    except PolicyPublicationError:
        raise
    except Exception:
        raise PolicyPublicationError("Policy fixture is invalid") from None
    return load_policy_data(data)


@dataclass(frozen=True)
class PolicyAnswer:
    status: str
    code: str | None
    reply: str
    citations: tuple[dict, ...]


_POLICY_TEXT_MARKERS = ("政策", "发货", "包邮", "价保", "价格保护", "礼品包装")

_SCOPE_PATTERNS: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = (
    ("demo_shipping", (
        re.compile(r"(?:请问)?演示商城(?:一般|通常)?(?:多久|多长时间)(?:发货|发出)(?:呢)?[？?。]?"),
        re.compile(r"(?:请问)?演示商城的?发货(?:时间|时限)(?:是多久|是多长时间|多久)?(?:呢)?[？?。]?"),
    )),
    ("demo_free_shipping", (
        re.compile(r"(?:请问)?演示商城(?:满多少|多少钱|怎样|怎么)(?:才)?包邮(?:呢)?[？?。]?"),
        re.compile(r"(?:请问)?演示商城的?包邮(?:门槛|规则|政策)(?:是多少|是什么|多少)?(?:呢)?[？?。]?"),
    )),
    ("demo_price_protection", (
        re.compile(r"(?:请问)?演示商城的?价格保护(?:期限|政策|规则)?(?:是多久|是什么|多久)?(?:呢)?[？?。]?"),
        re.compile(r"(?:请问)?演示商城(?:可以|能)价保(?:吗|多久)(?:呢)?[？?。]?"),
    )),
    ("demo_gift_packaging", (
        re.compile(r"(?:请问)?演示商城的?礼品包装(?:政策|规则)?(?:是什么|有哪些)?(?:呢)?[？?。]?"),
    )),
)


def understand_policy_scope(text: str) -> str | None:
    sentence = "".join(text.split())
    for scope_key, patterns in _SCOPE_PATTERNS:
        if any(pattern.fullmatch(sentence) for pattern in patterns):
            return scope_key
    return None


def looks_like_policy_question(text: str) -> bool:
    sentence = "".join(text.split())
    return any(marker in sentence for marker in _POLICY_TEXT_MARKERS)


def _unavailable(reply: str) -> PolicyAnswer:
    return PolicyAnswer("unavailable", "policy_unavailable", reply, ())


def _citation(record: PolicyRecord) -> dict:
    return {
        "policy_id": record.policy_id,
        "version": record.version,
        "source_label": record.source_label,
        "source_ref": record.source_ref,
        "effective_from": record.effective_from.isoformat(),
        "effective_to": record.effective_to.isoformat() if record.effective_to else None,
        "content": record.canonical_content,
        "content_sha256": record.content_sha256,
        "synthetic": True,
        "label": SYNTHETIC_LABEL,
    }


def _reply(record: PolicyRecord) -> str:
    until = record.effective_to.isoformat() if record.effective_to else "长期"
    return (f"{record.canonical_content}\n依据：{record.source_label}，版本 v{record.version}，"
            f"生效期 {record.effective_from.isoformat()} 至 {until}（{SYNTHETIC_LABEL}）。")


def answer_policy_question(text: str, registry: PolicyRegistry | None,
                           index: SyntheticPolicyIndex | None, now: datetime) -> PolicyAnswer | None:
    """Return None when the text is not a policy question at all.

    The registry is authoritative. Index text is only used to locate candidate
    document identities; it never supplies the answer or citation body.
    """
    if registry is None or index is None:
        if looks_like_policy_question(text):
            return _unavailable("政策和检索服务暂不可用。")
        return None
    scope_key = understand_policy_scope(text)
    if scope_key is None:
        if looks_like_policy_question(text):
            return PolicyAnswer("needs_clarification", None,
                                "暂无法确定适用的政策主题或条件，请补充具体问题。", ())
        return None

    active = tuple(record for record in registry.records_for_scope(scope_key) if record.active_at(now))
    if len(active) > 1:
        return PolicyAnswer("conflict", "policy_conflict", "当前政策依据存在冲突，暂无法确认。", ())

    try:
        result = index.search(text, scope_key)
    except Exception:
        return _unavailable("政策和检索服务暂不可用。")

    qualified: dict[tuple[str, int], PolicyRecord] = {}
    stale_candidate_seen = False
    for document in result.policy_documents:
        record = registry.lookup(document.knowledge_base_id, document.knowledge_id)
        if record is None:
            stale_candidate_seen = True
            continue
        if record.scope_key != scope_key:
            continue
        if not record.active_at(now):
            stale_candidate_seen = True
            continue
        qualified[(record.policy_id, record.version)] = record
    if len(qualified) > 1:
        return PolicyAnswer("conflict", "policy_conflict", "当前政策依据存在冲突，暂无法确认。", ())
    if not qualified:
        if stale_candidate_seen:
            return _unavailable("相关依据已失效或待维护，暂无法确认。")
        if active:
            return _unavailable("当前登记依据未能通过检索确认，暂无法确认。")
        reply = "未检索到足够相关的政策依据。"
        if result.research_documents:
            reply += "仅找到标注为非商城政策的研究资料，不能作为商城政策依据。"
        return PolicyAnswer("no_match", "policy_no_match", reply, ())

    record = next(iter(qualified.values()))
    try:
        registry.assert_deliverable(record, now)
    except PolicyPublicationError:
        return _unavailable("相关依据已失效或待维护，暂无法确认。")
    return PolicyAnswer("ok", None, _reply(record), (_citation(record),))
