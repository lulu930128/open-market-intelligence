"""Taiwan policy adapter from persisted official daily rows to Gateway candidates."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from app.market.daily_price_repository import TaiwanOfficialDailyBarRepository
from app.market_data.candidate_repository import DailyBarCandidateQuery
from app.market_data.contracts import EvidenceFreshness, Market, MarketSession
from app.market_data.gateway import BarCandidateBatch
from app.market_data.integration_contracts import (
    BarCapabilityRequest,
    DataRequirementV2,
    InstrumentTarget,
)
from app.market_data.registry import DATASET_REGISTRY, evaluate_dataset_health
from app.market_data.resolution import BarSeriesCandidate


TAIWAN_TZ = ZoneInfo("Asia/Taipei")


class TaiwanCompletedDailyCandidateReader:
    def __init__(self, repository: TaiwanOfficialDailyBarRepository) -> None:
        self._repository = repository

    def read_bar_candidates(self, requirement: DataRequirementV2) -> BarCandidateBatch:
        if not isinstance(requirement.target, InstrumentTarget):
            raise ValueError("Taiwan daily candidates require an instrument target")
        if requirement.target.instrument.market is not Market.TW:
            raise ValueError("Taiwan daily candidates require market=TW")
        if not isinstance(requirement.request, BarCapabilityRequest):
            raise ValueError("Taiwan daily candidates require a bars request")
        request = requirement.request
        if request.capability_id != "daily.ohlcv" or request.interval != "1d":
            raise ValueError("Taiwan daily candidates support daily.ohlcv interval=1d")

        start_date = request.start_at.astimezone(TAIWAN_TZ).date()
        expected_date = request.end_at.astimezone(TAIWAN_TZ).date()
        stored = self._repository.load_daily_bars(
            DailyBarCandidateQuery(
                instrument=requirement.target.instrument,
                start_date=start_date,
                end_date=expected_date,
                max_rows=requirement.bounds.max_rows,
            )
        )

        candidates: list[BarSeriesCandidate] = []
        limitations: list[str] = []
        latest_date = None
        for item in stored.series:
            bars = item.bars
            if len(bars) > request.max_bars:
                bars = bars[-request.max_bars :]
                limitations.append("BAR_SERIES_TRUNCATED_TO_REQUEST_BOUND")
            item_latest_date = bars[-1].end_at.astimezone(TAIWAN_TZ).date()
            latest_date = max(latest_date, item_latest_date) if latest_date else item_latest_date
            candidates.append(
                BarSeriesCandidate(
                    bars=bars,
                    freshness=(
                        EvidenceFreshness.FRESH
                        if item_latest_date >= expected_date
                        else EvidenceFreshness.STALE
                    ),
                    provider_priority=item.provider_priority,
                    session=MarketSession.CLOSED,
                )
            )

        if stored.rejections:
            limitations.extend(item.reason_code for item in stored.rejections)
        spec = DATASET_REGISTRY.get("tw.daily.ohlcv")
        dataset_health = evaluate_dataset_health(
            spec,
            expected_date=expected_date,
            latest_date=latest_date,
            checked_at=requirement.requested_at,
            eligible=True,
            partial=bool(stored.rejections),
        )
        return BarCandidateBatch(
            candidates=tuple(candidates),
            dataset_health=dataset_health,
            rejections=stored.rejections,
            limitations=tuple(dict.fromkeys(limitations)),
        )


__all__ = ["TaiwanCompletedDailyCandidateReader"]
