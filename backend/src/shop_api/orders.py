from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Uuid, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from shop_api.addresses import Address
from shop_api.cart import CartItem
from shop_api.catalog import Product
from shop_api.database import Base
from shop_api.identity import User, now_utc


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    address_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    recipient_name: Mapped[str] = mapped_column(String(80), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    province: Mapped[str] = mapped_column(String(80), nullable=False)
    city: Mapped[str] = mapped_column(String(80), nullable=False)
    district: Mapped[str] = mapped_column(String(80), nullable=False)
    detail: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending_payment")
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    shipping_company: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tracking_number: Mapped[str | None] = mapped_column(String(100), nullable=True)


class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    image_url: Mapped[str] = mapped_column(String(500), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)


class CheckoutInput(BaseModel):
    address_id: UUID


class OrderItemResponse(BaseModel):
    product_id: UUID
    name: str
    image_url: str
    unit_price: Decimal
    quantity: int
    line_total: Decimal


class OrderAddressResponse(BaseModel):
    recipient_name: str
    phone: str
    province: str
    city: str
    district: str
    detail: str


class OrderResponse(BaseModel):
    id: UUID
    status: str
    total: Decimal
    created_at: datetime
    paid_at: datetime | None
    closed_at: datetime | None
    shipped_at: datetime | None
    completed_at: datetime | None
    close_reason: str | None
    shipping_company: str | None
    tracking_number: str | None
    expires_at: datetime
    items: list[OrderItemResponse]
    address: OrderAddressResponse


class OrderListResponse(BaseModel):
    items: list[OrderResponse]
    total: int
    page: int
    page_size: int


class ShipmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    shipping_company: str = Field(min_length=1, max_length=100)
    tracking_number: str = Field(min_length=1, max_length=100)


def list_orders(session: Session, user: User, status: str | None, page: int, page_size: int) -> OrderListResponse:
    statement = select(Order)
    if user.role != "admin":
        statement = statement.where(Order.user_id == user.id)
    if status:
        statement = statement.where(Order.status == status)
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    orders = session.scalars(statement.order_by(Order.created_at.desc(), Order.id.asc()).offset((page - 1) * page_size).limit(page_size)).all()
    return OrderListResponse(items=[read_order(session, order) for order in orders], total=total, page=page, page_size=page_size)


def _support_notification(session: Session, order: Order, event: str, message: str, now: datetime | None) -> None:
    from shop_api.customer_service_support import notify
    notify(session, order.user_id, f"order:{order.id}:{event}", message, now or now_utc())


def ship_order(session: Session, order_id: UUID, payload: ShipmentInput, now=None) -> OrderResponse:
    order = session.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status != "pending_shipment":
        raise HTTPException(status_code=409, detail="当前订单状态不可发货")
    order.status = "pending_receipt"
    order.shipping_company = payload.shipping_company
    order.tracking_number = payload.tracking_number
    order.shipped_at = now or now_utc()
    _support_notification(session, order, "shipped", f"订单 {order.id} 已发货，请在本人订单中查看物流公司和运单号。", order.shipped_at)
    session.commit()
    return read_order(session, order)


def confirm_receipt(session: Session, user: User, order_id: UUID, now=None) -> OrderResponse:
    order = session.scalar(select(Order).where(Order.id == order_id, Order.user_id == user.id).with_for_update())
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status != "pending_receipt":
        raise HTTPException(status_code=409, detail="当前订单状态不可确认收货")
    order.status = "completed"
    order.completed_at = now or now_utc()
    _support_notification(session, order, "receipt", f"订单 {order.id} 已由你确认收货。", order.completed_at)
    session.commit()
    return read_order(session, order)


def create_order(session: Session, user: User, address_id: UUID, idempotency_key: str) -> OrderResponse:
    # Serialize checkout and cart mutations for this buyer before reading the key.
    session.execute(select(User.id).where(User.id == user.id).with_for_update()).one()
    prior = session.scalar(select(Order).where(Order.user_id == user.id, Order.idempotency_key == idempotency_key))
    if prior:
        requested_rows = session.execute(select(CartItem.product_id, CartItem.quantity).where(CartItem.user_id == user.id, CartItem.selected.is_(True)).order_by(CartItem.product_id)).all()
        requested_fingerprint = tuple((product_id, quantity) for product_id, quantity in requested_rows)
        prior_rows = session.execute(select(OrderItem.product_id, OrderItem.quantity).where(OrderItem.order_id == prior.id).order_by(OrderItem.product_id)).all()
        if prior.address_id != address_id or (requested_fingerprint and requested_fingerprint != tuple(prior_rows)):
            raise HTTPException(status_code=409, detail="幂等键已用于不同的结算请求")
        return read_order(session, prior)
    address = session.scalar(select(Address).where(Address.id == address_id, Address.user_id == user.id).with_for_update())
    if address is None:
        raise HTTPException(status_code=404, detail="收货地址不存在")
    rows = session.execute(select(CartItem, Product).join(Product, Product.id == CartItem.product_id).where(CartItem.user_id == user.id, CartItem.selected.is_(True)).order_by(Product.id).with_for_update(of=Product)).all()
    if not rows:
        raise HTTPException(status_code=409, detail="没有已勾选的商品")
    for cart, product in rows:
        if not product.is_listed:
            raise HTTPException(status_code=409, detail="商品已下架，无法结算")
        if cart.quantity > product.stock:
            raise HTTPException(status_code=409, detail="商品库存不足")
    total = sum((product.price * cart.quantity for cart, product in rows), Decimal("0.00"))
    now = now_utc()
    order = Order(user_id=user.id, address_id=address.id, recipient_name=address.recipient_name, phone=address.phone, province=address.province, city=address.city, district=address.district, detail=address.detail, status="pending_payment", total=total, idempotency_key=idempotency_key, created_at=now, expires_at=now + timedelta(minutes=30))
    session.add(order)
    session.flush()
    for cart, product in rows:
        product.stock -= cart.quantity
        session.add(OrderItem(order_id=order.id, product_id=product.id, name=product.name, image_url=product.image_url, unit_price=product.price, quantity=cart.quantity, line_total=product.price * cart.quantity))
        session.delete(cart)
    session.commit()
    return read_order(session, order)


def get_order(session: Session, user: User, order_id: UUID) -> OrderResponse:
    order = session.scalar(select(Order).where(Order.id == order_id, Order.user_id == user.id))
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    return read_order(session, order)


def simulate_payment(session: Session, user: User, order_id: UUID, now=None) -> OrderResponse:
    order = session.scalar(select(Order).where(Order.id == order_id, Order.user_id == user.id).with_for_update())
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    current = now or now_utc()
    if order.status != "pending_payment":
        raise HTTPException(status_code=409, detail="当前订单状态不可支付")
    if order.expires_at <= current:
        raise HTTPException(status_code=409, detail="订单已超时，暂不可支付")
    order.status = "pending_shipment"
    order.paid_at = current
    session.commit()
    return read_order(session, order)


def close_order(session: Session, order: Order, reason: str, current) -> None:
    items = session.scalars(select(OrderItem).where(OrderItem.order_id == order.id).order_by(OrderItem.product_id)).all()
    products = session.scalars(select(Product).where(Product.id.in_([item.product_id for item in items])).order_by(Product.id).with_for_update()).all()
    quantities = {item.product_id: item.quantity for item in items}
    for product in products:
        product.stock += quantities[product.id]
    order.status = "closed"
    order.close_reason = reason
    order.closed_at = current


def cancel_order(session: Session, user: User, order_id: UUID, now=None, *, clock=now_utc) -> OrderResponse:
    order = session.scalar(select(Order).where(Order.id == order_id, Order.user_id == user.id).with_for_update())
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status != "pending_payment":
        raise HTTPException(status_code=409, detail="当前订单状态不可取消")
    current = now if now is not None else clock()
    if order.expires_at <= current:
        raise HTTPException(status_code=409, detail="订单已超时，暂不可取消")
    close_order(session, order, "buyer_cancelled", current)
    return read_order(session, order)


def read_order(session: Session, order: Order) -> OrderResponse:
    items = session.scalars(select(OrderItem).where(OrderItem.order_id == order.id)).all()
    return OrderResponse(id=order.id, status=order.status, total=order.total, created_at=order.created_at,
        paid_at=order.paid_at, closed_at=order.closed_at, shipped_at=order.shipped_at, completed_at=order.completed_at,
        close_reason=order.close_reason, shipping_company=order.shipping_company, tracking_number=order.tracking_number, expires_at=order.expires_at,
        items=[OrderItemResponse(product_id=i.product_id, name=i.name, image_url=i.image_url, unit_price=i.unit_price, quantity=i.quantity, line_total=i.line_total) for i in items],
        address=OrderAddressResponse(recipient_name=order.recipient_name, phone=order.phone, province=order.province, city=order.city, district=order.district, detail=order.detail))
