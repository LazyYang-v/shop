from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from shop_api.customer_service import CustomerServiceUnavailable
from shop_api.customer_service_model import ModelProductFacts
from shop_api.customer_service_model_budget import ModelBudget, ModelBudgetDenied, Completion
from shop_api.customer_service_model_transport import CompletionTransport
from shop_api.customer_service_model_turn import ModelTurn
from test_customer_service_model_budget import budget_context


class LocalTurn:
    """Explicit test-only admission; production ModelTurn.prepare remains closed."""
    def __init__(self, budget, session_id, timeout=1):
        self.budget, self.session_id, self.timeout = budget, session_id, timeout
        self.reservation = None

    def prepare(self, facts):
        self.reservation = self.budget.reserve(self.session_id, input_tokens=100)
        return {'stream': False}, self.reservation, self.timeout

    def mark_timeout(self, reservation):
        self.budget.mark_caller_timeout(self.session_id, reservation.id)


def completion(reason='stop'):
    return {'object': 'chat.completion', 'choices': [{'finish_reason': reason, 'message': {'content': '{}'}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 10}}


def test_busy_workers_reject_before_reserving_even_after_ledger_ttl():
    # A permissive fake ledger represents slots reaped after 90 seconds, while
    # the original exchanges still own both local worker threads.
    budget = Mock()
    budget.reserve.side_effect = lambda *args, **kwargs: SimpleNamespace(
        id=uuid4(), session_id=uuid4(), reserved_tokens=1600)
    release = Event()
    entered = [Event(), Event()]
    calls = []

    def exchange(*args):
        index = len(calls)
        calls.append(args)
        entered[index].set()
        assert release.wait(5)
        return completion()

    transport = CompletionTransport(budget, exchange=exchange)
    try:
        for index in range(2):
            with pytest.raises(CustomerServiceUnavailable):
                transport.execute(LocalTurn(budget, uuid4(), timeout=0.02), None, token='synthetic')
            assert entered[index].wait(1)
        for _ in range(5):
            with pytest.raises(CustomerServiceUnavailable):
                transport.execute(LocalTurn(budget, uuid4(), timeout=0.02), None, token='synthetic')
        assert budget.reserve.call_count == 2
        assert len(calls) == 2
    finally:
        release.set()
        transport.close()
    # Releasing the old workers must not start any timed-out replacement.
    assert len(calls) == 2


def test_execute_cancels_not_started_work_at_caller_deadline(monkeypatch):
    from concurrent.futures import Future
    budget = Mock()
    budget.reserve.return_value = SimpleNamespace(id=uuid4(), session_id=uuid4(), reserved_tokens=1600)
    exchange = Mock(return_value=completion())
    transport = CompletionTransport(budget, exchange=exchange)
    pending = Future()
    monkeypatch.setattr(transport._workers, 'submit', lambda *args: pending)
    try:
        with pytest.raises(CustomerServiceUnavailable):
            transport.execute(LocalTurn(budget, uuid4(), timeout=0.01), None, token='synthetic')
        assert pending.cancelled()
        exchange.assert_not_called()
        budget.mark_caller_timeout.assert_called_once()
    finally:
        transport.close()


def test_execute_does_not_start_exchange_after_scheduling_deadline(monkeypatch):
    import shop_api.customer_service_model_transport as module
    from concurrent.futures import Future
    budget = Mock()
    budget.reserve.return_value = SimpleNamespace(id=uuid4(), session_id=uuid4(), reserved_tokens=1600)
    exchange = Mock(return_value=completion())
    transport = CompletionTransport(budget, exchange=exchange)
    clock = [0.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])

    def delayed_start(function, *args):
        # Deterministically simulate scheduler delay past the request deadline.
        clock[0] = 2.0
        future = Future()
        try:
            future.set_result(function(*args))
        except Exception as error:
            future.set_exception(error)
        return future

    monkeypatch.setattr(transport._workers, 'submit', delayed_start)
    try:
        with pytest.raises(CustomerServiceUnavailable):
            transport.execute(LocalTurn(budget, uuid4(), timeout=1), None, token='synthetic')
        exchange.assert_not_called()
    finally:
        transport.close()


