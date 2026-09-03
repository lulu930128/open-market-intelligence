from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.market.tw_bar_contracts import (
    BarBucketCoverage,
    BarBucketCoverageStatus,
    TaiwanHistoryStatus,
    TaiwanSessionResolutionManifest,
    normalize_taiwan_bar_interval,
    require_taiwan_base_bar_interval,
)
from app.market_data.integration_contracts import BarSeriesResolutionMode


TAIPEI = timezone(timedelta(hours=8))


def _bucket_times() -> tuple[datetime, datetime]:
    start = datetime(2026, 9, 1, 9, 0, tzinfo=TAIPEI)
    return start, start + timedelta(minutes=1)


def test_row_absence_cannot_qualify_verified_no_trade() -> None:
    start, end = _bucket_times()

    with pytest.raises(ValidationError, match="positive evidence"):
        BarBucketCoverage(
            bucket_start=start,
            bucket_end=end,
            status=BarBucketCoverageStatus.VERIFIED_NO_TRADE,
            expected_by_trading_policy=True,
            reason_code="NO_ROW",
            trading_policy_version="tw.trading_policy.v1",
            coverage_algorithm_version="tw.bar.coverage.v1",
        )


def test_verified_no_trade_requires_positive_evidence_and_owner() -> None:
    start, end = _bucket_times()

    coverage = BarBucketCoverage(
        bucket_start=start,
        bucket_end=end,
        status=BarBucketCoverageStatus.VERIFIED_NO_TRADE,
        expected_by_trading_policy=True,
        evidence_refs=("receipt:abc",),
        reason_code="QUALIFIED_NO_TRADE_DATASET",
        qualification_method="exchange_no_trade_marker",
        verified_by="taiwan_bar_coverage_evaluator",
        trading_policy_version="tw.trading_policy.v1",
        coverage_algorithm_version="tw.bar.coverage.v1",
    )

    assert coverage.status is BarBucketCoverageStatus.VERIFIED_NO_TRADE


def test_not_applicable_is_not_expected_missing_evidence() -> None:
    start, end = _bucket_times()

    with pytest.raises(ValidationError, match="cannot be expected"):
        BarBucketCoverage(
            bucket_start=start,
            bucket_end=end,
            status=BarBucketCoverageStatus.NOT_APPLICABLE,
            expected_by_trading_policy=True,
            reason_code="BATCH_AUCTION_NON_MATCH_MINUTE",
            trading_policy_version="tw.trading_policy.v1",
            coverage_algorithm_version="tw.bar.coverage.v1",
        )


def test_current_session_resolution_is_timestamp_composed() -> None:
    manifest = TaiwanSessionResolutionManifest(
        trade_date=date(2026, 9, 1),
        resolution_mode=BarSeriesResolutionMode.COMPOSE_BY_TIMESTAMP,
        current_session=True,
        contributor_candidate_ids=("kgi", "nstock"),
        coverage_status=TaiwanHistoryStatus.PARTIAL,
    )

    assert manifest.selected_candidate_id is None
    assert manifest.contributor_candidate_ids == ("kgi", "nstock")

    with pytest.raises(ValidationError, match="COMPOSE_BY_TIMESTAMP"):
        TaiwanSessionResolutionManifest(
            trade_date=date(2026, 9, 1),
            resolution_mode=BarSeriesResolutionMode.SINGLE_CANDIDATE,
            current_session=True,
            selected_candidate_id="kgi",
            contributor_candidate_ids=("kgi",),
            coverage_status=TaiwanHistoryStatus.PARTIAL,
        )


@pytest.mark.parametrize(
    ("value", "expected"),
    (("daily", "1d"), ("1wk", "1w"), ("monthly", "1mo"), ("15M", "15m")),
)
def test_transport_interval_aliases_normalize_only_at_seam(
    value: str,
    expected: str,
) -> None:
    assert normalize_taiwan_bar_interval(value) == expected


def test_persistence_interval_guard_rejects_derived_interval() -> None:
    assert require_taiwan_base_bar_interval("1m") == "1m"
    assert require_taiwan_base_bar_interval("1d") == "1d"
    with pytest.raises(ValueError, match="TW_BASE_BAR_INTERVAL_REQUIRED"):
        require_taiwan_base_bar_interval("4h")
