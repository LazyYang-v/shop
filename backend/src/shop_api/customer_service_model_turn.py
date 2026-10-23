"""Request scheduling limits, independent of transport and tokenizer availability."""

import time

from shop_api.customer_service import CustomerServiceUnavailable
from shop_api.customer_service_model_budget import ModelBudget


class ModelTurn:
    """At most four admissions in 45 seconds; a provider attempt gets at most 20s.

    Each instance belongs to one server-owned turn. Callers must retain the same
    instance throughout that turn. Reservations persist until completion or TTL.
    This primitive grants no permission to send and has no retry loop.
    """

    def __init__(self, budget: ModelBudget, session_id, *, deadline=None):
        self._budget = budget
        self._session_id = session_id
        self._deadline = deadline if deadline is not None else time.monotonic() + 45.0
        self._attempts = 0

    def prepare(self, facts):
        """Check the input estimate before touching shared quota.

        Estimated mode reserves the full input allowance independently of the
        admission score. Real transport authorization remains a separate gate.
        """
        from shop_api.customer_service_model import prepare_model_request, measured_input_tokens
        request = facts if isinstance(facts, dict) else prepare_model_request(facts)
        count = measured_input_tokens(request)
        reservation, timeout = self.reserve(measured_input_tokens=count, metering_mode='estimated')
        return request, reservation, timeout

    def reserve(self, *, measured_input_tokens: int, metering_mode='verified'):
        if self._attempts >= 4 or time.monotonic() >= self._deadline:
            raise CustomerServiceUnavailable
        self._attempts += 1
        reservation = self._budget.reserve(self._session_id, input_tokens=measured_input_tokens, metering_mode=metering_mode)
        remaining = min(20.0, self._deadline - time.monotonic())
        if remaining <= 0:
            # Conservatively retain charge and slot. Scheduling expiry is not
            # proof that an independently owned dependency has ended.
            self._budget.mark_caller_timeout(self._session_id, reservation.id)
            raise CustomerServiceUnavailable
        return reservation, remaining

    def mark_timeout(self, reservation):
        self._budget.mark_caller_timeout(self._session_id, reservation.id)
