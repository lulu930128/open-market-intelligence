"""Execute a Shared plan using bounded KR provider IO and canonical conversion."""

from datetime import datetime, time, timezone
from decimal import Decimal
import json
import hashlib
import logging

from app.kr_market.errors import KRMarketDataFetchError
from app.kr_market.identity import KRInstrumentIdentity
from app.kr_market.market_data.descriptors import KR_DAILY_PARSER_VERSION
from app.kr_market.providers.krx import fetch_krx_daily_price_payload
from app.kr_market.providers.yahoo import fetch_yahoo_chart_payload
from app.kr_market.sources import parse_krx_daily_price_records, parse_yahoo_daily_prices
from app.kr_market.trading_calendar import (
    KR_DAILY_PRICE_RELEASE_TIME, KR_MARKET_TIMEZONE, is_kr_trading_day,
)

from app.market_data.contracts import BarFinalization, BarObservation, Quantity, QuantityUnit, SourceLineage
from app.market_data.gateway import BarAcquisitionResult
from app.market_data.integration_contracts import (
    AcquisitionResourceAttempt, AcquisitionStatus, AcquisitionSummary, RawFetchReceiptV1,
)

logger = logging.getLogger(__name__)


class KRDailyAcquisition:
    def __init__(self, identity: KRInstrumentIdentity, *, fetcher=None, clock=None):
        self.identity = identity
        self.fetcher = fetcher or self._fetch
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _fetch(self, route, requirement):
        if route.provider_key == "krx_data":
            return fetch_krx_daily_price_payload(local_code=self.identity.instrument.symbol,
                trade_date=requirement.request.end_at.astimezone(KR_MARKET_TIMEZONE).date(),
                timeout_seconds=route.timeout_seconds)
        if route.provider_key == "yahoo_chart":
            return fetch_yahoo_chart_payload(symbol=self.identity.yahoo_symbol,
                range_value="1mo", interval="1d", timeout_seconds=route.timeout_seconds,
                start_at=requirement.request.start_at, end_at=requirement.request.end_at)
        raise ValueError("Unregistered KR provider route")

    def acquire_bar_observations(self, requirement, plan):
        bars, receipts, providers, limitations = [], [], [], []
        calls = 0
        resource_attempts = []
        for route in plan.routes:
            if calls >= requirement.bounds.max_external_calls:
                break
            if not route.fetch_allowed or route.max_external_calls < 1:
                raise ValueError("KR daily acquisition requires a bounded fetch route")
            providers.append(route.provider_key)
            resource_attempts.append(AcquisitionResourceAttempt(provider=route.provider_key, resource_id=route.resource_id))
            calls += 1
            try:
                payload, url = self.fetcher(route, requirement)
                fetched_at = self.clock()
                text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
                receipt = RawFetchReceiptV1(provider=route.provider_key, source=route.resource_id,
                    resource_id=route.resource_id, fetched_at=fetched_at,
                    method="POST" if route.provider_key == "krx_data" else "GET", url=url,
                    status_code=200, content_type="application/json", content_hash=digest,
                    raw_text=text, parser_version=KR_DAILY_PARSER_VERSION, provider_timeframe="end_of_day")
                records = (parse_krx_daily_price_records(payload, symbol=self.identity.yahoo_symbol, source_url=url,
                           trade_date=requirement.request.end_at.astimezone(KR_MARKET_TIMEZONE).date())
                           if route.provider_key == "krx_data" else
                           parse_yahoo_daily_prices(payload, symbol=self.identity.yahoo_symbol, source_url=url))
                selected = []
                for record in records:
                    if record.symbol != self.identity.yahoo_symbol or record.currency != self.identity.currency:
                        limitations.append("KR_PROVIDER_INSTRUMENT_MISMATCH")
                        continue
                    start = datetime.combine(record.trade_date, time(9), KR_MARKET_TIMEZONE)
                    end = datetime.combine(record.trade_date, time(15, 30), KR_MARKET_TIMEZONE)
                    release = datetime.combine(record.trade_date, KR_DAILY_PRICE_RELEASE_TIME, KR_MARKET_TIMEZONE)
                    if not requirement.request.start_at <= start < end <= requirement.request.end_at:
                        continue
                    if release > fetched_at or not is_kr_trading_day(record.trade_date):
                        continue
                    try:
                        selected.append(BarObservation(instrument=self.identity.instrument,
                            lineage=SourceLineage(provider=route.provider_key, source=route.resource_id,
                                authority=route.authority, event_at=end, fetched_at=fetched_at,
                                content_hash=digest, raw_contract_version=receipt.parser_version),
                            interval="1d", start_at=start, end_at=end,
                            open_price=Decimal(str(record.open_price)), high_price=Decimal(str(record.high_price)),
                            low_price=Decimal(str(record.low_price)), close_price=Decimal(str(record.close_price)),
                            volume=Quantity(value=record.trade_volume, unit=QuantityUnit.SHARE) if record.trade_volume is not None else None,
                            volume_status="observed" if record.trade_volume is not None else "missing",
                            price_basis="raw", finalization=BarFinalization.FINAL))
                    except (ValueError, ArithmeticError):
                        limitations.append("KR_PROVIDER_BAR_INVALID")
                by_time = {}
                conflicts = set()
                for bar in selected:
                    previous = by_time.get(bar.start_at)
                    if previous is not None and previous != bar:
                        conflicts.add(bar.start_at)
                    by_time[bar.start_at] = bar
                if conflicts:
                    limitations.append("KR_PROVIDER_DUPLICATE_BAR_CONFLICT")
                selected = [bar for timestamp, bar in by_time.items() if timestamp not in conflicts]
                maximum = min(requirement.bounds.max_rows - len(bars), requirement.request.max_bars)
                selected = sorted(selected, key=lambda bar: bar.start_at)[-maximum:] if maximum > 0 else []
                bars.extend(selected)
                receipts.append(receipt)
                if not selected:
                    limitations.append("KR_PROVIDER_COMPLETED_BARS_MISSING")
            except (ValueError, OSError, RuntimeError, KRMarketDataFetchError) as exc:
                logger.warning("KR acquisition failed: provider=%s error_type=%s", route.provider_key, type(exc).__name__)
                limitations.append("KR_PROVIDER_ACQUISITION_FAILED")
        return BarAcquisitionResult(
            summary=AcquisitionSummary(attempted=bool(calls), status=(AcquisitionStatus.NOT_ATTEMPTED if not calls
                else AcquisitionStatus.PARTIAL if limitations else AcquisitionStatus.COMPLETED),
                providers_attempted=tuple(dict.fromkeys(providers)), external_calls=calls,
                resource_attempts=tuple(resource_attempts),
                limitations=tuple(dict.fromkeys(limitations))), observations=tuple(bars), receipts=tuple(receipts))
