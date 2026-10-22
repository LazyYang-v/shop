from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select

from shop_api.identity import AuthSession, User, digest
from shop_api.cli import cleanup_expired_sessions


def test_expired_anonymous_session_is_rejected_and_cleanup_removes_only_expired(client):
    token = client.get("/api/auth/csrf").json()["csrf_token"]
    raw_cookie = client.cookies.get("shop_session")
    assert raw_cookie

    with client.app.state.session_factory.begin() as session:
        anonymous = session.scalar(select(AuthSession).where(AuthSession.token_hash == digest(raw_cookie)))
        anonymous.expires_at = anonymous.created_at - timedelta(seconds=1)

    assert client.post(
        "/api/auth/register",
        headers={"X-CSRF-Token": token, "Origin": "http://testserver"},
        json={"email": f"{uuid4().hex}@example.com", "password": "portfolio-demo-pass-123"},
    ).status_code == 403

    with client.app.state.session_factory.begin() as session:
        user = User(
            email=f"active-{uuid4().hex}@example.com",
            password_hash="unused-test-hash",
            role="buyer",
            is_active=True,
            created_at=anonymous.created_at,
        )
        session.add(user)
        session.flush()
        active = AuthSession(
            token_hash=digest(f"active-session-{uuid4().hex}"),
            csrf_hash=digest(f"active-csrf-{uuid4().hex}"),
            user_id=user.id,
            kind="authenticated",
            created_at=anonymous.created_at,
            expires_at=anonymous.created_at + timedelta(days=7),
        )
        session.add(active)

    database_url = client.app.state.session_factory.kw["bind"].url.render_as_string(hide_password=False)
    deleted = cleanup_expired_sessions(database_url)
    assert deleted >= 1
    with client.app.state.session_factory() as session:
        remaining = session.scalars(select(AuthSession)).all()
        assert all(record.expires_at > anonymous.created_at for record in remaining)
        assert any(record.kind == "authenticated" for record in remaining)
