"""Pure admission tests: no engine, credentials, or database fixtures required."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from shop_api.customer_service_admission import require_demo_buyer, require_query_rate_limits
from shop_api.identity import User


class IdentityStore:
    def __init__(self, user):
        self.user = user

    def get(self, model, key):
        assert model is User
        return self.user if self.user.id == key else None


def request(state, *, client=("127.0.0.1", 1234)):
    return Request({"type": "http", "app": SimpleNamespace(state=state), "client": client,
                    "headers": [(b"cookie", b"shop_session=synthetic-session"),
                                (b"x-forwarded-for", b"untrusted-address")]})


def test_demo_admission_rejects_disabled_unapproved_inactive_and_admin():
    buyer_id = uuid4()
    user = SimpleNamespace(id=buyer_id, role="buyer", is_active=True)
    record = SimpleNamespace(kind="authenticated", user_id=buyer_id)
    state = SimpleNamespace(customer_service_enabled=True, customer_service_buyer_ids={buyer_id})
    assert require_demo_buyer(request(state), record, IdentityStore(user)) is user
    for field, value, status in [("customer_service_enabled", False, 503),
                                  ("customer_service_buyer_ids", set(), 403)]:
        previous = getattr(state, field)
        setattr(state, field, value)
        with pytest.raises(HTTPException) as failure:
            require_demo_buyer(request(state), record, IdentityStore(user))
        assert failure.value.status_code == status
        setattr(state, field, previous)
    user.role = "admin"
    with pytest.raises(HTTPException) as failure:
        require_demo_buyer(request(state), record, IdentityStore(user))
    assert failure.value.status_code == 403
    user.role, user.is_active = "buyer", False
    with pytest.raises(HTTPException) as failure:
        require_demo_buyer(request(state), record, IdentityStore(user))
    assert failure.value.status_code == 401


def test_query_quota_uses_connection_address_and_fail_closed_retry():
    class Limiter:
        def __init__(self):
            self.calls = []

        def allow(self, key, limit, seconds, now):
            self.calls.append((key, limit, seconds))
            return (not key.startswith("ip:"), 17)

    limiter = Limiter()
    state = SimpleNamespace(customer_service_limiter=limiter, clock=lambda: datetime(2026, 10, 23, tzinfo=UTC))
    with pytest.raises(HTTPException) as failure:
        require_query_rate_limits(request(state))
    assert failure.value.status_code == 429
    assert failure.value.headers == {"Retry-After": "17"}
    assert [call[1:] for call in limiter.calls] == [(20, 60), (60, 60)]
    assert all("synthetic-session" not in call[0] and "untrusted-address" not in call[0] for call in limiter.calls)
    with pytest.raises(HTTPException) as failure:
        require_query_rate_limits(request(state, client=None))
    assert failure.value.status_code == 503
