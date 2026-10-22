import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from collections.abc import Generator
from uuid import UUID

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from shop_api.addresses import AddressInput, AddressListResponse, AddressPatch, AddressResponse, create_address, delete_address, list_addresses, update_address
from shop_api.catalog import CatalogQuery, Product, ProductListResponse, list_categories, list_products
from shop_api.cart import AddCartItem, CartItem, CartResponse, UpdateCartItem, add_item, read_cart, update_item
from shop_api.database import make_session_factory
from shop_api.expiry import expire_orders, expiry_loop
from shop_api.orders import CheckoutInput, Order, OrderListResponse, OrderResponse, ShipmentInput, cancel_order, confirm_receipt, create_order, get_order, list_orders, read_order, ship_order, simulate_payment
from shop_api.admin_catalog import build_admin_catalog_router
from shop_api.identity import (
    AuthSession,
    Credentials,
    CsrfResponse,
    Role,
    User,
    UserResponse,
    authenticate,
    clear_session_cookie,
    create_session,
    find_session,
    get_csrf,
    make_current_session_dependency,
    register_buyer,
    require_csrf,
    require_role,
    revoke,
    set_session_cookie,
)


def create_app(database_url: str | None = None) -> FastAPI:
    resolved_database_url = database_url or os.getenv("SHOP_DATABASE_URL")
    if not resolved_database_url:
        raise RuntimeError("SHOP_DATABASE_URL must be configured")

    factory = make_session_factory(resolved_database_url)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        try:
            await asyncio.to_thread(expire_orders, factory, application.state.clock())
        except Exception:
            logging.getLogger(__name__).exception("Startup order expiry scan failed; periodic scan will retry")
        task = asyncio.create_task(expiry_loop(factory, clock=lambda: application.state.clock()))
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            factory.kw["bind"].dispose()

    app = FastAPI(title="Shop Portfolio API", version="0.1.0", lifespan=lifespan)
    secure_cookie = os.getenv("SHOP_COOKIE_SECURE", "false").lower() == "true"
    app.state.clock = __import__("shop_api.identity", fromlist=["now_utc"]).now_utc

    def session_dependency() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    current_session = make_current_session_dependency(session_dependency, clock=lambda: app.state.clock())
    app.state.session_factory = factory
    app.include_router(build_admin_catalog_router(session_dependency, current_session))

    @app.get("/api/products", response_model=ProductListResponse)
    def get_products(
        q: str = Query(default="", max_length=120),
        category: str | None = Query(default=None, max_length=80),
        sort: str = Query(default="popular", pattern="^(popular|price_asc|price_desc)$"),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=100),
        session: Session = Depends(session_dependency),
    ) -> ProductListResponse:
        query = CatalogQuery(q=q, category=category, sort=sort, page=page, page_size=page_size)
        return list_products(session, query)

    @app.get("/api/categories")
    def get_categories(session: Session = Depends(session_dependency)) -> dict[str, list[str]]:
        return {"items": list_categories(session)}

    @app.get("/api/products/{product_id}")
    def get_product(product_id: UUID, session: Session = Depends(session_dependency)) -> dict[str, object]:
        product = session.get(Product, product_id)
        if product is None or not product.is_listed:
            raise HTTPException(status_code=404, detail="商品不存在")
        return {"id": str(product.id), "name": product.name, "category": product.category, "description": product.description,
                "image_url": product.image_url, "price": product.price, "stock": product.stock}

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    def verify_cart_change(
        request: Request,
        record: AuthSession,
        csrf_token: str | None,
        origin: str | None,
    ) -> None:
        require_csrf(request, record, csrf_token, origin)

    @app.get("/api/cart", response_model=CartResponse)
    def get_cart(
        record: AuthSession = Depends(current_session),
        db: Session = Depends(session_dependency),
    ) -> CartResponse:
        user = require_role(db, record, Role.BUYER)
        return read_cart(db, user)

    @app.patch("/api/cart/items/{product_id}", response_model=CartResponse)
    def update_cart_item(
        product_id: UUID,
        payload: UpdateCartItem,
        request: Request,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        origin: str | None = Header(default=None),
        record: AuthSession = Depends(current_session),
        db: Session = Depends(session_dependency),
    ) -> CartResponse:
        verify_cart_change(request, record, csrf_token, origin)
        user = require_role(db, record, Role.BUYER)
        return update_item(db, user, product_id, payload)

    @app.delete("/api/cart/items/{product_id}", status_code=204)
    def delete_cart_item(
        product_id: UUID,
        request: Request,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        origin: str | None = Header(default=None),
        record: AuthSession = Depends(current_session),
        db: Session = Depends(session_dependency),
    ) -> Response:
        verify_cart_change(request, record, csrf_token, origin)
        user = require_role(db, record, Role.BUYER)
        db.execute(select(User.id).where(User.id == user.id).with_for_update()).one()
        item = db.scalar(
            select(CartItem).where(CartItem.user_id == user.id, CartItem.product_id == product_id)
        )
        if item is None:
            raise HTTPException(status_code=404, detail="购物车条目不存在")
        db.delete(item)
        db.commit()
        return Response(status_code=204)

    @app.post("/api/cart/items", response_model=CartResponse, status_code=201)
    def add_cart_item(
        payload: AddCartItem,
        request: Request,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        origin: str | None = Header(default=None),
        record: AuthSession = Depends(current_session),
        db: Session = Depends(session_dependency),
    ) -> CartResponse:
        verify_cart_change(request, record, csrf_token, origin)
        user = require_role(db, record, Role.BUYER)
        return add_item(db, user, payload)

    @app.get("/api/addresses", response_model=AddressListResponse)
    def get_addresses(
        record: AuthSession = Depends(current_session),
        db: Session = Depends(session_dependency),
    ) -> AddressListResponse:
        user = require_role(db, record, Role.BUYER)
        return list_addresses(db, user)

    @app.post("/api/addresses", response_model=AddressResponse, status_code=201)
    def post_address(
        payload: AddressInput,
        request: Request,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        origin: str | None = Header(default=None),
        record: AuthSession = Depends(current_session),
        db: Session = Depends(session_dependency),
    ) -> AddressResponse:
        require_csrf(request, record, csrf_token, origin)
        user = require_role(db, record, Role.BUYER)
        return create_address(db, user, payload)

    @app.patch("/api/addresses/{address_id}", response_model=AddressResponse)
    def patch_address(
        address_id: UUID,
        payload: AddressPatch,
        request: Request,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        origin: str | None = Header(default=None),
        record: AuthSession = Depends(current_session),
        db: Session = Depends(session_dependency),
    ) -> AddressResponse:
        require_csrf(request, record, csrf_token, origin)
        user = require_role(db, record, Role.BUYER)
        return update_address(db, user, address_id, payload)

    @app.delete("/api/addresses/{address_id}", status_code=204)
    def remove_address(
        address_id: UUID,
        request: Request,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        origin: str | None = Header(default=None),
        record: AuthSession = Depends(current_session),
        db: Session = Depends(session_dependency),
    ) -> Response:
        require_csrf(request, record, csrf_token, origin)
        user = require_role(db, record, Role.BUYER)
        delete_address(db, user, address_id)
        return Response(status_code=204)

    @app.post("/api/orders", response_model=OrderResponse, status_code=201)
    def checkout(
        payload: CheckoutInput,
        request: Request,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        origin: str | None = Header(default=None),
        record: AuthSession = Depends(current_session),
        db: Session = Depends(session_dependency),
    ) -> OrderResponse:
        require_csrf(request, record, csrf_token, origin)
        user = require_role(db, record, Role.BUYER)
        if not idempotency_key or len(idempotency_key) > 128:
            raise HTTPException(status_code=422, detail="Idempotency-Key 必填且长度不超过 128")
        return create_order(db, user, payload.address_id, idempotency_key)

    @app.get("/api/orders", response_model=OrderListResponse)
    def buyer_orders(
        status: str | None = Query(default=None, pattern="^(pending_payment|pending_shipment|pending_receipt|completed|closed)$"),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=100),
        record: AuthSession = Depends(current_session),
        db: Session = Depends(session_dependency),
    ) -> OrderListResponse:
        return list_orders(db, require_role(db, record, Role.BUYER), status, page, page_size)

    @app.get("/api/admin/orders", response_model=OrderListResponse)
    def admin_orders(
        status: str | None = Query(default=None, pattern="^(pending_payment|pending_shipment|pending_receipt|completed|closed)$"),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=100),
        record: AuthSession = Depends(current_session),
        db: Session = Depends(session_dependency),
    ) -> OrderListResponse:
        return list_orders(db, require_role(db, record, Role.ADMIN), status, page, page_size)

    @app.get("/api/admin/orders/{order_id}", response_model=OrderResponse)
    def admin_order(
        order_id: UUID,
        record: AuthSession = Depends(current_session),
        db: Session = Depends(session_dependency),
    ) -> OrderResponse:
        require_role(db, record, Role.ADMIN)
        order = db.get(Order, order_id)
        if order is None:
            raise HTTPException(status_code=404, detail="订单不存在")
        return read_order(db, order)

    @app.post("/api/admin/orders/{order_id}/ship", response_model=OrderResponse)
    def ship_admin_order(
        order_id: UUID,
        payload: ShipmentInput,
        request: Request,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        origin: str | None = Header(default=None),
        record: AuthSession = Depends(current_session),
        db: Session = Depends(session_dependency),
    ) -> OrderResponse:
        require_csrf(request, record, csrf_token, origin)
        require_role(db, record, Role.ADMIN)
        return ship_order(db, order_id, payload, app.state.clock())

    @app.post("/api/orders/{order_id}/confirm-receipt", response_model=OrderResponse)
    def receive_buyer_order(
        order_id: UUID,
        request: Request,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        origin: str | None = Header(default=None),
        record: AuthSession = Depends(current_session),
        db: Session = Depends(session_dependency),
    ) -> OrderResponse:
        require_csrf(request, record, csrf_token, origin)
        return confirm_receipt(db, require_role(db, record, Role.BUYER), order_id, app.state.clock())

    @app.get("/api/orders/{order_id}", response_model=OrderResponse)
    def read_buyer_order(
        order_id: UUID,
        record: AuthSession = Depends(current_session),
        db: Session = Depends(session_dependency),
    ) -> OrderResponse:
        user = require_role(db, record, Role.BUYER)
        return get_order(db, user, order_id)

    @app.post("/api/orders/{order_id}/cancel", response_model=OrderResponse)
    def cancel_buyer_order(
        order_id: UUID,
        request: Request,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        origin: str | None = Header(default=None),
        record: AuthSession = Depends(current_session),
        db: Session = Depends(session_dependency),
    ) -> OrderResponse:
        require_csrf(request, record, csrf_token, origin)
        user = require_role(db, record, Role.BUYER)
        result = cancel_order(db, user, order_id, clock=lambda: app.state.clock())
        db.commit()
        return result

    @app.post("/api/orders/{order_id}/pay", response_model=OrderResponse)
    def pay_order(
        order_id: UUID,
        request: Request,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        origin: str | None = Header(default=None),
        record: AuthSession = Depends(current_session),
        db: Session = Depends(session_dependency),
    ) -> OrderResponse:
        require_csrf(request, record, csrf_token, origin)
        user = require_role(db, record, Role.BUYER)
        return simulate_payment(db, user, order_id, app.state.clock())

    @app.get("/api/auth/csrf", response_model=CsrfResponse)
    def csrf(
        response: Response,
        db: Session = Depends(session_dependency),
        raw_session: str | None = Cookie(default=None, alias="shop_session"),
    ) -> CsrfResponse:
        record = find_session(db, raw_session)
        return get_csrf(response, db, record, raw_session, secure_cookie)

    @app.post("/api/auth/register", status_code=201)
    def register(
        payload: Credentials,
        request: Request,
        response: Response,
        db: Session = Depends(session_dependency),
        raw_session: str | None = Cookie(default=None, alias="shop_session"),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        origin: str | None = Header(default=None),
    ) -> dict[str, str]:
        record = find_session(db, raw_session)
        if record is None or record.kind != "anonymous":
            raise HTTPException(status_code=403, detail="请重新获取 CSRF Token")
        require_csrf(request, record, csrf_token, origin)
        register_buyer(db, payload)
        return {"message": "注册成功，请登录。"}

    @app.post("/api/auth/login", response_model=dict[str, UserResponse])
    def login(
        payload: Credentials,
        request: Request,
        response: Response,
        db: Session = Depends(session_dependency),
        raw_session: str | None = Cookie(default=None, alias="shop_session"),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        origin: str | None = Header(default=None),
    ) -> dict[str, UserResponse]:
        record = find_session(db, raw_session)
        if record is None or record.kind != "anonymous":
            raise HTTPException(status_code=403, detail="请重新获取 CSRF Token")
        require_csrf(request, record, csrf_token, origin)
        user = authenticate(db, payload)
        revoke(record)
        authenticated, raw_id, next_csrf = create_session(db, "authenticated", user)
        db.commit()
        set_session_cookie(response, raw_id, authenticated.expires_at, secure_cookie)
        response.headers["X-CSRF-Token"] = next_csrf
        return {"user": UserResponse.model_validate(user)}

    @app.post("/api/auth/logout", status_code=204)
    def logout(
        request: Request,
        response: Response,
        record: AuthSession = Depends(current_session),
        db: Session = Depends(session_dependency),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        origin: str | None = Header(default=None),
    ) -> Response:
        require_csrf(request, record, csrf_token, origin)
        revoke(record)
        db.commit()
        clear_session_cookie(response, secure_cookie)
        response.status_code = 204
        return response

    @app.get("/api/auth/me", response_model=UserResponse)
    def me(record: AuthSession = Depends(current_session), db: Session = Depends(session_dependency)) -> UserResponse:
        if record.kind != "authenticated" or record.user_id is None:
            raise HTTPException(status_code=401, detail="需要登录")
        user = db.get(User, record.user_id)
        if user is None or not user.is_active:
            raise HTTPException(status_code=401, detail="需要登录")
        return UserResponse.model_validate(user)

    @app.get("/api/admin/access", response_model=UserResponse)
    def admin_access(
        record: AuthSession = Depends(current_session),
        db: Session = Depends(session_dependency),
    ) -> UserResponse:
        user = require_role(db, record, Role.ADMIN)
        return UserResponse.model_validate(user)

    return app


app = create_app()
