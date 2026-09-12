"""JP completed-daily composition root for the shared cache-only Gateway."""

from datetime import date, datetime, time

from sqlalchemy.orm import Session

from app.config import settings
from app.jp_market.bar_transaction import JPBarTransaction
from app.jp_market.daily_acquisition import JPDailyAcquisition
from app.jp_market.daily_repository import JPDailyBarRepository
from app.jp_market.daily_health import planning_daily_health, publish_daily_attempts
from app.jp_market.market_data.adapters import jp_daily_session_end
from app.jp_market.market_data.descriptors import JP_DAILY_DESCRIPTORS
from app.jp_market.trading_calendar import JP_MARKET_TIMEZONE
from app.market_data.candidate_repository import DailyBarCandidateQuery
from app.market_data.contracts import EvidenceFreshness, InstrumentKey, MarketSession
from app.market_data.gateway import BarCandidateBatch, MarketDataGateway
from app.market_data.integration_contracts import (
    BarCapabilityRequest, BarCoverageRequirement, DataRequirementV2, FreshnessBasis, FreshnessRequirement,
    InstrumentTarget, QualityRequirement, RequestBounds,
)
from app.market_data.policies import DataPurpose, RealtimePolicy
from app.market_data.registry import DATASET_REGISTRY, evaluate_dataset_health
from app.market_data.resolution import BarSeriesCandidate


class JPDailyCandidateReader:
    def __init__(self, db: Session, *, repository=None) -> None:
        self.db = db
        self.include_provider_health = repository is None
        self.repository = repository or JPDailyBarRepository(db)

    def read_bar_candidates(self, requirement: DataRequirementV2) -> BarCandidateBatch:
        if not isinstance(requirement.target, InstrumentTarget) or not isinstance(requirement.request, BarCapabilityRequest):
            raise ValueError("JP daily reader requires an instrument bar request")
        request = requirement.request
        if request.capability_id != "daily.ohlcv" or request.interval != "1d" or request.price_basis != "raw":
            raise ValueError("JP daily reader requires raw daily.ohlcv bars")
        expected = request.end_at.astimezone(JP_MARKET_TIMEZONE).date()
        stored = self.repository.load_daily_bars(DailyBarCandidateQuery(
            instrument=requirement.target.instrument,
            start_date=request.start_at.astimezone(JP_MARKET_TIMEZONE).date(),
            end_date=expected, available_at=requirement.requested_at,
            max_rows=requirement.bounds.max_rows,
        ))
        candidates = []
        latest = None
        for series in stored.series:
            bars = series.bars[-request.max_bars:]
            series_latest = bars[-1].end_at.astimezone(JP_MARKET_TIMEZONE).date()
            latest = max(latest, series_latest) if latest else series_latest
            candidates.append(BarSeriesCandidate(
                bars=bars, freshness=EvidenceFreshness.FRESH if series_latest == expected else EvidenceFreshness.STALE,
                provider_priority=series.provider_priority, session=MarketSession.CLOSED,
            ))
        defects = tuple(r for r in stored.rejections if r.reason_code != "SUPERSEDED_REVISION")
        return BarCandidateBatch(
            provider_health=planning_daily_health(self.db, symbol=requirement.target.instrument.symbol, now=requirement.requested_at) if self.include_provider_health else (),
            candidates=tuple(candidates), rejections=stored.rejections,
            limitations=tuple(sorted({r.reason_code for r in defects})),
            dataset_health=evaluate_dataset_health(
                DATASET_REGISTRY.get("jp.daily.ohlcv"), expected_date=expected,
                latest_date=latest, checked_at=requirement.requested_at,
                eligible=True, partial=bool(defects),
            ),
        )


class JPDailyPlatform:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.reader = JPDailyCandidateReader(db)

    @staticmethod
    def requirement(*, instrument: InstrumentKey, start_date: date, end_date: date,
                    requested_at: datetime, max_bars: int = 500, max_rows: int = 5000,
                    minimum_bars: int = 1, acquire: bool = False):
        if start_date > end_date or (end_date - start_date).days >= 3650:
            raise ValueError("JP daily date range must be ordered and within 3650 days")
        return DataRequirementV2(
            target=InstrumentTarget(instrument=instrument),
            request=BarCapabilityRequest(
                capability_id="daily.ohlcv", interval="1d",
                start_at=datetime.combine(start_date, time(9), tzinfo=JP_MARKET_TIMEZONE),
                end_at=jp_daily_session_end(end_date), max_bars=max_bars,
                completed_only=True, price_basis="raw",
                coverage=BarCoverageRequirement(minimum_bar_count=minimum_bars),
            ),
            purpose=DataPurpose.RESEARCH,
            realtime_policy=RealtimePolicy.PREFER_LIVE if acquire else RealtimePolicy.CACHE_ONLY,
            session=MarketSession.CLOSED, requested_at=requested_at,
            freshness=FreshnessRequirement(max_age_seconds=86400, basis=FreshnessBasis.COMPLETED_SESSION_DATE),
            quality=QualityRequirement(require_canonical_lineage=True, allow_partial=True),
            bounds=RequestBounds(max_rows=max_rows, max_external_calls=2 if acquire else 0,
                                 max_provider_attempts=2 if acquire else 0, timeout_seconds=30),
        )

    def read(self, **kwargs):
        requirement = self.requirement(**kwargs)
        return MarketDataGateway().resolve_bars(requirement, reader=self.reader)

    def refresh_daily_ohlcv(self, *, acquisition_port=None, descriptors=None, **kwargs):
        requirement = self.requirement(**kwargs, acquire=True)
        available = tuple(d for d in JP_DAILY_DESCRIPTORS if d.provider_key != "jquants" or settings.jquants_api_key)
        result = MarketDataGateway().resolve_bars(
            requirement, reader=self.reader, descriptors=available if descriptors is None else descriptors,
            acquisition_port=acquisition_port or JPDailyAcquisition(),
            transaction_port=JPBarTransaction(self.db), route_resolution_gate=True,
        )
        publish_daily_attempts(self.db, symbol=requirement.target.instrument.symbol, result=result)
        return result
