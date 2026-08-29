from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.market import intraday
from app.market.schemas import IntradayTrendRead
from app.market_data.contracts import (
    MarketSession,
    ResolvedEvidenceStatus,
    TradeObservationState,
)


class IntradayTrendTests(unittest.TestCase):
    def setUp(self):
        with intraday._INTRADAY_CACHE_LOCK:
            intraday._INTRADAY_CACHE.clear()
            intraday._INTRADAY_FETCH_LOCKS.clear()

    def test_concurrent_requests_share_one_cache_only_projection(self):
        start_barrier = Barrier(2)
        cached_result = {
            "stock_id": "2330",
            "symbol": "2330.TW",
            "source": "nstock_minute_stock_data",
            "previous_close": 100.0,
            "point_count": 1,
            "points": [
                {
                    "time": "2026-07-13T13:30:00+08:00",
                    "price": 101.0,
                    "volume": 1000,
                }
            ],
        }

        def load_cached_projection(*_args, **kwargs):
            self.assertEqual(kwargs["stock_id"], "2330")
            time.sleep(0.1)
            return intraday._cache_set(kwargs["cache_key"], cached_result)

        def load_trend():
            start_barrier.wait(timeout=2)
            return intraday.get_intraday_trend(db=object(), stock_id="2330")

        with (
            patch.object(
                intraday,
                "_get_stock",
                return_value=SimpleNamespace(market="TWSE"),
            ),
            patch.object(
                intraday,
                "_load_intraday_trend_uncached",
                side_effect=load_cached_projection,
            ) as load_uncached,
        ):
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: load_trend(), range(2)))

        self.assertEqual(load_uncached.call_count, 1)
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0]["point_count"], 1)

    def test_projection_cache_outlives_normal_five_second_poll(self):
        payload = {"stock_id": "2330", "point_count": 1}

        with patch.object(
            intraday.monotonic_time,
            "monotonic",
            side_effect=(100.0, 105.0, 113.0),
        ):
            intraday._cache_set("TWSE:2330", payload)
            self.assertEqual(intraday._cache_get("TWSE:2330"), payload)
            self.assertIsNone(intraday._cache_get("TWSE:2330"))

    def test_canonical_previous_close_uses_session_before_latest_intraday_bar(self):
        result = {
            "points": [
                {"time": "2026-08-28T13:30:00+08:00", "price": 621.0}
            ],
            "previous_close": None,
        }
        evidence = SimpleNamespace(
            daily=SimpleNamespace(
                trade_date=date(2026, 8, 27),
                close_price=Decimal("605.0"),
            )
        )

        with patch.object(
            intraday,
            "read_taiwan_latest_daily_evidence",
            return_value=evidence,
        ) as read_daily:
            projected = intraday._attach_canonical_previous_close(
                object(),
                stock_id="3711",
                result=result,
            )

        self.assertEqual(projected["previous_close"], 605.0)
        self.assertEqual(read_daily.call_args.kwargs["to_date"], date(2026, 8, 27))

    def test_stale_current_trade_does_not_remove_canonical_previous_close(self):
        event_at = intraday.datetime(
            2026,
            8,
            28,
            13,
            30,
            tzinfo=intraday.TAIPEI_TZ,
        )
        quote_result = SimpleNamespace(
            contract_version="omi.market_data.result.v1",
            requirement=SimpleNamespace(
                realtime_policy=SimpleNamespace(value="cache_only")
            ),
            acquisition=SimpleNamespace(status=SimpleNamespace(value="not_attempted")),
            dataset_health=None,
            provider_health=(),
            limitations=(),
            resolved=SimpleNamespace(
                quote=SimpleNamespace(
                    trade_state=TradeObservationState.TRADE_OBSERVED,
                    last_trade_price=Decimal("621.0"),
                    previous_close=Decimal("605.0"),
                    trade_date=date(2026, 8, 28),
                    lineage=SimpleNamespace(
                        event_at=event_at,
                        received_at=event_at,
                        fetched_at=event_at,
                        provider="nstock",
                        source="nstock_minute_stock_data",
                        observation_id="quote:3711:2026-08-28",
                        model_dump=lambda **_kwargs: {},
                    ),
                    model_dump=lambda **_kwargs: {},
                ),
                health=SimpleNamespace(
                    status=ResolvedEvidenceStatus.STALE,
                    research_usable=False,
                    selected_session=MarketSession.POST_CLOSE,
                    selection_reason="CACHE_ONLY_STALE",
                    model_dump=lambda **_kwargs: {},
                ),
            )
        )
        result = {
            "source": "nstock_minute_stock_data",
            "points": [],
            "previous_close": 605.0,
        }

        projected = intraday._apply_platform_quote_contract(result, quote_result)

        self.assertFalse(projected["current_trade_available"])
        self.assertEqual(projected["previous_close"], 605.0)

    def test_legacy_mis_snapshot_bar_masquerading_helpers_are_removed(self):
        self.assertFalse(hasattr(intraday, "_fetch_mis_message"))
        self.assertFalse(hasattr(intraday, "_fetch_mis_snapshot"))
        self.assertFalse(hasattr(intraday, "_apply_mis_volume_adjustment"))
        self.assertFalse(hasattr(intraday, "_fetch_nstock_intraday"))
        self.assertFalse(hasattr(intraday, "_fetch_yahoo_intraday"))
        self.assertFalse(hasattr(intraday, "_upsert_market_intraday_bars"))

    def test_public_schema_serializes_timezone_aware_intraday_points(self):
        payload = {
            "stock_id": "3711",
            "source": "nstock_minute_stock_data",
            "point_count": 1,
            "points": [
                {
                    "time": "2026-08-27T13:30:00+08:00",
                    "price": 605.0,
                }
            ],
        }

        public = IntradayTrendRead.model_validate(payload).model_dump(mode="json")

        self.assertEqual(public["points"][0]["time"], "2026-08-27T13:30:00+08:00")


if __name__ == "__main__":
    unittest.main()
