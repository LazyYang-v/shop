"""Independent maintenance deadlines for the controlled customer-service demo."""

import asyncio
import logging
import time

from shop_api.customer_service import cleanup_rate_limits
from shop_api.customer_service_cancel import expire_due_cancel_operations
from shop_api.customer_service_consultations import cleanup_consultations
from shop_api.customer_service_model_budget import ModelBudget
from shop_api.customer_service_support import cleanup_support


class CustomerServiceMaintenance:
    def __init__(self, session_factory, log_writer, clock, *, monotonic=time.monotonic):
        budget = ModelBudget(session_factory)
        self._monotonic = monotonic
        # Each task owns its deadline; a failed task stays due for the next scan.
        self._tasks = [
            ("logs", 3600, lambda: log_writer.prune(clock())),
            ("consultations", 30, lambda: cleanup_consultations(session_factory, clock())),
            ("cancel_operations", 30, lambda: expire_due_cancel_operations(session_factory, clock())),
            ("model_slots", 30, budget.reap_expired),
            ("model_evidence", 86400, budget.prune_ended),
            ("rate_limits", 3600, lambda: cleanup_rate_limits(session_factory, clock())),
            ("support", 3600, lambda: cleanup_support(session_factory, clock())),
        ]
        self._deadlines = {name: 0.0 for name, _, _ in self._tasks}

    async def run(self):
        async def repeat(task):
            while True:
                await self.run_due(tasks=[task])
                remaining = self._deadlines[task[0]] - self._monotonic()
                await asyncio.sleep(min(30, remaining) if remaining > 0 else 30)

        workers = [asyncio.create_task(repeat(task)) for task in self._tasks]
        try:
            await asyncio.gather(*workers)
        finally:
            for worker in workers:
                worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

    async def run_due(self, *, tasks=None):
        async def run(name, interval, operation):
            if self._monotonic() < self._deadlines[name]:
                return
            try:
                await asyncio.to_thread(operation)
            except Exception as error:
                logging.getLogger(__name__).warning(
                    "customer_service_maintenance_failed task=%s error=%s", name, type(error).__name__)
            else:
                self._deadlines[name] = self._monotonic() + interval

        # A slow database task must not delay file expiry either.
        await asyncio.gather(*(run(*task) for task in (self._tasks if tasks is None else tasks)))
