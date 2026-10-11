"""Immutable M1 contracts. Quantities are shares, never a number of lots."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum


class Market(str, Enum):
    TW = "TW"


class Asset(str, Enum):
    CASH_STOCK = "CASH_STOCK"
    ETF = "ETF"


class Venue(str, Enum):
    TWSE = "TWSE"
    TPEX = "TPEX"


class Lot(str, Enum):
    BOARD = "BOARD"
    ODD = "ODD"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderKind(str, Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


class Funding(str, Enum):
    CASH = "CASH"
    MARGIN = "MARGIN"
    SHORT_SELLING = "SHORT_SELLING"
    LEND_SELLING = "LEND_SELLING"


class PositionAction(str, Enum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"


class TradingPhase(str, Enum):
    MARKET_CONTINUOUS = "market_continuous"
    OPENING_AUCTION = "opening_auction"
    CLOSING_AUCTION = "closing_auction"
    ODD_LOT_AUCTION = "odd_lot_auction"
    UNKNOWN = "unknown"


class Capability(str, Enum):
    ALLOWED = "ALLOWED"
    DENIED = "DENIED"
    UNVERIFIED = "UNVERIFIED"


class TimeInForce(str, Enum):
    DAY = "DAY"


class Currency(str, Enum):
    TWD = "TWD"


class PriceUnit(str, Enum):
    PER_SHARE = "PER_SHARE"


class Origin(str, Enum):
    SYNTHETIC = "SYNTHETIC"


@dataclass(frozen=True)
class Instrument:
    market: Market
    symbol: str
    asset: Asset
    venue: Venue


@dataclass(frozen=True)
class Draft:
    instrument: Instrument
    account_id: str
    client_request_id: str
    side: Side
    quantity: int
    lot: Lot
    limit_price: Decimal | None
    currency: Currency = Currency.TWD
    price_unit: PriceUnit = PriceUnit.PER_SHARE
    order_kind: OrderKind = OrderKind.LIMIT
    funding: Funding = Funding.CASH
    time_in_force: TimeInForce = TimeInForce.DAY
    contract_version: int = field(default=1, metadata={"additive": True})
    position_action: PositionAction | None = field(default=None, metadata={"additive": True})
    simulated: bool = field(default=True, init=False, metadata={"additive": True})
    broker_connected: bool = field(default=False, init=False, metadata={"additive": True})
    test_only: bool = field(default=True, init=False, metadata={"additive": True})


@dataclass(frozen=True)
class EvidenceRef:
    snapshot_id: str
    owner: str
    observed_at: datetime
    valid_from: datetime
    valid_until: datetime
    origin: Origin = Origin.SYNTHETIC
    received_at: datetime | None = field(default=None, metadata={"additive": True})


@dataclass(frozen=True)
class TickBand:
    lower: Decimal  # Inclusive; prices must be exact multiples of tick from zero.
    upper: Decimal  # Exclusive.
    tick: Decimal


@dataclass(frozen=True)
class LotRule:
    board_size: int
    minimum: int
    maximum: int
    step: int


@dataclass(frozen=True)
class MarketTradePolicy:
    ref: EvidenceRef
    version: str
    instrument: Instrument
    lot: Lot
    session_id: str
    market_snapshot_id: str
    phase: TradingPhase
    authoritative_session: bool
    regular_security: bool
    market_orders: Capability
    margin: Capability
    short_selling: Capability
    lend_selling: Capability
    short_below_reference: bool
    reference_price: Decimal


@dataclass(frozen=True)
class CreditFacts:
    ref: EvidenceRef
    version: str
    account_id: str
    account_snapshot_id: str
    instrument: Instrument
    currency: Currency
    authenticated: bool
    available_credit: Decimal
    available_collateral: Decimal  # Separate from available_cash; no double counting.
    margin_cash_ratio: Decimal
    short_collateral_ratio: Decimal
    maintenance_ratio: Decimal
    minimum_maintenance_ratio: Decimal
    short_borrow_available: int
    lend_borrow_available: int
    margin_position: int
    short_position: int
    lend_position: int


@dataclass(frozen=True)
class MarketFacts:
    ref: EvidenceRef
    instrument: Instrument
    lot: Lot
    currency: Currency
    price_unit: PriceUnit
    session_id: str
    order_entry_open: bool
    tradable: bool
    tick_bands: tuple[TickBand, ...]
    minimum_price: Decimal
    maximum_price: Decimal
    lot_rule: LotRule
    trade_policy: MarketTradePolicy | None = field(default=None, metadata={"additive": True})


@dataclass(frozen=True)
class AccountFacts:
    ref: EvidenceRef
    account_id: str
    instrument: Instrument
    currency: Currency
    available_cash: Decimal
    sellable_quantity: int
    active: bool
    credit: CreditFacts | None = field(default=None, metadata={"additive": True})


@dataclass(frozen=True)
class PermissionFacts:
    ref: EvidenceRef
    principal_id: str
    account_id: str
    instrument: Instrument
    allowed_sides: frozenset[Side]
    allowed_lots: frozenset[Lot]
    can_trade: bool
    maximum_quantity: int
    maximum_notional: Decimal
    buy_fee_reserve: Decimal  # Supplied fixture amount; not a live fee calculator.
    allowed_funding: frozenset[Funding] = field(default=frozenset(), metadata={"additive": True})
    authenticated: bool = field(default=False, metadata={"additive": True})
    maximum_intraday_risk: Decimal | None = field(default=None, metadata={"additive": True})
    used_intraday_risk: Decimal | None = field(default=None, metadata={"additive": True})


@dataclass(frozen=True)
class Evidence:
    market: MarketFacts
    account: AccountFacts
    permission: PermissionFacts


@dataclass(frozen=True)
class ResourceRequirements:
    credit: Decimal = Decimal(0)
    collateral: Decimal = Decimal(0)
    short_borrow: int = 0
    lend_borrow: int = 0
    margin_position: int = 0
    short_position: int = 0
    lend_position: int = 0
    sellable: int = 0
    risk_notional: Decimal = Decimal(0)
    proceeds_floor: Decimal = Decimal(0)
    price_floor: Decimal = Decimal(0)
    price_ceiling: Decimal = Decimal(0)


@dataclass(frozen=True)
class Assessment:
    notional: Decimal
    required_cash: Decimal
    valid_until: datetime
    resources: ResourceRequirements | None = field(default=None, metadata={"additive": True})


@dataclass(frozen=True)
class Challenge:
    token: str
    digest: str
    principal_id: str
    expires_at: datetime
    action: str = field(default="CONFIRM_SYNTHETIC_DRY_RUN", init=False)


@dataclass(frozen=True)
class Preview:
    preview_id: str
    draft: Draft
    evidence: Evidence
    assessment: Assessment
    created_at: datetime
    challenge: Challenge
    simulated: bool = field(default=True, init=False)
    broker_connected: bool = field(default=False, init=False, metadata={"additive": True})
    test_only: bool = field(default=True, init=False, metadata={"additive": True})


@dataclass(frozen=True)
class Confirmation:
    preview_id: str
    token: str
    digest: str
    principal_id: str
    user_confirmed: bool


class State(str, Enum):
    PREVIEWED = "PREVIEWED"
    SIMULATED_PENDING = "SIMULATED_PENDING"
    SIMULATED_ACCEPTED = "SIMULATED_ACCEPTED"
    SIMULATED_PARTIALLY_FILLED = "SIMULATED_PARTIALLY_FILLED"
    SIMULATED_FILLED = "SIMULATED_FILLED"
    SIMULATED_REJECTED = "SIMULATED_REJECTED"
    CANCEL_PENDING = "CANCEL_PENDING"
    SIMULATED_CANCELLED = "SIMULATED_CANCELLED"
    UNKNOWN = "UNKNOWN"
    RECONCILING = "RECONCILING"


class EventKind(str, Enum):
    ACCEPTED = "ACCEPTED"
    PARTIAL_FILL = "PARTIAL_FILL"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    RECONCILE = "RECONCILE"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"


@dataclass(frozen=True)
class SimulationEvent:
    event_id: str
    preview_id: str
    kind: EventKind
    occurred_at: datetime
    sequence: int | None = None  # Required for fixture reports, absent for controls.
    cumulative_filled: int = 0
    fill_price: Decimal | None = field(default=None, metadata={"additive": True})
    simulated: bool = field(default=True, init=False)
    broker_connected: bool = field(default=False, init=False, metadata={"additive": True})
    test_only: bool = field(default=True, init=False, metadata={"additive": True})


@dataclass(frozen=True)
class OrderState:
    preview_id: str
    quantity: int
    state: State
    confirmed_at: datetime | None
    cumulative_filled: int = 0
    last_report_sequence: int = 0
    last_report_at: datetime | None = None
    cancel_requested: bool = False
    events: tuple[SimulationEvent, ...] = ()


@dataclass(frozen=True)
class DryRunResult:
    preview_id: str
    client_request_id: str
    state: State
    cumulative_filled: int
    simulation_attempts: int
    cancel_requested: bool
    simulated: bool = field(default=True, init=False)
    durable: bool = field(default=False, init=False)
    broker_connected: bool = field(default=False, init=False, metadata={"additive": True})
    test_only: bool = field(default=True, init=False, metadata={"additive": True})


@dataclass(frozen=True)
class AuditEvent:
    sequence: int
    occurred_at: datetime
    operation: str
    preview_id: str | None
    digest: str | None
    state: State | None
    reason: str
    event: SimulationEvent | None = None
    simulated: bool = field(default=True, init=False)


class ExecutionRejected(ValueError):
    """Stable machine-readable rejection; does not echo account or token values."""

    def __init__(self, code: str, *, outcome: Capability = Capability.DENIED):
        self.code = code
        self.outcome = outcome
        super().__init__(code)
