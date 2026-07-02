from __future__ import annotations

from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, StockMaster, TaiwanStockQuoteSnapshot
from app.market.quote_depth import (
    _QUOTE_DEPTH_CACHE,
    get_taiwan_stock_quote_depth,
    resolve_taiwan_stock_quote_phase,
)
from app.market.trading_calendar import TAIWAN_TZ


class FakeResponse:
    def __init__(self, payload: dict, url: str = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"):
        self._payload = payload
        self.url = url

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return Session(engine)


def sample_payload(*, stock_id: str = "2330", channel: str = "tse_2330.tw") -> dict:
    return {
        "msgArray": [
            {
                "c": stock_id,
                "n": "TSMC",
                "ch": channel,
                "d": "20260630",
                "t": "09:05:12",
                "z": "2410",
                "y": "2370",
                "o": "2380",
                "h": "2420",
                "l": "2375",
                "v": "49540",
                "b": "2410_2405_2400_2395_2390_",
                "g": "978_1150_1399_599_924_",
                "a": "2415_2420_2425_2430_2435_",
                "f": "2_209_209_3_1_",
            }
        ]
    }


class TaiwanStockQuoteDepthTests(unittest.TestCase):
    def setUp(self) -> None:
        _QUOTE_DEPTH_CACHE.clear()
        self.db = make_session()
        self.db.add(
            StockMaster(
                stock_id="2330",
                stock_name="TSMC",
                market="TWSE",
                instrument_type="stock",
            )
        )
        self.db.commit()

    def tearDown(self) -> None:
        _QUOTE_DEPTH_CACHE.clear()
        self.db.close()

    def test_session_phase_boundaries_follow_taiwan_stock_depth_rules(self) -> None:
        cases = {
            "2026-06-30T04:59:00+08:00": "post_close_snapshot",
            "2026-06-30T05:00:00+08:00": "closed_waiting_preopen",
            "2026-06-30T08:29:00+08:00": "closed_waiting_preopen",
            "2026-06-30T08:30:00+08:00": "preopen_auction",
            "2026-06-30T09:00:00+08:00": "regular_live",
            "2026-06-30T13:24:00+08:00": "regular_live",
            "2026-06-30T13:25:00+08:00": "closing_auction",
            "2026-06-30T13:30:00+08:00": "closing_auction",
            "2026-06-30T13:31:00+08:00": "post_close_snapshot",
            "2026-06-28T09:00:00+08:00": "market_closed",
        }

        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(resolve_taiwan_stock_quote_phase(datetime.fromisoformat(value)), expected)

    def test_live_quote_depth_parses_mis_levels_and_persists_snapshot(self) -> None:
        now = datetime(2026, 6, 30, 9, 5, tzinfo=TAIWAN_TZ)
        fetched_at = datetime(2026, 6, 30, 1, 5, tzinfo=timezone.utc)
        payload = sample_payload()

        with (
            patch("app.market.quote_depth.utc_now", return_value=fetched_at),
            patch("app.market.quote_depth.http_get", return_value=FakeResponse(payload)) as http_get,
        ):
            result = get_taiwan_stock_quote_depth(db=self.db, stock_id="2330", now=now)

        http_get.assert_called_once()
        self.assertEqual(http_get.call_args.kwargs["params"]["ex_ch"], "tse_2330.tw")
        self.assertEqual(result["session_phase"], "regular_live")
        self.assertEqual(result["freshness"]["status"], "live")
        self.assertTrue(result["depth_available"])
        self.assertEqual(result["best_bid_price"], 2410.0)
        self.assertEqual(result["best_bid_size_lots"], 978)
        self.assertEqual(result["best_ask_price"], 2415.0)
        self.assertEqual(result["best_ask_size_lots"], 2)
        self.assertEqual(result["spread"], 5.0)
        self.assertAlmostEqual(result["change_pct"], 40 / 2370 * 100)
        self.assertEqual(len(result["bid_levels"]), 5)
        self.assertEqual(len(result["ask_levels"]), 5)
        self.assertEqual(result["bid_total_size_lots"], 5050)
        self.assertEqual(result["ask_total_size_lots"], 424)

        rows = self.db.query(TaiwanStockQuoteSnapshot).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].stock_id, "2330")
        self.assertEqual(rows[0].quote_time.isoformat(), "2026-06-30T09:05:12")

    def test_tpex_stock_uses_otc_exchange_channel(self) -> None:
        self.db.add(
            StockMaster(
                stock_id="8069",
                stock_name="E Ink",
                market="TPEX",
                instrument_type="stock",
            )
        )
        self.db.commit()
        now = datetime(2026, 6, 30, 9, 5, tzinfo=TAIWAN_TZ)
        fetched_at = datetime(2026, 6, 30, 1, 5, tzinfo=timezone.utc)

        with (
            patch("app.market.quote_depth.utc_now", return_value=fetched_at),
            patch(
                "app.market.quote_depth.http_get",
                return_value=FakeResponse(sample_payload(stock_id="8069", channel="otc_8069.tw")),
            ) as http_get,
        ):
            result = get_taiwan_stock_quote_depth(db=self.db, stock_id="8069", now=now)

        self.assertEqual(http_get.call_args.kwargs["params"]["ex_ch"], "otc_8069.tw")
        self.assertEqual(result["exchange_channel"], "otc_8069.tw")

    def test_early_morning_wait_state_returns_empty_without_fetch(self) -> None:
        now = datetime(2026, 6, 30, 5, 15, tzinfo=TAIWAN_TZ)

        with patch("app.market.quote_depth.http_get") as http_get:
            result = get_taiwan_stock_quote_depth(db=self.db, stock_id="2330", now=now)

        http_get.assert_not_called()
        self.assertEqual(result["session_phase"], "closed_waiting_preopen")
        self.assertEqual(result["freshness"]["status"], "empty")
        self.assertFalse(result["depth_available"])
        self.assertEqual(result["bid_levels"], [])
        self.assertEqual(result["ask_levels"], [])

    def test_fetch_failure_falls_back_to_latest_snapshot_with_visible_status(self) -> None:
        now = datetime(2026, 6, 30, 9, 5, tzinfo=TAIWAN_TZ)
        fetched_at = datetime(2026, 6, 30, 1, 5, tzinfo=timezone.utc)

        with (
            patch("app.market.quote_depth.utc_now", return_value=fetched_at),
            patch("app.market.quote_depth.http_get", return_value=FakeResponse(sample_payload())),
        ):
            get_taiwan_stock_quote_depth(db=self.db, stock_id="2330", now=now)

        _QUOTE_DEPTH_CACHE.clear()

        with patch("app.market.quote_depth.http_get", side_effect=RuntimeError("MIS down")):
            result = get_taiwan_stock_quote_depth(db=self.db, stock_id="2330", now=now)

        self.assertEqual(result["freshness"]["status"], "cached")
        self.assertEqual(result["freshness"]["source_error"], "MIS down")
        self.assertTrue(result["freshness"]["is_stale"])
        self.assertEqual(result["best_bid_price"], 2410.0)


if __name__ == "__main__":
    unittest.main()
