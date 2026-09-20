from concurrent.futures import ThreadPoolExecutor
from datetime import date
from unittest.mock import patch

import pytest

from app.market import exchange_calendar_cache as cache
from app.market.trading_calendar import has_taiwan_calendar_year


def _calendar(name):
    return {"markets": {"tw": {"verified_years": [2026], "holidays": {"2026-09-14": name}}}}


def test_nested_calculation_reads_once_and_next_calculation_observes_update():
    with patch.object(cache, "read_exchange_calendar_cache", side_effect=[_calendar("first"), _calendar("updated")]) as read:
        with cache.exchange_calendar_read_scope():
            for _ in range(20):
                with cache.exchange_calendar_read_scope():
                    assert cache.cached_market_holiday("tw", date(2026, 9, 14)).name == "first"
            assert read.call_count == 1
        with cache.exchange_calendar_read_scope():
            assert cache.cached_market_holiday("tw", date(2026, 9, 14)).name == "updated"
        assert read.call_count == 2


def test_failed_calculation_does_not_leak_snapshot_to_next_read():
    with patch.object(cache, "read_exchange_calendar_cache", side_effect=[_calendar("first"), _calendar("updated")]):
        with pytest.raises(ValueError), cache.exchange_calendar_read_scope():
            raise ValueError("calculation failed")
        assert cache.cached_market_holiday("tw", date(2026, 9, 14)).name == "updated"


def test_annual_coverage_does_not_infer_historical_holidays_from_weekdays():
    with patch.object(cache, "read_exchange_calendar_cache", return_value=_calendar("known")):
        with cache.exchange_calendar_read_scope():
            assert has_taiwan_calendar_year(2026)
            assert has_taiwan_calendar_year(2025)  # built-in annual schedule
            assert not has_taiwan_calendar_year(2021)


def test_explicit_path_and_other_thread_are_not_pinned_to_callers_snapshot(tmp_path):
    with patch.object(cache, "read_exchange_calendar_cache", side_effect=[_calendar("first"), _calendar("explicit"), _calendar("thread")]) as read:
        with cache.exchange_calendar_read_scope():
            assert cache.cached_market_holiday("tw", date(2026, 9, 14), path=tmp_path / "other.json").name == "explicit"
            with ThreadPoolExecutor(max_workers=1) as pool:
                assert pool.submit(cache.cached_market_holiday, "tw", date(2026, 9, 14)).result().name == "thread"
            assert cache.cached_market_holiday("tw", date(2026, 9, 14)).name == "first"
        assert read.call_count == 3
