"""Session-bound fictional product consultations; real provider remains closed."""

import hashlib
import logging
import re
import secrets
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import DateTime, ForeignKey, LargeBinary, Uuid, delete, select, text, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from shop_api.customer_service import CustomerServiceUnavailable, QueryDeadline
from shop_api.customer_service_cancel import (
    CANCEL_TRIGGER_TEXT,
    PROPOSAL_CARD_FIELDS,
    CancellationTools,
    invalidate_pending_proposals,
    invalidate_pending_proposals_for_pages,
    replay_proposal_response,
)
from shop_api.customer_service_orders import OrderTools, looks_like_order_question, understand_order
from shop_api.customer_service_products import ProductTools
from shop_api.database import Base
from shop_api.identity import AuthSession, require_csrf
from shop_api.orders import Order
from shop_api.customer_service_admission import require_demo_buyer, require_product_reader, require_query_rate_limits

LIST_PRODUCTS_TEXT = "查看演示商品"
PRODUCT_SELECTION_PREFIX = "查看演示商品："
_POLICY_ENVELOPE_STATUS = {
    "ok": "ok", "no_match": "empty", "conflict": "unavailable",
    "unavailable": "unavailable", "needs_clarification": "needs_clarification",
}
_UUID4 = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
_TOKEN = r"^[A-Za-z0-9_-]{43}$"


