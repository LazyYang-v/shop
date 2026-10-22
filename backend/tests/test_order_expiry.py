import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, select, text

from shop_api.expiry import expire_orders, expiry_loop
from shop_api.orders import Order
from shop_api.identity import now_utc
from test_order_payment_api import buyer, make_order


PRODUCT_URL = "/api/products/00000000-0000-0000-0000-000000000001"


def test_expiry_closes_order_and_restores_stock_only_once(client):
    token = buyer(client, f"checkout-expiry-{uuid4().hex}@example.com")
    order_id = make_order(client, token)
    assert client.get(PRODUCT_URL).json()["stock"] == 23
    current = now_utc() + timedelta(minutes=31)

    assert expire_orders(client.app.state.session_factory, current) == 1

    response = client.get(f"/api/orders/{order_id}")
    assert response.status_code == 200
    order = response.json()
    assert order["status"] == "closed"
    assert order["close_reason"] == "payment_timeout"
    assert datetime.fromisoformat(order["closed_at"]) == current
    assert client.get(PRODUCT_URL).json()["stock"] == 24
    assert expire_orders(client.app.state.session_factory, current) == 0
    assert client.get(PRODUCT_URL).json()["stock"] == 24


@pytest.mark.parametrize("paid", [False, True], ids=["not_due", "paid"])
def test_expiry_preserves_orders_that_cannot_be_closed(client, paid):
    token = buyer(client, f"checkout-expiry-preserved-{uuid4().hex}@example.com")
    order_id = make_order(client, token)
    if paid:
        response = client.post(
            f"/api/orders/{order_id}/pay",
            headers={"X-CSRF-Token": token, "Origin": "http://testserver"},
        )
        assert response.status_code == 200
    current = now_utc() + timedelta(minutes=31) if paid else now_utc()

    assert expire_orders(client.app.state.session_factory, current) == 0

    order = client.get(f"/api/orders/{order_id}").json()
    assert order["status"] == ("pending_shipment" if paid else "pending_payment")
    assert order["closed_at"] is None
    assert order["close_reason"] is None
    assert client.get(PRODUCT_URL).json()["stock"] == 23


def test_expiry_closes_at_the_exact_payment_deadline(client):
    token = buyer(client, f"checkout-expiry-deadline-{uuid4().hex}@example.com")
    order_id = make_order(client, token)
    deadline = datetime.fromisoformat(client.get(f"/api/orders/{order_id}").json()["expires_at"])

    assert expire_orders(client.app.state.session_factory, deadline - timedelta(microseconds=1)) == 0
    assert expire_orders(client.app.state.session_factory, deadline) == 1

    assert client.get(f"/api/orders/{order_id}").json()["status"] == "closed"
    assert client.get(PRODUCT_URL).json()["stock"] == 24


def test_expiry_skips_locked_order_and_retries_next_scan(client):
    token = buyer(client, f"checkout-expiry-locked-{uuid4().hex}@example.com")
    order_id = make_order(client, token)
    factory = client.app.state.session_factory
    current = now_utc() + timedelta(minutes=31)

    with factory() as locking_session, ThreadPoolExecutor(max_workers=1) as executor:
        locking_session.scalar(select(Order).where(Order.id == UUID(order_id)).with_for_update())
        scan = executor.submit(expire_orders, factory, current)
        try:
            assert scan.result(timeout=5) == 0
        finally:
            locking_session.rollback()

    assert client.get(f"/api/orders/{order_id}").json()["status"] == "pending_payment"
    assert client.get(PRODUCT_URL).json()["stock"] == 23
    assert expire_orders(factory, current) == 1
    assert client.get(f"/api/orders/{order_id}").json()["status"] == "closed"
    assert client.get(PRODUCT_URL).json()["stock"] == 24


