from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from fastapi import Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from pwdlib import PasswordHash
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, LargeBinary, String, Uuid, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from shop_api.database import Base

SESSION_COOKIE = "shop_session"
SESSION_HEADER = "X-CSRF-Token"
ANONYMOUS_TTL = timedelta(minutes=30)
AUTHENTICATED_TTL = timedelta(days=7)
PASSWORD_HASHER = PasswordHash.recommended()


class Role(StrEnum):
    BUYER = "buyer"
    ADMIN = "admin"


class User(Base):
    __tablename__ = "users"
    __table_args__ = ({"sqlite_autoincrement": True},)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default=Role.BUYER.value)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sessions: Mapped[list[AuthSession]] = relationship(back_populates="user")


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        Index("ix_auth_sessions_expires_at", "expires_at"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True, nullable=False)
    csrf_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user: Mapped[User | None] = relationship(back_populates="sessions")


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    role: str


class CsrfResponse(BaseModel):
    csrf_token: str


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def find_session(session: Session, raw_token: str | None, now: datetime | None = None) -> AuthSession | None:
    if not raw_token:
        return None
    current = now or now_utc()
    record = session.scalar(select(AuthSession).where(AuthSession.token_hash == digest(raw_token)))
    if record is None or record.revoked_at is not None or record.expires_at <= current:
        return None
    return record


def set_session_cookie(response: Response, raw_token: str, expires_at: datetime, secure: bool) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        raw_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
        expires=expires_at,
    )


def clear_session_cookie(response: Response, secure: bool) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", secure=secure, httponly=True, samesite="lax")


def create_session(session: Session, kind: str, user: User | None = None) -> tuple[AuthSession, str, str]:
    current = now_utc()
    raw_id = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    record = AuthSession(
        token_hash=digest(raw_id),
        csrf_hash=digest(csrf_token),
        user_id=user.id if user else None,
        kind=kind,
        created_at=current,
        expires_at=current + (ANONYMOUS_TTL if kind == "anonymous" else AUTHENTICATED_TTL),
    )
    session.add(record)
    session.flush()
    return record, raw_id, csrf_token


def make_current_session_dependency(session_dependency, clock=now_utc):
    def dependency(
        db: Session = Depends(session_dependency),
        shop_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    ) -> AuthSession:
        record = find_session(db, shop_session, now=clock())
        if record is None:
            raise HTTPException(status_code=401, detail="需要登录")
        return record

    return dependency


def require_csrf(
    request: Request,
    record: AuthSession,
    csrf_token: str | None,
    origin: str | None,
) -> None:
    expected_origin = str(request.base_url).rstrip("/")
    if not origin or origin.rstrip("/") != expected_origin:
        raise HTTPException(status_code=403, detail="请求来源校验失败")
    if not csrf_token or not secrets.compare_digest(record.csrf_hash, digest(csrf_token)):
        raise HTTPException(status_code=403, detail="CSRF Token 无效或已过期")


def get_csrf(
    response: Response,
    db: Session,
    record: AuthSession | None,
    raw_token: str | None,
    secure_cookie: bool,
) -> CsrfResponse:
    if record is None:
        record, raw_token, csrf_token = create_session(db, "anonymous")
        db.commit()
        set_session_cookie(response, raw_token, record.expires_at, secure_cookie)
    else:
        csrf_token = secrets.token_urlsafe(32)
        record.csrf_hash = digest(csrf_token)
        db.commit()
    response.headers["Cache-Control"] = "no-store"
    return CsrfResponse(csrf_token=csrf_token)


def register_buyer(db: Session, credentials: Credentials) -> None:
    user = User(
        email=credentials.email,
        password_hash=PASSWORD_HASHER.hash(credentials.password),
        role=Role.BUYER.value,
        is_active=True,
        created_at=now_utc(),
    )
    db.add(user)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="该邮箱已注册") from None


def authenticate(db: Session, credentials: Credentials) -> User:
    user = db.scalar(select(User).where(User.email == credentials.email))
    if user is None or not user.is_active or not PASSWORD_HASHER.verify(credentials.password, user.password_hash):
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    return user


def revoke(record: AuthSession) -> None:
    record.revoked_at = now_utc()


def require_role(db: Session, record: AuthSession, role: Role) -> User:
    if record.kind != "authenticated" or record.user_id is None:
        raise HTTPException(status_code=401, detail="需要登录")
    user = db.get(User, record.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="需要登录")
    if user.role != role.value:
        raise HTTPException(status_code=403, detail="无权执行此操作")
    return user