class Consultation(Base):
    __tablename__ = "customer_service_consultations"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("auth_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConsultationPage(Base):
    __tablename__ = "customer_service_pages"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("auth_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    consultation_id: Mapped[UUID] = mapped_column(ForeignKey("customer_service_consultations.id", ondelete="CASCADE"), nullable=False)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    handoff_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32), nullable=True, unique=True)
    handoff_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Buyer selection is server-side and bound to this page/consultation.
    selected_order_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    selected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConsultationMessage(Base):
    __tablename__ = "customer_service_messages"
    # Page IDs remain here after a page expires; dedupe lasts until consultation expiry.
    consultation_id: Mapped[UUID] = mapped_column(ForeignKey("customer_service_consultations.id", ondelete="CASCADE"), primary_key=True)
    page_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    client_message_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    body_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    response: Mapped[dict] = mapped_column(JSONB, nullable=False)


class PageInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    handoff_token: str | None = Field(default=None, max_length=128, pattern=_TOKEN)


class RenewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    page_instance_id: str = Field(pattern=_UUID4, max_length=128)
    handoff_token: str = Field(pattern=_TOKEN, max_length=128)


class MessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    page_instance_id: str = Field(pattern=_UUID4, max_length=128)
    consultation_id: str = Field(pattern=_UUID4, max_length=128)
    client_message_id: str = Field(pattern=_UUID4, max_length=128)
    text: str | None = Field(default=None, min_length=1)
    selected_order_id: str | None = Field(default=None, max_length=36)


class ConsultationError(Exception):
    def __init__(self, status_code: int, code: str, message: str, headers=None):
        self.status_code, self.code, self.message, self.headers = status_code, code, message, headers


def _envelope(request: Request, status: str, data=None, **extra) -> dict:
    return {"request_id": request.state.customer_service_request_id,
            "queried_at": request.app.state.clock().astimezone(UTC).isoformat(),
            "status": status, "data": data, **extra}


class ConsultationRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def handle(request: Request):
            request.state.customer_service_request_id = str(uuid4())
            try:
                # Enforce bytes before JSON parsing, including chunked requests.
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > 16 * 1024:
                        raise ConsultationError(413, "payload_too_large", "请求正文过长")
                request._body = bytes(body)
                result = await handler(request)
            except Exception as error:
                from shop_api.customer_service_product_mcp import ProductMCPFailure
                from shop_api.customer_service_model_loop import ModelUnavailable
                if isinstance(error, ProductMCPFailure):
                    code = error.code
                    status_code = 403 if code == 'resource_unavailable' else 422 if code == 'invalid_input' else 409 if code == 'state_conflict' else 503
                    message = {'resource_unavailable': '未找到可访问的记录', 'invalid_input': '工具参数无效',
                               'state_conflict': '订单状态或页面选择已变化，请重新选择',
                               'mcp_timeout': '商品查询超时，请稍后重试', 'mcp_unavailable': '商品查询服务暂不可用'}[code]
                    failure = ConsultationError(status_code, code, message)
                elif isinstance(error, ModelUnavailable):
                    failure = ConsultationError(503, 'model_unavailable', '模型服务暂不可用')
                elif isinstance(error, ConsultationError):
                    failure = error
                elif isinstance(error, RequestValidationError):
                    failure = ConsultationError(422, "invalid_input", "请求参数无效")
                elif isinstance(error, HTTPException):
                    code, message = {401: ("authentication_required", "需要登录"),
                                     403: ("resource_unavailable", "未找到可访问的记录"),
                                     422: ("invalid_input", "请求参数无效"),
                                     429: ("rate_limited", "请求过于频繁")}.get(error.status_code, ("dependency_unavailable", "客服暂不可用"))
                    failure = ConsultationError(error.status_code, code, message, error.headers)
                else:
                    logging.getLogger(__name__).warning("customer_service_request_failed request_id=%s error=dependency_unavailable", request.state.customer_service_request_id)
                    failure = ConsultationError(503, "dependency_unavailable", "客服暂不可用")
                status = "unavailable" if failure.status_code == 503 else "processing" if failure.status_code == 425 else "error"
                result = JSONResponse(status_code=failure.status_code, headers=failure.headers,
                                      content=_envelope(request, status, code=failure.code, message=failure.message))
            result.headers["Cache-Control"] = "no-store"
            return result

        return handle


def _consultation_expired(consultation: Consultation, now: datetime) -> bool:
    return consultation.last_used_at + timedelta(minutes=30) <= now or consultation.created_at + timedelta(hours=24) <= now


def _lock_session(db: Session, record: AuthSession, now: datetime) -> None:
    QueryDeadline(3).apply(db)
    # All mutations use the same DB row lock, including page count/LRU and handoff.
    current = db.scalar(select(AuthSession).where(AuthSession.id == record.id).with_for_update().execution_options(populate_existing=True))
    if current is None or current.revoked_at is not None or current.expires_at <= now:
        raise ConsultationError(401, "authentication_required", "需要登录")


def _page(db: Session, record: AuthSession, page_id: str, now: datetime) -> tuple[ConsultationPage, Consultation]:
    page = db.get(ConsultationPage, UUID(page_id))
    if page is None:
        raise ConsultationError(410, "page_expired", "页面已过期，请重新打开")
    if page.session_id != record.id:
        raise ConsultationError(403, "resource_unavailable", "未找到可访问的记录")
    consultation = db.get(Consultation, page.consultation_id)
    if page.last_used_at + timedelta(minutes=10) <= now or consultation is None or _consultation_expired(consultation, now):
        raise ConsultationError(410, "page_expired", "页面已过期，请重新打开")
    return page, consultation


def _rate(request: Request, key: str, limit: int) -> None:
    allowed, retry_after = request.app.state.customer_service_limiter.allow(key, limit, 60, request.app.state.clock())
    if not allowed:
        raise ConsultationError(429, "rate_limited", "请求过于频繁", {"Retry-After": str(retry_after)})


def _store_response(db: Session, key: tuple, response: dict) -> None:
    message = db.get(ConsultationMessage, key)
    if message is None:
        raise ConsultationError(425, 'processing', '已有请求结果未能确认')
    message.response = response


def _order_probe_rate(request: Request, buyer) -> None:
    key = "order_probe:" + hashlib.sha256(str(buyer.id).encode()).hexdigest()
    _rate(request, key, 10)


def _record_selection(db: Session, page: ConsultationPage, order: Order, now: datetime) -> None:
    """Record the buyer's explicit server-side selection; a change revokes its card."""
    changed = page.selected_order_id != order.id
    page.selected_order_id = order.id
    page.selected_at = now
    if changed:
        invalidate_pending_proposals(db, page.id, now)


def _selected_order(db: Session, buyer, order_id: str) -> Order:
    try:
        wanted = UUID(order_id)
    except ValueError:
        raise ConsultationError(422, 'invalid_input', '请求参数无效') from None
    order = db.scalar(select(Order).where(Order.id == wanted, Order.user_id == buyer.id))
    if order is None:
        raise ConsultationError(403, 'resource_unavailable', '未找到可访问订单')
    return order


def _order_turn(payload: MessageInput, request: Request, record: AuthSession, db: Session,
                page: ConsultationPage, consultation: Consultation, body_hash: bytes,
                key: tuple, deadline: float) -> dict:
    """Deterministic order path; buyer identity comes only from the session."""
    from shop_api.customer_service_product_mcp import CustomerServiceMCP, ProductMCPFailure

    started = time.monotonic()
    if record.kind != 'authenticated' or record.user_id is None:
        raise ConsultationError(401, 'authentication_required', '请登录后查看本人订单')
    try:
        buyer = require_demo_buyer(request, record, db)
    except HTTPException as error:
        code, message = {401: ('authentication_required', '请登录后查看本人订单'),
                         403: ('resource_unavailable', '未找到可访问的记录'),
                         503: ('dependency_unavailable', '客服暂不可用')}.get(
                             error.status_code, ('dependency_unavailable', '客服暂不可用'))
        raise ConsultationError(error.status_code, code, message, error.headers) from None
    require_query_rate_limits(request)
    if payload.selected_order_id is not None:
        _order_probe_rate(request, buyer)
        selected = _selected_order(db, buyer, payload.selected_order_id)
        _record_selection(db, page, selected, request.app.state.clock())
        name, arguments = 'get_my_order', {'order_id': str(selected.id)}
    else:
        name, arguments = understand_order(payload.text or '') or ('clarify', {})
        if arguments.get('order_number') is not None:
            _order_probe_rate(request, buyer)

    claim = _envelope(request, 'unavailable', code='processing', message='已有请求结果未能确认')
    db.add(ConsultationMessage(consultation_id=consultation.id, page_id=page.id,
                               client_message_id=UUID(payload.client_message_id), body_hash=body_hash, response=claim))
    db.commit()

    if name == 'clarify':
        response = _envelope(request, 'needs_clarification', {
            'reply': '当前演示仅支持查看本人订单及已保存物流；不支持退款、发券、催发货、转人工或实时物流。请提供订单号，或查看我的订单后选择一单。',
            'cards': [], 'citations': []})
        now = request.app.state.clock()
        _store_response(db, key, response)
        page.last_used_at = consultation.last_used_at = now
        db.commit()
        return response

    query_deadline = QueryDeadline(max(0, deadline - time.monotonic()))
    tools = OrderTools(db, buyer, request.state.customer_service_request_id,
                       request.app.state.clock, deadline=query_deadline)
    mcp = CustomerServiceMCP(tools, deadline=deadline)
    try:
        mcp.initialize()
        mcp.tools()
        result = mcp.call(name, arguments)
    except ProductMCPFailure as error:
        code = error.code
        status_code = 403 if code == 'resource_unavailable' else 422 if code == 'invalid_input' else 409 if code == 'state_conflict' else 503
        message = {'resource_unavailable': '未找到可访问订单', 'invalid_input': '请求参数无效',
                   'state_conflict': '订单状态已变化，请重新选择',
                   'mcp_timeout': '订单查询超时，请稍后重试', 'mcp_unavailable': '订单查询服务暂不可用'}.get(
                       code, '订单查询服务暂不可用')
        raise ConsultationError(status_code, code, message) from None
    finally:
        mcp.close()
    db.commit()

    # Delivery revalidates auth/page and buyer membership after the tool read.
    now = request.app.state.clock()
    _lock_session(db, record, now)
    require_demo_buyer(request, record, db)
    page, consultation = _page(db, record, payload.page_instance_id, now)
    query_deadline.check()
    if name == 'get_my_order':
        data = result['data']
        cards = [{'type': 'order_detail', 'order': data}]
        reply, status = '已查询订单信息', 'ok'
    else:
        candidates = result['data']['items']
        cards = [{'type': 'order', 'order': item} for item in candidates]
        if not candidates:
            reply, status = '未找到可访问订单', 'empty'
        elif result['data']['has_more']:
            reply, status = '请选择要查询的订单；还有更多订单，请输入订单号进一步查询。', 'ok'
        else:
            reply, status = '请选择要查询的订单', 'ok'
    response = _envelope(request, status, {'reply': reply, 'cards': cards, 'citations': []})
    request.app.state.customer_service_log_writer.write(
        request.state.customer_service_request_id, name, '', int((time.monotonic() - started) * 1000), len(cards), now)
    _store_response(db, key, response)
    page.last_used_at = consultation.last_used_at = now
    db.commit()
    return response


def _cancel_turn(payload: MessageInput, request: Request, record: AuthSession, db: Session,
                 page: ConsultationPage, consultation: Consultation, body_hash: bytes,
                 key: tuple, deadline: float) -> dict:
    """Issue a cancellation proposal for the page's server-recorded selection."""
    from shop_api.customer_service_product_mcp import CustomerServiceMCP, ProductMCPFailure

    started = time.monotonic()
    if record.kind != 'authenticated' or record.user_id is None:
        raise ConsultationError(401, 'authentication_required', '请登录后查看本人订单')
    try:
        buyer = require_demo_buyer(request, record, db)
    except HTTPException as error:
        code, message = {401: ('authentication_required', '请登录后查看本人订单'),
                         403: ('resource_unavailable', '未找到可访问的记录'),
                         503: ('dependency_unavailable', '客服暂不可用')}.get(
                             error.status_code, ('dependency_unavailable', '客服暂不可用'))
        raise ConsultationError(error.status_code, code, message, error.headers) from None
    require_query_rate_limits(request)
    now = request.app.state.clock()
    if payload.selected_order_id is not None:
        _order_probe_rate(request, buyer)
        selected = _selected_order(db, buyer, payload.selected_order_id)
        _record_selection(db, page, selected, now)
    if page.selected_order_id is None:
        raise ConsultationError(409, 'state_conflict', '请先选择订单')
    selected_order_id = page.selected_order_id
    _rate(request, "cancel_proposal:" + hashlib.sha256(str(buyer.id).encode()).hexdigest(), 5)

    claim = _envelope(request, 'unavailable', code='processing', message='已有请求结果未能确认')
    db.add(ConsultationMessage(consultation_id=consultation.id, page_id=page.id,
                               client_message_id=UUID(payload.client_message_id), body_hash=body_hash, response=claim))
    db.commit()

    tools = CancellationTools(db, buyer, page, request.state.customer_service_request_id,
                              request.app.state.clock,
                              deadline=QueryDeadline(max(0, deadline - time.monotonic())))
    mcp = CustomerServiceMCP(tools, deadline=deadline)
    try:
        mcp.initialize()
        mcp.tools()
        result = mcp.call('propose_cancel', {'order_id': str(page.selected_order_id)})
    except ProductMCPFailure as error:
        code = error.code
        status_code = (403 if code == 'resource_unavailable' else 409 if code == 'state_conflict'
                       else 422 if code == 'invalid_input' else 503)
        message = {'resource_unavailable': '未找到可访问订单', 'state_conflict': '订单状态或页面选择已变化，请重新选择',
                   'invalid_input': '请求参数无效', 'mcp_timeout': '取消方案签发超时，请稍后重试',
                   'mcp_unavailable': '取消方案暂不可用'}.get(code, '取消方案暂不可用')
        raise ConsultationError(status_code, code, message) from None
    finally:
        mcp.close()
    token = tools.take_confirmation_token()
    if token is None:
        raise CustomerServiceUnavailable

    now = request.app.state.clock()
    _lock_session(db, record, now)
    require_demo_buyer(request, record, db)
    page, consultation = _page(db, record, payload.page_instance_id, now)
    data = result['data']
    card = {field: data[field] for field in PROPOSAL_CARD_FIELDS}
    card['order_number'] = str(selected_order_id)
    card['confirmation_token'] = token
    response = _envelope(request, 'ok', {
        'reply': '已生成取消确认方案；确认执行尚未开放。'
                 '取消后将恢复商品库存，操作不可撤销，且购物车不会恢复。',
        'cards': [], 'citations': []}, confirmation_card=card)
    request.app.state.customer_service_log_writer.write(
        request.state.customer_service_request_id, 'propose_cancel', '',
        int((time.monotonic() - started) * 1000), 1, now)
    _store_response(db, key, replay_proposal_response(response))
    page.last_used_at = consultation.last_used_at = now
    db.commit()
    return response


def build_consultation_router(session_dependency, current_session):
    router = APIRouter(prefix="/api/customer-service", route_class=ConsultationRoute)

    def authorized(request: Request, record: AuthSession = Depends(current_session),
                   db: Session = Depends(session_dependency),
                   csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
                   origin: str | None = Header(default=None)) -> AuthSession:
        try:
            require_csrf(request, record, csrf_token, origin)
        except HTTPException:
            raise ConsultationError(403, "forbidden", "请求校验失败") from None
        require_product_reader(request, record, db)
        if request.query_params:
            raise ConsultationError(422, "invalid_input", "请求参数无效")
        return record

    @router.post("/pages", status_code=201)
    def create_page(payload: PageInput, request: Request, record: AuthSession = Depends(authorized),
                    db: Session = Depends(session_dependency)):
        now = request.app.state.clock()
        _lock_session(db, record, now)
        pages = list(db.scalars(select(ConsultationPage).where(ConsultationPage.session_id == record.id)
                                .order_by(ConsultationPage.last_used_at, ConsultationPage.id)).all())
        consultation = None
        if payload.handoff_token:
            token_hash = hashlib.sha256(payload.handoff_token.encode()).digest()
            predecessor = next((page for page in pages if page.handoff_hash is not None and secrets.compare_digest(page.handoff_hash, token_hash)), None)
            if predecessor is not None and predecessor.handoff_expires_at > now and predecessor.last_used_at + timedelta(minutes=10) > now:
                candidate = db.get(Consultation, predecessor.consultation_id)
                if candidate is not None and not _consultation_expired(candidate, now):
                    consultation = candidate
                    invalidate_pending_proposals(db, predecessor.id, now)
                    db.delete(predecessor)
                    pages.remove(predecessor)
        # Expired pages cannot be revived; LRU removal is atomic with creation.
        for page in list(pages):
            context = db.get(Consultation, page.consultation_id)
            if page.last_used_at + timedelta(minutes=10) <= now or context is None or _consultation_expired(context, now):
                invalidate_pending_proposals(db, page.id, now)
                db.delete(page)
                pages.remove(page)
        if len(pages) >= 10:
            invalidate_pending_proposals(db, pages[0].id, now)
            db.delete(pages[0])
        if consultation is None:
            consultation = Consultation(id=uuid4(), session_id=record.id, created_at=now, last_used_at=now)
            db.add(consultation)
            db.flush()
        # Renewal/page creation does not extend consultation idle lifetime.
        token = secrets.token_urlsafe(32)
        page = ConsultationPage(id=uuid4(), session_id=record.id, consultation_id=consultation.id,
                                last_used_at=now, handoff_hash=hashlib.sha256(token.encode()).digest(),
                                handoff_expires_at=now + timedelta(seconds=90))
        db.add(page)
        db.commit()
        return _envelope(request, "ok", {"page_instance_id": str(page.id), "consultation_id": str(consultation.id),
                                         "handoff_token": token, "handoff_expires_at": page.handoff_expires_at.isoformat()})

    @router.post("/pages/renew")
    def renew_page(payload: RenewInput, request: Request, record: AuthSession = Depends(authorized),
                   db: Session = Depends(session_dependency)):
        now = request.app.state.clock()
        _lock_session(db, record, now)
        page, _ = _page(db, record, payload.page_instance_id, now)
        if page.handoff_hash is None or page.handoff_expires_at <= now or not secrets.compare_digest(page.handoff_hash, hashlib.sha256(payload.handoff_token.encode()).digest()):
            raise ConsultationError(410, "page_expired", "页面已过期，请重新打开")
        _rate(request, f"renew:{page.id}", 4)
        page.last_used_at = now
        page.handoff_expires_at = now + timedelta(seconds=90)
        db.commit()
        return _envelope(request, "ok", {"handoff_expires_at": page.handoff_expires_at.isoformat()})

    @router.post("/messages")
    def message(payload: MessageInput, request: Request, record: AuthSession = Depends(authorized),
                db: Session = Depends(session_dependency)):
        lock_key = int.from_bytes(hashlib.sha256(f"customer-service-message:{record.id}".encode()).digest()[:8], "big", signed=True)
        # A dedicated connection owns a session lock across short transactions.
        with request.app.state.session_factory.kw['bind'].connect() as owner:
            locked = owner.scalar(text('SELECT pg_try_advisory_lock(:key)'), {'key': lock_key})
            owner.commit()
            if not locked:
                raise ConsultationError(425, 'busy', '已有咨询消息正在处理')
            try:
                return run_message(payload, request, record, db)
            finally:
                owner.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': lock_key})
                owner.commit()

    def run_message(payload, request, record, db):
        deadline = time.monotonic() + 45.0
        now = request.app.state.clock()
        if payload.text is not None and len(payload.text) > 2000:
            raise ConsultationError(422, "message_too_long", "消息过长")
        _lock_session(db, record, now)
        page, consultation = _page(db, record, payload.page_instance_id, now)
        if str(consultation.id) != payload.consultation_id:
            raise ConsultationError(403, "resource_unavailable", "未找到可访问的记录")
        body_hash = hashlib.sha256(payload.model_dump_json().encode()).digest()
        key = (consultation.id, page.id, UUID(payload.client_message_id))
        existing = db.get(ConsultationMessage, key)
        if existing is not None:
            if not secrets.compare_digest(existing.body_hash, body_hash):
                raise ConsultationError(409, "message_conflict", "消息标识已用于其他内容")
            if existing.response.get('code') == 'processing':
                raise ConsultationError(425, 'processing', '已有请求结果未能确认')
            page.last_used_at = now
            db.commit()
            return existing.response
        if payload.text is None and payload.selected_order_id is None:
            raise ConsultationError(422, "invalid_input", "请选择受支持的服务查询")
        if payload.text is not None and payload.text.strip() == CANCEL_TRIGGER_TEXT:
            return _cancel_turn(payload, request, record, db, page, consultation, body_hash, key, deadline)
        if payload.selected_order_id is not None or looks_like_order_question(payload.text or ""):
            return _order_turn(payload, request, record, db, page, consultation, body_hash, key, deadline)
        require_query_rate_limits(request)
        intent = 'detail'
        args = {}
        name = "list_products"
        page_match = re.fullmatch(r"查看演示商品第([1-9][0-9]?|100)页", payload.text)
        if page_match:
            args = {"page": int(page_match.group(1))}
        elif payload.text != LIST_PRODUCTS_TEXT:
            product_id = payload.text.removeprefix(PRODUCT_SELECTION_PREFIX)
            if payload.text.startswith(PRODUCT_SELECTION_PREFIX):
                if product_id not in request.app.state.customer_service_fixtures:
                    raise ConsultationError(422, "invalid_input", "请选择受支持的商品查询")
                name, args = "get_product", {"product_id": product_id}
            else:
                if payload.text.startswith('查看演示商品第'):
                    raise ConsultationError(422, 'invalid_input', '请选择受支持的商品查询')
                from shop_api.customer_service_language import understand
                intent, name, args = understand(payload.text, request.app.state.customer_service_fixtures)
        # Commit a durable unknown-result claim before any orchestration. Crash replay
        # returns this claim and can never silently execute the turn again.
        claim = _envelope(request, 'unavailable', code='processing', message='已有请求结果未能确认')
        db.add(ConsultationMessage(consultation_id=consultation.id, page_id=page.id,
                                  client_message_id=UUID(payload.client_message_id), body_hash=body_hash, response=claim))
        db.commit()
        if name is None:
            now = request.app.state.clock()
            _lock_session(db, record, now)
            page, consultation = _page(db, record, payload.page_instance_id, now)
            from shop_api.customer_service_policy import SYNTHETIC_LABEL, answer_policy_question
            started = time.monotonic()
            registry = request.app.state.customer_service_policy_registry
            index = request.app.state.customer_service_policy_index
            answer = answer_policy_question(payload.text, registry, index, now)
            if answer is None:
                response = _envelope(request, 'needs_clarification',
                                     {'reply': '请提供完整演示商品名称，并询问价格或库存；也可咨询标注为虚构演示的政策主题。',
                                      'cards': [], 'citations': []})
            else:
                data = {'reply': answer.reply, 'cards': [], 'citations': list(answer.citations)}
                if registry is not None and index is not None:
                    data.update({'synthetic': True, 'policy_notice': SYNTHETIC_LABEL})
                response = _envelope(request, _POLICY_ENVELOPE_STATUS[answer.status], data,
                                     **({'code': answer.code} if answer.code else {}))
                if answer.status != 'needs_clarification':
                    request.app.state.customer_service_log_writer.write(
                        request.state.customer_service_request_id, 'search_policy', answer.code or '',
                        int((time.monotonic() - started) * 1000), len(answer.citations), now)
            _store_response(db, key, response)
            page.last_used_at = consultation.last_used_at = request.app.state.clock()
            db.commit()
            return response
        from shop_api.customer_service_product_mcp import ProductMCP
        query_deadline = QueryDeadline(max(0, deadline - time.monotonic()))
        tools = ProductTools(db, request.app.state.customer_service_fixtures,
                             request.state.customer_service_request_id, request.app.state.clock, deadline=query_deadline)
        mcp = ProductMCP(tools, deadline=deadline)
        try:
            mcp.initialize()
            mcp.tools()
            transport = getattr(request.app.state, 'customer_service_synthetic_transport', None)
            if intent == 'price_stock' and transport is not None:
                from shop_api.customer_service_model_loop import run_product_loop
                result = run_product_loop(request, record.id, deadline, mcp, args['product_id'], transport)
            else:
                result = mcp.call(name, args)
        finally:
            mcp.close()
        db.commit()
        # Delivery revalidates auth/page after the independent budget transactions.
        now = request.app.state.clock()
        _lock_session(db, record, now)
        require_product_reader(request, record, db)
        page, consultation = _page(db, record, payload.page_instance_id, now)
        query_deadline.check()
        degraded = result.pop('model_degraded', False)
        products = result["data"]["items"] if name == "list_products" else [result["data"]]
        cards = [{"type": "product", "product": product,
                  "selection_text": PRODUCT_SELECTION_PREFIX + product["id"]} for product in products]
        if name == "list_products" and result["data"]["has_more"]:
            cards.append({"type": "product_page", "selection_text": f"查看演示商品第{result['data']['page'] + 1}页"})
        response = _envelope(request, 'partial' if degraded else result["status"], {"reply": "模型服务暂不可用，以下为已核验商品信息" if degraded else "已查询演示商品信息" if products else "未找到可访问的记录",
                                                          "cards": cards, "citations": []}, **({'code': degraded} if degraded else {}))
        # Log failure rolls back result persistence; there are no business writes here.
        request.app.state.customer_service_log_writer.write(request.state.customer_service_request_id, name, "", 0, len(products), now)
        _store_response(db, key, response)
        page.last_used_at = consultation.last_used_at = now
        db.commit()
        return response

    return router


def cleanup_consultations(session_factory, now: datetime) -> None:
    """Reclaim expired contexts and secrets under the same session locks as requests."""
    with session_factory.begin() as db:
        QueryDeadline(3).apply(db)
        records = db.scalars(select(AuthSession).where(AuthSession.id.in_(select(Consultation.session_id)))
                             .with_for_update(skip_locked=True)).all()
        for record in records:
            db.execute(update(ConsultationPage).where(
                ConsultationPage.session_id == record.id,
                ConsultationPage.handoff_expires_at <= now,
                ConsultationPage.handoff_hash.is_not(None),
            ).values(handoff_hash=None))
            doomed_consultations = select(Consultation.id).where(
                Consultation.session_id == record.id,
                (Consultation.last_used_at <= now - timedelta(minutes=30)) |
                (Consultation.created_at <= now - timedelta(hours=24)))
            doomed_page_ids = db.scalars(select(ConsultationPage.id).where(
                ConsultationPage.session_id == record.id,
                (ConsultationPage.last_used_at <= now - timedelta(minutes=10)) |
                ConsultationPage.consultation_id.in_(doomed_consultations))).all()
            # Terminal evidence survives; only this page's pending credential is revoked.
            invalidate_pending_proposals_for_pages(db, doomed_page_ids, now)
            db.execute(delete(Consultation).where(Consultation.session_id == record.id,
                       (Consultation.last_used_at <= now - timedelta(minutes=30)) |
                       (Consultation.created_at <= now - timedelta(hours=24))))
            db.execute(delete(ConsultationPage).where(ConsultationPage.session_id == record.id,
                                                    ConsultationPage.last_used_at <= now - timedelta(minutes=10)))
