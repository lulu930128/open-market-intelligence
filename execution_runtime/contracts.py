"""Broker execution values, separate from M1 synthetic admission contracts."""

from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json

from execution.validation import identifier, integer, require


def encoded(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def digest(value: object) -> str:
    return hashlib.sha256(encoded(value).encode("utf-8")).hexdigest()


def decimal(value: object) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("INVALID_BROKER_NUMBER") from None
    require(result.is_finite(), "INVALID_BROKER_NUMBER")
    return result


def day(value: str) -> str:
    require(type(value) is str, "INVALID_TRADE_DATE")
    parsed = date.fromisoformat(value)
    require(parsed.isoformat() == value, "INVALID_TRADE_DATE")
    return value


@dataclass(frozen=True)
class Command:
    account_id: str
    trade_date: str
    request_id: str
    intent_id: str
    symbol: str
    action: str
    quantity: int  # shares throughout the execution application
    price: str
    condition: str = "CASH"
    lot: str = "Odd"
    shares_per_unit: int = 1
    space_id: str = "USER_SPACE"
    strategy_id: str | None = None  # opaque lineage, never strategy rules
    revision: int | None = None

    @property
    def execution_id(self) -> str:
        return "exec-" + digest([self.account_id, self.intent_id])

    def validate(self) -> None:
        for value in (self.account_id, self.request_id, self.intent_id, self.symbol):
            identifier(value)
        day(self.trade_date)
        require(self.space_id in {"USER_SPACE", "AGENT_SPACE"}, "INVALID_SPACE")
        if self.strategy_id is not None:
            identifier(self.strategy_id)
        if self.revision is not None:
            integer(self.revision, positive=True)
        integer(self.quantity, positive=True)
        integer(self.shares_per_unit, positive=True)
        require(self.lot in {"Odd", "Common"}, "UNSUPPORTED_LOT")
        require(self.lot != "Odd" or self.shares_per_unit == 1, "ODD_UNIT_MISMATCH")
        require(self.quantity % self.shares_per_unit == 0, "QUANTITY_UNIT_MISMATCH")
        require(self.action in {"Buy", "Sell"}, "UNSUPPORTED_ACTION")
        require(self.condition in {"CASH", "MARGIN", "CASH_SELLING", "SHORT_SELLING"},
                "UNSUPPORTED_CONDITION")
        require(self.condition == "CASH" or self.lot == "Common", "UNSUPPORTED_CREDIT_LOT")
        require(self.condition != "MARGIN" or self.action == "Buy" or self.strategy_id is not None, "UNQUALIFIED_MARGIN_SIDE")
        require(self.condition != "CASH_SELLING" or self.action == "Sell", "UNQUALIFIED_SHORT_SIDE")
        require(self.condition != "SHORT_SELLING" or self.action == "Sell" or self.strategy_id is not None,
                "UNQUALIFIED_SHORT_SIDE")
        require(type(self.price) is str and decimal(self.price) > 0, "INVALID_LIMIT_PRICE")


@dataclass(frozen=True)
class BrokerKey:
    account_id: str
    trade_date: str
    order_id: str

    def validate(self) -> None:
        identifier(self.account_id)
        identifier(self.order_id)
        day(self.trade_date)

    @property
    def identity(self) -> str:
        return digest(asdict(self))


@dataclass(frozen=True)
class Observation:
    key: BrokerKey
    kind: str
    source: str
    source_time: str
    symbol: str
    action: str
    condition: str
    lot: str
    seqno: str = ""
    quantity: int | None = None  # SDK units; Deal is delta, NewOrder is original
    price: str | None = None
    remaining: int | None = None
    channel: str | None = None
    cumulative: int | None = None
    broker_status: str | None = None

    def payload(self) -> dict:
        return asdict(self)

    @property
    def event_id(self) -> str:
        return digest(self.payload())


def observation_from(payload: dict) -> Observation:
    from .us_contracts import UsObservation
    kind = UsObservation if payload["key"].get("market") == "US" else Observation
    return kind(**{**payload, "key": broker_key_from(payload["key"])})


def command_from(payload: dict):
    """Old TW bytes retain their original codec and identity."""
    from .us_contracts import UsCommand
    require(type(payload) is dict, "INVALID_COMMAND")
    try:
        result = UsCommand(**payload) if "schema_version" in payload else Command(**payload)
    except TypeError:
        raise ValueError("INVALID_COMMAND_FIELDS") from None
    result.validate()
    return result


def command_payload(command):
    """Keep legacy US command bytes stable when no protection was attached."""
    result = asdict(command)
    if result.get("market") == "US" and result.get("strategy_id") is None:
        result.pop("strategy_id", None)
        result.pop("revision", None)
    return result


def broker_key_from(payload: dict):
    from .us_contracts import UsBrokerKey
    result = UsBrokerKey(**payload) if "market" in payload else BrokerKey(**payload)
    result.validate()
    return result


@dataclass(frozen=True)
class ReportDiagnostic:
    """Quarantined row evidence, never an order/fill fact or a synthetic key."""

    source: str
    row_index: int  # zero-based within this source's query response
    reason: str
    fields: dict[str, str | None]  # allowlisted raw cells, rendered as in v2.7
    account_matches: bool | None  # None: supplied account cell is unreadable
    trade_date: str | None  # None preserves unknown date, not the session date

    def may_affect(self, key: BrokerKey) -> bool:
        # An unreadable date cannot exonerate a matching order number. A known
        # different account/day cannot contaminate this order's reconciliation.
        return (self.account_matches is not False and self.fields.get("OrderNo") == key.order_id
                and self.trade_date in {None, key.trade_date})


@dataclass(frozen=True)
class SourceRead:
    source: str
    status: str
    row_count: int | None = None
    reason: str | None = None


@dataclass(frozen=True)
class QueryBatch:
    observations: tuple[Observation, ...]
    cached_keys: frozenset[BrokerKey]
    invalid_trade_count: int
    snapshots: tuple[Observation, ...] = ()
    # Neither Account.OrderReport nor the SDK cache proves complete fill history.
    fill_history_complete: bool = False
    diagnostics: tuple[ReportDiagnostic, ...] = ()
    sources: tuple[SourceRead, ...] = ()
    us_order_totals: tuple[dict, ...] = ()


def parse_stamp(day_value: str, value: object) -> str:
    raw = str(value)
    require(len(raw) == 6 and raw.isdigit(), "BROKER_TIME_UNAVAILABLE")
    try:
        datetime.strptime(day_value + raw, "%Y-%m-%d%H%M%S")
    except ValueError:
        raise ValueError("BROKER_TIME_INVALID") from None
    return raw
