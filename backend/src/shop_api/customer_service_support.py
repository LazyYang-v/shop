"""Persisted support cases, review workflows and consented buyer preferences.

Conversation context expires with its consultation. Cases retain a redacted,
minimal handoff for 30 days; neither a case nor a review moves money.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import re
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import DateTime, ForeignKey, String, Uuid, delete, select, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from shop_api.database import Base
from shop_api.identity import User
from shop_api.orders import Order


class SupportContext(Base):
    __tablename__ = "customer_service_contexts"

    consultation_id: Mapped[UUID] = mapped_column(
        ForeignKey("customer_service_consultations.id", ondelete="CASCADE"), primary_key=True)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SupportCase(Base):
    __tablename__ = "customer_service_cases"
    __table_args__ = (UniqueConstraint("buyer_id", "request_key", name="uq_cs_case_request"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    buyer_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    request_key: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    order_id: Mapped[UUID | None] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"))
    assigned_to: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    messages: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class SupportPreference(Base):
    __tablename__ = "customer_service_preferences"

    buyer_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class SupportEvent(Base):
    __tablename__ = "customer_service_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    consultation_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    buyer_id: Mapped[UUID | None] = mapped_column(Uuid)
    case_id: Mapped[UUID | None] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class SupportChannel(Base):
    __tablename__ = "customer_service_channels"

    name: Mapped[str] = mapped_column(String(24), primary_key=True)
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SupportNotification(Base):
    __tablename__ = "customer_service_notifications"
    __table_args__ = (UniqueConstraint("buyer_id", "source_key", name="uq_cs_notification_source"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    buyer_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source_key: Mapped[str] = mapped_column(String(160), nullable=False)
    text: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


REQUEST_KINDS = {
    "human_handoff": "人工交接", "shipping_reminder": "催发货", "address_change": "修改收货地址",
    "invoice": "发票申请", "return": "退货申请", "exchange": "换货申请", "refund": "退款申请",
    "missing": "少件处理", "damage": "破损处理", "wrong_item": "发错货处理", "warranty": "质保查询",
    "replacement": "补发登记", "compensation": "补偿协商", "complaint": "投诉处理",
}
ORDER_REQUESTS = set(REQUEST_KINDS) - {"human_handoff", "complaint"}
CASE_STATUSES = {"open", "in_progress", "waiting_buyer", "resolved", "rejected"}
CHANNELS = ("storefront", "taobao", "jd", "douyin", "pinduoduo")


def redact_text(text: str, limit: int = 1200) -> str:
    """Reduce accidental contact/credential collection in case and memory text."""
    value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[邮箱已隐藏]", text)
    value = re.sub(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)", "[电话已隐藏]", value)
    value = re.sub(r"(?<!\d)\d{15,19}(?!\d)", "[长号码已隐藏]", value)
    value = re.sub(r"(?i)(密码|password|token|密钥|验证码)\s*[:：=]?\s*\S+", r"\1[已隐藏]", value)
    # Addresses belong in the saved-address workflow, never in chat context.
    if re.search(r"(?:收货地址|详细地址|新地址|我住在)\s*[:：是为]?", value):
        value = re.sub(r"(?:收货地址|详细地址|新地址|我住在)\s*[:：是为]?.*", "地址信息请通过商城地址簿选择", value)
    return value[:limit]


def context_for(db: Session, consultation_id: UUID, now: datetime) -> SupportContext:
    row = db.get(SupportContext, consultation_id)
    if row is None:
        row = SupportContext(consultation_id=consultation_id, data={}, updated_at=now)
        db.add(row)
    return row


def remember_turn(context: SupportContext, *, user_text: str, reply: str, decision,
                  now: datetime, facts: list[dict] | None = None) -> None:
    data = dict(context.data)
    history = list(data.get("history", []))
    history.extend([{"role": "user", "text": redact_text(user_text, 600)},
                    {"role": "assistant", "text": redact_text(reply, 1200)}])
    data.update(history=history[-16:], last_intent=decision.intent, last_task=decision.task,
                last_emotion=decision.emotion)
    if facts:
        data["facts"] = facts[-8:]
    context.data, context.updated_at = data, now


def record_event(db: Session, now: datetime, kind: str, *, consultation_id=None,
                 buyer_id=None, case_id=None, **data) -> None:
    # Callers supply typed classifications/counts, never raw conversation text.
    allowed = {"role", "intent", "emotion", "path", "task", "status", "source", "hit", "success",
               "rating", "resolved", "reason", "version", "action", "from_status", "to_status"}
    safe = {key: value for key, value in data.items() if key in allowed
            and isinstance(value, (str, bool, int, float, type(None)))}
    db.add(SupportEvent(consultation_id=consultation_id, buyer_id=buyer_id,
                        case_id=case_id, kind=kind, data=safe, created_at=now))


def case_view(row: SupportCase, *, admin: bool = False) -> dict:
    value = {"id": str(row.id), "kind": row.kind, "kind_label": REQUEST_KINDS[row.kind],
             "status": row.status, "priority": row.priority,
             "order_id": str(row.order_id) if row.order_id else None,
             "assigned": row.assigned_to is not None, "summary": row.summary,
             "messages": row.messages, "created_at": row.created_at.isoformat(),
             "updated_at": row.updated_at.isoformat(), "expires_at": row.expires_at.isoformat()}
    if admin:
        value.update(buyer_id=str(row.buyer_id), assigned_to=str(row.assigned_to) if row.assigned_to else None,
                     details=row.details)
    return value


def owned_order(db: Session, buyer: User, order_id: UUID, *, lock: bool = False) -> Order:
    stmt = select(Order).where(Order.id == order_id, Order.user_id == buyer.id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    order = db.scalar(stmt)
    if order is None:
        raise HTTPException(403, "未找到可访问的记录")
    return order


def create_case(db: Session, *, buyer: User, request_key: str, kind: str, now: datetime,
                context: dict, concern: str, order: Order | None = None,
                details: dict | None = None, share_history: bool = False,
                reason: str = "buyer_request", priority: str = "normal") -> SupportCase:
    existing = db.scalar(select(SupportCase).where(
        SupportCase.buyer_id == buyer.id, SupportCase.request_key == request_key))
    if existing:
        if existing.kind != kind or existing.order_id != (order.id if order else None):
            raise HTTPException(409, "请求标识已用于其他申请")
        return existing
    if kind not in REQUEST_KINDS:
        raise HTTPException(422, "申请类型无效")
    if kind in ORDER_REQUESTS and order is None:
        raise HTTPException(422, "请先明确选择本人订单")
    if kind in {"shipping_reminder", "address_change"} and order is not None and order.status != "pending_shipment":
        raise HTTPException(409, "这项申请只适用于待发货订单")
    if kind in {"refund", "return", "exchange", "invoice", "compensation"} and order is not None and order.status in {"pending_payment", "closed"}:
        raise HTTPException(409, "该订单状态不适用，请核对订单或选择人工咨询")
    if kind in {"missing", "damage", "wrong_item", "warranty", "replacement"} and order is not None and order.status not in {"pending_receipt", "completed"}:
        raise HTTPException(409, "请在已发货订单中选择要处理的订单")
    facts = [item for item in context.get("facts", []) if isinstance(item, dict)
             and item.get("source") in {"get_my_order", "list_my_orders", "get_product", "list_products", "search_knowledge",
                                        "public_product_knowledge", "get_service_progress"}]
    if order:
        facts = [{"source": "get_my_order", "order_id": str(order.id), "status": order.status,
                  "total": str(order.total), "queried_at": now.isoformat()}]
    summary = {"concern": redact_text(concern or REQUEST_KINDS[kind]),
               "verified_facts": facts[-5:], "executed_actions": [],
               "blocker": "等待人工核对并回复；申请创建没有改变订单、物流或资金状态",
               "escalation_reason": reason,
               "history": list(context.get("history", []))[-12:] if share_history else [],
               "history_shared": share_history}
    row = SupportCase(id=uuid4(), buyer_id=buyer.id, request_key=request_key, kind=kind,
                      status="open", priority=priority, order_id=order.id if order else None,
                      summary=summary, details=details or {}, messages=[],
                      created_at=now, updated_at=now, expires_at=now + timedelta(days=30))
    db.add(row)
    record_event(db, now, "case_created", buyer_id=buyer.id, case_id=row.id, task=kind, reason=reason)
    return row


def notify(db: Session, buyer_id: UUID, source_key: str, text: str, now: datetime) -> None:
    existing = db.scalar(select(SupportNotification.id).where(
        SupportNotification.buyer_id == buyer_id, SupportNotification.source_key == source_key))
    if existing is None:
        db.add(SupportNotification(buyer_id=buyer_id, source_key=source_key,
                                   text=text[:500], created_at=now))


def cleanup_support(session_factory, now: datetime) -> None:
    with session_factory.begin() as db:
        db.execute(delete(SupportCase).where(SupportCase.expires_at <= now))
        db.execute(delete(SupportPreference).where(SupportPreference.expires_at <= now))
        db.execute(delete(SupportEvent).where(SupportEvent.created_at <= now - timedelta(days=30)))
        db.execute(delete(SupportNotification).where(SupportNotification.created_at <= now - timedelta(days=30)))
