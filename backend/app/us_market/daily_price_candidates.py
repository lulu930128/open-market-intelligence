"""Gateway candidate reader for persisted US daily OHLCV."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from app.market_data.candidate_repository import DailyBarCandidateQuery
from app.market_data.contracts import (
    EvidenceFreshness,
    Market,
    MarketSession,
)
from app.market_data.gateway import BarCandidateBatch
from app.market_data.integration_contracts import (
    BarCapabilityRequest,
    DataRequirementV2,
    InstrumentTarget,
)
from app.market_data.registry import DATASET_REGISTRY, evaluate_dataset_health
from app.market_data.resolution import BarSeriesCandidate
from app.us_market.daily_price_repository import USDailyBarRepository
from sqlalchemy.orm import Session


US_EASTERN = ZoneInfo("America/New_York")


class USCompletedDailyCandidateReader:
    def __init__(self, repository: USDailyBarRepository) -> None:
        self._repository = repository

    def read_bar_candidates(self, requirement: DataRequirementV2) -> BarCandidateBatch:
        if not isinstance(requirement.target, InstrumentTarget):
            raise ValueError("US daily candidates require an instrument target")
        if requirement.target.instrument.market is not Market.US:
            raise ValueError("US daily candidates require market=US")
        if not isinstance(requirement.request, BarCapabilityRequest):
            raise ValueError("US daily candidates require a bar request")
        request = requirement.request
        if request.capability_id != "daily.ohlcv" or request.interval != "1d":
            raise ValueError("US daily candidates support daily.ohlcv interval=1d")
        start_date = request.start_at.astimezone(US_EASTERN).date()
        expected_date = request.end_at.astimezone(US_EASTERN).date()
        stored = self._repository.load_daily_bars(
            DailyBarCandidateQuery(
                instrument=requirement.target.instrument,
                start_date=start_date,
                end_date=expected_date,
                available_at=requirement.requested_at,
                max_rows=requirement.bounds.max_rows,
            )
        )
        candidates = []
        latest_date = None
        for series in stored.series:
            bars = series.bars[-request.max_bars :]
            if not bars:
                continue
            series_latest = bars[-1].end_at.astimezone(US_EASTERN).date()
            latest_date = max(latest_date, series_latest) if latest_date else series_latest
            candidates.append(
                BarSeriesCandidate(
                    bars=bars,
                    freshness=(
                        EvidenceFreshness.FRESH
                        if series_latest >= expected_date
                        else EvidenceFreshness.STALE
                    ),
                    provider_priority=series.provider_priority,
                    session=MarketSession.CLOSED,
                )
            )
        spec = DATASET_REGISTRY.get("us.daily.ohlcv")
        health = evaluate_dataset_health(
            spec,
            expected_date=expected_date,
            latest_date=latest_date,
            checked_at=requirement.requested_at,
            eligible=True,
            partial=bool(stored.rejections),
        )
        return BarCandidateBatch(
            candidates=tuple(candidates),
            dataset_health=health,
            rejections=stored.rejections,
            limitations=tuple(
                dict.fromkeys(
                    rejection.reason_code for rejection in stored.rejections
                )
            ),
        )


def build_us_completed_daily_candidate_reader(
    db: Session,
) -> USCompletedDailyCandidateReader:
    """Create the cache-only canonical reader at the US persistence boundary."""

    return USCompletedDailyCandidateReader(USDailyBarRepository(db))


__all__ = [
    "USCompletedDailyCandidateReader",
    "build_us_completed_daily_candidate_reader",
]
