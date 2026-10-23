"""Real PostgreSQL accounting tests; run only against isolated shop_test."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from shop_api.customer_service_model_budget import (
    Completion, ModelBudget, ModelBudgetDenied, ModelBudgetUnavailable,
    ModelReservationNotFound, ProviderUsage,
)
from shop_api.identity import AuthSession, Role, User


@pytest.fixture
def budget_context(client):
    factory = client.app.state.session_factory
    now = datetime.now(UTC)
    session_ids = [uuid4() for _ in range(4)]
    user_id = uuid4()
    # The deployment scope is shared by all instances: save and restore it so this
    # fixture cannot erase unrelated accounting. These tests must run serially.
    with factory.begin() as db:
        assert db.scalar(text("SELECT current_database()")) == "shop_test"
        assert db.scalar(text("SELECT count(*) FROM customer_service_model_reservations WHERE ended_at IS NULL")) == 0
        blocked = db.scalar(text("SELECT metering_blocked FROM customer_service_model_guard WHERE id=1"))
        assert blocked is False
        db.add(User(id=user_id, email=f"budget-{user_id}@example.com", password_hash="unused-test-hash",
                    role=Role.BUYER.value, is_active=True, created_at=now))
        db.flush()
        for session_id in session_ids:
            db.add(AuthSession(id=session_id, user_id=user_id, token_hash=uuid4().bytes + uuid4().bytes,
                               csrf_hash=uuid4().bytes + uuid4().bytes, kind="authenticated",
                               created_at=now, expires_at=now + timedelta(days=7)))
        deployment_days = dict(db.execute(text("SELECT day, tokens FROM customer_service_model_days WHERE scope='deployment'")).all())
    clock = [now]
    yield factory, session_ids, clock
    with factory.begin() as db:
        db.execute(text("DELETE FROM customer_service_model_reservations WHERE session_id=ANY(:ids)"), {"ids": session_ids})
        for session_id in session_ids:
            db.execute(text("DELETE FROM customer_service_model_days WHERE scope=:scope"), {"scope": str(session_id)})
        db.execute(text("DELETE FROM customer_service_model_days WHERE scope='deployment'"))
        for day, tokens in deployment_days.items():
            db.execute(text("INSERT INTO customer_service_model_days VALUES ('deployment', :day, :tokens)"), {"day": day, "tokens": tokens})
        db.execute(text("UPDATE customer_service_model_guard SET metering_blocked=false WHERE id=1"))
        db.execute(text("DELETE FROM users WHERE id=:id"), {"id": user_id})


def ledger(factory, scope, day):
    with factory() as db:
        return db.scalar(text("SELECT tokens FROM customer_service_model_days WHERE scope=:scope AND day=:day"), {"scope": scope, "day": day})


def set_day(factory, scope, day, tokens):
    with factory.begin() as db:
        db.execute(text("""INSERT INTO customer_service_model_days VALUES (:scope, :day, :tokens)
            ON CONFLICT (scope, day) DO UPDATE SET tokens=excluded.tokens"""),
            {"scope": scope, "day": day, "tokens": tokens})


def test_reserve_settle_and_idempotence_across_instances(budget_context):
    factory, ids, clock = budget_context
    budget = ModelBudget(factory, clock=lambda: clock[0])
    before = ledger(factory, "deployment", clock[0].date()) or 0
    request = budget.reserve(ids[0], input_tokens=12_000)
    assert request.reserved_tokens == 13_500
    assert request.max_output_tokens == 1_500
    assert ledger(factory, str(ids[0]), request.day) == 13_500
    assert ledger(factory, "deployment", request.day) == before + 13_500
    restarted = ModelBudget(factory, clock=lambda: clock[0])
    assert restarted.settle_confirmed_end(ids[0], request.id, completion=Completion.SUCCESS,
                                          usage=ProviderUsage(12_000, 100)) == 12_100
    assert restarted.settle_confirmed_end(ids[0], request.id, completion=Completion.FAILURE) == 12_100
    assert ledger(factory, str(ids[0]), request.day) == 12_100
    assert ledger(factory, "deployment", request.day) == before + 12_100


@pytest.mark.parametrize("scope,limit", [("session", 50_000), ("deployment", 500_000)])
def test_atomic_daily_boundary_rolls_back_other_scope(budget_context, scope, limit):
    factory, ids, clock = budget_context
    budget = ModelBudget(factory, clock=lambda: clock[0])
    key = str(ids[0]) if scope == "session" else scope
    set_day(factory, key, clock[0].date(), limit - 13_500)
    request = budget.reserve(ids[0], input_tokens=12_000)
    budget.settle_confirmed_end(ids[0], request.id, completion=Completion.FAILURE)
    assert ledger(factory, key, request.day) == limit
    before = ledger(factory, "deployment", request.day)
    with pytest.raises(ModelBudgetDenied):
        budget.reserve(ids[0], input_tokens=0)
    assert ledger(factory, "deployment", request.day) == before


def test_concurrent_workers_share_exactly_two_slots(budget_context):
    factory, ids, clock = budget_context
    barrier = Barrier(8)

    def reserve(i):
        budget = ModelBudget(factory, clock=lambda: clock[0])
        barrier.wait(timeout=10)
        try:
            return budget.reserve(ids[i % len(ids)], input_tokens=100)
        except ModelBudgetDenied:
            return None

    with ThreadPoolExecutor(max_workers=8) as workers:
        results = list(workers.map(reserve, range(8)))
    accepted = [result for result in results if result is not None]
    assert len(accepted) == 2
    assert len({result.id for result in accepted}) == 2


def test_concurrent_admission_cannot_overspend_session_or_deployment(budget_context):
    factory, ids, clock = budget_context
    day = clock[0].date()
    set_day(factory, "deployment", day, 498_500)
    set_day(factory, str(ids[0]), day, 48_500)
    barrier = Barrier(4)

    def reserve(_):
        barrier.wait(timeout=10)
        try:
            return ModelBudget(factory, clock=lambda: clock[0]).reserve(ids[0], input_tokens=0)
        except ModelBudgetDenied:
            return None

    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(reserve, range(4)))
    assert sum(result is not None for result in results) == 1
    assert ledger(factory, "deployment", day) == 500_000
    assert ledger(factory, str(ids[0]), day) == 50_000


def test_timeout_rollover_and_session_deletion_release_only_after_ttl(budget_context):
    factory, ids, clock = budget_context
    clock[0] = clock[0].replace(hour=23, minute=59, second=59)
    budget = ModelBudget(factory, clock=lambda: clock[0])
    first = budget.reserve(ids[0], input_tokens=100)
    second = budget.reserve(ids[1], input_tokens=100)
    budget.mark_caller_timeout(ids[0], first.id)
    clock[0] += timedelta(seconds=89)
    with factory.begin() as db:
        db.execute(text("DELETE FROM auth_sessions WHERE id=:id"), {"id": ids[0]})
    restarted = ModelBudget(factory, clock=lambda: clock[0])
    with pytest.raises(ModelBudgetDenied):
        restarted.reserve(ids[2], input_tokens=100)
    clock[0] += timedelta(seconds=1)
    third = restarted.reserve(ids[2], input_tokens=0)
    with factory() as db:
        rows = db.execute(text("""SELECT ended_at, settlement_reason FROM customer_service_model_reservations
            WHERE id IN (:first, :second)"""), {"first": first.id, "second": second.id}).all()
        assert len(rows) == 2
        assert all(row.ended_at is not None and row.settlement_reason == "assumed_max" for row in rows)
    assert restarted.settle_confirmed_end(ids[0], first.id, completion=Completion.SUCCESS,
                                         usage=ProviderUsage(100, 1)) == 1_600
    assert ledger(factory, str(ids[0]), first.day) == 1_600
    assert third.day == clock[0].date() and third.day != first.day
    assert ledger(factory, str(ids[2]), third.day) == 1_500
    assert restarted.settle_confirmed_end(ids[1], second.id, completion=Completion.FAILURE) == 1_600


@pytest.mark.parametrize("usage", [None, ProviderUsage(-1, 0), ProviderUsage(True, 0),
                                    ProviderUsage(101, 0), ProviderUsage(100, 1501)])
def test_unreliable_success_usage_latches_admission_closed(budget_context, usage):
    factory, ids, clock = budget_context
    budget = ModelBudget(factory, clock=lambda: clock[0])
    request = budget.reserve(ids[0], input_tokens=100)
    assert budget.settle_confirmed_end(ids[0], request.id, completion=Completion.SUCCESS, usage=usage) == 1_600
    with pytest.raises(ModelBudgetUnavailable):
        ModelBudget(factory).reserve(ids[1], input_tokens=0)
    with factory() as db:
        assert db.scalar(text("SELECT ended_at IS NOT NULL FROM customer_service_model_reservations WHERE id=:id"), {"id": request.id})


def test_concurrent_settlement_refunds_once(budget_context):
    factory, ids, clock = budget_context
    budget = ModelBudget(factory, clock=lambda: clock[0])
    request = budget.reserve(ids[0], input_tokens=100)
    barrier = Barrier(4)

    def settle(_):
        barrier.wait(timeout=10)
        return ModelBudget(factory).settle_confirmed_end(ids[0], request.id, completion=Completion.SUCCESS,
                                                         usage=ProviderUsage(100, 10))

    with ThreadPoolExecutor(max_workers=4) as workers:
        assert list(workers.map(settle, range(4))) == [110] * 4
    assert ledger(factory, str(ids[0]), request.day) == 110


def test_strict_internal_ids_counts_and_session_ownership(budget_context):
    factory, ids, clock = budget_context
    budget = ModelBudget(factory, clock=lambda: clock[0])
    for invalid in (str(ids[0]), "buyer-supplied", None):
        with pytest.raises(ValueError):
            budget.reserve(invalid, input_tokens=0)
    for invalid in (True, -1, 12_001, 1.5):
        with pytest.raises(ValueError):
            budget.reserve(ids[0], input_tokens=invalid)
    for invalid in (None, "untrusted", 1):
        with pytest.raises(ValueError):
            budget.reserve(ids[0], input_tokens=0, metering_mode=invalid)
    with pytest.raises(ModelBudgetDenied):
        budget.reserve(uuid4(), input_tokens=0)
    request = budget.reserve(ids[0], input_tokens=0)
    with pytest.raises(ModelReservationNotFound):
        budget.settle_confirmed_end(ids[1], request.id, completion=Completion.FAILURE)
    with factory.begin() as db:
        db.execute(text("UPDATE auth_sessions SET revoked_at=:now WHERE id=:id"), {"now": clock[0], "id": ids[1]})
    with pytest.raises(ModelBudgetDenied):
        budget.reserve(ids[1], input_tokens=0)


def test_utc_date_and_late_settlement_charge_original_day(budget_context):
    factory, ids, clock = budget_context
    clock[0] = clock[0].replace(hour=23, minute=30).astimezone(timezone(timedelta(hours=8)))
    budget = ModelBudget(factory, clock=lambda: clock[0])
    request = budget.reserve(ids[0], input_tokens=100)
    assert request.day == clock[0].astimezone(UTC).date()
    assert request.day != clock[0].date()
    clock[0] = clock[0].replace(minute=59, second=59, microsecond=0)
    # The request above was made at 23:30 UTC; use a fresh near-midnight request
    # to verify an actual-usage refund across midnight within the 90-second TTL.
    assert budget.reap_expired() == 1
    request = budget.reserve(ids[1], input_tokens=100)
    clock[0] += timedelta(seconds=2)
    assert budget.settle_confirmed_end(ids[1], request.id, completion=Completion.SUCCESS,
                                      usage=ProviderUsage(100, 10)) == 110
    assert ledger(factory, str(ids[1]), request.day) == 110
    assert ledger(factory, str(ids[1]), clock[0].astimezone(UTC).date()) is None


def test_incomplete_ledger_rolls_back_settlement_and_keeps_slot(budget_context):
    factory, ids, clock = budget_context
    budget = ModelBudget(factory, clock=lambda: clock[0])
    request = budget.reserve(ids[0], input_tokens=100)
    before = ledger(factory, "deployment", request.day)
    with factory.begin() as db:
        db.execute(text("DELETE FROM customer_service_model_days WHERE scope=:scope AND day=:day"),
                   {"scope": str(ids[0]), "day": request.day})
    with pytest.raises(ModelBudgetUnavailable, match="Incomplete shared model ledger"):
        budget.settle_confirmed_end(ids[0], request.id, completion=Completion.SUCCESS,
                                    usage=ProviderUsage(100, 10))
    assert ledger(factory, "deployment", request.day) == before
    with factory() as db:
        row = db.execute(text("SELECT charged_tokens, ended_at FROM customer_service_model_reservations WHERE id=:id"),
                         {"id": request.id}).one()
        assert row.charged_tokens == 1_600
        assert row.ended_at is None


def test_model_turn_limits_four_requests_and_twenty_second_attempts(budget_context, monkeypatch):
    from shop_api.customer_service import CustomerServiceUnavailable
    from shop_api.customer_service_model_turn import ModelTurn
    import shop_api.customer_service_model_turn as module

    factory, ids, clock = budget_context
    moments = [0.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: moments[0])
    budget = ModelBudget(factory, clock=lambda: clock[0])
    turn = ModelTurn(budget, ids[0])
    for _ in range(4):
        reservation, timeout = turn.reserve(measured_input_tokens=10)
        assert timeout == 20.0
        budget.settle_confirmed_end(ids[0], reservation.id, completion=Completion.FAILURE)
    with pytest.raises(CustomerServiceUnavailable):
        turn.reserve(measured_input_tokens=10)
    other = ModelTurn(budget, ids[1])
    moments[0] = 40.0
    reservation, timeout = other.reserve(measured_input_tokens=10)
    assert timeout == 5.0
    other.mark_timeout(reservation)
    moments[0] = 45.0
    with pytest.raises(CustomerServiceUnavailable):
        other.reserve(measured_input_tokens=10)
    budget.settle_confirmed_end(ids[1], reservation.id, completion=Completion.FAILURE)


def test_retention_removes_only_terminal_records_and_preserves_outstanding_accounting(budget_context):
    factory, ids, clock = budget_context
    budget = ModelBudget(factory, clock=lambda: clock[0])
    ended = budget.reserve(ids[0], input_tokens=100)
    budget.settle_confirmed_end(ids[0], ended.id, completion=Completion.FAILURE)
    outstanding = budget.reserve(ids[1], input_tokens=100)
    budget.mark_caller_timeout(ids[1], outstanding.id)
    clock[0] += timedelta(days=31)
    assert budget.prune_ended() == 1
    assert budget.prune_ended() == 0
    with factory() as db:
        assert db.scalar(text('SELECT count(*) FROM customer_service_model_reservations WHERE id=:id'), {'id': ended.id}) == 0
        assert db.scalar(text('SELECT ended_at IS NULL FROM customer_service_model_reservations WHERE id=:id'), {'id': outstanding.id}) is True
    assert ledger(factory, 'deployment', outstanding.day) is not None
    assert budget.settle_confirmed_end(ids[1], outstanding.id, completion=Completion.FAILURE) == 1600


def test_estimated_measurement_reserves_full_allowance(budget_context):
    from shop_api.customer_service import ProductFixture
    from shop_api.customer_service_model import ModelProductFacts
    from shop_api.customer_service_model_turn import ModelTurn
    factory, ids, clock = budget_context
    product_id = '00000000-0000-0000-0000-000000000001'
    facts = ModelProductFacts.from_fixture({product_id: ProductFixture(product_id, 'demo', 'demo', '129.00', 24, True)})
    before = ledger(factory, 'deployment', clock[0].date())
    budget = ModelBudget(factory, clock=lambda: clock[0])
    _, reservation, timeout = ModelTurn(budget, ids[0]).prepare(facts)
    assert reservation.reserved_tokens == 13_500
    assert 0 < timeout <= 20
    assert ledger(factory, 'deployment', reservation.day) == (before or 0) + 13_500
    assert budget.settle_confirmed_end(ids[0], reservation.id, completion=Completion.SUCCESS,
                                      usage=ProviderUsage(12_000, 100)) == 12_100
    assert ledger(factory, str(ids[0]), reservation.day) == 12_100


@pytest.mark.parametrize("estimate", [0, 100, 12_000])
def test_estimated_reservation_full_max_and_usage_above_estimate(budget_context, estimate):
    factory, ids, clock = budget_context
    budget = ModelBudget(factory, clock=lambda: clock[0])
    request = budget.reserve(ids[0], input_tokens=estimate, metering_mode="estimated")
    assert request.reserved_tokens == 13_500
    assert ledger(factory, str(ids[0]), request.day) == 13_500
    assert budget.settle_confirmed_end(ids[0], request.id, completion=Completion.SUCCESS,
                                      usage=ProviderUsage(12_000, 1_500)) == 13_500
    # A valid actual count above the estimate must not latch metering closed.
    another = budget.reserve(ids[0], input_tokens=0)
    budget.settle_confirmed_end(ids[0], another.id, completion=Completion.FAILURE)


def test_explicit_maintenance_retains_original_utc_day_and_late_settlement(budget_context):
    factory, ids, clock = budget_context
    clock[0] = clock[0].replace(hour=23, minute=59, second=30, microsecond=0).astimezone(
        timezone(timedelta(hours=8)))
    budget = ModelBudget(factory, clock=lambda: clock[0])
    first = budget.reserve(ids[0], input_tokens=10, metering_mode="estimated")
    second = budget.reserve(ids[1], input_tokens=0, metering_mode="estimated")
    before = ledger(factory, "deployment", first.day)
    assert first.day == clock[0].astimezone(UTC).date()
    assert first.day != clock[0].date()
    clock[0] += timedelta(seconds=89)
    assert budget.reap_expired() == 0
    clock[0] += timedelta(seconds=1)
    assert budget.reap_expired() == 2
    assert budget.reap_expired() == 0
    assert budget.settle_confirmed_end(ids[0], first.id, completion=Completion.SUCCESS,
                                      usage=ProviderUsage(1, 1)) == 13_500
    assert budget.settle_confirmed_end(ids[1], second.id, completion=Completion.SUCCESS) == 13_500
    assert ledger(factory, "deployment", first.day) == before
    assert ledger(factory, str(ids[0]), first.day) == 13_500
    assert ledger(factory, "deployment", clock[0].astimezone(UTC).date()) is None
    third = budget.reserve(ids[2], input_tokens=0)
    assert third.day != first.day


def test_late_response_without_maintenance_assumes_max(budget_context):
    factory, ids, clock = budget_context
    budget = ModelBudget(factory, clock=lambda: clock[0])
    request = budget.reserve(ids[0], input_tokens=0, metering_mode="estimated")
    clock[0] += timedelta(seconds=90)
    assert budget.settle_confirmed_end(ids[0], request.id, completion=Completion.SUCCESS,
                                      usage=ProviderUsage(0, 0)) == 13_500
    assert budget.settle_confirmed_end(ids[0], request.id, completion=Completion.SUCCESS,
                                      usage=ProviderUsage(0, 0)) == 13_500
    assert ledger(factory, str(ids[0]), request.day) == 13_500
    with factory() as db:
        assert db.scalar(text("""SELECT settlement_reason FROM customer_service_model_reservations
            WHERE id=:id"""), {"id": request.id}) == "assumed_max"


def test_storage_failure_is_fail_closed(budget_context, monkeypatch):
    factory, ids, _ = budget_context

    def unavailable():
        raise OperationalError("private", {}, Exception("private"))

    monkeypatch.setattr(factory, "begin", unavailable)
    with pytest.raises(ModelBudgetUnavailable, match="Shared model accounting unavailable"):
        ModelBudget(factory).reserve(ids[0], input_tokens=0)
