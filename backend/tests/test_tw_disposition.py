from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app.jobs import scheduler
from app.market import tw_disposition
from app.market.providers.tw_disposition import (
    parse_tpex_dispositions,
    parse_twse_dispositions,
)
from app.market.tw_disposition import (
    get_taiwan_disposition_status,
    list_taiwan_dispositions,
    refresh_taiwan_dispositions,
)
from app.routers import market as market_router


TEST_TMP_ROOT = Path(__file__).resolve().parents[2] / ".tmp" / "disposition-tests"
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
        tw_disposition.invalidate_taiwan_disposition_cache()
        path.unlink(missing_ok=True)


class TaiwanDispositionParserTests(unittest.TestCase):
    def test_twse_parser_reads_roc_period_and_chinese_interval(self) -> None:
        rows = parse_twse_dispositions(
            [
                {
                    "Date": "1150717",
                    "Code": "2330",
                    "Name": "台積電",
                    "DispositionPeriod": "115/07/20～115/07/31",
                    "ReasonsOfDisposition": "連續三次",
                    "DispositionMeasures": "第二次處置",
                    "Detail": "以人工管制撮合終端機執行撮合作業（約每二十分鐘撮合一次），並收取全部價金。",
                }
            ]
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["start_date"], date(2026, 7, 20))
        self.assertEqual(rows[0]["end_date"], date(2026, 7, 31))
        self.assertEqual(rows[0]["matching_interval_minutes"], 20)
        self.assertTrue(rows[0]["requires_full_precollection"])

    def test_tpex_parser_reads_compact_period_and_arabic_interval(self) -> None:
        rows = parse_tpex_dispositions(
            [
                {
                    "Date": "1150720",
                    "SecuritiesCompanyCode": "8383",
                    "CompanyName": "千附",
                    "DispositionPeriod": "1150720~1150731",
                    "DispositionReasons": "連續3個營業日達注意標準",
                    "DisposalCondition": "改以人工管制撮合終端機執行撮合作業(約每5分鐘撮合一次)，暫停融資融券交易。",
                }
            ]
        )

        self.assertEqual(rows[0]["market"], "TPEX")
        self.assertEqual(rows[0]["matching_interval_minutes"], 5)
        self.assertTrue(rows[0]["margin_trading_suspended"])

    def test_parser_rejects_schema_drift_and_wholly_malformed_rows(self) -> None:
        with self.assertRaises(ValueError):
            parse_twse_dispositions({"data": []})
        with self.assertRaises(ValueError):
            parse_tpex_dispositions([{"Date": "bad"}])


