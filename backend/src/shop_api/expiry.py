import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from threading import Event

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from shop_api.identity import now_utc
from shop_api.orders import Order, close_order


logger = logging.getLogger(__name__)


def expire_orders(
    factory: Callable[[], Session], now: datetime | None = None, stop: Event | None = None,
) -> int:
    if stop is not None and stop.is_set():
        return 0
    current = now if now is not None else now_utc()
    # A finite snapshot prevents skipped locks or changing orders from keeping a
    # scan alive indefinitely. Each candidate is checked again under its lock.
    with factory() as session:
        session.execute(text("SET LOCAL lock_timeout = '5s'"))
        session.execute(text("SET LOCAL statement_timeout = '15s'"))
        candidates = session.scalars(
            select(Order.id)
            .where(Order.status == "pending_payment", Order.expires_at <= current)
            .order_by(Order.expires_at, Order.id)
        ).all()

    closed = 0
    for order_id in candidates:
        if stop is not None and stop.is_set():
            break
        with factory() as session, session.begin():
            session.execute(text("SET LOCAL lock_timeout = '5s'"))
            session.execute(text("SET LOCAL statement_timeout = '15s'"))
            order = session.scalar(
                select(Order)
                .where(
                    Order.id == order_id,
                    Order.status == "pending_payment",
                    Order.expires_at <= current,
                )
                .with_for_update(skip_locked=True)
            )
            if order is None:
                continue
            if order.status != "pending_payment" or order.expires_at > current:
                continue
            close_order(session, order, "payment_timeout", current)
        closed += 1
    return closed


async def expiry_loop(
    factory: Callable[[], Session],
    clock: Callable[[], datetime] = now_utc,
    interval: float = 60,
) -> None:
    while True:
        await asyncio.sleep(interval)
        stop = Event()
        scan = None
        try:
            scan = asyncio.create_task(asyncio.to_thread(expire_orders, factory, clock(), stop))
            await asyncio.shield(scan)
        except asyncio.CancelledError:
            stop.set()
            if scan is not None:
                # Repeated cancellation must not detach the database worker.
                while not scan.done():
                    try:
                        await asyncio.shield(scan)
                    except asyncio.CancelledError:
                        continue
                    except Exception:
                        break
                if not scan.cancelled() and scan.exception() is not None:
                    logger.error("Order expiry scan failed during shutdown", exc_info=scan.exception())
            raise
        except Exception:
            logger.exception("Order expiry scan failed; retrying next interval")
