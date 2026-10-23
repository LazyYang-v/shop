"""Bounded non-streaming completion transport; application enablement stays closed."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
import json
import time
from threading import BoundedSemaphore, Event
from urllib.request import Request, build_opener, HTTPRedirectHandler

from shop_api.customer_service import CustomerServiceUnavailable
from shop_api.customer_service_model_budget import Completion, ProviderUsage


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class CompletionTransport:
    """One background owner per admitted request, without retries.

    Local worker admission fails fast before reserving budget; there is no waiting
    queue behind occupied exchanges. Caller timeout cancels work that has not started,
    but Python cannot stop a running exchange: it occupies its worker until it returns,
    even after the independent 90-second ledger TTL. Uncertain remote requests retain
    their durable reservation until TTL; this transport never retries them.
    """

    def __init__(self, budget, *, exchange=None):
        self._budget = budget
        # Injection is for local tests. The production exchange has a fixed origin.
        self._exchange = exchange
        self._workers = ThreadPoolExecutor(max_workers=2)
        self._capacity = BoundedSemaphore(2)

    @staticmethod
    def _https_exchange(payload, token, timeout):
        request = Request('https://api.deepseek.com/chat/completions',
                          data=json.dumps(payload, separators=(',', ':')).encode(),
                          headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token}, method='POST')
        with build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise CustomerServiceUnavailable
            return json.loads(raw)

    def execute(self, turn, facts, *, token):
        # Estimated admission is allowed only with an explicitly injected offline
        # exchange. Real provider spending has not been authorized.
        if self._exchange is None:
            raise CustomerServiceUnavailable('真实提供方调用尚未授权')
        if not self._capacity.acquire(blocking=False):
            raise CustomerServiceUnavailable
        cancelled = Event()
        try:
            payload, reservation, timeout = turn.prepare(facts)
            deadline = time.monotonic() + timeout
            future = self._workers.submit(self._complete, reservation, payload, token, deadline, cancelled)
        except Exception:
            self._capacity.release()
            raise
        # A running exchange owns capacity until it actually returns. Cancellation
        # releases capacity only if the executor proves the task never started.
        future.add_done_callback(lambda _future: self._capacity.release())
        try:
            result = future.result(timeout=max(0, deadline - time.monotonic()))
            if time.monotonic() >= deadline:
                raise TimeoutError
            return result
        except TimeoutError:
            cancelled.set()
            future.cancel()
            turn.mark_timeout(reservation)
            raise CustomerServiceUnavailable from None
        except Exception:
            raise CustomerServiceUnavailable from None

    def _complete(self, reservation, payload, token, deadline, cancelled):
        remaining = deadline - time.monotonic()
        if cancelled.is_set() or remaining <= 0:
            raise CustomerServiceUnavailable
        response = self._exchange(payload, token, remaining)
        if not isinstance(response, dict) or response.get('object') != 'chat.completion':
            raise CustomerServiceUnavailable
        choices = response.get('choices')
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise CustomerServiceUnavailable
        if choices[0].get('finish_reason') not in {'stop', 'length', 'tool_calls', 'content_filter', 'insufficient_system_resource'}:
            raise CustomerServiceUnavailable
        usage = response.get('usage', {})
        if not isinstance(usage, dict):
            usage = {}
        counts = ProviderUsage(usage.get('prompt_tokens'), usage.get('completion_tokens'))
        self._budget.settle_confirmed_end(reservation.session_id, reservation.id,
                                         completion=Completion.SUCCESS, usage=counts)
        # Truncated/filtered/tool output is not a verified product answer.
        if (choices[0]['finish_reason'] not in {'stop', 'tool_calls'}
                or type(counts.input_tokens) is not int or type(counts.output_tokens) is not int
                or counts.input_tokens < 0 or counts.input_tokens > reservation.reserved_tokens - 1500
                or counts.output_tokens < 0 or counts.output_tokens > 1500):
            raise CustomerServiceUnavailable
        return response

    def close(self):
        self._workers.shutdown(wait=True, cancel_futures=False)
