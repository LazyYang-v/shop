from uuid import uuid4


def csrf(client):
    response = client.get("/api/auth/csrf")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["csrf_token"]
    assert client.cookies.get("shop_session")
    return response.json()["csrf_token"]


def test_registration_requires_anonymous_csrf_and_creates_buyer_only(client):
    token = csrf(client)
    email = f"Buyer-{uuid4().hex}@Example.COM"
    response = client.post(
        "/api/auth/register",
        headers={"X-CSRF-Token": token, "Origin": "http://testserver"},
        json={"email": email, "password": "portfolio-demo-pass-123"},
    )

    assert response.status_code == 201
    assert response.json() == {"message": "注册成功，请登录。"}
    assert client.get("/api/auth/me").status_code == 401


def test_registration_rejects_csrf_from_another_session(client):
    token = csrf(client)
    client.get("/api/auth/csrf")

    response = client.post(
        "/api/auth/register",
        headers={"X-CSRF-Token": token, "Origin": "http://testserver"},
        json={"email": f"{uuid4().hex}@example.com", "password": "portfolio-demo-pass-123"},
    )

    assert response.status_code == 403


def test_login_rotates_anonymous_session_and_refresh_restores_user(client):
    email = f"{uuid4().hex}@example.com"
    anonymous_token = csrf(client)
    registered = client.post(
        "/api/auth/register",
        headers={"X-CSRF-Token": anonymous_token, "Origin": "http://testserver"},
        json={"email": email, "password": "portfolio-demo-pass-123"},
    )
    assert registered.status_code == 201

    anonymous_session = client.cookies.get("shop_session")
    login_token = csrf(client)
    response = client.post(
        "/api/auth/login",
        headers={"X-CSRF-Token": login_token, "Origin": "http://testserver"},
        json={"email": email.upper(), "password": "portfolio-demo-pass-123"},
    )

    assert response.status_code == 200
    assert response.json()["user"]["email"] == email.lower()
    authenticated_session = client.cookies.get("shop_session")
    assert authenticated_session != anonymous_session
    assert client.get("/api/auth/me").json()["email"] == email.lower()
    assert client.get("/api/auth/csrf").json()["csrf_token"]


def test_registration_keeps_anonymous_session_for_login(client):
    email = f"{uuid4().hex}@example.com"
    token = csrf(client)
    assert client.post(
        "/api/auth/register",
        headers={"X-CSRF-Token": token, "Origin": "http://testserver"},
        json={"email": email, "password": "portfolio-demo-pass-123"},
    ).status_code == 201

    login = client.post(
        "/api/auth/login",
        headers={"X-CSRF-Token": token, "Origin": "http://testserver"},
        json={"email": email, "password": "portfolio-demo-pass-123"},
    )
    assert login.status_code == 200


def test_logout_revokes_session_and_protected_admin_api_checks_role(client):
    admin_email = "admin@example.com"
    admin_password = __import__("os").environ["SHOP_TEST_ADMIN_PASSWORD"]
    token = csrf(client)
    login = client.post(
        "/api/auth/login",
        headers={"X-CSRF-Token": token, "Origin": "http://testserver"},
        json={"email": admin_email, "password": admin_password},
    )
    assert login.status_code == 200
    assert client.get("/api/admin/access").json()["role"] == "admin"

    token = csrf(client)
    logout = client.post(
        "/api/auth/logout",
        headers={"X-CSRF-Token": token, "Origin": "http://testserver"},
    )
    assert logout.status_code == 204
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/admin/access").status_code == 401


def test_anonymous_admin_api_returns_401(client):
    assert client.get("/api/admin/access").status_code == 401


def test_buyer_cannot_access_admin_api(client):
    email = f"{uuid4().hex}@example.com"
    token = csrf(client)
    assert client.post(
        "/api/auth/register",
        headers={"X-CSRF-Token": token, "Origin": "http://testserver"},
        json={"email": email, "password": "portfolio-demo-pass-123"},
    ).status_code == 201
    assert client.post(
        "/api/auth/login",
        headers={"X-CSRF-Token": token, "Origin": "http://testserver"},
        json={"email": email, "password": "portfolio-demo-pass-123"},
    ).status_code == 200

    assert client.get("/api/admin/access").status_code == 403


def test_login_failure_has_generic_message_and_requires_csrf(client):
    token = csrf(client)
    bad_login = client.post(
        "/api/auth/login",
        headers={"X-CSRF-Token": token, "Origin": "http://testserver"},
        json={"email": "missing@example.com", "password": "wrong-password-long"},
    )
    assert bad_login.status_code == 401
    assert bad_login.json()["detail"] == "邮箱或密码错误"

    without_csrf = client.post(
        "/api/auth/login",
        headers={"Origin": "http://testserver"},
        json={"email": "missing@example.com", "password": "wrong-password-long"},
    )
    assert without_csrf.status_code == 403
