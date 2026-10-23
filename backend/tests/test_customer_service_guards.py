import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from shop_api.customer_service import CustomerServiceUnavailable, QueryDeadline, SafeLogWriter, SharedLimiter, check_fixture


def test_shared_limiter_enforces_atomic_rolling_window(client):
    limiter = SharedLimiter(client.app.state.session_factory)
    now = datetime.now(UTC)
    key = f"test:customer-service:{uuid4()}"

    assert limiter.allow(key, 2, 60, now)[0] is True
    assert limiter.allow(key, 2, 60, now)[0] is True
    blocked, retry_after = limiter.allow(key, 2, 60, now)
    assert blocked is False
    assert 1 <= retry_after <= 60
    assert limiter.allow(key, 2, 60, now + timedelta(seconds=61))[0] is True


def test_shared_limiter_keeps_recent_events_when_oldest_event_expires(client):
    limiter = SharedLimiter(client.app.state.session_factory)
    now = datetime.now(UTC)
    key = f"test:rolling:{uuid4()}"

    assert limiter.allow(key, 2, 60, now)[0] is True
    assert limiter.allow(key, 2, 60, now + timedelta(seconds=30))[0] is True
    assert limiter.allow(key, 2, 60, now + timedelta(seconds=59)) == (False, 1)
    assert limiter.allow(key, 2, 60, now + timedelta(seconds=60))[0] is True
    assert limiter.allow(key, 2, 60, now + timedelta(seconds=60.5)) == (False, 30)


def test_short_window_does_not_erase_another_buckets_longer_window(client):
    limiter = SharedLimiter(client.app.state.session_factory)
    now = datetime.now(UTC)
    long_key = f"test:long:{uuid4()}"
    short_key = f"test:short:{uuid4()}"

    assert limiter.allow(long_key, 1, 3600, now)[0] is True
    assert limiter.allow(short_key, 1, 60, now + timedelta(seconds=120))[0] is True
    assert limiter.allow(long_key, 1, 3600, now + timedelta(seconds=120)) == (False, 3480)


def test_shared_limiter_serializes_concurrent_requests_across_instances(client):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    now = datetime.now(UTC)
    key = f"test:concurrent:{uuid4()}"
    barrier = Barrier(8)

    def request(_):
        limiter = SharedLimiter(client.app.state.session_factory)
        barrier.wait(timeout=10)
        return limiter.allow(key, 3, 60, now)[0]

    with ThreadPoolExecutor(max_workers=8) as workers:
        results = list(workers.map(request, range(8)))
    assert results.count(True) == 3
    assert results.count(False) == 5


def test_shared_limiter_fails_closed_when_storage_is_unavailable(client, monkeypatch):
    def unavailable(*args, **kwargs):
        raise RuntimeError("private database error")

    monkeypatch.setattr(client.app.state.session_factory, "begin", unavailable)
    with pytest.raises(CustomerServiceUnavailable):
        SharedLimiter(client.app.state.session_factory).allow("test:unavailable", 1, 60, datetime.now(UTC))


def test_fixture_requires_an_external_digest_and_exact_catalog_facts(client, tmp_path):
    product_id = "00000000-0000-0000-0000-000000000001"
    payload = [{"id": product_id, "name": "春日轻盈针织开衫", "category": "女装", "price": "129.00", "stock": 24, "is_listed": True}]
    fixture = tmp_path / "products.json"
    raw = json.dumps(payload, ensure_ascii=False).encode()
    fixture.write_bytes(raw)

    accepted = check_fixture(client.app.state.session_factory(), str(fixture), hashlib.sha256(raw).hexdigest())
    assert list(accepted) == [product_id]
    with pytest.raises(CustomerServiceUnavailable):
        check_fixture(client.app.state.session_factory(), str(fixture), "0" * 64)


def test_fixture_rejects_unknown_product_facts_and_more_than_twenty_items(client, tmp_path):
    product_id = "00000000-0000-0000-0000-000000000001"
    payload = [{"id": product_id, "name": "被篡改商品", "category": "女装", "price": "129.00", "stock": 24, "is_listed": True}]
    fixture = tmp_path / "products.json"
    raw = json.dumps(payload, ensure_ascii=False).encode()
    fixture.write_bytes(raw)
    with pytest.raises(CustomerServiceUnavailable):
        check_fixture(client.app.state.session_factory(), str(fixture), hashlib.sha256(raw).hexdigest())

    many = [dict(payload[0], id=f"00000000-0000-4000-8000-{index:012d}") for index in range(21)]
    raw = json.dumps(many, ensure_ascii=False).encode()
    fixture.write_bytes(raw)
    with pytest.raises(CustomerServiceUnavailable):
        check_fixture(client.app.state.session_factory(), str(fixture), hashlib.sha256(raw).hexdigest())


