from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Boolean, ForeignKey, String, Uuid, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from shop_api.database import Base
from shop_api.identity import User


class Address(Base):
    __tablename__ = "addresses"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    recipient_name: Mapped[str] = mapped_column(String(80), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    province: Mapped[str] = mapped_column(String(80), nullable=False)
    city: Mapped[str] = mapped_column(String(80), nullable=False)
    district: Mapped[str] = mapped_column(String(80), nullable=False)
    detail: Mapped[str] = mapped_column(String(240), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AddressInput(BaseModel):
    recipient_name: str = Field(min_length=1, max_length=80)
    phone: str = Field(min_length=6, max_length=32)
    province: str = Field(min_length=1, max_length=80)
    city: str = Field(min_length=1, max_length=80)
    district: str = Field(min_length=1, max_length=80)
    detail: str = Field(min_length=1, max_length=240)
    is_default: bool = False


class AddressPatch(BaseModel):
    recipient_name: str | None = Field(default=None, min_length=1, max_length=80)
    phone: str | None = Field(default=None, min_length=6, max_length=32)
    province: str | None = Field(default=None, min_length=1, max_length=80)
    city: str | None = Field(default=None, min_length=1, max_length=80)
    district: str | None = Field(default=None, min_length=1, max_length=80)
    detail: str | None = Field(default=None, min_length=1, max_length=240)
    is_default: bool | None = None


class AddressResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    recipient_name: str
    phone: str
    province: str
    city: str
    district: str
    detail: str
    is_default: bool


class AddressListResponse(BaseModel):
    items: list[AddressResponse]


def list_addresses(session: Session, user: User) -> AddressListResponse:
    rows = session.scalars(select(Address).where(Address.user_id == user.id).order_by(Address.is_default.desc(), Address.id)).all()
    return AddressListResponse(items=[AddressResponse.model_validate(row) for row in rows])


def create_address(session: Session, user: User, payload: AddressInput) -> AddressResponse:
    current = session.scalar(select(Address).where(Address.user_id == user.id))
    address = Address(user_id=user.id, **payload.model_dump())
    if current is None:
        address.is_default = True
    elif address.is_default:
        for row in session.scalars(select(Address).where(Address.user_id == user.id, Address.is_default.is_(True))):
            row.is_default = False
    session.add(address)
    session.commit()
    return AddressResponse.model_validate(address)


def update_address(session: Session, user: User, address_id: UUID, payload: AddressPatch) -> AddressResponse:
    address = session.scalar(select(Address).where(Address.id == address_id, Address.user_id == user.id))
    if address is None:
        raise HTTPException(status_code=404, detail="收货地址不存在")
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("is_default"):
        for row in session.scalars(select(Address).where(Address.user_id == user.id, Address.is_default.is_(True))):
            row.is_default = False
    for key, value in changes.items():
        setattr(address, key, value)
    session.commit()
    return AddressResponse.model_validate(address)


def delete_address(session: Session, user: User, address_id: UUID) -> None:
    address = session.scalar(select(Address).where(Address.id == address_id, Address.user_id == user.id))
    if address is None:
        raise HTTPException(status_code=404, detail="收货地址不存在")
    session.delete(address)
    session.commit()
