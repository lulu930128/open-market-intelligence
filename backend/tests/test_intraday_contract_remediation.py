from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import requests

from app.ai.ask_finalizer import (
    _apply_stock_compact_fields,
    _domain_passport,
    _intraday_summary_from_compact,
    _market_live_summary,
)
from app.ai import ask_execution
from app.ai.agentic_execution import _compact_result
from app.ai.capability_contract import _canonical_capability_value
from app.ai.data_quality_contract import _continuity_summary
from app.ai.decision_envelope_v4 import _brief_capability_summary
from app.ai.decision_core import infer_question_intent
from app.ai.market_context.jp_context import _jp_intraday_compact, _jp_intraday_quote
from app.ai.market_context.kr_context import _kr_intraday_compact, _kr_intraday_quote
from app.ai.market_context.us_context import _us_intraday_compact
from app.ai.market_context import taiwan_stock
from app.ai.market_context.taiwan_stock import _apply_disposition_quote_contract
from app.ai.market_context.taiwan_projection import (
    _compact_index_quote,
    _compact_intraday_history,
    _compact_quote_snapshot,
    _compact_single_intraday_series,
    _intraday_slot_status,
)
from app.ai.tools import _health_dimensions
from app.ai.schemas import AiAskRequest
from app.ai.query_plan import build_query_plan
from app.ai.scope_resolution import _resolve_scope
from app.ai.market_payload_contract import requested_intraday_interval
from app.ai.technical_analysis import _normalize_technical_points
from app.market.intraday import (
    _append_completed_session_close_marker,
    _dedupe_disposition_points,
    _enrich_intraday_contract,
    _intraday_row_to_point,
)
from app.market.indices import _merge_index_intraday_snapshot
from app.market.providers import twse_mis
from app.market.quote_depth import (
    _freshness_for_row,
)
from app.observability.provider_http import (
    ProviderHttpError,
    ProviderRequestContext,
    request as provider_request,
)


