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
    emails = [f'cs-browser-{secrets.token_hex(8)}@example.com' for _ in range(2)]
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
    url = client.app.state.session_factory.kw['bind'].url.render_as_string(hide_password=False)
    app = create_app(database_url=url)
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
                       SHOP_BROWSER_TEST_CLOCK_KEY=test_clock_key)
            result = subprocess.run(['node', str(root / 'e2e/customer-service-real.mjs')], env=env, capture_output=True, text=True, timeout=45)
            assert result.returncode == 0, result.stdout + result.stderr
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            assert not thread.is_alive()
    records = [json.loads(line) for path in logs.glob('customer-service-*.jsonl') for line in path.read_text().splitlines()]
    assert {record['tool'] for record in records} == {'list_products', 'get_product'}
    assert all(set(record) == {'request_id', 'tool', 'error', 'duration_ms', 'count', 'recorded_at'} for record in records)
