"""Pure NStock and Yahoo adapters for canonical Taiwan intraday bars."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from typing import Any

from app.market.providers import http_get
from app.market.tw_intraday_capabilities import (
    NSTOCK_INTRADAY_PARSER_VERSION,
    NSTOCK_INTRADAY_PROVIDER,
    NSTOCK_INTRADAY_RESOURCE_ID,
    NSTOCK_INTRADAY_SOURCE,
    YAHOO_INTRADAY_PARSER_VERSION,
    YAHOO_INTRADAY_PROVIDER,
    YAHOO_INTRADAY_RESOURCE_ID,
    YAHOO_INTRADAY_SOURCE,
)
from app.market_data.contracts import (
    BarFinalization,
    BarObservation,
    ConnectionStatus,
    EnablementStatus,
    EntitlementStatus,
    EvidenceFreshness,
    Market,
    OperationalStatus,
    ProviderResourceHealth,
    Quantity,
    QuantityUnit,
    SourceLineage,
)
from app.market_data.gateway import BarAcquisitionResult
from app.market_data.integration_contracts import (
    AcquisitionResourceAttempt,
    AcquisitionStatus,
    AcquisitionSummary,
    BarCapabilityRequest,
    DataRequirementV2,
    InstrumentTarget,
    RawFetchReceiptV1,
)
from app.market_data.provider_catalog import ProviderResourceRouteV2


TAIPEI_TZ = timezone(timedelta(hours=8))
NSTOCK_MINUTE_URL = "https://shop.nstock.tw/api/v2/minute-stock-data/data"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


@dataclass(frozen=True, slots=True)
class IntradayProviderPayload:
    raw_text: str | None
    status: str
    url: str
    status_code: int | None = None
    content_type: str | None = None
    error: str | None = None


Clock = Callable[[], datetime]
NStockReader = Callable[[str, int], IntradayProviderPayload]
YahooReader = Callable[[str, str | None, str, str, int], IntradayProviderPayload]


def _aware_clock(clock: Clock) -> datetime:
    value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("intraday provider clock must be timezone-aware")
    return value


def _decimal(value: Any, *, non_negative: bool = False) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).replace(",", "").strip()
    if not text or text in {"-", "--"}:
        return None
    try:
        parsed = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite() or (non_negative and parsed < 0):
        return None
    return parsed


def _integer(value: Any, *, multiplier: int = 1) -> int | None:
    parsed = _decimal(value, non_negative=True)
    if parsed is None:
        return None
    scaled = parsed * multiplier
    if scaled != scaled.to_integral_value():
        return None
    return int(scaled)


def _bar_prices(
    *,
    open_price: Any,
    high_price: Any,
    low_price: Any,
    close_price: Any,
) -> tuple[Decimal, Decimal, Decimal, Decimal] | None:
    close_value = _decimal(close_price)
    if close_value is None or close_value <= 0:
        return None
    open_value = _decimal(open_price) or close_value
    high_value = _decimal(high_price) or max(open_value, close_value)
    low_value = _decimal(low_price) or min(open_value, close_value)
    high_value = max(high_value, open_value, close_value, low_value)
    low_value = min(low_value, open_value, close_value, high_value)
    if low_value <= 0:
        return None
    return open_value, high_value, low_value, close_value


def _finalization(end_at: datetime, requested_at: datetime) -> BarFinalization:
    """Finalize an interval only after its canonical close boundary."""

    return (
        BarFinalization.FINAL
        if requested_at.astimezone(TAIPEI_TZ)
        >= end_at.astimezone(TAIPEI_TZ)
        else BarFinalization.PROVISIONAL
    )


def _is_regular_session(start_at: datetime) -> bool:
    from app.market.tw_instrument_trading_policy import (
        is_taiwan_continuous_time_bar_start,
    )

    return is_taiwan_continuous_time_bar_start(start_at)


def _lineage(
    *,
    provider: str,
    source: str,
    parser_version: str,
    event_at: datetime,
    fetched_at: datetime,
    content_hash: str,
) -> SourceLineage:
    return SourceLineage(
        provider=provider,
        source=source,
        authority="vendor",
        raw_contract_version=parser_version,
        event_at=event_at,
        received_at=fetched_at,
        fetched_at=fetched_at,
        content_hash=content_hash,
    )


def _health(
    requirement: DataRequirementV2,
    *,
    provider: str,
    checked_at: datetime,
    healthy: bool,
    detail_code: str,
) -> ProviderResourceHealth:
    assert isinstance(requirement.target, InstrumentTarget)
    return ProviderResourceHealth(
        provider=provider,
        market=Market.TW,
        capability=requirement.request.capability_id,
        enablement=EnablementStatus.ENABLED,
        connection=(
            ConnectionStatus.CONNECTED
            if healthy
            else ConnectionStatus.DISCONNECTED
        ),
        entitlement=EntitlementStatus.ENTITLED,
        operational=(
            OperationalStatus.HEALTHY
            if healthy
            else OperationalStatus.FAILED
        ),
        freshness=(
            EvidenceFreshness.LIVE if healthy else EvidenceFreshness.MISSING
        ),
        checked_at=checked_at,
        detail_code=detail_code,
    )


def _result(
    requirement: DataRequirementV2,
    route: ProviderResourceRouteV2,
    *,
    provider: str,
    source: str,
    parser_version: str,
    payload: IntradayProviderPayload,
    fetched_at: datetime,
    bars: tuple[BarObservation, ...] = (),
    parse_error: str | None = None,
    limitations: tuple[str, ...] = (),
) -> BarAcquisitionResult:
    raw_text = payload.raw_text or ""
    content_hash = sha256(raw_text.encode("utf-8")).hexdigest()
    error = parse_error or payload.error
    receipt = RawFetchReceiptV1(
        provider=provider,
        source=source,
        resource_id=route.resource_id,
        fetched_at=fetched_at,
        method="GET",
        url=payload.url,
        status_code=payload.status_code,
        content_type=payload.content_type,
        content_hash=content_hash,
        raw_text=payload.raw_text,
        parser_version=parser_version,
        error_message=error,
    )
    healthy = payload.status == "available" and error is None
    status = (
        AcquisitionStatus.COMPLETED
        if healthy and bars
        else AcquisitionStatus.PARTIAL
        if healthy
        else AcquisitionStatus.FAILED
    )
    limitation = (
        ()
        if status is AcquisitionStatus.COMPLETED
        else ("PROVIDER_RETURNED_NO_BARS",)
        if status is AcquisitionStatus.PARTIAL
        else ("PROVIDER_REQUEST_OR_PARSE_FAILED",)
    )
    return BarAcquisitionResult(
        summary=AcquisitionSummary(
            attempted=True,
            status=status,
            providers_attempted=(provider,),
            resource_attempts=(
                AcquisitionResourceAttempt(
                    provider=provider,
                    resource_id=route.resource_id,
                ),
            ),
            external_calls=1,
            limitations=tuple(dict.fromkeys((*limitation, *limitations))),
        ),
        observations=bars,
        receipts=(receipt,),
        provider_health=(
            _health(
                requirement,
                provider=provider,
                checked_at=fetched_at,
                healthy=healthy,
                detail_code=(
                    "CANONICAL_INTRADAY_BARS_AVAILABLE"
                    if bars
                    else "PROVIDER_RETURNED_NO_BARS"
                    if healthy
                    else "PROVIDER_REQUEST_OR_PARSE_FAILED"
                ),
            ),
        ),
    )


def _default_nstock_reader(symbol: str, timeout_seconds: int) -> IntradayProviderPayload:
    response = http_get(
        NSTOCK_MINUTE_URL,
        params={"stock_id": symbol},
        headers={
            "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
            "Accept": "application/json,text/plain,*/*",
        },
        timeout=timeout_seconds,
    )
    return IntradayProviderPayload(
        raw_text=str(response.text or ""),
        status="available" if 200 <= int(response.status_code) < 300 else "failed",
        url=str(response.url or NSTOCK_MINUTE_URL),
        status_code=int(response.status_code),
        content_type=str(response.headers.get("content-type") or "") or None,
        error=(
            None
            if 200 <= int(response.status_code) < 300
            else f"HTTP {int(response.status_code)}"
        ),
    )


def _nstock_time(date_text: Any, time_text: Any) -> datetime | None:
    raw_date = str(date_text or "").strip()
    raw_time = str(time_text or "").strip()
    if (
        len(raw_date) != 8
        or len(raw_time) != 6
        or not raw_date.isdigit()
        or not raw_time.isdigit()
    ):
        return None
    try:
        return datetime(
            int(raw_date[:4]),
            int(raw_date[4:6]),
            int(raw_date[6:8]),
            int(raw_time[:2]),
            int(raw_time[2:4]),
            int(raw_time[4:6]),
            tzinfo=TAIPEI_TZ,
        )
    except ValueError:
        return None


class NStockIntradayAdapter:
    def __init__(
        self,
        reader: NStockReader = _default_nstock_reader,
        *,
        clock: Clock,
    ) -> None:
        self._reader = reader
        self._clock = clock

    def acquire_route(
        self,
        requirement: DataRequirementV2,
        route: ProviderResourceRouteV2,
    ) -> BarAcquisitionResult:
        if not isinstance(requirement.target, InstrumentTarget) or not isinstance(
            requirement.request,
            BarCapabilityRequest,
        ):
            raise ValueError("NStock intraday requires an instrument bar request")
        if route.provider_key != NSTOCK_INTRADAY_PROVIDER or (
            route.resource_id != NSTOCK_INTRADAY_RESOURCE_ID
        ):
            raise ValueError("NStock adapter received an unsupported route")
        fetched_at = _aware_clock(self._clock)
        try:
            payload = self._reader(
                requirement.target.instrument.symbol,
                route.timeout_seconds,
            )
        except Exception as exc:
            payload = IntradayProviderPayload(
                raw_text=None,
                status="failed",
                url=NSTOCK_MINUTE_URL,
                error=f"{type(exc).__name__}: {exc}"[:1000],
            )
        bars: list[BarObservation] = []
        parse_error = None
        limitations: list[str] = []
        content_hash = sha256((payload.raw_text or "").encode("utf-8")).hexdigest()
        if payload.status == "available" and payload.raw_text:
            try:
                parsed = json.loads(payload.raw_text)
                records = parsed.get("data") or []
                data = records[0] if records and isinstance(records[0], dict) else {}
                points: list[tuple[datetime, dict[str, Any], int | None]] = []
                for row in data.get("分K") or []:
                    if not isinstance(row, dict):
                        continue
                    start_at = _nstock_time(row.get("交易日"), row.get("交易時間"))
                    prices = _bar_prices(
                        open_price=row.get("開盤價"),
                        high_price=row.get("最高價"),
                        low_price=row.get("最低價"),
                        close_price=row.get("收盤價"),
                    )
                    if start_at is None or prices is None:
                        continue
                    if not _is_regular_session(start_at):
                        continue
                    points.append(
                        (start_at, row, _integer(row.get("成交量"), multiplier=1000))
                    )
                total_volume = _integer(data.get("總成交量"), multiplier=1000)
                observed_total = sum(volume or 0 for _, _, volume in points)
                if points and total_volume is not None and total_volume > observed_total:
                    limitations.append(
                        "PROVIDER_SESSION_TOTAL_VOLUME_NOT_ALLOCATED_TO_BARS"
                    )
                for start_at, row, volume in points[-requirement.request.max_bars :]:
                    prices = _bar_prices(
                        open_price=row.get("開盤價"),
                        high_price=row.get("最高價"),
                        low_price=row.get("最低價"),
                        close_price=row.get("收盤價"),
                    )
                    assert prices is not None
                    open_value, high_value, low_value, close_value = prices
                    bars.append(
                        BarObservation(
                            instrument=requirement.target.instrument,
                            lineage=_lineage(
                                provider=NSTOCK_INTRADAY_PROVIDER,
                                source=NSTOCK_INTRADAY_SOURCE,
                                parser_version=NSTOCK_INTRADAY_PARSER_VERSION,
                                event_at=start_at,
                                fetched_at=fetched_at,
                                content_hash=content_hash,
                            ),
                            interval="1m",
                            start_at=start_at,
                            end_at=start_at + timedelta(minutes=1),
                            open_price=open_value,
                            high_price=high_value,
                            low_price=low_value,
                            close_price=close_value,
                            volume=(
                                Quantity(
                                    value=Decimal(volume),
                                    unit=QuantityUnit.SHARE,
                                )
                                if volume is not None
                                else None
                            ),
                            finalization=_finalization(
                                start_at + timedelta(minutes=1),
                                requirement.requested_at,
                            ),
                        )
                    )
            except Exception as exc:
                parse_error = f"{type(exc).__name__}: {exc}"[:1000]
                bars = []
        return _result(
            requirement,
            route,
            provider=NSTOCK_INTRADAY_PROVIDER,
            source=NSTOCK_INTRADAY_SOURCE,
            parser_version=NSTOCK_INTRADAY_PARSER_VERSION,
            payload=payload,
            fetched_at=fetched_at,
            bars=tuple(bars),
            parse_error=parse_error,
            limitations=tuple(limitations),
        )


def _yahoo_symbol(symbol: str, venue: str | None) -> str:
    return f"{symbol}.TWO" if venue == "TPEX" else f"{symbol}.TW"


def _default_yahoo_reader(
    symbol: str,
    venue: str | None,
    range_value: str,
    interval: str,
    timeout_seconds: int,
) -> IntradayProviderPayload:
    provider_symbol = _yahoo_symbol(symbol, venue)
    url = YAHOO_CHART_URL.format(symbol=provider_symbol)
    response = http_get(
        url,
        params={
            "range": range_value,
            "interval": interval,
            "includePrePost": "false",
        },
        headers={
            "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
            "Accept": "application/json,text/plain,*/*",
        },
        timeout=timeout_seconds,
    )
    return IntradayProviderPayload(
        raw_text=str(response.text or ""),
        status="available" if 200 <= int(response.status_code) < 300 else "failed",
        url=str(response.url or url),
        status_code=int(response.status_code),
        content_type=str(response.headers.get("content-type") or "") or None,
        error=(
            None
            if 200 <= int(response.status_code) < 300
            else f"HTTP {int(response.status_code)}"
        ),
    )


def _provider_query(requirement: DataRequirementV2) -> tuple[str, str, int]:
    assert isinstance(requirement.request, BarCapabilityRequest)
    requested_interval = requirement.request.interval
    if requested_interval != "1m":
        raise ValueError("TW_BASE_BAR_INTERVAL_REQUIRED")
    fetch_interval = "1m"
    days = max(
        1,
        (
            requirement.request.end_at.astimezone(TAIPEI_TZ).date()
            - requirement.request.start_at.astimezone(TAIPEI_TZ).date()
        ).days
        + 1,
    )
    range_value = "1d" if days <= 1 else "5d"
    return range_value, fetch_interval, days


class YahooIntradayAdapter:
    def __init__(
        self,
        reader: YahooReader = _default_yahoo_reader,
        *,
        clock: Clock,
    ) -> None:
        self._reader = reader
        self._clock = clock

    def acquire_route(
        self,
        requirement: DataRequirementV2,
        route: ProviderResourceRouteV2,
    ) -> BarAcquisitionResult:
        if not isinstance(requirement.target, InstrumentTarget) or not isinstance(
            requirement.request,
            BarCapabilityRequest,
        ):
            raise ValueError("Yahoo intraday requires an instrument bar request")
        if route.provider_key != YAHOO_INTRADAY_PROVIDER or (
            route.resource_id != YAHOO_INTRADAY_RESOURCE_ID
        ):
            raise ValueError("Yahoo adapter received an unsupported route")
        fetched_at = _aware_clock(self._clock)
        range_value, fetch_interval, _ = _provider_query(requirement)
        instrument = requirement.target.instrument
        try:
            payload = self._reader(
                instrument.symbol,
                instrument.venue,
                range_value,
                fetch_interval,
                route.timeout_seconds,
            )
        except Exception as exc:
            payload = IntradayProviderPayload(
                raw_text=None,
                status="failed",
                url=YAHOO_CHART_URL.format(
                    symbol=_yahoo_symbol(instrument.symbol, instrument.venue)
                ),
                error=f"{type(exc).__name__}: {exc}"[:1000],
            )
        bars: list[BarObservation] = []
        parse_error = None
        content_hash = sha256((payload.raw_text or "").encode("utf-8")).hexdigest()
        if payload.status == "available" and payload.raw_text:
            try:
                parsed = json.loads(payload.raw_text)
                result = (parsed.get("chart", {}).get("result") or [None])[0]
                if result:
                    meta = result.get("meta") or {}
                    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
                    timestamps = result.get("timestamp") or []
                    offset = int(meta.get("gmtoffset") or 28800)
                    provider_tz = timezone(timedelta(seconds=offset))
                    raw_bars: list[BarObservation] = []
                    for index, timestamp in enumerate(timestamps):
                        def item(name: str) -> Any:
                            values = quote.get(name)
                            return values[index] if isinstance(values, list) and index < len(values) else None

                        prices = _bar_prices(
                            open_price=item("open"),
                            high_price=item("high"),
                            low_price=item("low"),
                            close_price=item("close"),
                        )
                        if prices is None:
                            continue
                        start_at = datetime.fromtimestamp(int(timestamp), tz=provider_tz)
                        if not (
                            requirement.request.start_at <= start_at <= requirement.request.end_at
                        ):
                            continue
                        if not _is_regular_session(start_at):
                            continue
                        open_value, high_value, low_value, close_value = prices
                        seconds = 60
                        volume = _integer(item("volume"))
                        raw_bars.append(
                            BarObservation(
                                instrument=instrument,
                                lineage=_lineage(
                                    provider=YAHOO_INTRADAY_PROVIDER,
                                    source=YAHOO_INTRADAY_SOURCE,
                                    parser_version=YAHOO_INTRADAY_PARSER_VERSION,
                                    event_at=start_at,
                                    fetched_at=fetched_at,
                                    content_hash=content_hash,
                                ),
                                interval="1m",
                                start_at=start_at,
                                end_at=start_at + timedelta(seconds=seconds),
                                open_price=open_value,
                                high_price=high_value,
                                low_price=low_value,
                                close_price=close_value,
                                volume=(
                                    Quantity(
                                        value=Decimal(volume),
                                        unit=QuantityUnit.SHARE,
                                    )
                                    if volume is not None
                                    else None
                                ),
                                finalization=_finalization(
                                    start_at + timedelta(seconds=seconds),
                                    requirement.requested_at,
                                ),
                            )
                        )
                    bars = raw_bars[-requirement.request.max_bars :]
            except Exception as exc:
                parse_error = f"{type(exc).__name__}: {exc}"[:1000]
                bars = []
        return _result(
            requirement,
            route,
            provider=YAHOO_INTRADAY_PROVIDER,
            source=YAHOO_INTRADAY_SOURCE,
            parser_version=YAHOO_INTRADAY_PARSER_VERSION,
            payload=payload,
            fetched_at=fetched_at,
            bars=tuple(bars),
            parse_error=parse_error,
        )


__all__ = [
    "IntradayProviderPayload",
    "NSTOCK_MINUTE_URL",
    "NStockIntradayAdapter",
    "YAHOO_CHART_URL",
    "YahooIntradayAdapter",
]
