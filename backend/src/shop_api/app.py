import asyncio
import time
import logging
import os
import tempfile
from contextlib import asynccontextmanager, suppress
from collections.abc import Generator
from datetime import UTC
from uuid import UUID, uuid4

from fastapi import APIRouter, Cookie, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from shop_api.addresses import AddressInput, AddressListResponse, AddressPatch, AddressResponse, create_address, delete_address, list_addresses, update_address
from shop_api.catalog import CatalogQuery, Product, ProductListResponse, list_categories, list_products
from shop_api.cart import AddCartItem, CartItem, CartResponse, UpdateCartItem, add_item, read_cart, update_item
from shop_api.database import make_session_factory
from shop_api.customer_service import CustomerServiceUnavailable, SafeLogWriter, SharedLimiter, acquire_query_turn, check_fixture
from shop_api.customer_service_maintenance import CustomerServiceMaintenance
from shop_api.customer_service_admission import require_product_reader, require_query_rate_limits
from shop_api.customer_service_products import ProductTools
from shop_api.customer_service_consultations import build_consultation_router
from shop_api.customer_service_support_api import build_support_router
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


def create_app(database_url: str | None = None, *, synthetic_product_exchange=None,
               product_transport=None, synthetic_consultation_exchange=None) -> FastAPI:
    resolved_database_url = database_url or os.getenv("SHOP_DATABASE_URL")
    if not resolved_database_url:
        raise RuntimeError("SHOP_DATABASE_URL must be configured")

    factory = make_session_factory(resolved_database_url)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        try:
            with factory() as session:
                initialize_customer_service_guards(application, session)
        except Exception as error:
            logging.getLogger(__name__).warning("customer_service_guards_unavailable error=%s", type(error).__name__)
            application.state.customer_service_enabled = False
        try:
            await asyncio.to_thread(expire_orders, factory, application.state.clock())
        except Exception:
            logging.getLogger(__name__).exception("Startup order expiry scan failed; periodic scan will retry")
        task = asyncio.create_task(expiry_loop(factory, clock=lambda: application.state.clock()))
        customer_service_task = asyncio.create_task(customer_service_maintenance(application))
        try:
            yield
        finally:
            task.cancel()
            customer_service_task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            with suppress(asyncio.CancelledError):
                await customer_service_task
            if application.state.customer_service_synthetic_transport is not None:
                await asyncio.to_thread(application.state.customer_service_synthetic_transport.close)
            if application.state.customer_service_composite_transport is not None:
                await asyncio.to_thread(application.state.customer_service_composite_transport.close)
            factory.kw["bind"].dispose()

    app = FastAPI(title="Shop Portfolio API", version="0.1.0", lifespan=lifespan)
    secure_cookie = os.getenv("SHOP_COOKIE_SECURE", "false").lower() == "true"
    app.state.clock = __import__("shop_api.identity", fromlist=["now_utc"]).now_utc

    def session_dependency() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    current_session = make_current_session_dependency(session_dependency, clock=lambda: app.state.clock())
    app.state.session_factory = factory
    configured_customer_service_mode = os.getenv("SHOP_CUSTOMER_SERVICE_MODE")
    if configured_customer_service_mode not in {"demo", "integrated"}:
        configured_customer_service_mode = "demo" if os.getenv("SHOP_CUSTOMER_SERVICE_DEMO_MODE") == "1" else "disabled"
    app.state.customer_service_mode = configured_customer_service_mode
    app.state.customer_service_enabled = False
    app.state.customer_service_limiter = SharedLimiter(factory)
    app.state.customer_service_log_writer = None
    app.state.customer_service_fixtures = {}
    app.state.customer_service_buyer_ids = set()
    # Synthetic policy internals stay None unless an explicit verified demo
    # fixture is configured. There is no WeKnora client, URL, token or real path.
    app.state.customer_service_policy_registry = None
    app.state.customer_service_policy_index = None
    # Trusted server constructor seam only. No env/browser/provider activation.
    app.state.customer_service_synthetic_transport = None
    if synthetic_product_exchange is not None and product_transport is not None:
        raise RuntimeError("Inject either a synthetic exchange or a built transport, not both")
    if product_transport is not None:
        app.state.customer_service_synthetic_transport = product_transport
    elif synthetic_product_exchange is not None:
        from shop_api.customer_service_model_budget import ModelBudget
        from shop_api.customer_service_model_transport import CompletionTransport
        app.state.customer_service_synthetic_transport = CompletionTransport(
            ModelBudget(factory, clock=lambda: app.state.clock(), product_only=True),
            exchange=synthetic_product_exchange)

    app.state.customer_service_composite_transport = None
    if synthetic_consultation_exchange is not None:
        from shop_api.customer_service_model_budget import ModelBudget
        from shop_api.customer_service_model_transport import CompletionTransport
        if synthetic_consultation_exchange is CompletionTransport._https_exchange:
            raise ValueError('Composite consultations only allow a synthetic exchange')
        app.state.customer_service_composite_transport = CompletionTransport(
            ModelBudget(factory, clock=lambda: app.state.clock(), product_only=True),
            exchange=synthetic_consultation_exchange)

    async def customer_service_maintenance(application: FastAPI) -> None:
        maintenance = CustomerServiceMaintenance(
            factory, application.state.customer_service_log_writer, lambda: application.state.clock())
        if application.state.customer_service_enabled:
            await maintenance.run()

    def initialize_integrated_customer_service(application: FastAPI, session: Session) -> None:
        if application.state.customer_service_mode != "integrated":
            return
        try:
            from shop_api.customer_service import QueryDeadline
            from shop_api.customer_service_cancel import CancelOperation
            from shop_api.customer_service_consultations import Consultation, ConsultationMessage, ConsultationPage

            with session.begin_nested():
                QueryDeadline(3).apply(session)
                # Validate the columns used by consultations without changing schema or data.
                from shop_api.customer_service_support import (
                    SupportContext, SupportCase, SupportPreference, SupportEvent, SupportChannel, SupportNotification,
                )
                from shop_api.customer_service_knowledge import KnowledgeEntry
                for model in (Consultation, ConsultationPage, ConsultationMessage, CancelOperation,
                              SupportContext, SupportCase, SupportPreference, SupportEvent,
                              SupportChannel, SupportNotification, KnowledgeEntry):
                    session.execute(select(model).limit(0))
                from sqlalchemy import text
                session.execute(text("SELECT bucket_key, hits, window_started_at, expires_at FROM customer_service_rate_limits LIMIT 0"))
                session.execute(text("SELECT id, bucket_key, event_at FROM customer_service_rate_limit_events LIMIT 0"))
            directory = os.getenv("SHOP_CUSTOMER_SERVICE_LOG_DIRECTORY")
            if directory is None:
                directory = os.path.join(tempfile.gettempdir(), "shop-customer-service-integrated-logs")
                os.makedirs(directory, mode=0o700, exist_ok=True)
            writer = SafeLogWriter(directory)
            writer.verify()
            writer.prune(application.state.clock())
            application.state.customer_service_log_writer = writer
            application.state.customer_service_enabled = True
        except Exception as error:
            logging.getLogger(__name__).warning(
                "customer_service_integrated_disabled error=%s", type(error).__name__)

    def initialize_customer_service_guards(application: FastAPI, session: Session) -> None:
        if application.state.customer_service_mode == "integrated":
            initialize_integrated_customer_service(application, session)
            return
        if application.state.customer_service_mode != "demo":
            return
        fixture_path = os.getenv("SHOP_CUSTOMER_SERVICE_FIXTURE_PATH")
        fixture_digest = os.getenv("SHOP_CUSTOMER_SERVICE_FIXTURE_SHA256")
        log_directory = os.getenv("SHOP_CUSTOMER_SERVICE_LOG_DIRECTORY")
        buyer_ids_raw = os.getenv("SHOP_CUSTOMER_SERVICE_BUYER_IDS", "")
        if os.getenv("SHOP_CUSTOMER_SERVICE_DEMO_MODE") != "1" or not fixture_path or not fixture_digest or not log_directory or not buyer_ids_raw:
            return
        try:
            buyer_ids = {UUID(value.strip()) for value in buyer_ids_raw.split(",") if value.strip()}
            if len(buyer_ids) != 2:
                raise CustomerServiceUnavailable
            approved_buyers = set(session.scalars(select(User.id).where(
                User.id.in_(buyer_ids), User.role == Role.BUYER.value, User.is_active.is_(True)
            )).all())
            if approved_buyers != buyer_ids:
                raise CustomerServiceUnavailable
            fixtures = check_fixture(session, fixture_path, fixture_digest)
            writer = SafeLogWriter(log_directory)
            writer.verify()
            # Expired files from downtime are removed before admission is enabled.
            writer.prune(application.state.clock())
            policy_path = os.getenv("SHOP_CUSTOMER_SERVICE_POLICY_PATH")
            policy_digest = os.getenv("SHOP_CUSTOMER_SERVICE_POLICY_SHA256")
            if policy_path or policy_digest:
                if not policy_path or not policy_digest:
                    raise CustomerServiceUnavailable
                from shop_api.customer_service_policy import (
                    PolicyPublicationError, load_synthetic_policy_fixture,
                )
                try:
                    registry, index = load_synthetic_policy_fixture(policy_path, policy_digest)
                except PolicyPublicationError:
                    raise CustomerServiceUnavailable from None
                application.state.customer_service_policy_registry = registry
                application.state.customer_service_policy_index = index
            application.state.customer_service_fixtures = fixtures
            application.state.customer_service_buyer_ids = buyer_ids
            for transport in (application.state.customer_service_synthetic_transport,
                              application.state.customer_service_composite_transport):
                if transport is not None:
                    transport._budget._approved_buyer_ids = frozenset(buyer_ids)
            application.state.customer_service_log_writer = writer
            application.state.customer_service_enabled = True
        except CustomerServiceUnavailable:
            logging.getLogger(__name__).warning("customer_service_guards_unavailable error=fixture_verification_failed")
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

    class CustomerServiceRoute(APIRoute):
        def get_route_handler(self):
            handler = super().get_route_handler()

            async def handle(request: Request) -> Response:
                request.state.customer_service_request_id = str(uuid4())
                try:
                    result = await handler(request)
                except RequestValidationError:
                    result = customer_service_error(request, 422)
                except StarletteHTTPException as error:
                    result = customer_service_error(request, error.status_code, error.headers)
                except Exception:
                    # Never expose or log exception objects, request bodies or credentials.
                    logging.getLogger(__name__).warning(
                        "customer_service_request_failed request_id=%s error=dependency_unavailable",
                        request.state.customer_service_request_id,
                    )
                    result = customer_service_error(request, 503)
                result.headers["Cache-Control"] = "no-store"
                return result

            return handle

    def customer_service_error(request: Request, status_code: int, headers=None) -> JSONResponse:
        code, message = {
            401: ("authentication_required", "需要登录"),
            403: ("resource_unavailable", "未找到可访问的记录"),
            422: ("invalid_input", "查询参数无效"),
            425: ("busy", "已有查询正在处理"),
            429: ("rate_limited", "查询过于频繁"),
            503: ("dependency_unavailable", "商品查询暂不可用"),
        }.get(status_code, ("internal_error", "客服请求失败"))
        return JSONResponse(
            status_code=status_code,
            headers=headers,
            content={
                "request_id": request.state.customer_service_request_id,
                "queried_at": app.state.clock().astimezone(UTC).isoformat(),
                "status": "unavailable" if status_code == 503 else "processing" if status_code == 425 else "error",
                "data": None,
                "code": code,
                "message": message,
            },
        )

    customer_service_router = APIRouter(prefix="/api/customer-service", route_class=CustomerServiceRoute)

    @customer_service_router.get("/mode")
    def customer_service_mode(response: Response) -> dict[str, object]:
        response.headers["Cache-Control"] = "no-store"
        return {"mode": app.state.customer_service_mode, "enabled": app.state.customer_service_enabled}

    @customer_service_router.get("/products")
    def customer_service_products(
        request: Request,
        response: Response,
        record: AuthSession = Depends(current_session),
        buyer_session: Session = Depends(session_dependency),
        q: str = Query(default="", max_length=100),
        category: str | None = Query(default=None, max_length=64),
        page: int = Query(default=1, ge=1, le=100),
        page_size: int = Query(default=10, ge=1, le=20),
        session: Session = Depends(session_dependency),
    ) -> dict[str, object]:
        response.headers["Cache-Control"] = "no-store"
        require_product_reader(request, record, buyer_session)
        if app.state.customer_service_mode == "integrated" and category is not None:
            raise HTTPException(status_code=422, detail="查询参数无效")
        if set(request.query_params) - {"q", "category", "page", "page_size"}:
            raise HTTPException(status_code=422, detail="查询参数无效")
        request_id = request.state.customer_service_request_id
        started = time.monotonic()
        if not acquire_query_turn(session, record.id):
            raise HTTPException(status_code=425, detail="已有查询正在处理")
        require_query_rate_limits(request)
        try:
            if app.state.customer_service_mode == "integrated":
                from shop_api.customer_service_integrated import StorefrontProductTools
                result = StorefrontProductTools(session, request_id, app.state.clock).call(
                    "list_products", {"keyword": q, "page": page, "page_size": page_size})
            else:
                result = ProductTools(session, app.state.customer_service_fixtures, request_id, app.state.clock).call(
                    "list_products", {"keyword": q, "category": category, "page": page, "page_size": page_size},
                )
        except HTTPException:
            raise
        except Exception as error:
            if app.state.customer_service_log_writer is not None:
                app.state.customer_service_log_writer.write(request_id, "list_products", "dependency_unavailable", int((time.monotonic() - started) * 1000), 1, app.state.clock())
            logging.getLogger(__name__).warning("customer_service_query_failed request_id=%s error=%s", request_id, type(error).__name__)
            raise HTTPException(status_code=503, detail="商品查询暂不可用") from None
        if app.state.customer_service_log_writer is not None:
            app.state.customer_service_log_writer.write(request_id, "list_products", "", int((time.monotonic() - started) * 1000), len(result["data"]["items"]), app.state.clock())
        return result

    @customer_service_router.get("/products/{product_id}")
    def customer_service_product(
        product_id: UUID,
        request: Request,
        response: Response,
        record: AuthSession = Depends(current_session),
        buyer_session: Session = Depends(session_dependency),
        session: Session = Depends(session_dependency),
    ) -> dict[str, object]:
        response.headers["Cache-Control"] = "no-store"
        require_product_reader(request, record, buyer_session)
        if request.query_params:
            raise HTTPException(status_code=422, detail="查询参数无效")
        request_id = request.state.customer_service_request_id
        started = time.monotonic()
        if not acquire_query_turn(session, record.id):
            raise HTTPException(status_code=425, detail="已有查询正在处理")
        require_query_rate_limits(request)
        try:
            if app.state.customer_service_mode == "integrated":
                from shop_api.customer_service_integrated import StorefrontProductTools
                result = StorefrontProductTools(session, request_id, app.state.clock).call(
                    "get_product", {"product_id": str(product_id)})
            else:
                result = ProductTools(session, app.state.customer_service_fixtures, request_id, app.state.clock).call(
                    "get_product", {"product_id": str(product_id)},
                )
        except HTTPException:
            raise
        except Exception as error:
            if app.state.customer_service_log_writer is not None:
                app.state.customer_service_log_writer.write(request_id, "get_product", "dependency_unavailable", int((time.monotonic() - started) * 1000), 1, app.state.clock())
            logging.getLogger(__name__).warning("customer_service_lookup_failed request_id=%s error=%s", request_id, type(error).__name__)
            raise HTTPException(status_code=503, detail="商品查询暂不可用") from None
        if app.state.customer_service_log_writer is not None:
            app.state.customer_service_log_writer.write(request_id, "get_product", "", int((time.monotonic() - started) * 1000), 1, app.state.clock())
        return result

    app.include_router(customer_service_router)
    app.include_router(build_consultation_router(session_dependency, current_session))
    app.include_router(build_support_router(session_dependency, current_session))

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
        if os.getenv("SHOP_CUSTOMER_SERVICE_DEMO_MODE") == "1" or os.getenv("SHOP_REGISTRATION_ENABLED", "true").lower() != "true":
            raise HTTPException(status_code=403, detail="演示环境不开放注册")
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
