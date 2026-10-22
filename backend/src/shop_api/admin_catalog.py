from datetime import datetime
from decimal import Decimal
from typing import Annotated
from urllib.parse import unquote, urlsplit
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Uuid, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from shop_api.database import Base
from shop_api.catalog import Product
from shop_api.identity import AuthSession, Role, now_utc, require_csrf, require_role


def validate_image_url(value: str) -> str:
    decoded = unquote(value)
    if any(ord(character) < 33 for character in decoded) or "\\" in decoded:
        raise ValueError("图片地址无效")
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() in {"http", "https"} and parsed.hostname and parsed.port != 0:
            return value
        if not parsed.scheme and not parsed.netloc and decoded.startswith("/images/"):
            if all(part not in {".", ".."} for part in urlsplit(decoded).path.split("/")) and len(parsed.path) > len("/images/"):
                return value
    except ValueError:
        pass
    raise ValueError("图片仅支持 /images/ 本地路径或 HTTP(S) 地址")


ImageReference = Annotated[str, Field(min_length=1, max_length=500), AfterValidator(validate_image_url)]


class ProductInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=160)
    category: str = Field(min_length=1, max_length=80)
    description: str = Field(max_length=10000)
    image_url: ImageReference
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    is_listed: bool = True


class ProductPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=160)
    category: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=10000)
    image_url: ImageReference | None = None
    price: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    is_listed: bool | None = Field(default=None, strict=True)

    @model_validator(mode="before")
    @classmethod
    def reject_null_fields(cls, values):
        if isinstance(values, dict) and any(value is None for value in values.values()):
            raise ValueError("商品字段不可为 null")
        return values


class AdminProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    category: str
    description: str
    image_url: str
    price: Decimal
    stock: int
    is_listed: bool
    created_at: datetime


class AdminProductListResponse(BaseModel):
    items: list[AdminProductResponse]
    total: int
    page: int
    page_size: int


class InventoryAdjustment(Base):
    __tablename__ = "inventory_adjustments"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    delta: Mapped[int] = mapped_column(nullable=False)
    before_stock: Mapped[int] = mapped_column(BigInteger, nullable=False)
    after_stock: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    admin_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class InventoryAdjustmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    delta: int = Field(strict=True, ge=-2147483647, le=2147483647)
    reason: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def reject_zero(self):
        if self.delta == 0:
            raise ValueError("库存调整数量不得为零")
        return self


class InventoryAdjustmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    delta: int
    before_stock: int
    after_stock: int
    reason: str
    admin_id: UUID
    created_at: datetime


class InventoryAdjustmentListResponse(BaseModel):
    items: list[InventoryAdjustmentResponse]
    total: int
    page: int
    page_size: int


def get_product(db: Session, product_id: UUID, *, lock: bool = False) -> Product:
    statement = select(Product).where(Product.id == product_id)
    if lock:
        statement = statement.with_for_update()
    product = db.scalar(statement)
    if product is None:
        raise HTTPException(status_code=404, detail="商品不存在")
    return product


def build_admin_catalog_router(session_dependency, current_session) -> APIRouter:
    router = APIRouter(prefix="/api/admin/products", tags=["admin catalog"])

    def write_admin(
        request: Request,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        origin: str | None = Header(default=None),
        record: AuthSession = Depends(current_session),
        db: Session = Depends(session_dependency),
    ):
        user = require_role(db, record, Role.ADMIN)
        require_csrf(request, record, csrf_token, origin)
        return user

    @router.get("", response_model=AdminProductListResponse)
    def list_admin_products(
        q: str = Query(default="", max_length=120),
        category: str | None = Query(default=None, max_length=80),
        is_listed: bool | None = None,
        page: int = Query(default=1, ge=1, le=100000),
        page_size: int = Query(default=20, ge=1, le=100),
        record: AuthSession = Depends(current_session),
        db: Session = Depends(session_dependency),
    ) -> AdminProductListResponse:
        require_role(db, record, Role.ADMIN)
        statement = select(Product)
        if q.strip():
            statement = statement.where(Product.name.icontains(q.strip(), autoescape=True) | Product.description.icontains(q.strip(), autoescape=True))
        if category is not None:
            statement = statement.where(Product.category == category)
        if is_listed is not None:
            statement = statement.where(Product.is_listed == is_listed)
        total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
        rows = db.scalars(statement.order_by(Product.created_at.desc(), Product.id).offset((page - 1) * page_size).limit(page_size)).all()
        return AdminProductListResponse(items=rows, total=total, page=page, page_size=page_size)

    @router.get("/{product_id}", response_model=AdminProductResponse)
    def read_product(product_id: UUID, record: AuthSession = Depends(current_session), db: Session = Depends(session_dependency)) -> AdminProductResponse:
        require_role(db, record, Role.ADMIN)
        return AdminProductResponse.model_validate(get_product(db, product_id))

    @router.post("", response_model=AdminProductResponse, status_code=201)
    def create_product(payload: ProductInput, user=Depends(write_admin), db: Session = Depends(session_dependency)) -> AdminProductResponse:
        current = now_utc()
        product = Product(id=uuid4(), stock=0, created_at=current, listed_at=current, **payload.model_dump())
        db.add(product)
        db.commit()
        return AdminProductResponse.model_validate(product)

    @router.patch("/{product_id}", response_model=AdminProductResponse)
    def update_product(product_id: UUID, payload: ProductPatch, user=Depends(write_admin), db: Session = Depends(session_dependency)) -> AdminProductResponse:
        product = get_product(db, product_id, lock=True)
        if payload.is_listed is True and not product.is_listed:
            product.listed_at = now_utc()
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(product, key, value)
        db.commit()
        return AdminProductResponse.model_validate(product)

    @router.post("/{product_id}/inventory-adjustments", response_model=InventoryAdjustmentResponse, status_code=201)
    def adjust_inventory(product_id: UUID, payload: InventoryAdjustmentInput, user=Depends(write_admin), db: Session = Depends(session_dependency)) -> InventoryAdjustmentResponse:
        product = get_product(db, product_id, lock=True)
        before_stock = product.stock
        after_stock = before_stock + payload.delta
        if after_stock < 0 or after_stock > 2147483647:
            raise HTTPException(status_code=409, detail="库存调整超出可用范围")
        adjustment = InventoryAdjustment(product_id=product.id, delta=payload.delta, before_stock=before_stock,
                                         after_stock=after_stock, reason=payload.reason, admin_id=user.id, created_at=now_utc())
        product.stock = after_stock
        db.add(adjustment)
        db.commit()
        return InventoryAdjustmentResponse.model_validate(adjustment)

    @router.get("/{product_id}/inventory-adjustments", response_model=InventoryAdjustmentListResponse)
    def list_inventory_adjustments(
        product_id: UUID,
        page: int = Query(default=1, ge=1, le=100000),
        page_size: int = Query(default=20, ge=1, le=100),
        record: AuthSession = Depends(current_session),
        db: Session = Depends(session_dependency),
    ) -> InventoryAdjustmentListResponse:
        require_role(db, record, Role.ADMIN)
        get_product(db, product_id)
        statement = select(InventoryAdjustment).where(InventoryAdjustment.product_id == product_id)
        total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
        rows = db.scalars(statement.order_by(InventoryAdjustment.created_at.desc(), InventoryAdjustment.id).offset((page - 1) * page_size).limit(page_size)).all()
        return InventoryAdjustmentListResponse(items=rows, total=total, page=page, page_size=page_size)

    return router
