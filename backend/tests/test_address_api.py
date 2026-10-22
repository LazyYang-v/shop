from uuid import uuid4


def register_and_login(client, email: str) -> str:
    token = client.get("/api/auth/csrf").json()["csrf_token"]
    headers = {"X-CSRF-Token": token, "Origin": "http://testserver"}
    assert client.post("/api/auth/register", headers=headers, json={"email": email, "password": "portfolio-demo-pass-123"}).status_code == 201
    assert client.post("/api/auth/login", headers=headers, json={"email": email, "password": "portfolio-demo-pass-123"}).status_code == 200
    return client.get("/api/auth/csrf").json()["csrf_token"]


def test_buyer_can_create_list_update_and_delete_owned_addresses(client):
    token = register_and_login(client, f"address-{uuid4().hex}@example.com")
    headers = {"X-CSRF-Token": token, "Origin": "http://testserver"}
    payload = {"recipient_name": "林女士", "phone": "13800138000", "province": "浙江省", "city": "杭州市", "district": "西湖区", "detail": "文三路 1 号"}

    created = client.post("/api/addresses", headers=headers, json=payload)
    assert created.status_code == 201
    address = created.json()
    assert address["recipient_name"] == "林女士"
    assert address["is_default"] is True
    assert client.get("/api/addresses").json() == {"items": [address]}

    updated = client.patch(f"/api/addresses/{address['id']}", headers=headers, json={"detail": "文三路 2 号"})
    assert updated.status_code == 200
    assert updated.json()["detail"] == "文三路 2 号"
    assert client.delete(f"/api/addresses/{address['id']}", headers=headers).status_code == 204
    assert client.get("/api/addresses").json() == {"items": []}


def test_buyer_cannot_access_another_buyers_address(client):
    first_token = register_and_login(client, f"address-a-{uuid4().hex}@example.com")
    first_headers = {"X-CSRF-Token": first_token, "Origin": "http://testserver"}
    created = client.post("/api/addresses", headers=first_headers, json={"recipient_name": "甲", "phone": "13800138000", "province": "浙江省", "city": "杭州市", "district": "西湖区", "detail": "地址一"})
    address_id = created.json()["id"]

    client.post("/api/auth/logout", headers=first_headers)
    second_token = register_and_login(client, f"address-b-{uuid4().hex}@example.com")
    second_headers = {"X-CSRF-Token": second_token, "Origin": "http://testserver"}
    assert client.patch(f"/api/addresses/{address_id}", headers=second_headers, json={"detail": "越权"}).status_code == 404
    assert client.delete(f"/api/addresses/{address_id}", headers=second_headers).status_code == 404
