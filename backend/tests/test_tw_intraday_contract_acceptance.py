from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
import unittest
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai.data_quality_contract import _fusion_issues
from app.ai.market_context import taiwan_market
from app.ai.realtime_contract import classify_observation
from app.ai.taiwan_intraday_contract import (
    classify_taiwan_session_date_relation,
    resolve_effective_source_health,
    resolve_taiwan_current_price,
)
from app.ai.technical_analysis import _technical_price_levels
from app.db.models import Base, TaiwanMarketMinuteState
from app.market.quote_depth import (
    _depth_contract,
    _first_price_level,
    _parse_depth_levels,
)
from app.market.taiwan_market_state import (
    persist_taiwan_market_minute_state,
)


TAIWAN_TZ = ZoneInfo("Asia/Taipei")


class _BreadthDependencies:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def get_market_index_summary(self, _db, *, force_refresh: bool) -> dict:
        if force_refresh:
            raise AssertionError("acceptance fixture must remain cache-only")
        return self.payload


def _breadth_item(
    *,
    market: str,
    index_id: str,
    total_count: int,
    universe_count: int,
) -> dict:
    return {
        "market": market,
        "index_id": index_id,
        "breadth": {
            "market": market,
            "scope": "full_market",
            "trade_date": "2026-07-30",
            "advance_count": total_count // 3,
            "decline_count": total_count // 2,
            "unchanged_count": total_count - total_count // 3 - total_count // 2,
            "total_count": total_count,
            "universe_count": universe_count,
            "trade_value": 100_000_000,
            "source": f"{market.lower()}_fixture",
        },
        "breadth_status": {"status": "ready"},
    }


