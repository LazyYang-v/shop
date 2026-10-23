"""Cancellation proposals: explicit selection, one-time credentials, expiry.

This slice deliberately has no execution path. A proposal records an operation
and returns a confirmation card; the order, stock and close reason never change.
The plaintext credential leaves only through an in-process side channel on the
tool instance and never enters the MCP result, chat response, logs or storage.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
import hashlib
import json
import re
import secrets
from typing import Literal
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import DateTime, ForeignKey, LargeBinary, String, Uuid, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from shop_api.customer_service import CustomerServiceUnavailable, QueryDeadline
from shop_api.database import Base
from shop_api.orders import Order, OrderItem

CANCEL_TRIGGER_TEXT = "申请取消订单"
CONFIRMATION_TTL_SECONDS = 120
CANCEL_ACTION = "cancel"
PENDING = "pending"
EXECUTED = "executed"
REJECTED = "rejected"
EXPIRED = "expired"

PROPOSAL_CARD_FIELDS = ("operation_id", "status", "product_summary", "total", "currency", "expires_at")
_PROPOSAL_KEYS = set(PROPOSAL_CARD_FIELDS)
_MONEY = re.compile(r"^[0-9]+\.[0-9]{2}$")
_ORDER_NUMBER = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


class CancelOperation(Base):
    __tablename__ = "customer_service_cancel_operations"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    buyer_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    session_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    consultation_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    page_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False, default=CANCEL_ACTION)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default=PENDING)
    credential_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32), nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class ProposeCancelArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    order_id: str = Field(max_length=36)


PROPOSE_CANCEL_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"order_id": {"type": "string", "format": "uuid", "maxLength": 36}},
    "required": ["order_id"],
}
CANCEL_TOOL_SCHEMAS = [{"name": "propose_cancel", "inputSchema": PROPOSE_CANCEL_SCHEMA}]


def invalidate_pending_proposals(session: Session, page_id: UUID, now: datetime) -> None:
    """Expire the page's pending proposal; terminal states are never touched."""
    invalidate_pending_proposals_for_pages(session, [page_id], now)


def invalidate_pending_proposals_for_pages(session: Session, page_ids, now: datetime) -> None:
    page_ids = [page_id for page_id in page_ids if page_id is not None]
    if not page_ids:
        return
    session.execute(update(CancelOperation).where(
        CancelOperation.page_id.in_(page_ids),
        CancelOperation.state == PENDING,
    ).values(state=EXPIRED, credential_hash=None, terminal_at=now))


def expire_due_cancel_operations(session_factory, now: datetime) -> None:
    """Periodic conditional expiry: only pending rows past their deadline change."""
    with session_factory.begin() as session:
        session.execute(update(CancelOperation).where(
            CancelOperation.state == PENDING,
            CancelOperation.expires_at <= now,
        ).values(state=EXPIRED, credential_hash=None, terminal_at=now))


def order_product_summary(session: Session, order_id: UUID) -> str:
    items = session.scalars(select(OrderItem).where(OrderItem.order_id == order_id)
                            .order_by(OrderItem.name, OrderItem.id)).all()
    return "、".join(f"{item.name} ×{item.quantity}" for item in items)[:300]


def replay_proposal_response(response: dict) -> dict:
    """Persisted/deduped copy: replay withholds the plaintext credential."""
    stored = dict(response)
    card = dict(stored.get("confirmation_card") or {})
    card.pop("confirmation_token", None)
    stored["confirmation_card"] = card
    stored["code"] = "card_unavailable"
    return stored


