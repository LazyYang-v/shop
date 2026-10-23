"""Durable lifetime paid-call budget; no provider transmission is enabled here.

One singleton row holds the whole allowance across sessions, workers and restarts:
at most 200 committed provider attempts and at most RMB 20 (2,000 fen) in total.
Money is reserved atomically before a future transport may send, using a frozen
price card. Ambiguous or late outcomes keep the full reservation; only a validated,
timely actual usage report can refund unused money. Attempt counts never refund.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from shop_api.customer_service_model_budget import (
    INPUT_LIMIT, OUTPUT_LIMIT, ModelBudgetDenied, ModelBudgetUnavailable,
    ModelReservationNotFound,
)

MAX_ATTEMPTS = 200
CAP_FEN = 2000
_MICROS_PER_CURRENCY_UNIT = 1_000_000
_TOKENS_PER_PRICE_UNIT = 1_000_000
_FEN_PER_CURRENCY_UNIT = 100


def _uuid(value: UUID) -> None:
    if type(value) is not UUID or value.int == 0:
        raise ValueError("Expected a nonzero internal UUID")


def _bounded_text(value: str, maximum: int) -> str:
    if type(value) is not str or not value or len(value) > maximum:
        raise ValueError("Invalid price card text")
    return value


def _rate(value: int) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("Price card rates must be non-negative integers")
    return value


@dataclass(frozen=True)
class PriceCard:
    """Frozen provider price snapshot. Rates are provider micro-units per 1M tokens.

    The card is supplied by trusted server code after review; it is never read from
    the browser, tools, model output or environment. Reservations charge every input
    token at the cache-miss rate, so an unexpected cache miss cannot exceed the bound.
    """

    version: str
    provider: str
    model: str
    source: str
    approval: str
    currency: str
    input_micros: int
    output_micros: int
    cache_hit_micros: int
    fx_numerator: int
    fx_denominator: int

    def __post_init__(self) -> None:
        for name, maximum in (("version", 64), ("provider", 64), ("model", 128),
                              ("source", 256), ("approval", 128)):
            _bounded_text(getattr(self, name), maximum)
        if self.currency not in ("USD", "CNY"):
            raise ValueError("Unsupported price card currency")
        for name in ("input_micros", "output_micros", "cache_hit_micros"):
            _rate(getattr(self, name))
        if type(self.fx_numerator) is not int or self.fx_numerator <= 0:
            raise ValueError("FX numerator must be a positive integer")
        if type(self.fx_denominator) is not int or self.fx_denominator <= 0:
            raise ValueError("FX denominator must be a positive integer")

    def canonical_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def digest(self) -> str:
        return sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_json(cls, value) -> "PriceCard":
        if not isinstance(value, dict):
            raise ValueError("Stored price card is invalid")
        fields = set(cls.__dataclass_fields__)
        if set(value) != fields:
            raise ValueError("Stored price card fields are invalid")
        try:
            return cls(**value)
        except (TypeError, ValueError):
            raise ValueError("Stored price card is invalid") from None

    def cost_fen(self, input_tokens: int, output_tokens: int) -> int:
        """Round the worst-case cost up to whole fen; never use floating point."""
        if (type(input_tokens) is not int or input_tokens < 0
                or type(output_tokens) is not int or output_tokens < 0):
            raise ValueError("Token counts must be non-negative integers")
        numerator = ((input_tokens * self.input_micros + output_tokens * self.output_micros)
                     * self.fx_numerator * _FEN_PER_CURRENCY_UNIT)
        denominator = _TOKENS_PER_PRICE_UNIT * _MICROS_PER_CURRENCY_UNIT * self.fx_denominator
        return -(-numerator // denominator)


@dataclass(frozen=True)
class PaidReservation:
    reservation_id: UUID
    session_id: UUID
    price_card_sha256: str
    reserved_fen: int


@dataclass(frozen=True)
class SpendStatus:
    state: str
    attempts: int
    charged_fen: int
    max_attempts: int
    cap_fen: int
    stopped_reason: str | None


class SpendGuard:
    """Serialize every paid permit through one durable PostgreSQL row."""

    def __init__(self, session_factory: sessionmaker[Session], *,
                 clock: Callable[[], datetime] | None = None):
        self._factory = session_factory
        self._clock = clock

    def _now(self, db: Session) -> datetime:
        now = self._clock() if self._clock else db.scalar(text("SELECT clock_timestamp()"))
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ModelBudgetUnavailable("UTC clock unavailable")
        return now.astimezone(UTC)

    def _singleton(self, db: Session):
        row = db.execute(text("SELECT * FROM customer_service_paid_budget WHERE id=1 FOR UPDATE")).one_or_none()
        if row is None:
            raise ModelBudgetUnavailable("Missing paid budget guard")
        return row

    def reserve(self, reservation_id: UUID, *, session_id: UUID,
                price_card: PriceCard | None) -> PaidReservation:
        """Atomically commit one attempt and its full worst-case cost, or deny."""
        _uuid(reservation_id)
        _uuid(session_id)
        if not isinstance(price_card, PriceCard):
            raise ModelBudgetUnavailable("A frozen reviewed price card is required")
        digest = price_card.digest()
        try:
            denied: str | None = None
            with self._factory.begin() as db:
                paid = self._singleton(db)
                now = self._now(db)
                row = db.execute(text("""SELECT * FROM customer_service_model_reservations
                    WHERE id=:id AND session_id=:session FOR UPDATE"""),
                    {"id": reservation_id, "session": session_id}).one_or_none()
                if row is None:
                    raise ModelReservationNotFound("Unknown model reservation")
                if row.paid_reserved_fen is not None:
                    raise ModelBudgetUnavailable("Reservation already has a paid permit")
                if row.ended_at is not None or row.expires_at <= now:
                    raise ModelBudgetUnavailable("Model reservation is no longer open")
                state = paid.state
                if state == "blocked":
                    denied = "blocked"
                elif state == "stopped":
                    denied = paid.stopped_reason or "stopped"
                elif state == "armed" and paid.price_card_sha256 != digest:
                    denied = "price_card_mismatch"
                else:
                    if state == "disabled":
                        db.execute(text("""UPDATE customer_service_paid_budget
                            SET state='armed', armed_at=:now, price_card_sha256=:digest,
                                price_card=CAST(:card AS jsonb) WHERE id=1"""),
                            {"now": now, "digest": digest, "card": price_card.canonical_json()})
                    input_tokens = row.input_tokens
                    input_bound = INPUT_LIMIT if row.metering_mode == "estimated" else input_tokens
                    if not 0 <= input_bound <= INPUT_LIMIT:
                        raise ModelBudgetUnavailable("Reservation input bound is invalid")
                    reserved_fen = price_card.cost_fen(input_bound, OUTPUT_LIMIT)
                    if paid.attempts_committed + 1 > paid.max_attempts:
                        reason = "attempt_cap"
                    elif paid.charged_fen + reserved_fen > paid.cap_fen:
                        reason = "spend_cap"
                    else:
                        reason = None
                    if reason is not None:
                        db.execute(text("""UPDATE customer_service_paid_budget
                            SET state='stopped', stopped_reason=:reason, stopped_at=:now
                            WHERE id=1"""), {"reason": reason, "now": now})
                        denied = reason
                    else:
                        db.execute(text("""UPDATE customer_service_paid_budget
                            SET attempts_committed=attempts_committed+1,
                                charged_fen=charged_fen+:cost WHERE id=1"""),
                            {"cost": reserved_fen})
                        db.execute(text("""UPDATE customer_service_model_reservations
                            SET paid_reserved_fen=:cost, paid_price_card_sha256=:digest
                            WHERE id=:id"""), {"cost": reserved_fen, "digest": digest, "id": reservation_id})
                        result = PaidReservation(reservation_id, session_id, digest, reserved_fen)
            if denied is not None:
                raise ModelBudgetDenied(f"Paid model budget {denied}")
            return result
        except SQLAlchemyError:
            raise ModelBudgetUnavailable("Shared paid accounting unavailable") from None

    def claim_dispatch(self, reservation_id: UUID, *, session_id: UUID) -> bool:
        """Consume the one-shot send permit; a claimed reservation is never resent."""
        _uuid(reservation_id)
        _uuid(session_id)
        try:
            with self._factory.begin() as db:
                paid = self._singleton(db)
                now = self._now(db)
                if paid.state == "blocked":
                    return False
                result = db.execute(text("""UPDATE customer_service_model_reservations
                    SET dispatch_claimed_at=:now
                    WHERE id=:id AND session_id=:session AND paid_reserved_fen IS NOT NULL
                    AND dispatch_claimed_at IS NULL AND ended_at IS NULL AND expires_at>:now"""),
                    {"id": reservation_id, "session": session_id, "now": now})
                if result.rowcount == 1:
                    return True
                exists = db.scalar(text("""SELECT 1 FROM customer_service_model_reservations
                    WHERE id=:id AND session_id=:session"""), {"id": reservation_id, "session": session_id})
                if exists is None:
                    raise ModelReservationNotFound("Unknown model reservation")
                return False
        except SQLAlchemyError:
            raise ModelBudgetUnavailable("Shared paid accounting unavailable") from None

    def settle(self, reservation_id: UUID, *, session_id: UUID,
               input_tokens: int, output_tokens: int) -> int:
        """Refund unused money only for validated, timely usage; return final charge."""
        _uuid(reservation_id)
        _uuid(session_id)
        if (type(input_tokens) is not int or input_tokens < 0
                or type(output_tokens) is not int or output_tokens < 0):
            raise ValueError("Token counts must be non-negative integers")
        try:
            latch: str | None = None
            with self._factory.begin() as db:
                paid = self._singleton(db)
                now = self._now(db)
                row = db.execute(text("""SELECT * FROM customer_service_model_reservations
                    WHERE id=:id AND session_id=:session FOR UPDATE"""),
                    {"id": reservation_id, "session": session_id}).one_or_none()
                if row is None:
                    raise ModelReservationNotFound("Unknown model reservation")
                if row.paid_reserved_fen is None:
                    raise ModelBudgetUnavailable("Reservation has no paid permit")
                if row.paid_settled_at is not None:
                    return row.paid_charged_fen
                if row.ended_at is not None or now >= row.expires_at:
                    return row.paid_reserved_fen
                card = PriceCard.from_json(paid.price_card)
                input_bound = INPUT_LIMIT if row.metering_mode == "estimated" else row.input_tokens
                output_bound = OUTPUT_LIMIT
                if not 0 <= input_bound <= INPUT_LIMIT:
                    raise ModelBudgetUnavailable("Reservation input bound is invalid")
                if input_tokens > input_bound or output_tokens > output_bound:
                    latch = "usage_over_bound"
                    db.execute(text("""UPDATE customer_service_paid_budget
                        SET state='blocked', stopped_reason='usage_over_bound', stopped_at=:now
                        WHERE id=1"""), {"now": now})
                    actual = row.paid_reserved_fen
                else:
                    actual = min(card.cost_fen(input_tokens, output_tokens), row.paid_reserved_fen)
                    db.execute(text("""UPDATE customer_service_paid_budget
                        SET charged_fen=charged_fen-:refund WHERE id=1"""),
                        {"refund": row.paid_reserved_fen - actual})
                    db.execute(text("""UPDATE customer_service_model_reservations
                        SET paid_charged_fen=:actual, paid_settled_at=:now WHERE id=:id"""),
                        {"actual": actual, "now": now, "id": reservation_id})
            if latch is not None:
                raise ModelBudgetUnavailable(f"Paid model budget {latch}")
            return actual
        except SQLAlchemyError:
            raise ModelBudgetUnavailable("Shared paid accounting unavailable") from None

    def status(self) -> SpendStatus:
        try:
            with self._factory() as db:
                row = db.execute(text("SELECT * FROM customer_service_paid_budget WHERE id=1")).one_or_none()
                if row is None:
                    raise ModelBudgetUnavailable("Missing paid budget guard")
                return SpendStatus(row.state, row.attempts_committed, row.charged_fen,
                                   row.max_attempts, row.cap_fen, row.stopped_reason)
        except SQLAlchemyError:
            raise ModelBudgetUnavailable("Shared paid accounting unavailable") from None
