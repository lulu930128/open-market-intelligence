"""11/03 official receipt replay and Cron/backoff regression; isolated IO only."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from unittest.mock import Mock, patch

import pytest
from apscheduler.schedulers.background import BackgroundScheduler

from app.db.models import MarketDailyPrice, RawFetchResult, StockMaster
from app.jobs import scheduler
from app.market.daily_ohlcv_acquisition import TaiwanOfficialDailyAcquisitionExecutor
from app.market.daily_ohlcv_platform import refresh_taiwan_official_daily_venue, qualify_taiwan_eod_universe
from app.market.providers.tw_official_daily import parse_tpex_official_daily_payload
from app.market_data import eod_coverage as owner
from test_tw_official_daily_platform import db, FakeResponse, FIXTURE_ROOT  # noqa: F401


DAY = date(2026, 11, 3)
END = datetime(2026, 11, 3, 8, 20, 53, tzinfo=timezone.utc)
DUE = END + timedelta(seconds=900)


@pytest.mark.parametrize("receipt_index,volume", [(0, 23661000), (1, 24256298)])
def test_actual_1103_tpex_receipt_date_ohlcv_and_canonical_lineage(db, receipt_index, volume):
    receipt = json.loads((FIXTURE_ROOT / "tpex_eod_excerpt_20261103.json").read_text(
        encoding="utf-8"))["receipts"][receipt_index]
    raw = json.dumps(receipt["payload"], ensure_ascii=False)
    record = parse_tpex_official_daily_payload(raw).records[0]
    assert (record.symbol, record.trade_date) == ("6182", DAY)
    assert (record.open_price, record.high_price, record.low_price, record.close_price) == (
        Decimal("91.50"), Decimal("91.70"), Decimal("84.70"), Decimal("85.30"))
    assert record.trade_volume == volume
    db.add(StockMaster(stock_id="6182", market="TPEX", instrument_type="stock"))
    db.commit()
    acquired_at = datetime.fromisoformat(receipt["received_at"])
    result = refresh_taiwan_official_daily_venue(
        db, venue="TPEX", trade_date=DAY, requested_at=acquired_at, refresh_published=False,
        acquisition=TaiwanOfficialDailyAcquisitionExecutor(
            fetchers={receipt["resource"]: lambda _: FakeResponse(text=raw, url=receipt["url"])},
            clock=lambda: acquired_at),
        route_state=({"version": 1, "venue": "TPEX", "trade_date": DAY.isoformat(),
                      "attempted_resources": ["tpex_mainboard_quotes"]} if receipt_index else {}),
    )
    assert result["inserted_count"] == 1 and result["external_call_count"] == 1
    bar = db.query(MarketDailyPrice).one()
    stored_receipt = db.get(RawFetchResult, bar.raw_result_id)
    assert (bar.stock_id, bar.trade_date, bar.close_price, bar.trade_volume) == ("6182", DAY, 85.3, volume)
    assert stored_receipt.source_id == bar.source_id and stored_receipt.url == receipt["url"]
    coverage = owner.compute_eod_coverage(db, market="TW", expected_trade_date=DAY,
                                        taiwan_daily_qualifier=qualify_taiwan_eod_universe)
    assert coverage.current_symbols == {"6182"}
    # The same received payload cannot be currentized for another date.
    next_day = refresh_taiwan_official_daily_venue(
        db, venue="TPEX", trade_date=date(2026, 11, 4), requested_at=acquired_at + timedelta(days=1),
        refresh_published=False, max_external_calls=1,
        acquisition=TaiwanOfficialDailyAcquisitionExecutor(
            fetchers={"tpex_mainboard_quotes": lambda _: FakeResponse(text=raw)},
            clock=lambda: acquired_at + timedelta(days=1)),
    )
    assert next_day["parsed_count"] == 0 and db.query(MarketDailyPrice).count() == 1
    assert "EXPECTED_TRADE_DATE_NOT_OBSERVED" in next_day["limitations"]


@pytest.mark.parametrize("retry_at,next_cron,expected_wakeup", [
    (DUE, END.replace(minute=50, second=0), DUE),
    (END + timedelta(hours=1), END.replace(minute=50, second=0), None),
    (datetime(2026, 11, 3, 16, 5, tzinfo=timezone.utc),
     datetime(2026, 11, 4, 6, 35, tzinfo=timezone.utc), None),
    (datetime(2026, 11, 7, 8, 35, tzinfo=timezone.utc),
     datetime(2026, 11, 9, 6, 35, tzinfo=timezone.utc), None),
])
def test_cron_wakes_same_job_at_exact_backoff_without_shortening_it(
    retry_at, next_cron, expected_wakeup,
):
    jobs = BackgroundScheduler(timezone="UTC")  # Not started: no worker/provider IO.
    row = Mock(status="partial", repair_status="partial", next_retry_at=retry_at)
    database = Mock()
    database.query.return_value.filter.return_value.filter.return_value.filter.return_value.filter.return_value.order_by.return_value.first.return_value = row
    now = DUE.replace(second=0)
    with (
        patch.object(scheduler.settings, "enable_eod_coverage_scheduler", True),
        patch.object(scheduler.settings, "scheduler_eod_coverage_markets", "TW"),
        patch.object(scheduler, "SessionLocal", return_value=database),
        patch.object(scheduler, "expected_eod_trade_date", return_value=DAY),
        patch.object(scheduler, "enqueue_eod_coverage_reconcile") as enqueue,
        patch.object(owner, "compute_eod_coverage", return_value=Mock(universe_hash="fixture")),
        patch.object(owner, "utc_now", return_value=now),
    ):
        scheduler._add_market_eod_coverage_reconcile_job(jobs)
        jobs.modify_job("taiwan_eod_coverage_reconcile", next_run_time=next_cron)
        registered = jobs.get_job("taiwan_eod_coverage_reconcile")
        registered.func(**registered.kwargs)
        job = jobs.get_job("taiwan_eod_coverage_reconcile")
        assert len(jobs.get_jobs()) == 1
        assert job.next_run_time == (expected_wakeup or next_cron)
        enqueue.assert_not_called()  # No early enqueue at 16:35:00.
        if expected_wakeup:
            # Reuse the actual registration kwargs at 16:35:53, then Cron resumes.
            with patch.object(owner, "utc_now", return_value=retry_at):
                job.func(**job.kwargs)
            enqueue.assert_called_once()
            assert enqueue.call_args.kwargs["error_backoff_seconds"] == 900
            assert job.trigger.get_next_fire_time(retry_at, retry_at) == next_cron
