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
        self.assertEqual(result["results"][0]["bucket"], "limit_up_lock")
        self.assertEqual(result["results"][0]["bucket_label"], "漲停鎖強")
        self.assertEqual(result["results"][0]["urgency"], "high")
        self.assertEqual(result["results"][1]["bucket"], "support_break")
        self.assertIn("cross_below_ma20", result["results"][1]["matched_signal_keys"])
        bucket_counts = {bucket["key"]: bucket["count"] for bucket in result["buckets"]}
        self.assertEqual(bucket_counts["limit_up_lock"], 1)
        self.assertEqual(bucket_counts["limit_down_liquidity"], 0)
        self.assertEqual(bucket_counts["support_break"], 1)
        self.assertEqual(bucket_counts["breakout_high"], 0)

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

        self.assertEqual(items_by_stock["3008"]["bucket"], "surge_up")
        self.assertEqual(items_by_stock["3008"]["bucket_label"], "急漲追價")
        self.assertEqual(items_by_stock["3008"]["action_label"], "留意追價與隔日回落風險")
        self.assertEqual(items_by_stock["3661"]["bucket"], "limit_down_liquidity")
        self.assertEqual(items_by_stock["3661"]["bucket_label"], "跌停流動性")
        self.assertEqual(items_by_stock["3661"]["action_label"], "優先檢查停損與流動性")

        bucket_counts = {bucket["key"]: bucket["count"] for bucket in result["buckets"]}
        self.assertEqual(bucket_counts["surge_up"], 1)
        self.assertEqual(bucket_counts["limit_down_liquidity"], 1)

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

        self.assertEqual(items_by_stock["2330"]["bucket"], "limit_up_lock")
        self.assertEqual(items_by_stock["2317"]["bucket"], "limit_down_liquidity")

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
        self.assertEqual(result["results"][0]["bucket"], "trend_reclaim")

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
        surge = radar_service.build_watchlist_radar_from_ranking(ranking=ranking, mode="surge")
        breakout = radar_service.build_watchlist_radar_from_ranking(ranking=ranking, mode="breakout")
        volume = radar_service.build_watchlist_radar_from_ranking(ranking=ranking, mode="volume")
        weakness = radar_service.build_watchlist_radar_from_ranking(ranking=ranking, mode="weakness")
        risk = radar_service.build_watchlist_radar_from_ranking(ranking=ranking, mode="risk")
        momentum = radar_service.build_watchlist_radar_from_ranking(ranking=ranking, mode="momentum")
        all_items = radar_service.build_watchlist_radar_from_ranking(ranking=ranking, mode="all")

        self.assertEqual(
            {item["bucket"] for item in action["results"]},
            {"surge_up", "limit_down_liquidity", "support_break", "trend_reclaim", "volume"},
        )
        self.assertEqual(
            {item["bucket"] for item in surge["results"]},
            {"surge_up"},
        )
        self.assertEqual(
            {item["bucket"] for item in breakout["results"]},
            {"trend_reclaim"},
        )
        self.assertEqual(
            {item["bucket"] for item in volume["results"]},
            {"volume"},
        )
        self.assertEqual(
            {item["bucket"] for item in weakness["results"]},
            {"limit_down_liquidity", "support_break"},
        )
        self.assertEqual(
            {item["bucket"] for item in risk["results"]},
            {"limit_down_liquidity", "support_break"},
        )
        self.assertEqual(
            {item["bucket"] for item in momentum["results"]},
            {"surge_up", "trend_reclaim", "volume", "momentum"},
        )
        self.assertEqual(
            {item["bucket"] for item in all_items["results"]},
            {
                "surge_up",
                "limit_down_liquidity",
                "support_break",
                "trend_reclaim",
                "volume",
                "momentum",
                "watch",
            },
        )

        risk_bucket_counts = {bucket["key"]: bucket["count"] for bucket in risk["buckets"]}
        momentum_bucket_counts = {bucket["key"]: bucket["count"] for bucket in momentum["buckets"]}
        self.assertNotIn("surge_up", risk_bucket_counts)
        self.assertNotIn("limit_down_liquidity", momentum_bucket_counts)
        self.assertEqual(risk_bucket_counts["limit_down_liquidity"], 1)
        self.assertEqual(momentum_bucket_counts["surge_up"], 1)

    def test_signal_buckets_split_generic_risk_and_momentum_labels(self):
        rows = [
            {
                "rank": 1,
                "stock_id": "1111",
                "stock_name": "過熱股",
                "time": "2026-06-15",
                "close": 110.0,
                "volume": 12000,
                "change": 3.0,
                "previous_close": 107.0,
                "change_pct": 2.8,
                "limit_status": None,
                "score": 3,
                "status": "bullish",
                "signal_count": 1,
                "signal_keys": ["rsi_overheated"],
                "primary_signal_key": "rsi_overheated",
                "primary_signal_label": "RSI 過熱",
                "error_message": None,
            },
            {
                "rank": 2,
                "stock_id": "2222",
                "stock_name": "量價轉弱",
                "time": "2026-06-15",
                "close": 80.0,
                "volume": 30000,
                "change": -2.0,
                "previous_close": 82.0,
                "change_pct": -2.44,
                "limit_status": None,
                "score": -2,
                "status": "bearish",
                "signal_count": 1,
                "signal_keys": ["volume_price_down"],
                "primary_signal_key": "volume_price_down",
                "primary_signal_label": "量增價跌",
                "error_message": None,
            },
            {
                "rank": 3,
                "stock_id": "3333",
                "stock_name": "動能轉弱",
                "time": "2026-06-15",
                "close": 60.0,
                "volume": 9000,
                "change": -1.0,
                "previous_close": 61.0,
                "change_pct": -1.64,
                "limit_status": None,
                "score": -2,
                "status": "bearish",
                "signal_count": 1,
                "signal_keys": ["macd_negative"],
                "primary_signal_key": "macd_negative",
                "primary_signal_label": "MACD 偏空",
                "error_message": None,
            },
            {
                "rank": 4,
                "stock_id": "4444",
                "stock_name": "突破股",
                "time": "2026-06-15",
                "close": 120.0,
                "volume": 15000,
                "change": 4.0,
                "previous_close": 116.0,
                "change_pct": 3.45,
                "limit_status": None,
                "score": 4,
                "status": "bullish",
                "signal_count": 1,
                "signal_keys": ["donchian_breakout"],
                "primary_signal_key": "donchian_breakout",
                "primary_signal_label": "突破 20 日高",
                "error_message": None,
            },
            {
                "rank": 5,
                "stock_id": "5555",
                "stock_name": "攻擊股",
                "time": "2026-06-15",
                "close": 50.0,
                "volume": 20000,
                "change": 1.5,
                "previous_close": 48.5,
                "change_pct": 3.09,
                "limit_status": None,
                "score": 2,
                "status": "bullish",
                "signal_count": 1,
                "signal_keys": ["volume_price_up"],
                "primary_signal_key": "volume_price_up",
                "primary_signal_label": "量增價漲",
                "error_message": None,
            },
        ]

        result = radar_service.build_watchlist_radar_from_ranking(
            ranking=_ranking_payload(rows),
            mode="all",
        )
        overheat = radar_service.build_watchlist_radar_from_ranking(
            ranking=_ranking_payload(rows),
            mode="overheat",
        )
        items_by_stock = {item["stock_id"]: item for item in result["results"]}

        self.assertEqual(items_by_stock["1111"]["bucket"], "overheated")
        self.assertEqual(items_by_stock["1111"]["bucket_label"], "過熱警戒")
        self.assertEqual(items_by_stock["2222"]["bucket"], "volume_down")
        self.assertEqual(items_by_stock["2222"]["bucket_label"], "量價轉弱")
        self.assertEqual(items_by_stock["2222"]["matched_signal_labels"], ["量增價跌"])
        self.assertEqual(items_by_stock["3333"]["bucket"], "bearish_momentum")
        self.assertEqual(items_by_stock["3333"]["bucket_label"], "動能轉弱")
        self.assertEqual(items_by_stock["3333"]["matched_signal_labels"], ["MACD 偏空"])
        self.assertEqual(items_by_stock["4444"]["bucket"], "breakout_high")
        self.assertEqual(items_by_stock["4444"]["bucket_label"], "突破確認")
        self.assertEqual(items_by_stock["4444"]["matched_signal_labels"], ["突破 20 日高"])
        self.assertEqual(items_by_stock["5555"]["bucket"], "volume_up")
        self.assertEqual(items_by_stock["5555"]["bucket_label"], "量價攻擊")
        self.assertEqual(items_by_stock["5555"]["matched_signal_labels"], ["量增價漲"])
        self.assertEqual(
            {item["bucket"] for item in overheat["results"]},
            {"overheated"},
        )

    def test_technical_setup_fields_cover_volatility_breakout_and_compression(self):
        rows = [
            {
                "rank": 1,
                "stock_id": "1111",
                "stock_name": "高波動股",
                "time": "2026-06-15",
                "close": 100.0,
                "volume": 12000,
                "change": 2.0,
                "previous_close": 98.0,
                "change_pct": 2.04,
                "limit_status": None,
                "score": 1,
                "status": "bullish",
                "signal_count": 1,
                "signal_keys": ["atr_high_volatility"],
                "primary_signal_key": "atr_high_volatility",
                "primary_signal_label": "ATR 高波動",
                "indicator_snapshot": {
                    "atr": {"atr14": 6.0},
                    "ma": {"ma20": 94.0},
                    "support_resistance": {"support20": 92.0, "resistance20": 108.0},
                },
                "error_message": None,
            },
            {
                "rank": 2,
                "stock_id": "2222",
                "stock_name": "突破股",
                "time": "2026-06-15",
                "close": 122.0,
                "volume": 20000,
                "change": 5.0,
                "previous_close": 117.0,
                "change_pct": 4.27,
                "limit_status": None,
                "score": 5,
                "status": "strong_bullish",
                "signal_count": 2,
                "signal_keys": ["bollinger_breakout", "structure_resistance_breakout"],
                "primary_signal_key": "bollinger_breakout",
                "primary_signal_label": "突破布林上緣",
                "indicator_snapshot": {
                    "bollinger": {"upper20": 120.0, "lower20": 90.0},
                    "ma": {"ma20": 105.0},
                    "support_resistance": {"support20": 96.0, "resistance20": 118.0},
                },
                "error_message": None,
            },
            {
                "rank": 3,
                "stock_id": "3333",
                "stock_name": "壓縮股",
                "time": "2026-06-15",
                "close": 50.0,
                "volume": 9000,
                "change": 0.1,
                "previous_close": 49.9,
                "change_pct": 0.2,
                "limit_status": None,
                "score": 0,
                "status": "neutral",
                "signal_count": 1,
                "signal_keys": ["bollinger_squeeze"],
                "primary_signal_key": "bollinger_squeeze",
                "primary_signal_label": "布林壓縮",
                "indicator_snapshot": {
                    "bollinger": {"upper20": 52.0, "lower20": 48.0, "bandwidth20_pct": 8.0},
                    "support_resistance": {"support20": 47.5, "resistance20": 52.5},
                },
                "error_message": None,
            },
            {
                "rank": 4,
                "stock_id": "4444",
                "stock_name": "KD過熱",
                "time": "2026-06-15",
                "close": 80.0,
                "volume": 10000,
                "change": 1.0,
                "previous_close": 79.0,
                "change_pct": 1.27,
                "limit_status": None,
                "score": 2,
                "status": "bullish",
                "signal_count": 1,
                "signal_keys": ["kd_overbought"],
                "primary_signal_key": "kd_overbought",
                "primary_signal_label": "KD 過熱",
                "indicator_snapshot": {
                    "kd": {"k9": 88.0, "d9": 82.0},
                    "support_resistance": {"support20": 74.0, "resistance20": 83.0},
                },
                "error_message": None,
            },
        ]

        result = radar_service.build_watchlist_radar_from_ranking(
            ranking=_ranking_payload(rows),
            mode="all",
        )
        items_by_stock = {item["stock_id"]: item for item in result["results"]}

        self.assertEqual(items_by_stock["1111"]["bucket"], "volatility_risk")
        self.assertEqual(items_by_stock["1111"]["direction_label"], "分歧")
        self.assertEqual(items_by_stock["1111"]["risk_label"], "波動擴大")
        self.assertEqual(items_by_stock["1111"]["price_levels"]["atr_pct"], 6.0)
        self.assertEqual(items_by_stock["2222"]["bucket"], "breakout_high")
        self.assertEqual(items_by_stock["2222"]["bucket_label"], "突破確認")
        self.assertEqual(items_by_stock["2222"]["direction"], "bullish")
        self.assertEqual(items_by_stock["2222"]["setup_label"], "突破確認")
        self.assertIn("突破布林上緣", items_by_stock["2222"]["technical_notes"])
        self.assertEqual(items_by_stock["3333"]["bucket"], "compression_watch")
        self.assertEqual(items_by_stock["3333"]["timing_label"], "等方向確認")
        self.assertEqual(items_by_stock["3333"]["price_levels"]["key_level_label"], "突破壓力")
        self.assertEqual(items_by_stock["4444"]["bucket"], "overheated")
        self.assertEqual(items_by_stock["4444"]["matched_signal_labels"], ["KD 過熱"])
        grade_values = {item["technical_grade"] for item in result["results"]}
        self.assertEqual(result["results"][0]["technical_grade"], "strong")
        self.assertEqual(result["results"][0]["technical_grade_label"], "強訊號")
        self.assertIn("medium", grade_values)
        self.assertIn("watch", grade_values)

    def test_context_signals_turn_market_data_into_confirmation_labels(self):
        rows = [
            {
                "rank": 1,
                "stock_id": "2330",
                "stock_name": "台積電",
                "time": "2026-06-15",
                "close": 122.0,
                "volume": 20000,
                "change": 5.0,
                "previous_close": 117.0,
                "change_pct": 4.27,
                "limit_status": None,
                "score": 5,
                "status": "strong_bullish",
                "signal_count": 2,
                "signal_keys": ["donchian_breakout", "volume_price_up"],
                "primary_signal_key": "donchian_breakout",
                "primary_signal_label": "突破 20 日高",
                "context_snapshot": {
                    "intraday": {
                        "change_pct": 2.4,
                        "session_change_pct": 0.8,
                    },
                    "institutional": {
                        "trade_date": "2026-06-15",
                        "total_net": 1500,
                    },
                    "margin": {
                        "trade_date": "2026-06-15",
                        "margin_balance_change": 500,
                    },
                    "revenue": {
                        "period": "2026-05-01",
                        "year_over_year_pct": 18.5,
                    },
                    "financial": {
                        "period": "2026Q1",
                        "eps": 8.0,
                        "roe": 24.0,
                    },
                },
                "error_message": None,
            },
        ]

        result = radar_service.build_watchlist_radar_from_ranking(
            ranking=_ranking_payload(rows),
            mode="momentum",
        )
        item = result["results"][0]
        labels = [signal["label"] for signal in item["context_signals"]]

        self.assertEqual(item["context_snapshot"]["institutional"]["total_net"], 1500)
        self.assertIn("盤中續強", labels)
        self.assertIn("法人確認", labels)
        self.assertIn("融資跟進", labels)
        self.assertIn("營收背書", labels)
        self.assertGreater(item["context_score"], 0)
        self.assertEqual(item["context_summary"], "盤中續強 · 法人確認 · 融資跟進")

    def test_context_signals_mark_contradiction_and_overheated_leverage(self):
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
                "context_snapshot": {
                    "institutional": {
                        "trade_date": "2026-06-15",
                        "total_net": -800,
                    },
                    "margin": {
                        "trade_date": "2026-06-15",
                        "margin_balance_change": 900,
                    },
                },
                "error_message": None,
            },
        ]

        result = radar_service.build_watchlist_radar_from_ranking(
            ranking=_ranking_payload(rows),
            mode="action",
        )
        labels = [signal["label"] for signal in result["results"][0]["context_signals"]]

        self.assertIn("法人背離", labels)
        self.assertIn("融資過熱", labels)
        self.assertLess(result["results"][0]["context_score"], 0)

    def test_priority_uses_technical_evidence_breadth(self):
        rows = [
            {
                "rank": 1,
                "stock_id": "1111",
                "stock_name": "單一破線",
                "time": "2026-06-15",
                "close": 80.0,
                "volume": 10000,
                "change": -2.0,
                "previous_close": 82.0,
                "change_pct": -2.44,
                "limit_status": None,
                "score": -3,
                "status": "bearish",
                "signal_count": 1,
                "signal_keys": ["cross_below_ma20"],
                "primary_signal_key": "cross_below_ma20",
                "primary_signal_label": "跌破 MA20",
                "error_message": None,
            },
            {
                "rank": 2,
                "stock_id": "2222",
                "stock_name": "多重轉弱",
                "time": "2026-06-15",
                "close": 80.0,
                "volume": 10000,
                "change": -2.0,
                "previous_close": 82.0,
                "change_pct": -2.44,
                "limit_status": None,
                "score": -3,
                "status": "bearish",
                "signal_count": 4,
                "signal_keys": [
                    "cross_below_ma20",
                    "volume_price_down",
                    "macd_negative",
                    "roc_negative",
                ],
                "primary_signal_key": "cross_below_ma20",
                "primary_signal_label": "跌破 MA20",
                "error_message": None,
            },
        ]

        result = radar_service.build_watchlist_radar_from_ranking(
            ranking=_ranking_payload(rows),
            mode="risk",
        )

        self.assertEqual(result["results"][0]["stock_id"], "2222")
        self.assertGreater(
            result["results"][0]["technical_evidence_score"],
            result["results"][1]["technical_evidence_score"],
        )

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
