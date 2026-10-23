"""Durable lifetime paid-budget tests against the isolated PostgreSQL test database.

The guard is accounting only: these tests never call a provider.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
from threading import Barrier

import pytest
from sqlalchemy import text

from test_customer_service_model_budget import budget_context  # noqa: F401 - pytest fixture
from shop_api.customer_service_model_budget import (
    ModelBudget, ModelBudgetDenied, ModelBudgetUnavailable,
)
from shop_api.customer_service_spend_guard import (
    CAP_FEN, MAX_ATTEMPTS, PriceCard, SpendGuard,
)


# Fictional frozen schedule: USD 1 / million input, USD 2 / million output,
# USD 0.5 / million cache hit; conservative fixture FX CNY 8 / USD.
CARD = PriceCard(version='fake-v1', provider='fake', model='fake-model',
                 source='fixture://official-snapshot', approval='fixture-only',
                 currency='USD', input_micros=1_000_000, output_micros=2_000_000,
                 cache_hit_micros=500_000, fx_numerator=8, fx_denominator=1)
OTHER_CARD = PriceCard(**{**CARD.__dict__, 'version': 'fake-v2'})


@pytest.fixture(autouse=True)
def isolated_paid_budget(budget_context):
    factory = budget_context[0]
    with factory() as db:
        snapshot = db.execute(text("SELECT * FROM customer_service_paid_budget WHERE id=1")).mappings().one()
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


def token_reservation(budget_context, index=0):
    factory, ids, clock = budget_context
    return ModelBudget(factory, clock=lambda: clock[0]).reserve(ids[index], input_tokens=12000)


def set_guard(factory, **values):
    assignments = ", ".join(f"{name}=:{name}" for name in values)
    with factory.begin() as db:
        db.execute(text(f"UPDATE customer_service_paid_budget SET {assignments} WHERE id=1"), values)


def test_missing_price_is_closed_and_frozen_price_reserves_before_attempt(budget_context):
    factory = budget_context[0]
    token = token_reservation(budget_context)
    guard = SpendGuard(factory, clock=lambda: budget_context[2][0])
    with pytest.raises(ModelBudgetUnavailable):
        guard.reserve(token.id, session_id=budget_context[1][0], price_card=None)
    reservation = guard.reserve(token.id, session_id=budget_context[1][0], price_card=CARD)
    assert reservation.reserved_fen == 12
    assert guard.status().attempts == 1
    assert guard.status().charged_fen == 12


def test_price_card_is_frozen_after_first_reservation(budget_context):
    factory, ids, clock = budget_context
    guard = SpendGuard(factory, clock=lambda: clock[0])
    first = token_reservation(budget_context, 0)
    second = token_reservation(budget_context, 1)
    guard.reserve(first.id, session_id=ids[0], price_card=CARD)
    with pytest.raises(ModelBudgetDenied):
        guard.reserve(second.id, session_id=ids[1], price_card=OTHER_CARD)
    assert guard.status().attempts == 1
    assert guard.status().charged_fen == 12


def test_attempt_cap_stops_permanently(budget_context):
    factory, ids, clock = budget_context
    guard = SpendGuard(factory, clock=lambda: clock[0])
    first = token_reservation(budget_context, 0)
    second = token_reservation(budget_context, 1)
    set_guard(factory, attempts_committed=MAX_ATTEMPTS - 1)
    guard.reserve(first.id, session_id=ids[0], price_card=CARD)
    assert guard.status().attempts == MAX_ATTEMPTS
    with pytest.raises(ModelBudgetDenied):
        guard.reserve(second.id, session_id=ids[1], price_card=CARD)
    status = guard.status()
    assert status.state == "stopped"
    assert status.stopped_reason == "attempt_cap"
    # A previously committed permit can still be dispatched; no reopening occurs.
    assert guard.claim_dispatch(first.id, session_id=ids[0]) is True


def test_spend_cap_stops_before_exceeding_twenty_yuan(budget_context):
    factory, ids, clock = budget_context
    guard = SpendGuard(factory, clock=lambda: clock[0])
    token = token_reservation(budget_context)
    set_guard(factory, charged_fen=CAP_FEN - 5)
    with pytest.raises(ModelBudgetDenied):
        guard.reserve(token.id, session_id=ids[0], price_card=CARD)
    status = guard.status()
    assert status.state == "stopped"
    assert status.stopped_reason == "spend_cap"
    assert status.charged_fen == CAP_FEN - 5


def test_concurrent_reservations_never_exceed_attempt_cap(budget_context):
    factory, ids, clock = budget_context
    guard = SpendGuard(factory, clock=lambda: clock[0])
    first = token_reservation(budget_context, 0)
    second = token_reservation(budget_context, 1)
    set_guard(factory, attempts_committed=MAX_ATTEMPTS - 1)
    barrier = Barrier(2)

    def attempt(reservation, session_id):
        barrier.wait()
        try:
            guard.reserve(reservation.id, session_id=session_id, price_card=CARD)
            return True
        except ModelBudgetDenied:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda pair: attempt(*pair), ((first, ids[0]), (second, ids[1]))))
    assert sorted(outcomes) == [False, True]
    status = guard.status()
    assert status.attempts == MAX_ATTEMPTS
    assert status.state == "stopped"


def test_guard_state_persists_across_instances(budget_context):
    factory, ids, clock = budget_context
    token = token_reservation(budget_context)
    SpendGuard(factory, clock=lambda: clock[0]).reserve(token.id, session_id=ids[0], price_card=CARD)
    restarted = SpendGuard(factory, clock=lambda: clock[0])
    assert restarted.status().attempts == 1
    assert restarted.status().charged_fen == 12
    assert restarted.status().state == "armed"


def test_ambiguous_outcome_retains_full_charge(budget_context):
    factory, ids, clock = budget_context
    guard = SpendGuard(factory, clock=lambda: clock[0])
    token = token_reservation(budget_context)
    guard.reserve(token.id, session_id=ids[0], price_card=CARD)
    clock[0] = clock[0] + timedelta(seconds=91)
    assert guard.settle(token.id, session_id=ids[0], input_tokens=100, output_tokens=20) == 12
    assert guard.status().charged_fen == 12


def test_valid_usage_refunds_unused_money_and_is_idempotent(budget_context):
    factory, ids, clock = budget_context
    guard = SpendGuard(factory, clock=lambda: clock[0])
    token = token_reservation(budget_context)
    guard.reserve(token.id, session_id=ids[0], price_card=CARD)
    assert guard.settle(token.id, session_id=ids[0], input_tokens=100, output_tokens=20) == 1
    assert guard.status().charged_fen == 1
    assert guard.settle(token.id, session_id=ids[0], input_tokens=1, output_tokens=1) == 1
    assert guard.status().charged_fen == 1


def test_over_bound_usage_latches_and_keeps_full_charge(budget_context):
    factory, ids, clock = budget_context
    guard = SpendGuard(factory, clock=lambda: clock[0])
    token = token_reservation(budget_context)
    guard.reserve(token.id, session_id=ids[0], price_card=CARD)
    with pytest.raises(ModelBudgetUnavailable):
        guard.settle(token.id, session_id=ids[0], input_tokens=12001, output_tokens=1)
    status = guard.status()
    assert status.state == "blocked"
    assert status.charged_fen == 12


def test_claim_dispatch_is_one_shot(budget_context):
    factory, ids, clock = budget_context
    guard = SpendGuard(factory, clock=lambda: clock[0])
    token = token_reservation(budget_context)
    guard.reserve(token.id, session_id=ids[0], price_card=CARD)
    assert guard.claim_dispatch(token.id, session_id=ids[0]) is True
    assert guard.claim_dispatch(token.id, session_id=ids[0]) is False


def test_exact_rounding_rounds_up():
    tiny = PriceCard(version='tiny', provider='fake', model='fake-model',
                     source='fixture://rounding', approval='fixture-only',
                     currency='USD', input_micros=1, output_micros=0,
                     cache_hit_micros=0, fx_numerator=1, fx_denominator=1)
    assert tiny.cost_fen(1, 0) == 1
    assert CARD.cost_fen(12000, 1500) == 12
