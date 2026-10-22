from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select

from shop_api.identity import AuthSession, digest


def test_authenticated_session_expires_after_seven_days(client):
    token = client.get("/api/auth/csrf").json()["csrf_token"]
    email = f"{uuid4().hex}@example.com"
    registered = client.post(
        "/api/auth/register",
        headers={"X-CSRF-Token": token, "Origin": "http://testserver"},
        json={"email": email, "password": "portfolio-demo-pass-123"},
    )
    assert registered.status_code == 201
    token = client.get("/api/auth/csrf").json()["csrf_token"]
    assert client.post(
        "/api/auth/login",
        headers={"X-CSRF-Token": token, "Origin": "http://testserver"},
        json={"email": email, "password": "portfolio-demo-pass-123"},
    ).status_code == 200

    raw_cookie = client.cookies.get("shop_session")
    with client.app.state.session_factory() as session:
        auth_session = session.scalar(select(AuthSession).where(AuthSession.token_hash == digest(raw_cookie)))
        expiry = auth_session.expires_at

    client.app.state.clock = lambda: expiry + timedelta(microseconds=1)
    assert client.get("/api/auth/me").status_code == 401
