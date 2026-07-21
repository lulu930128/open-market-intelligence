from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app.jobs import scheduler
from app.market import tw_corporate_events
from app.market.providers.tw_corporate_events import (
    parse_mops_conferences,
    parse_tpex_ex_dividend_history,
    parse_tpex_ex_dividends,
    parse_twse_ex_dividend_history,
    parse_twse_ex_dividends,
)
from app.market.tw_corporate_events import (
    backfill_taiwan_corporate_event_history,
    get_taiwan_stock_event_history,
    get_taiwan_stock_event_summary,
    list_taiwan_corporate_events,
    refresh_taiwan_corporate_events,
)
from app.routers import market as market_router


TEST_TMP_ROOT = Path(__file__).resolve().parents[2] / ".tmp" / "corporate-event-tests"
TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)


class _TestProcessLock:
    def __init__(self, _path: Path) -> None:
        pass

    def acquire(self, **_kwargs) -> bool:
        return True

    def release(self) -> None:
        pass


@contextmanager
def _cache_path(name: str):
    path = TEST_TMP_ROOT / f"{name}.json"
    path.unlink(missing_ok=True)
    try:
        yield path
    finally:
        tw_corporate_events.invalidate_taiwan_corporate_event_cache()
        path.unlink(missing_ok=True)


MOPS_HTML = """
<table id="myTable">
  <tr data-type="body">
    <td>2330</td><td>台積電</td><td>115/07/16</td><td>14:00</td>
    <td>線上法說會</td>
    <td>公布本公司2026年第2季財務報告及第3季業績展望。</td>
    <td></td><td></td>
    <td><a href="https://investor.example/2330">公司網站</a></td>
    <td><a href="https://video.example/2330">影音</a></td>
    <td>無</td><td></td>
  </tr>
  <tr data-type="body">
    <td>2301</td><td>光寶科</td><td>115/07/13 至 115/07/14</td><td>09:00</td>
    <td>美國紐約</td><td>券商安排之海外投資人會議，說明營運概況。</td>
    <td></td><td></td><td></td><td></td><td>無</td><td></td>
  </tr>
</table>
"""


class TaiwanCorporateEventParserTests(unittest.TestCase):
    def test_ex_dividend_parsers_keep_official_date_and_amount(self) -> None:
        twse = parse_twse_ex_dividends(
            [
                {
                    "Date": "20260728",
                    "Code": "2330",
                    "Name": "台積電",
                    "Exdividend": "除息",
                    "CashDividend": "5.00",
                    "StockDividendRatio": "0",
                }
            ]
        )
        tpex = parse_tpex_ex_dividends(
            [
                {
                    "ExRrightsExDividendDate": "115/07/29",
                    "SecuritiesCompanyCode": "8069",
                    "CompanyName": "元太",
                    "ExRrightsExDividend": "除權息",
                    "CashDividend": "3",
                    "StockDividendRatio": "0.1",
                }
            ]
        )

        self.assertEqual(twse[0]["start_date"], date(2026, 7, 28))
        self.assertEqual(twse[0]["cash_dividend"], 5.0)
        self.assertEqual(tpex[0]["market"], "TPEX")
        self.assertEqual(tpex[0]["stock_dividend_ratio"], 0.1)

    def test_mops_parser_emits_financial_event_only_for_explicit_publication(self) -> None:
        rows = parse_mops_conferences(MOPS_HTML, market="TWSE")

        self.assertEqual(len(rows), 3)
        financial = [row for row in rows if row["event_type"] == "financial_report"]
        conferences = [row for row in rows if row["event_type"] == "investor_conference"]
        self.assertEqual(len(financial), 1)
        self.assertEqual(financial[0]["stock_id"], "2330")
        self.assertEqual(financial[0]["timing_status"], "scheduled")
        self.assertEqual(conferences[1]["end_date"], date(2026, 7, 14))

    def test_mops_parser_rejects_schema_drift(self) -> None:
        with self.assertRaises(ValueError):
            parse_mops_conferences("<html></html>", market="TWSE")

    def test_historical_ex_dividend_parsers_keep_actual_dates(self) -> None:
        twse = parse_twse_ex_dividend_history(
            {
                "stat": "OK",
                "data": [
                    [
                        "115年07月09日",
                        "2492",
                        "華新科",
                        "474.00",
                        "471.49",
                        "2.503091",
                        "息",
                    ]
                ],
            }
        )
        tpex = parse_tpex_ex_dividend_history(
            {
                "stat": "ok",
                "tables": [
                    {
                        "data": [
                            [
                                "115/07/01",
                                "2230",
                                "泰茂",
                                "25.55",
                                "24.94",
                                "0",
                                "0.608951",
                                "0.608951",
                                "除息",
                                "27.40",
                                "22.45",
                                "24.95",
                                "24.94",
                                "0.60895126",
                                "100",
                            ]
                        ]
                    }
                ],
            }
        )

        self.assertEqual(twse[0]["start_date"], date(2026, 7, 9))
        self.assertEqual(twse[0]["timing_status"], "actual")
        self.assertEqual(twse[0]["cash_dividend"], 2.503091)
        self.assertEqual(tpex[0]["cash_dividend"], 0.60895126)
        self.assertEqual(tpex[0]["stock_dividend_ratio"], 0.1)


