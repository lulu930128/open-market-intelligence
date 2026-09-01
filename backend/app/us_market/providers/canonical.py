"""Pure canonical conversion for already-acquired US provider payloads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from app.market_data.contracts import (
    AuthorityClass,
    BarFinalization,
    BarObservation,
    CanonicalMarketSnapshot,
    InstrumentKey,
    InstrumentType,
    Market,
    MarketSession,
    MarketSessionContext,
    ObservationState,
    Quantity,
    QuantityUnit,
    QuoteObservation,
    SourceLineage,
    TradeObservationState,
)
from app.us_market.trading_calendar import (
    us_post_market_close_time,
    us_session_close_time,
)
from app.us_market.volume_semantics import normalize_yahoo_intraday_volume


US_EASTERN = ZoneInfo("America/New_York")
_INTERVAL_DURATION = {
    "1m": timedelta(minutes=1),
    "1d": timedelta(days=1),
}
_TWELVE_INTERVALS = {
    "1min": ("1m", timedelta(minutes=1)),
    "5min": ("5m", timedelta(minutes=5)),
    "15min": ("15m", timedelta(minutes=15)),
    "30min": ("30m", timedelta(minutes=30)),
    "45min": ("45m", timedelta(minutes=45)),
    "1h": ("1h", timedelta(hours=1)),
}


@dataclass(frozen=True, slots=True)
class CanonicalUSMarketData:
    instrument: InstrumentKey
    provider: str
    interval: str
    price_basis: str
    snapshot: CanonicalMarketSnapshot | None
    bars: tuple[BarObservation, ...]
    skipped_bar_count: int = 0
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.instrument.market is not Market.US:
            raise ValueError("canonical US market data requires a US instrument")
        if self.snapshot is not None and self.snapshot.instrument != self.instrument:
            raise ValueError("snapshot identity does not match the canonical batch")
        if any(bar.instrument != self.instrument for bar in self.bars):
            raise ValueError("bar identity does not match the canonical batch")
        if any(bar.interval != self.interval for bar in self.bars):
            raise ValueError("bar interval does not match the canonical batch")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _value(values: Any, index: int) -> Any:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return None
    return values[index] if 0 <= index < len(values) else None


def _positive_ohlc(
    open_value: Any,
    high_value: Any,
    low_value: Any,
    close_value: Any,
) -> tuple[Decimal, Decimal, Decimal, Decimal] | None:
    values = tuple(_decimal(value) for value in (open_value, high_value, low_value, close_value))
    if any(value is None or value <= 0 for value in values):
        return None
    open_price, high_price, low_price, close_price = values
    if high_price < max(open_price, low_price, close_price):
        return None
    if low_price > min(open_price, high_price, close_price):
        return None
    return open_price, high_price, low_price, close_price


def us_session_for_timestamp(value: datetime) -> MarketSession:
    """Map a US timestamp to the shared cross-market session vocabulary."""

    _require_aware(value, "session timestamp")
    local = value.astimezone(US_EASTERN)
    wall = local.timetz().replace(tzinfo=None)
    session_close = us_session_close_time(local.date())
    post_market_close = us_post_market_close_time(local.date())
    closing_auction_end = (
        datetime.combine(local.date(), session_close) + timedelta(minutes=1)
    ).time()
    if time(4, 0) <= wall < time(9, 30):
        return MarketSession.PRE_OPEN
    if time(9, 30) <= wall < session_close:
        return MarketSession.CONTINUOUS
    if session_close <= wall < closing_auction_end:
        return MarketSession.CLOSING_AUCTION
    if closing_auction_end <= wall < post_market_close:
        return MarketSession.POST_CLOSE
    return MarketSession.CLOSED


def _session_in_scope(session: MarketSession, session_scope: str) -> bool:
    if session_scope == "all":
        return session in {
            MarketSession.PRE_OPEN,
            MarketSession.CONTINUOUS,
            MarketSession.CLOSING_AUCTION,
            MarketSession.POST_CLOSE,
        }
    if session_scope == "extended":
        return session in {MarketSession.PRE_OPEN, MarketSession.POST_CLOSE}
    if session_scope == "regular":
        return session in {
            MarketSession.CONTINUOUS,
            MarketSession.CLOSING_AUCTION,
        }
    raise ValueError("session_scope must be one of: regular, extended, all")


def _lineage(
    *,
    provider: str,
    source: str,
    event_at: datetime,
    fetched_at: datetime,
    raw_contract_version: str,
) -> SourceLineage:
    return SourceLineage(
        provider=provider,
        source=source,
        authority=AuthorityClass.VENDOR,
        raw_contract_version=raw_contract_version,
        event_at=event_at,
        fetched_at=fetched_at,
    )


def _quantity(value: Any) -> Quantity | None:
    parsed = _decimal(value)
    if parsed is None or parsed < 0:
        return None
    return Quantity(value=parsed, unit=QuantityUnit.SHARE)


def _snapshot_from_bars(
    *,
    instrument: InstrumentKey,
    bars: tuple[BarObservation, ...],
    previous_close: Decimal | None,
    currency: str | None,
) -> CanonicalMarketSnapshot | None:
    if not bars:
        return None
    latest = bars[-1]
    session = (
        MarketSession.POST_CLOSE
        if latest.interval == "1d"
        else us_session_for_timestamp(latest.start_at)
    )
    quote = QuoteObservation(
        instrument=instrument,
        lineage=latest.lineage,
        trade_date=latest.start_at.astimezone(US_EASTERN).date(),
        currency=currency,
        state=ObservationState.AVAILABLE,
        trade_state=TradeObservationState.TRADE_OBSERVED,
        last_trade_price=latest.close_price,
        open_price=latest.open_price,
        high_price=latest.high_price,
        low_price=latest.low_price,
        previous_close=previous_close,
    )
    return CanonicalMarketSnapshot(
        instrument=instrument,
        session=MarketSessionContext(
            market=Market.US,
            session=session,
            observed_at=latest.lineage.event_at or latest.end_at,
            trade_date=quote.trade_date,
        ),
        quote=quote,
    )


def canonical_yahoo_chart_payload(
    *,
    instrument: InstrumentKey,
    payload: Mapping[str, Any],
    fetched_at: datetime,
    interval: str,
    session_scope: str = "all",
    provider_symbol: str | None = None,
) -> CanonicalUSMarketData:
    """Convert one already-acquired Yahoo chart payload without IO or persistence."""

    if instrument.market is not Market.US:
        raise ValueError("Yahoo US adapter requires a US instrument")
    _require_aware(fetched_at, "fetched_at")
    duration = _INTERVAL_DURATION.get(interval)
    if duration is None:
        raise ValueError("Yahoo canonical adapter supports only 1m and 1d")
    result_rows = payload.get("chart", {}).get("result") if isinstance(payload, Mapping) else None
    result = result_rows[0] if isinstance(result_rows, list) and result_rows else None
    if not isinstance(result, Mapping):
        raise ValueError("Yahoo chart payload has no result")
    meta = result.get("meta") if isinstance(result.get("meta"), Mapping) else {}
    expected_symbol = str(provider_symbol or instrument.symbol).strip().upper()
    payload_symbol = str(meta.get("symbol") or expected_symbol).strip().upper()
    if payload_symbol != expected_symbol:
        raise ValueError("Yahoo payload symbol does not match the provider symbol")
    timestamps = result.get("timestamp")
    indicators = result.get("indicators")
    quote_rows = indicators.get("quote") if isinstance(indicators, Mapping) else None
    quote = quote_rows[0] if isinstance(quote_rows, list) and quote_rows else None
    if not isinstance(timestamps, list) or not isinstance(quote, Mapping):
        raise ValueError("Yahoo chart payload has no timestamp/quote series")

    bars: list[BarObservation] = []
    minute_bars: dict[datetime, tuple[datetime, BarObservation]] = {}
    skipped = 0
    extended_zero_volume_count = 0
    duplicate_minute_count = 0
    for index, raw_timestamp in enumerate(timestamps):
        try:
            provider_event_at = datetime.fromtimestamp(
                int(raw_timestamp),
                tz=US_EASTERN,
            )
        except (OSError, OverflowError, TypeError, ValueError):
            skipped += 1
            continue
        start_at = (
            provider_event_at.replace(second=0, microsecond=0)
            if interval == "1m"
            else provider_event_at
        )
        session = (
            MarketSession.POST_CLOSE
            if interval == "1d"
            else us_session_for_timestamp(start_at)
        )
        if interval == "1m" and not _session_in_scope(session, session_scope):
            continue
        ohlc = _positive_ohlc(
            _value(quote.get("open"), index),
            _value(quote.get("high"), index),
            _value(quote.get("low"), index),
            _value(quote.get("close"), index),
        )
        if ohlc is None:
            skipped += 1
            continue
        if interval == "1d":
            trade_date = start_at.astimezone(US_EASTERN).date()
            start_at = datetime.combine(trade_date, time(9, 30), tzinfo=US_EASTERN)
            end_at = datetime.combine(
                trade_date,
                us_session_close_time(trade_date),
                tzinfo=US_EASTERN,
            )
        else:
            end_at = start_at + duration
        finalization = (
            BarFinalization.FINAL
            if fetched_at.astimezone(US_EASTERN) >= end_at
            else BarFinalization.PROVISIONAL
        )
        open_price, high_price, low_price, close_price = ohlc
        raw_volume = _value(quote.get("volume"), index)
        daily_index_volume_not_applicable = bool(
            interval == "1d"
            and instrument.instrument_type is InstrumentType.INDEX
        )
        parsed_volume = (
            None
            if daily_index_volume_not_applicable
            else _quantity(raw_volume)
        )
        if interval == "1m":
            normalized_volume, volume_status = normalize_yahoo_intraday_volume(
                int(parsed_volume.value) if parsed_volume is not None else None,
                session=(
                    "pre_market"
                    if session is MarketSession.PRE_OPEN
                    else "after_hours"
                    if session is MarketSession.POST_CLOSE
                    else "regular"
                ),
            )
            if volume_status == "provider_unavailable":
                extended_zero_volume_count += 1
            parsed_volume = _quantity(normalized_volume)
        bar = BarObservation(
            instrument=instrument,
            lineage=_lineage(
                provider="yahoo_chart",
                source=f"yahoo.chart.{interval}",
                event_at=(provider_event_at if interval == "1m" else end_at),
                fetched_at=fetched_at,
                raw_contract_version="yahoo.chart.v8",
            ),
            interval=interval,
            start_at=start_at,
            end_at=end_at,
            open_price=open_price,
            high_price=high_price,
            low_price=low_price,
            close_price=close_price,
            volume=parsed_volume,
            volume_status=(
                "not_applicable"
                if daily_index_volume_not_applicable
                else "observed"
                if parsed_volume is not None
                else "missing"
            ),
            price_basis="raw",
            finalization=finalization,
        )
        if interval == "1m":
            existing = minute_bars.get(start_at)
            if existing is not None:
                duplicate_minute_count += 1
            if existing is None or provider_event_at >= existing[0]:
                minute_bars[start_at] = (provider_event_at, bar)
        else:
            bars.append(bar)
    if interval == "1m":
        bars.extend(bar for _, bar in minute_bars.values())
    bars.sort(key=lambda item: item.start_at)
    limitations = tuple(
        code
        for code, present in (
            ("MALFORMED_BARS_SKIPPED", skipped > 0),
            (
                "YAHOO_DUPLICATE_MINUTE_BARS_DEDUPLICATED",
                duplicate_minute_count > 0,
            ),
            (
                "YAHOO_EXTENDED_VOLUME_ZERO_FILLED",
                extended_zero_volume_count > 0,
            ),
        )
        if present
    )
    canonical_bars = tuple(bars)
    currency = str(meta.get("currency") or "USD").strip().upper()
    previous_close = _decimal(meta.get("chartPreviousClose") or meta.get("previousClose"))
    return CanonicalUSMarketData(
        instrument=instrument,
        provider="yahoo_chart",
        interval=interval,
        price_basis="raw",
        snapshot=_snapshot_from_bars(
            instrument=instrument,
            bars=canonical_bars,
            previous_close=previous_close,
            currency=currency,
        ),
        bars=canonical_bars,
        skipped_bar_count=skipped,
        limitations=limitations,
    )


def canonical_alphavantage_daily_payload(
    *,
    instrument: InstrumentKey,
    payload: Mapping[str, Any],
    fetched_at: datetime,
    provider_symbol: str | None = None,
) -> CanonicalUSMarketData:
    """Convert one already-acquired Alpha Vantage daily payload."""

    if instrument.market is not Market.US:
        raise ValueError("Alpha Vantage US adapter requires a US instrument")
    _require_aware(fetched_at, "fetched_at")
    metadata = payload.get("Meta Data")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    expected_symbol = str(provider_symbol or instrument.symbol).strip().upper()
    payload_symbol = str(metadata.get("2. Symbol") or expected_symbol).strip().upper()
    if payload_symbol != expected_symbol:
        raise ValueError("Alpha Vantage payload symbol does not match the provider symbol")
    series_key = next(
        (
            key
            for key, value in payload.items()
            if str(key).startswith("Time Series (Daily)") and isinstance(value, Mapping)
        ),
        None,
    )
    if series_key is None:
        raise ValueError("Alpha Vantage payload has no daily time series")
    series = payload[series_key]
    bars: list[BarObservation] = []
    skipped = 0
    adjusted_available = False
    for raw_date, row in series.items():
        if not isinstance(row, Mapping):
            skipped += 1
            continue
        try:
            trade_date = date.fromisoformat(str(raw_date))
        except ValueError:
            skipped += 1
            continue
        ohlc = _positive_ohlc(
            row.get("1. open"),
            row.get("2. high"),
            row.get("3. low"),
            row.get("4. close"),
        )
        if ohlc is None:
            skipped += 1
            continue
        adjusted_available = adjusted_available or _decimal(row.get("5. adjusted close")) is not None
        start_at = datetime.combine(trade_date, time(9, 30), tzinfo=US_EASTERN)
        end_at = datetime.combine(
            trade_date,
            us_session_close_time(trade_date),
            tzinfo=US_EASTERN,
        )
        open_price, high_price, low_price, close_price = ohlc
        bars.append(
            BarObservation(
                instrument=instrument,
                lineage=_lineage(
                    provider="alphavantage",
                    source="alphavantage.time_series_daily",
                    event_at=end_at,
                    fetched_at=fetched_at,
                    raw_contract_version="alphavantage.daily.v1",
                ),
                interval="1d",
                start_at=start_at,
                end_at=end_at,
                open_price=open_price,
                high_price=high_price,
                low_price=low_price,
                close_price=close_price,
                volume=_quantity(row.get("6. volume", row.get("5. volume"))),
                volume_status=(
                    "observed"
                    if _quantity(row.get("6. volume", row.get("5. volume"))) is not None
                    else "not_applicable"
                    if instrument.instrument_type is InstrumentType.INDEX
                    else "missing"
                ),
                price_basis="raw",
                finalization=(
                    BarFinalization.FINAL
                    if trade_date < fetched_at.astimezone(US_EASTERN).date()
                    else BarFinalization.PROVISIONAL
                ),
            )
        )
    bars.sort(key=lambda item: item.start_at)
    limitations: list[str] = []
    if skipped:
        limitations.append("MALFORMED_BARS_SKIPPED")
    if adjusted_available:
        limitations.append("ADJUSTED_CLOSE_AVAILABLE_BUT_BARS_REMAIN_RAW")
    canonical_bars = tuple(bars)
    return CanonicalUSMarketData(
        instrument=instrument,
        provider="alphavantage",
        interval="1d",
        price_basis="raw",
        snapshot=_snapshot_from_bars(
            instrument=instrument,
            bars=canonical_bars,
            previous_close=None,
            currency="USD",
        ),
        bars=canonical_bars,
        skipped_bar_count=skipped,
        limitations=tuple(limitations),
    )


def _provider_datetime(
    value: Any,
    *,
    default_timezone: ZoneInfo,
) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    text = str(value or "").strip()
    if not text:
        raise ValueError("provider timestamp is missing")
    if text.isdigit():
        return datetime.fromtimestamp(int(text), tz=timezone.utc)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("provider timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=default_timezone)
    return parsed


def canonical_alpaca_stock_bars_payload(
    *,
    instrument: InstrumentKey,
    payload: Mapping[str, Any],
    fetched_at: datetime,
    provider_symbol: str | None = None,
) -> CanonicalUSMarketData:
    """Convert one already-acquired Alpaca SIP historical daily response."""

    if instrument.market is not Market.US:
        raise ValueError("Alpaca US adapter requires a US instrument")
    if instrument.instrument_type not in {InstrumentType.STOCK, InstrumentType.ETF}:
        raise ValueError("Alpaca stock bars support only US stocks and ETFs")
    _require_aware(fetched_at, "fetched_at")
    expected_symbol = str(provider_symbol or instrument.symbol).strip().upper()
    payload_symbol = str(payload.get("symbol") or expected_symbol).strip().upper()
    if payload_symbol != expected_symbol:
        raise ValueError("Alpaca payload symbol does not match the provider symbol")
    raw_bars = payload.get("bars")
    if isinstance(raw_bars, Mapping):
        raw_bars = raw_bars.get(expected_symbol)
    if not isinstance(raw_bars, Sequence) or isinstance(raw_bars, (str, bytes)):
        raise ValueError("Alpaca payload has no stock bars")

    bars: list[BarObservation] = []
    skipped = 0
    for row in raw_bars:
        if not isinstance(row, Mapping):
            skipped += 1
            continue
        try:
            provider_at = _provider_datetime(
                row.get("t"),
                default_timezone=US_EASTERN,
            )
        except ValueError:
            skipped += 1
            continue
        trade_date = provider_at.astimezone(US_EASTERN).date()
        ohlc = _positive_ohlc(
            row.get("o"),
            row.get("h"),
            row.get("l"),
            row.get("c"),
        )
        if ohlc is None:
            skipped += 1
            continue
        start_at = datetime.combine(trade_date, time(9, 30), tzinfo=US_EASTERN)
        end_at = datetime.combine(
            trade_date,
            us_session_close_time(trade_date),
            tzinfo=US_EASTERN,
        )
        open_price, high_price, low_price, close_price = ohlc
        volume = _quantity(row.get("v"))
        bars.append(
            BarObservation(
                instrument=instrument,
                lineage=_lineage(
                    provider="alpaca",
                    source="alpaca.sip.stock_bars.1d",
                    event_at=end_at,
                    fetched_at=fetched_at,
                    raw_contract_version="alpaca.stock_bars.v2",
                ),
                interval="1d",
                start_at=start_at,
                end_at=end_at,
                open_price=open_price,
                high_price=high_price,
                low_price=low_price,
                close_price=close_price,
                volume=volume,
                volume_status="observed" if volume is not None else "missing",
                price_basis="raw",
                finalization=(
                    BarFinalization.FINAL
                    if fetched_at.astimezone(US_EASTERN) >= end_at
                    else BarFinalization.PROVISIONAL
                ),
            )
        )
    bars.sort(key=lambda item: item.start_at)
    if any(
        current.start_at == following.start_at
        for current, following in zip(bars, bars[1:])
    ):
        raise ValueError("Alpaca payload contains duplicate daily bar timestamps")
    limitations = ["ALPACA_SIP_DELAYED_EVIDENCE"]
    if skipped:
        limitations.append("MALFORMED_BARS_SKIPPED")
    if payload.get("next_page_token"):
        limitations.append("ALPACA_PAGINATION_TRUNCATED")
    canonical_bars = tuple(bars)
    return CanonicalUSMarketData(
        instrument=instrument,
        provider="alpaca",
        interval="1d",
        price_basis="raw",
        snapshot=_snapshot_from_bars(
            instrument=instrument,
            bars=canonical_bars,
            previous_close=None,
            currency="USD",
        ),
        bars=canonical_bars,
        skipped_bar_count=skipped,
        limitations=tuple(limitations),
    )


def canonical_twelve_data_quote_payload(
    *,
    instrument: InstrumentKey,
    payload: Mapping[str, Any],
    fetched_at: datetime,
    provider_symbol: str | None = None,
) -> CanonicalUSMarketData:
    """Convert a Twelve Data quote response without provider IO."""

    if instrument.market is not Market.US:
        raise ValueError("Twelve Data US adapter requires a US instrument")
    _require_aware(fetched_at, "fetched_at")
    expected_symbol = str(provider_symbol or instrument.symbol).strip().upper()
    payload_symbol = str(payload.get("symbol") or expected_symbol).strip().upper()
    if payload_symbol != expected_symbol:
        raise ValueError("Twelve Data payload symbol does not match the provider symbol")
    price = _decimal(payload.get("close") or payload.get("price"))
    if price is None or price <= 0:
        raise ValueError("Twelve Data quote has no valid last price")
    event_at = _provider_datetime(
        payload.get("timestamp", payload.get("datetime", fetched_at)),
        default_timezone=US_EASTERN,
    )
    lineage = _lineage(
        provider="twelve_data",
        source="twelve_data.quote",
        event_at=event_at,
        fetched_at=fetched_at,
        raw_contract_version="twelve_data.quote.v1",
    )
    cumulative_quantity = _quantity(payload.get("volume"))
    quote = QuoteObservation(
        instrument=instrument,
        lineage=lineage,
        trade_date=event_at.astimezone(US_EASTERN).date(),
        currency=str(payload.get("currency") or "USD"),
        state=ObservationState.AVAILABLE,
        trade_state=TradeObservationState.TRADE_OBSERVED,
        last_trade_price=price,
        cumulative_quantity=cumulative_quantity,
        open_price=_decimal(payload.get("open")),
        high_price=_decimal(payload.get("high")),
        low_price=_decimal(payload.get("low")),
        previous_close=_decimal(payload.get("previous_close")),
    )
    return CanonicalUSMarketData(
        instrument=instrument,
        provider="twelve_data",
        interval="quote",
        price_basis="raw",
        snapshot=CanonicalMarketSnapshot(
            instrument=instrument,
            session=MarketSessionContext(
                market=Market.US,
                session=us_session_for_timestamp(event_at),
                observed_at=event_at,
                trade_date=quote.trade_date,
            ),
            quote=quote,
        ),
        bars=(),
        limitations=("PARTIAL_US_MARKET_VOLUME",),
    )


def canonical_twelve_data_intraday_payload(
    *,
    instrument: InstrumentKey,
    payload: Mapping[str, Any],
    fetched_at: datetime,
    interval: str,
    provider_symbol: str | None = None,
) -> CanonicalUSMarketData:
    """Convert a Twelve Data time_series response into canonical intraday bars."""

    if instrument.market is not Market.US:
        raise ValueError("Twelve Data US adapter requires a US instrument")
    _require_aware(fetched_at, "fetched_at")
    interval_contract = _TWELVE_INTERVALS.get(interval)
    if interval_contract is None:
        raise ValueError("unsupported Twelve Data intraday interval")
    canonical_interval, duration = interval_contract
    metadata = payload.get("meta")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    expected_symbol = str(provider_symbol or instrument.symbol).strip().upper()
    payload_symbol = str(metadata.get("symbol") or expected_symbol).strip().upper()
    if payload_symbol != expected_symbol:
        raise ValueError("Twelve Data payload symbol does not match the provider symbol")
    timezone_name = str(metadata.get("exchange_timezone") or "America/New_York")
    try:
        exchange_timezone = ZoneInfo(timezone_name)
    except Exception as exc:
        raise ValueError("Twelve Data exchange timezone is invalid") from exc
    values = payload.get("values")
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise ValueError("Twelve Data payload has no time-series values")

    bars: list[BarObservation] = []
    skipped = 0
    for row in values:
        if not isinstance(row, Mapping):
            skipped += 1
            continue
        try:
            start_at = _provider_datetime(
                row.get("datetime"),
                default_timezone=exchange_timezone,
            )
        except ValueError:
            skipped += 1
            continue
        ohlc = _positive_ohlc(
            row.get("open"),
            row.get("high"),
            row.get("low"),
            row.get("close"),
        )
        if ohlc is None:
            skipped += 1
            continue
        end_at = start_at + duration
        open_price, high_price, low_price, close_price = ohlc
        volume = _quantity(row.get("volume"))
        bars.append(
            BarObservation(
                instrument=instrument,
                lineage=_lineage(
                    provider="twelve_data",
                    source=f"twelve_data.time_series.{interval}",
                    event_at=end_at,
                    fetched_at=fetched_at,
                    raw_contract_version="twelve_data.time_series.v1",
                ),
                interval=canonical_interval,
                start_at=start_at,
                end_at=end_at,
                open_price=open_price,
                high_price=high_price,
                low_price=low_price,
                close_price=close_price,
                volume=volume,
                volume_status="observed" if volume is not None else "missing",
                price_basis="raw",
                finalization=(
                    BarFinalization.FINAL
                    if fetched_at >= end_at.astimezone(fetched_at.tzinfo)
                    else BarFinalization.PROVISIONAL
                ),
            )
        )
    bars.sort(key=lambda item: item.start_at)
    if any(
        current.start_at == following.start_at
        for current, following in zip(bars, bars[1:])
    ):
        raise ValueError("Twelve Data payload contains duplicate bar timestamps")
    canonical_bars = tuple(bars)
    limitations = ["PARTIAL_US_MARKET_VOLUME"]
    if skipped:
        limitations.append("MALFORMED_BARS_SKIPPED")
    return CanonicalUSMarketData(
        instrument=instrument,
        provider="twelve_data",
        interval=canonical_interval,
        price_basis="raw",
        snapshot=_snapshot_from_bars(
            instrument=instrument,
            bars=canonical_bars,
            previous_close=None,
            currency=str(metadata.get("currency") or "USD"),
        ),
        bars=canonical_bars,
        skipped_bar_count=skipped,
        limitations=tuple(limitations),
    )


__all__ = [
    "CanonicalUSMarketData",
    "US_EASTERN",
    "canonical_alpaca_stock_bars_payload",
    "canonical_alphavantage_daily_payload",
    "canonical_twelve_data_intraday_payload",
    "canonical_twelve_data_quote_payload",
    "canonical_yahoo_chart_payload",
    "us_session_for_timestamp",
]
