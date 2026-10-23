import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
from threading import Thread
import time

import pytest
from fastapi.staticfiles import StaticFiles
import uvicorn

from shop_api.app import create_app


@pytest.mark.skipif(os.getenv('SHOP_RUN_BROWSER_TESTS') != '1', reason='Opt in to real browser integration')
def test_customer_service_browser_queries_real_isolated_catalog(client, tmp_path, monkeypatch):
    if not shutil.which('node'):
        pytest.fail('Node is required for real browser integration')
    password = secrets.token_urlsafe(24)
    emails = [f'checkout-cs-browser-{secrets.token_hex(8)}@example.com' for _ in range(2)]
    buyer_ids = []
    for email in emails:
        csrf = client.get('/api/auth/csrf').json()['csrf_token']
        response = client.post('/api/auth/register', headers={'Origin': 'http://testserver', 'X-CSRF-Token': csrf}, json={'email': email, 'password': password})
        assert response.status_code == 201
        csrf = client.get('/api/auth/csrf').json()['csrf_token']
        assert client.post('/api/auth/login', headers={'Origin': 'http://testserver', 'X-CSRF-Token': csrf}, json={'email': email, 'password': password}).status_code == 200
        buyer_ids.append(client.get('/api/auth/me').json()['id'])
        csrf = client.get('/api/auth/csrf').json()['csrf_token']
        assert client.post('/api/auth/logout', headers={'Origin': 'http://testserver', 'X-CSRF-Token': csrf}).status_code == 204

    # Seed one owner-visible order with saved logistics for the real browser flow.
    csrf = client.get('/api/auth/csrf').json()['csrf_token']
    headers = {'Origin': 'http://testserver', 'X-CSRF-Token': csrf}
    assert client.post('/api/auth/login', headers=headers, json={'email': emails[0], 'password': password}).status_code == 200
    headers['X-CSRF-Token'] = client.get('/api/auth/csrf').json()['csrf_token']
    address = client.post('/api/addresses', headers=headers, json={
        'recipient_name': '林女士', 'phone': '13800138000', 'province': '浙江省',
        'city': '杭州市', 'district': '西湖区', 'detail': '文三路 1 号'}).json()
    assert client.post('/api/cart/items', headers=headers, json={
        'product_id': '00000000-0000-0000-0000-000000000001', 'quantity': 1}).status_code == 201
    order = client.post('/api/orders', headers={**headers, 'Idempotency-Key': secrets.token_hex(16)},
                        json={'address_id': address['id']})
    assert order.status_code == 201
    order_id = order.json()['id']
    from sqlalchemy import text as sql_text
    with client.app.state.session_factory.begin() as db:
        db.execute(sql_text("""UPDATE orders SET status='pending_receipt', shipping_company='虚构速运',
            tracking_number='DEMO-BROWSER-001', shipped_at=:now,
            phone='PRIVATE_PHONE_SENTINEL', detail='PRIVATE_ADDRESS_SENTINEL' WHERE id=:id"""),
                   {'now': client.app.state.clock(), 'id': order_id})
        # The synthetic catalog fixture fixes stock at 24; this seeded order is
        # display-only and must not make the verified fixture fail closed.
        db.execute(sql_text("UPDATE products SET stock=24 WHERE id='00000000-0000-0000-0000-000000000001'"))
    csrf = client.get('/api/auth/csrf').json()['csrf_token']
    assert client.post('/api/auth/logout', headers={'Origin': 'http://testserver', 'X-CSRF-Token': csrf}).status_code == 204

    fixture = tmp_path / 'fixture.json'
    raw = json.dumps([{'id': '00000000-0000-0000-0000-000000000001', 'name': '春日轻盈针织开衫', 'category': '女装', 'price': '129.00', 'stock': 24, 'is_listed': True}], ensure_ascii=False).encode()
    fixture.write_bytes(raw)
    logs = tmp_path / 'logs'
    logs.mkdir(mode=0o700)
    monkeypatch.setenv('SHOP_CUSTOMER_SERVICE_DEMO_MODE', '1')
    monkeypatch.setenv('SHOP_CUSTOMER_SERVICE_FIXTURE_PATH', str(fixture))
    monkeypatch.setenv('SHOP_CUSTOMER_SERVICE_FIXTURE_SHA256', hashlib.sha256(raw).hexdigest())
    monkeypatch.setenv('SHOP_CUSTOMER_SERVICE_LOG_DIRECTORY', str(logs))
    monkeypatch.setenv('SHOP_CUSTOMER_SERVICE_BUYER_IDS', ','.join(buyer_ids))
    policy = Path(__file__).resolve().parents[2] / 'deploy/customer-service-demo/policies.synthetic.v1.json'
    monkeypatch.setenv('SHOP_CUSTOMER_SERVICE_POLICY_PATH', str(policy))
    monkeypatch.setenv('SHOP_CUSTOMER_SERVICE_POLICY_SHA256', hashlib.sha256(policy.read_bytes()).hexdigest())
    url = client.app.state.session_factory.kw['bind'].url.render_as_string(hide_password=False)
    from sqlalchemy import text
    with client.app.state.session_factory() as db:
        previous_reservations = set(db.scalars(text('SELECT id FROM customer_service_model_reservations')))
    exchanges = []
    def synthetic_exchange(payload, token, timeout):
        exchanges.append(json.dumps(payload, ensure_ascii=False))
        tool_reply = payload['messages'][-1]['role'] == 'tool'
        message = ({'role': 'assistant', 'content': '{"intent":"price_stock","product_refs":["product_1"]}'} if tool_reply
                   else {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'call_1', 'type': 'function',
                         'function': {'name': 'get_product', 'arguments': '{"product_ref":"product_1"}'}}]})
        return {'object': 'chat.completion', 'choices': [{'finish_reason': 'stop' if tool_reply else 'tool_calls', 'message': message}],
                'usage': {'prompt_tokens': 150, 'completion_tokens': 30}}
    app = create_app(database_url=url, synthetic_product_exchange=synthetic_exchange)
    from datetime import timedelta
    from fastapi import Header, HTTPException
    test_clock_key = secrets.token_urlsafe(32)
    clock_offset = timedelta()
    real_clock = app.state.clock
    app.state.clock = lambda: real_clock() + clock_offset

    @app.post('/__test/advance-clock')
    def advance_clock(minutes: int, x_test_key: str = Header()):
        nonlocal clock_offset
        if not secrets.compare_digest(x_test_key, test_clock_key) or not 0 <= minutes <= 31:
            raise HTTPException(403)
        clock_offset += timedelta(minutes=minutes)
        return {'ok': True}

    root = Path(__file__).resolve().parents[2]
    app.mount('/', StaticFiles(directory=root / 'public', html=True))
    server = uvicorn.Server(uvicorn.Config(app, log_config=None, access_log=False, log_level='critical'))
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        thread = Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and time.monotonic() < deadline:
                time.sleep(0.05)
            assert server.started
            env = os.environ.copy()
            env.update(SHOP_BROWSER_TEST_ORIGIN=f'http://127.0.0.1:{port}', SHOP_BROWSER_TEST_EMAIL=emails[0], SHOP_BROWSER_TEST_PASSWORD=password,
                       SHOP_BROWSER_TEST_EMAIL_2=emails[1], SHOP_BROWSER_TEST_ORDER_ID=order_id,
                       SHOP_BROWSER_TEST_CLOCK_KEY=test_clock_key)
            result = subprocess.run(['node', str(root / 'e2e/customer-service-real.mjs')], env=env, capture_output=True, text=True, timeout=45)
            assert result.returncode == 0, result.stdout + result.stderr
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            assert not thread.is_alive()
    app.state.customer_service_synthetic_transport.close()
    with app.state.session_factory.begin() as db:
        created_reservations = set(db.scalars(text('SELECT id FROM customer_service_model_reservations'))) - previous_reservations
        for reservation_id in created_reservations:
            db.execute(text('DELETE FROM customer_service_model_reservations WHERE id=:id'), {'id': reservation_id})
    assert len(exchanges) == 4
    for forbidden in ['PRIVATE_SENTINEL', 'PRIVATE_POLICY_SENTINEL', 'PRIVATE_RESEARCH_SENTINEL',
                      'PRIVATE_PHONE_SENTINEL', 'PRIVATE_ADDRESS_SENTINEL', 'DEMO-BROWSER-001', order_id,
                      '春日', '00000000-0000-0000-0000-000000000001', password, test_clock_key, *emails]:
        assert all(forbidden not in exchange for exchange in exchanges)
        assert all(forbidden not in path.read_text() for path in logs.glob('*.jsonl'))
    records = [json.loads(line) for path in logs.glob('customer-service-*.jsonl') for line in path.read_text().splitlines()]
    assert {record['tool'] for record in records} == {'list_products', 'get_product', 'list_my_orders',
                                                       'get_my_order', 'search_policy'}
    assert all(set(record) == {'request_id', 'tool', 'error', 'duration_ms', 'count', 'recorded_at'} for record in records)
