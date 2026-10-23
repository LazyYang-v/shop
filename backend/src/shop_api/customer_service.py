from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from shop_api.catalog import Product

_REQUEST_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
_LOGGER = logging.getLogger("shop_api.customer_service")


class CustomerServiceUnavailable(RuntimeError):
    pass


class QueryDeadlineExceeded(CustomerServiceUnavailable):
    pass


@dataclass(frozen=True)
class ProductFixture:
    id: str
    name: str
    category: str
    price: str
    stock: int
    is_listed: bool

    @classmethod
    def from_product(cls, product: Product) -> ProductFixture:
        return cls(str(product.id), product.name, product.category, str(product.price), product.stock, product.is_listed)

    def matches(self, product: Product) -> bool:
        return self == self.from_product(product)


class SharedLimiter:
    """PostgreSQL-backed atomic rolling-window limiter with fail-closed behavior."""

    def __init__(self, session_factory):
        self._factory = session_factory

    def allow(self, key: str, limit: int, window_seconds: int, now: datetime) -> tuple[bool, int]:
        try:
            with self._factory.begin() as session:
                now_ts = now.timestamp()
                cutoff = now_ts - window_seconds
                session.execute(text("INSERT INTO customer_service_rate_limits (bucket_key, hits, window_started_at, expires_at) VALUES (:key, 1, :now, :expires) ON CONFLICT (bucket_key) DO NOTHING"), {"key": key, "now": now_ts, "expires": now_ts + 3600})
                session.execute(text("SELECT bucket_key FROM customer_service_rate_limits WHERE bucket_key=:key FOR UPDATE"), {"key": key}).one()
                session.execute(text("DELETE FROM customer_service_rate_limit_events WHERE bucket_key=:key AND event_at <= :cutoff"), {"key": key, "cutoff": cutoff})
                count = session.scalar(text("SELECT count(*) FROM customer_service_rate_limit_events WHERE bucket_key=:key AND event_at > :cutoff"), {"key": key, "cutoff": cutoff})
                if count >= limit:
                    oldest = session.scalar(text("SELECT min(event_at) FROM customer_service_rate_limit_events WHERE bucket_key=:key AND event_at > :cutoff"), {"key": key, "cutoff": cutoff})
                    return False, max(1, math.ceil(oldest + window_seconds - now_ts))
                session.execute(text("INSERT INTO customer_service_rate_limit_events (bucket_key, event_at) VALUES (:key, :now)"), {"key": key, "now": now_ts})
                session.execute(text("UPDATE customer_service_rate_limits SET hits=:hits, window_started_at=:now, expires_at=:expires WHERE bucket_key=:key"), {"hits": count + 1, "now": now_ts, "expires": now_ts + 3600, "key": key})
            return True, 0
        except Exception as error:
            _LOGGER.warning("customer_service_guard_failed error=%s", type(error).__name__)
            raise CustomerServiceUnavailable from None


