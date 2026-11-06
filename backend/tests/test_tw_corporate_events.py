from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import pytest

from app.jobs import scheduler
from app.market import tw_corporate_events
from app.market.providers import tw_corporate_events as corporate_event_provider
from app.market.providers.tw_corporate_events import (
    MopsConferenceBatch,
    MopsConferenceWindowFailure,
    fetch_mops_conferences,
    classify_mops_conference_response,
    parse_mops_conferences,
    parse_tpex_ex_dividend_history,
    parse_tpex_ex_dividends,
    parse_twse_ex_dividend_history,
    parse_twse_ex_dividends,
)
from app.observability.provider_http import (
    ProviderHttpError,
    ProviderHttpFailure,
    ProviderRequestContext,
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


@pytest.mark.parametrize("new_start,new_end,expected_start,expected_end", [
    ("2026-08-10", "2026-08-15", "2026-08-01", "2026-08-31"),
    ("2026-08-20", "2026-09-05", "2026-08-01", "2026-09-05"),
    ("2026-07-20", "2026-08-05", "2026-07-20", "2026-08-31"),
    ("2026-09-01", "2026-09-05", "2026-08-01", "2026-09-05"),
    ("2026-07-20", "2026-07-31", "2026-07-20", "2026-08-31"),
    ("2026-09-02", "2026-09-05", "2026-08-01", "2026-08-31"),
    ("2026-07-20", "2026-07-30", "2026-08-01", "2026-08-31"),
    (None, None, "2026-08-01", "2026-08-31"),
    ("malformed", "2026-09-05", "2026-08-01", "2026-08-31"),
    ("2026-09-05", "2026-09-01", "2026-08-01", "2026-08-31"),
])
def test_entry_merge_retains_only_contiguous_proven_coverage(
    tmp_path, new_start, new_end, expected_start, expected_end,
):
    path = tmp_path / "events.json"
    key = "twse_ex_dividend_history"
    now = datetime(2026, 9, 6, tzinfo=timezone.utc)
    try:
        tw_corporate_events._write_refresh(updates={key: {"entries": [],
            "coverage_start": "2026-08-01", "coverage_end": "2026-08-31", "coverage_years": [2026]}},
            errors={}, attempted_at=now, path=path)
        result = tw_corporate_events._write_refresh(updates={key: {"merge_entries": True,
            "entries": [], "coverage_start": new_start, "coverage_end": new_end}},
            errors={}, attempted_at=now, path=path)
        stored = result["providers"][key]
        assert (stored["coverage_start"], stored["coverage_end"]) == (expected_start, expected_end)
        assert stored["coverage_years"] == [2026]
        if (new_start, new_end) in {("2026-09-02", "2026-09-05"), ("2026-07-20", "2026-07-30")}:
            from app.market.technical_evidence import build_corporate_action_contract
            from app.market_data.contracts import InstrumentKey
            assert stored["coverage_merge_reason"] == "DISCONTIGUOUS_COVERAGE_RETAINED"
            contract = build_corporate_action_contract(
                {**stored, "cache_status": "current", "results": []},
                analysis_start=date(2026, 7, 20), analysis_end=date(2026, 9, 5))
            assert contract["coverage_status"] == "partial"
            evidence = tw_corporate_events.read_taiwan_instrument_event_evidence(
                instrument=InstrumentKey(market="TW", venue="TWSE", symbol="1102", instrument_type="stock"),
                available_at=now, path=path)
            basis = tw_corporate_events.resolve_taiwan_price_basis(
                evidence, prior_date=date(2026, 8, 31), trade_date=date(2026, 9, 2))
            assert basis.status == "unknown"
    finally:
        tw_corporate_events.invalidate_taiwan_corporate_event_cache()


def test_entry_merge_cannot_clear_failed_years_or_rejuvenate_retained_coverage(tmp_path):
    path = tmp_path / "events.json"
    key = "twse_ex_dividend_history"
    earlier = datetime(2026, 10, 1, tzinfo=timezone.utc)
    now = datetime(2026, 11, 2, tzinfo=timezone.utc)
    try:
        for failed in (False, True):
            update = {"entries": [], "coverage_start": "2022-01-01", "coverage_end": "2026-10-30",
                "coverage_years": [2022, 2024, 2025, 2026] if failed else list(range(2022, 2027)),
                "failed_years": [2023] if failed else [], "partial_success": failed,
                "successful_windows": ["TWSE:2026"]}
            details = [{"market": "TWSE", "window": "2023", "message": "fixture timeout"}] if failed else []
            tw_corporate_events._write_refresh(updates={key: update},
                errors={key: "2023 failed"} if failed else {},
                error_details={key: details}, attempted_at=earlier, path=path)
            before = tw_corporate_events.taiwan_corporate_event_semantic_revision(cache_path=path, available_at=now)
            written = tw_corporate_events._write_refresh(updates={key: {"merge_entries": True,
                "entries": [], "coverage_start": "2026-10-19", "coverage_end": "2026-10-29"}},
                errors={}, attempted_at=now, path=path)["providers"][key]
            assert written["coverage_years"] == update["coverage_years"]
            assert written["failed_years"] == update["failed_years"]
            assert written["partial_success"] is failed
            assert written["successful_windows"] == update["successful_windows"]
            assert written["last_failure_details"] == details
            assert written["fetched_at"] == now.isoformat()
            assert written["coverage_fetched_at"] == earlier.isoformat()
            status = tw_corporate_events._provider_cache_status(written, now=now, archive=True)
            assert status["status"] == ("degraded" if failed else "stale")
            assert tw_corporate_events.taiwan_corporate_event_semantic_revision(
                cache_path=path, available_at=now) == before
            retained_cache = {"providers": {name: written for name in tw_corporate_events.HISTORY_PROVIDER_KEYS}}
            assert not tw_corporate_events._history_refresh_is_recent(
                retained_cache, now=now, target_end=date(2026, 10, 30))
        # An explicit complete refresh still replaces coverage/entries and clears old qualification.
        replaced = tw_corporate_events._write_refresh(updates={key: {"entries": [],
            "coverage_start": "2026-10-01", "coverage_end": "2026-11-02", "coverage_years": [2026]}},
            errors={}, attempted_at=now, path=path)["providers"][key]
        assert replaced["coverage_start"] == "2026-10-01"
        assert replaced["failed_years"] == [] and replaced["last_error"] is None
        assert "coverage_fetched_at" not in replaced
        assert tw_corporate_events._provider_cache_status(replaced, now=now, archive=True)["status"] == "current"
    finally:
        tw_corporate_events.invalidate_taiwan_corporate_event_cache()


def test_entry_merge_does_not_infer_coverage_from_old_positive_events_or_years(tmp_path):
    path = tmp_path / "events.json"
    key = "twse_ex_dividend_history"
    now = datetime(2026, 11, 2, tzinfo=timezone.utc)
    try:
        tw_corporate_events._write_refresh(updates={key: {"entries": [
            {"event_id": "old", "start_date": "2022-01-01"}], "coverage_years": [2022, 2026]}},
            errors={}, attempted_at=now, path=path)
        stored = tw_corporate_events._write_refresh(updates={key: {"merge_entries": True,
            "entries": [], "coverage_start": "2026-10-19", "coverage_end": "2026-10-29"}},
            errors={}, attempted_at=now, path=path)["providers"][key]
        assert (stored["coverage_start"], stored["coverage_end"]) == ("2026-10-19", "2026-10-29")
        assert stored["coverage_years"] == []
        assert stored["entries"][0]["event_id"] == "old"
    finally:
        tw_corporate_events.invalidate_taiwan_corporate_event_cache()


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

    def test_mops_response_classifier_distinguishes_provider_pages(self) -> None:
        self.assertEqual(
            classify_mops_conference_response(MOPS_HTML),
            "valid_data",
        )
        self.assertEqual(
            classify_mops_conference_response(
                '<table id="myTable"><tr><td>查無資料</td></tr></table>'
            ),
            "valid_empty",
        )
        self.assertEqual(
            classify_mops_conference_response("<html><body>系統維護中</body></html>"),
            "maintenance_page",
        )
        self.assertEqual(
            classify_mops_conference_response(
                "<html><body>Access Denied - CAPTCHA</body></html>"
            ),
            "anti_bot_or_invalid_response",
        )
        self.assertEqual(
            classify_mops_conference_response(
                "<table><tr><th>完全不同欄位</th></tr><tr><td>x</td></tr></table>"
            ),
            "html_schema_changed",
        )

    def test_mops_parser_supports_header_validated_renamed_table(self) -> None:
        html = """
        <table id="conference-result-v2">
          <tr><th>公司代碼</th><th>公司名稱</th><th>召開日期</th><th>召開時間</th>
              <th>召開地點</th><th>活動內容</th><th>公司網站</th><th>影音連結</th></tr>
          <tr><td>2330</td><td>台積電</td><td>115/07/16</td><td>14:00</td>
              <td>線上</td><td>說明營運概況</td>
              <td><a href="https://investor.example/2330">網站</a></td>
              <td><a href="https://video.example/2330">影音</a></td></tr>
        </table>
        """

        self.assertEqual(
            classify_mops_conference_response(html),
            "html_schema_changed",
        )
        rows = parse_mops_conferences(html, market="TWSE")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["stock_id"], "2330")
        self.assertEqual(rows[0]["company_url"], "https://investor.example/2330")

    def test_mops_window_retries_transport_failure_and_reports_recovery(self) -> None:
        context = ProviderRequestContext(
            market="tw",
            provider="mops",
            resource="tw_corporate_events",
            target="TWSE:2026-07:result",
        )
        failure = ProviderHttpFailure(
            context=context,
            status="error",
            source_url="https://example.test/signed-result",
            error_message="MOPS signed result connection failed.",
            exception_type="ConnectionError",
        )
        transport_error = ProviderHttpError(
            failure.error_message or "MOPS request failed.",
            failure=failure,
        )
        rows = parse_mops_conferences(MOPS_HTML, market="TWSE")

        with patch.object(
            corporate_event_provider,
            "_fetch_mops_conference_window",
            side_effect=[transport_error, rows, rows, rows, rows],
        ):
            batch = fetch_mops_conferences(
                as_of=date(2026, 7, 20),
                month_count=2,
                timeout_seconds=20,
                max_attempts=2,
            )

        self.assertEqual(batch.errors, [])
        self.assertEqual(batch.request_count, 10)
        self.assertEqual(batch.retry_count, 1)
        self.assertEqual(batch.recovered_windows, ["TWSE:2026-07"])
        self.assertEqual(
            batch.successful_windows,
            ["TWSE:2026-07", "TWSE:2026-08", "TPEX:2026-07", "TPEX:2026-08"],
        )

    def test_mops_window_exhaustion_identifies_market_window_and_stage(self) -> None:
        rows = parse_mops_conferences(MOPS_HTML, market="TWSE")

        def fetch_window(**kwargs):
            if kwargs["market"] == "TPEX" and kwargs["month"] == 7:
                context = ProviderRequestContext(
                    market="tw",
                    provider="mops",
                    resource="tw_corporate_events",
                    target="TPEX:2026-07:result",
                )
                failure = ProviderHttpFailure(
                    context=context,
                    status="error",
                    source_url="https://example.test/signed-result",
                    error_message="MOPS signed result connection failed.",
                    exception_type="ConnectionError",
                )
                raise ProviderHttpError(
                    failure.error_message or "MOPS request failed.",
                    failure=failure,
                )
            return rows

        with patch.object(
            corporate_event_provider,
            "_fetch_mops_conference_window",
            side_effect=fetch_window,
        ):
            batch = fetch_mops_conferences(
                as_of=date(2026, 7, 20),
                month_count=2,
                timeout_seconds=20,
                max_attempts=2,
            )

        self.assertEqual(batch.request_count, 10)
        self.assertEqual(batch.retry_count, 1)
        self.assertEqual(len(batch.failures), 1)
        self.assertEqual(batch.failures[0].market, "TPEX")
        self.assertEqual(batch.failures[0].window, "2026-07")
        self.assertEqual(batch.failures[0].stage, "result")
        self.assertEqual(batch.failures[0].exception_type, "ConnectionError")
        self.assertEqual(batch.failures[0].attempt_count, 2)
        self.assertIn("MOPS/TPEX/2026-07/result", batch.errors[0])

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
        self.assertEqual(refreshed["request_limit"], 18)
        self.assertEqual(refreshed["request_count"], 10)
        self.assertEqual(summary["result_count"], 2)
        self.assertEqual(summary["results"][0]["days_until"], 8)

    def test_stock_summary_defaults_to_seven_day_reminder_window(self) -> None:
        within_window = {
            **self._event("twse_ex_dividend"),
            "start_date": date(2026, 7, 27),
            "end_date": date(2026, 7, 27),
        }
        outside_window = self._event("mops_conference")

        def fetcher(provider_key: str, **_kwargs):
            if provider_key == "twse_ex_dividend":
                return [within_window]
            if provider_key == "mops_conference":
                return {
                    "entries": [outside_window],
                    "request_count": 8,
                    "coverage_start": date(2026, 7, 1),
                    "coverage_end": date(2026, 8, 31),
                    "errors": [],
                }
            return [self._event(provider_key)]

        with _cache_path("seven-day-reminder") as cache_path:
            with patch.object(tw_corporate_events, "ProcessFileLock", _TestProcessLock):
                refresh_taiwan_corporate_events(
                    cache_path=cache_path,
                    now=datetime(2026, 7, 20, tzinfo=timezone.utc),
                    fetch_provider=fetcher,
                )
                summary = get_taiwan_stock_event_summary(
                    "2330",
                    market="TWSE",
                    now=datetime(2026, 7, 20, tzinfo=timezone.utc),
                    cache_path=cache_path,
                )

        self.assertEqual(summary["reminder_days"], 7)
        self.assertEqual(summary["result_count"], 1)
        self.assertEqual(summary["results"][0]["event_type"], "ex_dividend")
        self.assertEqual(summary["results"][0]["days_until"], 7)

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

    def test_listing_applies_plural_filters_before_offset_pagination(self) -> None:
        with _cache_path("plural-filter-pagination") as cache_path:
            first = self._event("twse_ex_dividend")
            first["event_id"] = "twse-2330-first"
            first["stock_id"] = "2330"
            first["start_date"] = date(2026, 7, 25)
            first["end_date"] = date(2026, 7, 25)
            second = {**first}
            second["event_id"] = "twse-2330-second"
            second["start_date"] = date(2026, 7, 26)
            second["end_date"] = date(2026, 7, 26)
            excluded_stock = {**first}
            excluded_stock["event_id"] = "twse-2317"
            excluded_stock["stock_id"] = "2317"
            excluded_stock["start_date"] = date(2026, 7, 27)
            excluded_stock["end_date"] = date(2026, 7, 27)

            tw_corporate_events._atomic_write(
                cache_path,
                {
                    "schema_version": tw_corporate_events.CACHE_SCHEMA_VERSION,
                    "updated_at": datetime(
                        2026, 7, 20, tzinfo=timezone.utc
                    ).isoformat(),
                    "providers": {
                        "twse_ex_dividend": {
                            "fetched_at": datetime(
                                2026, 7, 20, tzinfo=timezone.utc
                            ).isoformat(),
                            "entries": [
                                tw_corporate_events._json_entry(first),
                                tw_corporate_events._json_entry(excluded_stock),
                                tw_corporate_events._json_entry(second),
                            ],
                        }
                    }
                },
            )
            tw_corporate_events.invalidate_taiwan_corporate_event_cache()
            listing = list_taiwan_corporate_events(
                stock_ids={"2330"},
                markets={"TWSE"},
                date_from=date(2026, 7, 20),
                date_to=date(2026, 7, 31),
                offset=1,
                limit=1,
                now=datetime(2026, 7, 20, tzinfo=timezone.utc),
                cache_path=cache_path,
            )

        self.assertEqual(listing["total_count"], 2)
        self.assertEqual(listing["result_count"], 1)
        self.assertEqual(listing["results"][0]["event_id"], "twse-2330-second")
        self.assertEqual(listing["offset"], 1)
        self.assertEqual(listing["limit"], 1)

    def test_partial_mops_refresh_updates_successes_and_preserves_failed_window(self) -> None:
        old_twse = self._event("mops_conference")
        old_twse["event_id"] = "mops-old-twse"
        old_twse["market"] = "TWSE"
        old_twse["stock_id"] = "2330"
        old_twse["start_date"] = date(2026, 7, 28)
        old_twse["end_date"] = date(2026, 7, 28)
        old_tpex = {**old_twse}
        old_tpex["event_id"] = "mops-old-tpex"
        old_tpex["market"] = "TPEX"
        old_tpex["stock_id"] = "8069"
        old_tpex["start_date"] = date(2026, 7, 29)
        old_tpex["end_date"] = date(2026, 7, 29)
        new_twse = {**old_twse}
        new_twse["event_id"] = "mops-new-twse"

        failure = MopsConferenceWindowFailure(
            provider="mops",
            market="TPEX",
            window="2026-07",
            stage="result",
            status="error",
            exception_type="ConnectionError",
            attempt_count=2,
            retryable=True,
            message="MOPS signed result connection failed.",
        )

        def initial_fetcher(provider_key: str, **_kwargs):
            if provider_key == "mops_conference":
                return MopsConferenceBatch(
                    entries=[old_twse, old_tpex],
                    request_count=8,
                    errors=[],
                    coverage_start=date(2026, 7, 1),
                    coverage_end=date(2026, 8, 31),
                    successful_windows=[
                        "TWSE:2026-07",
                        "TWSE:2026-08",
                        "TPEX:2026-07",
                        "TPEX:2026-08",
                    ],
                )
            return [self._event(provider_key)]

        def partial_fetcher(provider_key: str, **_kwargs):
            if provider_key == "mops_conference":
                return MopsConferenceBatch(
                    entries=[new_twse],
                    request_count=10,
                    errors=[failure.summary()],
                    coverage_start=date(2026, 7, 1),
                    coverage_end=date(2026, 8, 31),
                    failures=[failure],
                    successful_windows=[
                        "TWSE:2026-07",
                        "TWSE:2026-08",
                        "TPEX:2026-08",
                    ],
                    retry_count=1,
                )
            return [self._event(provider_key)]

        with _cache_path("partial-window") as cache_path:
            with patch.object(tw_corporate_events, "ProcessFileLock", _TestProcessLock):
                refresh_taiwan_corporate_events(
                    cache_path=cache_path,
                    now=datetime(2026, 7, 20, tzinfo=timezone.utc),
                    fetch_provider=initial_fetcher,
                )
                with patch.object(
                    tw_corporate_events,
                    "record_provider_event",
                ) as record_event:
                    refreshed = refresh_taiwan_corporate_events(
                        cache_path=cache_path,
                        now=datetime(2026, 7, 21, tzinfo=timezone.utc),
                        fetch_provider=partial_fetcher,
                        db=SimpleNamespace(rollback=Mock()),
                    )
                cache = tw_corporate_events.read_taiwan_corporate_event_cache(
                    path=cache_path
                )
                listing = list_taiwan_corporate_events(
                    now=datetime(2026, 7, 21, tzinfo=timezone.utc),
                    cache_path=cache_path,
                )
                twse_summary = get_taiwan_stock_event_summary(
                    "2330",
                    market="TWSE",
                    reminder_days=7,
                    now=datetime(2026, 7, 21, tzinfo=timezone.utc),
                    cache_path=cache_path,
                )
                failed_tpex_listing = list_taiwan_corporate_events(
                    market="TPEX",
                    date_from=date(2026, 7, 21),
                    date_to=date(2026, 7, 31),
                    now=datetime(2026, 7, 21, tzinfo=timezone.utc),
                    cache_path=cache_path,
                )
                successful_tpex_listing = list_taiwan_corporate_events(
                    market="TPEX",
                    date_from=date(2026, 8, 1),
                    date_to=date(2026, 8, 31),
                    now=datetime(2026, 7, 21, tzinfo=timezone.utc),
                    cache_path=cache_path,
                )

        mops_entries = cache["providers"]["mops_conference"]["entries"]
        self.assertEqual(
            {entry["event_id"] for entry in mops_entries},
            {"mops-new-twse", "mops-old-tpex"},
        )
        self.assertEqual(refreshed["results"]["mops_conference"]["status"], "partial")
        self.assertEqual(refreshed["partial_count"], 1)
        self.assertEqual(refreshed["error_count"], 1)
        source = listing["sources"]["mops_conference"]
        self.assertEqual(source["status"], "degraded")
        self.assertTrue(source["partial_success"])
        self.assertEqual(source["last_failure_details"][0]["market"], "TPEX")
        self.assertEqual(source["last_failure_details"][0]["stage"], "result")
        self.assertIn("MOPS/TPEX/2026-07/result", source["warning"])
        self.assertEqual(twse_summary["cache_status"], "current")
        self.assertIsNone(twse_summary["warning"])
        self.assertEqual(
            failed_tpex_listing["sources"]["mops_conference"]["status"],
            "degraded",
        )
        scoped_source = successful_tpex_listing["sources"]["mops_conference"]
        self.assertEqual(scoped_source["status"], "current")
        self.assertIsNone(scoped_source["last_error"])
        self.assertEqual(scoped_source["last_failure_details"], [])
        self.assertFalse(scoped_source["partial_success"])
        self.assertIsNone(successful_tpex_listing["warning"])
        mops_event = next(
            call
            for call in record_event.call_args_list
            if call.kwargs["provider"] == "mops"
        )
        self.assertEqual(mops_event.kwargs["status"], "partial_success")
        self.assertEqual(mops_event.kwargs["detail"]["failures"][0]["market"], "TPEX")

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

        self.assertEqual(refreshed["request_limit"], 20)
        self.assertEqual(refreshed["request_count"], 12)
        self.assertEqual(history["total_count"], 4)
        self.assertEqual(history["returned_count"], 4)
        self.assertEqual(history["sort_order"], "desc")
        self.assertEqual(
            [event["start_date"] for event in history["results"]],
            sorted(
                [event["start_date"] for event in history["results"]],
                reverse=True,
            ),
        )
        self.assertTrue(all(event["status"] == "past" for event in history["results"]))
        self.assertEqual(calendar["date_from"], date(2026, 7, 20))
        self.assertEqual(calendar["result_count"], 0)
        self.assertEqual(set(calendar["sources"]), set(tw_corporate_events.CURRENT_PROVIDER_KEYS))

    def test_recent_history_cache_does_not_skip_incomplete_latest_session(
        self,
    ) -> None:
        now = datetime(2026, 9, 6, 2, 0, tzinfo=timezone.utc)
        fetched_at = datetime(2026, 9, 2, 2, 0, tzinfo=timezone.utc)
        calls: list[tuple[str, int, date]] = []

        def fetcher(provider_key: str, *, year: int, date_to: date, **_kwargs):
            calls.append((provider_key, year, date_to))
            return []

        with _cache_path("history-lagged-latest-session") as cache_path:
            tw_corporate_events._atomic_write(
                cache_path,
                {
                    "schema_version": tw_corporate_events.CACHE_SCHEMA_VERSION,
                    "updated_at": fetched_at.isoformat(),
                    "providers": {
                        key: {
                            "fetched_at": fetched_at.isoformat(),
                            "coverage_start": "2022-01-01",
                            "coverage_end": "2026-09-03",
                            "coverage_years": [2022, 2023, 2024, 2025, 2026],
                            "coverage_contract": tw_corporate_events.HISTORY_COVERAGE_CONTRACT,
                            "entries": [],
                        }
                        for key in tw_corporate_events.HISTORY_PROVIDER_KEYS
                    },
                },
            )
            tw_corporate_events.invalidate_taiwan_corporate_event_cache()
            with patch.object(
                tw_corporate_events,
                "ProcessFileLock",
                _TestProcessLock,
            ):
                result = backfill_taiwan_corporate_event_history(
                    years=5,
                    force=False,
                    now=now,
                    cache_path=cache_path,
                    fetch_provider=fetcher,
                )

        self.assertEqual(len(calls), len(tw_corporate_events.HISTORY_PROVIDER_KEYS))
        self.assertTrue(all(year == 2026 for _, year, _ in calls))
        self.assertTrue(all(date_to == date(2026, 9, 4) for _, _, date_to in calls))
        self.assertGreater(result["request_count"], 0)

    def test_history_uses_completed_session_and_never_forecast_coverage(self) -> None:
        import json
        with _cache_path("history-completed-session-cutoff") as cache_path:
            actual = self._event("twse_ex_dividend_history")
            actual.update(start_date="2026-10-29", end_date="2026-10-29")
            forecast = self._event("twse_ex_dividend")
            forecast.update(start_date="2026-10-29", end_date="2026-10-29")
            providers = {
                key: {"fetched_at": "2026-10-29T00:00:00+00:00", "coverage_start": "2022-01-01",
                    "coverage_end": "2026-10-29", "entries": [actual] if key == "twse_ex_dividend_history" else []}
                for key in tw_corporate_events.HISTORY_PROVIDER_KEYS
            }
            providers["twse_ex_dividend"] = {"fetched_at": "2026-10-29T00:00:00+00:00",
                "coverage_start": "2026-01-01", "coverage_end": "2026-12-31", "entries": [forecast]}
            cache_path.write_text(json.dumps({"schema_version": 1, "providers": providers}), encoding="utf-8")
            preimage = cache_path.read_bytes()
            for hour, expected_ids in [(4, []), (6, [actual["event_id"]])]:
                with self.subTest(utc_hour=hour):
                    history = get_taiwan_stock_event_history("2330", market="TWSE",
                        now=datetime(2026, 10, 29, hour, tzinfo=timezone.utc), cache_path=cache_path)
                    self.assertEqual([row["event_id"] for row in history["results"]], expected_ids)
                    self.assertEqual(history["coverage_end"], date(2026, 10, 29))
            self.assertEqual(cache_path.read_bytes(), preimage)

    def test_history_cutoff_keeps_prior_year_at_new_year_preopen(self) -> None:
        with patch.object(tw_corporate_events, "list_taiwan_corporate_events", return_value={
            "results": [], "sources": {}, "warning": None, "total_count": 0,
        }) as listing:
            get_taiwan_stock_event_history("2330", years=1, now=datetime(2027, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(listing.call_args.kwargs["date_to"], date(2026, 12, 31))
        self.assertEqual(listing.call_args.kwargs["date_from"], date(2026, 1, 1))
        self.assertIs(listing.call_args.kwargs["history_only"], True)

    def test_history_delta_keeps_unpublished_provider_partial_and_old_years(self) -> None:
        import json
        calls = []
        with _cache_path("history-authority-unpublished") as cache_path:
            historical = self._event("twse_ex_dividend_history")
            historical.update(start_date="2025-07-28", end_date="2025-07-28")
            cache_path.write_text(json.dumps({"schema_version": 1, "providers": {
                key: {"fetched_at": "2026-10-28T09:19:56+00:00", "coverage_start": "2022-01-01",
                    "coverage_end": "2026-10-28", "coverage_years": [2022, 2023, 2024, 2025, 2026],
                    "entries": [historical] if key == "twse_ex_dividend_history" else []}
                for key in tw_corporate_events.HISTORY_PROVIDER_KEYS
            }}), encoding="utf-8")

            def fetch(provider_key, *, year, date_to, **kwargs):
                calls.append((provider_key, year, date_to))
                if provider_key == "tpex_ex_dividend_history":
                    raise ValueError("Official completed-session publication unavailable")
                return []  # Qualified successful empty result, not a failed response.

            with patch.object(tw_corporate_events, "ProcessFileLock", _TestProcessLock):
                result = backfill_taiwan_corporate_event_history(years=1, force=False,
                    now=datetime(2026, 10, 30, tzinfo=timezone.utc), cache_path=cache_path, fetch_provider=fetch)
            providers = tw_corporate_events.read_taiwan_corporate_event_cache(path=cache_path)["providers"]
            self.assertEqual(len(calls), 3)
            self.assertTrue(all(year == 2026 and end == date(2026, 10, 29) for _, year, end in calls))
            self.assertEqual(providers["twse_ex_dividend_history"]["coverage_end"], "2026-10-29")
            self.assertEqual(providers["twse_ex_dividend_history"]["entries"][0]["start_date"], "2025-07-28")
            self.assertEqual(providers["tpex_ex_dividend_history"]["coverage_end"], "2026-10-28")
            self.assertEqual(result["results"]["tpex_ex_dividend_history"]["status"], "error")

    def test_history_scheduler_defaults_to_weekday_completed_session_reconciliation(self) -> None:
        from app.config import Settings
        fake_scheduler = SimpleNamespace(add_job=Mock())
        with patch.object(scheduler.settings, "enable_tw_corporate_event_scheduler", True), \
                patch.object(scheduler.settings, "scheduler_tw_corporate_event_history_refresh_time",
                    Settings.model_fields["scheduler_tw_corporate_event_history_refresh_time"].default), \
                patch.object(scheduler.settings, "scheduler_tw_corporate_event_history_refresh_day_of_week",
                    Settings.model_fields["scheduler_tw_corporate_event_history_refresh_day_of_week"].default):
            self.assertTrue(scheduler._add_taiwan_corporate_event_history_refresh_job(fake_scheduler))
        kwargs = fake_scheduler.add_job.call_args.kwargs
        clocks=kwargs["trigger"].triggers
        self.assertTrue(all(str(t.fields[4])=="mon-fri" for t in clocks))
        self.assertEqual([(str(t.fields[5]),str(t.fields[6])) for t in clocks], [("14","35"),("15","20"),("16","35")])
        self.assertEqual(kwargs["max_instances"], 1)

    def test_history_limit_returns_latest_events_after_descending_sort(self) -> None:
        with _cache_path("history-latest-first") as cache_path:
            events = []
            for event_date in (
                date(2025, 9, 1),
                date(2026, 1, 15),
                date(2026, 6, 30),
            ):
                event = self._event("twse_ex_dividend_history")
                event["event_id"] = f"twse-history-{event_date.isoformat()}"
                event["stock_id"] = "2330"
                event["start_date"] = event_date
                event["end_date"] = event_date
                events.append(tw_corporate_events._json_entry(event))
            tw_corporate_events._atomic_write(
                cache_path,
                {
                    "schema_version": tw_corporate_events.CACHE_SCHEMA_VERSION,
                    "updated_at": datetime(2026, 7, 20, tzinfo=timezone.utc).isoformat(),
                    "providers": {
                        "twse_ex_dividend_history": {
                            "fetched_at": datetime(
                                2026, 7, 20, tzinfo=timezone.utc
                            ).isoformat(),
                            "entries": events,
                        }
                    },
                },
            )
            tw_corporate_events.invalidate_taiwan_corporate_event_cache()

            history = get_taiwan_stock_event_history(
                "2330",
                market="TWSE",
                years=2,
                max_results=2,
                now=datetime(2026, 7, 20, tzinfo=timezone.utc),
                cache_path=cache_path,
            )

        self.assertEqual(history["total_count"], 3)
        self.assertEqual(history["returned_count"], 2)
        self.assertEqual(history["result_count"], 2)
        self.assertEqual(history["limit"], 2)
        self.assertEqual(history["sort_order"], "desc")
        self.assertEqual(
            [event["start_date"] for event in history["results"]],
            [date(2026, 6, 30), date(2026, 1, 15)],
        )

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
        configured=kwargs["trigger"].triggers[0]
        self.assertEqual(str(configured.fields[4]), "sun")
        self.assertEqual(str(configured.fields[5]), "7")
        self.assertEqual(str(configured.fields[6]), "35")
        self.assertEqual(kwargs["id"], "taiwan_corporate_event_history_refresh")


if __name__ == "__main__":
    unittest.main()
