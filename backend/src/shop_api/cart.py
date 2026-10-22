from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import ForeignKey, Integer, Numeric, Boolean, Uuid, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from shop_api.catalog import Product
from shop_api.database import Base
from shop_api.identity import User


class CartItem(Base):
    __tablename__ = "cart_items"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AddCartItem(BaseModel):
    product_id: UUID
    quantity: int = Field(ge=1, le=99)


class UpdateCartItem(BaseModel):
    quantity: int | None = Field(default=None, ge=1, le=99)
    selected: bool | None = None


class CartItemResponse(BaseModel):
    product_id: UUID
    name: str
    image_url: str
    unit_price: Decimal
    quantity: int
    selected: bool
    stock: int


class CartResponse(BaseModel):
    items: list[CartItemResponse]
    total: Decimal


def read_cart(session: Session, user: User) -> CartResponse:
    rows = session.execute(
        select(CartItem, Product)
        .join(Product, Product.id == CartItem.product_id)
        .where(CartItem.user_id == user.id)
        .order_by(CartItem.id)
    ).all()
    items = [
        CartItemResponse(
            product_id=product.id,
            name=product.name,
            image_url=product.image_url,
            unit_price=product.price,
            quantity=item.quantity,
            selected=item.selected,
            stock=product.stock,
        )
        for item, product in rows
    ]
    total = sum((item.unit_price * item.quantity for item in items if item.selected), Decimal("0.00"))
    return CartResponse(items=items, total=total)


def update_item(session: Session, user: User, product_id: UUID, request: UpdateCartItem) -> CartResponse:
    session.execute(select(User.id).where(User.id == user.id).with_for_update()).one()
    item = session.scalar(
        select(CartItem).where(CartItem.user_id == user.id, CartItem.product_id == product_id)
    )
    if item is None:
        raise HTTPException(status_code=404, detail="购物车条目不存在")
    product = session.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="商品不存在")
    if request.quantity is not None:
        if not product.is_listed:
            raise HTTPException(status_code=409, detail="商品已下架，无法修改购买数量")
        if request.quantity > product.stock:
            raise HTTPException(status_code=409, detail="商品库存不足")
        item.quantity = request.quantity
    if request.selected is not None:
        item.selected = request.selected
    session.commit()
    return read_cart(session, user)


def add_item(session: Session, user: User, request: AddCartItem) -> CartResponse:
    session.execute(select(User.id).where(User.id == user.id).with_for_update()).one()
    product = session.get(Product, request.product_id)
    if product is None or not product.is_listed:
        raise HTTPException(status_code=404, detail="商品不存在或已下架")
    if request.quantity > product.stock:
        raise HTTPException(status_code=409, detail="商品库存不足")

    item = session.scalar(
        select(CartItem).where(CartItem.user_id == user.id, CartItem.product_id == product.id)
    )
    if item is None:
        session.add(CartItem(user_id=user.id, product_id=product.id, quantity=request.quantity, selected=True))
    else:
        next_quantity = item.quantity + request.quantity
        if next_quantity > product.stock:
            raise HTTPException(status_code=409, detail="商品库存不足")
        item.quantity = next_quantity
    session.commit()
    return read_cart(session, user)
