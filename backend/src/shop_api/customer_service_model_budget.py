"""Offline accounting only; this module neither enables nor calls a model.

All IDs and token counts come from trusted server context, never tool/browser fields.
Reserve commits before a future transport may send. Each reservation authorizes exactly
one provider attempt; retries need a fresh reservation. Verified metering reserves
measured input; estimated metering reserves the entire input/output allowance.

Admission slots expire after 90 seconds and settle at their full reserved charge with
reason assumed_max. This releases local capacity only: it does not prove that a remote
provider request has stopped. Late responses cannot refund an expired reservation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

INPUT_LIMIT = 12_000
OUTPUT_LIMIT = 1_500
SESSION_DAILY_LIMIT = 50_000
DEPLOYMENT_DAILY_LIMIT = 500_000
MAX_IN_FLIGHT = 2
RESERVATION_TTL_SECONDS = 90
_DEPLOYMENT = "deployment"


class ModelBudgetUnavailable(RuntimeError):
    """Shared accounting or metering is unavailable; do not send a request."""


class ModelBudgetDenied(RuntimeError):
    """Budget, concurrent capacity or authenticated buyer context denied admission."""


class ModelReservationNotFound(ValueError):
    """Reservation does not belong to the supplied internal session."""


class Completion(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"


@dataclass(frozen=True)
class ProviderUsage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class ModelReservation:
    id: UUID
    session_id: UUID
    day: date
    reserved_tokens: int
    max_output_tokens: int = OUTPUT_LIMIT


def _uuid(value: UUID) -> None:
    if type(value) is not UUID or value.int == 0:
        raise ValueError("Expected a nonzero internal UUID")


def _count(value: int, maximum: int) -> bool:
    return type(value) is int and 0 <= value <= maximum


class ModelBudget:
    """One deployment-wide ledger, shared by every worker using the same database.

    Owns short transactions; never holds a DB transaction across network work.
    `clock` is an optional trusted server test clock; production uses PostgreSQL UTC.
    Infrastructure errors fail closed. A bad successful usage report persistently
    blocks admission; there is intentionally no automatic reset of that safety latch.
    """

    def __init__(self, session_factory: sessionmaker[Session], *,
                 clock: Callable[[], datetime] | None = None,
                 product_only: bool = False, approved_buyer_ids=()):
        self._factory = session_factory
        self._clock = clock
        self._product_only = product_only
        self._approved_buyer_ids = frozenset(approved_buyer_ids)

    def _lock(self, db: Session) -> bool:
        row = db.execute(text("SELECT metering_blocked FROM customer_service_model_guard WHERE id=1 FOR UPDATE")).one_or_none()
        if row is None:
            raise ModelBudgetUnavailable("Missing shared model guard")
        return row.metering_blocked

    def _now(self, db: Session) -> datetime:
        now = self._clock() if self._clock else db.scalar(text("SELECT clock_timestamp()"))
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ModelBudgetUnavailable("UTC clock unavailable")
        return now.astimezone(UTC)

    def _reap_expired(self, db: Session, now: datetime) -> int:
        # The full reserved charge already belongs to the original UTC day. Do not
        # refund or move it when freeing local admission capacity.
        result = db.execute(text("""UPDATE customer_service_model_reservations
            SET ended_at=:now, settlement_reason='assumed_max'
            WHERE ended_at IS NULL AND expires_at<=:now"""), {"now": now})
        return result.rowcount or 0

    def reap_expired(self) -> int:
        """Settle expired local slots at full charge; remote work may still be running."""
        try:
            with self._factory.begin() as db:
                self._lock(db)
                return self._reap_expired(db, self._now(db))
        except SQLAlchemyError:
            raise ModelBudgetUnavailable("Shared model accounting unavailable") from None

    def reserve(self, session_id: UUID, *, input_tokens: int,
                metering_mode: str = "verified") -> ModelReservation:
        """Atomically reserve input + worst-case output and one 90-second local slot.

        Estimated metering reserves 12000 + 1500 regardless of the supplied estimate.

        The session ID must originate in authenticated server context. This checks an
        active buyer session, but demo eligibility and tokenizer reliability remain
        prerequisites for the future caller; this API is not an authorization gate.
        """
        _uuid(session_id)
        if not _count(input_tokens, INPUT_LIMIT):
            raise ValueError("Input tokens must be an integer between 0 and 12000")
        if metering_mode not in ("estimated", "verified"):
            raise ValueError("Expected estimated or verified metering mode")
        charge = (INPUT_LIMIT if metering_mode == "estimated" else input_tokens) + OUTPUT_LIMIT
        reservation_id = uuid4()
        try:
            with self._factory.begin() as db:
                if self._lock(db):
                    raise ModelBudgetUnavailable("Model metering blocked")
                now = self._now(db)
                self._reap_expired(db, now)
                day = now.date()
                if self._product_only:
                    valid = db.execute(text("""SELECT s.id FROM auth_sessions s
                        WHERE s.id=:id AND s.revoked_at IS NULL AND s.expires_at>:now
                        AND ((s.kind='anonymous' AND s.user_id IS NULL AND s.created_at + interval '30 minutes'>:now)
                        OR (s.kind='authenticated' AND s.user_id=ANY(:buyers) AND EXISTS
                            (SELECT 1 FROM users u WHERE u.id=s.user_id AND u.is_active AND u.role='buyer')))
                        FOR SHARE OF s"""), {"id": session_id, "now": now, "buyers": list(self._approved_buyer_ids)}).one_or_none()
                else:
                    valid = db.execute(text("""SELECT s.id FROM auth_sessions s JOIN users u ON u.id=s.user_id
                        WHERE s.id=:id AND s.kind='authenticated' AND s.revoked_at IS NULL
                        AND s.expires_at>:now AND u.is_active AND u.role='buyer'
                        FOR SHARE OF s, u"""), {"id": session_id, "now": now}).one_or_none()
                if valid is None:
                    raise ModelBudgetDenied("Active buyer session required")
                outstanding = db.scalar(text("SELECT count(*) FROM customer_service_model_reservations WHERE ended_at IS NULL"))
                if outstanding >= MAX_IN_FLIGHT:
                    raise ModelBudgetDenied("Model concurrency exhausted")
                for scope, limit in ((_DEPLOYMENT, DEPLOYMENT_DAILY_LIMIT), (str(session_id), SESSION_DAILY_LIMIT)):
                    db.execute(text("""INSERT INTO customer_service_model_days(scope, day, tokens)
                        VALUES (:scope, :day, 0) ON CONFLICT DO NOTHING"""), {"scope": scope, "day": day})
                    tokens = db.scalar(text("SELECT tokens FROM customer_service_model_days WHERE scope=:scope AND day=:day"), {"scope": scope, "day": day})
                    if tokens + charge > limit:
                        raise ModelBudgetDenied("Daily model budget exhausted")
                    db.execute(text("UPDATE customer_service_model_days SET tokens=tokens+:charge WHERE scope=:scope AND day=:day"),
                               {"scope": scope, "day": day, "charge": charge})
                db.execute(text("""INSERT INTO customer_service_model_reservations
                    (id, session_id, day, input_tokens, charged_tokens, caller_timed_out,
                     created_at, expires_at, metering_mode)
                    VALUES (:id, :session, :day, :input, :charge, false, :now, :expires, :mode)"""),
                    {"id": reservation_id, "session": session_id, "day": day, "input": input_tokens,
                     "charge": charge, "now": now, "expires": now + timedelta(seconds=RESERVATION_TTL_SECONDS),
                     "mode": metering_mode})
            return ModelReservation(reservation_id, session_id, day, charge)
        except SQLAlchemyError:
            raise ModelBudgetUnavailable("Shared model accounting unavailable") from None

    def prune_ended(self) -> int:
        """Delete terminal ledger entries after 30 days; never reclaim in-flight work.

        Day counters needed by outstanding reservations are retained even across
        long outages. The permanent metering latch is not cleared by retention.
        """
        try:
            with self._factory.begin() as db:
                self._lock(db)
                cutoff = self._now(db) - timedelta(days=30)
                result = db.execute(text("""DELETE FROM customer_service_model_reservations
                    WHERE ended_at IS NOT NULL AND ended_at <= :cutoff"""), {"cutoff": cutoff})
                db.execute(text("""DELETE FROM customer_service_model_days d
                    WHERE d.day < :day AND NOT EXISTS (
                        SELECT 1 FROM customer_service_model_reservations r
                        WHERE r.day=d.day AND (d.scope='deployment' OR d.scope=CAST(r.session_id AS text)))"""),
                           {"day": cutoff.date()})
                return result.rowcount or 0
        except SQLAlchemyError:
            raise ModelBudgetUnavailable("Shared model accounting unavailable") from None

    def _reservation(self, db: Session, session_id: UUID, reservation_id: UUID):
        row = db.execute(text("""SELECT * FROM customer_service_model_reservations
            WHERE id=:id AND session_id=:session FOR UPDATE"""),
            {"id": reservation_id, "session": session_id}).one_or_none()
        if row is None:
            raise ModelReservationNotFound("Unknown model reservation")
        return row

    def mark_caller_timeout(self, session_id: UUID, reservation_id: UUID) -> None:
        """Keep the full reservation charge; local slot expiry remains unchanged.

        Call before reporting timeout. A timeout arriving after a successful settlement
        cannot reopen the already-ended request or change its recorded charge.
        """
        _uuid(session_id)
        _uuid(reservation_id)
        try:
            with self._factory.begin() as db:
                self._lock(db)
                row = self._reservation(db, session_id, reservation_id)
                if row.ended_at is None:
                    db.execute(text("UPDATE customer_service_model_reservations SET caller_timed_out=true WHERE id=:id"), {"id": reservation_id})
        except SQLAlchemyError:
            raise ModelBudgetUnavailable("Shared model accounting unavailable") from None

    def settle_confirmed_end(self, session_id: UUID, reservation_id: UUID, *,
                             completion: Completion, usage: ProviderUsage | None = None) -> int:
        """Settle confirmed provider end or an expired local slot; return final charge.

        Success refunds unused reservation using validated total provider input/output
        (including cached input). Failure or caller timeout always costs the full
        reservation, even if usage is supplied. Missing/invalid successful usage keeps
        the full charge and latches model admission closed. Settlement is idempotent;
        the first terminal result wins, including assumed_max expiry and worker restarts.
        """
        _uuid(session_id)
        _uuid(reservation_id)
        if type(completion) is not Completion:
            raise ValueError("Expected a Completion enum")
        try:
            with self._factory.begin() as db:
                self._lock(db)
                now = self._now(db)
                self._reap_expired(db, now)
                row = self._reservation(db, session_id, reservation_id)
                if row.ended_at is not None:
                    return row.charged_tokens
                charge = row.charged_tokens
                reason = "assumed_max"
                if completion is Completion.SUCCESS:
                    reliable = (type(usage) is ProviderUsage
                                and _count(usage.input_tokens, INPUT_LIMIT if row.metering_mode == "estimated" else row.input_tokens)
                                and _count(usage.output_tokens, OUTPUT_LIMIT))
                    if not reliable:
                        db.execute(text("UPDATE customer_service_model_guard SET metering_blocked=true WHERE id=1"))
                    elif not row.caller_timed_out:
                        charge = usage.input_tokens + usage.output_tokens
                        reason = "actual_usage"
                refund = row.charged_tokens - charge
                for scope in (_DEPLOYMENT, str(session_id)):
                    result = db.execute(text("""UPDATE customer_service_model_days SET tokens=tokens-:refund
                        WHERE scope=:scope AND day=:day AND tokens>=:reserved"""),
                        {"scope": scope, "day": row.day, "refund": refund, "reserved": row.charged_tokens})
                    if result.rowcount != 1:
                        raise ModelBudgetUnavailable("Incomplete shared model ledger")
                db.execute(text("""UPDATE customer_service_model_reservations
                    SET charged_tokens=:charge, ended_at=:now, settlement_reason=:reason WHERE id=:id"""),
                    {"charge": charge, "now": now, "reason": reason, "id": reservation_id})
            return charge
        except SQLAlchemyError:
            raise ModelBudgetUnavailable("Shared model accounting unavailable") from None
