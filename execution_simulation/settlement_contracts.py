"""Explicit fictional settlement evidence; no broker or real billing semantics."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from execution.contracts import Currency, Instrument, Origin


@dataclass(frozen=True)
class FillLot:
    event_id: str
    preview_id: str
    shares: int  # Delta, never cumulative quantity.
    executed_price: Decimal
    occurred_at: datetime


@dataclass(frozen=True)
class FeeSchedule:
    evidence_id: str
    version: str
    valid_from: datetime
    valid_until: datetime
    currency: Currency
    commission_rate: Decimal
    sale_levy_rate: Decimal
    borrow_open_rate: Decimal
    money_quantum: Decimal
    rounding: str
    origin: Origin = Origin.SYNTHETIC


@dataclass(frozen=True)
class InterestPolicy:
    evidence_id: str
    version: str
    valid_from: datetime
    valid_until: datetime
    currency: Currency
    financing_rate_per_second: Decimal
    borrow_rate_per_second: Decimal
    maximum_period_seconds: int
    money_quantum: Decimal
    rounding: str
    origin: Origin = Origin.SYNTHETIC


@dataclass(frozen=True)
class SettlementReceipt:
    event_id: str
    version: str
    preview_id: str
    account_id: str
    session_id: str
    currency: Currency
    instrument: Instrument
    preview_digest: str
    order_digest: str
    fills_digest: str
    valid_from: datetime
    valid_until: datetime
    eligible_at: datetime
    no_outstanding_late_fills: bool
    opening_preview_id: str | None = None
    lender_ack_id: str | None = None
    origin: Origin = Origin.SYNTHETIC


@dataclass(frozen=True)
class AccrualTick:
    event_id: str
    opening_preview_id: str
    period_start: datetime
    period_end: datetime


@dataclass(frozen=True)
class RestrictionEvidence:
    event_id: str
    account_id: str
    reason: str  # MAINTENANCE_UNVERIFIED / MARGIN_CALL / BORROW_RECALL
    occurred_at: datetime
