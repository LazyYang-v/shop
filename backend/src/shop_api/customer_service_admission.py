"""Shared controlled-demo identity and query quota admission boundaries."""

import hashlib

from fastapi import HTTPException, Request

from shop_api.customer_service import CustomerServiceUnavailable
from shop_api.identity import Role, User, require_role


def require_demo_buyer(request: Request, record, db):
    if not request.app.state.customer_service_enabled:
        raise HTTPException(status_code=503, detail="客服暂不可用")
    buyer = require_role(db, record, Role.BUYER)
    if (getattr(request.app.state, "customer_service_mode", "demo") != "integrated"
            and buyer.id not in request.app.state.customer_service_buyer_ids):
        raise HTTPException(status_code=403, detail="未找到可访问的记录")
    return buyer


def require_product_reader(request: Request, record, db):
    """Anonymous and signed-in sessions may read the public catalog."""
    if not request.app.state.customer_service_enabled:
        raise HTTPException(status_code=503, detail="客服暂不可用")
    if record.kind == "anonymous" and record.user_id is None:
        return None
    if getattr(request.app.state, "customer_service_mode", "demo") == "integrated":
        if record.kind != "authenticated" or record.user_id is None:
            raise HTTPException(status_code=401, detail="需要登录")
        user = db.get(User, record.user_id)
        if user is None or not user.is_active or user.role not in {Role.BUYER.value, Role.ADMIN.value}:
            raise HTTPException(status_code=401, detail="需要登录")
        return user
    return require_demo_buyer(request, record, db)


def require_query_rate_limits(request: Request) -> None:
    if request.client is None:
        raise HTTPException(status_code=503, detail="客服查询保护暂不可用")
    keys = (
        (f"session:{hashlib.sha256(request.cookies.get('shop_session', '').encode()).hexdigest()}", 20),
        (f"ip:{hashlib.sha256(request.client.host.encode()).hexdigest()}", 60),
    )
    try:
        for key, limit in keys:
            allowed, retry_after = request.app.state.customer_service_limiter.allow(
                key, limit, 60, request.app.state.clock())
            if not allowed:
                raise HTTPException(status_code=429, detail="查询过于频繁", headers={"Retry-After": str(retry_after)})
    except CustomerServiceUnavailable:
        raise HTTPException(status_code=503, detail="客服查询保护暂不可用") from None
