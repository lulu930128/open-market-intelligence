from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.ai import agentic_tools, tools
from app.ai.market_context import common, us_context
from app.ai.market_context import taiwan_market, taiwan_projection
from app.ai.schemas import AiDataEnvelope
from app.ai.market_context.crypto_context import (
    _crypto_core_source_health_status,
    _crypto_health_status,
    _crypto_market_cap_matches_asset,
)
from app.crypto_market.assets import get_crypto_asset


class AIMarketContextProjectionTests(unittest.TestCase):
    def test_taiwan_market_breadth_combines_twse_and_tpex(self) -> None:
        summary = {
            "as_of": "2026-07-22T13:30:00+08:00",
            "indices": [
                {
                    "index_id": "TAIEX",
                    "breadth": {
                        "market": "TWSE",
                        "scope": "full_market",
                        "trade_date": "2026-07-22",
                        "advance_count": 530,
                        "decline_count": 464,
                        "unchanged_count": 68,
                        "total_count": 1062,
                        "limit_up_count": 30,
                        "limit_down_count": 2,
                        "trade_value": 1_025_958_396_323,
                        "source": "twse_rwd_mi_index",
                    },
                    "breadth_status": {"status": "ready"},
                },
                {
                    "index_id": "TPEX",
                    "breadth": {
                        "market": "TPEX",
                        "scope": "full_market",
                        "trade_date": "2026-07-22",
                        "advance_count": 535,
                        "decline_count": 257,
                        "unchanged_count": 74,
                        "total_count": 866,
                        "limit_up_count": 28,
                        "limit_down_count": 2,
                        "trade_value": 186_314_449_680,
                        "source": "tpex_openapi_mainboard_quotes",
                    },
                    "breadth_status": {"status": "ready"},
                },
            ],
        }
        refs: list[dict] = []
        breadth = taiwan_market._market_breadth_from_index_summary(
            db=SimpleNamespace(),
            dependencies=SimpleNamespace(
                get_market_index_summary=lambda *_args, **_kwargs: summary
            ),
            warnings=[],
            source_refs=refs,
        )

        self.assertIsNotNone(breadth)
        self.assertEqual(breadth["status"], "ready")
        self.assertEqual(breadth["included_markets"], ["TWSE", "TPEX"])
        self.assertEqual(breadth["advance_count"], 1065)
        self.assertEqual(breadth["decline_count"], 721)
        self.assertEqual(breadth["total_count"], 1928)
        self.assertEqual(breadth["trade_value"], 1_212_272_846_003)
        self.assertEqual(breadth["markets"]["TWSE"]["total_count"], 1062)
        self.assertEqual(breadth["markets"]["TPEX"]["total_count"], 866)
        self.assertEqual(refs, [{"type": "derived", "name": "app.market.indices.summary"}])

    def test_sample_derived_market_slots_are_partial_when_coverage_is_partial(self) -> None:
        slots = taiwan_projection._build_tw_market_slots(
            as_of="2026-07-22",
            payload_level="compact",
            breadth={"status": "ready", "total_count": 1928},
            sample_coverage={
                "status": "partial",
                "sample_count": 84,
                "universe_count": 1973,
                "coverage_ratio": 84 / 1973,
            },
            distribution={"mild_up_count": 75},
            industry_rows=[{"industry": "Semiconductor"}],
            index_intraday={"enabled": False},
            cross_market={"status": "ready"},
            market_chips={"status": "ready"},
            volume_state={"status": "partial", "warnings": ["history accumulating"]},
            missing=["market_daily_price.full_market_coverage"],
            warnings=["sample coverage is partial"],
        )

        self.assertEqual(slots["market_breadth"]["status"], "ready")
        self.assertEqual(slots["distribution"]["status"], "partial")
        self.assertEqual(slots["sector_industry"]["status"], "partial")

    def test_ai_data_envelope_preserves_top_level_freshness(self) -> None:
        envelope = AiDataEnvelope.model_validate(
            {
                "kind": "market_overview",
                "generated_at": "2026-07-22T13:30:00+08:00",
                "freshness": {"is_current": False, "missing": ["sample_coverage"]},
            }
        )

        self.assertEqual(
            envelope.model_dump(mode="json")["freshness"],
            {"is_current": False, "missing": ["sample_coverage"]},
        )

    def test_evidence_passport_projection_keeps_same_top_level_freshness(self) -> None:
        freshness = {
            "is_current": False,
            "missing": ["market_breadth.tpex"],
            "warnings": ["TPEX breadth is unavailable."],
        }

        envelope = taiwan_projection._with_evidence_passport(
            {
                "kind": "market_overview",
                "as_of": "2026-07-22",
                "missing": ["market_breadth.tpex"],
                "warnings": ["TPEX breadth is unavailable."],
                "source_refs": [],
                "data": {},
            },
            freshness=freshness,
        )

        self.assertEqual(envelope["freshness"], freshness)
        self.assertEqual(envelope["evidence_passport"]["data_freshness"], "stale")

    def test_us_intraday_quote_is_not_live_when_market_is_closed(self) -> None:
        quote = us_context._us_intraday_quote(
            {
                "source": "yahoo_finance_chart",
                "session_phase": "regular",
                "previous_close": 100.0,
                "latest_point": {
                    "time": "2026-07-17T16:00:00-04:00",
                    "session": "regular",
                    "price": 101.0,
                    "volume": 10,
                },
            },
            calendar_status={
                "checked_at": "2026-07-18T12:00:00-04:00",
                "date": "2026-07-18",
                "is_trading_day": False,
                "phase": "closed",
                "previous_trading_day": "2026-07-17",
            },
        )

        self.assertFalse(quote["is_realtime"])
        self.assertFalse(quote["is_live"])
        self.assertTrue(quote["is_latest_session_quote"])
        self.assertEqual(quote["market_status"], "closed")
        self.assertEqual(quote["last_quote_session"], "regular")
        self.assertEqual(quote["volume_unit"], "shares")
        self.assertEqual(quote["volume_semantics"], "interval_shares")

    def test_us_intraday_compact_declares_share_volume_unit(self) -> None:
        compact = us_context._us_intraday_compact(
            {
                "source": "yahoo_finance_chart",
                "point_count": 2,
                "points": [
                    {
                        "time": "2026-07-24T09:30:00-04:00",
                        "price": 210.0,
                        "volume": 100,
                    },
                    {
                        "time": "2026-07-24T09:31:00-04:00",
                        "price": 210.5,
                        "volume": 120,
                    },
                ],
            },
            market_data_params={"intraday_limit": 2},
        )

        series = compact["series"]["1m"]
        self.assertEqual(series["volume_unit"], "shares")
        self.assertEqual(series["volume_semantics"], "interval_shares")

    def test_ai_tool_modules_keep_common_projection_facades(self) -> None:
        self.assertIs(agentic_tools._compact_market_context, common.compact_market_context)
        self.assertIs(agentic_tools._append_source_ref_once, common.append_source_ref_once)
        self.assertIs(tools._append_source_ref_once, common.append_source_ref_once)

    def test_compact_stock_context_exposes_missing_and_not_requested_slots(self) -> None:
        compact = common.compact_market_context(
            kind="us_stock_compact_evidence",
            target={"type": "us_stock", "symbol": "AAPL"},
            quote={},
            resources={"include_intraday": False, "daily_rows": 0},
            freshness={"price": {"status": "missing"}},
        )

        self.assertEqual(compact["version"], "market_compact_evidence.v1")
        self.assertEqual(compact["slots"]["identity"]["status"], "ready")
        self.assertEqual(compact["slots"]["quote"]["status"], "missing")
        self.assertEqual(compact["slots"]["intraday"]["status"], "not_requested")
        self.assertEqual(compact["slots"]["fundamentals"]["status"], "missing")
        self.assertEqual(compact["slots"]["data_quality"]["status"], "partial")

    def test_compact_crypto_context_requires_derivatives_when_missing(self) -> None:
        slots = common.compact_market_slots(
            target={"type": "crypto_asset", "asset": "BTC"},
            quote={"last_price": 100},
            resources={"ohlcv_rows": 2, "derivatives_rows": 0},
            freshness={"quote": {"status": "current"}},
            payload_level="compact",
        )

        self.assertEqual(slots["quote"]["status"], "ready")
        self.assertEqual(slots["daily_chart"]["status"], "ready")
        self.assertEqual(slots["derivatives"]["status"], "missing")

    def test_stale_or_failed_freshness_never_produces_ready_slots(self) -> None:
        stale_slots = common.compact_market_slots(
            target={"type": "crypto_asset", "asset": "BTC"},
            quote={"last_price": 100},
            resources={"ohlcv_rows": 2},
            freshness={"quote": "stale", "ohlcv": {"status": "delayed"}},
            payload_level="compact",
        )
        failed_slots = common.compact_market_slots(
            target={"type": "us_stock", "symbol": "TSM"},
            quote={"price": 100},
            resources={"daily_rows": 2},
            freshness={
                "price": {"status": "current"},
                "source_health": {"provider_error": "upstream timeout"},
            },
            payload_level="compact",
        )

        self.assertEqual(stale_slots["quote"]["status"], "stale")
        self.assertEqual(stale_slots["daily_chart"]["status"], "stale")
        self.assertEqual(stale_slots["data_quality"]["status"], "stale")
        self.assertEqual(failed_slots["quote"]["status"], "ready")
        self.assertEqual(failed_slots["data_quality"]["status"], "failed")
        self.assertIn("data_quality_and_freshness", failed_slots["data_quality"]["missing"])

    def test_empty_and_summary_health_counts_are_consumer_visible_problems(self) -> None:
        self.assertEqual(common.freshness_problem_status("empty"), "missing")
        self.assertEqual(
            common.freshness_problem_status({"summary": {"healthy": 2, "stale": 3, "empty": 1}}),
            "stale",
        )
        self.assertEqual(
            common.freshness_problem_status({"status": "blocked", "missing": ["api_key"]}),
            "blocked",
        )

    def test_crypto_health_uses_resource_status_not_row_existence(self) -> None:
        source_health = {
            "entries": [
                {
                    "resource": "crypto_ticker",
                    "status": "stale",
                    "ok": False,
                    "required": True,
                },
                {
                    "resource": "crypto_realtime_liquidation_event",
                    "status": "empty",
                    "ok": False,
                    "required": True,
                },
            ]
        }

        self.assertEqual(
            _crypto_health_status(
                source_health,
                resources={"crypto_ticker"},
                available=True,
            ),
            "stale",
        )
        self.assertEqual(_crypto_core_source_health_status(source_health), "stale")

    def test_optional_event_empty_does_not_make_crypto_core_unhealthy(self) -> None:
        source_health = {
            "entries": [
                {
                    "resource": "crypto_ticker",
                    "status": "live",
                    "ok": True,
                    "required": True,
                },
                {
                    "resource": "crypto_realtime_liquidation_event",
                    "status": "empty",
                    "ok": False,
                    "required": True,
                },
            ]
        }

        self.assertEqual(_crypto_core_source_health_status(source_health), "current")

    def test_source_refs_are_deduplicated_by_name_or_kind(self) -> None:
        refs: list[dict] = []
        common.append_source_ref_once(refs, {"type": "table", "name": "daily_price"})
        common.append_source_ref_once(refs, {"type": "table", "name": "daily_price"})
        common.append_source_ref_once(refs, {"type": "derived", "kind": "freshness"})

        self.assertEqual(len(refs), 2)

    def test_stock_capability_freshness_isolated_per_chip_dataset(self) -> None:
        source_health = {
            "entries": [
                {
                    "resource": "institutional_trade_daily",
                    "status": "current",
                    "ok": True,
                    "latest_data_date": "2026-07-24",
                    "expected_data_date": "2026-07-24",
                },
                {
                    "resource": "margin_trading_daily",
                    "status": "current",
                    "ok": True,
                    "latest_data_date": "2026-07-24",
                    "expected_data_date": "2026-07-24",
                },
                {
                    "resource": "shareholding_distribution_weekly",
                    "status": "stale",
                    "ok": False,
                    "latest_data_date": "2026-07-17",
                    "expected_data_date": "2026-07-24",
                },
            ]
        }

        freshness = taiwan_projection._build_freshness_by_capability(
            quote={},
            intraday_bars={"enabled": False},
            source_health=source_health,
            overnight_impact=None,
            missing=[],
        )

        self.assertEqual(freshness["chips.institutional"]["status"], "current")
        self.assertFalse(
            freshness["chips.institutional"]["refresh_recommended"]
        )
        self.assertEqual(freshness["chips.margin"]["status"], "current")
        self.assertFalse(freshness["chips.margin"]["refresh_recommended"])
        self.assertEqual(
            freshness["ownership.distribution"]["status"],
            "stale",
        )
        self.assertTrue(
            freshness["ownership.distribution"]["refresh_recommended"]
        )

    def test_missing_shareholding_remains_refreshable_during_release_window(
        self,
    ) -> None:
        freshness = taiwan_projection._freshness_for_resource(
            source_health={
                "entries": [
                    {
                        "resource": "shareholding_distribution_weekly",
                        "status": "empty",
                        "ok": False,
                        "row_count": 0,
                        "release_status": "pending",
                        "refresh_eligible": True,
                        "expected_data_date": "2026-07-17",
                    }
                ]
            },
            resource="shareholding_distribution_weekly",
            missing=["shareholding_distribution_weekly"],
        )

        self.assertEqual(freshness["status"], "empty")
        self.assertEqual(freshness["release_status"], "pending")
        self.assertFalse(freshness["is_current"])
        self.assertTrue(freshness["refresh_recommended"])

    def test_crypto_market_cap_identity_prefers_registry_coin_id(self) -> None:
        ton = get_crypto_asset("TON")

        self.assertIsNotNone(ton)
        self.assertTrue(
            _crypto_market_cap_matches_asset(
                SimpleNamespace(coin_id="the-open-network", symbol="gram"),
                ton,
            )
        )
        self.assertFalse(
            _crypto_market_cap_matches_asset(
                SimpleNamespace(coin_id="bitcoin", symbol="btc"),
                ton,
            )
        )


if __name__ == "__main__":
    unittest.main()
