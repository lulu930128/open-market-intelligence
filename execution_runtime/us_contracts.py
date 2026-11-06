"""Versioned US execution values. No SDK, clock acquisition or broker IO."""

from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from execution.validation import identifier, integer, money, require
from .contracts import BrokerKey, Observation, day, decimal, digest


def us_symbol(value):
    require(type(value) is str and 0 < len(value) <= 64 and
            all(c.isascii() and (c.isalnum() or c in "._/-") for c in value), "INVALID_US_SYMBOL")


@dataclass(frozen=True)
class UsCommand:
    account_id: str
    trade_date: str  # journal scope: native uses UTC submission day, not broker business date
    request_id: str
    intent_id: str
    symbol: str
    action: str
    quantity: int
    price: str
    settlement_mode: str  # explicit TWD/MUT; distinct from USD quote currency
    environment: str
    instrument_revision: str
    schema_version: int = 2
    market: str = "US"
    trade_currency: str = "USD"
    order_type: str = "LIMIT"
    time_in_force: str = "ROD"
    session_policy: str = "REGULAR"
    space_id: str = "USER_SPACE"
    strategy_id: str | None = None
    revision: int | None = None

    # Engine vocabulary only. These are deliberately absent from the wire payload.
    condition = "CASH"
    lot = "Shares"
    shares_per_unit = 1

    @property
    def execution_id(self):
        return "exec-" + digest([self.schema_version, self.environment, self.market,
                                 self.account_id, self.intent_id])

    def validate(self):
        for name in ("account_id", "trade_date", "request_id", "intent_id", "symbol", "action", "price",
                     "settlement_mode", "environment", "instrument_revision", "market", "trade_currency",
                     "order_type", "time_in_force", "session_policy", "space_id"):
            require(type(getattr(self, name)) is str, "INVALID_US_COMMAND_FIELD")
        require(type(self.schema_version) is int and self.schema_version == 2 and self.market == "US",
                "INVALID_US_COMMAND_VERSION")
        for name in ("account_id", "request_id", "intent_id", "instrument_revision"):
            identifier(getattr(self, name))
        day(self.trade_date)
        us_symbol(self.symbol)
        integer(self.quantity, positive=True)
        require(self.action in {"Buy", "Sell"}, "UNSUPPORTED_ACTION")
        require(self.environment in {"PRODUCTION", "OFFLINE"}, "UNSUPPORTED_US_ENVIRONMENT")
        require(self.settlement_mode in {"TWD", "MUT"}, "INVALID_SETTLEMENT_MODE")
        require(self.trade_currency == "USD", "UNSUPPORTED_TRADE_CURRENCY")
        require((self.order_type, self.time_in_force, self.session_policy) == ("LIMIT", "ROD", "REGULAR"),
                "UNSUPPORTED_US_ORDER_POLICY")
        require(self.space_id == "USER_SPACE", "US_MANUAL_ONLY")
        require((self.strategy_id is None) == (self.revision is None), "STRATEGY_LINEAGE_INCOMPLETE")
        if self.strategy_id is not None:
            identifier(self.strategy_id)
            integer(self.revision, positive=True)
        require(type(self.price) is str and len(self.price) <= 64, "INVALID_LIMIT_PRICE")
        money(decimal(self.price), positive=True)


@dataclass(frozen=True)
class UsBrokerKey(BrokerKey):
    environment: str
    market: str = "US"

    def validate(self):
        super().validate()
        require(self.market == "US" and type(self.environment) is str and self.environment in {"OFFLINE", "PRODUCTION"},
                "INVALID_US_BROKER_SCOPE")


@dataclass(frozen=True)
class UsObservation(Observation):
    original_id: str = ""
    settlement_mode: str | None = None


@dataclass(frozen=True)
class UsAccountBinding:
    account_id: str = field(repr=False)
    environment: str
    trade_date: str | None = None
    report_timezone: str | None = None
    current_day: object = field(default=None, repr=False, compare=False)

    def validate(self):
        identifier(self.account_id)
        require(type(self.environment) is str and self.environment in {"OFFLINE", "PRODUCTION"}, "UNSUPPORTED_US_ENVIRONMENT")
        if self.trade_date is not None:
            day(self.trade_date)
        if self.report_timezone is not None:
            ZoneInfo(self.report_timezone)

    def date_matches(self):
        return self.trade_date is not None and (self.current_day is None or self.current_day() == self.trade_date)

    def timestamp(self, raw):
        """Never invent a timezone or business date for an unqualified report."""
        require(self.trade_date is not None and self.report_timezone is not None, "US_REPORT_TIME_UNQUALIFIED")
        require(type(raw) is str, "US_REPORT_TIME_INVALID")
        try:
            if len(raw) == 19:
                value = datetime.strptime(raw, "%Y/%m/%d %H:%M:%S")
            elif len(raw) == 6 and raw.isdigit():
                value = datetime.strptime(self.trade_date + raw, "%Y-%m-%d%H%M%S")
            elif len(raw) == 17 and raw.isdigit():
                value = datetime.strptime(raw, "%Y%m%d%H%M%S%f")
            else:
                raise ValueError()
            zone = ZoneInfo(self.report_timezone)
            first, second = value.replace(tzinfo=zone, fold=0), value.replace(tzinfo=zone, fold=1)
            require(first.utcoffset() == second.utcoffset(), "US_REPORT_TIME_AMBIGUOUS")
            return first.isoformat()
        except (ValueError, TypeError):
            raise ValueError("US_REPORT_TIME_INVALID") from None
