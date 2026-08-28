"""Taiwan policy adapter from persisted official daily rows to Gateway candidates."""

from __future__ import annotations

from datetime import datetime
from typing import Sequence
from zoneinfo import ZoneInfo

from app.market.daily_price_repository import TaiwanOfficialDailyBarRepository
from app.market_data.candidate_repository import DailyBarCandidateQuery, PersistedBarSeries
from app.market_data.contracts import BarObservation, EvidenceFreshness, Market, MarketSession
from app.market_data.gateway import BarCandidateBatch
from app.market_data.integration_contracts import (
    BarCapabilityRequest,
    DataRequirementV2,
    InstrumentTarget,
)
from app.market_data.registry import DATASET_REGISTRY, evaluate_dataset_health
from app.market_data.resolution import BarSeriesCandidate


TAIWAN_TZ = ZoneInfo("Asia/Taipei")


def _reconcile_official_daily_series(
    stored_series: Sequence[PersistedBarSeries],
    *,
    max_bars: int,
) -> tuple[tuple[BarObservation, ...], int, tuple[str, ...]]:
    """Build one date-complete official series while preserving per-bar lineage."""

    selected_by_start: dict[
        datetime,
        tuple[tuple[int, str, str], BarObservation],
    ] = {}
    conflicts = False
    contributing_sources: set[str] = set()
    for item in sorted(
        stored_series,
        key=lambda value: (
            value.provider_priority,
            value.provider,
            value.source,
        ),
    ):
        rank = (item.provider_priority, item.provider, item.source)
        for bar in item.bars:
            current = selected_by_start.get(bar.start_at)
            if current is not None:
                current_rank, current_bar = current
                if (
                    current_bar.open_price,
                    current_bar.high_price,
                    current_bar.low_price,
                    current_bar.close_price,
                    current_bar.volume,
                ) != (
                    bar.open_price,
                    bar.high_price,
                    bar.low_price,
                    bar.close_price,
                    bar.volume,
                ):
                    conflicts = True
                if current_rank <= rank:
                    continue
            selected_by_start[bar.start_at] = (rank, bar)

    ordered = tuple(
        item[1]
        for _, item in sorted(selected_by_start.items(), key=lambda value: value[0])
    )
    if len(ordered) > max_bars:
        ordered = ordered[-max_bars:]
    ordered_starts = {bar.start_at for bar in ordered}
    for bar in ordered:
        contributing_sources.add(bar.lineage.source)
    limitations: list[str] = []
    if len(contributing_sources) > 1:
        limitations.append("OFFICIAL_DAILY_SERIES_RECONCILED")
    if conflicts:
        limitations.append("OFFICIAL_DAILY_SAME_DATE_CONFLICT_RESOLVED")
    selected_priority = min(
        (
            rank[0]
            for start_at, (rank, _) in selected_by_start.items()
            if start_at in ordered_starts
        ),
        default=100,
    )
    return ordered, selected_priority, tuple(limitations)


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

        limitations: list[str] = []
        bars, selected_priority, reconciliation_limitations = (
            _reconcile_official_daily_series(
                stored.series,
                max_bars=request.max_bars,
            )
        )
        limitations.extend(reconciliation_limitations)
        latest_date = (
            bars[-1].end_at.astimezone(TAIWAN_TZ).date()
            if bars
            else None
        )
        candidates = (
            BarSeriesCandidate(
                bars=bars,
                freshness=(
                    EvidenceFreshness.FRESH
                    if latest_date >= expected_date
                    else EvidenceFreshness.STALE
                ),
                provider_priority=selected_priority,
                session=MarketSession.CLOSED,
            ),
        ) if bars else ()

        selected_dates = {
            bar.end_at.astimezone(TAIWAN_TZ).date()
            for bar in bars
        }
        uncovered_rejections = tuple(
            item
            for item in stored.rejections
            if item.event_date not in selected_dates
        )
        if uncovered_rejections:
            limitations.extend(item.reason_code for item in uncovered_rejections)
        spec = DATASET_REGISTRY.get("tw.daily.ohlcv")
        dataset_health = evaluate_dataset_health(
            spec,
            expected_date=expected_date,
            latest_date=latest_date,
            checked_at=requirement.requested_at,
            eligible=True,
            partial=bool(uncovered_rejections),
        )
        return BarCandidateBatch(
            candidates=candidates,
            dataset_health=dataset_health,
            rejections=stored.rejections,
            limitations=tuple(dict.fromkeys(limitations)),
        )


__all__ = ["TaiwanCompletedDailyCandidateReader"]
