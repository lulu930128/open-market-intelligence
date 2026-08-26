"""Taiwan-owned inputs for Shared DatasetHealth evaluation.

The shared evaluator remains market neutral.  This seam supplies only Taiwan
calendar/applicability facts and candidate observation dates; it does not
select providers or alter Resolver ordering.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime

from app.market.trading_calendar import TAIWAN_TZ
from app.market_data.contracts import DatasetHealth, EvidenceFreshness, Market
from app.market_data.integration_contracts import DataRequirementV2
from app.market_data.registry import DATASET_REGISTRY, evaluate_dataset_health


def evaluate_taiwan_candidate_dataset_health(
    requirement: DataRequirementV2,
    *,
    dataset_id: str,
    eligible: bool | None,
    event_times: Iterable[datetime] = (),
    observed_dates: Iterable[date] = (),
    freshness_values: Iterable[EvidenceFreshness] = (),
    partial: bool = False,
    provider_available: bool = True,
) -> DatasetHealth:
    """Build non-null DatasetHealth from one cache-only candidate read."""

    spec = DATASET_REGISTRY.get(dataset_id)
    if spec.market is not Market.TW:
        raise ValueError("Taiwan lifecycle evaluator requires a TW dataset")
    if requirement.requested_at.tzinfo is None or requirement.requested_at.utcoffset() is None:
        raise ValueError("Taiwan lifecycle evaluation requires aware requested_at")

    dates = list(observed_dates)
    for event_at in event_times:
        if event_at.tzinfo is None or event_at.utcoffset() is None:
            raise ValueError("Taiwan lifecycle event times must be timezone-aware")
        dates.append(event_at.astimezone(TAIWAN_TZ).date())
    latest_date = max(dates) if dates else None
    freshness = tuple(freshness_values)
    stale = bool(freshness) and all(
        value is EvidenceFreshness.STALE for value in freshness
    )
    return evaluate_dataset_health(
        spec,
        expected_date=requirement.requested_at.astimezone(TAIWAN_TZ).date(),
        latest_date=latest_date,
        checked_at=requirement.requested_at,
        eligible=eligible,
        partial=partial,
        stale=stale,
        provider_available=provider_available,
    )


__all__ = ["evaluate_taiwan_candidate_dataset_health"]
