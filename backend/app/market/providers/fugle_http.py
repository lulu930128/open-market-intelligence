"""Bounded Fugle intraday HTTP acquisition; no persistence or fallback policy.

Quote and candles share one in-flight transport and a 60/minute admission window.
HTTP does not consume or alter the existing WebSocket subscription allocation.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import re
from threading import Event, Lock, Thread
from time import monotonic

from app.config import settings
from app.market.providers._http import get
from app.market.providers.fugle_realtime import (
    FugleStreamRecord, TAIPEI_TZ, _decimal, _event_time, _iso_time, _microsecond_time, _lots,
    _validate_stock_payload_identity, fugle_quote_acquisition,
)
from app.market.tw_intraday_capabilities import (
    FUGLE_HTTP_INTRADAY_PARSER_VERSION, FUGLE_HTTP_INTRADAY_RESOURCE_ID,
    FUGLE_HTTP_INTRADAY_SOURCE,
)
from app.market.tw_realtime_capabilities import (
    FUGLE_PROVIDER, FUGLE_HTTP_QUOTE_PARSER_VERSION,
    FUGLE_HTTP_QUOTE_RESOURCE_ID, FUGLE_HTTP_QUOTE_SOURCE,
)
from app.market_data.contracts import BarObservation, ProviderResourceHealth, SourceLineage
from app.market_data.gateway import BarAcquisitionResult, QuoteAcquisitionResult
from app.market_data.integration_contracts import (
    AcquisitionResourceAttempt, AcquisitionSummary, BarCapabilityRequest,
    DataRequirementV2, InstrumentTarget, RawFetchReceiptV1,
)
from app.market_data.provider_catalog import ProviderResourceRouteV2
from app.observability.provider_http import ProviderHttpError

BASE_URL = "https://api.fugle.tw/marketdata/v1.0/stock/intraday"
_lock = Lock()
_transport = Lock()
_calls: deque[float] = deque()
_cooldown_until = 0.0


@dataclass(frozen=True)
class FugleHttpPayload:
    raw_text: str | None = None
    status_code: int | None = None
    error: str | None = None
    external_calls: int = 0
    retry_after_seconds: int | None = None


def http_admission_status() -> dict:
    with _lock:
        now = monotonic()
        return {"in_flight": _transport.locked(),
                "calls_last_minute": sum(at > now - 60 for at in _calls),
                "cooldown_seconds": max(0, _cooldown_until - now)}


def read_fugle_http(kind: str, symbol: str, timeout_seconds: int) -> FugleHttpPayload:
    """One request, no retry; timed-out transport retains ownership until exit."""
    global _cooldown_until
    # Canonical Taiwan stock/ETF codes can carry an uppercase suffix (00981A,
    # 00679B). Keep this a bounded ASCII path segment; instrument eligibility
    # still belongs to StockMaster and the canonical acquisition route.
    supported_symbol = isinstance(symbol, str) and (
        re.fullmatch(r"[0-9]{4,6}[A-Z]?", symbol)
        or (kind == "quote" and symbol in {"IX0001", "IX0043"})
        or (kind == "snapshot_quotes" and symbol in {"TSE", "OTC"})
    )
    if kind not in {"quote", "candles", "snapshot_quotes"} or not supported_symbol:
        raise ValueError("unsupported Fugle HTTP target")
    key = str(settings.fugle_api_key or "").strip()
    if not key:
        return FugleHttpPayload(error="FUGLE_CREDENTIAL_MISSING")
    with _lock:
        now = monotonic()
        while _calls and _calls[0] <= now - 60:
            _calls.popleft()
        if now < _cooldown_until or len(_calls) >= 60:
            return FugleHttpPayload(error="FUGLE_RATE_LIMITED", retry_after_seconds=60)
        if not _transport.acquire(blocking=False):
            return FugleHttpPayload(error="FUGLE_PREVIOUS_TRANSPORT_IN_FLIGHT")
        _calls.append(now)
    done = Event()
    outcome: list[FugleHttpPayload] = []
    budget = max(0.1, min(float(timeout_seconds), 5.0))

    def run() -> None:
        global _cooldown_until
        try:
            url = (f"{BASE_URL.rsplit('/', 1)[0]}/snapshot/quotes/{symbol}"
                   if kind == "snapshot_quotes" else f"{BASE_URL}/{kind}/{symbol}")
            response = get(url, provider=FUGLE_PROVIDER,
                resource=f"intraday.{kind}", target=symbol, timeout_seconds=budget,
                headers={"X-API-KEY": key, "Accept": "application/json"},
                params={"timeframe": "1", "sort": "asc"} if kind == "candles" else
                    {"type": "COMMONSTOCK"} if kind == "snapshot_quotes" else None,
                allow_redirects=False)
            code = response.status_code
            error = None if code == 200 else {
                401: "FUGLE_AUTH_FAILED", 403: "FUGLE_PLAN_RESTRICTED",
                429: "FUGLE_RATE_LIMITED",
            }.get(code, "FUGLE_HTTP_FAILED")
            retry = 60 if code == 429 else None
            outcome.append(FugleHttpPayload(response.text if code == 200 else None,
                code, error, 1, retry))
        except ProviderHttpError as exc:
            code = exc.http_status_code
            error = {401: "FUGLE_AUTH_FAILED", 403: "FUGLE_PLAN_RESTRICTED",
                     429: "FUGLE_RATE_LIMITED"}.get(code, "FUGLE_TRANSPORT_FAILED")
            outcome.append(FugleHttpPayload(status_code=code, error=error,
                external_calls=1, retry_after_seconds=exc.retry_after_seconds))
        except Exception as exc:
            # Never serialize exception text/headers containing an API key.
            outcome.append(FugleHttpPayload(error=f"FUGLE_TRANSPORT_{type(exc).__name__.upper()}", external_calls=1))
        finally:
            if outcome and outcome[0].status_code == 429:
                with _lock:
                    _cooldown_until = max(_cooldown_until, monotonic() + (outcome[0].retry_after_seconds or 60))
            _transport.release()
            done.set()

    Thread(target=run, name="fugle-http", daemon=True).start()
    if not done.wait(budget):
        return FugleHttpPayload(error="FUGLE_TIMEOUT", external_calls=1)
    return outcome[0]


def index_trade_value_observation(data: dict, *, scope: str, lineage: SourceLineage):
    """Decode original HTTP receipt; total.time never borrows the price clock."""
    from app.market_data.contracts import MarketTradeValueObservation
    expected = {"TAIEX": ("IX0001", "TWSE", "TSE"), "TPEX": ("IX0043", "TPEx", "OTC")}[scope]
    if (data.get("symbol"), data.get("exchange"), data.get("market")) != expected or data.get("type") != "INDEX":
        raise ValueError("FUGLE_INDEX_SCOPE_MISMATCH")
    day = date.fromisoformat(data["date"])
    total = data.get("total") or {}
    amount = _decimal(total.get("tradeValue"))
    event = _microsecond_time(total.get("time"))
    if amount is None or amount < 0 or amount != amount.to_integral_value() or event is None:
        raise ValueError("FUGLE_INDEX_TURNOVER_INVALID")
    # Keep the source clock verbatim. Eligibility checks both event and receipt
    # against requested_at; a sub-second server/client skew is not a new clock.
    if event.astimezone(TAIPEI_TZ).date() != day:
        raise ValueError("FUGLE_INDEX_TURNOVER_CLOCK_INVALID")
    return MarketTradeValueObservation(market="TW", venue="TWSE" if scope == "TAIEX" else "TPEX",
        trade_date=day, value=amount, currency="TWD", scope="venue_regular_market",
        semantics="vendor_cumulative_trade_value", official=False, is_estimate=False,
        lineage=lineage.model_copy(update={"event_at": event}))


def read_fugle_current_index(scope: str, timeout_seconds: int):
    from app.market.providers.tw_current_market import CurrentMarketProviderPayload
    symbol = {"TAIEX": "IX0001", "TPEX": "IX0043"}[scope]
    result = read_fugle_http("quote", symbol, timeout_seconds)
    normalized = None
    error = result.error
    if error is None:
        try:
            data = json.loads(result.raw_text)
            # Validate scope and amount here, and again in the typed adapter and
            # persisted decoder. RawResult retains the exact original payload.
            lineage = SourceLineage(provider=FUGLE_PROVIDER, source="fugle_http_index_quote",
                authority="vendor", raw_contract_version="fugle.http.index.quote.v1",
                fetched_at=datetime.now(timezone.utc), content_hash=sha256(result.raw_text.encode()).hexdigest())
            amount = index_trade_value_observation(data, scope=scope, lineage=lineage)
            price_at = _microsecond_time(data.get("closeTime")) or _microsecond_time(data.get("lastUpdated"))
            if price_at is None or price_at > lineage.fetched_at or price_at.astimezone(TAIPEI_TZ).date() != amount.trade_date:
                raise ValueError("FUGLE_INDEX_PRICE_CLOCK_INVALID")
            normalized = dict(trade_date=data["date"], as_of=price_at.isoformat(),
                close=data.get("closePrice"), previous_close=data.get("previousClose"),
                trade_value=int(amount.value), transaction_count=(data.get("total") or {}).get("transaction"))
        except (ValueError, TypeError, KeyError):
            error = "FUGLE_INDEX_SCHEMA_INVALID"
    return CurrentMarketProviderPayload(payload=normalized, status="failed" if error else "available",
        url=f"{BASE_URL}/quote/{symbol}", status_code=result.status_code, error=error,
        detail_code=error, external_calls=result.external_calls, retry_after_seconds=result.retry_after_seconds,
        raw_text=result.raw_text)


def _identity(data: dict, requirement: DataRequirementV2, received: datetime) -> date:
    if not isinstance(data, dict):
        raise ValueError("FUGLE_SCHEMA_OBJECT_REQUIRED")
    instrument = requirement.target.instrument
    if data.get("symbol") != instrument.symbol or data.get("type") not in {"EQUITY", "ETF"}:
        raise ValueError("FUGLE_INSTRUMENT_SCOPE_MISMATCH")
    _validate_stock_payload_identity(data, instrument)
    trade_date = date.fromisoformat(data["date"])
    if trade_date != requirement.requested_at.astimezone(TAIPEI_TZ).date() or trade_date != received.astimezone(TAIPEI_TZ).date():
        raise ValueError("FUGLE_CURRENT_DATE_MISMATCH")
    return trade_date


class FugleHttpAdapter:
    def __init__(self, *, clock=None, reader=read_fugle_http):
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.reader = reader

    def acquire_route(self, requirement: DataRequirementV2, route: ProviderResourceRouteV2):
        if not isinstance(requirement.target, InstrumentTarget):
            raise ValueError("Fugle HTTP requires an instrument")
        is_bar = route.resource_id == FUGLE_HTTP_INTRADAY_RESOURCE_ID
        if route.provider_key != FUGLE_PROVIDER or route.resource_id not in {
            FUGLE_HTTP_INTRADAY_RESOURCE_ID, FUGLE_HTTP_QUOTE_RESOURCE_ID,
        }:
            raise ValueError("unsupported Fugle HTTP route")
        if not route.fetch_allowed or route.subscription_allowed or route.max_external_calls != 1:
            raise ValueError("Fugle HTTP requires one FETCH route")
        kind = "candles" if is_bar else "quote"
        source = FUGLE_HTTP_INTRADAY_SOURCE if is_bar else FUGLE_HTTP_QUOTE_SOURCE
        parser = FUGLE_HTTP_INTRADAY_PARSER_VERSION if is_bar else FUGLE_HTTP_QUOTE_PARSER_VERSION
        payload = self.reader(kind, requirement.target.instrument.symbol, route.timeout_seconds)
        received = self.clock()
        if received.utcoffset() is None:
            raise ValueError("Fugle receipt clock must be aware")
        raw = payload.raw_text or ""
        digest = sha256(raw.encode()).hexdigest()
        observations = ()
        error = payload.error
        limits = ["ROUND_LOT_ONLY", "VENDOR_NOT_OFFICIAL", "CUMULATIVE_AVERAGE_NOT_MINUTE_TURNOVER"]
        if error is None:
            try:
                data = json.loads(raw)
                trade_date = _identity(data, requirement, received)
                if is_bar:
                    observations, rejected = self._bars(data, requirement, received, digest, trade_date)
                    if rejected:
                        limits.append(f"FUGLE_REJECTED_BAR_COUNT:{rejected}")
                else:
                    at = _event_time("aggregates", data)
                    if at is None or at > received or at.date() != trade_date:
                        raise ValueError("FUGLE_QUOTE_EVENT_INVALID")
                    record = FugleStreamRecord("aggregates", data["symbol"], data, raw, digest, at, received, 0)
                    mapped = fugle_quote_acquisition(record, requirement).observations[0]
                    observations = (mapped.model_copy(update={"lineage": mapped.lineage.model_copy(update={
                        "source": source, "raw_contract_version": parser})}),)
            except (ValueError, TypeError, KeyError) as exc:
                error = str(exc) if str(exc).startswith("FUGLE_") else "FUGLE_SCHEMA_INVALID"
        status = "failed" if error else "completed" if observations else "partial"
        if error:
            limits.append(error)
        elif not observations:
            limits.append("PROVIDER_RETURNED_NO_BARS" if is_bar else "PROVIDER_RETURNED_NO_QUOTE")
        receipt = RawFetchReceiptV1(provider=FUGLE_PROVIDER, source=source,
            resource_id=route.resource_id, fetched_at=received, method="GET",
            url=f"{BASE_URL}/{kind}/{requirement.target.instrument.symbol}",
            status_code=payload.status_code, content_type="application/json",
            content_hash=digest, raw_text=payload.raw_text, parser_version=parser, error_message=error)
        health = ProviderResourceHealth(provider=FUGLE_PROVIDER, market="TW",
            capability=requirement.request.capability_id, resource_id=route.resource_id,
            enablement="enabled", connection="connected" if payload.status_code else "disconnected",
            entitlement="auth_failed" if error in {"FUGLE_AUTH_FAILED", "FUGLE_CREDENTIAL_MISSING"}
                else "plan_restricted" if error == "FUGLE_PLAN_RESTRICTED" else "unknown" if error else "entitled",
            operational="rate_limited" if error == "FUGLE_RATE_LIMITED" else "failed" if error else "healthy",
            freshness="unknown" if observations else "missing", checked_at=received,
            detail_code=error or "FUGLE_HTTP_OBSERVATIONS_AVAILABLE",
            retry_after_seconds=payload.retry_after_seconds)
        return (BarAcquisitionResult if is_bar else QuoteAcquisitionResult)(
            summary=AcquisitionSummary(attempted=True, status=status,
                providers_attempted=(FUGLE_PROVIDER,),
                resource_attempts=(AcquisitionResourceAttempt(provider=FUGLE_PROVIDER, resource_id=route.resource_id),),
                external_calls=payload.external_calls, limitations=tuple(limits)),
            observations=observations, receipts=(receipt,), provider_health=(health,))

    @staticmethod
    def _bars(data, requirement, received, digest, trade_date):
        request = requirement.request
        if not isinstance(request, BarCapabilityRequest) or request.interval != "1m" or str(data.get("timeframe", "1")) != "1":
            raise ValueError("FUGLE_BASE_1M_REQUIRED")
        if not isinstance(data.get("data"), list):
            raise ValueError("FUGLE_CANDLES_DATA_MISSING")
        from app.market.tw_instrument_trading_policy import is_taiwan_continuous_time_bar_start
        by_time = {}
        conflicts = set()
        rejected = 0
        for row in data["data"]:
            try:
                start = _iso_time(row.get("date"))
                if start is None or start.astimezone(TAIPEI_TZ).date() != trade_date or start > received:
                    raise ValueError("invalid event")
                if start.second or start.microsecond or not is_taiwan_continuous_time_bar_start(start):
                    raise ValueError("not regular minute")
                if not request.start_at <= start <= request.end_at:
                    continue
                prices = [_decimal(row.get(k), positive=True) for k in ("open", "high", "low", "close")]
                if any(p is None for p in prices):
                    raise ValueError("OHLC missing")
                end = start + timedelta(minutes=1)
                volume = _lots(row.get("volume"))
                bar = BarObservation(instrument=requirement.target.instrument,
                    lineage=SourceLineage(provider=FUGLE_PROVIDER, source=FUGLE_HTTP_INTRADAY_SOURCE,
                        authority="vendor", raw_contract_version=FUGLE_HTTP_INTRADAY_PARSER_VERSION,
                        event_at=start, received_at=received, fetched_at=received, content_hash=digest),
                    interval="1m", start_at=start, end_at=end, open_price=prices[0], high_price=prices[1],
                    low_price=prices[2], close_price=prices[3], volume=volume,
                    volume_status="observed" if volume is not None else "missing", price_basis="raw",
                    finalization="final" if end <= received else "provisional")
                if start in by_time and by_time[start] != bar:
                    conflicts.add(start)
                by_time[start] = bar
            except (ValueError, TypeError, AttributeError):
                rejected += 1
        # Conflicting duplicates have no ordering/revision evidence: reject the bucket.
        return tuple(by_time[t] for t in sorted(by_time) if t not in conflicts)[-request.max_bars:], rejected + len(conflicts)
