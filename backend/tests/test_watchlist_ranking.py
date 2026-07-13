from datetime import date, datetime
import unittest
from unittest.mock import ANY, patch

from app.watchlists import ranking_service


class WatchlistRankingLimitStatusTests(unittest.TestCase):
    def test_limit_status_from_change_pct(self):
        self.assertEqual(ranking_service._limit_status_from_change_pct(9.5), "limit_up")
        self.assertEqual(ranking_service._limit_status_from_change_pct(-9.5), "limit_down")
        self.assertIsNone(ranking_service._limit_status_from_change_pct(9.49))
        self.assertIsNone(ranking_service._limit_status_from_change_pct(None))

    def test_previous_close_prefers_price_change(self):
        self.assertEqual(
            ranking_service._previous_close_from_change(
                close=204.5,
                change=18.5,
                change_pct=9.9462,
            ),
            186.0,
        )

    def test_previous_close_can_fallback_to_change_pct(self):
        self.assertAlmostEqual(
            ranking_service._previous_close_from_change(
                close=204.5,
                change=None,
                change_pct=9.9462365591,
            ),
            186.0,
            places=4,
        )

    def test_ranking_freshness_marks_old_rows_stale(self):
        with patch.object(
            ranking_service,
            "expected_daily_price_date",
            return_value=date(2026, 6, 8),
        ):
            freshness = ranking_service._ranking_freshness(
                rows=[{"time": "2026-06-05"}],
                requested_stock_count=1,
            )

        self.assertFalse(freshness["is_current"])
        self.assertEqual(freshness["target_trade_date"], date(2026, 6, 8))
        self.assertEqual(freshness["trade_date"], date(2026, 6, 5))
        self.assertEqual(freshness["current_stock_count"], 0)
        self.assertEqual(freshness["stale_stock_count"], 1)

    def test_ranking_freshness_accepts_target_trade_date(self):
        with patch.object(
            ranking_service,
            "expected_daily_price_date",
            return_value=date(2026, 6, 8),
        ):
            freshness = ranking_service._ranking_freshness(
                rows=[
                    {"time": "2026-06-08"},
                    {"time": date(2026, 6, 8)},
                ],
                requested_stock_count=2,
            )

        self.assertTrue(freshness["is_current"])
        self.assertEqual(freshness["current_stock_count"], 2)
        self.assertEqual(freshness["stale_stock_count"], 0)

    def test_ranking_freshness_accepts_intraday_rows_after_previous_release(self):
        with patch.object(
            ranking_service,
            "expected_daily_price_date",
            return_value=date(2026, 6, 5),
        ):
            freshness = ranking_service._ranking_freshness(
                rows=[{"time": datetime(2026, 6, 8, 9, 1)}],
                requested_stock_count=1,
            )

        self.assertTrue(freshness["is_current"])
        self.assertEqual(freshness["trade_date"], date(2026, 6, 8))
        self.assertEqual(freshness["current_stock_count"], 1)

    def test_ranking_batch_processes_only_requested_slice(self):
        items = [
            {"stock_id": "1101", "stock_name": "Alpha"},
            {"stock_id": "2330", "stock_name": "Beta"},
            {"stock_id": "2454", "stock_name": "Gamma"},
        ]
        seen_stock_ids: list[str] = []

        def fake_signal_result(*, stock_id: str, **_: object):
            seen_stock_ids.append(stock_id)
            return {
                "time": "2026-06-08",
                "close": 100.0,
                "volume": 1000,
                "change": 1.0,
                "change_pct": 1.0,
                "score": 7,
                "status": "ready",
                "signals": [{"key": "above_ma20", "label": "站上 MA20"}],
                "indicator_snapshot": {"atr": {"atr14": 2.5}},
            }

        with (
            patch.object(ranking_service.watchlist_service, "get_group", return_value={}),
            patch.object(
                ranking_service.watchlist_service,
                "get_group_tree",
                return_value=[{"id": 1, "children": []}],
            ),
            patch.object(
                ranking_service.watchlist_service,
                "list_items",
                return_value=items,
            ),
            patch.object(
                ranking_service,
                "calculate_latest_stock_signals",
                side_effect=fake_signal_result,
            ),
            patch.object(
                ranking_service,
                "expected_daily_price_date",
                return_value=date(2026, 6, 8),
            ),
        ):
            result = ranking_service.get_watchlist_group_latest_ranking_batch(
                db=object(),
                group_id=1,
                offset=1,
                batch_size=1,
            )

        self.assertEqual(seen_stock_ids, ["2330"])
        self.assertEqual(result["total_stock_count"], 3)
        self.assertEqual(result["requested_stock_count"], 1)
        self.assertTrue(result["has_more"])
        self.assertEqual(result["results"][0]["rank"], 2)
        self.assertEqual(result["results"][0]["stock_id"], "2330")
        self.assertEqual(result["results"][0]["indicator_snapshot"]["atr"]["atr14"], 2.5)

    def test_ranking_batch_applies_intraday_limit_across_offsets(self):
        items = [
            {"stock_id": str(1000 + index), "stock_name": f"Stock {index}"}
            for index in range(40)
        ]
        signal_result = {
            "time": "2026-06-08",
            "close": 100.0,
            "volume": 1000,
            "change": 0.0,
            "change_pct": 0.0,
            "score": 0,
            "status": "ready",
            "signals": [],
            "indicator_snapshot": {},
        }

        with (
            patch.object(ranking_service.watchlist_service, "get_group", return_value={}),
            patch.object(
                ranking_service.watchlist_service,
                "get_group_tree",
                return_value=[{"id": 1, "children": []}],
            ),
            patch.object(
                ranking_service.watchlist_service,
                "list_items",
                return_value=items,
            ),
            patch.object(
                ranking_service,
                "calculate_latest_stock_signals",
                return_value=signal_result,
            ),
            patch.object(ranking_service, "_market_context_by_stock", return_value={}),
            patch.object(
                ranking_service,
                "_get_intraday_overlay",
                return_value=None,
            ) as get_overlay,
            patch.object(
                ranking_service,
                "expected_daily_price_date",
                return_value=date(2026, 6, 8),
            ),
        ):
            first_result = ranking_service.get_watchlist_group_latest_ranking_batch(
                db=object(),
                group_id=1,
                use_intraday=True,
                intraday_limit=30,
                offset=27,
                batch_size=6,
            )
            second_result = ranking_service.get_watchlist_group_latest_ranking_batch(
                db=object(),
                group_id=1,
                use_intraday=True,
                intraday_limit=30,
                offset=30,
                batch_size=3,
            )

        self.assertEqual(len(first_result["results"]), 6)
        self.assertEqual(len(second_result["results"]), 3)
        self.assertEqual(
            [call.kwargs["stock_id"] for call in get_overlay.call_args_list],
            ["1027", "1028", "1029"],
        )

    def test_ranking_rows_include_market_context_snapshot(self):
        def fake_signal_result(*, stock_id: str, **_: object):
            return {
                "time": "2026-06-08",
                "close": 100.0,
                "volume": 1000,
                "change": 1.0,
                "change_pct": 1.0,
                "score": 7,
                "status": "ready",
                "signals": [{"key": "above_ma20", "label": "站上 MA20"}],
                "indicator_snapshot": {"atr": {"atr14": 2.5}},
            }

        with (
            patch.object(
                ranking_service,
                "calculate_latest_stock_signals",
                side_effect=fake_signal_result,
            ),
            patch.object(
                ranking_service,
                "_market_context_by_stock",
                return_value={
                    "2330": {
                        "institutional": {
                            "trade_date": "2026-06-08",
                            "total_net": 1200,
                        },
                    },
                },
            ),
        ):
            rows = ranking_service._build_watchlist_ranking_rows(
                db=object(),
                items=[{"stock_id": "2330", "stock_name": "台積電"}],
                ma_windows="5,20,60",
                volume_ma_windows="5,20",
                limit=100,
                volume_ratio_threshold=1.5,
                use_intraday=False,
                intraday_limit=30,
            )

        self.assertEqual(rows[0]["context_snapshot"]["institutional"]["total_net"], 1200)

    def test_intraday_overlay_updates_context_snapshot(self):
        def fake_signal_result(*, stock_id: str, **_: object):
            return {
                "time": "2026-06-08",
                "close": 100.0,
                "volume": 1000,
                "change": 1.0,
                "change_pct": 1.0,
                "score": 7,
                "status": "ready",
                "signals": [{"key": "above_ma20", "label": "站上 MA20"}],
                "indicator_snapshot": {},
            }

        with (
            patch.object(
                ranking_service,
                "calculate_latest_stock_signals",
                side_effect=fake_signal_result,
            ),
            patch.object(
                ranking_service,
                "_market_context_by_stock",
                return_value={"2330": {"institutional": {"total_net": 1200}}},
            ),
            patch.object(
                ranking_service,
                "_get_intraday_overlay",
                return_value={
                    "time": "2026-06-08T10:00:00+08:00",
                    "close": 103.0,
                    "volume": 5000,
                    "change": 3.0,
                    "change_pct": 3.0,
                    "previous_close": 100.0,
                    "limit_status": None,
                    "points": [
                        {"time": "2026-06-08T09:00:00+08:00", "price": 101.0},
                        {"time": "2026-06-08T10:00:00+08:00", "price": 103.0},
                    ],
                    "source": "test",
                },
            ),
        ):
            rows = ranking_service._build_watchlist_ranking_rows(
                db=object(),
                items=[{"stock_id": "2330", "stock_name": "台積電"}],
                ma_windows="5,20,60",
                volume_ma_windows="5,20",
                limit=100,
                volume_ratio_threshold=1.5,
                use_intraday=True,
                intraday_limit=30,
            )

        self.assertEqual(rows[0]["context_snapshot"]["institutional"]["total_net"], 1200)
        self.assertEqual(rows[0]["context_snapshot"]["intraday"]["change_pct"], 3.0)
        self.assertAlmostEqual(
            rows[0]["context_snapshot"]["intraday"]["session_change_pct"],
            1.9802,
            places=4,
        )

    def test_intraday_overlay_cache_is_reused_across_ranking_scopes(self):
        signal_result = {
            "time": "2026-06-08",
            "close": 100.0,
            "volume": 1000,
            "change": 0.0,
            "change_pct": 0.0,
            "score": 0,
            "status": "ready",
            "signals": [],
            "indicator_snapshot": {},
        }
        cache: dict[str, dict | None] = {}

        with (
            patch.object(
                ranking_service,
                "calculate_latest_stock_signals",
                return_value=signal_result,
            ),
            patch.object(ranking_service, "_market_context_by_stock", return_value={}),
            patch.object(
                ranking_service,
                "_get_intraday_overlay",
                return_value=None,
            ) as get_overlay,
        ):
            for _ in range(2):
                ranking_service._build_watchlist_ranking_rows(
                    db=object(),
                    items=[{"stock_id": "2330", "stock_name": "TSMC"}],
                    ma_windows="5,20,60",
                    volume_ma_windows="5,20",
                    limit=100,
                    volume_ratio_threshold=1.5,
                    use_intraday=True,
                    intraday_limit=30,
                    intraday_overlay_cache=cache,
                )

        get_overlay.assert_called_once_with(db=ANY, stock_id="2330")
        self.assertIn("2330", cache)

    def test_unique_watchlist_items_follow_group_tree_order(self):
        def fake_list_items(*, group_id: int, **_: object):
            return {
                1: [
                    {"stock_id": "2330", "stock_name": "Beta"},
                    {"stock_id": "2303", "stock_name": "Delta"},
                ],
                2: [
                    {"stock_id": "2454", "stock_name": "Gamma"},
                    {"stock_id": "2330", "stock_name": "Duplicate"},
                ],
            }[group_id]

        with (
            patch.object(ranking_service.watchlist_service, "get_group", return_value={}),
            patch.object(
                ranking_service.watchlist_service,
                "get_group_tree",
                return_value=[
                    {
                        "id": 1,
                        "children": [
                            {"id": 2, "children": []},
                        ],
                    }
                ],
            ),
            patch.object(
                ranking_service.watchlist_service,
                "list_items",
                side_effect=fake_list_items,
            ),
        ):
            items = ranking_service._get_unique_watchlist_items(
                db=object(),
                group_id=1,
                include_children=True,
                enabled_only=True,
            )

        self.assertEqual(
            [item["stock_id"] for item in items],
            ["2330", "2303", "2454"],
        )


if __name__ == "__main__":
    unittest.main()
