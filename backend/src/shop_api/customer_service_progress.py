"""Buyer-scoped, read-only service progress for the private in-process MCP.

Case review status and staff replies are not execution evidence. Refund,
replacement and invoice execution systems are not connected; the sole verified
local action is the address-change evidence written by the review transaction.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import json
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from shop_api.customer_service import CustomerServiceUnavailable, QueryDeadline
from shop_api.customer_service_support import CASE_STATUSES, REQUEST_KINDS, SupportCase, redact_text
from shop_api.identity import Role, User
from shop_api.orders import Order

MAX_PROGRESS_CASES = 10
MAX_PROGRESS_REPLY = 300
PROGRESS_NOTICE = (
    "以下仅为服务申请的工单审核进度。工单已处理（resolved）和人工回复不代表退款到账、补发完成或发票开具；"
    "这些业务执行系统尚未接通（not_connected）。只有带执行证据的修改收货地址记录可核验为 verified。"
)


class GetServiceProgressArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    order_id: str = Field(min_length=36, max_length=36)
    kind: str | None = Field(default=None, max_length=32)

    @field_validator("order_id")
    @classmethod
    def valid_order_id(cls, value: str) -> str:
        return str(UUID(value))

    @field_validator("kind")
    @classmethod
    def known_kind(cls, value: str | None) -> str | None:
        if value is not None and value not in REQUEST_KINDS:
            raise ValueError("Unknown request kind")
        return value


SERVICE_PROGRESS_TOOL_SCHEMAS = [{
    "name": "get_service_progress",
    "inputSchema": {
        "type": "object", "additionalProperties": False,
        "properties": {
            "order_id": {"type": "string", "minLength": 36, "maxLength": 36},
            "kind": {"type": "string", "enum": sorted(REQUEST_KINDS)},
        },
        "required": ["order_id"],
    },
}]


def _timestamp(value: str) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("Invalid timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValueError("Timezone required")
    return parsed


def _latest_reply(row: SupportCase) -> dict | None:
    if not isinstance(row.messages, list):
        return None
    for message in reversed(row.messages[-50:]):
        if (not isinstance(message, dict) or message.get("role") != "staff"
                or not isinstance(message.get("text"), str)):
            continue
        try:
            at = _timestamp(message.get("at"))
        except (ValueError, TypeError):
            continue
        if row.created_at <= at <= row.updated_at:
            return {"role": "staff", "text": redact_text(message["text"], MAX_PROGRESS_REPLY),
                    "at": at.isoformat()}
    return None


def _executed_actions(row: SupportCase, order_id: UUID, now: datetime) -> list[dict]:
    if row.kind != "address_change" or not isinstance(row.summary, dict):
        return []
    actions = row.summary.get("executed_actions")
    if not isinstance(actions, list):
        return []
    for action in reversed(actions[-50:]):
        if (not isinstance(action, dict) or action.get("action") != "address_change"
                or action.get("order_id") != str(order_id)):
            continue
        try:
            at = _timestamp(action.get("at"))
        except (ValueError, TypeError):
            continue
        if row.created_at <= at <= row.updated_at <= now:
            return [{"action": "address_change", "order_id": str(order_id), "at": at.isoformat()}]
    return []


class ServiceProgressTools:
    """Two bounded reads per turn; identity is supplied by the server, never arguments.

    Callers must first validate the consultation's explicit order selection. The
    tool independently rechecks order ownership and scopes every case read.
    """

    tool_names = ("get_service_progress",)
    tool_schemas = SERVICE_PROGRESS_TOOL_SCHEMAS
    server_name = "shop-service-progress"

    @staticmethod
    def verify_result(name, result):
        return verify_service_progress_result(name, result)

    def __init__(self, session: Session, buyer: User | None, request_id: str,
                 clock: Callable[[], datetime], *, deadline=None):
        if buyer is None or not buyer.is_active:
            raise HTTPException(401, "需要登录")
        if buyer.role != Role.BUYER.value:
            raise HTTPException(403, "无权执行此操作")
        self._session = session
        self._buyer = buyer
        self._request_id = request_id
        self._clock = clock
        self._deadline = deadline or QueryDeadline(45)
        self._calls = 0
        self._seen: set[str] = set()

    def call(self, name: Literal["get_service_progress"], arguments: dict) -> dict:
        if name not in self.tool_names:
            raise HTTPException(422, "工具参数无效")
        try:
            params = GetServiceProgressArguments.model_validate(arguments)
        except (ValidationError, ValueError):
            raise HTTPException(422, "工具参数无效") from None
        key = json.dumps(params.model_dump(), sort_keys=True)
        if self._calls >= 2:
            raise HTTPException(503, "服务进度工具额度已用完")
        if key in self._seen:
            raise HTTPException(422, "重复服务进度工具调用")
        self._seen.add(key)
        self._calls += 1
        now = self._clock()
        order_id = UUID(params.order_id)
        order = self._read(select(Order).where(Order.id == order_id, Order.user_id == self._buyer.id), first=True)
        if order is None:
            raise HTTPException(403, "未找到可访问的记录")
        statement = select(SupportCase).where(
            SupportCase.buyer_id == self._buyer.id, SupportCase.order_id == order_id,
            SupportCase.expires_at > now, SupportCase.kind.in_(REQUEST_KINDS),
            SupportCase.status.in_(CASE_STATUSES),
        )
        if params.kind is not None:
            statement = statement.where(SupportCase.kind == params.kind)
        rows = self._read(statement.order_by(SupportCase.updated_at.desc(), SupportCase.id.asc())
                          .limit(MAX_PROGRESS_CASES + 1))
        items = []
        for row in rows[:MAX_PROGRESS_CASES]:
            actions = _executed_actions(row, order_id, now)
            items.append({
                "case_id": str(row.id), "kind": row.kind, "kind_label": REQUEST_KINDS[row.kind],
                "status": row.status, "latest_reply": _latest_reply(row), "updated_at": row.updated_at.isoformat(),
                "execution_status": "verified" if actions else "not_connected", "executed_actions": actions,
            })
        return {
            "request_id": self._request_id, "queried_at": now.isoformat(), "status": "ok" if items else "empty",
            "data": {"order_id": str(order_id), "kind": params.kind, "items": items,
                     "has_more": len(rows) > MAX_PROGRESS_CASES, "notice": PROGRESS_NOTICE},
        }

    def _read(self, statement, *, first: bool = False):
        self._deadline.check()
        with self._session.begin_nested():
            query_deadline = QueryDeadline(3)
            query_deadline.apply(self._session)
            statement = statement.execution_options(populate_existing=True)
            value = self._session.scalar(statement) if first else self._session.scalars(statement).all()
            query_deadline.check()
            self._deadline.check()
            return value


def verify_service_progress_result(name: str, result) -> dict:
    """Reject extra fields and unsupported execution claims at the MCP boundary."""
    try:
        if name != "get_service_progress" or not isinstance(result, dict) or set(result) != {
                "request_id", "queried_at", "status", "data"}:
            raise ValueError
        if not isinstance(result["request_id"], str):
            raise ValueError
        UUID(result["request_id"])
        queried_at = _timestamp(result["queried_at"])
        data = result["data"]
        if not isinstance(data, dict) or set(data) != {"order_id", "kind", "items", "has_more", "notice"}:
            raise ValueError
        params = GetServiceProgressArguments.model_validate({"order_id": data["order_id"], "kind": data["kind"]})
        items = data["items"]
        if (type(items) is not list or len(items) > MAX_PROGRESS_CASES or type(data["has_more"]) is not bool
                or data["has_more"] and len(items) != MAX_PROGRESS_CASES
                or data["notice"] != PROGRESS_NOTICE or result["status"] != ("ok" if items else "empty")):
            raise ValueError
        seen = set()
        for item in items:
            if not isinstance(item, dict) or set(item) != {
                    "case_id", "kind", "kind_label", "status", "latest_reply", "updated_at",
                    "execution_status", "executed_actions"}:
                raise ValueError
            case_id = item["case_id"]
            if not isinstance(case_id, str) or len(case_id) != 36 or str(UUID(case_id)) != case_id or case_id in seen:
                raise ValueError
            seen.add(case_id)
            if (item["kind"] not in REQUEST_KINDS or item["kind_label"] != REQUEST_KINDS[item["kind"]]
                    or item["status"] not in CASE_STATUSES or params.kind is not None and item["kind"] != params.kind):
                raise ValueError
            updated_at = _timestamp(item["updated_at"])
            if updated_at > queried_at:
                raise ValueError
            reply = item["latest_reply"]
            if reply is not None:
                if (not isinstance(reply, dict) or set(reply) != {"role", "text", "at"}
                        or reply["role"] != "staff" or not isinstance(reply["text"], str)
                        or len(reply["text"]) > MAX_PROGRESS_REPLY
                        or redact_text(reply["text"], MAX_PROGRESS_REPLY) != reply["text"]
                        or _timestamp(reply["at"]) > updated_at):
                    raise ValueError
            actions = item["executed_actions"]
            if type(actions) is not list or len(actions) > 1:
                raise ValueError
            if item["execution_status"] != ("verified" if actions else "not_connected"):
                raise ValueError
            for action in actions:
                if (item["kind"] != "address_change" or not isinstance(action, dict)
                        or set(action) != {"action", "order_id", "at"} or action["action"] != "address_change"
                        or action["order_id"] != params.order_id or _timestamp(action["at"]) > updated_at):
                    raise ValueError
    except (KeyError, TypeError, ValueError, ValidationError, AttributeError):
        raise CustomerServiceUnavailable from None
    return result