def verify_cancel_result(name: str, result) -> dict:
    """Strict MCP response validation; credentials can never be present."""
    if name != "propose_cancel" or not isinstance(result, dict):
        raise CustomerServiceUnavailable
    if set(result) != {"request_id", "queried_at", "status", "data"}:
        raise CustomerServiceUnavailable
    if result["status"] != "proposed":
        raise CustomerServiceUnavailable
    UUID(result["request_id"])
    if datetime.fromisoformat(result["queried_at"]).utcoffset() is None:
        raise CustomerServiceUnavailable
    data = result["data"]
    if not isinstance(data, dict) or set(data) != _PROPOSAL_KEYS:
        raise CustomerServiceUnavailable
    if (not _ORDER_NUMBER.fullmatch(str(data["operation_id"]))
            or data["status"] != "pending_payment"
            or not isinstance(data["product_summary"], str) or len(data["product_summary"]) > 300
            or not isinstance(data["total"], str) or not _MONEY.fullmatch(data["total"])
            or data["currency"] != "CNY"
            or datetime.fromisoformat(data["expires_at"]).utcoffset() is None):
        raise CustomerServiceUnavailable
    return result


class CancellationTools:
    """One model tool: propose a cancellation for the page's recorded selection."""

    tool_names = ("propose_cancel",)
    tool_schemas = CANCEL_TOOL_SCHEMAS
    server_name = "shop-cancellation"

    @staticmethod
    def verify_result(name, result):
        return verify_cancel_result(name, result)

    def __init__(self, session: Session, buyer, page, request_id: str,
                 clock: Callable[[], datetime], *, deadline=None):
        self._session = session
        self._buyer = buyer
        self._page = page
        self._request_id = request_id
        self._clock = clock
        self._deadline = deadline or QueryDeadline(45.0)
        self._confirmation_token: str | None = None

    def take_confirmation_token(self) -> str | None:
        token, self._confirmation_token = self._confirmation_token, None
        return token

    def call(self, name: Literal["propose_cancel"], arguments: dict) -> dict:
        if name not in self.tool_names:
            raise HTTPException(status_code=422, detail="工具参数无效")
        self._confirmation_token = None
        try:
            params = ProposeCancelArguments.model_validate(arguments)
            wanted = UUID(params.order_id)
            normalized = str(wanted)
        except (ValidationError, ValueError):
            raise HTTPException(status_code=422, detail="工具参数无效") from None
        self._deadline.check()

        # Lazy import avoids a module cycle with the consultation models.
        from shop_api.customer_service_consultations import ConsultationPage

        page = self._session.scalar(select(ConsultationPage).where(
            ConsultationPage.id == self._page.id).with_for_update())
        if page is None:
            raise HTTPException(status_code=409, detail="页面已过期")
        if page.selected_order_id is None or page.selected_order_id != wanted or normalized != str(page.selected_order_id):
            raise HTTPException(status_code=409, detail="订单选择已变化")
        order = self._session.scalar(select(Order).where(
            Order.id == wanted, Order.user_id == self._buyer.id).with_for_update())
        if order is None:
            raise HTTPException(status_code=403, detail="未找到可访问的记录")
        now = self._clock()
        if order.status != "pending_payment" or order.expires_at <= now:
            raise HTTPException(status_code=409, detail="订单状态不满足取消条件")

        invalidate_pending_proposals(self._session, page.id, now)
        token = secrets.token_urlsafe(32)
        expires_at = min(now + timedelta(seconds=CONFIRMATION_TTL_SECONDS), order.expires_at)
        operation = CancelOperation(
            id=uuid4(), buyer_id=self._buyer.id, session_id=page.session_id,
            consultation_id=page.consultation_id, page_id=page.id, order_id=order.id,
            action=CANCEL_ACTION, state=PENDING,
            credential_hash=hashlib.sha256(token.encode()).digest(),
            issued_at=now, expires_at=expires_at)
        self._session.add(operation)
        self._session.flush()
        self._confirmation_token = token
        summary = {
            "operation_id": str(operation.id),
            "status": order.status,
            "product_summary": order_product_summary(self._session, order.id),
            "total": str(order.total),
            "currency": "CNY",
            "expires_at": expires_at.isoformat(),
        }
        return {
            "request_id": self._request_id,
            "queried_at": now.isoformat(),
            "status": "proposed",
            "data": {field: summary[field] for field in PROPOSAL_CARD_FIELDS},
        }
