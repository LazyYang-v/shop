"""One routed specialist per turn, with facts supplied by bounded local MCP tools."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import timedelta
import json
import re
import time
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from shop_api.customer_service import CustomerServiceUnavailable, QueryDeadline
from shop_api.customer_service_integrated import StorefrontProductTools, route_message
from shop_api.customer_service_orders import OrderTools
from shop_api.customer_service_product_mcp import CustomerServiceMCP
from shop_api.customer_service_support import (
    ORDER_REQUESTS, REQUEST_KINDS, SupportCase, SupportChannel, SupportPreference,
    case_view, context_for, create_case, owned_order, record_event, redact_text, remember_turn,
)


_TASK_REQUESTS = {"reminder": "shipping_reminder", "address": "address_change", "invoice": "invoice",
                  "return": "return", "exchange": "exchange", "refund": "refund", "missing": "missing",
                  "damage": "damage", "wrong": "wrong_item", "warranty": "warranty", "replacement": "replacement",
                  "compensation": "compensation"}
_PROGRESS_TASKS: dict[str, str | None] = {task + "_progress": kind for task, kind in _TASK_REQUESTS.items()}
_PROGRESS_TASKS["service_progress"] = None


class KnowledgeTools:
    server_name = "shop-knowledge"
    tool_schemas = [
        {"name": "search_knowledge", "inputSchema": {
            "type": "object", "additionalProperties": False,
            "properties": {"query": {"type": "string", "maxLength": 2000},
                           "product_id": {"type": "string", "maxLength": 36},
                           "kind": {"type": "string", "enum": ["faq", "product", "policy", "promotion"]}},
            "required": ["query"]}},
        {"name": "public_product_knowledge", "inputSchema": {
            "type": "object", "additionalProperties": False,
            "properties": {"product_id": {"type": "string", "maxLength": 36}}, "required": ["product_id"]}},
        {"name": "recommend_products", "inputSchema": {
            "type": "object", "additionalProperties": False,
            "properties": {"query": {"type": "string", "maxLength": 2000}}, "required": ["query"]}},
    ]

    def __init__(self, db, request_id, clock, *, preferences=None):
        self.db, self.request_id, self.clock, self.calls = db, request_id, clock, 0
        self.preferences = preferences

    def call(self, name, arguments):
        from shop_api.customer_service_knowledge import public_product_knowledge, recommend_products, search_knowledge
        allowed = {"search_knowledge": {"query", "product_id", "kind"},
                   "public_product_knowledge": {"product_id"}, "recommend_products": {"query"}}
        if name not in allowed or self.calls >= 2 or set(arguments) - allowed[name]:
            raise HTTPException(422, "知识查询参数无效")
        self.calls += 1
        QueryDeadline(3).apply(self.db)
        try:
            if name == "public_product_knowledge":
                result = public_product_knowledge(self.db, UUID(arguments["product_id"]), self.clock())
            else:
                query = arguments.get("query")
                if not isinstance(query, str) or len(query) > 2000:
                    raise ValueError
                if name == "recommend_products":
                    result = recommend_products(self.db, query, self.clock(), preferences=self.preferences)
                    result["status"] = "ok" if result["items"] else "empty"
                else:
                    kind = arguments.get("kind")
                    result = search_knowledge(self.db, query, self.clock(),
                        product_id=UUID(arguments["product_id"]) if arguments.get("product_id") else None,
                        kinds=(kind,) if kind is not None else None)
        except (ValueError, TypeError, KeyError):
            raise HTTPException(422, "知识查询参数无效") from None
        return {"request_id": self.request_id, "queried_at": self.clock().isoformat(),
                "status": result["status"], "data": result}

    @staticmethod
    def verify_result(name, result):
        if (name not in {"search_knowledge", "public_product_knowledge", "recommend_products"}
                or not isinstance(result, dict) or set(result) != {"request_id", "queried_at", "status", "data"}
                or result["status"] not in {"ok", "empty", "conflict"}
                or not isinstance(result["data"], dict) or result["data"].get("status") != result["status"]
                or not isinstance(result["data"].get("items"), list)):
            raise CustomerServiceUnavailable
        for item in result["data"]["items"]:
            if name == "recommend_products":
                StorefrontProductTools._verify_product(item.get("product"))
            elif not isinstance(item, dict) or not {"id", "title", "body", "source", "version", "attributes", "product_id"} <= set(item):
                raise CustomerServiceUnavailable
        return result


def _call(db, request, toolset, name, arguments, consultation_id, buyer_id, deadline):
    mcp = CustomerServiceMCP(toolset, deadline=deadline)
    try:
        mcp.initialize()
        mcp.tools()
        result = mcp.call(name, arguments)
    except CustomerServiceUnavailable:
        record_event(db, request.app.state.clock(), "tool", consultation_id=consultation_id,
                     buyer_id=buyer_id, source=name, success=False)
        raise
    finally:
        mcp.close()
    record_event(db, request.app.state.clock(), "tool", consultation_id=consultation_id,
                 buyer_id=buyer_id, source=name, success=True)
    return result


def run_specialist(payload, request, record, db, page, consultation, buyer, *, deadline):
    """Return a response data object; the caller revalidates identity before commit."""
    from shop_api.customer_service_agents import ROLE_DEFINITIONS, classify
    from shop_api.customer_service_knowledge import explain_comparison, explain_size, parse_measurements
    from shop_api.customer_service_progress import ServiceProgressTools

    now = request.app.state.clock()
    context = context_for(db, consultation.id, now)
    state = dict(context.data)
    text = payload.text or ""
    decision = classify(text, state)
    legacy = route_message(text)
    if payload.selected_order_id is not None and not text:
        pending = state.get("pending_task")
        task = pending if pending in {*_TASK_REQUESTS, *_PROGRESS_TASKS, "payment", "logistics"} else "order_query"
        after_sales = task.removesuffix("_progress") in set(_TASK_REQUESTS) - {"reminder", "address", "invoice"}
        decision = replace(decision, role="after_sales" if after_sales else "orders_logistics",
                           intent="after_sales" if after_sales else "logistics" if task == "logistics" else "order",
                           task=task, path="workflow", confidence=1.0)
    if legacy.product_id:
        decision = replace(decision, role="presales", intent="presales", path="knowledge", confidence=1.0,
                           task="size" if state.get("pending_task") == "size" else "product_detail")
    channel = db.get(SupportChannel, "storefront")
    threshold = channel.settings.get("handoff_threshold", 0.45) if channel else 0.45
    corrections = int(state.get("corrections", 0)) + 1 if decision.correction else 0
    state["corrections"] = corrections
    cards, parts, replies, citations, facts = [], [], [], [], []
    buyer_id = buyer.id if buyer else None
    toolset = StorefrontProductTools(db, request.state.customer_service_request_id, request.app.state.clock)
    def call(tools, name, args):
        if name not in ROLE_DEFINITIONS[decision.role].allowed_tools:
            raise CustomerServiceUnavailable("当前客服职责不允许使用此工具")
        return _call(db, request, tools, name, args, consultation.id, buyer_id, deadline)
    if decision.emotion == "angry":
        replies.append("这次购物让你很生气，我理解你希望尽快有明确的处理结果。我先核对事实，再说明接下来由谁处理。")
    elif decision.emotion == "anxious":
        replies.append("我理解你比较着急，我们先确认当前进度和下一步。")
    faq_entries = []
    if decision.task == "clarify" and not decision.correction and not decision.explicit_handoff:
        faq_entries = _knowledge(db, request, call, text, None, consultation.id, buyer_id, kind="faq")
        if faq_entries:
            decision = replace(decision, task="faq", path="knowledge", confidence=1.0)
    record_event(db, now, "turn", consultation_id=consultation.id, buyer_id=buyer_id,
                 role=decision.role, intent=decision.intent, emotion=decision.emotion,
                 path=decision.path, task=decision.task)

    escalation = ("explicit_request" if decision.explicit_handoff else "repeated_correction" if corrections >= 2
                  else "low_confidence" if decision.confidence < threshold else None)
    if escalation:
        concern = text if not decision.correction else state.get("concern", text)
        summary = {"concern": redact_text(concern), "verified_facts": state.get("facts", [])[-5:],
                   "executed_actions": [], "blocker": "需要人工进一步核实", "history": state.get("history", [])[-12:]}
        if buyer:
            case = create_case(db, buyer=buyer, request_key=f"auto:{consultation.id}", kind="human_handoff",
                               now=now, context=state, concern=concern, reason=escalation,
                               priority="urgent" if decision.emotion == "angry" else "normal")
            cards.append({"type": "support_case", "case": case_view(case)})
            replies.append("已创建人工交接工单，当前等待商城管理员接手。工单保留30天，只包含下方诉求和已核验事实；没有自动共享逐句对话。你可以补充信息或选择共享本次必要对话。")
            summary = {**summary, "case_id": str(case.id)}
        else:
            replies.append("这个问题需要人工进一步核对。请先登录商城买家账号，我会保留当前页面中的交接预览；登录后可创建可跟进工单。")
        cards.append({"type": "handoff_preview", "summary": summary})
        record_event(db, now, "handoff", consultation_id=consultation.id, buyer_id=buyer_id, reason=escalation)
        state["pending_task"] = None
    elif decision.correction:
        replies.append("谢谢指出。我先停止沿用上一条结论，请告诉我是商品、订单还是处理方式有误；再次答错时会进入人工交接。")
    elif decision.intent in {"order", "logistics"} or decision.task in {*_TASK_REQUESTS, *_PROGRESS_TASKS, "payment"}:
        state["pending_task"] = decision.task
        state["concern"] = redact_text(text or state.get("concern", ""))
        if not buyer:
            raise HTTPException(401, "请登录商城买家账号后查看本人订单")
        selected_id = page.selected_order_id if (payload.selected_order_id or
            page.selected_at is not None and page.selected_at + timedelta(minutes=10) > now) else None
        order_match = re.search(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", text)
        # A supplied identifier always filters candidates, never silently selects a different order.
        if order_match:
            selected_id = None
        order_tools = OrderTools(db, buyer, request.state.customer_service_request_id, request.app.state.clock)
        if selected_id is None:
            args = {"page": legacy.page}
            if order_match:
                args["order_number"] = order_match.group(0)
            result = call(order_tools, "list_my_orders", args)
            cards.extend({"type": "order", "order": item} for item in result["data"]["items"])
            parts.append({"source": "list_my_orders", "queried_at": result["queried_at"], "status": result["status"]})
            replies.append("请明确选择一笔本人订单，我再继续处理这项请求。" if result["data"]["items"] else "没有找到可访问的本人订单。")
            if result["data"]["has_more"] and legacy.page < 100:
                cards.append({"type": "order_page", "selection_text": f"查询我的订单第{legacy.page + 1}页"})
        else:
            result = call(order_tools, "get_my_order", {"order_id": str(selected_id)})
            order = result["data"]
            cards.append({"type": "order_detail", "order": order})
            parts.append({"source": "get_my_order", "queried_at": result["queried_at"], "status": "ok"})
            facts.append({"source": "get_my_order", "order_id": order["order_number"], "status": order["status"],
                          "total": order["total"], "queried_at": result["queried_at"]})
            if decision.task in _PROGRESS_TASKS:
                kind = _PROGRESS_TASKS[decision.task]
                arguments = {"order_id": str(selected_id)}
                if kind:
                    arguments["kind"] = kind
                progress = call(ServiceProgressTools(db, buyer, request.state.customer_service_request_id,
                                request.app.state.clock), "get_service_progress", arguments)
                cards.append({"type": "service_progress", "progress": progress["data"]})
                parts.append({"source": "get_service_progress", "status": progress["status"],
                              "queried_at": progress["queried_at"]})
                replies.append(progress["data"]["notice"])
                if not progress["data"]["items"]:
                    replies.append("当前未找到这笔订单对应的有效服务申请，请核对申请类型，或选择申请处理。")
            elif decision.task in _TASK_REQUESTS:
                kind = _TASK_REQUESTS[decision.task]
                replies.append(f"已核对你选择的本人订单。{REQUEST_KINDS[kind]}需要提交申请并经人工核对，创建申请不会改变订单或资金状态。")
                if kind in {"damage", "missing", "wrong_item", "replacement"}:
                    replies.append("请说明涉及商品、数量和收到的情况；请勿在对话中发送支付凭证、密码或完整收货地址。")
                if kind == "compensation":
                    replies.append("可以登记你的诉求和期望方案，金额与是否补偿由人工核定，我不会提前承诺。")
                if kind == "address_change":
                    replies.append("请在申请卡中选择商城地址簿中的地址。发货前由人工审核并再次核对订单状态。")
                cards.append({"type": "service_request", "kind": kind, "order_id": str(selected_id),
                              "concern": state.get("concern", text)})
            elif decision.task == "payment":
                if order["status"] == "pending_payment":
                    replies.append("该订单待支付，请在商城订单页查看支付截止时间并完成模拟支付。支付失败时先刷新核对状态；已超时订单不能继续支付，也不需要提供任何银行卡或验证码。")
                    cards.append({"type": "storefront_link", "href": "/?view=orders", "label": "前往商城订单页"})
                else:
                    replies.append("当前订单已经不是待支付状态，请在商城订单页核对状态，避免重复操作。")
            else:
                replies.append("已核对你选择的本人订单及商城已保存物流信息。")
                if decision.intent == "logistics" or decision.task == "logistics":
                    replies.append("物流公司、运单号和发货时间来自商城记录；承运商实时轨迹尚未配置。若物流异常，可提交人工核查工单。")
                    cards.append({"type": "service_request", "kind": "complaint", "order_id": str(selected_id),
                                  "concern": "请求核查物流异常：" + text})
                if order["status"] == "pending_payment":
                    replies.append("此单尚未支付，请留意支付截止时间。你可前往商城订单页支付，或使用取消确认卡。")
    elif decision.intent == "presales" or legacy.intent == "product_detail":
        if decision.task == "recommendation":
            preference = db.get(SupportPreference, buyer.id) if buyer else None
            preferences = preference.data if preference and preference.expires_at > now else None
            previous = state.get("recommendation_query", "") if state.get("pending_task") == "recommendation" else ""
            query = (previous + "；" + text).strip("；")[-1800:]
            knowledge_tools = KnowledgeTools(db, request.state.customer_service_request_id,
                                             request.app.state.clock, preferences=preferences)
            result = call(knowledge_tools, "recommend_products", {"query": query})
            recommendation = result["data"]
            parts.append({"source": "recommend_products", "status": result["status"], "queried_at": result["queried_at"]})
            state["recommendation_query"], state["pending_task"] = redact_text(query, 1800), "recommendation"
            state.pop("product_id", None)
            for item in recommendation["items"]:
                cards.append({"type": "product", "product": item["product"], "selection_text": "查看商品：" + item["product"]["id"]})
                replies.append(item["product"]["name"] + "：" + "；".join(item["reasons"]))
                citations.extend(item.get("knowledge", []))
            replies.extend(recommendation.get("needs", []))
            if not recommendation["items"]:
                replies.append("请补充预算、商品类别或使用场景，我会按目录和已登记属性筛选。")
        else:
            product_id = legacy.product_id
            if legacy.product_id and legacy.product_id != state.get("product_id"):
                state.pop("measurements", None)
            if decision.task != "size":
                state["pending_task"] = None
            if not product_id and decision.task in {"size", "product_detail"}:
                product_id = state.get("product_id")
            keyword = decision.keyword or (legacy.keyword if legacy.intent == "products" and decision.task == "products" else "")
            if decision.task == "size":
                state["pending_task"] = "size"
                state["measurements"] = {**state.get("measurements", {}), **parse_measurements(text)}
            if not keyword and not product_id:
                keyword = state.get("product_keyword", "")
            if legacy.comparison:
                result = call(toolset, "compare_products", {"names": list(legacy.comparison)})
                products = result["data"]["matched"]
                if result["data"]["missing"]:
                    replies.append("以下名称需要更准确的商品信息：" + "、".join(result["data"]["missing"]))
            elif product_id:
                result = call(toolset, "get_product", {"product_id": product_id})
                products = [result["data"]]
            else:
                result = call(toolset, "list_products", {"keyword": keyword[:100], "page": legacy.page, "page_size": 20})
                products = result["data"]["items"]
                if result["data"]["has_more"] and legacy.page < 100:
                    selection_text = f"查看商品第{legacy.page + 1}页" + ("：" + keyword if keyword else "")
                    cards.append({"type": "product_page", "selection_text": selection_text})
            source = "get_product" if product_id else "compare_products" if legacy.comparison else "list_products"
            parts.append({"source": source, "queried_at": result["queried_at"], "status": result["status"]})
            cards.extend({"type": "product", "product": item, "selection_text": "查看商品：" + item["id"]} for item in products)
            state["product_keyword"] = keyword
            if len(products) != 1 and not product_id:
                state.pop("product_id", None)
            if len(products) == 1:
                product = products[0]
                if product["id"] != state.get("product_id") and decision.task != "size":
                    state.pop("measurements", None)
                state["product_id"] = product["id"]
                replies.append(f"{product['name']}当前标价 ¥{product['price']}，可售库存 {product['stock']} 件。")
                citations.extend(_knowledge(db, request, call, text or product["name"], product["id"], consultation.id, buyer_id,
                                           product_facts=True))
            elif not products:
                replies.append("没有找到匹配的上架商品，请补充商品名称，或说明预算和使用场景。")
            else:
                replies.append("以下是匹配的商城在售商品。请选择具体商品核对参数，或指定两件商品比较。")
            if legacy.comparison and len(products) >= 2:
                for product in products[:2]:
                    citations.extend(_knowledge(db, request, call, product["name"], product["id"], consultation.id, buyer_id,
                                               product_facts=True))
                comparison = explain_comparison(products, citations)
                cards.append({"type": "product_comparison", "comparison": comparison})
                replies.extend(comparison.get("needs", []))
            if decision.task == "size":
                size = explain_size(citations, state.get("measurements", {}))
                if len(products) == 1:
                    cards.append({"type": "size_advice", "product_id": products[0]["id"],
                                  "product_name": products[0]["name"], "advice": size})
                replies.extend(size.get("recommendations", []))
                replies.extend(size.get("needs", []))
                if len(products) != 1:
                    replies.append("请先选择一件具体商品，我会继续使用你本次提供的尺寸核对它的尺码表。")
                elif size["status"] != "ok":
                    replies.append("还没有可用于这件商品的有效尺码依据，不能仅凭身高体重猜测尺码。")
            if citations and not legacy.comparison:
                replies.extend(entry["body"] for entry in citations[:3])
    elif decision.task == "greeting":
        replies.append(channel.settings.get("welcome", "你好，很高兴为你服务。") if channel else "你好，很高兴为你服务。")
        replies.append("你可以咨询商品参数、订单物流或售后，也可以告诉我需要人工处理的事项。")
    elif decision.path == "knowledge" or decision.intent in {"promotion", "after_sales"}:
        entries = faq_entries or _knowledge(db, request, call, text, None, consultation.id, buyer_id,
                             kind="promotion" if decision.intent == "promotion" else None)
        citations.extend(entries)
        if entries:
            replies.extend(item["body"] for item in entries)
        else:
            replies.append("暂时没有可唯一确认的当前有效规则。可以描述具体商品、活动或售后情况，我会先收集需要核对的信息，再交人工确认。")
    elif decision.intent == "complaint":
        state["concern"] = redact_text(text)
        replies.append("请告诉我具体发生了什么，以及你希望怎样处理。我可以核对本人订单，或按你的选择创建投诉工单。")
        cards.append({"type": "service_request", "kind": "complaint", "concern": text})
    else:
        replies.append(channel.settings.get("welcome", "你好，很高兴为你服务。") if channel else "你好，很高兴为你服务。")
        replies.append("你可以咨询商品参数与推荐、订单物流、活动规则、退换货或投诉；缺少信息时我会继续追问。")

    if not replies:
        replies.append("请补充具体商品、订单或希望的处理方式。")
    if text and not decision.correction and not escalation:
        state["concern"] = redact_text(text)
    for entry in citations[:6]:
        facts.append({"source": "public_product_knowledge" if entry.get("product_id") else "search_knowledge",
                      "knowledge_id": entry["id"], "version": entry["version"], "title": entry["title"],
                      "queried_at": now.isoformat()})
    context.data = state
    reply = "\n".join(replies)
    remember_turn(context, user_text=text or "买家明确选择本人订单", reply=reply,
                  decision=decision, now=now, facts=facts)
    return {"reply": reply, "cards": cards, "parts": parts, "citations": citations[:6],
            "route": decision.role, "decision": asdict(decision),
            "context_notice": "本次必要上下文保留至咨询过期；工单30天，主动保存的偏好90天。"}


def _knowledge(db, request, call, query, product_id, consultation_id, buyer_id, *, kind=None, product_facts=False):
    arguments = {"product_id": product_id} if product_facts else {"query": query}
    if product_id and not product_facts:
        arguments["product_id"] = product_id
    if kind:
        arguments["kind"] = kind
    result = call(KnowledgeTools(db, request.state.customer_service_request_id, request.app.state.clock),
                  "public_product_knowledge" if product_facts else "search_knowledge", arguments)
    record_event(db, request.app.state.clock(), "retrieval", consultation_id=consultation_id,
                 buyer_id=buyer_id, source="search_knowledge", hit=result["status"] == "ok", status=result["status"])
    return result["data"]["items"] if result["status"] == "ok" else []