@pytest.mark.parametrize('operation', ['apply', 'check'])
def test_query_deadline_rejects_expired_session(client, monkeypatch, operation):
    import shop_api.customer_service as customer_service

    moments = iter((10.0, 11.0))
    monkeypatch.setattr(customer_service.time, "monotonic", lambda: next(moments))
    deadline = QueryDeadline(0.5)
    with client.app.state.session_factory() as session:
        with pytest.raises(customer_service.QueryDeadlineExceeded):
            if operation == 'apply':
                deadline.apply(session)
            else:
                deadline.check()


def test_safe_log_writer_omits_unapproved_fields_and_prunes_expired_partitions(tmp_path):
    writer = SafeLogWriter(str(tmp_path))
    now = datetime.now(UTC)
    request_id = "8a3adfa6-7a43-4b29-8b64-d6b34e695c15"
    writer.write(request_id, "list_products", "", 17, 1, now)
    log_path = tmp_path / f"customer-service-{now:%Y-%m-%d}.jsonl"
    record = json.loads(log_path.read_text())
    assert record == {
        "request_id": request_id,
        "tool": "list_products",
        "error": "",
        "duration_ms": 17,
        "count": 1,
        "recorded_at": now.isoformat(),
    }

    expired = now - timedelta(days=8)
    old_path = tmp_path / f"customer-service-{expired:%Y-%m-%d}.jsonl"
    old_path.write_text("{}\n")
    os.utime(old_path, (expired.timestamp(), expired.timestamp()))
    assert writer.prune(now) == 1
    assert not old_path.exists()
    assert log_path.exists()


def test_safe_log_prunes_from_partition_start_even_after_late_writes(tmp_path):
    writer = SafeLogWriter(str(tmp_path))
    request_id = "8a3adfa6-7a43-4b29-8b64-d6b34e695c15"
    writer.write(request_id, "list_products", "", 1, 1, datetime(2026, 10, 1, tzinfo=UTC))
    writer.write(request_id, "list_products", "", 1, 1, datetime(2026, 10, 1, 23, 59, tzinfo=UTC))
    path = tmp_path / "customer-service-2026-10-01.jsonl"
    last = datetime(2026, 10, 1, 23, 59, tzinfo=UTC).timestamp()
    os.utime(path, (last, last))
    assert writer.prune(datetime(2026, 10, 7, 23, 59, tzinfo=UTC)) == 0
    assert writer.prune(datetime(2026, 10, 8, tzinfo=UTC)) == 1
    assert not path.exists()


def test_safe_log_writer_rejects_group_or_world_writable_directory(tmp_path):
    directory = tmp_path / "unsafe-logs"
    directory.mkdir(mode=0o777)
    directory.chmod(0o777)
    writer = SafeLogWriter(str(directory))

    with pytest.raises(PermissionError):
        writer.write("8a3adfa6-7a43-4b29-8b64-d6b34e695c15", "list_products", "", 1, 1, datetime.now(UTC))


def test_safe_log_pruning_rejects_directory_with_changed_permissions(tmp_path):
    directory = tmp_path / 'logs'
    directory.mkdir(mode=0o700)
    writer = SafeLogWriter(str(directory))
    writer.verify()
    directory.chmod(0o755)
    with pytest.raises(PermissionError):
        writer.prune(datetime.now(UTC))


def test_safe_log_writer_rejects_existing_file_with_broad_permissions(tmp_path):
    now = datetime.now(UTC)
    log_path = tmp_path / f'customer-service-{now:%Y-%m-%d}.jsonl'
    log_path.write_text('')
    log_path.chmod(0o644)
    writer = SafeLogWriter(str(tmp_path))
    with pytest.raises(PermissionError):
        writer.write('8a3adfa6-7a43-4b29-8b64-d6b34e695c15', 'list_products', '', 1, 1, now)


def test_safe_log_writer_refuses_symlinks(tmp_path):
    writer = SafeLogWriter(str(tmp_path))
    now = datetime.now(UTC)
    target = tmp_path / "external.jsonl"
    target.write_text("untouched")
    log_path = tmp_path / f"customer-service-{now:%Y-%m-%d}.jsonl"
    log_path.symlink_to(target)

    with pytest.raises(OSError):
        writer.write("8a3adfa6-7a43-4b29-8b64-d6b34e695c15", "list_products", "", 1, 1, now)
    assert target.read_text() == "untouched"
