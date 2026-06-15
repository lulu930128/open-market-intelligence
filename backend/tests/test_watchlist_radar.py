from datetime import date
import unittest
from unittest.mock import patch

from app.watchlists import radar_service


def _ranking_payload(rows: list[dict]) -> dict:
    return {
        "group_id": 7,
        "include_children": True,
        "rank_by": "score",
        "sort_order": "desc",
        "requested_stock_count": len(rows),
        "ranked_count": len([row for row in rows if row.get("status") not in {"no_data", "error"}]),
        "no_data_count": len([row for row in rows if row.get("status") == "no_data"]),
        "error_count": len([row for row in rows if row.get("status") == "error"]),
        "trade_date": date(2026, 6, 15),
        "target_trade_date": date(2026, 6, 15),
        "is_current": True,
        "current_stock_count": len(rows),
        "stale_stock_count": 0,
        "results": rows,
    }


class WatchlistRadarServiceTests(unittest.TestCase):
    def test_action_mode_prioritizes_large_move_and_risk(self):
        rows = [
            {
                "rank": 1,
                "stock_id": "2330",
                "stock_name": "台積電",
                "time": "2026-06-15",
                "close": 1100.0,
                "volume": 50000,
                "change": 98.0,
                "previous_close": 1002.0,
                "change_pct": 9.78,
                "limit_status": "limit_up",
                "score": 6,
                "status": "strong_bullish",
                "signal_count": 3,
                "signal_keys": ["donchian_breakout", "volume_price_up", "price_up"],
                "primary_signal_key": "donchian_breakout",
                "primary_signal_label": "突破 20 日高",
                "error_message": None,
            },
            {
                "rank": 2,
                "stock_id": "2317",
                "stock_name": "鴻海",
                "time": "2026-06-15",
                "close": 160.0,
                "volume": 70000,
                "change": -7.0,
                "previous_close": 167.0,
                "change_pct": -4.19,
                "limit_status": None,
                "score": -6,
                "status": "strong_bearish",
                "signal_count": 2,
                "signal_keys": ["cross_below_ma20", "volume_price_down"],
                "primary_signal_key": "cross_below_ma20",
                "primary_signal_label": "跌破 MA20",
                "error_message": None,
            },
            {
                "rank": 3,
                "stock_id": "9999",
                "stock_name": "無資料",
                "time": None,
                "close": None,
                "volume": None,
                "change": None,
                "previous_close": None,
                "change_pct": None,
                "limit_status": None,
                "score": 0,
                "status": "no_data",
                "signal_count": 0,
                "signal_keys": [],
                "primary_signal_key": None,
                "primary_signal_label": None,
                "error_message": None,
            },
        ]

        with patch.object(
            radar_service.ranking_service,
            "get_watchlist_group_latest_ranking",
            return_value=_ranking_payload(rows),
        ):
            result = radar_service.get_watchlist_group_radar(db=object(), group_id=7)

        self.assertEqual(result["matched_count"], 2)
        self.assertEqual(result["radar_count"], 2)
        self.assertEqual(result["results"][0]["stock_id"], "2330")
        self.assertEqual(result["results"][0]["bucket"], "limit_move")
        self.assertEqual(result["results"][0]["urgency"], "high")
        self.assertEqual(result["results"][1]["bucket"], "risk")
        self.assertIn("cross_below_ma20", result["results"][1]["matched_signal_keys"])
        bucket_counts = {bucket["key"]: bucket["count"] for bucket in result["buckets"]}
        self.assertEqual(bucket_counts["limit_move"], 1)
        self.assertEqual(bucket_counts["risk"], 1)
        self.assertEqual(bucket_counts["breakout"], 0)

    def test_momentum_mode_filters_out_risk_rows(self):
        rows = [
            {
                "rank": 1,
                "stock_id": "2454",
                "stock_name": "聯發科",
                "time": "2026-06-15",
                "close": 1500.0,
                "volume": 30000,
                "change": 40.0,
                "previous_close": 1460.0,
                "change_pct": 2.74,
                "limit_status": None,
                "score": 5,
                "status": "strong_bullish",
                "signal_count": 2,
                "signal_keys": ["cross_above_ma20", "macd_positive"],
                "primary_signal_key": "cross_above_ma20",
                "primary_signal_label": "重新站上 MA20",
                "error_message": None,
            },
            {
                "rank": 2,
                "stock_id": "2317",
                "stock_name": "鴻海",
                "time": "2026-06-15",
                "close": 160.0,
                "volume": 70000,
                "change": -7.0,
                "previous_close": 167.0,
                "change_pct": -4.19,
                "limit_status": None,
                "score": -6,
                "status": "strong_bearish",
                "signal_count": 1,
                "signal_keys": ["cross_below_ma20"],
                "primary_signal_key": "cross_below_ma20",
                "primary_signal_label": "跌破 MA20",
                "error_message": None,
            },
        ]

        with patch.object(
            radar_service.ranking_service,
            "get_watchlist_group_latest_ranking",
            return_value=_ranking_payload(rows),
        ):
            result = radar_service.get_watchlist_group_radar(
                db=object(),
                group_id=7,
                mode="momentum",
            )

        self.assertEqual(result["matched_count"], 1)
        self.assertEqual(result["results"][0]["stock_id"], "2454")
        self.assertEqual(result["results"][0]["bucket"], "breakout")

    def test_stale_rows_are_flagged_and_capped_below_high_urgency(self):
        rows = [
            {
                "rank": 1,
                "stock_id": "2330",
                "stock_name": "台積電",
                "time": "2026-06-12",
                "close": 1000.0,
                "volume": 50000,
                "change": 80.0,
                "previous_close": 920.0,
                "change_pct": 8.7,
                "limit_status": None,
                "score": 5,
                "status": "strong_bullish",
                "signal_count": 2,
                "signal_keys": ["donchian_breakout", "volume_price_up"],
                "primary_signal_key": "donchian_breakout",
                "primary_signal_label": "突破 20 日高",
                "error_message": None,
            },
        ]

        with patch.object(
            radar_service.ranking_service,
            "get_watchlist_group_latest_ranking",
            return_value=_ranking_payload(rows),
        ):
            result = radar_service.get_watchlist_group_radar(db=object(), group_id=7)

        item = result["results"][0]
        self.assertTrue(item["stale"])
        self.assertEqual(item["urgency"], "medium")
        self.assertIn("落後目標 2026-06-15", item["reason"])


if __name__ == "__main__":
    unittest.main()