class TaiwanCorporateEventRefreshTests(unittest.TestCase):
    def tearDown(self) -> None:
        tw_corporate_events.invalidate_taiwan_corporate_event_cache()

    @staticmethod
    def _event(provider_key: str) -> dict:
        is_mops = provider_key.startswith("mops_conference")
        market = "TPEX" if provider_key.startswith("tpex_ex_dividend") else "TWSE"
        stock_id = "2330" if market == "TWSE" else "8069"
        event_type = "investor_conference" if is_mops else "ex_dividend"
        return {
            "event_id": f"{provider_key}-{stock_id}",
            "event_type": event_type,
            "timing_status": "actual" if provider_key.endswith("history") and not is_mops else "scheduled",
            "provider": "mops" if is_mops else f"{market.lower()}_openapi",
            "market": market,
            "source_name": "test",
            "source_url": "https://example.test",
            "stock_id": stock_id,
            "stock_name": "台積電" if market == "TWSE" else "元太",
            "start_date": date(2026, 7, 28),
            "end_date": date(2026, 7, 28),
            "start_time": "14:00" if is_mops else None,
            "title": "法人說明會" if is_mops else "除息",
            "summary": None,
            "location": None,
            "cash_dividend": 5.0 if not is_mops else None,
            "stock_dividend_ratio": None,
            "financial_report_related": False,
            "related_event_id": None,
            "company_url": None,
            "video_url": None,
        }

    def test_refresh_is_bounded_and_stock_summary_is_cache_only(self) -> None:
        calls: list[str] = []

        def fetcher(provider_key: str, **_kwargs):
            calls.append(provider_key)
            if provider_key == "mops_conference":
                return {
                    "entries": [self._event(provider_key)],
                    "request_count": 8,
                    "coverage_start": date(2026, 7, 1),
                    "coverage_end": date(2026, 8, 31),
                    "errors": [],
                }
            return [self._event(provider_key)]

        with _cache_path("bounded") as cache_path:
            with patch.object(tw_corporate_events, "ProcessFileLock", _TestProcessLock):
                refreshed = refresh_taiwan_corporate_events(
                    cache_path=cache_path,
                    now=datetime(2026, 7, 20, tzinfo=timezone.utc),
                    fetch_provider=fetcher,
                )
                summary = get_taiwan_stock_event_summary(
                    "2330",
                    market="TWSE",
                    reminder_days=14,
                    now=datetime(2026, 7, 20, tzinfo=timezone.utc),
                    cache_path=cache_path,
                )

        self.assertEqual(calls, ["twse_ex_dividend", "tpex_ex_dividend", "mops_conference"])
        self.assertEqual(refreshed["request_limit"], 10)
        self.assertEqual(refreshed["request_count"], 10)
        self.assertEqual(summary["result_count"], 2)
        self.assertEqual(summary["results"][0]["days_until"], 8)

    def test_failed_provider_keeps_last_successful_cache(self) -> None:
        def success_fetcher(provider_key: str, **_kwargs):
            if provider_key == "mops_conference":
                return {
                    "entries": [self._event(provider_key)],
                    "request_count": 8,
                    "coverage_start": date(2026, 7, 1),
                    "coverage_end": date(2026, 8, 31),
                    "errors": [],
                }
            return [self._event(provider_key)]

        def partial_fetcher(provider_key: str, **_kwargs):
            if provider_key == "mops_conference":
                raise RuntimeError("MOPS unavailable")
            return [self._event(provider_key)]

        with _cache_path("preserve") as cache_path:
            with patch.object(tw_corporate_events, "ProcessFileLock", _TestProcessLock):
                refresh_taiwan_corporate_events(
                    cache_path=cache_path,
                    now=datetime(2026, 7, 20, tzinfo=timezone.utc),
                    fetch_provider=success_fetcher,
                )
                refreshed = refresh_taiwan_corporate_events(
                    cache_path=cache_path,
                    now=datetime(2026, 7, 21, tzinfo=timezone.utc),
                    fetch_provider=partial_fetcher,
                )
                listing = list_taiwan_corporate_events(
                    stock_id="2330",
                    now=datetime(2026, 7, 21, tzinfo=timezone.utc),
                    cache_path=cache_path,
                )

        self.assertEqual(refreshed["error_count"], 1)
        self.assertEqual(listing["result_count"], 2)
        self.assertEqual(listing["sources"]["mops_conference"]["status"], "degraded")

    def test_manual_refresh_route_uses_transaction_owner(self) -> None:
        db = SimpleNamespace()
        expected = {"kind": "taiwan_corporate_event_refresh"}
        with patch.object(
            market_router,
            "refresh_taiwan_corporate_events",
            return_value=expected,
        ) as refresh:
            result = market_router.refresh_taiwan_corporate_event_calendar(db)

        self.assertIs(result, expected)
        refresh.assert_called_once_with(db=db)

    def test_history_backfill_is_bounded_and_calendar_defaults_to_today(self) -> None:
        def fetcher(provider_key: str, *, year: int, **_kwargs):
            event = self._event(provider_key)
            event_date = date(year, 6, 1)
            event["event_id"] = f"{provider_key}-{year}-{event['stock_id']}"
            event["start_date"] = event_date
            event["end_date"] = event_date
            return [event]

        with _cache_path("history") as cache_path:
            with patch.object(tw_corporate_events, "ProcessFileLock", _TestProcessLock):
                refreshed = backfill_taiwan_corporate_event_history(
                    years=2,
                    now=datetime(2026, 7, 20, tzinfo=timezone.utc),
                    cache_path=cache_path,
                    fetch_provider=fetcher,
                )
                history = get_taiwan_stock_event_history(
                    "2330",
                    market="TWSE",
                    years=2,
                    now=datetime(2026, 7, 20, tzinfo=timezone.utc),
                    cache_path=cache_path,
                )
                calendar = list_taiwan_corporate_events(
                    now=datetime(2026, 7, 20, tzinfo=timezone.utc),
                    cache_path=cache_path,
                )

        self.assertEqual(refreshed["request_limit"], 12)
        self.assertEqual(refreshed["request_count"], 12)
        self.assertEqual(history["total_count"], 4)
        self.assertTrue(all(event["status"] == "past" for event in history["results"]))
        self.assertEqual(calendar["date_from"], date(2026, 7, 20))
        self.assertEqual(calendar["result_count"], 0)
        self.assertEqual(set(calendar["sources"]), set(tw_corporate_events.CURRENT_PROVIDER_KEYS))

    def test_calendar_route_clamps_past_range_and_history_has_separate_route(self) -> None:
        expected_calendar = {"kind": "taiwan_corporate_events"}
        expected_history = {"stock_id": "2330"}
        with (
            patch.object(
                market_router,
                "list_taiwan_corporate_events",
                return_value=expected_calendar,
            ) as listing,
            patch.object(
                market_router,
                "get_taiwan_stock_event_history",
                return_value=expected_history,
            ) as history,
        ):
            calendar_result = market_router.get_taiwan_corporate_events(
                stock_id=None,
                market=None,
                event_types=None,
                date_from=date(2026, 7, 1),
                date_to=None,
                limit=500,
                now=datetime(2026, 7, 20, tzinfo=timezone.utc),
            )
            history_result = market_router.get_taiwan_corporate_event_history(
                "2330",
                market=None,
                years=5,
                limit=50,
                now=datetime(2026, 7, 20, tzinfo=timezone.utc),
            )

        self.assertIs(calendar_result, expected_calendar)
        self.assertEqual(listing.call_args.kwargs["date_from"], date(2026, 7, 20))
        self.assertIs(history_result, expected_history)
        history.assert_called_once_with(
            "2330",
            market=None,
            years=5,
            max_results=50,
            now=datetime(2026, 7, 20, tzinfo=timezone.utc),
        )

    def test_manual_history_backfill_route_uses_transaction_owner(self) -> None:
        db = SimpleNamespace()
        expected = {"kind": "taiwan_corporate_event_history_backfill"}
        with patch.object(
            market_router,
            "backfill_taiwan_corporate_event_history",
            return_value=expected,
        ) as backfill:
            result = market_router.backfill_taiwan_corporate_event_calendar_history(
                years=5,
                db=db,
            )

        self.assertIs(result, expected)
        backfill.assert_called_once_with(years=5, force=True, db=db)

    def test_scheduler_registers_immediate_daily_refresh(self) -> None:
        fake_scheduler = SimpleNamespace(add_job=Mock())
        with (
            patch.object(
                scheduler.settings,
                "enable_tw_corporate_event_scheduler",
                True,
            ),
            patch.object(
                scheduler.settings,
                "scheduler_tw_corporate_event_refresh_time",
                "07:25",
            ),
        ):
            added = scheduler._add_taiwan_corporate_event_refresh_job(fake_scheduler)

        self.assertTrue(added)
        kwargs = fake_scheduler.add_job.call_args.kwargs
        self.assertIs(
            fake_scheduler.add_job.call_args.args[0],
            scheduler.refresh_taiwan_corporate_event_calendar,
        )
        self.assertEqual(kwargs["trigger"], "cron")
        self.assertEqual(kwargs["hour"], 7)
        self.assertEqual(kwargs["minute"], 25)
        self.assertEqual(kwargs["id"], "taiwan_corporate_event_refresh")
        self.assertIsNotNone(kwargs["next_run_time"])

    def test_scheduler_registers_weekly_history_reconciliation(self) -> None:
        fake_scheduler = SimpleNamespace(add_job=Mock())
        with (
            patch.object(
                scheduler.settings,
                "enable_tw_corporate_event_scheduler",
                True,
            ),
            patch.object(
                scheduler.settings,
                "scheduler_tw_corporate_event_history_refresh_time",
                "07:35",
            ),
            patch.object(
                scheduler.settings,
                "scheduler_tw_corporate_event_history_refresh_day_of_week",
                "sun",
            ),
        ):
            added = scheduler._add_taiwan_corporate_event_history_refresh_job(
                fake_scheduler
            )

        self.assertTrue(added)
        kwargs = fake_scheduler.add_job.call_args.kwargs
        self.assertIs(
            fake_scheduler.add_job.call_args.args[0],
            scheduler.refresh_taiwan_corporate_event_history,
        )
        self.assertEqual(kwargs["day_of_week"], "sun")
        self.assertEqual(kwargs["hour"], 7)
        self.assertEqual(kwargs["minute"], 35)
        self.assertEqual(kwargs["id"], "taiwan_corporate_event_history_refresh")


if __name__ == "__main__":
    unittest.main()
