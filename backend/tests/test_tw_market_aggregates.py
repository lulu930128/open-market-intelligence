from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from app.ai.market_context import taiwan_market, taiwan_screening


class TaiwanMarketAggregateTests(unittest.TestCase):
    def test_intraday_sector_merge_overrides_daily_sample(self) -> None:
        daily = {
            "kind": "tw_market_sectors",
            "data_mode": "previous_completed_session",
            "is_intraday": False,
            "items": [{"name": "每日樣本"}],
        }
        intraday = {
            "kind": "tw_market_sectors",
            "status": "ready",
            "data_mode": "intraday_rolling_state",
            "is_intraday": True,
            "snapshot_id": "tw_intraday_groups:2026-07-31:10:00:2",
            "items": [{"name": "半導體業"}],
        }
        market_context = {
            "data": {
                "market": {"sectors": daily},
                "compact": {"market": {"sectors": daily}},
                "freshness_by_capability": {
                    "market.sectors": {"status": "partial"}
                },
                "slots": {
                    "market_sectors": {"status": "partial"}
                },
            },
            "missing": [],
            "warnings": [],
            "source_refs": [],
        }
        screening_context = {
            "data": {
                "screening": {},
                "market": {"sectors": intraday},
                "compact": {
                    "screening": {},
                    "market": {"sectors": intraday},
                },
                "freshness_by_capability": {
                    "market.sectors": {"status": "ready"}
                },
                "slots": {"market_sectors": {"status": "ready"}},
            },
            "missing": [],
            "warnings": [],
            "source_refs": [],
        }

        merged = taiwan_screening.merge_tw_screening_context(
            market_context,
            screening_context,
        )

        self.assertEqual(
            merged["data"]["market"]["sectors"]["data_mode"],
            "intraday_rolling_state",
        )
        self.assertEqual(
            merged["data"]["compact"]["market"]["sectors"][
                "snapshot_id"
            ],
            intraday["snapshot_id"],
        )
        self.assertEqual(
            merged["data"]["freshness_by_capability"][
                "market.sectors"
            ]["status"],
            "ready",
        )

    def test_sector_merge_keeps_daily_fallback_when_intraday_missing(self) -> None:
        daily = {
            "kind": "tw_market_sectors",
            "status": "partial",
            "data_mode": "previous_completed_session",
            "is_intraday": False,
            "items": [{"name": "每日樣本"}],
        }
        merged = taiwan_screening.merge_tw_screening_context(
            {
                "data": {
                    "market": {"sectors": daily},
                    "compact": {"market": {"sectors": daily}},
                },
                "missing": [],
                "warnings": [],
                "source_refs": [],
            },
            {
                "data": {
                    "screening": {},
                    "market": {},
                    "compact": {"screening": {}, "market": {}},
                },
                "missing": [],
                "warnings": [
                    "Intraday sector state is unavailable; daily fallback retained."
                ],
                "source_refs": [],
            },
        )

        self.assertEqual(
            merged["data"]["market"]["sectors"]["data_mode"],
            "previous_completed_session",
        )
        self.assertEqual(
            merged["data"]["compact"]["market"]["sectors"]["items"],
            [{"name": "每日樣本"}],
        )

    @staticmethod
    def _dependencies(**overrides):
        values = {
            "market_service": SimpleNamespace(),
            "get_market_index_intraday": Mock(),
            "get_market_index_summary": Mock(),
            "read_cross_market_context": Mock(),
            "read_market_chips_context": Mock(),
            "read_market_volume_state": Mock(),
            "build_taiwan_source_health": Mock(),
            "now": Mock(),
            "get_market_index_contributions": Mock(),
            "list_taiwan_corporate_events": None,
        }
        values.update(overrides)
        return taiwan_market.TaiwanMarketDependencies(**values)

    @staticmethod
    def _official_market_chips(*, same_trade_date: bool) -> dict:
        dates = (
            ["2026-07-28"]
            if same_trade_date
            else ["2026-07-28", "2026-07-29"]
        )
        return {
            "official_market_aggregate": {
                "same_trade_date": same_trade_date,
                "trade_dates": dates,
                "markets": ["TWSE", "TPEX"],
                "rows": [
                    {
                        "index_id": "TAIEX",
                        "market": "TWSE",
                        "source_grade": "official",
                        "total_institutional_net_value": 100,
                        "foreign_investor_net_value": 80,
                        "investment_trust_net_value": 10,
                        "dealer_net_value": 10,
                        "margin_balance_change_value": 50,
                        "margin_balance_change_shares": 5,
                        "short_balance_change_shares": -2,
                    },
                    {
                        "index_id": "TPEX",
                        "market": "TPEX",
                        "source_grade": "official",
                        "total_institutional_net_value": 40,
                        "foreign_investor_net_value": 25,
                        "investment_trust_net_value": 10,
                        "dealer_net_value": 5,
                        "margin_balance_change_value": -10,
                        "margin_balance_change_shares": -1,
                        "short_balance_change_shares": 3,
                    },
                ],
            }
        }

    def test_same_date_official_rows_are_aggregated_with_units(self) -> None:
        institutional, margin = (
            taiwan_market._official_market_flow_capabilities(
                self._official_market_chips(same_trade_date=True)
            )
        )

        self.assertEqual(institutional["status"], "ready")
        self.assertEqual(institutional["unit"], "TWD")
        self.assertEqual(
            institutional["aggregate"]["total_institutional_net_value"],
            140,
        )
        self.assertEqual(
            margin["aggregate"]["margin_balance_change_value"],
            40,
        )
        self.assertEqual(
            margin["unit_semantics"]["short_balance_change_shares"],
            "shares",
        )

    def test_mismatched_official_dates_withhold_combined_totals(self) -> None:
        institutional, margin = (
            taiwan_market._official_market_flow_capabilities(
                self._official_market_chips(same_trade_date=False)
            )
        )

        self.assertEqual(institutional["status"], "partial")
        self.assertIsNone(
            institutional["aggregate"]["total_institutional_net_value"]
        )
        self.assertIsNone(
            margin["aggregate"]["margin_balance_change_value"]
        )
        self.assertIn("different trade dates", institutional["warnings"][0])

    def test_sector_fallback_is_explicitly_local_sample(self) -> None:
        capability = taiwan_market._sample_sector_capability(
            industry_summary=[
                {
                    "industry": "半導體",
                    "average_change_pct": 1.5,
                    "advance_count": 4,
                    "decline_count": 1,
                    "trade_value": 10_000,
                    "count": 5,
                }
            ],
            sample_coverage={
                "universe_count": 1900,
                "coverage_count": 100,
                "coverage_ratio": 100 / 1900,
            },
            as_of="2026-07-29",
        )

        self.assertEqual(capability["status"], "partial")
        self.assertFalse(capability["is_full_market"])
        self.assertEqual(
            capability["ranking_basis"],
            "omi_local_daily_sample_stock_aggregation",
        )
        self.assertEqual(
            capability["aggregation_method"],
            "equal_weighted_mean_stock_return_pct",
        )
        self.assertEqual(capability["items"][0]["trade_value_unit"], "TWD")
        self.assertEqual(capability["missing"], [])
        self.assertEqual(
            capability["coverage_gaps"],
            ["market_daily_price.full_market_sector_index"],
        )
        self.assertIn("must not be treated", capability["warnings"][0])

    def test_contribution_reader_is_not_called_without_external_authority(
        self,
    ) -> None:
        contribution_reader = Mock()
        dependencies = self._dependencies(
            get_market_index_contributions=contribution_reader,
        )

        capability = taiwan_market._market_index_contributions_capability(
            db=SimpleNamespace(),
            dependencies=dependencies,
            data_params={
                "external_fetch_allowed": False,
                "capability_parameters": {
                    "market.index_contributions": {
                        "index_ids": ["TAIEX"],
                        "limit": 5,
                    }
                },
            },
        )

        self.assertEqual(capability["status"], "not_requested")
        self.assertEqual(
            capability["cache_policy"],
            "external_fetch_required_bounded",
        )
        contribution_reader.assert_not_called()

    def test_contribution_reader_records_fetches_and_enforces_budget(
        self,
    ) -> None:
        contribution_reader = Mock(
            return_value={
                "trade_date": "2026-07-29",
                "source": "twse_official",
                "reconciliation_status": "within_tolerance",
                "positive": [],
                "negative": [],
            }
        )
        dependencies = self._dependencies(
            get_market_index_contributions=contribution_reader,
        )

        capability = taiwan_market._market_index_contributions_capability(
            db=SimpleNamespace(),
            dependencies=dependencies,
            data_params={
                "external_fetch_allowed": True,
                "tool_budget": {"max_external_fetches": 1},
                "capability_parameters": {
                    "market.index_contributions": {
                        "index_ids": ["TAIEX", "TPEX"],
                        "limit": 5,
                    }
                },
            },
        )

        self.assertEqual(contribution_reader.call_count, 1)
        self.assertEqual(
            [run["status"] for run in capability["tool_runs"]],
            ["success", "skipped_budget"],
        )
        self.assertTrue(
            all(run["external_fetch"] for run in capability["tool_runs"])
        )
        self.assertFalse(
            any(run["writes_cache"] for run in capability["tool_runs"])
        )
        self.assertEqual(
            capability["tool_runs"][0]["requested_capabilities"],
            ["market.index_contributions"],
        )
        self.assertEqual(
            capability["missing"],
            ["market_index_contributions.TPEX"],
        )

    def test_current_empty_event_calendar_is_valid(self) -> None:
        listing = Mock(
            return_value={
                "as_of": date(2026, 7, 29),
                "date_from": date(2026, 7, 29),
                "date_to": date(2026, 8, 28),
                "result_count": 0,
                "total_count": 0,
                "results": [],
                "sources": {
                    "twse_ex_dividend": {"status": "current"},
                    "tpex_ex_dividend": {"status": "current"},
                    "mops_conference": {"status": "current"},
                },
                "warning": None,
            }
        )
        dependencies = self._dependencies(
            list_taiwan_corporate_events=listing
        )
        now = datetime(2026, 7, 29, 2, 0, tzinfo=timezone.utc)

        capability = taiwan_market._events_calendar_capability(
            dependencies=dependencies,
            data_params={
                "capability_parameters": {
                    "events.calendar": {
                        "date_from": "2026-07-29",
                        "date_to": "2026-08-28",
                        "event_types": ["investor_conference"],
                        "markets": ["TWSE", "TPEX"],
                        "limit": 50,
                        "offset": 0,
                    }
                }
            },
            generated_at=now,
        )

        self.assertEqual(capability["status"], "ready")
        self.assertTrue(capability["empty_result_is_valid"])
        self.assertEqual(capability["events"], [])
        listing.assert_called_once_with(
            event_types={"investor_conference"},
            markets={"TWSE", "TPEX"},
            stock_ids=None,
            date_from=date(2026, 7, 29),
            date_to=date(2026, 8, 28),
            limit=50,
            offset=0,
            now=now,
        )

    def test_event_calendar_filters_and_paginates_cached_rows(self) -> None:
        rows = [
            {
                "event_id": "event-2",
                "market": "TWSE",
                "stock_id": "2330",
                "start_date": date(2026, 8, 3),
            }
        ]
        listing = Mock(
            return_value={
                "as_of": date(2026, 7, 29),
                "date_from": date(2026, 7, 29),
                "date_to": date(2026, 10, 27),
                "total_count": 2,
                "results": rows,
                "sources": {
                    "twse_ex_dividend": {"status": "current"},
                },
                "warning": None,
            }
        )
        dependencies = self._dependencies(
            list_taiwan_corporate_events=listing
        )

        capability = taiwan_market._events_calendar_capability(
            dependencies=dependencies,
            data_params={
                "capability_parameters": {
                    "events.calendar": {
                        "markets": ["TWSE"],
                        "stock_ids": ["2330"],
                        "limit": 1,
                        "offset": 1,
                    }
                }
            },
            generated_at=datetime(
                2026,
                7,
                29,
                2,
                0,
                tzinfo=timezone.utc,
            ),
        )

        self.assertEqual(capability["result_count"], 1)
        self.assertEqual(capability["events"][0]["event_id"], "event-2")
        self.assertEqual(capability["pagination"]["available_count"], 2)
        self.assertFalse(capability["pagination"]["has_more"])
        listing.assert_called_once_with(
            event_types=None,
            markets={"TWSE"},
            stock_ids={"2330"},
            date_from=None,
            date_to=None,
            limit=1,
            offset=1,
            now=datetime(
                2026,
                7,
                29,
                2,
                0,
                tzinfo=timezone.utc,
            ),
        )

    def test_event_calendar_rejects_ranges_over_366_days(self) -> None:
        dependencies = self._dependencies(
            list_taiwan_corporate_events=Mock()
        )
        capability = taiwan_market._events_calendar_capability(
            dependencies=dependencies,
            data_params={
                "capability_parameters": {
                    "events.calendar": {
                        "date_from": "2026-01-01",
                        "date_to": "2027-01-03",
                    }
                }
            },
            generated_at=datetime(
                2026,
                7,
                29,
                2,
                0,
                tzinfo=timezone.utc,
            ),
        )

        self.assertEqual(capability["status"], "invalid")
        self.assertIn("366 days", capability["warnings"][0])
        dependencies.list_taiwan_corporate_events.assert_not_called()


if __name__ == "__main__":
    unittest.main()