def test_real_gate_prevents_paid_transport(budget_context):
    factory, ids, clock = budget_context
    budget = ModelBudget(factory, clock=lambda: clock[0])
    transport = CompletionTransport(budget)
    try:
        with pytest.raises(CustomerServiceUnavailable):
            transport.execute(ModelTurn(budget, ids[0]), ModelProductFacts({}), token='synthetic-test-secret')
    finally:
        transport.close()


def test_estimated_model_turn_runs_end_to_end_with_synthetic_exchange(budget_context):
    from shop_api.customer_service import ProductFixture
    factory, ids, clock = budget_context
    budget = ModelBudget(factory, clock=lambda: clock[0])
    product_id = '00000000-0000-0000-0000-000000000001'
    facts = ModelProductFacts.from_fixture({product_id: ProductFixture(product_id, 'demo', 'demo', '129.00', 24, True)})
    captured = []
    def exchange(payload, token, timeout):
        captured.append(payload)
        return completion()
    transport = CompletionTransport(budget, exchange=exchange)
    try:
        assert transport.execute(ModelTurn(budget, ids[0]), facts, token='synthetic') == completion()
        assert len(captured) == 1
        assert captured[0]['max_tokens'] == 1500
    finally:
        transport.close()


def test_completion_releases_slot_after_valid_terminal_response(budget_context):
    factory, ids, clock = budget_context
    budget = ModelBudget(factory, clock=lambda: clock[0])
    transport = CompletionTransport(budget, exchange=lambda *args: completion())
    try:
        turn = LocalTurn(budget, ids[0])
        assert transport.execute(turn, None, token='synthetic-test-secret')['object'] == 'chat.completion'
        assert budget.settle_confirmed_end(ids[0], turn.reservation.id, completion=Completion.FAILURE) == 110
    finally:
        transport.close()


def test_timeout_retains_slot_until_background_response_finishes(budget_context):
    factory, ids, clock = budget_context
    budget = ModelBudget(factory, clock=lambda: clock[0])
    release = Event()
    def slow(*args):
        assert release.wait(timeout=5)
        return completion()
    transport = CompletionTransport(budget, exchange=slow)
    turn = LocalTurn(budget, ids[0], timeout=0.02)
    try:
        with pytest.raises(CustomerServiceUnavailable):
            transport.execute(turn, None, token='synthetic-test-secret')
        other = budget.reserve(ids[1], input_tokens=10)
        with pytest.raises(ModelBudgetDenied):
            budget.reserve(ids[2], input_tokens=10)
        release.set()
        transport.close()
        assert budget.settle_confirmed_end(ids[0], turn.reservation.id, completion=Completion.FAILURE) == 1600
        budget.settle_confirmed_end(ids[1], other.id, completion=Completion.FAILURE)
    finally:
        release.set()
        transport.close()


def test_connection_loss_does_not_release_slot_or_leak_secret(budget_context):
    factory, ids, clock = budget_context
    budget = ModelBudget(factory, clock=lambda: clock[0])
    def disconnected(*args):
        raise OSError('synthetic-test-secret')
    transport = CompletionTransport(budget, exchange=disconnected)
    turn = LocalTurn(budget, ids[0])
    try:
        with pytest.raises(CustomerServiceUnavailable) as error:
            transport.execute(turn, None, token='synthetic-test-secret')
        assert 'synthetic-test-secret' not in str(error.value)
        budget.reserve(ids[1], input_tokens=10)
        with pytest.raises(ModelBudgetDenied):
            budget.reserve(ids[2], input_tokens=10)
    finally:
        transport.close()


@pytest.mark.parametrize('response', [{}, {'object': 'chat.completion', 'choices': []}])
def test_incomplete_response_never_proves_remote_end(budget_context, response):
    factory, ids, clock = budget_context
    budget = ModelBudget(factory, clock=lambda: clock[0])
    transport = CompletionTransport(budget, exchange=lambda *args: response)
    turn = LocalTurn(budget, ids[0])
    try:
        with pytest.raises(CustomerServiceUnavailable):
            transport.execute(turn, None, token='synthetic-test-secret')
        other = budget.reserve(ids[1], input_tokens=10)
        with pytest.raises(ModelBudgetDenied):
            budget.reserve(ids[2], input_tokens=10)
        # Test fixture teardown owns cleanup of synthetic outstanding reservations.
    finally:
        transport.close()