def test_failed_expiry_rolls_back_and_can_be_retried(client):
    token = buyer(client, f"checkout-expiry-retry-{uuid4().hex}@example.com")
    order_id = make_order(client, token)
    factory = client.app.state.session_factory
    current = now_utc() + timedelta(minutes=31)

    def fail_after_flush(session, context):
        raise RuntimeError("temporary database failure")

    def failing_factory():
        session = factory()
        event.listen(session, "after_flush", fail_after_flush)
        return session

    with pytest.raises(RuntimeError, match="temporary database failure"):
        expire_orders(failing_factory, current)

    assert client.get(f"/api/orders/{order_id}").json()["status"] == "pending_payment"
    assert client.get(PRODUCT_URL).json()["stock"] == 23
    assert expire_orders(factory, current) == 1
    assert client.get(f"/api/orders/{order_id}").json()["status"] == "closed"
    assert client.get(PRODUCT_URL).json()["stock"] == 24


def test_periodic_expiry_recovers_from_failure_off_thread_and_can_be_cancelled(client, caplog):
    token = buyer(client, f"checkout-expiry-loop-{uuid4().hex}@example.com")
    order_id = make_order(client, token)
    factory = client.app.state.session_factory
    current = now_utc() + timedelta(minutes=31)
    worker_threads = []

    async def run_loop():
        loop = asyncio.get_running_loop()
        committed = asyncio.Event()
        first_attempt = True
        caller_thread = threading.get_ident()

        def retrying_factory():
            nonlocal first_attempt
            worker_threads.append(threading.get_ident())
            if first_attempt:
                first_attempt = False
                raise RuntimeError("temporary scanner failure")
            session = factory()
            event.listen(session, "after_commit", lambda session: loop.call_soon_threadsafe(committed.set))
            return session

        task = asyncio.create_task(expiry_loop(retrying_factory, lambda: current, interval=0.01))
        try:
            await asyncio.wait_for(committed.wait(), timeout=5)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert worker_threads
        assert all(worker != caller_thread for worker in worker_threads)

    asyncio.run(run_loop())

    assert "temporary scanner failure" in caplog.text
    assert client.get(f"/api/orders/{order_id}").json()["status"] == "closed"
    assert client.get(PRODUCT_URL).json()["stock"] == 24


def test_expiry_stop_between_orders_leaves_remaining_orders_for_retry(client):
    token = buyer(client, f"checkout-expiry-stop-{uuid4().hex}@example.com")
    first_id = make_order(client, token)
    second_id = make_order(client, token)
    factory = client.app.state.session_factory
    stop = threading.Event()
    current = now_utc() + timedelta(minutes=31)

    def stopping_factory():
        session = factory()
        event.listen(session, "after_commit", lambda session: stop.set())
        return session

    assert expire_orders(stopping_factory, current, stop=stop) == 1
    statuses = [client.get(f"/api/orders/{order_id}").json()["status"] for order_id in (first_id, second_id)]
    assert sorted(statuses) == ["closed", "pending_payment"]
    assert client.get(PRODUCT_URL).json()["stock"] == 23
    assert expire_orders(factory, current) == 1
    assert client.get(PRODUCT_URL).json()["stock"] == 24


def test_periodic_cancellation_waits_for_active_scan_to_exit(client):
    factory = client.app.state.session_factory
    release = threading.Event()
    exited = threading.Event()

    async def cancel_active_scan():
        loop = asyncio.get_running_loop()
        entered = asyncio.Event()

        def blocked_factory():
            loop.call_soon_threadsafe(entered.set)
            try:
                if not release.wait(timeout=5):
                    raise TimeoutError("test did not release scanner")
                return factory()
            finally:
                exited.set()

        task = asyncio.create_task(expiry_loop(blocked_factory, now_utc, interval=0.01))
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            task.cancel()
            await asyncio.sleep(0.01)
            assert not task.done()
        finally:
            release.set()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert exited.is_set()

    asyncio.run(cancel_active_scan())


def test_expiry_transactions_bound_database_waits(client):
    token = buyer(client, f"checkout-expiry-timeouts-{uuid4().hex}@example.com")
    make_order(client, token)
    factory = client.app.state.session_factory
    settings = []

    def record_settings(session, context, instances):
        settings.append(tuple(session.execute(text("SELECT current_setting('lock_timeout'), current_setting('statement_timeout')")).one()))

    def observing_factory():
        session = factory()
        event.listen(session, "before_flush", record_settings)
        return session

    assert expire_orders(observing_factory, now_utc() + timedelta(minutes=31)) == 1
    assert settings == [("5s", "15s")]
