"""Deterministic customer-service routing over the storefront's current data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from shop_api.catalog import Product
from shop_api.customer_service import CustomerServiceUnavailable, QueryDeadline
from shop_api.customer_service_product_mcp import TOOLS
from shop_api.customer_service_products import GetProductArguments, ListProductsArguments


@dataclass(frozen=True)
class CustomerServiceRoute:
    role: Literal["presales", "orders_logistics", "after_sales", "complaint_appeasement", "entry_router"]
    intent: Literal["products", "product_detail", "orders", "complaint", "after_sales", "policy", "greeting", "unclear"]
    keyword: str = ""
    product_id: str | None = None
    page: int = 1
    comparison: tuple[str, ...] = ()


def route_message(text: str) -> CustomerServiceRoute:
    """Choose a bounded deterministic route; user text never grants tool access."""
    value = text.strip()
    compact = "".join(value.split())

    page_match = re.fullmatch(r"查看(?:演示)?商品第([1-9][0-9]?|100)页(?:[:：]([^\r\n]{1,100}))?", value)
    if page_match:
        return CustomerServiceRoute("presales", "products", keyword=page_match.group(2) or "",
                                    page=int(page_match.group(1)))

    order_page = re.fullmatch(r"(?:查看|查询)(?:我的)?订单第([1-9][0-9]?|100)页", compact)
    if order_page:
        return CustomerServiceRoute("orders_logistics", "orders", page=int(order_page.group(1)))

    selected = re.fullmatch(
        r"查看(?:演示)?商品[:：]([0-9a-fA-F-]{36})", compact)
    if selected:
        try:
            product_id = str(UUID(selected.group(1)))
        except ValueError:
            return CustomerServiceRoute("entry_router", "unclear")
        return CustomerServiceRoute("presales", "product_detail", product_id=product_id)

    order_id = re.fullmatch(r"(?:查看|查询)(?:我的)?订单[:：]([0-9a-fA-F-]{36})", compact)
    if order_id:
        try:
            UUID(order_id.group(1))
        except ValueError:
            return CustomerServiceRoute("entry_router", "unclear")
        return CustomerServiceRoute("orders_logistics", "orders")

    if re.fullmatch(r"申请取消订单", compact):
        return CustomerServiceRoute("after_sales", "after_sales")

    if re.search(r"人工客服|转人工|找人工|投诉|差评|生气|不满|受骗|被骗|欺骗|不靠谱|失望|太差劲|愤怒", value):
        return CustomerServiceRoute("complaint_appeasement", "complaint")

    comparison_text = re.sub(r"[？?。！!]+$", "", value).strip()
    prefix = re.match(r"(?:比较|对比)\s*", comparison_text)
    suffix = re.search(r"\s*(?:哪个(?:更好|好|更适合|更合适)|有什么区别|有什么不同|的区别)$", comparison_text)
    if prefix or suffix:
        names_text = comparison_text[prefix.end() if prefix else 0:suffix.start() if suffix else len(comparison_text)]
        names = tuple(name.strip() for name in re.split(r"\s*(?:和|与|vs\.?|VS\.?)\s*", names_text))
        if 2 <= len(names) <= 3 and all(names):
            return CustomerServiceRoute("presales", "products", comparison=names)

    from shop_api.customer_service_orders import looks_like_order_question
    if looks_like_order_question(value) or re.search(r"快递未到|物流异常|查看物流|查物流|物流信息", value):
        return CustomerServiceRoute("orders_logistics", "orders")

    if re.search(r"退款|退货|退换|换货|补发|赔偿|售后|催发货|发票|优惠券", value):
        return CustomerServiceRoute("after_sales", "after_sales")

    if compact in {"查看上架商品", "查看商品列表", "查看商城在售商品"} or re.fullmatch(r"(?:请问|请帮我|帮我)?(?:有哪些|有什么)?(?:商城)?(?:在售|上架)?商品(?:列表|目录)?[？?。]?", compact):
        return CustomerServiceRoute("presales", "products")

    if re.search(r"包邮|运费|活动|优惠|赠品|价格保护|多久发货|什么时候发货|发货时间|退换货政策", value):
        return CustomerServiceRoute("after_sales", "policy")

    if re.fullmatch(r"(?:你好|您好|在吗|嗨|谢谢|好的|收到)[？?。!！]*", compact):
        return CustomerServiceRoute("entry_router", "greeting")

    keyword = value
    for prefix in ("请问", "请帮我查询", "请帮我查看", "请帮我", "帮我查询", "帮我查看", "帮我", "麻烦", "我想了解", "我想看看", "查询", "查看", "看看"):
        if keyword.startswith(prefix):
            keyword = keyword[len(prefix):].strip()
            break
    keyword = re.sub(r"(?:的)?(?:多少钱还有多少库存|价格和库存|价格与库存|价格是多少|库存是多少|还有库存吗|多少钱|有货吗|商品信息|价格|库存|详情|怎么样)[？?。！!]*$", "", keyword).strip(" ，,。？?！!\t")
    keyword = re.sub(r"^(?:请问|这个|商品)\s*", "", keyword).strip()
    if keyword:
        return CustomerServiceRoute("presales", "products", keyword=keyword)
    return CustomerServiceRoute("entry_router", "unclear")


class StorefrontProductTools:
    """Small public-catalog tool set; only listed storefront products are visible."""

    tool_names = ("list_products", "get_product", "compare_products")
    tool_schemas = [*TOOLS, {"name": "compare_products", "inputSchema": {
        "type": "object", "additionalProperties": False,
        "properties": {"names": {"type": "array", "minItems": 2, "maxItems": 3,
                                   "items": {"type": "string", "minLength": 1, "maxLength": 100}}},
        "required": ["names"]}}]
    server_name = "shop-products"

    def __init__(self, session: Session, request_id: str, clock, *, deadline=None):
        self._session = session
        self._request_id = request_id
        self._clock = clock
        self._deadline = deadline or QueryDeadline(3.0)
        self._calls = 0
        self._seen: set[tuple[str, str]] = set()

    @staticmethod
    def verify_result(name: str, result: dict) -> dict:
        if not isinstance(result, dict) or set(result) != {"request_id", "queried_at", "status", "data"}:
            raise CustomerServiceUnavailable
        UUID(result["request_id"])
        if datetime.fromisoformat(result["queried_at"]).utcoffset() is None:
            raise CustomerServiceUnavailable
        data = result["data"]
        if name == "compare_products":
            if (result["status"] not in {"ok", "empty"} or not isinstance(data, dict)
                    or set(data) != {"matched", "missing"} or not isinstance(data["matched"], list)
                    or len(data["matched"]) > 3 or not isinstance(data["missing"], list)):
                raise CustomerServiceUnavailable
            for product in data["matched"]:
                StorefrontProductTools._verify_product(product)
            return result
        if name == "get_product":
            if result["status"] != "ok":
                raise CustomerServiceUnavailable
            StorefrontProductTools._verify_product(data)
            return result
        if name != "list_products" or not isinstance(data, dict) or set(data) != {
            "items", "total", "page", "page_size", "has_more"
        }:
            raise CustomerServiceUnavailable
        if (type(data["items"]) is not list or len(data["items"]) > 20
                or type(data["total"]) is not int or not 0 <= data["total"] <= 100_000
                or type(data["page"]) is not int or not 1 <= data["page"] <= 100
                or type(data["page_size"]) is not int or not 1 <= data["page_size"] <= 20
                or type(data["has_more"]) is not bool
                or result["status"] != ("ok" if data["items"] else "empty")):
            raise CustomerServiceUnavailable
        for product in data["items"]:
            StorefrontProductTools._verify_product(product)
        return result

    @staticmethod
    def _verify_product(product) -> None:
        if (not isinstance(product, dict) or set(product) != {"id", "name", "category", "price", "stock", "is_listed"}
                or str(UUID(product["id"])) != product["id"]
                or not isinstance(product["name"], str) or not 1 <= len(product["name"]) <= 160
                or not isinstance(product["category"], str) or not 1 <= len(product["category"]) <= 80
                or not isinstance(product["price"], str) or not re.fullmatch(r"[0-9]+\.[0-9]{2}", product["price"])
                or type(product["stock"]) is not int or product["stock"] < 0
                or product["is_listed"] is not True):
            raise CustomerServiceUnavailable

    def call(self, name: str, arguments: dict) -> dict:
        if name == "compare_products":
            if set(arguments) != {"names"} or not isinstance(arguments["names"], list) or any(not isinstance(item, str) for item in arguments["names"]):
                raise HTTPException(422, "商品对比参数无效")
            data = self.compare_products(tuple(arguments["names"]))
            return {"request_id": self._request_id, "queried_at": self._clock().isoformat(),
                    "status": "ok" if not data["missing"] else "empty", "data": data}
        if name not in self.tool_names or self._calls >= 2:
            raise HTTPException(status_code=422, detail="工具参数无效")
        try:
            if name == "list_products":
                params = ListProductsArguments.model_validate(arguments)
                params.keyword = params.keyword.strip()
            else:
                params = GetProductArguments.model_validate(arguments)
                params.product_id = str(UUID(params.product_id))
        except (ValidationError, ValueError):
            raise HTTPException(status_code=422, detail="工具参数无效") from None
        key = (name, str(params.model_dump(mode="json", exclude_none=False)))
        if key in self._seen:
            raise HTTPException(status_code=422, detail="重复商品工具调用")
        self._seen.add(key)
        self._calls += 1
        self._deadline.check()
        if isinstance(params, GetProductArguments):
            product = self._read(select(Product).where(
                Product.id == UUID(params.product_id), Product.is_listed.is_(True)), first=True)
            if product is None:
                raise HTTPException(status_code=403, detail="未找到可访问的记录")
            data = self._facts(product)
            status = "ok"
        else:
            statement = select(Product).where(Product.is_listed.is_(True))
            if params.keyword:
                escaped = params.keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                pattern = f"%{escaped}%"
                statement = statement.where(or_(Product.name.ilike(pattern, escape="\\"),
                                                Product.description.ilike(pattern, escape="\\")))
            total = self._read(select(func.count()).select_from(statement.subquery()), first=True)
            page_size = min(params.page_size, 20)
            rows = self._read(statement.order_by(Product.listed_at.desc(), Product.id.asc())
                              .offset((params.page - 1) * page_size).limit(page_size))
            items = [self._facts(product) for product in rows]
            data = {"items": items, "total": total, "page": params.page, "page_size": page_size,
                    "has_more": (params.page - 1) * page_size + len(items) < total and params.page < 100}
            status = "ok" if items else "empty"
        return {"request_id": self._request_id, "queried_at": self._clock().isoformat(), "status": status, "data": data}

    def _read(self, statement, *, first: bool = False):
        self._deadline.check()
        try:
            with self._session.begin_nested():
                self._deadline.apply(self._session, maximum_seconds=3.0)
                value = self._session.scalar(statement) if first else self._session.scalars(statement).all()
                self._deadline.check()
                return value
        except DBAPIError:
            raise CustomerServiceUnavailable from None

    def compare_products(self, names: tuple[str, ...]) -> dict:
        normalized = tuple(name.strip() for name in names)
        folded = tuple(name.casefold() for name in normalized)
        if (not 2 <= len(normalized) <= 3 or any(not 1 <= len(name) <= 100 for name in normalized)
                or len(set(folded)) != len(folded)):
            raise HTTPException(status_code=422, detail="商品对比参数无效")
        key = ("compare_products", str(normalized))
        if self._calls >= 2 or key in self._seen:
            raise HTTPException(status_code=422, detail="商品对比查询额度已用完")
        self._seen.add(key)
        self._calls += 1
        escaped = tuple(name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                        for name in normalized)
        statement = select(Product).where(
            Product.is_listed.is_(True),
            or_(*(Product.name.ilike(f"%{name}%", escape="\\") for name in escaped)),
        ).order_by(Product.listed_at.desc(), Product.id.asc())
        rows = self._read(statement.limit(201))
        if len(rows) > 200:
            raise HTTPException(422, "匹配商品太多，请提供完整名称")
        matched, missing, used = [], [], set()
        for label, needle in zip(normalized, folded):
            candidates = [product for product in rows if needle in product.name.casefold()]
            if len(candidates) != 1 or candidates[0].id in used:
                missing.append(label)
                continue
            used.add(candidates[0].id)
            matched.append(candidates[0])
        return {"matched": [self._facts(product) for product in matched], "missing": missing}

    @staticmethod
    def _facts(product: Product) -> dict:
        return {"id": str(product.id), "name": product.name, "category": product.category,
                "price": str(product.price), "stock": product.stock, "is_listed": product.is_listed}