class TaiwanDispositionRefreshTests(unittest.TestCase):
    def tearDown(self) -> None:
        tw_disposition.invalidate_taiwan_disposition_cache()

    @staticmethod
    def _entry(provider_key: str) -> dict:
        is_twse = provider_key == "twse"
        return {
            "provider": "twse_openapi" if is_twse else "tpex_openapi",
            "market": "TWSE" if is_twse else "TPEX",
            "source_url": f"https://example.test/{provider_key}",
            "announced_date": date(2026, 7, 17),
            "stock_id": "2330" if is_twse else "8383",
            "stock_name": "台積電" if is_twse else "千附",
            "start_date": date(2026, 7, 20),
            "end_date": date(2026, 7, 31),
            "matching_interval_minutes": 20 if is_twse else 5,
            "reason": "test",
            "measure": "處置有價證券",
            "requires_full_precollection": True,
            "margin_trading_suspended": False,
            "detail": "test detail",
        }

    def test_refresh_is_two_requests_and_preserves_partial_success(self) -> None:
        calls: list[str] = []

        def fetcher(provider_key: str, **_kwargs):
            calls.append(provider_key)
            if provider_key == "tpex":
                raise RuntimeError("TPEx unavailable")
            return [self._entry(provider_key)]

        with _cache_path("partial") as cache_path:
            with patch.object(
                tw_disposition,
                "ProcessFileLock",
                _TestProcessLock,
            ):
                result = refresh_taiwan_dispositions(
                    cache_path=cache_path,
                    now=datetime(2026, 7, 20, tzinfo=timezone.utc),
                    fetch_provider=fetcher,
                )
                status = get_taiwan_disposition_status(
                    "2330",
                    market="TWSE",
                    now=datetime(2026, 7, 20, tzinfo=timezone.utc),
                    cache_path=cache_path,
                )

        self.assertEqual(calls, ["twse", "tpex"])
        self.assertEqual(result["request_limit"], 2)
        self.assertEqual(result["success_count"], 1)
        self.assertEqual(result["error_count"], 1)
        self.assertTrue(status["is_active"])
        self.assertEqual(status["matching_interval_minutes"], 20)

    def test_list_separates_active_and_upcoming_entries(self) -> None:
        def fetcher(provider_key: str, **_kwargs):
            entry = self._entry(provider_key)
            if provider_key == "tpex":
                entry["start_date"] = date(2026, 7, 21)
                entry["end_date"] = date(2026, 8, 3)
            return [entry]

        with _cache_path("list") as cache_path:
            with patch.object(
                tw_disposition,
                "ProcessFileLock",
                _TestProcessLock,
            ):
                refresh_taiwan_dispositions(
                    cache_path=cache_path,
                    now=datetime(2026, 7, 20, tzinfo=timezone.utc),
                    fetch_provider=fetcher,
                )
                result = list_taiwan_dispositions(
                    now=datetime(2026, 7, 20, tzinfo=timezone.utc),
                    cache_path=cache_path,
                )

        self.assertEqual(result["active_count"], 1)
        self.assertEqual(result["upcoming_count"], 1)
        self.assertEqual(result["result_count"], 2)

    def test_latest_overlapping_active_disposition_wins(self) -> None:
        first = self._entry("twse")
        first["start_date"] = date(2026, 7, 10)
        first["matching_interval_minutes"] = 5
        second = self._entry("twse")
        second["start_date"] = date(2026, 7, 20)
        second["matching_interval_minutes"] = 20

        def fetcher(provider_key: str, **_kwargs):
            return [first, second] if provider_key == "twse" else []

        with _cache_path("overlap") as cache_path:
            with patch.object(
                tw_disposition,
                "ProcessFileLock",
                _TestProcessLock,
            ):
                refresh_taiwan_dispositions(
                    cache_path=cache_path,
                    now=datetime(2026, 7, 20, tzinfo=timezone.utc),
                    fetch_provider=fetcher,
                )
                status = get_taiwan_disposition_status(
                    "2330",
                    market="TWSE",
                    now=datetime(2026, 7, 20, tzinfo=timezone.utc),
                    cache_path=cache_path,
                )
                listing = list_taiwan_dispositions(
                    now=datetime(2026, 7, 20, tzinfo=timezone.utc),
                    cache_path=cache_path,
                )

        self.assertEqual(status["matching_interval_minutes"], 20)
        self.assertEqual(listing["result_count"], 1)
        self.assertEqual(listing["results"][0]["matching_interval_minutes"], 20)

    def test_manual_refresh_route_uses_transaction_owner(self) -> None:
        db = SimpleNamespace()
        expected = {"kind": "taiwan_disposition_refresh"}
        with patch.object(
            market_router,
            "refresh_taiwan_dispositions",
            return_value=expected,
        ) as refresh:
            result = market_router.refresh_taiwan_disposition_securities(db)

        self.assertIs(result, expected)
        refresh.assert_called_once_with(db=db)

    def test_scheduler_registers_immediate_daily_refresh(self) -> None:
        fake_scheduler = SimpleNamespace(add_job=Mock())
        with (
            patch.object(scheduler.settings, "enable_tw_disposition_scheduler", True),
            patch.object(
                scheduler.settings,
                "scheduler_tw_disposition_refresh_time",
                "07:20",
            ),
        ):
            added = scheduler._add_taiwan_disposition_refresh_job(fake_scheduler)

        self.assertTrue(added)
        kwargs = fake_scheduler.add_job.call_args.kwargs
        self.assertIs(
            fake_scheduler.add_job.call_args.args[0],
            scheduler.refresh_taiwan_disposition_securities,
        )
        self.assertEqual(kwargs["trigger"], "cron")
        self.assertEqual(kwargs["hour"], 7)
        self.assertEqual(kwargs["minute"], 20)
        self.assertEqual(kwargs["id"], "taiwan_disposition_refresh")
        self.assertIsNotNone(kwargs["next_run_time"])


if __name__ == "__main__":
    unittest.main()
