from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import patch

from app.market import institutional_holding_ratio_cache as cache_module
from app.market.institutional_holding_ratio_cache import (
    read_cached_institutional_holding_ratios,
    refresh_cached_institutional_holding_ratios,
)
from app.market.institutional_holding_ratios import (
    InstitutionalHoldingRatio,
    InstitutionalHoldingRatioPoint,
)


def _observation(stock_id: str) -> InstitutionalHoldingRatio:
    point = InstitutionalHoldingRatioPoint(
        trade_date=date(2026, 8, 25),
        foreign_investor_ratio=72.5,
        investment_trust_ratio=None,
        dealer_ratio=1.25,
    )
    return InstitutionalHoldingRatio(
        stock_id=stock_id,
        stock_name="台積電",
        trade_date=point.trade_date,
        foreign_investor_ratio=point.foreign_investor_ratio,
        investment_trust_ratio=point.investment_trust_ratio,
        dealer_ratio=point.dealer_ratio,
        source_name="nStock",
        source_url=f"https://example.test/{stock_id}",
        fetched_at=datetime(2026, 8, 26, 8, 0, tzinfo=timezone.utc),
        history=[point],
    )


def test_refresh_writes_bounded_compatibility_cache_and_get_rereads_it() -> None:
    state = cache_module._empty_cache()
    calls: list[str] = []

    def persist(_path, payload) -> None:
        assert payload is state

    with (
        patch.object(cache_module, "_read_payload", side_effect=lambda _path: state),
        patch.object(cache_module, "_atomic_write", side_effect=persist) as write,
    ):
        refreshed = refresh_cached_institutional_holding_ratios(
            "2330",
            fetcher=lambda stock_id: calls.append(stock_id) or _observation(stock_id),
        )
        cached = read_cached_institutional_holding_ratios("2330")

    assert calls == ["2330"]
    assert write.call_count == 1
    assert refreshed.trade_date == date(2026, 8, 25)
    assert cached == refreshed
    assert state["classification"] == "compatibility_cache"
    assert state["lineage_status"] == "raw_receipt_not_persisted"
    assert state["stocks"]["2330"]["canonical_truth"] is False
    assert state["stocks"]["2330"]["decision_usable"] is False
    assert state["stocks"]["2330"]["raw_receipt_id"] is None
    assert cached is not None
    assert cached.classification == "compatibility_cache"
    assert cached.lineage_status == "raw_receipt_not_persisted"
    assert cached.canonical_truth is False
    assert cached.decision_usable is False
    assert "RAW_RECEIPT_NOT_PERSISTED" in cached.limitations


def test_cache_only_read_does_not_call_fetcher_and_malformed_cache_fails_closed() -> None:
    with patch.object(
        cache_module,
        "_read_payload",
        return_value={**cache_module._empty_cache(), "stocks": {"2330": {}}},
    ):
        assert read_cached_institutional_holding_ratios(
            "2330",
        ) is None
