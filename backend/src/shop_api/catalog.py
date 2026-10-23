from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import BigInteger, DateTime, Numeric, String, Text, Uuid, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from shop_api.database import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    image_url: Mapped[str] = mapped_column(String(500), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    stock: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_listed: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    listed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    category: str
    description: str
    image_url: str
    price: Decimal
    stock: int


class ProductListResponse(BaseModel):
    items: list[ProductResponse]
    total: int
    page: int = 1
    page_size: int = 20


class CatalogQuery(BaseModel):
    q: str = Field(default="", max_length=120)
    category: str | None = Field(default=None, max_length=80)
    sort: str = Field(default="popular", pattern="^(popular|price_asc|price_desc)$")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


def list_categories(session: Session) -> list[str]:
    return list(session.scalars(select(Product.category).where(Product.is_listed.is_(True)).distinct().order_by(Product.category)).all())


def list_products(session: Session, query: CatalogQuery | None = None) -> ProductListResponse:
    query = query or CatalogQuery()
    statement = select(Product).where(Product.is_listed.is_(True))
    if query.q.strip():
        term = f"%{query.q.strip()}%"
        statement = statement.where(Product.name.ilike(term) | Product.description.ilike(term))
    if query.category:
        statement = statement.where(Product.category == query.category)
    ordering = {
        "popular": (Product.listed_at.desc(), Product.id.asc()),
        "price_asc": (Product.price.asc(), Product.id.asc()),
        "price_desc": (Product.price.desc(), Product.id.asc()),
    }[query.sort]
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    products = session.scalars(statement.order_by(*ordering).offset((query.page - 1) * query.page_size).limit(query.page_size)).all()
    return ProductListResponse(items=products, total=total, page=query.page, page_size=query.page_size)
