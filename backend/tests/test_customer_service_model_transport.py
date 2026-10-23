from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4
import json

import pytest
from sqlalchemy import text

from shop_api.customer_service import CustomerServiceUnavailable
from shop_api.customer_service_model import ModelProductFacts
from shop_api.customer_service_model_budget import ModelBudget, ModelBudgetDenied, Completion
from shop_api.customer_service_model_transport import CompletionTransport
from shop_api.customer_service_model_turn import ModelTurn
from shop_api.customer_service_spend_guard import PriceCard, SpendGuard
from test_customer_service_model_budget import budget_context


CARD = PriceCard(version='fake-v1', provider='fake', model='fake-model',
                 source='fixture://official-snapshot', approval='fixture-only',
                 currency='USD', input_micros=1_000_000, output_micros=2_000_000,
                 cache_hit_micros=500_000, fx_numerator=8, fx_denominator=1)


@pytest.fixture
def paid_budget_reset(budget_context):
    factory = budget_context[0]
    with factory() as db:
        snapshot = db.execute(text("SELECT * FROM customer_service_paid_budget WHERE id=1")).mappings().one()
    with factory.begin() as db:
        db.execute(text("""UPDATE customer_service_paid_budget SET state='disabled',
            attempts_committed=0, charged_fen=0, price_card_sha256=NULL, price_card=NULL,
            stopped_reason=NULL, armed_at=NULL, stopped_at=NULL WHERE id=1"""))
    yield
    with factory.begin() as db:
        db.execute(text("""UPDATE customer_service_paid_budget SET
            state=:state, attempts_committed=:attempts, charged_fen=:charged,
            price_card_sha256=:digest, price_card=CAST(:card AS jsonb),
            stopped_reason=:reason, armed_at=:armed, stopped_at=:stopped WHERE id=1"""),
            {"state": snapshot["state"], "attempts": snapshot["attempts_committed"],
             "charged": snapshot["charged_fen"], "digest": snapshot["price_card_sha256"],
             "card": None if snapshot["price_card"] is None else
             json.dumps(snapshot["price_card"], sort_keys=True, separators=(",", ":")),
             "reason": snapshot["stopped_reason"], "armed": snapshot["armed_at"],
             "stopped": snapshot["stopped_at"]})


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


def test_real_provider_exchange_requires_paid_controls():
    with pytest.raises(ValueError):
        CompletionTransport(Mock(), exchange=CompletionTransport._https_exchange)
    with pytest.raises(ValueError):
        CompletionTransport(Mock(), exchange=lambda *args: completion(), spend_guard=Mock())
    with pytest.raises(ValueError):
        CompletionTransport(Mock(), exchange=lambda *args: completion(), price_card=CARD)
    with pytest.raises(ValueError):
        CompletionTransport(Mock(), exchange=CompletionTransport._https_exchange,
                            spend_guard=Mock(), price_card=CARD, provider_token='token')


def test_paid_transport_reserves_before_send_claims_once_and_settles(budget_context, paid_budget_reset):
    factory, ids, clock = budget_context
    budget = ModelBudget(factory, clock=lambda: clock[0])
    guard = SpendGuard(factory, clock=lambda: clock[0])
    observed = []

    def exchange(payload, token, timeout):
        status = guard.status()
        observed.append((token, status.attempts, status.charged_fen))
        return completion()

    transport = CompletionTransport(budget, exchange=exchange, spend_guard=guard,
                                    price_card=CARD, provider_token='synthetic-credential')
    turn = LocalTurn(budget, ids[0])
    try:
        result = transport.execute(turn, None, token='')
    finally:
        transport.close()
    assert result['choices'][0]['finish_reason'] == 'stop'
    # 100 input + 1500 output allowance was reserved before the exchange ran.
    assert observed == [('synthetic-credential', 1, 3)]
    status = guard.status()
    assert (status.attempts, status.charged_fen) == (1, 1)
    with factory() as db:
        row = db.execute(text('''SELECT dispatch_claimed_at, paid_reserved_fen, paid_charged_fen
            FROM customer_service_model_reservations WHERE id=:id'''), {'id': turn.reservation.id}).one()
    assert row.dispatch_claimed_at is not None
    assert (row.paid_reserved_fen, row.paid_charged_fen) == (3, 1)


def test_paid_transport_retains_full_charge_when_exchange_fails(budget_context, paid_budget_reset):
    factory, ids, clock = budget_context
    budget = ModelBudget(factory, clock=lambda: clock[0])
    guard = SpendGuard(factory, clock=lambda: clock[0])

    def disconnected(*args):
        raise OSError('synthetic-test-secret')

    transport = CompletionTransport(budget, exchange=disconnected, spend_guard=guard,
                                    price_card=CARD, provider_token='synthetic-credential')
    try:
        with pytest.raises(CustomerServiceUnavailable) as error:
            transport.execute(LocalTurn(budget, ids[0]), None, token='')
        assert 'synthetic-test-secret' not in str(error.value)
    finally:
        transport.close()
    status = guard.status()
    assert (status.attempts, status.charged_fen) == (1, 3)


def test_paid_transport_never_sends_without_claim(budget_context, paid_budget_reset, monkeypatch):
    factory, ids, clock = budget_context
    budget = ModelBudget(factory, clock=lambda: clock[0])
    guard = SpendGuard(factory, clock=lambda: clock[0])
    monkeypatch.setattr(guard, 'claim_dispatch', lambda *args, **kwargs: False)
    exchange = Mock(return_value=completion())
    transport = CompletionTransport(budget, exchange=exchange, spend_guard=guard,
                                    price_card=CARD, provider_token='synthetic-credential')
    try:
        with pytest.raises(CustomerServiceUnavailable):
            transport.execute(LocalTurn(budget, ids[0]), None, token='')
    finally:
        transport.close()
    exchange.assert_not_called()
    status = guard.status()
    assert (status.attempts, status.charged_fen) == (1, 3)


def test_paid_transport_does_not_refund_rejected_usage(budget_context, paid_budget_reset):
    factory, ids, clock = budget_context
    budget = ModelBudget(factory, clock=lambda: clock[0])
    guard = SpendGuard(factory, clock=lambda: clock[0])
    oversized = completion()
    oversized['usage'] = {'prompt_tokens': 100, 'completion_tokens': 1501}
    transport = CompletionTransport(budget, exchange=lambda *args: oversized, spend_guard=guard,
                                    price_card=CARD, provider_token='synthetic-credential')
    try:
        with pytest.raises(CustomerServiceUnavailable):
            transport.execute(LocalTurn(budget, ids[0]), None, token='')
    finally:
        transport.close()
    status = guard.status()
    assert (status.attempts, status.charged_fen) == (1, 3)
