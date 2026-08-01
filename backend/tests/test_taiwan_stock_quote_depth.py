from __future__ import annotations

from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    MarketDailyPrice,
    RawFetchResult,
    SourceRegistry,
    StockMaster,
    TaiwanQuoteContractSnapshot,
    TaiwanStockQuoteSnapshot,
)
from app.jobs.taiwan_quote_contract_scheduler import (
    add_taiwan_quote_contract_snapshot_jobs,
)
from app.market.quote_depth import (
    _QUOTE_DEPTH_CACHE,
    TAIWAN_QUOTE_CONTRACT_SLOTS,
    capture_taiwan_quote_contract_snapshot,
    get_taiwan_quote_contract_replay,
    get_taiwan_stock_quote_depth,
    reset_twse_mis_quote_depth_guard,
    resolve_taiwan_stock_quote_phase,
)
from app.market.schemas import TaiwanStockQuoteDepthRead
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
                "tv": "750",
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
        reset_twse_mis_quote_depth_guard()
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
        reset_twse_mis_quote_depth_guard()
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
        now = datetime(2026, 6, 30, 9, 5, 42, tzinfo=TAIWAN_TZ)
        fetched_at = datetime(2026, 6, 30, 1, 5, 42, tzinfo=timezone.utc)
        payload = sample_payload()

        with (
            patch("app.market.quote_depth.utc_now", return_value=fetched_at),
            patch("app.market.quote_depth.http_get", return_value=FakeResponse(payload)) as http_get,
        ):
            result = get_taiwan_stock_quote_depth(db=self.db, stock_id="2330", now=now)
            cached_result = get_taiwan_stock_quote_depth(
                db=self.db,
                stock_id="2330",
                now=now,
            )

        http_get.assert_called_once()
        self.assertEqual(http_get.call_args.kwargs["params"]["ex_ch"], "tse_2330.tw")
        self.assertEqual(result["session_phase"], "regular_live")
        self.assertEqual(result["freshness"]["status"], "live")
        self.assertEqual(result["freshness"]["age_seconds"], 30)
        self.assertEqual(result["freshness"]["fetch_age_seconds"], 0)
        self.assertEqual(
            result["quote_time"].isoformat(),
            "2026-06-30T09:05:12+08:00",
        )
        self.assertEqual(
            result["snapshot_time"].isoformat(),
            "2026-06-30T09:05:42+08:00",
        )
        self.assertEqual(
            result["quote_time_basis"],
            "provider_exchange_event_time",
        )
        self.assertEqual(result["event_age_seconds"], 30)
        self.assertIsNone(result["network_latency_ms"])
        self.assertEqual(
            result["provider_event_time"].isoformat(),
            "2026-06-30T09:05:12+08:00",
        )
        self.assertEqual(result["last_trade_time"], result["provider_event_time"])
        self.assertEqual(result["refresh_outcome"], "updated")
        self.assertEqual(cached_result["refresh_outcome"], "cache_hit")
        self.assertTrue(result["depth_available"])
        self.assertEqual(result["best_bid_price"], 2410.0)
        self.assertEqual(result["best_bid_size_lots"], 978)
        self.assertEqual(result["best_ask_price"], 2415.0)
        self.assertEqual(result["best_ask_size_lots"], 2)
        self.assertEqual(result["spread"], 5.0)
        self.assertAlmostEqual(result["change_pct"], 40 / 2370 * 100)
        self.assertEqual(len(result["bid_levels"]), 5)
        self.assertEqual(len(result["ask_levels"]), 5)
        self.assertEqual(result["bid_depth"], result["bid_levels"])
        self.assertEqual(result["ask_depth"], result["ask_levels"])
        self.assertEqual(result["bid_depth"][0]["volume_lots"], 978)
        self.assertIsNone(result["bid_depth"][0]["order_count"])
        self.assertEqual(
            result["bid_depth"][0]["order_count_status"],
            "not_provided",
        )
        self.assertEqual(result["bid_total_size_lots"], 5050)
        self.assertEqual(result["ask_total_size_lots"], 424)
        self.assertEqual(result["top5_bid_volume_lots"], 5050)
        self.assertEqual(result["top5_ask_volume_lots"], 424)
        self.assertAlmostEqual(
            result["top5_imbalance"],
            (5050 - 424) / (5050 + 424),
        )
        self.assertEqual(result["depth_volume_unit"], "lots")
        self.assertEqual(result["depth_order_count_status"], "not_provided")
        self.assertEqual(result["total_volume_lots"], 49_540)
        self.assertEqual(result["cumulative_volume_lots"], 49_540)
        self.assertEqual(result["cumulative_volume_shares"], 49_540_000)
        self.assertEqual(result["last_trade_volume_lots"], 750)
        self.assertEqual(result["last_trade_volume_shares"], 750_000)
        self.assertEqual(result["volume_source_field"], "v")
        self.assertEqual(result["last_trade_volume_source_field"], "tv")
        self.assertEqual(result["volume_reconciliation"]["status"], "not_comparable")
        self.assertEqual(
            result["volume_reconciliation"]["reason"],
            "official_daily_volume_not_available",
        )
        self.assertEqual(
            result["ohlc_summary"]["semantics"],
            "current_session_to_date",
        )

        rows = self.db.query(TaiwanStockQuoteSnapshot).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].stock_id, "2330")
        self.assertEqual(rows[0].quote_time.isoformat(), "2026-06-30T09:05:12")
        self.assertEqual(rows[0].total_volume_lots, 49_540)
        self.assertEqual(rows[0].last_trade_volume_lots, 750)
        public_payload = TaiwanStockQuoteDepthRead.model_validate(result)
        self.assertEqual(public_payload.last_trade_volume_lots, 750)

    def test_quote_volume_keeps_same_day_official_daily_total_cross_scope(
        self,
    ) -> None:
        source = SourceRegistry(
            source_name="TWSE OpenAPI Daily Trading",
            source_type="api",
            category="market_daily_price",
            priority=10,
            reliability_level="official",
        )
        self.db.add(source)
        self.db.flush()
        raw_result = RawFetchResult(
            source_id=source.id,
            method="GET",
        )
        self.db.add(raw_result)
        self.db.flush()
        self.db.add(
            MarketDailyPrice(
                source_id=source.id,
                raw_result_id=raw_result.id,
                trade_date=datetime(2026, 6, 30).date(),
                stock_id="2330",
                stock_name="TSMC",
                trade_volume=49_540_000,
                close_price=2410,
            )
        )
        self.db.commit()
        now = datetime(2026, 6, 30, 13, 34, 0, tzinfo=TAIWAN_TZ)
        fetched_at = datetime(2026, 6, 30, 5, 34, 0, tzinfo=timezone.utc)
        payload = sample_payload()
        payload["msgArray"][0]["t"] = "13:30:00"

        with (
            patch("app.market.quote_depth.utc_now", return_value=fetched_at),
            patch(
                "app.market.quote_depth.http_get",
                return_value=FakeResponse(payload),
            ),
        ):
            result = get_taiwan_stock_quote_depth(
                db=self.db,
                stock_id="2330",
                now=now,
            )

        self.assertEqual(result["official_daily_volume_shares"], 49_540_000)
        self.assertEqual(
            result["official_daily_volume_source"],
            "TWSE OpenAPI Daily Trading",
        )
        self.assertEqual(
            result["volume_reconciliation"]["status"],
            "scope_different",
        )
        self.assertEqual(result["volume_reconciliation"]["difference_shares"], 0)
        self.assertEqual(
            result["volume_reconciliation"]["reason"],
            "provider_and_official_volume_scopes_differ",
        )
        self.assertFalse(result["volume_decision_usable"])

    def test_fixed_slot_capture_is_idempotent_and_replay_is_read_only(self) -> None:
        first_now = datetime(2026, 6, 30, 8, 50, 2, tzinfo=TAIWAN_TZ)
        second_now = datetime(2026, 6, 30, 8, 55, 3, tzinfo=TAIWAN_TZ)

        def quote_payload(*, now: datetime, **_kwargs) -> dict:
            return {
                "stock_id": "2330",
                "stock_name": "TSMC",
                "market": "TWSE",
                "provider": "twse_mis",
                "source": "twse_mis_quote_depth",
                "session_phase": "preopen_auction",
                "quote_time": now,
                "refresh_outcome": "updated",
                "last_price": None,
                "depth_available": True,
                "best_bid_price": 2410.0,
                "best_ask_price": 2415.0,
                "auction_indicative_available": True,
                "freshness": {
                    "status": "live",
                    "is_live": True,
                    "is_stale": False,
                },
            }

        with patch(
            "app.market.quote_depth.get_taiwan_stock_quote_depth",
            side_effect=quote_payload,
        ):
            first = capture_taiwan_quote_contract_snapshot(
                db=self.db,
                stock_id="2330",
                capture_slot="08:50",
                now=first_now,
            )
            repeated = capture_taiwan_quote_contract_snapshot(
                db=self.db,
                stock_id="2330",
                capture_slot="08:50",
                now=first_now,
            )
            second = capture_taiwan_quote_contract_snapshot(
                db=self.db,
                stock_id="2330",
                capture_slot="08:55",
                now=second_now,
            )

        before_replay_count = self.db.query(TaiwanQuoteContractSnapshot).count()
        replay = get_taiwan_quote_contract_replay(
            db=self.db,
            stock_id="2330",
            trade_date=first_now.date(),
        )
        after_replay_count = self.db.query(TaiwanQuoteContractSnapshot).count()

        self.assertEqual(first["capture_status"], "captured")
        self.assertEqual(repeated["capture_status"], "captured")
        self.assertEqual(second["capture_status"], "captured")
        self.assertEqual(before_replay_count, 2)
        self.assertEqual(after_replay_count, before_replay_count)
        self.assertEqual(replay["required_slots"], list(TAIWAN_QUOTE_CONTRACT_SLOTS))
        self.assertEqual(replay["captured_count"], 2)
        self.assertAlmostEqual(
            replay["coverage_ratio"],
            2 / len(TAIWAN_QUOTE_CONTRACT_SLOTS),
        )
        self.assertFalse(replay["complete"])
        self.assertFalse(replay["read_path_side_effects"])
        captured = {
            item["capture_slot"]: item
            for item in replay["snapshots"]
            if item["status"].startswith("captured")
        }
        self.assertEqual(captured["08:50"]["quote"]["provider"], "twse_mis")
        projected_quote = captured["08:50"]["quote"]
        self.assertEqual(
            projected_quote["snapshot_time"],
            first_now.isoformat(),
        )
        self.assertEqual(
            projected_quote["provider_event_time"],
            first_now.isoformat(),
        )
        self.assertTrue(projected_quote["auction_book_available"])
        self.assertEqual(projected_quote["auction_book_status"], "depth_only")
        self.assertEqual(projected_quote["auction_best_bid"], 2410.0)
        self.assertEqual(projected_quote["auction_best_ask"], 2415.0)
        self.assertFalse(projected_quote["auction_indicative_available"])
        self.assertIsNone(projected_quote["indicative_bid"])
        self.assertIsNone(projected_quote["indicative_ask"])
        self.assertEqual(
            projected_quote["replay_projection"],
            "current_public_contract",
        )
        self.assertIn("08:30", replay["missing_slots"])

    def test_fixed_slot_scheduler_registers_every_acceptance_slot(self) -> None:
        class FakeScheduler:
            def __init__(self) -> None:
                self.jobs: list[dict] = []

            def add_job(self, function, **kwargs) -> None:
                self.jobs.append({"function": function, **kwargs})

        scheduler = FakeScheduler()

        enabled = add_taiwan_quote_contract_snapshot_jobs(scheduler)

        self.assertTrue(enabled)
        self.assertEqual(len(scheduler.jobs), len(TAIWAN_QUOTE_CONTRACT_SLOTS))
        self.assertEqual(
            [job["kwargs"]["capture_slot"] for job in scheduler.jobs],
            list(TAIWAN_QUOTE_CONTRACT_SLOTS),
        )
        self.assertTrue(all(job["max_instances"] == 1 for job in scheduler.jobs))

    def test_preopen_keeps_indicative_book_separate_from_last_trade(self) -> None:
        now = datetime(2026, 6, 30, 8, 45, 0, tzinfo=TAIWAN_TZ)
        fetched_at = datetime(2026, 6, 30, 0, 45, 0, tzinfo=timezone.utc)
        payload = sample_payload()
        payload["msgArray"][0].update(
            {
                "t": "08:45:00",
                "z": "-",
                "o": "-",
                "h": "-",
                "l": "-",
                "v": "0",
            }
        )

        with (
            patch("app.market.quote_depth.utc_now", return_value=fetched_at),
            patch(
                "app.market.quote_depth.http_get",
                return_value=FakeResponse(payload),
            ),
        ):
            result = get_taiwan_stock_quote_depth(
                db=self.db,
                stock_id="2330",
                now=now,
            )

        self.assertEqual(result["session_phase"], "preopen_auction")
        self.assertEqual(result["market_status"], "preopen")
        self.assertEqual(result["quote_semantics"], "preopen_depth_only")
        self.assertEqual(result["delivery_status"], "live_depth_only")
        self.assertFalse(result["fallback_used"])
        self.assertFalse(result["price_available"])
        self.assertFalse(result["last_trade_available"])
        self.assertIsNone(result["last_trade_price"])
        self.assertIsNone(result["last_trade_volume_lots"])
        self.assertIsNone(result["cumulative_volume_lots"])
        self.assertTrue(result["auction_book_available"])
        self.assertEqual(result["auction_book_status"], "depth_only")
        self.assertEqual(
            result["auction_book_time"].isoformat(),
            "2026-06-30T08:45:00+08:00",
        )
        self.assertFalse(result["auction_indicative_available"])
        self.assertFalse(result["indicative_match_available"])
        self.assertEqual(result["indicative_match_status"], "not_provided")
        self.assertIsNone(result["indicative_unmatched_buy_volume_lots"])
        self.assertIsNone(result["indicative_unmatched_sell_volume_lots"])
        self.assertEqual(
            result["auction_indicative_status"],
            "not_provided",
        )
        self.assertEqual(result["auction_phase"], "preopen_auction")
        self.assertEqual(
            result["auction_event_time"].isoformat(),
            "2026-06-30T08:45:00+08:00",
        )
        self.assertEqual(result["auction_best_bid"], 2410.0)
        self.assertEqual(result["auction_best_ask"], 2415.0)
        self.assertIsNone(result["indicative_bid"])
        self.assertIsNone(result["indicative_ask"])
        self.assertFalse(result["indicative_price_available"])
        self.assertFalse(result["official_close_available"])

    def test_preopen_parses_official_mis_indicative_match_fields(self) -> None:
        now = datetime(2026, 6, 30, 8, 45, 0, tzinfo=TAIWAN_TZ)
        fetched_at = datetime(2026, 6, 30, 0, 45, 0, tzinfo=timezone.utc)
        payload = sample_payload()
        payload["msgArray"][0].update(
            {
                "t": "08:45:00",
                "z": "-",
                "o": "-",
                "h": "-",
                "l": "-",
                "v": "0",
                "tv": "750",
                "ts": "1",
                "pz": "2412.50",
                "ps": "2046",
            }
        )

        with (
            patch("app.market.quote_depth.utc_now", return_value=fetched_at),
            patch(
                "app.market.quote_depth.http_get",
                return_value=FakeResponse(payload),
            ),
        ):
            result = get_taiwan_stock_quote_depth(
                db=self.db,
                stock_id="2330",
                now=now,
            )

        self.assertEqual(
            result["quote_semantics"],
            "preopen_indicative_match_and_depth",
        )
        self.assertEqual(
            result["auction_book_status"],
            "depth_and_indicative_match",
        )
        self.assertTrue(result["auction_indicative_available"])
        self.assertEqual(result["auction_indicative_status"], "available")
        self.assertEqual(result["auction_indicative_source"], "twse_mis_quote_depth")
        self.assertTrue(result["indicative_match_available"])
        self.assertEqual(result["indicative_match_price"], 2412.5)
        self.assertEqual(result["indicative_match_volume_lots"], 2_046)
        self.assertEqual(result["indicative_match_price_source_field"], "pz")
        self.assertEqual(result["indicative_match_volume_source_field"], "ps")
        self.assertEqual(result["indicative_match_status_source_field"], "ts")
        self.assertFalse(result["last_trade_available"])
        self.assertIsNone(result["last_trade_volume_lots"])
        self.assertIsNone(result["cumulative_volume_lots"])

        public_payload = TaiwanStockQuoteDepthRead.model_validate(result)
        self.assertEqual(public_payload.indicative_match_price, 2412.5)
        self.assertEqual(public_payload.indicative_match_volume_lots, 2_046)
        self.assertEqual(
            result["official_close_status"],
            "not_available_yet",
        )

    def test_closing_auction_does_not_relabel_last_trade_as_official_close(
        self,
    ) -> None:
        now = datetime(2026, 6, 30, 13, 27, 0, tzinfo=TAIWAN_TZ)
        fetched_at = datetime(2026, 6, 30, 5, 27, 0, tzinfo=timezone.utc)
        payload = sample_payload()
        payload["msgArray"][0]["t"] = "13:24:59"

        with (
            patch("app.market.quote_depth.utc_now", return_value=fetched_at),
            patch(
                "app.market.quote_depth.http_get",
                return_value=FakeResponse(payload),
            ),
        ):
            result = get_taiwan_stock_quote_depth(
                db=self.db,
                stock_id="2330",
                now=now,
            )

        self.assertEqual(result["session_phase"], "closing_auction")
        self.assertEqual(result["market_status"], "closing_auction")
        self.assertEqual(
            result["quote_semantics"],
            "closing_auction_depth_only",
        )
        self.assertEqual(result["delivery_status"], "closing_auction")
        self.assertTrue(result["last_trade_available"])
        self.assertEqual(result["last_trade_price"], 2410.0)
        self.assertTrue(result["auction_book_available"])
        self.assertFalse(result["auction_indicative_available"])
        self.assertTrue(result["last_trade_before_auction"])
        self.assertEqual(
            result["last_trade_time"].isoformat(),
            "2026-06-30T13:24:59+08:00",
        )
        self.assertEqual(
            result["auction_book_time"].isoformat(),
            "2026-06-30T13:27:00+08:00",
        )
        self.assertFalse(result["official_close_available"])
        self.assertEqual(
            result["official_close_status"],
            "closing_auction_pending",
        )
        public_payload = TaiwanStockQuoteDepthRead.model_validate(
            result
        ).model_dump(mode="json")
        self.assertEqual(
            public_payload["snapshot_time"],
            "2026-06-30T13:27:00+08:00",
        )
        self.assertEqual(
            public_payload["provider_event_time"],
            "2026-06-30T13:24:59+08:00",
        )
        self.assertTrue(public_payload["last_trade_before_auction"])
        self.assertTrue(public_payload["auction_book_available"])
        self.assertEqual(
            public_payload["auction_book_time"],
            "2026-06-30T13:27:00+08:00",
        )

    def test_post_close_is_pending_until_close_resolution_deadline(self) -> None:
        now = datetime(2026, 6, 30, 13, 31, 0, tzinfo=TAIWAN_TZ)
        fetched_at = datetime(2026, 6, 30, 5, 31, 0, tzinfo=timezone.utc)
        payload = sample_payload()
        payload["msgArray"][0]["t"] = "13:30:00"

        with (
            patch("app.market.quote_depth.utc_now", return_value=fetched_at),
            patch(
                "app.market.quote_depth.http_get",
                return_value=FakeResponse(payload),
            ),
        ):
            result = get_taiwan_stock_quote_depth(
                db=self.db,
                stock_id="2330",
                now=now,
            )

        self.assertEqual(result["session_phase"], "post_close_snapshot")
        self.assertEqual(result["market_status"], "closed")
        self.assertEqual(result["quote_semantics"], "official_close_pending")
        self.assertFalse(result["price_available"])
        self.assertFalse(result["official_close_available"])
        self.assertEqual(result["official_close_status"], "pending")
        self.assertEqual(
            result["freshness"]["status"],
            "official_close_pending",
        )

    def test_post_close_confirms_official_close_after_resolution_deadline(
        self,
    ) -> None:
        now = datetime(2026, 6, 30, 13, 34, 0, tzinfo=TAIWAN_TZ)
        fetched_at = datetime(2026, 6, 30, 5, 34, 0, tzinfo=timezone.utc)
        payload = sample_payload()
        payload["msgArray"][0]["t"] = "13:30:00"

        with (
            patch("app.market.quote_depth.utc_now", return_value=fetched_at),
            patch(
                "app.market.quote_depth.http_get",
                return_value=FakeResponse(payload),
            ),
        ):
            result = get_taiwan_stock_quote_depth(
                db=self.db,
                stock_id="2330",
                now=now,
            )

        self.assertEqual(result["market_status"], "closed")
        self.assertEqual(result["quote_semantics"], "official_close")
        self.assertTrue(result["price_available"])
        self.assertTrue(result["official_close_available"])
        self.assertEqual(result["official_close_status"], "confirmed")
        self.assertEqual(result["official_close_price"], 2410.0)
        self.assertEqual(result["official_close_raw"], "2410")
        self.assertEqual(result["official_close_display"], "2410")
        self.assertEqual(result["official_close_precision"], 0)
        self.assertEqual(
            result["official_close_precision_semantics"],
            "provider_decimal_preserved",
        )
        self.assertEqual(
            result["official_close_trade_date"].isoformat(),
            "2026-06-30",
        )
        self.assertEqual(
            result["freshness"]["status"],
            "official_close",
        )

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
        reset_twse_mis_quote_depth_guard()

        with patch("app.market.quote_depth.http_get", side_effect=RuntimeError("MIS down")):
            result = get_taiwan_stock_quote_depth(db=self.db, stock_id="2330", now=now)

        self.assertEqual(result["freshness"]["status"], "cached")
        self.assertEqual(result["freshness"]["source_error"], "MIS down")
        self.assertTrue(result["freshness"]["is_stale"])
        self.assertEqual(result["best_bid_price"], 2410.0)


if __name__ == "__main__":
    unittest.main()
