"""Buyer support and administrator review routes using the storefront session."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from shop_api.customer_service import QueryDeadline
from shop_api.customer_service_admission import require_query_rate_limits
from shop_api.customer_service_support import (
    CASE_STATUSES, CHANNELS, ORDER_REQUESTS, REQUEST_KINDS, SupportCase, SupportChannel,
    SupportContext, SupportEvent, SupportNotification, SupportPreference,
    case_view, create_case, notify, owned_order, record_event, redact_text,
)
from shop_api.identity import Role, require_csrf, require_role


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SupportRequestInput(StrictInput):
    page_instance_id: UUID
    consultation_id: UUID
    client_request_id: UUID
    kind: str = Field(max_length=32)
    selected_order_id: UUID | None = None
    concern: str = Field(default="", max_length=1200)
    share_history: bool = False
    address_id: UUID | None = None
    invoice_title: str = Field(default="", max_length=120)
    consent: Literal[True]


class CaseUpdateInput(StrictInput):
    status: Literal["in_progress", "waiting_buyer", "resolved", "rejected"]
    reply: str = Field(min_length=1, max_length=1200)
    expected_updated_at: datetime
    apply_address: bool = False


class CaseReplyInput(StrictInput):
    text: str = Field(min_length=1, max_length=1200)


class ShareContextInput(StrictInput):
    consultation_id: UUID
    consent: Literal[True]


class PreferenceInput(StrictInput):
    consent: Literal[True]
    categories: list[str] = Field(default_factory=list, max_length=6)
    occasion: str = Field(default="", max_length=100)
    budget_max: Decimal | None = Field(default=None, ge=0, le=1000000)


class FeedbackInput(StrictInput):
    consultation_id: UUID
    rating: int = Field(ge=1, le=5)
    resolved: bool


class KnowledgeInput(StrictInput):
    kind: Literal["faq", "product", "policy", "promotion"]
    topic: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=8000)
    source: str = Field(min_length=1, max_length=500)
    keywords: list[str] = Field(default_factory=list, max_length=20)
    attributes: dict = Field(default_factory=dict)
    product_id: UUID | None = None
    state: Literal["draft", "published", "retired"] = "draft"
    valid_from: datetime
    valid_until: datetime | None = None

    @model_validator(mode="after")
    def check_dates(self):
        if self.valid_from.utcoffset() is None or (self.valid_until and self.valid_until.utcoffset() is None):
            raise ValueError("Dates need timezone")
        if self.valid_until and self.valid_until <= self.valid_from:
            raise ValueError("Invalid effective interval")
        if any(not isinstance(word, str) or not 1 <= len(word) <= 80 for word in self.keywords):
            raise ValueError("Invalid keyword")
        import json
        if len(json.dumps(self.attributes, ensure_ascii=False)) > 12000:
            raise ValueError("Attributes too large")
        from shop_api.customer_service_knowledge import validate_product_attributes
        self.attributes = validate_product_attributes(self.attributes)
        return self


class ChannelInput(StrictInput):
    display_name: str = Field(min_length=1, max_length=80)
    welcome: str = Field(default="欢迎咨询商城客服", max_length=300)
    handoff_threshold: float = Field(default=0.45, ge=0.2, le=0.8)


def build_support_router(session_dependency, current_session) -> APIRouter:
    router = APIRouter()

    def enabled(request: Request, response: Response, db: Session = Depends(session_dependency)):
        response.headers["Cache-Control"] = "no-store"
        if (request.app.state.customer_service_mode != "integrated"
                or not request.app.state.customer_service_enabled):
            raise HTTPException(503, "商城客服暂不可用")
        QueryDeadline(3).apply(db)

    def buyer(request: Request, record=Depends(current_session), db: Session = Depends(session_dependency),
              _=Depends(enabled)):
        if request.method != "GET":
            require_csrf(request, record, request.headers.get("X-CSRF-Token"), request.headers.get("Origin"))
        return require_role(db, record, Role.BUYER)

    def admin(request: Request, record=Depends(current_session), db: Session = Depends(session_dependency),
              _=Depends(enabled)):
        if request.method != "GET":
            require_csrf(request, record, request.headers.get("X-CSRF-Token"), request.headers.get("Origin"))
        return require_role(db, record, Role.ADMIN)

    @router.get("/api/customer-service/history")
    def history(consultation_id: UUID, request: Request, record=Depends(current_session),
                db: Session = Depends(session_dependency), _=Depends(enabled)):
        from shop_api.customer_service_consultations import Consultation, _consultation_expired
        row = db.get(Consultation, consultation_id)
        if row is None or row.session_id != record.id or _consultation_expired(row, request.app.state.clock()):
            raise HTTPException(403, "未找到可访问的记录")
        context = db.get(SupportContext, consultation_id)
        return {"items": (context.data.get("history", []) if context else []),
                "retention": "当前咨询空闲30分钟或创建24小时后删除；人工工单另存30天"}

    @router.get("/api/customer-service/faq-hints")
    def faq_hints(request: Request, _=Depends(enabled), db: Session = Depends(session_dependency)):
        from shop_api.customer_service_knowledge import faq_hints as current_faq_hints
        require_query_rate_limits(request)
        return {"items": current_faq_hints(db, request.app.state.clock())}

    @router.post("/api/customer-service/requests", status_code=201)
    def support_request(payload: SupportRequestInput, request: Request, user=Depends(buyer),
                        record=Depends(current_session), db: Session = Depends(session_dependency)):
        from shop_api.customer_service_consultations import _lock_session, _page
        now = request.app.state.clock()
        _lock_session(db, record, now)
        page, consultation = _page(db, record, str(payload.page_instance_id), now)
        if consultation.id != payload.consultation_id:
            raise HTTPException(403, "未找到可访问的记录")
        if payload.kind not in REQUEST_KINDS:
            raise HTTPException(422, "申请类型无效")
        order = None
        if payload.kind in ORDER_REQUESTS:
            if payload.selected_order_id != page.selected_order_id:
                raise HTTPException(409, "订单选择已变化，请重新核对申请卡")
            if page.selected_order_id is None or page.selected_at is None or page.selected_at + timedelta(minutes=10) <= now:
                raise HTTPException(409, "请重新明确选择本人订单")
            order = owned_order(db, user, page.selected_order_id, lock=True)
        details = {}
        if payload.kind == "address_change":
            from shop_api.addresses import Address
            if payload.address_id is None:
                raise HTTPException(422, "请选择商城地址簿中的地址")
            address = db.get(Address, payload.address_id)
            if address is None or address.user_id != user.id:
                raise HTTPException(403, "未找到可访问的记录")
            details["address_id"] = str(address.id)
            details["requested_address"] = {key: getattr(address, key) for key in
                ("recipient_name", "phone", "province", "city", "district", "detail")}
            details["original_address"] = {key: getattr(order, key) for key in
                ("recipient_name", "phone", "province", "city", "district", "detail")}
        if payload.kind == "invoice":
            if not payload.invoice_title.strip():
                raise HTTPException(422, "请填写发票抬头")
            details["invoice_title"] = redact_text(payload.invoice_title, 120)
        if payload.kind in {"return", "exchange", "refund", "damage", "missing", "wrong_item", "replacement", "compensation"} and len(payload.concern.strip()) < 4:
            raise HTTPException(422, "请补充问题、数量或希望的处理方式")
        context = db.get(SupportContext, consultation.id)
        data = context.data if context else {}
        row = create_case(db, buyer=user, request_key=f"request:{payload.client_request_id}", kind=payload.kind,
                          now=now, context=data, concern=payload.concern, order=order, details=details,
                          share_history=payload.share_history,
                          priority="urgent" if data.get("last_emotion") == "angry" else "normal")
        db.commit()
        return {"case": case_view(row), "notice": "申请已进入商城人工队列，尚未接手；需人工审核后回复。不会自动退款或补偿。"}

    @router.get("/api/customer-service/service-progress")
    def service_progress(order_id: UUID, page_instance_id: UUID, consultation_id: UUID, request: Request,
                         kind: str | None = Query(None, max_length=32), user=Depends(buyer),
                         record=Depends(current_session), db: Session = Depends(session_dependency)):
        from shop_api.customer_service import CustomerServiceUnavailable
        from shop_api.customer_service_consultations import ConsultationError, _lock_session, _order_probe_rate, _page
        from shop_api.customer_service_product_mcp import CustomerServiceMCP, CustomerServiceMCPFailure
        from shop_api.customer_service_progress import ServiceProgressTools

        allowed = {"order_id", "kind", "page_instance_id", "consultation_id"}
        if set(request.query_params) - allowed or any(len(request.query_params.getlist(key)) != 1
                                                     for key in request.query_params):
            raise HTTPException(422, "请求参数无效")
        if kind is not None and kind not in REQUEST_KINDS:
            raise HTTPException(422, "申请类型无效")
        now = request.app.state.clock()
        try:
            _lock_session(db, record, now)
            page, consultation = _page(db, record, str(page_instance_id), now)
            _order_probe_rate(request, user)
        except ConsultationError as error:
            raise HTTPException(error.status_code, error.message, headers=error.headers) from None
        except CustomerServiceUnavailable:
            raise HTTPException(503, "服务申请进度暂不可用") from None
        if consultation.id != consultation_id or consultation.session_id != record.id:
            raise HTTPException(403, "未找到可访问的记录")
        if page.selected_order_id != order_id:
            raise HTTPException(409, "请明确选择要查询的本人订单")
        if page.selected_at is None or not now - timedelta(minutes=10) < page.selected_at <= now:
            raise HTTPException(409, "请重新明确选择本人订单")
        arguments = {"order_id": str(order_id)}
        if kind is not None:
            arguments["kind"] = kind
        mcp = CustomerServiceMCP(ServiceProgressTools(db, user, str(uuid4()), request.app.state.clock))
        try:
            mcp.initialize()
            return mcp.call("get_service_progress", arguments)
        except CustomerServiceMCPFailure as error:
            if error.code == "resource_unavailable":
                raise HTTPException(403, "未找到可访问的记录") from None
            raise HTTPException(503, "服务申请进度暂不可用") from None
        except CustomerServiceUnavailable:
            raise HTTPException(503, "服务申请进度暂不可用") from None
        finally:
            mcp.close()

    @router.get("/api/customer-service/cases")
    def buyer_cases(request: Request, user=Depends(buyer), db: Session = Depends(session_dependency)):
        rows = db.scalars(select(SupportCase).where(SupportCase.buyer_id == user.id,
                          SupportCase.expires_at > request.app.state.clock())
                          .order_by(SupportCase.created_at.desc()).limit(50)).all()
        return {"items": [case_view(row) for row in rows]}

    @router.post("/api/customer-service/cases/{case_id}/replies")
    def buyer_reply(case_id: UUID, payload: CaseReplyInput, request: Request,
                    user=Depends(buyer), db: Session = Depends(session_dependency)):
        row = db.scalar(select(SupportCase).where(SupportCase.id == case_id, SupportCase.buyer_id == user.id,
                        SupportCase.expires_at > request.app.state.clock()).with_for_update())
        if row is None:
            raise HTTPException(403, "未找到可访问的记录")
        if len(row.messages) >= 50:
            raise HTTPException(409, "工单消息已满，请另建工单")
        now = request.app.state.clock()
        row.messages = [*row.messages, {"role": "buyer", "text": redact_text(payload.text), "at": now.isoformat()}]
        if row.status in {"waiting_buyer", "resolved", "rejected"}:
            row.status = "in_progress" if row.assigned_to else "open"
        row.updated_at = now
        db.commit()
        return {"case": case_view(row)}

    @router.post("/api/customer-service/cases/{case_id}/share-context")
    def share_context(case_id: UUID, payload: ShareContextInput, request: Request,
                      user=Depends(buyer), record=Depends(current_session), db: Session = Depends(session_dependency)):
        from shop_api.customer_service_consultations import Consultation, _consultation_expired
        now = request.app.state.clock()
        consultation = db.get(Consultation, payload.consultation_id)
        row = db.scalar(select(SupportCase).where(SupportCase.id == case_id, SupportCase.buyer_id == user.id,
                        SupportCase.expires_at > now).with_for_update())
        if (row is None or consultation is None or consultation.session_id != record.id
                or _consultation_expired(consultation, now)):
            raise HTTPException(403, "未找到可访问的记录")
        context = db.get(SupportContext, consultation.id)
        summary = dict(row.summary)
        summary.update(history=list(context.data.get("history", []))[-12:] if context else [], history_shared=True)
        row.summary, row.updated_at = summary, now
        record_event(db, now, "history_shared", case_id=row.id, buyer_id=user.id, action="buyer_consent")
        db.commit()
        return {"case": case_view(row)}

    @router.get("/api/customer-service/preferences")
    def read_preferences(request: Request, user=Depends(buyer), db: Session = Depends(session_dependency)):
        row = db.get(SupportPreference, user.id)
        active = row is not None and row.expires_at > request.app.state.clock()
        return {"data": row.data if active else {}, "expires_at": row.expires_at.isoformat() if active else None}

    @router.put("/api/customer-service/preferences")
    def preferences(payload: PreferenceInput, request: Request, user=Depends(buyer), db: Session = Depends(session_dependency)):
        if any(not 1 <= len(item) <= 40 for item in payload.categories):
            raise HTTPException(422, "分类无效")
        now = request.app.state.clock()
        row = db.get(SupportPreference, user.id) or SupportPreference(buyer_id=user.id)
        row.data = {"categories": [redact_text(item, 40) for item in payload.categories],
                    "occasion": redact_text(payload.occasion, 100),
                    "budget_max": str(payload.budget_max) if payload.budget_max is not None else None}
        row.updated_at, row.expires_at = now, now + timedelta(days=90)
        db.add(row)
        db.commit()
        return {"data": row.data, "expires_at": row.expires_at.isoformat()}

    @router.delete("/api/customer-service/preferences", status_code=204)
    def delete_preferences(user=Depends(buyer), db: Session = Depends(session_dependency)):
        row = db.get(SupportPreference, user.id)
        if row:
            db.delete(row)
        db.commit()
        return Response(status_code=204)

    @router.post("/api/customer-service/feedback")
    def feedback(payload: FeedbackInput, request: Request, user=Depends(buyer),
                 record=Depends(current_session), db: Session = Depends(session_dependency)):
        from shop_api.customer_service_consultations import Consultation, _lock_session, _consultation_expired
        now = request.app.state.clock()
        _lock_session(db, record, now)
        consultation = db.get(Consultation, payload.consultation_id)
        if consultation is None or consultation.session_id != record.id or _consultation_expired(consultation, now):
            raise HTTPException(403, "未找到可访问的记录")
        row = db.scalar(select(SupportEvent).where(SupportEvent.kind == "feedback",
                         SupportEvent.consultation_id == consultation.id))
        if row:
            row.data, row.created_at = {"rating": payload.rating, "resolved": payload.resolved}, now
        else:
            record_event(db, now, "feedback", buyer_id=user.id, consultation_id=consultation.id,
                         rating=payload.rating, resolved=payload.resolved)
        db.commit()
        return {"saved": True}

    @router.get("/api/customer-service/notifications")
    def notifications(request: Request, user=Depends(buyer), db: Session = Depends(session_dependency)):
        rows = db.scalars(select(SupportNotification).where(SupportNotification.buyer_id == user.id,
                SupportNotification.created_at > request.app.state.clock() - timedelta(days=30))
                .order_by(SupportNotification.created_at.desc()).limit(50)).all()
        return {"items": [{"id": str(row.id), "text": row.text, "created_at": row.created_at.isoformat(),
                           "read": row.read_at is not None} for row in rows]}

    @router.post("/api/customer-service/notifications/{notification_id}/read")
    def read_notification(notification_id: UUID, request: Request, user=Depends(buyer),
                          db: Session = Depends(session_dependency)):
        row = db.scalar(select(SupportNotification).where(SupportNotification.id == notification_id,
                SupportNotification.buyer_id == user.id).with_for_update())
        if row is None:
            raise HTTPException(403, "未找到可访问的记录")
        row.read_at = request.app.state.clock()
        db.commit()
        return {"read": True}

    @router.get("/api/admin/customer-service/cases")
    def admin_cases(request: Request, status: str | None = None, page: int = Query(1, ge=1),
                    user=Depends(admin), db: Session = Depends(session_dependency)):
        stmt = select(SupportCase).where(SupportCase.expires_at > request.app.state.clock())
        if status:
            if status not in CASE_STATUSES:
                raise HTTPException(422, "状态无效")
            stmt = stmt.where(SupportCase.status == status)
        total = db.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = db.scalars(stmt.order_by(SupportCase.created_at.desc(), SupportCase.id)
                          .offset((page - 1) * 20).limit(20)).all()
        return {"items": [case_view(row, admin=True) for row in rows], "total": total, "page": page}

    @router.patch("/api/admin/customer-service/cases/{case_id}")
    def review_case(case_id: UUID, payload: CaseUpdateInput, request: Request,
                    user=Depends(admin), db: Session = Depends(session_dependency)):
        now = request.app.state.clock()
        row = db.scalar(select(SupportCase).where(SupportCase.id == case_id, SupportCase.expires_at > now).with_for_update())
        if row is None:
            raise HTTPException(404, "工单不存在")
        if payload.expected_updated_at != row.updated_at:
            raise HTTPException(409, "工单已被更新，请刷新后重试")
        if row.assigned_to and row.assigned_to != user.id:
            raise HTTPException(409, "工单已由其他管理员接手")
        if row.status in {"resolved", "rejected"}:
            raise HTTPException(409, "工单已结束；买家补充问题后可重新处理")
        if len(row.messages) >= 50:
            raise HTTPException(409, "工单消息已满")
        previous = row.status
        if payload.apply_address:
            if row.kind != "address_change" or payload.status != "resolved":
                raise HTTPException(422, "地址审核动作无效")
            from shop_api.addresses import Address
            from shop_api.orders import Order
            order = db.scalar(select(Order).where(Order.id == row.order_id,
                    Order.user_id == row.buyer_id).with_for_update().execution_options(populate_existing=True))
            address = db.get(Address, UUID(row.details["address_id"]), with_for_update=True)
            requested = row.details.get("requested_address", {})
            if (order is None or order.status != "pending_shipment" or address is None or address.user_id != row.buyer_id
                    or requested != {key: getattr(address, key) for key in requested}
                    or len(requested) != 6):
                raise HTTPException(409, "订单或地址状态已变化，未修改订单")
            # Copy only the buyer-selected saved address; never accept an administrator-supplied address.
            order.address_id = address.id
            order.recipient_name = address.recipient_name
            order.phone = address.phone
            order.province = address.province
            order.city = address.city
            order.district = address.district
            order.detail = address.detail
            summary = dict(row.summary)
            summary["executed_actions"] = [{"action": "address_change", "order_id": str(order.id), "at": now.isoformat()}]
            row.summary = summary
        row.assigned_to, row.status, row.updated_at = user.id, payload.status, now
        row.messages = [*row.messages, {"role": "staff", "text": redact_text(payload.reply), "at": now.isoformat()}]
        record_event(db, now, "case_review", buyer_id=row.buyer_id, case_id=row.id, action=row.kind,
                     from_status=previous, to_status=row.status)
        notify(db, row.buyer_id, f"case:{row.id}:{uuid4()}",
               f"你的{REQUEST_KINDS[row.kind]}工单有新回复，当前状态：{row.status}。请在客服工单中查看。", now)
        db.commit()
        return {"case": case_view(row, admin=True)}

    @router.get("/api/admin/customer-service/knowledge")
    def knowledge_list(user=Depends(admin), db: Session = Depends(session_dependency)):
        from shop_api.customer_service_knowledge import KnowledgeEntry
        rows = db.scalars(select(KnowledgeEntry).order_by(KnowledgeEntry.updated_at.desc()).limit(200)).all()
        return {"items": [{"id": str(row.id), "kind": row.kind, "topic": row.topic, "title": row.title,
                           "body": row.body, "source": row.source, "keywords": row.keywords,
                           "attributes": row.attributes, "product_id": str(row.product_id) if row.product_id else None,
                           "version": row.version, "state": row.state,
                           "valid_from": row.valid_from.isoformat(), "valid_until": row.valid_until.isoformat() if row.valid_until else None}
                          for row in rows]}

    @router.post("/api/admin/customer-service/knowledge", status_code=201)
    def publish_knowledge(payload: KnowledgeInput, request: Request, user=Depends(admin),
                          db: Session = Depends(session_dependency)):
        from shop_api.catalog import Product
        from shop_api.customer_service_knowledge import KnowledgeEntry
        if payload.product_id and db.get(Product, payload.product_id) is None:
            raise HTTPException(422, "商品不存在")
        if payload.kind == "product" and payload.product_id is None:
            raise HTTPException(422, "商品知识必须绑定商品")
        # Serialize publication per topic. No overlapping active version is silently chosen.
        db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                   {"key": f"knowledge:{payload.kind}:{payload.topic}:{payload.product_id}"})
        previous = db.scalars(select(KnowledgeEntry).where(KnowledgeEntry.kind == payload.kind,
                         KnowledgeEntry.topic == payload.topic, KnowledgeEntry.product_id == payload.product_id)
                         .with_for_update()).all()
        if payload.state == "published":
            for item in previous:
                if (item.state == "published" and (item.valid_until is None or item.valid_until > payload.valid_from)
                        and (payload.valid_until is None or item.valid_from < payload.valid_until)):
                    raise HTTPException(409, "已有生效区间重叠的发布版本，请先撤回旧版本")
        now = request.app.state.clock()
        row = KnowledgeEntry(id=uuid4(), **payload.model_dump(),
                             version=max((item.version for item in previous), default=0) + 1,
                             created_at=now, updated_at=now)
        db.add(row)
        record_event(db, now, "knowledge_publish", status=row.state, version=row.version, action=row.kind)
        db.commit()
        return {"id": str(row.id), "version": row.version, "state": row.state}

    @router.post("/api/admin/customer-service/knowledge/{entry_id}/retire")
    def retire_knowledge(entry_id: UUID, request: Request, user=Depends(admin), db: Session = Depends(session_dependency)):
        from shop_api.customer_service_knowledge import KnowledgeEntry
        row = db.get(KnowledgeEntry, entry_id, with_for_update=True)
        if row is None:
            raise HTTPException(404, "知识条目不存在")
        row.state, row.updated_at = "retired", request.app.state.clock()
        record_event(db, row.updated_at, "knowledge_retire", version=row.version, action=row.kind)
        db.commit()
        return {"state": row.state}

    @router.get("/api/admin/customer-service/metrics")
    def metrics(request: Request, days: int = Query(7, ge=1, le=30), user=Depends(admin), db: Session = Depends(session_dependency)):
        now = request.app.state.clock()
        rows = db.scalars(select(SupportEvent).where(SupportEvent.created_at >= now - timedelta(days=days))
                          .order_by(SupportEvent.created_at).limit(100001)).all()
        if len(rows) > 100000:
            raise HTTPException(422, "样本过多，请缩短时间范围")
        turns = [row for row in rows if row.kind == "turn"]
        consultations = {row.consultation_id for row in turns}
        feedbacks = [row for row in rows if row.kind == "feedback"]
        tools = [row for row in rows if row.kind == "tool"]
        retrievals = [row for row in rows if row.kind == "retrieval"]
        handoffs = {row.consultation_id for row in rows if row.kind == "handoff"}
        ratio = lambda numerator, denominator: {"numerator": numerator, "denominator": denominator,
                                               "value": numerator / denominator if denominator else None}
        routes = {}
        for row in turns:
            intent = row.data.get("intent", "other")
            routes[intent] = routes.get(intent, 0) + 1
        return {"days": days, "from": (now - timedelta(days=days)).isoformat(), "to": now.isoformat(),
                "turns": len(turns), "consultations": len(consultations), "routes": routes,
                "resolution_rate": ratio(sum(row.data.get("resolved") is True for row in feedbacks), len(feedbacks)),
                "handoff_rate": ratio(len(handoffs & consultations), len(consultations)),
                "tool_success_rate": ratio(sum(row.data.get("success") is True for row in tools), len(tools)),
                "retrieval_hit_rate": ratio(sum(row.data.get("hit") is True for row in retrievals), len(retrievals)),
                "satisfaction": ratio(sum(row.data.get("rating", 0) >= 4 for row in feedbacks), len(feedbacks)),
                "definitions": {"resolution_rate": "在窗口内提交反馈的咨询中，买家明确标记已解决的比例",
                    "handoff_rate": "在窗口内有对话的咨询中，触发人工升级的比例（不等于人工接手）",
                    "tool_success_rate": "工具调用正常返回次数 / 工具调用总次数（空结果也计正常）",
                    "retrieval_hit_rate": "找到当前有效且无冲突依据的检索次数 / 检索总次数",
                    "satisfaction": "4或5分反馈数 / 有评分反馈数"}}

    @router.get("/api/admin/customer-service/channels")
    def channels(user=Depends(admin), db: Session = Depends(session_dependency)):
        saved = {row.name: row.settings for row in db.scalars(select(SupportChannel)).all()}
        return {"items": [{"name": name, "connected": name == "storefront",
                           "adapter": "storefront_session" if name == "storefront" else "not_configured",
                           "settings": saved.get(name, {"display_name": name, "welcome": "欢迎咨询商城客服", "handoff_threshold": 0.45})}
                          for name in CHANNELS]}

    @router.put("/api/admin/customer-service/channels/{name}")
    def configure_channel(name: str, payload: ChannelInput, request: Request,
                          user=Depends(admin), db: Session = Depends(session_dependency)):
        if name not in CHANNELS:
            raise HTTPException(422, "渠道无效")
        row = db.get(SupportChannel, name) or SupportChannel(name=name)
        row.settings, row.updated_at = payload.model_dump(), request.app.state.clock()
        db.add(row)
        record_event(db, row.updated_at, "channel_config", action=name)
        db.commit()
        return {"name": name, "connected": name == "storefront", "settings": row.settings}

    return router
