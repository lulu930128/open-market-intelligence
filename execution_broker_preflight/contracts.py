"""Versioned fixture boundary. These types are not M1 or broker contracts."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum


class Action(Enum):
    BUY = "BUY"
    SELL = "SELL"


class Intent(Enum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"


class Funding(Enum):
    CASH = "CASH"
    MARGIN = "MARGIN"
    CREDIT_SHORT = "CREDIT_SHORT"
    BORROWED_SHORT = "BORROWED_SHORT"
    CASH_FIRST_SELL = "CASH_FIRST_SELL"


class PriceKind(Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


class TimeInForce(Enum):
    ROD = "ROD"
    IOC = "IOC"
    FOK = "FOK"


class Lot(Enum):
    BOARD = "Common"
    ODD = "Odd"
    AFTER_ODD = "Odd_AfterMarket"
    FIXING = "Fixing"


class Session(Enum):
    OPEN_AUCTION = "OPEN_AUCTION"
    CONTINUOUS = "CONTINUOUS"
    CLOSE_AUCTION = "CLOSE_AUCTION"
    ODD = "ODD"
    CLOSED = "CLOSED"


class Proof(Enum):
    UNKNOWN = "UNKNOWN"
    DENIED = "DENIED"
    SYNTHETIC_VERIFIED = "SYNTHETIC_VERIFIED"


@dataclass(frozen=True)
class Scope:
    entity: str
    account: str
    subaccount: str
    currency: str
    venue: str
    symbol: str


@dataclass(frozen=True)
class ApprovedOrderFixture:
    scope: Scope
    request_id: str
    action: Action
    intent: Intent
    funding: Funding
    price_kind: PriceKind
    time_in_force: TimeInForce
    lot: Lot
    shares: int
    price: Decimal | str
    approved: bool = False
    schema: str = "omi.kgi.preflight.order-fixture.v1"
    mode: str = "SYNTHETIC"


@dataclass(frozen=True)
class RiskFixture:
    scope: Scope
    observed_at: datetime
    expires_at: datetime
    session: Session
    # Required independently; UNKNOWN never implies permission.
    account_enabled: Proof = Proof.UNKNOWN
    api_agreement: Proof = Proof.UNKNOWN
    ca_certificate: Proof = Proof.UNKNOWN
    entitlement: Proof = Proof.UNKNOWN
    sdk_compatibility: Proof = Proof.UNKNOWN
    session_coexistence: Proof = Proof.UNKNOWN
    instrument_tradable: Proof = Proof.UNKNOWN
    risk_limits: Proof = Proof.UNKNOWN
    tick_and_price_bounds: Proof = Proof.UNKNOWN
    position_or_credit: Proof = Proof.UNKNOWN
    collateral_settlement: Proof = Proof.UNKNOWN
    short_eligibility: Proof = Proof.UNKNOWN
    borrow_allocation: Proof = Proof.UNKNOWN
    credit_terms: Proof = Proof.UNKNOWN
    has_price_limit: bool | None = None
    extended_matching: bool | None = None
    short_below_reference_allowed: bool | None = None
    short_reference: Decimal | None = None
    mode: str = "SYNTHETIC"


@dataclass(frozen=True)
class UnitConversionFixture:
    scope: Scope
    lot: Lot
    shares_per_sdk_qty: int
    board_shares: int
    evidence_id: str
    sdk_version: str
    verification: Proof = Proof.UNKNOWN
    mode: str = "SYNTHETIC"


def nonempty(value: object) -> bool:
    return type(value) is str and bool(value.strip())


def positive_int(value: object) -> bool:
    return type(value) is int and value > 0


def positive_decimal(value: object) -> bool:
    return type(value) is Decimal and value.is_finite() and value > 0


def aware(value: object) -> bool:
    return type(value) is datetime and value.tzinfo is not None and value.utcoffset() is not None


def valid_scope(value: object) -> bool:
    return type(value) is Scope and all(nonempty(v) for v in (
        value.entity, value.account, value.subaccount, value.currency, value.symbol,
    )) and value.venue in ("TWSE", "TPEX")
