"""Server-scoped order reads for logged-in demo buyers.

Order identity always comes from the authenticated session. Tool arguments can
select or filter orders, but cannot choose a buyer. Candidate cards and the
detail payload are deliberately narrower than the ordinary order API: no
address, phone, email, user id, images or live-carrier data.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import datetime
import json
import re
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from shop_api.customer_service import CustomerServiceUnavailable, QueryDeadline
from shop_api.orders import Order, OrderItem

ORDER_STATUSES = {"pending_payment", "pending_shipment", "pending_receipt", "completed", "closed"}
_CANDIDATE_KEYS = {"order_number", "created_at", "product_summary", "total", "status"}
_DETAIL_KEYS = {"order_number", "status", "total", "product_summary", "expires_at",
                "close_reason", "shipping_company", "tracking_number", "shipped_at"}
_CLOSE_REASONS = {None, "buyer_cancelled", "payment_timeout"}
_ORDER_NUMBER = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_MONEY = re.compile(r"^[0-9]+\.[0-9]{2}$")


class ListMyOrdersArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal["pending_payment", "pending_shipment", "pending_receipt", "completed", "closed"] | None = None
    order_number: str | None = Field(default=None, max_length=64)
    page: int = Field(default=1, ge=1, le=100)
    page_size: int = Field(default=10, ge=1, le=20)


class GetMyOrderArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    order_id: str = Field(max_length=36)


LIST_MY_ORDERS_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "status": {"type": "string", "enum": sorted(ORDER_STATUSES)},
        "order_number": {"type": "string", "maxLength": 64},
        "page": {"type": "integer", "minimum": 1, "maximum": 100},
        "page_size": {"type": "integer", "minimum": 1, "maximum": 20},
    },
    "required": [],
}
GET_MY_ORDER_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"order_id": {"type": "string", "maxLength": 36}},
    "required": ["order_id"],
}

ORDER_TOOL_SCHEMAS = [
    {"name": "list_my_orders", "inputSchema": LIST_MY_ORDERS_SCHEMA},
    {"name": "get_my_order", "inputSchema": GET_MY_ORDER_SCHEMA},
]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _summary(items: list[OrderItem]) -> str:
    text = "、".join(f"{item.name} ×{item.quantity}" for item in items)
    return text[:300]


def _candidate(order: Order, items: list[OrderItem]) -> dict:
    return {
        "order_number": str(order.id),
        "created_at": order.created_at.isoformat(),
        "product_summary": _summary(items),
        "total": str(order.total),
        "status": order.status,
    }


def _detail(order: Order, items: list[OrderItem]) -> dict:
    return {
        "order_number": str(order.id),
        "status": order.status,
        "total": str(order.total),
        "product_summary": _summary(items),
        "expires_at": order.expires_at.isoformat(),
        "close_reason": order.close_reason,
        "shipping_company": order.shipping_company,
        "tracking_number": order.tracking_number,
        "shipped_at": _iso(order.shipped_at),
    }


class OrderTools:
    """At most two order reads per turn; all queries are buyer-scoped."""

    tool_names = ("list_my_orders", "get_my_order")
    tool_schemas = ORDER_TOOL_SCHEMAS
    server_name = "shop-orders"

    @staticmethod
    def verify_result(name, result):
        return verify_order_result(name, result)

    def __init__(self, session: Session, buyer, request_id: str, clock: Callable[[], datetime], *, deadline=None):
        self._session = session
        self._buyer = buyer
        self._request_id = request_id
        self._clock = clock
        self._calls = 0
        self._seen: set[tuple[str, str]] = set()
        self._deadline = deadline or QueryDeadline(45.0)

    def call(self, name: Literal["list_my_orders", "get_my_order"], arguments: dict) -> dict:
        if name not in self.tool_names:
            raise HTTPException(status_code=422, detail="工具参数无效")
        list_params: ListMyOrdersArguments | None = None
        detail_params: GetMyOrderArguments | None = None
        try:
            if name == "list_my_orders":
                list_params = ListMyOrdersArguments.model_validate(arguments)
                if list_params.order_number is not None:
                    list_params.order_number = list_params.order_number.strip()
            else:
                detail_params = GetMyOrderArguments.model_validate(arguments)
                detail_params.order_id = str(UUID(detail_params.order_id))
        except (ValidationError, ValueError):
            raise HTTPException(status_code=422, detail="工具参数无效") from None
        normalized = (list_params or detail_params)
        assert normalized is not None
        if self._calls >= 2:
            raise HTTPException(status_code=503, detail="订单工具额度已用完")
        call_key = (name, json.dumps(normalized.model_dump(), sort_keys=True, separators=(",", ":")))
        if call_key in self._seen:
            raise HTTPException(status_code=422, detail="重复订单工具调用")
        self._seen.add(call_key)
        self._calls += 1
        self._deadline.check()
        if detail_params is not None:
            order = self._read_order(detail_params.order_id)
            return {"request_id": self._request_id, "queried_at": self._clock().isoformat(),
                    "status": "ok", "data": _detail(order, self._items([order.id])[order.id])}
        assert list_params is not None
        return self._list(list_params)

    def _list(self, params: ListMyOrdersArguments) -> dict:
        statement = select(Order).where(Order.user_id == self._buyer.id)
        if params.status is not None:
            statement = statement.where(Order.status == params.status)
        if params.order_number is not None:
            wanted = self._order_number(params.order_number)
            statement = statement.where(Order.id == wanted) if wanted else statement.where(Order.id.is_(None))
        orders = self._read(statement.order_by(Order.created_at.desc(), Order.id.asc()))
        total = len(orders)
        start = (params.page - 1) * params.page_size
        page_orders = orders[start:start + params.page_size]
        items = self._items([order.id for order in page_orders])
        data = {
            "items": [_candidate(order, items[order.id]) for order in page_orders],
            "total": total, "page": params.page, "page_size": params.page_size,
            "has_more": start + params.page_size < total,
        }
        return {"request_id": self._request_id, "queried_at": self._clock().isoformat(),
                "status": "ok" if page_orders else "empty", "data": data}

    @staticmethod
    def _order_number(value: str) -> UUID | None:
        try:
            return UUID(value)
        except ValueError:
            return None

    def _read_order(self, order_id: str) -> Order:
        wanted = UUID(order_id)
        order = self._read(select(Order).where(Order.id == wanted, Order.user_id == self._buyer.id), first=True)
        if order is None:
            raise HTTPException(status_code=403, detail="未找到可访问的记录")
        return order

    def _items(self, order_ids: list[UUID]) -> dict[UUID, list[OrderItem]]:
        grouped: dict[UUID, list[OrderItem]] = defaultdict(list)
        if not order_ids:
            return grouped
        rows = self._read(select(OrderItem).where(OrderItem.order_id.in_(order_ids))
                          .order_by(OrderItem.name, OrderItem.id))
        for item in rows:
            grouped[item.order_id].append(item)
        return grouped

    def _read(self, statement, *, first: bool = False):
        for attempt in range(2):
            self._deadline.check()
            try:
                with self._session.begin_nested():
                    QueryDeadline(3.0).apply(self._session, maximum_seconds=3.0)
                    if first:
                        value = self._session.scalar(statement)
                    else:
                        value = self._session.scalars(statement).all()
                    QueryDeadline(3.0).check()
                    return value
            except DBAPIError as error:
                sqlstate = getattr(error.orig, "sqlstate", None)
                if attempt or sqlstate not in {"40001", "40P01", "55P03", "57014"}:
                    raise
                # A retry consumes the turn's two-call order budget.
                self._calls += 1
        raise HTTPException(status_code=503, detail="订单查询暂不可用")


def verify_order_result(name: str, result) -> dict:
    """Strict MCP response validation; rejects any extra field."""
    if not isinstance(result, dict) or set(result) != {"request_id", "queried_at", "status", "data"}:
        raise CustomerServiceUnavailable
    UUID(result["request_id"])
    if datetime.fromisoformat(result["queried_at"]).utcoffset() is None:
        raise CustomerServiceUnavailable
    data = result["data"]
    if name == "list_my_orders":
        if not isinstance(data, dict) or set(data) != {"items", "total", "page", "page_size", "has_more"}:
            raise CustomerServiceUnavailable
        if (type(data["items"]) is not list or len(data["items"]) > 20
                or type(data["total"]) is not int or not 0 <= data["total"] <= 10_000
                or type(data["page"]) is not int or not 1 <= data["page"] <= 100
                or type(data["page_size"]) is not int or not 1 <= data["page_size"] <= 20
                or type(data["has_more"]) is not bool
                or result["status"] != ("ok" if data["items"] else "empty")):
            raise CustomerServiceUnavailable
        for item in data["items"]:
            _verify_candidate(item)
        return result
    if name == "get_my_order":
        if result["status"] != "ok":
            raise CustomerServiceUnavailable
        _verify_detail(data)
        return result
    raise CustomerServiceUnavailable


def _verify_candidate(item) -> None:
    if not isinstance(item, dict) or set(item) != _CANDIDATE_KEYS:
        raise CustomerServiceUnavailable
    if (not _ORDER_NUMBER.fullmatch(item["order_number"]) or item["status"] not in ORDER_STATUSES
            or not isinstance(item["product_summary"], str) or len(item["product_summary"]) > 300
            or not isinstance(item["total"], str) or not _MONEY.fullmatch(item["total"])):
        raise CustomerServiceUnavailable
    if datetime.fromisoformat(item["created_at"]).utcoffset() is None:
        raise CustomerServiceUnavailable


def _verify_detail(data) -> None:
    if not isinstance(data, dict) or set(data) != _DETAIL_KEYS:
        raise CustomerServiceUnavailable
    if (not _ORDER_NUMBER.fullmatch(data["order_number"]) or data["status"] not in ORDER_STATUSES
            or not isinstance(data["total"], str) or not _MONEY.fullmatch(data["total"])
            or not isinstance(data["product_summary"], str) or len(data["product_summary"]) > 300
            or data["close_reason"] not in _CLOSE_REASONS):
        raise CustomerServiceUnavailable
    if datetime.fromisoformat(data["expires_at"]).utcoffset() is None:
        raise CustomerServiceUnavailable
    if data["shipped_at"] is not None and datetime.fromisoformat(data["shipped_at"]).utcoffset() is None:
        raise CustomerServiceUnavailable
    for field in ("shipping_company", "tracking_number"):
        if data[field] is not None and (not isinstance(data[field], str) or not 1 <= len(data[field]) <= 100):
            raise CustomerServiceUnavailable


_ORDER_LIKE = re.compile(r"我的订单|订单号|订单详情|订单列表|订单状态|查询订单|查看订单|看看订单|订单(?:是|为|：|:)\s*[A-Za-z0-9-]")
_LIST = re.compile(r"(?:请问|请帮我|帮我)?(?:查看|查询|看看)?(?:我的)?订单(?:列表)?[？?。]?")
_ORDER_NUMBER_TEXT = re.compile(
    r"(?:请问|请帮我|帮我)?(?:查询|查看|看看)?订单(?:号)?(?:是|为|：|:)?\s*([A-Za-z0-9-]{1,64})[？?。]?")
_ORDER_DETAIL_TEXT = re.compile(r"(?:请问|请帮我|帮我)?(?:查询|查看|看看)订单详情[？?。]?")


def understand_order(text: str) -> tuple[str, dict] | None:
    """Return a supported order intent, or None for unrelated text.

    Callers use ``looks_like_order_question`` to distinguish an unknown order
    request (clarify/login) from unrelated product or policy text.
    """
    sentence = "".join(text.split())
    if _LIST.fullmatch(sentence):
        return "list_my_orders", {}
    number = _ORDER_NUMBER_TEXT.fullmatch(sentence)
    if number is not None:
        return "list_my_orders", {"order_number": number.group(1)}
    if _ORDER_DETAIL_TEXT.fullmatch(sentence) or looks_like_order_question(sentence):
        return "clarify", {}
    return None


def looks_like_order_question(text: str) -> bool:
    return bool(_ORDER_LIKE.search("".join(text.split())))
