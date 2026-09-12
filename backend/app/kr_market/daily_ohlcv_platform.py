"""KR daily application owner using Shared Gateway selection and mandatory reread."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy.orm import Session
from sqlalchemy import inspect

from app.kr_market.bar_transaction import KRBarTransaction
from app.kr_market.daily_acquisition import KRDailyAcquisition
from app.kr_market.daily_repository import KRDailyCandidateReader
from app.kr_market.identity import KRInstrumentIdentity, resolve_kr_instrument_identity
from app.kr_market.market_data.descriptors import KR_DAILY_DESCRIPTORS
from app.kr_market.trading_calendar import (
    KR_MARKET_TIMEZONE, expected_kr_daily_price_date, previous_kr_trading_day,
    is_kr_trading_day, kr_calendar_limit,
)
from app.market_data.gateway import MarketDataGateway
from app.market_data.integration_contracts import (
    BarCapabilityRequest, BarCoverageRequirement, DataRequirementV2,
    FreshnessRequirement, InstrumentTarget, MarketDataResultV1, RequestBounds,
)
from app.market_data.policies import DataPurpose, RealtimePolicy


@dataclass(frozen=True, slots=True)
class KRDailyResult:
    identity: KRInstrumentIdentity
    result: MarketDataResultV1
    projection: dict
    postcondition_satisfied: bool


class KRDailyOhlcvPlatform:
    def __init__(self, db: Session, *, gateway=None, acquisition=None, transaction=None):
        self.db = db
        self.gateway = gateway or MarketDataGateway()
        self.reader = KRDailyCandidateReader(db)
        self.acquisition = acquisition
        self.transaction = transaction or KRBarTransaction(db)

    def read(self, *, symbol: str, bars: int = 90, now=None, to_date=None, require_history_coverage=False):
        return self._run(symbol=symbol, bars=bars, now=now, to_date=to_date,
                         acquire=False, require_history_coverage=require_history_coverage)

    def refresh(self, *, symbol: str, bars: int = 90, now=None, to_date=None, require_history_coverage=False):
        return self._run(symbol=symbol, bars=bars, now=now, to_date=to_date,
                         acquire=True, require_history_coverage=require_history_coverage)

    def _run(self, *, symbol, bars, now, to_date, acquire, require_history_coverage):
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("KR daily requested_at must be timezone-aware")
        if not 1 <= bars <= 2500:
            raise ValueError("KR canonical daily supports between 1 and 2500 bars")
        if acquire and (self.db.new or self.db.dirty or self.db.deleted):
            raise ValueError("KR canonical refresh requires a clean session")
        identity = resolve_kr_instrument_identity(self.db, symbol)
        if acquire and not inspect(self.db.get_bind()).has_table("kr_bar_evidence"):
            raise ValueError("KR canonical schema is not adopted; acquisition was not attempted")
        current_expected = expected_kr_daily_price_date(now=now)
        expected = previous_kr_trading_day(to_date, include_value=True) if to_date else current_expected
        if expected > current_expected:
            raise ValueError("KR requested completed session is in the future")
        start_date = expected - timedelta(days=min(3649, max(14, bars * 3)))
        requirement = DataRequirementV2(target=InstrumentTarget(instrument=identity.instrument),
            request=BarCapabilityRequest(capability_id="daily.ohlcv", interval="1d",
                start_at=datetime.combine(start_date, time(9), KR_MARKET_TIMEZONE),
                end_at=datetime.combine(expected, time(15, 30), KR_MARKET_TIMEZONE),
                max_bars=bars, completed_only=True, price_basis="raw",
                coverage=BarCoverageRequirement(minimum_bar_count=bars) if require_history_coverage else None),
            purpose=DataPurpose.RESEARCH,
            realtime_policy=RealtimePolicy.PREFER_LIVE if acquire else RealtimePolicy.COMPLETED_SESSION,
            session="closed", requested_at=now,
            freshness=FreshnessRequirement(max_age_seconds=14 * 86400),
            bounds=RequestBounds(max_provider_attempts=2 if acquire else 0, max_external_calls=2 if acquire else 0,
                max_subscriptions=0, max_candidates=8, max_rows=min(5000, max(30, bars * 3))))
        result = self.gateway.resolve_bars(requirement, reader=self.reader,
            descriptors=KR_DAILY_DESCRIPTORS if acquire else (),
            acquisition_port=(self.acquisition or KRDailyAcquisition(identity)) if acquire else None,
            transaction_port=self.transaction if acquire else None, route_resolution_gate=acquire)
        selected = result.resolved.bars
        latest = selected[-1].end_at.astimezone(KR_MARKET_TIMEZONE).date() if selected else None
        dates = {bar.end_at.astimezone(KR_MARKET_TIMEZONE).date() for bar in selected}
        gaps = []
        if selected:
            cursor = min(dates)
            while cursor <= expected:
                if is_kr_trading_day(cursor) and cursor not in dates:
                    gaps.append(cursor.isoformat())
                cursor += timedelta(days=1)
        coverage = len(selected) >= bars and not gaps
        calendar_known = all(kr_calendar_limit(year) is None for year in {expected.year, *(day.year for day in dates)})
        venue_scope_verified = bool(selected) and "KR_PROVIDER_VENUE_COVERAGE_UNVERIFIED" not in result.resolved.health.limitations
        decision = bool(latest == expected and result.resolved.health.research_usable and calendar_known
                        and venue_scope_verified
                        and not gaps
                        and (coverage if require_history_coverage else True))
        projection = {
            "contract_version": "kr.daily.resolved.v1", "symbol": identity.instrument.symbol,
            "listing_board": identity.listing_board, "listing_venue": identity.instrument.venue,
            "expected_trade_date": expected.isoformat(), "latest_trade_date": latest.isoformat() if latest else None,
            "freshness_status": "missing" if latest is None else "current" if latest == expected else "stale",
            "selected_provider": selected[-1].lineage.provider if selected else None,
            "source": selected[-1].lineage.source if selected else None,
            "facts_usable": result.resolved.health.facts_usable, "decision_usable": decision,
            "venue_scope_verified": venue_scope_verified,
            "coverage_status": "complete" if coverage else "partial" if selected else "missing",
            "missing_dates": gaps, "price_basis": "raw",
            "refresh_recommended": latest != expected or bool(gaps) or (require_history_coverage and not coverage),
            "fallback_used": result.resolved.health.fallback_used,
            "health": result.resolved.health.model_dump(mode="json"),
            "limitations": list(dict.fromkeys((*result.limitations, *result.resolved.health.limitations,
                *result.acquisition.limitations, *( () if calendar_known else ("KR_CALENDAR_COVERAGE_UNVERIFIED",))))),
            "points": [{"time": bar.end_at.astimezone(KR_MARKET_TIMEZONE).date(),
                "open": float(bar.open_price), "high": float(bar.high_price), "low": float(bar.low_price),
                "close": float(bar.close_price), "volume": float(bar.volume.value) if bar.volume else None,
                "lineage": bar.lineage.model_dump(mode="json"), "finalization": bar.finalization.value}
                for bar in selected],
        }
        return KRDailyResult(identity, result, projection, decision)