class IntradayContractRemediationTests(unittest.TestCase):
    def test_intraday_projection_appends_official_close_marker_without_indicator_use(
        self,
    ) -> None:
        evidence = SimpleNamespace(
            daily=SimpleNamespace(
                trade_date=date(2026, 8, 31),
                close_price=584,
                provider="twse_openapi",
                source="twse_daily_trading",
                event_at=datetime.fromisoformat("2026-08-31T15:15:00+08:00"),
            ),
            resolved_health=SimpleNamespace(facts_usable=True),
        )
        with (
            patch(
                "app.market.intraday.read_taiwan_latest_daily_evidence",
                return_value=evidence,
            ),
            patch("app.market.intraday.read_taiwan_session_close", return_value=object()),
            patch(
                "app.market.intraday.project_taiwan_session_close",
                return_value={
                    "available": True,
                    "status": "session_final",
                    "finalization": "session_final",
                    "price": 580,
                    "trade_date": date(2026, 8, 31),
                    "event_time": datetime.fromisoformat(
                        "2026-08-31T13:30:00+08:00"
                    ),
                    "provider": "twse_mis",
                    "source": "twse_mis_public_quote",
                    "closing_match_volume_shares": 37_000,
                    "closing_match_volume_lots": 37,
                    "closing_match_volume_semantics": (
                        "provider_reported_closing_match_volume"
                    ),
                    "closing_match_volume_source_field": "tv",
                    "session_cumulative_volume_shares": 26_754_000,
                    "session_cumulative_volume_lots": 26_754,
                    "session_cumulative_volume_trade_date": date(2026, 8, 31),
                    "session_cumulative_volume_event_time": datetime.fromisoformat(
                        "2026-08-31T13:30:00+08:00"
                    ),
                    "session_cumulative_volume_source_field": "v",
                    "volume_provider": "twse_mis",
                    "volume_source": "twse_mis_quote_depth",
                    "volume_event_time": datetime.fromisoformat(
                        "2026-08-31T13:30:00+08:00"
                    ),
                    "volume_status": "session_final",
                    "volume_scope": "completed_regular_session",
                },
            ),
        ):
            projected = _append_completed_session_close_marker(
                object(),
                stock_id="3711",
                points=[
                    {
                        "time": "2026-08-31T13:24:00+08:00",
                        "price": 580,
                        "close": 580,
                        "volume": 1000,
                        "finalization": "final",
                    }
                ],
                requested_at=datetime.fromisoformat(
                    "2026-08-31T16:00:00+08:00"
                ),
            )

        points, metadata = _enrich_intraday_contract(
            projected,
            interval="1m",
            source="nstock_minute_stock_data",
            now=datetime.fromisoformat("2026-08-31T16:00:00+08:00"),
        )
        marker = points[-1]
        self.assertEqual(marker["time"], datetime.fromisoformat("2026-08-31T13:30:00+08:00"))
        self.assertEqual(marker["price"], 584)
        self.assertEqual(marker["bar_type"], "official_close_marker")
        self.assertEqual(marker["price_semantics"], "official_close")
        self.assertTrue(marker["display_eligible"])
        self.assertFalse(marker["indicator_eligible"])
        self.assertEqual(marker["volume"], 37_000)
        self.assertEqual(marker["cumulative_volume"], 26_754_000)
        self.assertEqual(marker["provider"], "twse_openapi")
        self.assertEqual(marker["session_close_provider"], "twse_mis")
        self.assertIsNone(marker["bar_close_time"])
        self.assertEqual(metadata["bar_type_counts"]["official_close_marker"], 1)
        self.assertEqual(metadata["indicator_eligible_count"], 1)
        self.assertEqual(metadata["bar_volume_latest_time"], "2026-08-31T13:24:00+08:00")
        self.assertEqual(metadata["closing_match_volume_shares"], 37_000)
        self.assertEqual(metadata["session_cumulative_volume_shares"], 26_754_000)
        self.assertEqual(metadata["cumulative_volume_shares"], 26_754_000)
        self.assertEqual(metadata["cumulative_volume_status"], "session_final")

    def test_intraday_projection_falls_back_to_confirmed_session_close_marker(
        self,
    ) -> None:
        missing_daily = SimpleNamespace(
            daily=None,
            resolved_health=SimpleNamespace(facts_usable=False),
        )
        with (
            patch(
                "app.market.intraday.read_taiwan_latest_daily_evidence",
                return_value=missing_daily,
            ),
            patch("app.market.intraday.read_taiwan_session_close", return_value=object()),
            patch(
                "app.market.intraday.project_taiwan_session_close",
                return_value={
                    "available": True,
                    "status": "session_final",
                    "finalization": "session_final",
                    "price": 605,
                    "trade_date": date(2026, 8, 31),
                    "event_time": datetime.fromisoformat(
                        "2026-08-31T13:30:00+08:00"
                    ),
                    "provider": "twse_mis",
                    "source": "twse_mis_public_quote",
                },
            ),
        ):
            projected = _append_completed_session_close_marker(
                object(),
                stock_id="2330",
                points=[
                    {
                        "time": "2026-08-31T13:24:00+08:00",
                        "price": 600,
                        "close": 600,
                        "volume": 1000,
                    }
                ],
            )

        marker = projected[-1]
        self.assertEqual(marker["bar_type"], "session_close_marker")
        self.assertEqual(marker["price_semantics"], "session_close")
        self.assertEqual(marker["evidence_finalization"], "session_final")
        self.assertFalse(marker["indicator_eligible"])

    def test_legacy_intraday_timeframe_alias_does_not_capture_daily_timeframes(self) -> None:
        self.assertEqual(
            requested_intraday_interval({"timeframe": "5m"}),
            "5m",
        )
        self.assertIsNone(
            requested_intraday_interval({"timeframe": "daily"}),
        )

    def test_cache_only_keeps_intraday_requested_without_external_fetch(
        self,
    ) -> None:
        payload = AiAskRequest(
            question="7203 即時走勢",
            target={"type": "jp_stock", "id": "7203.T"},
            realtime_policy="cache_only",
            allow_external_fetch=True,
            market_data_params={"include_intraday": True},
        )

        params = ask_execution._external_intraday_market_data_params(
            payload,
            policy={"can_external_fetch": True},
        )

        self.assertTrue(params["include_intraday"])
        self.assertEqual(params["realtime_policy"], "cache_only")
        self.assertFalse(params["external_fetch_allowed"])

    def test_taiwan_intraday_contract_exposes_volume_value_vwap_and_partial_bar(self) -> None:
        points, metadata = _enrich_intraday_contract(
            [
                {
                    "time": "2026-07-27T09:00:00+08:00",
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.0,
                    "volume": 1_000,
                    "trade_value": 100_000,
                },
                {
                    "time": "2026-07-27T09:01:00+08:00",
                    "open": 101.0,
                    "high": 102.0,
                    "low": 100.0,
                    "close": 101.0,
                    "volume": 500,
                    "trade_value": None,
                },
            ],
            interval="1m",
            source="nstock_minute_stock_data_twse_mis_volume",
            now=datetime.fromisoformat("2026-07-27T09:01:30+08:00"),
        )

        self.assertEqual(points[0]["volume_shares"], 1_000)
        self.assertEqual(points[0]["volume_lots"], 1)
        self.assertEqual(points[0]["provider_volume_unit"], "lots")
        self.assertEqual(points[0]["trade_value_status"], "official")
        self.assertEqual(points[1]["trade_value_status"], "estimated")
        self.assertTrue(points[1]["is_partial"])
        self.assertFalse(points[1]["finalized"])
        self.assertEqual(points[0]["bar_type"], "regular_interval")
        self.assertEqual(points[0]["price_semantics"], "intraday_bar_close")
        self.assertTrue(points[0]["display_eligible"])
        self.assertTrue(points[0]["indicator_eligible"])
        self.assertFalse(points[1]["indicator_eligible"])
        self.assertEqual(metadata["canonical_volume_unit"], "shares")
        self.assertEqual(metadata["bar_contract_version"], "tw.intraday.bar.v1")
        self.assertEqual(metadata["bar_type_counts"], {"regular_interval": 2})
        self.assertEqual(metadata["finalized_bar_count"], 1)
        self.assertEqual(metadata["indicator_eligible_count"], 1)
        self.assertEqual(metadata["bar_volume_sum_shares"], 1_500)
        self.assertEqual(metadata["bar_volume_sum_lots"], 1.5)
        self.assertEqual(metadata["window_volume_sum_shares"], 1_500)
        self.assertEqual(
            metadata["bar_volume_scope"],
            "latest_trade_date_interval_bar_sum",
        )
        self.assertEqual(
            metadata["session_cumulative_volume_status"],
            "fallback_bar_sum",
        )
        self.assertEqual(metadata["cumulative_volume_shares"], 1_500)
        self.assertEqual(metadata["cumulative_volume_lots"], 1.5)
        self.assertEqual(metadata["cumulative_volume_source"], "intraday_bar_sum")
        self.assertEqual(metadata["cumulative_volume_status"], "fallback_bar_sum")
        self.assertIsNone(metadata["cumulative_trade_value"])
        self.assertEqual(metadata["available_cumulative_trade_value"], 100_000)
        self.assertEqual(metadata["trade_value_status"], "partial")
        self.assertIsNone(metadata["official_vwap"])
        self.assertIsNotNone(metadata["approx_vwap"])
        self.assertEqual(
            metadata["partial_bar_policy"],
            "exclude_partial_bars_from_indicators",
        )
        self.assertEqual(
            metadata["indicator_policy"],
            "finalized_regular_interval_or_closing_auction_only",
        )

    def test_taiwan_intraday_session_metrics_do_not_cross_trade_dates(self) -> None:
        points, metadata = _enrich_intraday_contract(
            [
                {
                    "time": "2026-08-05T12:00:00+08:00",
                    "close": 100.0,
                    "volume": 10_000,
                },
                {
                    "time": "2026-08-05T13:00:00+08:00",
                    "close": 100.0,
                    "volume": 20_000,
                },
                {
                    "time": "2026-08-06T09:00:00+08:00",
                    "close": 200.0,
                    "volume": 1_000,
                },
                {
                    "time": "2026-08-06T09:01:00+08:00",
                    "close": 200.0,
                    "volume": 2_000,
                },
            ],
            interval="1m",
            source="yahoo_finance_chart",
            now=datetime.fromisoformat("2026-08-06T09:01:30+08:00"),
        )

        self.assertEqual(len(points), 4)
        self.assertEqual(metadata["window_trade_date_count"], 2)
        self.assertEqual(metadata["window_volume_sum_shares"], 33_000)
        self.assertEqual(metadata["bar_volume_trade_date"], "2026-08-06")
        self.assertEqual(metadata["bar_volume_sum_shares"], 3_000)
        self.assertEqual(metadata["cumulative_volume_shares"], 3_000)
        self.assertEqual(metadata["estimated_cumulative_trade_value"], 600_000)
        self.assertAlmostEqual(metadata["approx_vwap"], 200.0)
        self.assertEqual(
            metadata["vwap_volume_scope"],
            "latest_trade_date_interval_bars",
        )

    def test_partial_series_keeps_bar_sum_but_suppresses_session_cumulative(self) -> None:
        _, metadata = _enrich_intraday_contract(
            [
                {
                    "time": "2026-08-06T11:25:00+08:00",
                    "close": 200.0,
                    "volume": 1_000,
                    "finalization": "final",
                },
                {
                    "time": "2026-08-06T13:24:00+08:00",
                    "close": 201.0,
                    "volume": 2_000,
                    "finalization": "final",
                },
            ],
            interval="1m",
            source="nstock_minute_stock_data",
            now=datetime.fromisoformat("2026-08-06T14:00:00+08:00"),
            series_coverage={
                "status": "trailing_window",
                "current_cumulative_volume_complete": False,
                "session_volume_complete": False,
            },
        )

        self.assertEqual(metadata["bar_volume_sum_shares"], 3_000)
        self.assertIsNone(metadata["cumulative_volume_shares"])
        self.assertEqual(metadata["cumulative_volume_status"], "partial_coverage")
        self.assertEqual(
            metadata["volume_semantics"],
            "observed_window_bar_sum_not_session_cumulative",
        )

    def test_intraday_compact_projection_preserves_dual_volume_contract(self) -> None:
        compact = _compact_intraday_history(
            {
                "interval": "1m",
                "requested_interval": "1m",
                "source_interval": "1m",
                "effective_interval": "1m",
                "range": "1d",
                "provider": "nstock",
                "source": "nstock_minute_stock_data",
                "series_coverage": {
                    "status": "trailing_window",
                    "opening_covered": False,
                    "current_window_complete": False,
                },
                "bar_volume_sum_shares": 3_012_567,
                "bar_volume_sum_lots": 3_012.567,
                "bar_volume_trade_date": "2026-08-06",
                "bar_volume_latest_time": "2026-08-06T09:40:00+08:00",
                "bar_volume_scope": "latest_trade_date_interval_bar_sum",
                "bar_volume_provider": "nstock_minute_stock_data",
                "window_volume_sum_shares": 3_012_567,
                "window_volume_sum_lots": 3_012.567,
                "window_volume_scope": "query_window_interval_bar_sum",
                "window_trade_date_count": 1,
                "session_cumulative_volume_status": "fallback_bar_sum",
                "cumulative_volume_shares": 3_012_567,
                "cumulative_volume_lots": 3_012.567,
                "cumulative_volume_trade_date": "2026-08-06",
                "cumulative_volume_source": "intraday_bar_sum",
                "cumulative_volume_status": "fallback_bar_sum",
                "vwap_volume_scope": "latest_trade_date_interval_bars",
                "points": [
                    {
                        "time": "2026-08-06T09:40:00+08:00",
                        "close": 2_850.0,
                        "volume": 10_000,
                    }
                ],
            }
        )

        self.assertEqual(compact["bar_volume_sum_shares"], 3_012_567)
        self.assertEqual(compact["bar_volume_trade_date"], "2026-08-06")
        self.assertEqual(compact["cumulative_volume_source"], "intraday_bar_sum")
        self.assertEqual(compact["window_trade_date_count"], 1)
        self.assertEqual(compact["coverage_status"], "trailing_window")
        self.assertEqual(
            compact["series_coverage"]["opening_covered"],
            False,
        )
        self.assertEqual(
            compact["vwap_volume_scope"],
            "latest_trade_date_interval_bars",
        )

    def test_intraday_slot_is_partial_when_series_coverage_is_incomplete(self) -> None:
        self.assertEqual(
            _intraday_slot_status(
                {
                    "enabled": True,
                    "series": {
                        "1m": {
                            "returned_point_count": 2,
                            "series_coverage": {"status": "trailing_window"},
                        }
                    },
                }
            ),
            "partial",
        )
        self.assertEqual(
            _intraday_slot_status(
                {
                    "enabled": True,
                    "series": {
                        "1m": {
                            "returned_point_count": 2,
                            "series_coverage": {"status": "complete_prefix"},
                        }
                    },
                }
            ),
            "ready",
        )

    def test_aligned_mis_volume_reconciles_without_mutating_points(self) -> None:
        original_points = [
            {
                "time": "2026-08-06T09:40:00+08:00",
                "volume_shares": 10_000,
            }
        ]
        intraday_bars = {
            "series": {
                "1m": {
                    "interval": "1m",
                    "effective_interval": "1m",
                    "bar_volume_sum_shares": 3_012_567,
                    "bar_volume_sum_lots": 3_012.567,
                    "bar_volume_trade_date": "2026-08-06",
                    "bar_volume_latest_time": "2026-08-06T09:40:00+08:00",
                    "approx_vwap": 2_848.44,
                    "vwap_confidence": "medium",
                    "points": [dict(point) for point in original_points],
                    "warnings": [],
                }
            },
            "warnings": [],
        }
        quote = {
            "trade_date": "2026-08-06",
            "event_time": "2026-08-06T09:39:56+08:00",
            "session_phase": "regular_live",
            "cumulative_volume_shares": 3_091_000,
            "cumulative_volume_lots": 3_091,
            "volume_source": "twse_mis",
            "volume_source_field": "v",
            "volume_scope": "regular_session_board_lot_cumulative",
            "volume_status": "available",
            "freshness": {"status": "live", "is_stale": False},
        }

        taiwan_stock._apply_taiwan_intraday_volume_reconciliation(
            quote=quote,
            intraday_bars=intraday_bars,
            calendar_status={"phase": "regular"},
        )

        series = intraday_bars["series"]["1m"]
        self.assertEqual(series["session_cumulative_volume_shares"], 3_091_000)
        self.assertEqual(series["cumulative_volume_shares"], 3_091_000)
        self.assertEqual(series["bar_volume_sum_shares"], 3_012_567)
        self.assertEqual(series["unallocated_volume_shares"], 78_433)
        self.assertEqual(series["unallocated_volume_lots"], 78.433)
        self.assertEqual(series["volume_reconciliation"]["status"], "time_skew")
        self.assertEqual(series["vwap_confidence"], "low")
        self.assertEqual(series["points"], original_points)

    def test_older_same_day_mis_does_not_override_newer_bar_sum(self) -> None:
        intraday_bars = {
            "series": {
                "1m": {
                    "interval": "1m",
                    "effective_interval": "1m",
                    "bar_volume_sum_shares": 121_447_000,
                    "bar_volume_trade_date": "2026-08-06",
                    "bar_volume_latest_time": "2026-08-06T13:30:00+08:00",
                    "warnings": [],
                }
            },
            "warnings": [],
        }
        quote = {
            "trade_date": "2026-08-06",
            "event_time": "2026-08-06T09:34:35+08:00",
            "session_phase": "post_close_snapshot",
            "cumulative_volume_shares": 53_962_000,
            "cumulative_volume_lots": 53_962,
            "volume_source": "twse_mis",
            "volume_source_field": "v",
            "volume_scope": "regular_session_board_lot_cumulative",
            "volume_status": "available",
            "freshness": {
                "status": "official_close_pending",
                "is_stale": False,
            },
        }

        taiwan_stock._apply_taiwan_intraday_volume_reconciliation(
            quote=quote,
            intraday_bars=intraday_bars,
            calendar_status={"phase": "post_close"},
        )

        series = intraday_bars["series"]["1m"]
        self.assertEqual(series["session_cumulative_volume_shares"], 53_962_000)
        self.assertEqual(series["session_cumulative_volume_status"], "time_skew")
        self.assertEqual(series["cumulative_volume_shares"], 121_447_000)
        self.assertEqual(series["cumulative_volume_source"], "intraday_bar_sum")
        self.assertEqual(series["cumulative_volume_status"], "fallback_bar_sum")
        self.assertEqual(series["volume_reconciliation"]["status"], "time_skew")

    def test_preopen_volume_does_not_reuse_previous_session_bar_sum(self) -> None:
        intraday_bars = {
            "series": {
                "1m": {
                    "interval": "1m",
                    "bar_volume_sum_shares": 50_000,
                    "bar_volume_trade_date": "2026-08-05",
                    "bar_volume_latest_time": "2026-08-05T13:30:00+08:00",
                }
            },
            "warnings": [],
        }

        taiwan_stock._apply_taiwan_intraday_volume_reconciliation(
            quote={
                "trade_date": "2026-08-06",
                "session_phase": "preopen_auction",
                "cumulative_volume_shares": None,
                "volume_status": "unavailable",
                "freshness": {"status": "live", "is_stale": False},
            },
            intraday_bars=intraday_bars,
            calendar_status={"phase": "preopen"},
        )

        series = intraday_bars["series"]["1m"]
        self.assertIsNone(series["session_cumulative_volume_shares"])
        self.assertIsNone(series["cumulative_volume_shares"])
        self.assertEqual(series["cumulative_volume_status"], "unavailable")
        self.assertEqual(
            series["volume_reconciliation"]["reason"],
            "preopen_session_cumulative_unavailable",
        )

    def test_intraday_volume_date_mismatch_preserves_both_evidence_dates(self) -> None:
        intraday_bars = {
            "series": {
                "1m": {
                    "interval": "1m",
                    "bar_volume_sum_shares": 50_000,
                    "bar_volume_trade_date": "2026-08-05",
                    "bar_volume_latest_time": "2026-08-05T13:30:00+08:00",
                }
            },
            "warnings": [],
        }
        taiwan_stock._apply_taiwan_intraday_volume_reconciliation(
            quote={
                "trade_date": "2026-08-06",
                "event_time": "2026-08-06T09:10:00+08:00",
                "session_phase": "regular_live",
                "cumulative_volume_shares": 10_000,
                "volume_source": "twse_mis",
                "volume_source_field": "v",
                "volume_scope": "regular_session_board_lot_cumulative",
                "volume_status": "available",
                "freshness": {"status": "live", "is_stale": False},
            },
            intraday_bars=intraday_bars,
            calendar_status={"phase": "regular"},
        )

        series = intraday_bars["series"]["1m"]
        self.assertEqual(series["bar_volume_trade_date"], "2026-08-05")
        self.assertEqual(
            series["session_cumulative_volume_trade_date"],
            "2026-08-06",
        )
        self.assertEqual(series["cumulative_volume_shares"], 50_000)
        self.assertEqual(series["cumulative_volume_status"], "date_mismatch")
        self.assertEqual(
            series["volume_reconciliation"]["status"],
            "date_mismatch",
        )

    def test_aligned_bar_sum_exceeding_mis_remains_visible(self) -> None:
        intraday_bars = {
            "series": {
                "1m": {
                    "interval": "1m",
                    "bar_volume_sum_shares": 54_070_000,
                    "bar_volume_trade_date": "2026-08-06",
                    "bar_volume_latest_time": "2026-08-06T09:34:00+08:00",
                }
            },
            "warnings": [],
        }
        taiwan_stock._apply_taiwan_intraday_volume_reconciliation(
            quote={
                "trade_date": "2026-08-06",
                "event_time": "2026-08-06T09:34:35+08:00",
                "session_phase": "regular_live",
                "cumulative_volume_shares": 53_962_000,
                "volume_source": "twse_mis",
                "volume_source_field": "v",
                "volume_scope": "regular_session_board_lot_cumulative",
                "volume_status": "available",
                "freshness": {"status": "live", "is_stale": False},
            },
            intraday_bars=intraday_bars,
            calendar_status={"phase": "regular"},
        )

        series = intraday_bars["series"]["1m"]
        reconciliation = series["volume_reconciliation"]
        self.assertEqual(series["cumulative_volume_shares"], 53_962_000)
        self.assertEqual(reconciliation["status"], "bar_sum_exceeds_exchange")
        self.assertEqual(reconciliation["difference_shares"], -108_000)
        self.assertEqual(series["unallocated_volume_shares"], 0)

    def test_taiwan_intraday_contract_marks_close_and_irregular_points(self) -> None:
        points, metadata = _enrich_intraday_contract(
            [
                {
                    "time": "2026-07-27T13:25:00+08:00",
                    "close": 100.0,
                    "volume": 2_000,
                },
                {
                    "time": "2026-07-27T13:30:00+08:00",
                    "close": 101.0,
                    "volume": 0,
                },
                {
                    "time": "2026-07-27T13:30:17+08:00",
                    "close": 101.0,
                    "volume": 0,
                },
            ],
            interval="1m",
            source="yahoo_finance_chart",
            now=datetime.fromisoformat("2026-07-27T14:00:00+08:00"),
        )

        self.assertEqual(points[0]["bar_type"], "closing_auction")
        self.assertTrue(points[0]["indicator_eligible"])
        self.assertEqual(points[1]["bar_type"], "official_close_marker")
        self.assertFalse(points[1]["indicator_eligible"])
        self.assertEqual(points[1]["market_event"], "official_close")
        self.assertEqual(points[2]["bar_type"], "provider_irregular")
        self.assertFalse(points[2]["indicator_eligible"])
        self.assertEqual(metadata["indicator_eligible_point_count"], 1)

    def test_index_intraday_projection_preserves_actual_five_second_interval(self) -> None:
        projected = _compact_single_intraday_series(
            raw_payload={
                "interval": "5s",
                "provider": "twse_openapi",
                "source": "twse_index_5s",
                "point_count": 2,
                "points": [
                    {
                        "time": "2026-07-24T09:00:00+08:00",
                        "price": 44000.0,
                    },
                    {
                        "time": "2026-07-24T09:00:05+08:00",
                        "price": 44001.0,
                    },
                ],
            },
            interval="1m",
            include_intraday=True,
            market_data_params={
                "intraday_interval": "5m",
                "intraday_limit": 1,
            },
        )

        self.assertEqual(projected["intervals"], ["5s"])
        self.assertEqual(projected["requested_interval"], "5m")
        self.assertEqual(projected["source_interval"], "5s")
        self.assertEqual(projected["effective_interval"], "5s")
        self.assertEqual(projected["interval_status"], "unsupported")
        self.assertTrue(
            any("without relabeling" in item for item in projected["warnings"])
        )
        series = projected["series"]["5s"]
        self.assertEqual(series["requested_interval"], "5m")
        self.assertEqual(series["source_interval"], "5s")
        self.assertEqual(series["effective_interval"], "5s")
        self.assertEqual(series["interval_status"], "unsupported")
        self.assertEqual(series["point_count"], 2)
        self.assertEqual(series["returned_point_count"], 1)
        self.assertEqual(series["bar_limit"], 1)
        self.assertTrue(series["truncated"])

    def test_index_session_metadata_survives_intraday_capability_projection(
        self,
    ) -> None:
        canonical = _canonical_capability_value(
            "intraday.bars",
            {
                "series": {
                    "5s": {
                        "interval": "5s",
                        "session_phase": "post_close",
                        "market_status": "closed",
                        "official_close_status": "confirmed",
                        "delivery_status": "official_close",
                        "points": [
                            {
                                "time": "2026-07-27T13:33:00+08:00",
                                "price": 43_634.19,
                            }
                        ],
                    }
                }
            },
        )
        summary = _brief_capability_summary("intraday.bars", canonical)

        self.assertEqual(canonical["session_phase"], "post_close")
        self.assertEqual(canonical["official_close_status"], "confirmed")
        self.assertEqual(summary["market_status"], "closed")
        self.assertEqual(summary["delivery_status"], "official_close")

    def test_intraday_summary_uses_max_timestamp_for_latest_point(self) -> None:
        summary = _brief_capability_summary(
            "intraday.bars",
            {
                "interval": "1m",
                "event_time": "2026-07-28T02:04:00Z",
                "bars": [
                    {
                        "bar_time": "2026-07-28T02:13:00Z",
                        "close_price": 101.0,
                        "base_volume": 2.5,
                        "base_volume_unit": "BTC",
                    },
                    {
                        "bar_time": "2026-07-28T02:04:00Z",
                        "close_price": 99.0,
                        "base_volume": 1.0,
                        "base_volume_unit": "BTC",
                    },
                ],
            },
        )

        self.assertEqual(
            summary["latest_point"]["bar_time"],
            "2026-07-28T02:13:00Z",
        )
        self.assertEqual(summary["latest_point"]["close_price"], 101.0)
        self.assertEqual(summary["latest_point"]["base_volume_unit"], "BTC")
        self.assertEqual(summary["event_time"], "2026-07-28T02:13:00Z")

    def test_intraday_capability_normalizes_descending_rows_before_limiting(
        self,
    ) -> None:
        canonical = _canonical_capability_value(
            "intraday.bars",
            {
                "interval": "1m",
                "bars": [
                    {"bar_time": "2026-07-28T02:13:00Z", "close_price": 101},
                    {"bar_time": "2026-07-28T02:12:00Z", "close_price": 100},
                    {"bar_time": "2026-07-28T02:11:00Z", "close_price": 99},
                ],
            },
        )

        self.assertEqual(
            [row["bar_time"] for row in canonical["bars"]],
            [
                "2026-07-28T02:11:00Z",
                "2026-07-28T02:12:00Z",
                "2026-07-28T02:13:00Z",
            ],
        )
        self.assertEqual(canonical["sort_order"], "asc")
        self.assertEqual(
            canonical["latest_point"]["bar_time"],
            "2026-07-28T02:13:00Z",
        )
        self.assertEqual(canonical["event_time"], "2026-07-28T02:13:00Z")

    def test_index_price_points_are_eligible_for_intraday_technical_context(
        self,
    ) -> None:
        points = _normalize_technical_points(
            [
                {
                    "time": "2026-07-27T13:30:00+08:00",
                    "price": 43_634.19,
                    "open": 43_585.92,
                    "high": 43_686.15,
                    "low": 42_969.48,
                }
            ]
        )

        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["close"], 43_634.19)
        self.assertEqual(points[0]["high"], 43_686.15)

    def test_us_latest_n_intraday_keeps_contiguous_source_interval(self) -> None:
        start = datetime(2026, 7, 24, 9, 30)
        source_points = [
            {
                "time": (start + timedelta(minutes=index)).isoformat(),
                "price": 200.0 + index,
                "volume": 1_000 + index,
            }
            for index in range(390)
        ]

        tool_summary = _compact_result(
            {
                "status": "ok",
                "source": "yahoo_finance_chart",
                "interval": "1m",
                "requested_interval": "1m",
                "point_count": len(source_points),
                "points": source_points,
            }
        )
        compact = _us_intraday_compact(
            tool_summary,
            market_data_params={"intraday_limit": 30},
        )
        series = compact["series"]["1m"]
        continuity = _continuity_summary(series, market="US")

        self.assertEqual(tool_summary["sampling_mode"], "latest_n")
        self.assertEqual(tool_summary["original_point_count"], 390)
        self.assertEqual(tool_summary["returned_point_count"], 80)
        self.assertEqual(tool_summary["requested_interval"], "1m")
        self.assertEqual(tool_summary["points"][0], source_points[-80])
        self.assertEqual(series["source_interval"], "1m")
        self.assertEqual(series["effective_interval"], "1m")
        self.assertEqual(series["sampling_mode"], "latest_n")
        self.assertEqual(series["original_point_count"], 390)
        self.assertEqual(series["returned_point_count"], 30)
        self.assertEqual(series["points"], source_points[-30:])
        self.assertEqual(
            continuity["expected_interval_seconds"],
            60.0,
        )
        self.assertEqual(
            continuity["observed_median_interval_seconds"],
            60.0,
        )
        self.assertEqual(continuity["status"], "continuous")

    def test_us_intraday_interval_mismatch_is_explicit_not_silently_relabelled(self) -> None:
        compact = _us_intraday_compact(
            {
                "source": "yahoo_finance_chart",
                "interval": "1m",
                "point_count": 1,
                "points": [
                    {
                        "time": "2026-07-20T13:15:00-04:00",
                        "price": 210.0,
                        "volume": 1000,
                    }
                ],
            },
            market_data_params={"intraday_interval": "5m"},
        )

        self.assertEqual(compact["requested_interval"], "5m")
        series = compact["series"]["1m"]
        self.assertEqual(series["requested_interval"], "5m")
        self.assertEqual(series["source_interval"], "1m")
        self.assertEqual(series["effective_interval"], "1m")
        self.assertEqual(series["interval_status"], "unsupported")
        self.assertTrue(any("without relabeling" in item for item in compact["warnings"]))

    def test_taiwan_closing_auction_gap_requires_session_evidence(self) -> None:
        with_evidence = _continuity_summary(
            {
                "interval": "1m",
                "session_phase": "closing_auction",
                "points": [
                    {"time": "2026-07-27T13:24:00+08:00", "price": 100.0},
                    {"time": "2026-07-27T13:30:00+08:00", "price": 101.0},
                ],
            },
            market="TW",
        )
        without_evidence = _continuity_summary(
            {
                "interval": "1m",
                "points": [
                    {"time": "2026-07-27T13:24:00+08:00", "price": 100.0},
                    {"time": "2026-07-27T13:30:00+08:00", "price": 101.0},
                ],
            },
            market="TW",
        )

        self.assertEqual(with_evidence["status"], "continuous")
        self.assertEqual(with_evidence["gap_count"], 0)
        self.assertEqual(with_evidence["recognized_session_gap_count"], 1)
        self.assertEqual(
            with_evidence["session_gap_evidence"],
            "closing_auction_or_official_close",
        )
        self.assertEqual(without_evidence["status"], "partial")
        self.assertEqual(without_evidence["gap_count"], 1)

        official_publish_gap = _continuity_summary(
            {
                "interval": "5s",
                "official_close_status": "confirmed",
                "points": [
                    {"time": "2026-07-27T13:30:00+08:00", "price": 100.0},
                    {"time": "2026-07-27T13:33:00+08:00", "price": 101.0},
                ],
            },
            market="TW",
        )
        self.assertEqual(official_publish_gap["gap_count"], 0)
        self.assertEqual(
            official_publish_gap["recognized_session_gap_count"],
            1,
        )

    def test_taiwan_trading_day_boundary_is_not_missing_intraday_data(self) -> None:
        continuity = _continuity_summary(
            {
                "interval": "1m",
                "points": [
                    {"time": "2026-08-03T13:30:00+08:00", "price": 100.0},
                    {"time": "2026-08-04T09:00:00+08:00", "price": 101.0},
                ],
            },
            market="TW",
        )

        self.assertEqual(continuity["status"], "continuous")
        self.assertEqual(continuity["gap_count"], 0)
        self.assertEqual(continuity["recognized_session_gap_count"], 1)
        self.assertEqual(continuity["overnight_session_gap_count"], 1)
        self.assertEqual(
            continuity["session_gap_evidence"],
            "trading_day_boundary",
        )

    def test_kr_market_halt_event_reclassifies_gap_without_hiding_provenance(
        self,
    ) -> None:
        continuity = _continuity_summary(
            {
                "interval": "1m",
                "market_events": [
                    {
                        "event_id": "KR-KOSPI-20260728-INFERRED-HALT-01",
                        "market": "KR",
                        "event_type": "inferred_market_halt",
                        "halt_start_at": "2026-07-28T10:14:00+09:00",
                        "halt_end_at": "2026-07-28T10:42:59+09:00",
                        "continuous_trading_resumed_at": (
                            "2026-07-28T10:44:00+09:00"
                        ),
                        "source": "cross_instrument_intraday_observation",
                        "source_grade": "inferred",
                        "confirmed": False,
                    }
                ],
                "points": [
                    {
                        "time": "2026-07-28T10:13:00+09:00",
                        "price": 100.0,
                    },
                    {
                        "time": "2026-07-28T10:44:00+09:00",
                        "price": 99.0,
                    },
                ],
            },
            market="KR",
        )

        self.assertEqual(continuity["status"], "continuous_with_market_halt")
        self.assertEqual(continuity["gap_count"], 0)
        self.assertEqual(continuity["recognized_session_gap_count"], 1)
        self.assertEqual(continuity["market_halt_gap_count"], 1)
        self.assertEqual(continuity["gap_reason"], "market_halt")
        self.assertEqual(
            continuity["market_event_refs"],
            ["KR-KOSPI-20260728-INFERRED-HALT-01"],
        )
        self.assertNotIn("missing_interval", continuity["issues"])

    def test_index_snapshot_volume_keeps_provider_specific_semantics(self) -> None:
        merged = _merge_index_intraday_snapshot(
            {
                "source": "twse_index_5s",
                "interval": "5s",
                "volume_unit": None,
                "volume_semantics": "not_provided_for_cash_index",
                "points": [
                    {
                        "time": "2026-07-27T13:30:00+08:00",
                        "price": 43_634.19,
                        "volume": None,
                    }
                ],
            },
            {
                "source": "twse_mis_index_snapshot",
                "points": [
                    {
                        "time": "2026-07-27T13:33:00+08:00",
                        "price": 43_634.19,
                        "volume": 8_876_197,
                    }
                ],
            },
        )

        self.assertEqual(merged["volume_unit"], "provider_units")
        self.assertEqual(merged["provider_volume_unit"], "provider_units")
        self.assertIsNone(merged["canonical_volume_unit"])
        self.assertEqual(merged["volume_status"], "provider_specific")
        self.assertEqual(
            merged["volume_semantics"],
            "snapshot_provider_value_not_market_trade_value",
        )
        self.assertEqual(
            merged["points"][-1]["provider_volume_unit"],
            "provider_units",
        )

    def test_taiwan_intraday_reader_honors_explicit_five_minute_interval(self) -> None:
        get_history = unittest.mock.Mock(
            return_value={
                "interval": "5m",
                "requested_interval": "5m",
                "source_interval": "1m",
                "effective_interval": "5m",
                "interval_status": "ready",
                "range": "1d",
                "provider": "local_derived",
                "source": "local_current_1m_aggregate",
                "point_count": 1,
                "cached_count": 1,
                "refreshed_count": 1,
                "points": [
                    {
                        "time": "2026-07-20T13:15:00+08:00",
                        "open": 2324.0,
                        "high": 2326.0,
                        "low": 2324.0,
                        "close": 2325.0,
                        "volume": 1000,
                    }
                ],
            }
        )

        with unittest.mock.patch.object(
            taiwan_stock,
            "project_taiwan_bar_series",
            return_value=get_history.return_value,
        ):
            result = taiwan_stock._compact_intraday_bars(
                dependencies=SimpleNamespace(read_taiwan_bars=get_history),
                db=SimpleNamespace(),
                stock_id="2330",
                include_intraday=True,
                market_data_params={"intraday_interval": "5m"},
            )

        get_history.assert_called_once()
        self.assertEqual(get_history.call_args.kwargs["interval"], "5m")
        self.assertEqual(result["intervals"], ["5m"])
        self.assertEqual(result["requested_interval"], "5m")
        series = result["series"]["5m"]
        self.assertEqual(series["requested_interval"], "5m")
        self.assertEqual(series["source_interval"], "1m")
        self.assertEqual(series["effective_interval"], "5m")
        self.assertEqual(series["interval_status"], "ready")

    def test_cached_taiwan_intraday_row_restores_taipei_timezone_at_reader_exit(self) -> None:
        point = _intraday_row_to_point(
            SimpleNamespace(
                bar_time=datetime(2026, 7, 20, 13, 15),
                open_price=2324.0,
                high_price=2326.0,
                low_price=2324.0,
                close_price=2325.0,
                trade_volume=1000,
                trade_value=2_325_000,
            )
        )

        self.assertEqual(point["time"].utcoffset(), timedelta(hours=8))
        self.assertEqual(point["time"].isoformat(), "2026-07-20T13:15:00+08:00")

    def test_jp_intraday_five_minute_aggregation_respects_lunch_boundary(self) -> None:
        compact = _jp_intraday_compact(
            {
                "source": "yahoo_finance_chart",
                "interval": "1m",
                "volume_unit": "shares",
                "volume_semantics": "interval_volume",
                "point_count": 4,
                "points": [
                    {
                        "time": "2026-07-20T09:00:00+09:00",
                        "price": 3200.0,
                        "volume": 100,
                    },
                    {
                        "time": "2026-07-20T09:01:00+09:00",
                        "price": 3210.0,
                        "volume": 200,
                    },
                    {
                        "time": "2026-07-20T09:04:00+09:00",
                        "price": 3190.0,
                        "volume": 300,
                    },
                    {
                        "time": "2026-07-20T12:30:00+09:00",
                        "price": 3220.0,
                        "volume": 400,
                    },
                ],
            },
            market_data_params={"intraday_interval": "5m"},
        )

        self.assertEqual(compact["requested_interval"], "5m")
        series = compact["series"]["5m"]
        self.assertEqual(series["requested_interval"], "5m")
        self.assertEqual(series["source_interval"], "1m")
        self.assertEqual(series["effective_interval"], "5m")
        self.assertEqual(series["interval_status"], "ready")
        self.assertEqual(
            series["aggregation_method"],
            "local_ohlcv_1m_to_5m",
        )
        self.assertEqual(series["points"][0]["open"], 3200.0)
        self.assertEqual(series["points"][0]["high"], 3210.0)
        self.assertEqual(series["points"][0]["low"], 3190.0)
        self.assertEqual(series["points"][0]["close"], 3190.0)
        self.assertEqual(series["points"][0]["volume"], 600)
        self.assertEqual(len(series["points"]), 2)
        self.assertEqual(series["points"][1]["session"], "regular_pm")

    def test_kr_intraday_five_minute_aggregation_returns_real_ohlcv(self) -> None:
        compact = _kr_intraday_compact(
            {
                "source": "yahoo_finance_chart",
                "interval": "1m",
                "volume_unit": "shares",
                "volume_semantics": "interval_volume",
                "point_count": 3,
                "points": [
                    {
                        "time": "2026-07-20T09:00:00+09:00",
                        "price": 85_000.0,
                        "volume": 1000,
                    },
                    {
                        "time": "2026-07-20T09:01:00+09:00",
                        "price": 85_500.0,
                        "volume": 2000,
                    },
                    {
                        "time": "2026-07-20T09:04:00+09:00",
                        "price": 84_500.0,
                        "volume": 3000,
                    },
                ],
            },
            market_data_params={"intraday_interval": "5m"},
        )

        self.assertEqual(compact["requested_interval"], "5m")
        series = compact["series"]["5m"]
        self.assertEqual(series["requested_interval"], "5m")
        self.assertEqual(series["source_interval"], "1m")
        self.assertEqual(series["effective_interval"], "5m")
        self.assertEqual(series["interval_status"], "ready")
        self.assertEqual(series["points"][0]["open"], 85_000.0)
        self.assertEqual(series["points"][0]["high"], 85_500.0)
        self.assertEqual(series["points"][0]["low"], 84_500.0)
        self.assertEqual(series["points"][0]["close"], 84_500.0)
        self.assertEqual(series["points"][0]["volume"], 6000)

    def test_empty_regional_five_minute_request_reports_support_or_availability(self) -> None:
        projectors = (
            ("JP", _jp_intraday_compact, "unavailable"),
            ("KR", _kr_intraday_compact, "unavailable"),
            ("US", _us_intraday_compact, "unsupported"),
        )

        for market, projector, expected_status in projectors:
            with self.subTest(market=market):
                compact = projector(
                    None,
                    market_data_params={"intraday_interval": "5m"},
                )

                self.assertFalse(compact["enabled"])
                self.assertEqual(compact["requested_interval"], "5m")
                self.assertEqual(compact["source_interval"], "1m")
                self.assertIsNone(compact["effective_interval"])
                self.assertEqual(compact["interval_status"], expected_status)
                warning_text = " ".join(compact["warnings"])
                if expected_status == "unsupported":
                    self.assertIn("unsupported", warning_text)
                else:
                    self.assertIn("did not return data", warning_text)

    def test_unavailable_depth_does_not_expose_stale_bid_ask(self) -> None:
        quote = _compact_quote_snapshot(
            latest_daily=None,
            quote_depth={
                "source": "twse_mis_quote_depth",
                "last_price": 2350.0,
                "total_volume_lots": 21505,
                "best_bid_price": 2345.0,
                "best_ask_price": 2350.0,
                "spread": 5.0,
                "depth_available": False,
                "freshness": {
                    "status": "final_snapshot",
                    "is_live": False,
                    "is_stale": False,
                },
            },
            quote_error=None,
            session_phase="post_close",
        )

        self.assertFalse(quote["depth_available"])
        self.assertEqual(quote["depth_status"], "unavailable")
        self.assertEqual(quote["total_volume_lots"], 21505)
        self.assertEqual(quote["volume_unit"], "lots")
        self.assertIsNone(quote["best_bid_price"])
        self.assertIsNone(quote["best_ask_price"])
        self.assertIsNone(quote["spread"])

    def test_preopen_daily_fallback_exposes_previous_close_not_latest_price(
        self,
    ) -> None:
        quote = _compact_quote_snapshot(
            latest_daily=SimpleNamespace(
                trade_date="2026-07-24",
                close_price=2350.0,
                price_change=25.0,
                open_price=2310.0,
                high_price=2360.0,
                low_price=2300.0,
                trade_volume=25_000_000,
            ),
            quote_depth=None,
            quote_error="TWSE MIS unavailable",
            session_phase="preopen",
            current_session_date="2026-07-27",
            is_trading_day=True,
        )

        self.assertEqual(quote["status"], "preopen_no_last_trade")
        self.assertEqual(quote["quote_semantics"], "previous_close_fallback")
        self.assertEqual(quote["delivery_status"], "previous_close")
        self.assertTrue(quote["fallback_used"])
        self.assertFalse(quote["price_available"])
        self.assertIsNone(quote["latest_price"])
        self.assertIsNone(quote["price"])
        self.assertIsNone(quote["last_price"])
        self.assertEqual(quote["previous_close"], 2350.0)
        self.assertEqual(
            quote["fallback_quote"],
            {
                "price": 2350.0,
                "trade_date": "2026-07-24",
                "source": "market_daily_price",
                "provider": "local_daily_close",
                "semantics": "latest_completed_session_reference",
                "current_session": False,
            },
        )
        self.assertFalse(quote["facts_usable_for_current_session"])
        self.assertFalse(quote["last_trade_available"])
        self.assertFalse(quote["official_close_available"])
        self.assertEqual(
            quote["official_close_status"],
            "not_available_yet",
        )
        self.assertIsNone(quote["open_price"])
        self.assertIsNone(quote["total_volume_lots"])

    def test_post_close_daily_fallback_stays_pending_until_current_row_arrives(
        self,
    ) -> None:
        quote = _compact_quote_snapshot(
            latest_daily=SimpleNamespace(
                trade_date="2026-07-24",
                close_price=2350.0,
                price_change=25.0,
                open_price=2310.0,
                high_price=2360.0,
                low_price=2300.0,
                trade_volume=25_000_000,
            ),
            quote_depth=None,
            quote_error=None,
            session_phase="post_close",
            current_session_date="2026-07-27",
            is_trading_day=True,
        )

        self.assertEqual(quote["status"], "official_close_pending")
        self.assertEqual(quote["quote_semantics"], "official_close_pending")
        self.assertFalse(quote["price_available"])
        self.assertIsNone(quote["latest_price"])
        self.assertEqual(quote["previous_close"], 2350.0)
        self.assertFalse(quote["official_close_available"])
        self.assertEqual(quote["official_close_status"], "pending")

    def test_daily_only_quote_does_not_claim_live_close_is_pending(self) -> None:
        quote = _compact_quote_snapshot(
            latest_daily=SimpleNamespace(
                trade_date="2026-07-24",
                close_price=2350.0,
                price_change=25.0,
                open_price=2310.0,
                high_price=2360.0,
                low_price=2300.0,
                trade_volume=25_000_000,
            ),
            quote_depth=None,
            quote_error=None,
            session_phase="post_close",
            current_session_date="2026-07-27",
            is_trading_day=True,
            live_quote_requested=False,
        )

        self.assertEqual(quote["status"], "delayed_daily_close")
        self.assertEqual(
            quote["quote_semantics"],
            "latest_completed_session_close",
        )
        self.assertEqual(
            quote["freshness"]["status"],
            "latest_completed_session",
        )
        self.assertFalse(quote["fallback_used"])
        self.assertTrue(quote["official_close_available"])
        self.assertEqual(quote["latest_price"], 2350.0)

    def test_current_daily_row_resolves_official_close_explicitly(self) -> None:
        quote = _compact_quote_snapshot(
            latest_daily=SimpleNamespace(
                trade_date="2026-07-27",
                close_price=2380.0,
                price_change=30.0,
                open_price=2360.0,
                high_price=2390.0,
                low_price=2345.0,
                trade_volume=30_000_000,
            ),
            quote_depth=None,
            quote_error=None,
            session_phase="post_close",
            current_session_date="2026-07-27",
            is_trading_day=True,
        )

        self.assertEqual(quote["status"], "official_close")
        self.assertEqual(quote["quote_semantics"], "official_close")
        self.assertTrue(quote["price_available"])
        self.assertEqual(quote["latest_price"], 2380.0)
        self.assertEqual(quote["previous_close"], 2350.0)
        self.assertTrue(quote["official_close_available"])
        self.assertEqual(quote["official_close_status"], "confirmed")
        self.assertEqual(quote["official_close_price"], 2380.0)
        self.assertEqual(
            quote["official_close_source"],
            "market_daily_price.close_price",
        )

    def test_stale_taiwan_index_point_is_not_live_during_session(self) -> None:
        calendar_status = {
            "market": "tw",
            "timezone": "Asia/Taipei",
            "checked_at": "2026-07-20T13:15:00+08:00",
            "date": "2026-07-20",
            "is_trading_day": True,
            "phase": "regular",
            "reason": "trading_day",
            "holiday_name": None,
            "previous_trading_day": "2026-07-17",
            "next_trading_day": "2026-07-21",
            "session": {
                "open_time": "09:00",
                "close_time": "13:30",
            },
        }
        intraday = {
            "source": "twse_index_5s",
            "previous_close": 42000.0,
            "points": [
                {
                    "time": "2026-07-20T12:55:00+08:00",
                    "price": 42600.0,
                    "open": 42300.0,
                    "high": 42700.0,
                    "low": 42100.0,
                    "volume": None,
                }
            ],
        }

        result = _compact_index_quote(
            index_id="TAIEX",
            index_snapshot={"time": "2026-07-20", "volume": 0},
            intraday=intraday,
            calendar_status=calendar_status,
        )

        self.assertFalse(result["is_realtime"])
        self.assertFalse(result["freshness"]["is_live"])
        self.assertTrue(result["freshness"]["is_stale"])
        self.assertEqual(result["freshness"]["age_seconds"], 1200)
        self.assertFalse(result["is_latest_session_quote"])

    def test_taiwan_index_ohlc_is_aggregated_and_zero_volume_is_missing(self) -> None:
        calendar_status = {
            "market": "tw",
            "timezone": "Asia/Taipei",
            "checked_at": "2026-07-20T10:01:00+08:00",
            "date": "2026-07-20",
            "is_trading_day": True,
            "phase": "regular",
            "reason": "trading_day",
            "holiday_name": None,
            "previous_trading_day": "2026-07-17",
            "next_trading_day": "2026-07-21",
            "session": {"open_time": "09:00", "close_time": "13:30"},
        }
        result = _compact_index_quote(
            index_id="TAIEX",
            index_snapshot={"time": "2026-07-20", "volume": 0},
            intraday={
                "source": "twse_index_5s",
                "previous_close": 42000.0,
                "points": [
                    {"time": "2026-07-20T09:00:00+08:00", "price": 42200.0, "open": 42100.0, "high": 42250.0, "low": 42050.0, "volume": None},
                    {"time": "2026-07-20T10:00:00+08:00", "price": 42300.0, "open": 42200.0, "high": 42400.0, "low": 42150.0, "volume": None},
                ],
            },
            calendar_status=calendar_status,
        )

        self.assertEqual(result["open_price"], 42100.0)
        self.assertEqual(result["high_price"], 42400.0)
        self.assertEqual(result["low_price"], 42050.0)
        self.assertIsNone(result["volume"])
        self.assertEqual(result["volume_status"], "not_provided")

    def test_taiwan_index_current_session_excludes_previous_session_fields(self) -> None:
        result = _compact_index_quote(
            index_id="TPEX",
            index_snapshot={
                "time": "2026-07-30",
                "as_of": "2026-07-30T13:30:00+08:00",
                "open": 320.0,
                "high": 324.0,
                "low": 318.0,
                "close": 322.74,
                "trade_value": 174_150_558_495,
                "source": "tpex_openapi_daily_trading_index",
            },
            intraday={
                "source": "twse_mis_intraday",
                "previous_close": 322.74,
                "points": [
                    {
                        "time": "2026-07-31T09:00:00+08:00",
                        "price": 344.0,
                        "open": 343.5,
                        "high": 344.5,
                        "low": 343.0,
                    },
                    {
                        "time": "2026-07-31T10:00:00+08:00",
                        "price": 345.6,
                        "open": 344.0,
                        "high": 346.0,
                        "low": 344.0,
                    },
                ],
            },
            calendar_status={
                "market": "tw",
                "timezone": "Asia/Taipei",
                "checked_at": "2026-07-31T10:00:10+08:00",
                "date": "2026-07-31",
                "is_trading_day": True,
                "phase": "regular",
                "previous_trading_day": "2026-07-30",
                "session": {"open_time": "09:00", "close_time": "13:30"},
            },
        )

        self.assertEqual(result["trade_date"], "2026-07-31")
        self.assertEqual(result["selected_candidate"], "intraday_last_trade")
        self.assertEqual(result["open_price"], 343.5)
        self.assertEqual(result["high_price"], 346.0)
        self.assertEqual(result["low_price"], 343.0)
        self.assertIsNone(result["trade_value"])
        self.assertEqual(result["trade_value_status"], "not_provided")
        self.assertEqual(result["session_reconciliation_status"], "separated")
        self.assertEqual(result["current_session"]["trade_date"], "2026-07-31")
        self.assertEqual(result["previous_session"]["trade_date"], "2026-07-30")
        self.assertEqual(result["previous_session"]["low_price"], 318.0)
        self.assertEqual(
            result["previous_session"]["trade_value"],
            174_150_558_495,
        )

    def test_taiwan_index_closing_auction_keeps_official_close_pending(self) -> None:
        result = _compact_index_quote(
            index_id="TAIEX",
            index_snapshot={
                "time": "2026-07-27",
                "as_of": "2026-07-27T13:28:00+08:00",
                "close": 43_634.19,
                "high": 43_686.15,
                "source": "yahoo_finance_chart",
            },
            intraday={
                "source": "twse_index_5s",
                "points": [
                    {
                        "time": "2026-07-27T13:24:00+08:00",
                        "price": 43_640.0,
                    }
                ],
            },
            calendar_status={
                "market": "tw",
                "timezone": "Asia/Taipei",
                "checked_at": "2026-07-27T13:28:00+08:00",
                "date": "2026-07-27",
                "is_trading_day": True,
                "phase": "closing_auction",
                "previous_trading_day": "2026-07-24",
                "session": {"open_time": "09:00", "close_time": "13:30"},
            },
        )

        self.assertEqual(result["latest_price"], 43_640.0)
        self.assertEqual(result["selected_candidate"], "intraday_last_trade")
        self.assertEqual(
            result["official_close_status"],
            "closing_auction_pending",
        )
        self.assertFalse(result["official_close_available"])
        self.assertIsNone(result["official_close_price"])
        self.assertEqual(result["high_price"], 43_686.15)

    def test_taiwan_index_post_close_clock_cannot_confirm_without_evidence(self) -> None:
        snapshot = {
            "time": "2026-07-27",
            "as_of": "2026-07-27T13:30:05+08:00",
            "close": 43_634.19,
            "high": 43_686.15,
            "source": "yahoo_finance_chart+twse_index_5s_snapshot",
        }
        intraday = {
            "source": "twse_index_5s",
            "points": [
                {
                    "time": "2026-07-27T13:30:00+08:00",
                    "price": 43_634.19,
                }
            ],
        }
        calendar = {
            "market": "tw",
            "timezone": "Asia/Taipei",
            "date": "2026-07-27",
            "is_trading_day": True,
            "phase": "post_close",
            "previous_trading_day": "2026-07-24",
            "session": {"open_time": "09:00", "close_time": "13:30"},
        }

        pending = _compact_index_quote(
            index_id="TAIEX",
            index_snapshot=snapshot,
            intraday=intraday,
            calendar_status={
                **calendar,
                "checked_at": "2026-07-27T13:32:00+08:00",
            },
        )
        still_pending = _compact_index_quote(
            index_id="TAIEX",
            index_snapshot=snapshot,
            intraday=intraday,
            calendar_status={
                **calendar,
                "checked_at": "2026-07-27T13:34:00+08:00",
            },
        )

        self.assertEqual(pending["official_close_status"], "pending")
        self.assertFalse(pending["official_close_available"])
        self.assertEqual(pending["latest_price"], 43_634.19)
        self.assertEqual(pending["high_price"], 43_686.15)
        self.assertIsNone(pending["official_close_price"])
        self.assertEqual(still_pending["official_close_status"], "pending")
        self.assertFalse(still_pending["official_close_available"])
        self.assertIsNone(still_pending["official_close_price"])
        self.assertIsNone(still_pending["official_close_display"])
        self.assertEqual(
            still_pending["selection_reason"],
            "latest_same_trade_date_candidate_pending_confirmation",
        )
        auction = still_pending["components"]["auction"]
        self.assertEqual(auction["status"], "not_applicable")
        self.assertEqual(
            auction["unavailable_reason_code"],
            "CASH_INDEX_NO_ORDER_BOOK_AUCTION",
        )
        self.assertFalse(auction["refresh_recommended"])

    def test_display_price_prefers_current_intraday_over_stale_depth_quote(self) -> None:
        result = _market_live_summary(
            compact={"target": {"type": "tw_stock", "id": "2330"}},
            quote={
                "last_price": 2335.0,
                "quote_time": "2026-07-20T12:24:40+08:00",
                "depth_available": True,
                "freshness": {"status": "cached", "is_live": False, "is_stale": True},
            },
            intraday={
                "status": "ok",
                "interval": "1m",
                "last_update": "2026-07-20T13:17:00+08:00",
                "freshness_status": "current",
                "latest_point": {"time": "2026-07-20T13:17:00+08:00", "close": 2325.0},
            },
        )

        self.assertEqual(result["display_price"], 2325.0)
        self.assertEqual(result["display_price_source"], "intraday")
        self.assertEqual(result["display_price_time"], "2026-07-20T13:17:00+08:00")
        self.assertEqual(result["display_price_freshness"], "current")
        self.assertFalse(result["quote_depth_available"])

    def test_live_summary_respects_explicit_live_quote_flag(self) -> None:
        result = _market_live_summary(
            compact={"target": {"type": "kr_stock", "id": "005930"}},
            quote={
                "price": 90_000,
                "quote_time": "2026-07-24T10:00:00+09:00",
                "is_live": True,
                "is_realtime": True,
                "freshness": {"status": "current_session"},
            },
            intraday={},
        )

        self.assertTrue(result["quote_is_live"])
        self.assertTrue(result["is_live"])
        self.assertTrue(result["is_realtime"])

    def test_market_compact_live_summary_uses_taiex_intraday_pack(self) -> None:
        output: dict[str, object] = {}
        _apply_stock_compact_fields(
            output,
            {
                "target": {"type": "market", "id": "TW", "market": "TW"},
                "index_intraday": {
                    "enabled": True,
                    "indices": [
                        {
                            "index_id": "TAIEX",
                            "quote": {
                                "price": 23_510,
                                "quote_time": "2026-07-24T13:30:00+08:00",
                                "source": "twse_index_5s",
                                "is_live": True,
                                "is_realtime": True,
                                "freshness": {"status": "live"},
                            },
                            "intraday_bars": {
                                "enabled": True,
                                "series": {
                                    "1m": {
                                        "interval": "1m",
                                        "point_count": 2,
                                        "returned_point_count": 2,
                                        "to_time": "2026-07-24T13:30:00+08:00",
                                        "freshness_status": "live",
                                        "latest": {
                                            "time": "2026-07-24T13:30:00+08:00",
                                            "close": 23_510,
                                        },
                                        "points": [],
                                    }
                                },
                            },
                        }
                    ],
                },
            },
        )

        live_summary = output["live_summary"]
        self.assertEqual(live_summary["status"], "ready")
        self.assertEqual(live_summary["quote_price"], 23_510)
        self.assertTrue(live_summary["intraday_available"])
        self.assertTrue(live_summary["is_live"])

    def test_intraday_compact_freshness_reaches_live_summary(self) -> None:
        summary = _intraday_summary_from_compact(
            {
                "enabled": True,
                "series": {
                    "1m": {
                        "interval": "1m",
                        "returned_point_count": 1,
                        "to_time": "2026-07-20T13:17:00+08:00",
                        "freshness_status": "live",
                        "age_seconds": 20,
                        "market_status": "open",
                        "latest": {
                            "time": "2026-07-20T13:17:00+08:00",
                            "close": 2325.0,
                        },
                        "points": [],
                    }
                },
            }
        )

        self.assertEqual(summary["freshness_status"], "live")
        self.assertEqual(summary["age_seconds"], 20)
        self.assertEqual(summary["market_status"], "open")

    def test_negated_broker_branch_term_does_not_select_broker_branch_intent(self) -> None:
        question = "只測即時報價與分K，不刷新法人、營收、分點。"

        self.assertEqual(infer_question_intent(question), "quote")

        plan = build_query_plan(
            payload=AiAskRequest(
                question=question,
                target={"type": "tw_stock", "id": "2330"},
                mode="data_only",
                allow_external_fetch=True,
            ),
            scope_type="stock",
            question_intent="quote",
            effective_mode="data_only",
        )
        self.assertEqual(plan.requested_domains, ("quote", "intraday"))
        self.assertIn("live_intraday_bars", plan.required_capabilities)
        self.assertNotIn("live_intraday_bars", plan.excluded_capabilities)
        self.assertIn("read_taiwan_bars", plan.required_readers)
        self.assertNotIn("read_taiwan_bars", plan.excluded_readers)
        self.assertIn("broker_branch", plan.excluded_domains)
        self.assertIn("fundamentals", plan.excluded_domains)
        self.assertTrue(plan.matched_negative_terms)

    def test_query_plan_keeps_strict_provider_contract(self) -> None:
        plan = build_query_plan(
            payload=AiAskRequest(
                question="2330 即時報價",
                target={"type": "tw_stock", "id": "2330"},
                mode="data_only",
                market_data_params={
                    "provider": "twse_mis",
                    "strict_provider": True,
                    "refresh_domains": ["quote"],
                },
            ),
            scope_type="stock",
            question_intent="quote",
            effective_mode="data_only",
        )

        self.assertEqual(plan.requested_provider, "twse_mis")
        self.assertTrue(plan.strict_provider)
        self.assertEqual(plan.requested_domains, ("quote",))

    @staticmethod
    def _quote_reader_dependencies(*, quote_depth, intraday_history):
        return taiwan_stock.TaiwanStockDependencies(
            market_service=SimpleNamespace(
                get_latest_stock_daily_price=lambda *_args, **_kwargs: SimpleNamespace(
                    trade_date=datetime.fromisoformat("2026-07-17T00:00:00+08:00").date(),
                    close_price=2330.0,
                    open_price=2320.0,
                    high_price=2340.0,
                    low_price=2310.0,
                    price_change=10.0,
                    trade_volume=1000,
                )
            ),
            stock_service=SimpleNamespace(
                get_stock=lambda **_kwargs: SimpleNamespace(
                    stock_id="2330",
                    stock_name="TSMC",
                    market="TWSE",
                ),
                StockNotFoundError=RuntimeError,
            ),
            build_stock_technical_report=lambda **_kwargs: {},
            build_taiwan_calendar_status=lambda: {
                "market": "tw",
                "timezone": "Asia/Taipei",
                "checked_at": "2026-07-20T13:17:20+08:00",
                "date": "2026-07-20",
                "is_trading_day": True,
                "phase": "regular_live",
                "reason": "trading_day",
                "holiday_name": None,
                "previous_trading_day": "2026-07-17",
                "next_trading_day": "2026-07-21",
                "session": {"open_time": "09:00", "close_time": "13:30"},
                "release_windows": {
                    "market_daily_price": {"expected_trade_date": "2026-07-17"}
                },
            },
            build_taiwan_source_health=lambda **_kwargs: {},
            build_us_overnight_impact_report=lambda **_kwargs: {},
            get_broker_branch_trade_summary=lambda **_kwargs: {},
            read_taiwan_bars=intraday_history,
            read_taiwan_quote_evidence=quote_depth,
            acquire_taiwan_quote_evidence=quote_depth,
            read_taiwan_latest_daily_evidence=lambda *_args, **_kwargs: SimpleNamespace(
                trade_date=datetime.fromisoformat("2026-07-17T00:00:00+08:00").date(),
                close_price=2330.0,
                open_price=2320.0,
                high_price=2340.0,
                low_price=2310.0,
                price_change=10.0,
                trade_volume=1000,
            ),
            get_taiwan_disposition_status=lambda *_args, **_kwargs: {"is_active": False},
            now=lambda: datetime.fromisoformat("2026-07-20T13:17:20+08:00"),
        )

    def test_strict_twse_provider_failure_does_not_fallback_to_yahoo(self) -> None:
        intraday_history = unittest.mock.Mock(
            side_effect=AssertionError("strict provider must not use Yahoo intraday")
        )
        dependencies = self._quote_reader_dependencies(
            quote_depth=unittest.mock.Mock(side_effect=RuntimeError("MIS unavailable")),
            intraday_history=intraday_history,
        )

        result = taiwan_stock.read_stock_quote_context(
            db=SimpleNamespace(),
            stock_id="2330",
            market_data_params={
                "requested_domains": ["quote", "intraday"],
                "external_fetch_allowed": True,
                "provider": "twse_mis",
                "strict_provider": True,
            },
            dependencies=dependencies,
        )

        contract = result["data"]["provider_contract"]
        self.assertFalse(contract["strict_provider"])
        self.assertTrue(contract["legacy_strict_provider"])
        self.assertEqual(contract["legacy_requested_provider"], "twse_mis")
        self.assertEqual(contract["provider_control_status"], "deprecated_ignored")
        self.assertFalse(contract["provider_fallback_used"])
        self.assertIsNone(contract["provider_fallback_reason"])
        self.assertEqual(
            result["data"]["compact"]["freshness_by_domain"]["intraday"],
            "unavailable",
        )
        self.assertGreaterEqual(intraday_history.call_count, 1)
        for call in intraday_history.call_args_list:
            self.assertNotIn("refresh", call.kwargs)

    def test_prefer_live_without_external_fetch_reads_only_persisted_intraday(
        self,
    ) -> None:
        quote_depth = unittest.mock.Mock(return_value={})
        intraday_history = unittest.mock.Mock(
            return_value={
                "interval": "1m",
                "range": "1d",
                "provider": "yahoo_finance_chart",
                "source": "persisted_yahoo_chart",
                "cached_count": 1,
                "refreshed_count": 0,
                "cache_status": "persisted_hit",
                "cache_hit": True,
                "to_time": "2026-07-20T13:17:00+08:00",
                "points": [
                    {
                        "time": "2026-07-20T13:17:00+08:00",
                        "close": 2335.0,
                    }
                ],
            }
        )
        dependencies = self._quote_reader_dependencies(
            quote_depth=quote_depth,
            intraday_history=intraday_history,
        )

        with unittest.mock.patch.object(
            taiwan_stock,
            "project_taiwan_bar_series",
            return_value=intraday_history.return_value,
        ):
            result = taiwan_stock.read_stock_quote_context(
                db=SimpleNamespace(),
                stock_id="2330",
                market_data_params={
                    "requested_domains": ["quote", "intraday"],
                    "realtime_policy": "prefer_live",
                    "external_fetch_allowed": False,
                    "fallback_to_cached": True,
                },
                dependencies=dependencies,
            )

        quote_depth.assert_called_once_with(db=unittest.mock.ANY, stock_id="2330")
        self.assertGreaterEqual(intraday_history.call_count, 1)
        for call in intraday_history.call_args_list:
            self.assertNotIn("refresh", call.kwargs)
        intraday = result["data"]["intraday_bars"]
        self.assertEqual(intraday["read_mode"], "taiwan_bar_service_cache_only")
        self.assertFalse(intraday["provider_refresh_allowed"])
        self.assertEqual(intraday["series"]["1m"]["cache_status"], "persisted_hit")
        contract = result["data"]["provider_contract"]
        self.assertEqual(contract["provider_attempts"], [])
        self.assertEqual(contract["cache_reads"][0]["status"], "persisted_hit")

    def test_non_strict_provider_fallback_is_explicit_and_domain_scoped(self) -> None:
        def intraday_history(**kwargs):
            interval = kwargs["interval"]
            return {
                "interval": interval,
                "range": "1d",
                "provider": "yahoo_finance_chart",
                "source": "yahoo_finance_chart",
                "point_count": 1,
                "refreshed_count": 1,
                "points": [
                    {
                        "time": "2026-07-20T13:17:00+08:00",
                        "open": 2324.0,
                        "high": 2326.0,
                        "low": 2324.0,
                        "close": 2325.0,
                        "volume": 1000,
                    }
                ],
            }

        dependencies = self._quote_reader_dependencies(
            quote_depth=unittest.mock.Mock(
                return_value={
                    "provider": "twse_mis",
                    "source": "twse_mis_quote_depth",
                    "last_price": 2335.0,
                    "quote_time": "2026-07-20T12:24:40+08:00",
                    "depth_available": False,
                    "freshness": {
                        "status": "cached",
                        "is_live": False,
                        "is_stale": True,
                        "source_error": "MIS unavailable",
                    },
                }
            ),
            intraday_history=unittest.mock.Mock(side_effect=intraday_history),
        )

        result = taiwan_stock.read_stock_quote_context(
            db=SimpleNamespace(),
            stock_id="2330",
            market_data_params={
                "requested_domains": ["quote", "intraday"],
                "external_fetch_allowed": True,
                "providers": ["twse_mis"],
                "strict_provider": False,
            },
            dependencies=dependencies,
        )

        contract = result["data"]["provider_contract"]
        refresh = result["data"]["refresh_summary"]
        self.assertEqual(contract["requested_provider"], "auto")
        self.assertEqual(contract["legacy_requested_provider"], "twse_mis")
        self.assertEqual(contract["provider_control_status"], "deprecated_ignored")
        self.assertFalse(contract["provider_fallback_used"])
        self.assertIsNone(contract["provider_fallback_reason"])
        self.assertEqual(refresh["attempted_domains"], ["quote"])
        self.assertEqual(refresh["attempted_dataset_count"], 1)
        self.assertNotIn("fundamentals", refresh["attempted_domains"])
        self.assertNotIn("broker_branch", refresh["attempted_domains"])

    def test_explicit_n225_alias_resolves_to_canonical_symbol(self) -> None:
        payload = AiAskRequest(
            question="日經 225 最新狀態",
            target={"type": "jp_index", "id": "N225"},
            mode="data_only",
            allow_llm=False,
            allow_write=False,
        )

        result = _resolve_scope(None, payload)

        self.assertEqual(result.selected_scope_type, "jp_index")
        self.assertEqual(result.selected_scope_id, "^N225")

    def test_jp_holiday_latest_close_is_not_realtime_or_stale(self) -> None:
        summary = {
            "source": "yahoo_finance_chart",
            "previous_close": 49800.0,
            "session_phase": "regular",
            "points": [{"time": "2026-07-17T15:30:00+09:00", "price": 50000.0, "volume": 1}],
        }
        calendar_status = {
            "market": "jp",
            "timezone": "Asia/Tokyo",
            "checked_at": "2026-07-20T13:00:00+09:00",
            "date": "2026-07-20",
            "is_trading_day": False,
            "phase": "market_closed",
            "reason": "holiday",
            "holiday_name": "Marine Day",
            "previous_trading_day": "2026-07-17",
            "next_trading_day": "2026-07-21",
            "session": {"open_time": "09:00", "close_time": "15:30"},
        }

        quote = _jp_intraday_quote(summary, calendar_status=calendar_status)

        self.assertFalse(quote["is_realtime"])
        self.assertFalse(quote["freshness"]["is_stale"])
        self.assertEqual(quote["market_status"], "closed_holiday")
        self.assertEqual(
            quote["quote_semantics"],
            "latest_completed_session_trade",
        )
        self.assertTrue(quote["last_trade_available"])
        self.assertFalse(quote["depth_available"])
        self.assertFalse(quote["indicative_match_available"])
        self.assertEqual(quote["session_phase"], "market_closed")

    def test_kr_stale_stock_quote_is_not_current_during_session(self) -> None:
        summary = {
            "source": "yahoo_finance_chart",
            "previous_close": 85000.0,
            "session_phase": "regular",
            "points": [{"time": "2026-07-20T13:56:37+09:00", "price": 85500.0, "volume": 10}],
        }
        calendar_status = {
            "market": "kr",
            "timezone": "Asia/Seoul",
            "checked_at": "2026-07-20T14:16:00+09:00",
            "date": "2026-07-20",
            "is_trading_day": True,
            "phase": "regular",
            "reason": "trading_day",
            "holiday_name": None,
            "previous_trading_day": "2026-07-17",
            "next_trading_day": "2026-07-21",
            "session": {"open_time": "09:00", "close_time": "15:30"},
        }

        quote = _kr_intraday_quote(summary, calendar_status=calendar_status)

        self.assertFalse(quote["is_realtime"])
        self.assertTrue(quote["freshness"]["is_stale"])
        self.assertEqual(quote["freshness"]["age_seconds"], 1163)
        self.assertEqual(quote["market_status"], "open")
        self.assertEqual(
            quote["quote_semantics"],
            "delayed_current_session_trade",
        )
        self.assertTrue(quote["last_trade_available"])
        self.assertFalse(quote["depth_available"])
        self.assertFalse(quote["indicative_match_available"])

    def test_quote_depth_age_uses_exchange_quote_time_not_fetch_time(self) -> None:
        row = SimpleNamespace(
            quote_time=datetime.fromisoformat("2026-07-20T12:24:40+08:00"),
            fetched_at=datetime.fromisoformat("2026-07-20T13:17:01+08:00"),
            trade_date=datetime.fromisoformat("2026-07-20T00:00:00+08:00").date(),
        )

        freshness = _freshness_for_row(
            row,
            phase="regular_live",
            now=datetime.fromisoformat("2026-07-20T13:17:41+08:00"),
        )

        self.assertEqual(freshness["age_seconds"], 3181)
        self.assertEqual(freshness["fetch_age_seconds"], 40)
        self.assertEqual(freshness["status"], "stale")

    def test_provider_http_diagnostics_preserve_status_type_and_content_type(self) -> None:
        response = requests.Response()
        response.status_code = 429
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        response.headers["Retry-After"] = "90"

        with self.assertRaises(ProviderHttpError) as caught:
            provider_request(
                ProviderRequestContext(
                    market="tw",
                    provider="twse_mis",
                    resource="quote_depth",
                    target="2330",
                ),
                "GET",
                "https://example.test/quote",
                timeout_seconds=(2, 5),
                request_callable=lambda *_args, **_kwargs: response,
            )

        diagnostics = caught.exception.failure.diagnostic_fields()
        self.assertEqual(diagnostics["http_status_code"], 429)
        self.assertEqual(diagnostics["exception_type"], "HTTPError")
        self.assertEqual(diagnostics["response_content_type"], "text/html; charset=utf-8")
        self.assertEqual(diagnostics["retry_after_seconds"], 90)
        self.assertEqual(diagnostics["retry_count"], 0)

    def test_quote_depth_provider_context_is_not_mislabeled_as_index_snapshot(self) -> None:
        sentinel = object()
        with patch.object(twse_mis, "get", return_value=sentinel) as get:
            result = twse_mis.get_response(
                "https://mis.twse.com.tw/stock/api/getStockInfo.jsp",
                params={"ex_ch": "tse_2330.tw"},
                omi_resource="quote_depth",
                omi_target="2330",
            )

        self.assertIs(result, sentinel)
        self.assertEqual(get.call_args.kwargs["resource"], "quote_depth")
        self.assertEqual(get.call_args.kwargs["target"], "2330")
        self.assertNotIn("omi_resource", get.call_args.kwargs)

    def test_domain_passport_does_not_let_fundamentals_pollute_quote_trust(self) -> None:
        passport = _domain_passport(
            compact={
                "freshness_by_domain": {
                    "quote": "live",
                    "intraday": "waiting",
                    "fundamentals": "stale",
                }
            },
            query_plan={"requested_domains": ["quote"]},
        )

        self.assertEqual(passport["quote_trust"]["trust_level"], "high")
        self.assertEqual(passport["fundamentals_trust"]["trust_level"], "low")
        self.assertEqual(passport["decision_readiness"]["status"], "ready")

    def test_holiday_live_feed_health_is_closed_not_missing(self) -> None:
        holiday_calendar = {
            "market": "jp",
            "timezone": "Asia/Tokyo",
            "checked_at": "2026-07-20T13:00:00+09:00",
            "date": "2026-07-20",
            "is_trading_day": False,
            "phase": "market_closed",
            "reason": "holiday",
            "holiday_name": "Marine Day",
            "session": {"open_time": "09:00", "close_time": "15:30"},
        }
        envelope = {
            "as_of": "2026-07-17",
            "missing": ["jp_fundamental"],
            "evidence_passport": {"data_freshness": "stale"},
        }

        with patch(
            "app.ai.tools.build_market_calendar_status",
            return_value={"markets": {"jp": holiday_calendar}},
        ):
            dimensions = _health_dimensions(envelope, market="JP")

        self.assertEqual(dimensions["live_feed_health"]["status"], "closed_holiday")
        self.assertEqual(dimensions["database_freshness"]["status"], "stale")
        self.assertEqual(dimensions["coverage_completeness"]["status"], "partial")

    def test_disposition_contract_marks_batch_auction_and_advances_next_batch(self) -> None:
        quote = {
            "last_price": 288.0,
            "last_trade_available": True,
            "best_bid_price": 287.5,
            "best_ask_price": 289.0,
            "quote_time": "2026-07-20T09:02:00+08:00",
            "market_status": "open",
        }
        _apply_disposition_quote_contract(
            quote,
            {
                "is_active": True,
                "cache_status": "current",
                "matching_interval_minutes": 20,
                "start_date": "2026-07-20",
                "end_date": "2026-07-31",
            },
            now=datetime.fromisoformat("2026-07-20T09:25:00+08:00"),
        )

        self.assertEqual(quote["trading_mode"], "disposition_batch_auction")
        self.assertEqual(quote["market_status"], "disposition_batch_auction")
        self.assertEqual(quote["last_trade_price"], 288.0)
        self.assertEqual(quote["indicative_bid"], 287.5)
        self.assertEqual(quote["next_batch_time"], "2026-07-20T09:42:00+08:00")

    def test_disposition_contract_does_not_invent_unavailable_last_trade(self) -> None:
        quote = {
            "last_price": 288.0,
            "price": 288.0,
            "last_trade_available": False,
            "quote_time": "2026-07-20T08:55:00+08:00",
        }

        _apply_disposition_quote_contract(
            quote,
            {"is_active": False, "cache_status": "current"},
        )

        self.assertFalse(quote["last_trade_available"])
        self.assertIsNone(quote["last_trade_price"])

    def test_disposition_points_drop_repeated_poll_snapshots(self) -> None:
        points = [
            {"time": "2026-07-20T09:02:00+08:00", "close": 288.0, "volume": 428000},
            {"time": "2026-07-20T09:13:00+08:00", "close": 288.0, "volume": 428000},
            {"time": "2026-07-20T09:22:00+08:00", "close": 289.0, "volume": 430000},
        ]

        deduped = _dedupe_disposition_points(points)

        self.assertEqual(len(deduped), 2)
        self.assertEqual(deduped[-1]["volume"], 430000)

    def test_disposition_points_keep_a_new_official_trade_timestamp(self) -> None:
        points = [
            {
                "time": "2026-07-20T09:02:00+08:00",
                "close": 288.0,
                "volume": 428000,
                "official_trade_timestamp": "2026-07-20T09:00:00+08:00",
            },
            {
                "time": "2026-07-20T09:13:00+08:00",
                "close": 288.0,
                "volume": 428000,
                "official_trade_timestamp": "2026-07-20T09:10:00+08:00",
            },
        ]

        self.assertEqual(len(_dedupe_disposition_points(points)), 2)


if __name__ == "__main__":
    unittest.main()