def check_fixture(session: Session, fixture_path: str | None, expected_digest: str | None) -> dict[str, ProductFixture]:
    if not fixture_path or not expected_digest:
        raise CustomerServiceUnavailable
    path = Path(fixture_path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024:
        raise CustomerServiceUnavailable
    try:
        raw = path.read_bytes()
        actual_digest = hashlib.sha256(raw).hexdigest()
        if not hmac.compare_digest(actual_digest, expected_digest.lower()):
            raise CustomerServiceUnavailable
        data = json.loads(raw)
        if not isinstance(data, list) or not 1 <= len(data) <= 20:
            raise CustomerServiceUnavailable
        fixtures: dict[str, ProductFixture] = {}
        for item in data:
            if not isinstance(item, dict) or set(item) != {"id", "name", "category", "price", "stock", "is_listed"}:
                raise CustomerServiceUnavailable
            product_id = str(item["id"])
            try:
                UUID(product_id)
            except ValueError:
                raise CustomerServiceUnavailable from None
            product = session.get(Product, product_id)
            if product is None or not product.is_listed:
                raise CustomerServiceUnavailable
            expected = ProductFixture.from_product(product)
            given = ProductFixture(product_id, item["name"], item["category"], item["price"], item["stock"], item["is_listed"])
            if given != expected or product_id in fixtures:
                raise CustomerServiceUnavailable
            fixtures[product_id] = expected
        return fixtures
    except CustomerServiceUnavailable:
        raise
    except Exception as error:
        _LOGGER.warning("customer_service_fixture_rejected error=%s", type(error).__name__)
        raise CustomerServiceUnavailable from None


class SafeLogWriter:
    def __init__(self, directory: str):
        self._directory = Path(directory)
        self._lock = Lock()

    def verify(self) -> None:
        if not self._directory.exists() or self._directory.is_symlink() or not self._directory.is_dir():
            raise PermissionError("Customer-service log directory is unavailable")
        if self._directory.stat().st_mode & 0o077:
            raise PermissionError("Customer-service log directory permissions are too broad")
        probe = self._directory / f".customer-service-probe-{os.getpid()}-{time.monotonic_ns()}"
        fd = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(fd)
        probe.unlink()

    def write(self, request_id: str, tool: str, error: str, duration_ms: int, count: int, now: datetime) -> None:
        if not _REQUEST_ID.fullmatch(request_id):
            raise ValueError("Invalid request identifier")
        safe_tool = tool if tool in {"list_products", "get_product"} else "unknown"
        safe_error = error if error in {"", "dependency_unavailable", "budget_exhausted", "rate_limited"} else "internal_error"
        record = {"request_id": request_id, "tool": safe_tool, "error": safe_error,
                  "duration_ms": max(0, int(duration_ms)), "count": max(0, int(count)),
                  "recorded_at": now.astimezone(UTC).isoformat()}
        if not self._directory.exists() or self._directory.is_symlink() or not self._directory.is_dir():
            raise PermissionError("Customer-service log directory is unavailable")
        if self._directory.stat().st_mode & 0o077:
            raise PermissionError("Customer-service log directory permissions are too broad")
        day = now.astimezone(UTC).strftime("%Y-%m-%d")
        path = self._directory / f"customer-service-{day}.jsonl"
        with self._lock:
            if path.is_symlink():
                raise OSError("Refusing a symbolic-link log target")
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
            try:
                if os.fstat(fd).st_mode & 0o077:
                    raise PermissionError("Customer-service log file permissions are too broad")
                os.write(fd, (json.dumps(record, separators=(",", ":")) + "\n").encode())
            finally:
                os.close(fd)

    def prune(self, now: datetime) -> int:
        cutoff = now.astimezone(UTC).timestamp() - 7 * 24 * 60 * 60
        deleted = 0
        failed = False
        self.verify()
        for entry in self._directory.iterdir():
            if entry.is_symlink() or not entry.is_file() or not re.fullmatch(r"customer-service-\d{4}-\d{2}-\d{2}\.jsonl", entry.name):
                continue
            try:
                # Expire the whole partition from its earliest possible record.
                # Hourly maintenance adds at most one hour; mtime would add a day.
                day = datetime.strptime(entry.name[17:-6], "%Y-%m-%d").replace(tzinfo=UTC)
                if day.timestamp() <= cutoff:
                    entry.unlink()
                    deleted += 1
            except (OSError, ValueError) as error:
                failed = True
                _LOGGER.warning("customer_service_log_prune_failed error=%s", type(error).__name__)
        if failed:
            raise CustomerServiceUnavailable
        return deleted


def acquire_query_turn(session: Session, session_id) -> bool:
    key = int.from_bytes(hashlib.sha256(f"customer-service-message:{session_id}".encode()).digest()[:8], "big", signed=True)
    QueryDeadline(3).apply(session)
    return bool(session.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key}))


class QueryDeadline:
    def __init__(self, seconds: float):
        self._expires_at = time.monotonic() + seconds

    def apply(self, session: Session, maximum_seconds: float | None = None) -> None:
        remaining = self._expires_at - time.monotonic()
        if maximum_seconds is not None:
            remaining = min(remaining, maximum_seconds)
        if remaining <= 0:
            raise QueryDeadlineExceeded
        if session.bind is None or session.bind.dialect.name != "postgresql":
            raise CustomerServiceUnavailable
        session.execute(text("SELECT set_config('statement_timeout', :timeout, true)"), {"timeout": str(max(1, int(remaining * 1000)))})

    def check(self) -> None:
        if time.monotonic() >= self._expires_at:
            raise QueryDeadlineExceeded


def cleanup_rate_limits(session_factory, now: datetime) -> int:
    try:
        with session_factory.begin() as session:
            result = session.execute(text("DELETE FROM customer_service_rate_limit_events WHERE event_at <= :cutoff"), {"cutoff": now.timestamp() - 3600})
            session.execute(text("DELETE FROM customer_service_rate_limits WHERE expires_at <= :now"), {"now": now.timestamp()})
            return result.rowcount or 0
    except Exception as error:
        _LOGGER.warning("customer_service_rate_limit_cleanup_failed error=%s", type(error).__name__)
        raise CustomerServiceUnavailable from None
