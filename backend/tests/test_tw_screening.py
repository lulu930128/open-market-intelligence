from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai import capability_contract, tools
from app.db.models import (
    Base,
    InstitutionalTradeDaily,
    MarginTradingDaily,
    RawFetchResult,
    SourceRegistry,
    StockMaster,
)
from app.market.tw_screening import build_tw_screening_snapshot
from app.market.tw_universe import list_taiwan_stock_ids


class TaiwanScreeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)
        self.source_a = SourceRegistry(
            source_name="screening source a",
            source_type="official_api",
            category="screening_test",
        )
        self.source_b = SourceRegistry(
            source_name="screening source b",
            source_type="official_api",
            category="screening_test",
        )
        self.raw_a = RawFetchResult(source=self.source_a, method="GET")
        self.raw_b = RawFetchResult(source=self.source_b, method="GET")
        self.db.add_all(
            [
                self.source_a,
                self.source_b,
                self.raw_a,
                self.raw_b,
                StockMaster(
                    stock_id="1101",
                    stock_name="台泥",
                    market="TWSE",
                    instrument_type="stock",
                    industry="水泥工業",
                    is_active=True,
                ),
                StockMaster(
                    stock_id="2330",
                    stock_name="台積電",
                    market="TWSE",
                    instrument_type="stock",
                    industry="半導體業",
                    is_active=True,
                ),
                StockMaster(
                    stock_id="6488",
                    stock_name="環球晶",
                    market="TPEx",
                    instrument_type="stock",
                    industry="半導體業",
                    is_active=True,
                ),
                StockMaster(
                    stock_id="0050",
                    stock_name="元大台灣50",
                    market="TWSE",
                    instrument_type="etf",
                    is_active=True,
                ),
                StockMaster(
                    stock_id="9999",
                    stock_name="停用股票",
                    market="TWSE",
                    instrument_type="stock",
                    is_active=False,
                ),
            ]
        )
        self.db.flush()
        self.day_minus_four = date(2026, 7, 24)
        self.day_minus_three = date(2026, 7, 25)
        self.day_minus_two = date(2026, 7, 26)
        self.day_one = date(2026, 7, 27)
        self.day_two = date(2026, 7, 28)
        for trade_date in (
            self.day_minus_four,
            self.day_minus_three,
            self.day_minus_two,
        ):
            self._add_institutional(
                "1101", trade_date, foreign=0, trust=0
            )
            self._add_institutional(
                "2330", trade_date, foreign=0, trust=0
            )
        self._add_institutional(
            "1101", self.day_one, foreign=100, trust=10
        )
        self._add_institutional(
            "1101", self.day_two, foreign=50, trust=20
        )
        self._add_institutional(
            "2330", self.day_one, foreign=100, trust=30
        )
        self._add_institutional(
            "2330", self.day_two, foreign=200, trust=40
        )
        # The later row id is the deterministic winner for one stock/date.
        self._add_institutional(
            "2330",
            self.day_two,
            foreign=300,
            trust=50,
            source=self.source_b,
            raw=self.raw_b,
        )
        self._add_institutional(
            "6488", self.day_two, foreign=500, trust=60
        )
        self._add_margin(
            "1101",
            self.day_minus_four,
            previous=100,
            current=100,
        )
        self._add_margin(
            "1101",
            self.day_minus_three,
            previous=100,
            current=100,
        )
        self._add_margin(
            "1101",
            self.day_minus_two,
            previous=100,
            current=100,
        )
        self._add_margin(
            "1101",
            self.day_one,
            previous=100,
            current=110,
        )
        self._add_margin(
            "1101",
            self.day_two,
            previous=110,
            current=121,
        )
        self._add_margin(
            "2330",
            self.day_minus_four,
            previous=200,
            current=200,
        )
        self._add_margin(
            "2330",
            self.day_minus_three,
            previous=200,
            current=200,
        )
        self._add_margin(
            "2330",
            self.day_minus_two,
            previous=200,
            current=200,
        )
        self._add_margin(
            "2330",
            self.day_one,
            previous=200,
            current=220,
        )
        self._add_margin(
            "2330",
            self.day_two,
            previous=220,
            current=242,
        )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _add_institutional(
        self,
        stock_id: str,
        trade_date: date,
        *,
        foreign: int,
        trust: int,
        source: SourceRegistry | None = None,
        raw: RawFetchResult | None = None,
    ) -> None:
        self.db.add(
            InstitutionalTradeDaily(
                source_id=(source or self.source_a).id,
                raw_result_id=(raw or self.raw_a).id,
                trade_date=trade_date,
                stock_id=stock_id,
                stock_name=stock_id,
                foreign_investor_net=foreign,
                investment_trust_net=trust,
            )
        )
        self.db.flush()

    def _add_margin(
        self,
        stock_id: str,
        trade_date: date,
        *,
        previous: int,
        current: int,
    ) -> None:
        self.db.add(
            MarginTradingDaily(
                source_id=self.source_a.id,
                raw_result_id=self.raw_a.id,
                trade_date=trade_date,
                stock_id=stock_id,
                stock_name=stock_id,
                margin_previous_balance=previous,
                margin_today_balance=current,
            )
        )
        self.db.flush()

    def test_universe_is_active_twse_tpex_ordinary_stocks(self) -> None:
        self.assertEqual(
            list_taiwan_stock_ids(self.db),
            ["1101", "2330", "6488"],
        )

    def test_foreign_ranking_is_stable_cache_only_and_coverage_visible(
        self,
    ) -> None:
        before_counts = (
            self.db.query(InstitutionalTradeDaily).count(),
            self.db.query(MarginTradingDaily).count(),
        )
        first = build_tw_screening_snapshot(
            self.db,
            parameters={
                "metric": "foreign_investor_net_shares",
                "window": 5,
                "limit": 2,
            },
            generated_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
        )
        second = build_tw_screening_snapshot(
            self.db,
            parameters={
                "metric": "foreign_investor_net_shares",
                "window": 5,
                "limit": 2,
            },
            generated_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
        )

        self.assertEqual(first["snapshot_id"], second["snapshot_id"])
        self.assertEqual(
            [row["stock_id"] for row in first["ranking"]["rows"]],
            ["2330", "1101"],
        )
        self.assertEqual(
            [row["value"] for row in first["ranking"]["rows"]],
            [400, 150],
        )
        self.assertEqual(first["coverage"]["universe_count"], 3)
        self.assertEqual(first["coverage"]["covered_count"], 3)
        self.assertEqual(first["coverage"]["complete_window_count"], 2)
        self.assertEqual(first["coverage"]["partial_window_count"], 1)
        self.assertFalse(first["coverage"]["is_full_requested_universe"])
        self.assertEqual(first["coverage"]["status"], "partial")
        self.assertEqual(
            first["ranking"]["pagination"]["total_ranked_count"],
            2,
        )
        self.assertFalse(first["ranking"]["pagination"]["has_more"])
        self.assertTrue(first["ranking"]["require_complete_window"])
        self.assertEqual(first["coverage"]["eligible_rank_count"], 2)
        self.assertEqual(
            first["coverage"]["excluded_incomplete_count"],
            1,
        )
        self.assertEqual(first["missing"], [])
        self.assertTrue(first["coverage"]["coverage_gaps"])
        self.assertEqual(
            (
                self.db.query(InstitutionalTradeDaily).count(),
                self.db.query(MarginTradingDaily).count(),
            ),
            before_counts,
        )

    def test_margin_window_uses_first_previous_and_latest_current(self) -> None:
        snapshot = build_tw_screening_snapshot(
            self.db,
            parameters={
                "metric": "margin_balance_change_pct",
                "window": 5,
                "universe": {"stock_ids": ["1101", "2330"]},
            },
        )

        self.assertEqual(
            [row["stock_id"] for row in snapshot["ranking"]["rows"]],
            ["1101", "2330"],
        )
        self.assertEqual(
            [row["value"] for row in snapshot["ranking"]["rows"]],
            [21.0, 21.0],
        )
        self.assertEqual(
            [row["rank"] for row in snapshot["ranking"]["rows"]],
            [1, 1],
        )
        self.assertEqual(
            snapshot["coverage"]["status"],
            "latest_completed_session",
        )

    def test_incomplete_window_rows_require_explicit_opt_in(self) -> None:
        snapshot = build_tw_screening_snapshot(
            self.db,
            parameters={
                "metric": "foreign_investor_net_shares",
                "window": 5,
                "require_complete_window": False,
                "incomplete_window_policy": "include_and_flag",
            },
        )

        self.assertEqual(
            [row["stock_id"] for row in snapshot["ranking"]["rows"]],
            ["6488", "2330", "1101"],
        )
        self.assertEqual(
            snapshot["ranking"]["pagination"]["total_ranked_count"],
            3,
        )
        self.assertFalse(snapshot["ranking"]["rows"][0]["window_complete"])

    def test_capability_parameters_reject_invalid_window(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be one of"):
            capability_contract.normalize_selection(
                selection={
                    "required": [
                        "target.identity",
                        "screening.ranking",
                        "screening.coverage",
                    ],
                    "parameters": {
                        "screening.ranking": {
                            "metric": "foreign_investor_net_shares",
                            "window": 2,
                        }
                    },
                },
                output="evidence_only",
                realtime_policy="cache_only",
                payload_level="compact",
                scope_type="market",
                target_market="TW",
                question_intent="general",
            )

    def test_market_reader_routes_screening_without_new_tool(self) -> None:
        context = tools.read_market_overview(
            self.db,
            market_data_params={
                "payload_level": "compact",
                "requested_capabilities": [
                    "target.identity",
                    "screening.ranking",
                    "screening.coverage",
                    "data.freshness",
                ],
                "capability_parameters": {
                    "screening.ranking": {
                        "metric": "investment_trust_net_shares",
                        "window": 1,
                    }
                },
            },
        )

        self.assertEqual(context["kind"], "market_overview")
        self.assertEqual(
            context["data"]["compact"]["screening"]["ranking"]["metric"],
            "investment_trust_net_shares",
        )
        self.assertIn(
            "screening.ranking",
            context["data"]["freshness_by_capability"],
        )
        self.assertEqual(
            context["data"]["slots"]["screening_coverage"]["capability"],
            "tw_screening_coverage",
        )


if __name__ == "__main__":
    unittest.main()