class TaiwanIntradayContractAcceptanceTests(unittest.TestCase):
    def test_case_01_live_depth_only_uses_intraday_current_price(self) -> None:
        resolved = resolve_taiwan_current_price(
            quote={
                "trade_date": "2026-07-30",
                "quote_semantics": "live_depth_only",
                "last_trade_available": False,
                "price_available": False,
                "last_trade_price": None,
                "previous_close": 102.5,
                "best_bid_price": 109.5,
                "best_ask_price": 110.0,
            },
            intraday_bars={
                "enabled": True,
                "series": {
                    "1m": {
                        "interval": "1m",
                        "provider": "yahoo_chart",
                        "source": "market_intraday_bar",
                        "trade_date": "2026-07-30",
                        "points": [
                            {
                                "time": "2026-07-30T10:47:00+08:00",
                                "close": 110.0,
                                "finalized": True,
                                "indicator_eligible": True,
                            }
                        ],
                    }
                },
            },
            current_session_date="2026-07-30",
            checked_at=datetime(
                2026,
                7,
                30,
                10,
                47,
                34,
                tzinfo=TAIWAN_TZ,
            ),
        )

        self.assertEqual(resolved["value"], 110.0)
        self.assertEqual(resolved["source_kind"], "intraday_bar_latest")
        self.assertEqual(
            resolved["semantics"],
            "delayed_last_trade_finalized_bar",
        )
        self.assertEqual(resolved["fallback_reason"], "quote_last_trade_unavailable")
        self.assertEqual(resolved["reference_price"], 102.5)

    def test_case_02_delayed_complete_bars_keep_research_facts_usable(self) -> None:
        assessment = classify_observation(
            {
                "status": "current",
                "event_time": "2026-07-30T10:47:00+08:00",
                "received_at": "2026-07-30T10:47:34+08:00",
                "market_status": "open",
                "session_phase": "regular_live",
                "expected_provider_delay_seconds": 15,
                "price": 110.0,
            },
            market="TW",
            realtime_policy="require_live",
            now=datetime(
                2026,
                7,
                30,
                10,
                47,
                34,
                tzinfo=TAIWAN_TZ,
            ),
        )

        self.assertEqual(assessment["state"], "delayed")
        self.assertFalse(assessment["policy_satisfied"])
        self.assertFalse(assessment["contract_compliant"])
        self.assertTrue(assessment["facts_usable"])
        self.assertTrue(assessment["intraday_research_usable"])
        self.assertFalse(assessment["execution_grade_usable"])
        self.assertFalse(assessment["decision_usable"])

    def test_case_03_current_quote_and_completed_daily_are_expected(self) -> None:
        relation = classify_taiwan_session_date_relation(
            quote_date="2026-07-30",
            completed_daily_date="2026-07-29",
            current_session_date="2026-07-30",
            previous_trading_day="2026-07-29",
            is_trading_day=True,
            session_phase="regular_live",
        )
        self.assertEqual(
            relation["relation"],
            "expected_current_session_vs_completed_daily",
        )
        self.assertEqual(relation["status"], "aligned")

        capabilities = {
            "quote.snapshot": {
                "temporal": {"latest_date": "2026-07-30"},
                "decision_usable": True,
                "issues": [],
            },
            "daily.ohlcv": {
                "temporal": {"latest_date": "2026-07-29"},
                "decision_usable": True,
                "issues": [],
            },
        }
        issues = _fusion_issues(
            capabilities,
            projected_data={
                "quote.snapshot": {
                    "price": 110.0,
                    "session_date_relation": relation,
                },
                "daily.ohlcv": {"close": 102.5},
            },
        )
        self.assertNotIn(
            "quote_daily_date_mismatch",
            {item["code"] for item in issues},
        )

    def test_case_04_zero_price_depth_is_not_best_limit_price(self) -> None:
        levels = _parse_depth_levels("0_112.5", "34097_7603")
        best = _first_price_level(levels)
        contract = _depth_contract(
            bid_levels=levels,
            ask_levels=[],
            depth_available=True,
        )

        self.assertEqual(levels[0]["price"], 0.0)
        self.assertEqual(levels[0]["price_status"], "non_price_level")
        self.assertIsNotNone(best)
        self.assertEqual(best["price"], 112.5)
        self.assertEqual(contract["top5_bid_volume_lots"], 7603)
        self.assertEqual(contract["raw_top5_bid_volume_lots"], 41700)
        self.assertEqual(contract["limit_bid_depth"], [levels[1]])
        self.assertEqual(contract["non_price_bid_levels"], [levels[0]])
        self.assertEqual(
            contract["non_price_level_semantics"],
            "provider_non_price_level_unclassified_not_market_order",
        )

    def test_case_05_missing_tpex_breadth_is_partial(self) -> None:
        warnings: list[str] = []
        breadth = taiwan_market._market_breadth_from_index_summary(
            db=None,
            dependencies=_BreadthDependencies(
                {
                    "as_of": "2026-07-30T10:48:00+08:00",
                    "indices": [
                        _breadth_item(
                            market="TWSE",
                            index_id="TAIEX",
                            total_count=1032,
                            universe_count=1032,
                        )
                    ],
                }
            ),
            warnings=warnings,
            source_refs=[],
        )

        self.assertIsNotNone(breadth)
        self.assertEqual(breadth["status"], "partial")
        self.assertEqual(breadth["included_markets"], ["TWSE"])
        self.assertEqual(breadth["missing_markets"], ["TPEX"])
        self.assertEqual(breadth["market_completion_ratio"], 0.5)

    def test_case_06_twse_universe_overflow_is_not_hidden(self) -> None:
        breadth = taiwan_market._market_breadth_from_index_summary(
            db=None,
            dependencies=_BreadthDependencies(
                {
                    "as_of": "2026-07-30T10:48:00+08:00",
                    "indices": [
                        _breadth_item(
                            market="TWSE",
                            index_id="TAIEX",
                            total_count=1080,
                            universe_count=1032,
                        )
                    ],
                }
            ),
            warnings=[],
            source_refs=[],
        )

        self.assertIsNotNone(breadth)
        twse = breadth["markets"]["TWSE"]
        self.assertTrue(twse["coverage_overflow"])
        self.assertGreater(twse["coverage_ratio_raw"], 1.0)
        self.assertEqual(twse["reconciliation_status"], "inconsistent")

    def test_case_07_previous_session_ranking_keeps_observed_date(self) -> None:
        capability = taiwan_market._sample_sector_capability(
            industry_summary=[
                {
                    "industry": "半導體業",
                    "average_change_pct": -3.5,
                    "advance_count": 5,
                    "decline_count": 50,
                    "trade_value": 1_000_000,
                    "count": 55,
                }
            ],
            sample_coverage={
                "universe_count": 1973,
                "coverage_count": 83,
            },
            as_of="2026-07-29",
            computed_at="2026-07-30T10:48:40+08:00",
        )

        self.assertEqual(capability["observed_trade_date"], "2026-07-29")
        self.assertEqual(
            capability["computed_at"],
            "2026-07-30T10:48:40+08:00",
        )
        self.assertEqual(capability["data_mode"], "previous_completed_session")
        self.assertFalse(capability["is_intraday"])

    def test_case_08_intraday_technical_levels_use_resolved_price(self) -> None:
        levels = _technical_price_levels(
            technical_reports={},
            latest_daily=SimpleNamespace(
                trade_date=date(2026, 7, 29),
                close_price=1515.0,
            ),
            resolved_current_price={
                "value": 1570.0,
                "source_kind": "intraday_bar_latest",
                "event_time": "2026-07-30T10:48:00+08:00",
                "trade_date": "2026-07-30",
                "is_estimate": False,
            },
        )

        self.assertEqual(levels["latest_price"], 1570.0)
        self.assertEqual(levels["basis_timeframe"], "intraday_with_daily_structure")
        self.assertEqual(levels["price_basis_date"], "2026-07-30")
        self.assertEqual(levels["daily_basis_date"], "2026-07-29")
        self.assertEqual(levels["technical_price_basis"], "intraday_bar_latest")
        self.assertFalse(levels["bid_ask_price_used"])

    def test_case_09_trade_value_persists_without_breadth(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        with Session(engine) as db:
            result = persist_taiwan_market_minute_state(
                db,
                payload={
                    "as_of": "2026-07-30T10:48:45+08:00",
                    "indices": [
                        {
                            "index_id": "TPEX",
                            "market": "TPEX",
                            "time": "2026-07-30",
                            "close": 250.0,
                            "trade_value": 123_000_000,
                            "source": "official_index_summary",
                            "breadth": None,
                            "breadth_status": {
                                "status": "missing",
                            },
                        }
                    ],
                },
            )
            row = db.query(TaiwanMarketMinuteState).one()

        self.assertEqual(result["inserted_count"], 1)
        self.assertEqual(row.cumulative_trade_value, 123_000_000)
        self.assertEqual(row.breadth_status, "missing")
        self.assertEqual(row.quality_status, "partial")

    def test_case_10_request_success_overrides_expired_snapshot(self) -> None:
        effective = resolve_effective_source_health(
            request_health={
                "status": "success",
                "checked_at": "2026-07-30T10:48:20+08:00",
                "provider": "twse_mis",
            },
            persisted_health={
                "status": "expired",
                "checked_at": "2026-07-22T12:00:00+08:00",
                "snapshot_is_stale": True,
            },
        )

        self.assertEqual(effective["status"], "request_succeeded")
        self.assertEqual(effective["authority"], "request_health")
        self.assertTrue(effective["request_succeeded"])
        self.assertIn(
            "persisted_health_snapshot_expired",
            effective["warnings"],
        )


if __name__ == "__main__":
    unittest.main()
