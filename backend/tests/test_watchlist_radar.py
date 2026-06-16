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
        self.assertEqual(result["results"][0]["bucket"], "limit_up_move")
        self.assertEqual(result["results"][0]["bucket_label"], "漲停 / 急漲")
        self.assertEqual(result["results"][0]["urgency"], "high")
        self.assertEqual(result["results"][1]["bucket"], "risk")
        self.assertIn("cross_below_ma20", result["results"][1]["matched_signal_keys"])
        bucket_counts = {bucket["key"]: bucket["count"] for bucket in result["buckets"]}
        self.assertEqual(bucket_counts["limit_up_move"], 1)
        self.assertEqual(bucket_counts["limit_down_move"], 0)
        self.assertEqual(bucket_counts["risk"], 1)
        self.assertEqual(bucket_counts["breakout"], 0)

    def test_large_move_buckets_split_rising_and_falling(self):
        rows = [
            {
                "rank": 1,
                "stock_id": "3008",
                "stock_name": "大立光",
                "time": "2026-06-15",
                "close": 2500.0,
                "volume": 1500,
                "change": 190.0,
                "previous_close": 2310.0,
                "change_pct": 8.23,
                "limit_status": None,
                "score": 4,
                "status": "bullish",
                "signal_count": 2,
                "signal_keys": ["price_up", "volume_price_up"],
                "primary_signal_key": "price_up",
                "primary_signal_label": "上漲",
                "error_message": None,
            },
            {
                "rank": 2,
                "stock_id": "3661",
                "stock_name": "世芯-KY",
                "time": "2026-06-15",
                "close": 1800.0,
                "volume": 2500,
                "change": -200.0,
                "previous_close": 2000.0,
                "change_pct": -10.0,
                "limit_status": "limit_down",
                "score": -5,
                "status": "bearish",
                "signal_count": 2,
                "signal_keys": ["price_down", "volume_price_down"],
                "primary_signal_key": "price_down",
                "primary_signal_label": "下跌",
                "error_message": None,
            },
        ]

        result = radar_service.build_watchlist_radar_from_ranking(ranking=_ranking_payload(rows))
        items_by_stock = {item["stock_id"]: item for item in result["results"]}

        self.assertEqual(items_by_stock["3008"]["bucket"], "limit_up_move")
        self.assertEqual(items_by_stock["3008"]["bucket_label"], "漲停 / 急漲")
        self.assertEqual(items_by_stock["3008"]["action_label"], "留意追價與隔日回落風險")
        self.assertEqual(items_by_stock["3661"]["bucket"], "limit_down_move")
        self.assertEqual(items_by_stock["3661"]["bucket_label"], "跌停 / 急跌")
        self.assertEqual(items_by_stock["3661"]["action_label"], "優先檢查停損與流動性")

        bucket_counts = {bucket["key"]: bucket["count"] for bucket in result["buckets"]}
        self.assertEqual(bucket_counts["limit_up_move"], 1)
        self.assertEqual(bucket_counts["limit_down_move"], 1)

    def test_limit_status_takes_precedence_when_change_pct_direction_disagrees(self):
        rows = [
            {
                "rank": 1,
                "stock_id": "2330",
                "stock_name": "台積電",
                "time": "2026-06-15",
                "close": 1100.0,
                "volume": 50000,
                "change": -5.0,
                "previous_close": 1105.0,
                "change_pct": -0.45,
                "limit_status": "limit_up",
                "score": 5,
                "status": "bullish",
                "signal_count": 2,
                "signal_keys": ["price_up", "volume_price_up"],
                "primary_signal_key": "price_up",
                "primary_signal_label": "上漲",
                "error_message": None,
            },
            {
                "rank": 2,
                "stock_id": "2317",
                "stock_name": "鴻海",
                "time": "2026-06-15",
                "close": 150.0,
                "volume": 30000,
                "change": 5.0,
                "previous_close": 145.0,
                "change_pct": 3.45,
                "limit_status": "limit_down",
                "score": -5,
                "status": "bearish",
                "signal_count": 2,
                "signal_keys": ["price_down", "volume_price_down"],
                "primary_signal_key": "price_down",
                "primary_signal_label": "下跌",
                "error_message": None,
            },
        ]

        result = radar_service.build_watchlist_radar_from_ranking(ranking=_ranking_payload(rows))
        items_by_stock = {item["stock_id"]: item for item in result["results"]}

        self.assertEqual(items_by_stock["2330"]["bucket"], "limit_up_move")
        self.assertEqual(items_by_stock["2317"]["bucket"], "limit_down_move")

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

    def test_radar_modes_use_distinct_bucket_scopes(self):
        rows = [
            {
                "rank": 1,
                "stock_id": "3008",
                "stock_name": "大立光",
                "time": "2026-06-15",
                "close": 2500.0,
                "volume": 1500,
                "change": 190.0,
                "previous_close": 2310.0,
                "change_pct": 8.23,
                "limit_status": None,
                "score": 4,
                "status": "bullish",
                "signal_count": 2,
                "signal_keys": ["price_up", "volume_price_up"],
                "primary_signal_key": "price_up",
                "primary_signal_label": "上漲",
                "error_message": None,
            },
            {
                "rank": 2,
                "stock_id": "3661",
                "stock_name": "世芯-KY",
                "time": "2026-06-15",
                "close": 1800.0,
                "volume": 2500,
                "change": -200.0,
                "previous_close": 2000.0,
                "change_pct": -10.0,
                "limit_status": "limit_down",
                "score": -5,
                "status": "bearish",
                "signal_count": 2,
                "signal_keys": ["price_down", "volume_price_down"],
                "primary_signal_key": "price_down",
                "primary_signal_label": "下跌",
                "error_message": None,
            },
            {
                "rank": 3,
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
                "rank": 4,
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
                "rank": 5,
                "stock_id": "2303",
                "stock_name": "聯電",
                "time": "2026-06-15",
                "close": 55.0,
                "volume": 80000,
                "change": 0.2,
                "previous_close": 54.8,
                "change_pct": 0.36,
                "limit_status": None,
                "score": 1,
                "status": "neutral",
                "signal_count": 1,
                "signal_keys": ["volume_expansion"],
                "primary_signal_key": "volume_expansion",
                "primary_signal_label": "量能放大",
                "error_message": None,
            },
            {
                "rank": 6,
                "stock_id": "2357",
                "stock_name": "華碩",
                "time": "2026-06-15",
                "close": 480.0,
                "volume": 9000,
                "change": 3.0,
                "previous_close": 477.0,
                "change_pct": 0.63,
                "limit_status": None,
                "score": 4,
                "status": "bullish",
                "signal_count": 2,
                "signal_keys": ["above_ma20", "macd_positive"],
                "primary_signal_key": "above_ma20",
                "primary_signal_label": "站在 MA20 之上",
                "error_message": None,
            },
            {
                "rank": 7,
                "stock_id": "9998",
                "stock_name": "觀察股",
                "time": "2026-06-15",
                "close": 30.0,
                "volume": 1000,
                "change": 0.0,
                "previous_close": 30.0,
                "change_pct": 0.0,
                "limit_status": None,
                "score": 1,
                "status": "neutral",
                "signal_count": 1,
                "signal_keys": ["custom_signal"],
                "primary_signal_key": "custom_signal",
                "primary_signal_label": "自訂訊號",
                "error_message": None,
            },
        ]

        ranking = _ranking_payload(rows)

        action = radar_service.build_watchlist_radar_from_ranking(ranking=ranking, mode="action")
        risk = radar_service.build_watchlist_radar_from_ranking(ranking=ranking, mode="risk")
        momentum = radar_service.build_watchlist_radar_from_ranking(ranking=ranking, mode="momentum")
        all_items = radar_service.build_watchlist_radar_from_ranking(ranking=ranking, mode="all")

        self.assertEqual(
            {item["bucket"] for item in action["results"]},
            {"limit_up_move", "limit_down_move", "risk", "breakout", "volume"},
        )
        self.assertEqual(
            {item["bucket"] for item in risk["results"]},
            {"limit_down_move", "risk"},
        )
        self.assertEqual(
            {item["bucket"] for item in momentum["results"]},
            {"limit_up_move", "breakout", "volume", "momentum"},
        )
        self.assertEqual(
            {item["bucket"] for item in all_items["results"]},
            {
                "limit_up_move",
                "limit_down_move",
                "risk",
                "breakout",
                "volume",
                "momentum",
                "watch",
            },
        )

        risk_bucket_counts = {bucket["key"]: bucket["count"] for bucket in risk["buckets"]}
        momentum_bucket_counts = {bucket["key"]: bucket["count"] for bucket in momentum["buckets"]}
        self.assertNotIn("limit_up_move", risk_bucket_counts)
        self.assertNotIn("limit_down_move", momentum_bucket_counts)
        self.assertEqual(risk_bucket_counts["limit_down_move"], 1)
        self.assertEqual(momentum_bucket_counts["limit_up_move"], 1)

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
