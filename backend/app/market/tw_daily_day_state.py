"""Taiwan instrument-day truth. Pure resolution; no acquisition or persistence.

The state is a projection of independent calendar, status, price, activity and
event evidence. Missing quotes never establish suspension or absence of trades.
"""
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Literal

from app.market_data.contracts import (
    BarObservation, CanonicalModel, InstrumentKey, InstrumentTradability,
    SourceLineage, TradingStatusObservation,
)


class TaiwanDailyState(str, Enum):
    MARKET_CLOSED = "MARKET_CLOSED"
    INSTRUMENT_SUSPENDED = "INSTRUMENT_SUSPENDED"
    TRADED_WITH_PRICE = "TRADED_WITH_PRICE"
    VERIFIED_NO_TRADE = "VERIFIED_NO_TRADE"
    TRADE_ACTIVITY_WITHOUT_PRICE = "TRADE_ACTIVITY_WITHOUT_PRICE"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    CONFLICTED_EVIDENCE = "CONFLICTED_EVIDENCE"


class TaiwanPriceBasis(CanonicalModel):
    status: Literal["unchanged", "changed", "unknown"] = "unknown"
    coverage: Literal["complete", "partial", "missing"] = "missing"
    lineage: tuple[SourceLineage, ...] = ()
    limitations: tuple[str, ...] = ("PRICE_BASIS_EVENT_COVERAGE_MISSING",)


class TaiwanDailyEvidence(CanonicalModel):
    """Qualified official daily row, including null-price activity evidence."""
    trade_date: date
    lineage: SourceLineage
    all_prices_missing: bool
    volume: Decimal | None = None
    trade_value: Decimal | None = None
    transaction_count: int | None = None

    @property
    def positive_activity(self) -> bool:
        return any(value is not None and value > 0 for value in (
            self.volume, self.trade_value, self.transaction_count))

    @property
    def zero_activity(self) -> bool:
        return all(value == 0 for value in (
            self.volume, self.trade_value, self.transaction_count))


class TaiwanDailyDayState(CanonicalModel):
    contract_version: str = "tw.daily.day_state.v1"
    instrument: InstrumentKey
    trade_date: date
    state: TaiwanDailyState
    market_open: bool | None
    instrument_status: InstrumentTradability = InstrumentTradability.UNKNOWN
    expected_session: bool
    price_basis: TaiwanPriceBasis = TaiwanPriceBasis()
    lineage: tuple[SourceLineage, ...] = ()
    blockers: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


def resolve_taiwan_daily_day_state(
    *, instrument: InstrumentKey, trade_date: date, market_open: bool | None,
    statuses: tuple[TradingStatusObservation, ...] = (),
    prices: tuple[BarObservation, ...] = (),
    daily: tuple[TaiwanDailyEvidence, ...] = (),
    price_basis: TaiwanPriceBasis | None = None,
    limitations: tuple[str, ...] = (),
) -> TaiwanDailyDayState:
    """Resolve qualified evidence for one exact identity/date, conservatively."""
    basis = price_basis or TaiwanPriceBasis()
    status_values = {item.status for item in statuses}
    status = next(iter(status_values)) if len(status_values) == 1 else InstrumentTradability.UNKNOWN
    suspended = status in {InstrumentTradability.SUSPENDED, InstrumentTradability.HALTED}
    activity = any(item.positive_activity for item in daily)
    zero = any(item.all_prices_missing and item.zero_activity for item in daily)
    invalid_activity = any(value is not None and value < 0 for item in daily
                           for value in (item.volume, item.trade_value, item.transaction_count))
    price_values = {(p.open_price, p.high_price, p.low_price, p.close_price) for p in prices}
    conflict = (len(status_values) > 1 or len(price_values) > 1 or invalid_activity
                or (zero and (activity or bool(prices)))
                or ((market_open is False or suspended) and (activity or bool(prices))))
    blockers: tuple[str, ...] = ()
    if conflict:
        state = TaiwanDailyState.CONFLICTED_EVIDENCE
        blockers = ("OFFICIAL_EVIDENCE_CONFLICT",)
    elif market_open is False:
        state = TaiwanDailyState.MARKET_CLOSED
    elif market_open is None:
        state = TaiwanDailyState.MISSING_EVIDENCE
        blockers = ("MARKET_CALENDAR_COVERAGE_UNKNOWN",)
    elif suspended:
        state = TaiwanDailyState.INSTRUMENT_SUSPENDED
    elif prices:
        state = TaiwanDailyState.TRADED_WITH_PRICE
    elif activity:
        state = TaiwanDailyState.TRADE_ACTIVITY_WITHOUT_PRICE
        blockers = ("ALTERNATE_OFFICIAL_PRICE_REQUIRED",)
    elif zero:
        state = TaiwanDailyState.VERIFIED_NO_TRADE
        if basis.status != "unchanged" or basis.coverage != "complete":
            blockers = ("PRICE_BASIS_CHANGED" if basis.status == "changed"
                        else "PRICE_BASIS_EVENT_COVERAGE_REQUIRED",)
    else:
        state = TaiwanDailyState.MISSING_EVIDENCE
        blockers = ("OFFICIAL_DAILY_EVIDENCE_REQUIRED",)
        if status is InstrumentTradability.UNKNOWN:
            blockers += ("HISTORICAL_INSTRUMENT_STATUS_UNKNOWN",)
    lineage = tuple(dict.fromkeys(item.model_dump_json() for item in (
        *(item.lineage for item in statuses), *(item.lineage for item in prices),
        *(item.lineage for item in daily), *basis.lineage)))
    return TaiwanDailyDayState(
        instrument=instrument, trade_date=trade_date, state=state,
        market_open=market_open, instrument_status=status,
        expected_session=state not in {TaiwanDailyState.MARKET_CLOSED, TaiwanDailyState.INSTRUMENT_SUSPENDED},
        price_basis=basis, lineage=tuple(SourceLineage.model_validate_json(item) for item in lineage),
        blockers=blockers, limitations=limitations,
    )
