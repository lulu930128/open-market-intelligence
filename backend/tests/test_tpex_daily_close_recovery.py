"""Recorded official response replay; all writes are isolated SQLite only."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json

import pytest

from app.db.models import MarketDailyPrice, RawFetchResult, SourceRegistry, StockMaster
from app.market.daily_ohlcv_acquisition import TaiwanOfficialDailyAcquisitionExecutor, _default_fetch
from app.market.daily_ohlcv_platform import refresh_taiwan_official_daily_venue, read_taiwan_latest_daily_evidence
from app.market.providers import tpex
from app.market.providers.tw_official_daily import (
    TPEX_DAILY_RESOURCE_ID, TPEX_DAILY_CLOSE_RESOURCE_ID, TPEX_DAILY_CLOSE_PARSER_VERSION,
    TPEX_DATED_DAILY_RESOURCE_ID,
    TPEX_DAILY_CLOSE_DESCRIPTOR, TWSE_RWD_DAILY_RESOURCE_ID, parse_tpex_official_daily_payload,
)
from app.sources.defaults import TPEX_DAILY_CLOSE_QUOTES_SOURCE_NAME, TPEX_DAILY_QUOTES_SOURCE_NAME
from test_tw_official_daily_platform import db, FakeResponse, FIXTURE_ROOT  # noqa: F401


DAY = date(2026, 11, 2)
NOW = datetime(2026, 11, 2, 10, 20, tzinfo=timezone.utc)


def raw_payload():
    return json.dumps(json.loads((FIXTURE_ROOT / "tpex_daily_close_excerpt_20261102.json").read_text(
        encoding="utf-8"))["payload"], ensure_ascii=False)


def seed(db):
    for symbol, venue in (("6488", "TPEX"), ("3105", "TPEX"), ("2330", "TWSE")):
        db.add(StockMaster(stock_id=symbol, stock_name=symbol, market=venue, instrument_type="stock", is_active=True))
    db.commit()


def acquire(db, primary, fallback, *, now=NOW, refresh_published=False):
    calls = []
    def fetch(route):
        calls.append(route.resource_id)
        return {TPEX_DAILY_RESOURCE_ID: primary, TPEX_DAILY_CLOSE_RESOURCE_ID: fallback}[route.resource_id]
    executor = TaiwanOfficialDailyAcquisitionExecutor(fetchers={
        TPEX_DAILY_RESOURCE_ID: fetch, TPEX_DAILY_CLOSE_RESOURCE_ID: fetch,
    }, clock=lambda: now)
    result = refresh_taiwan_official_daily_venue(db, venue="TPEX", trade_date=DAY,
        requested_at=now, acquisition=executor, max_external_calls=2, refresh_published=refresh_published)
    return result, calls


def test_recorded_daily_close_schema_date_ohlcv_units_and_target_scope():
    parsed = parse_tpex_official_daily_payload(raw_payload(), target_symbols=frozenset({"6488"}))
    assert parsed.input_row_count == 4 and parsed.matched_row_count == 1
    record = parsed.records[0]
    assert record.trade_date == DAY and record.symbol == "6488"
    assert (record.open_price, record.high_price, record.low_price, record.close_price) == (
        Decimal("740"), Decimal("770"), Decimal("731"), Decimal("760"))
    assert (record.trade_volume, record.trade_value, record.transaction_count) == (10401885, 7831068682, 22796)


@pytest.mark.parametrize("failure", ["stale", "empty", "http403", "schema"])
def test_primary_failure_selects_recorded_batch_and_retains_both_receipts(db, failure):
    seed(db)
    primary = {
        "stale": FakeResponse(text=raw_payload().replace("1151102", "1151030")),
        "empty": FakeResponse(text="[]"),
        "http403": FakeResponse(text="denied", status_code=403),
        "schema": FakeResponse(text='{"unexpected": true}'),
    }[failure]
    result, calls = acquire(db, primary, FakeResponse(text=raw_payload()))
    assert calls == [TPEX_DAILY_RESOURCE_ID, TPEX_DAILY_CLOSE_RESOURCE_ID]
    assert result["external_call_count"] == 2 and result["parsed_count"] == 2
    assert result["replaced_trade_dates"] == [DAY]
    rows = db.query(MarketDailyPrice).all()
    assert {row.stock_id for row in rows} == {"6488", "3105"}
    assert all(row.trade_date == DAY and row.official and row.release_status == "released" for row in rows)
    assert all(row.finalization == "final" for row in rows)
    assert db.query(RawFetchResult).count() == 2
    raw = db.get(RawFetchResult, result["raw_result_id"])
    assert raw.parser_version == TPEX_DAILY_CLOSE_PARSER_VERSION
    assert raw.raw_text == raw_payload()
    assert raw.content_hash == hashlib.sha256(raw_payload().encode()).hexdigest()
    assert db.get(SourceRegistry, raw.source_id).source_name == TPEX_DAILY_CLOSE_QUOTES_SOURCE_NAME
    evidence = read_taiwan_latest_daily_evidence(db, stock_id="6488", to_date=DAY, requested_at=NOW)
    assert evidence.daily.trade_date == DAY and evidence.daily.trade_volume == 10401885
    assert evidence.daily.source == TPEX_DAILY_CLOSE_QUOTES_SOURCE_NAME
    assert not evidence.limitations or "EXPECTED_TRADE_DATE_NOT_OBSERVED" not in evidence.limitations


def test_primary_current_never_fetches_fallback_or_overwrites_its_qualified_row(db):
    seed(db)
    result, calls = acquire(db, FakeResponse(text=raw_payload()), FakeResponse(text="must not fetch"))
    assert calls == [TPEX_DAILY_RESOURCE_ID]
    assert result["external_call_count"] == 1
    assert db.query(SourceRegistry).filter_by(source_name=TPEX_DAILY_CLOSE_QUOTES_SOURCE_NAME).count() == 0
    row = db.query(MarketDailyPrice).filter_by(stock_id="6488").one()
    assert db.get(SourceRegistry, row.source_id).source_name == TPEX_DAILY_QUOTES_SOURCE_NAME


@pytest.mark.parametrize("payload", ["[]", "{}", "not json", raw_payload().replace("1151102", "1151030"),
                                     raw_payload().replace('"TradingShares": "10401885"', '"TradingShares": "-1"')])
def test_unpublished_or_invalid_fallback_never_claims_current_for_6488(db, payload):
    seed(db)
    result, calls = acquire(db, FakeResponse(text="[]"), FakeResponse(text=payload))
    assert len(calls) == 2
    assert db.query(MarketDailyPrice).filter_by(stock_id="6488").count() == 0
    assert db.query(RawFetchResult).count() == 2
    if not db.query(MarketDailyPrice).count():
        assert result["parse_status"] == "error"


def test_fallback_uses_shared_call_budget_and_does_not_claim_published_breadth(db):
    seed(db)
    result, calls = acquire(db, FakeResponse(text="[]"), FakeResponse(text=raw_payload()), refresh_published=True)
    assert calls == [TPEX_DAILY_RESOURCE_ID, TPEX_DAILY_CLOSE_RESOURCE_ID]
    assert "ACQUISITION_CALL_BUDGET_EXHAUSTED" in result["limitations"]
    from app.db.models import TaiwanPublishedBreadthSnapshot
    assert db.query(TaiwanPublishedBreadthSnapshot).count() == 0


def test_default_fetch_uses_verified_url_and_redirect_policy(monkeypatch):
    from app.market_data.integration_contracts import DatasetTarget, RefreshRequirementV1
    from app.market_data.provider_catalog import plan_refresh_acquisition_v1
    from app.market_data.contracts import Market
    from app.market_data.policies import DataPurpose
    requirement = RefreshRequirementV1(dataset_id="tw.daily.ohlcv.full_market",
        target=DatasetTarget(market=Market.TW, dataset_id="tw.daily.ohlcv.full_market", scope_key="TPEX"),
        from_date=DAY, to_date=DAY, requested_at=NOW, purpose=DataPurpose.REPAIR,
        max_provider_attempts=1, max_external_calls=1, timeout_seconds=30, max_symbols=2, max_range_days=1,
        postcondition="Dated official batch is persisted.")
    route = plan_refresh_acquisition_v1(requirement, (TPEX_DAILY_CLOSE_DESCRIPTOR,)).routes[0]
    calls = []
    monkeypatch.setattr(tpex, "get_response", lambda url, **kw: calls.append((url, kw)) or FakeResponse(text="[]"))
    _default_fetch(route, trade_date=DAY)
    assert calls == [(tpex.DAILY_CLOSE_QUOTES_URL, {"timeout_seconds": 30, "allow_redirects": False})]


@pytest.mark.parametrize("prior_tpex", ["missing", "stale"])
def test_recovery_preserves_twse_and_unifies_eod_daily_bar_and_research_dates(db, monkeypatch, prior_tpex):
    from sqlalchemy import event
    from app.market.daily_ohlcv_platform import qualify_taiwan_eod_universe
    from app.market.daily_price_repository import TaiwanOfficialDailyBarRepository
    from app.market.service import read_market_daily_snapshot
    from app.market.tw_bar_service import TaiwanBarService
    from app.market_data.eod_coverage import compute_eod_coverage
    from app.market.tw_swing_screening import SwingScreenRequest, SwingReason, read_tw_swing_evidence, screen_tw_swing_candidates
    seed(db)
    twse_raw = json.dumps(json.loads((FIXTURE_ROOT / "twse_rwd_eod_excerpt_20261102.json").read_text(
        encoding="utf-8"))["payload"], ensure_ascii=False)
    twse = refresh_taiwan_official_daily_venue(db, venue="TWSE", trade_date=DAY, requested_at=NOW,
        acquisition=TaiwanOfficialDailyAcquisitionExecutor(fetchers={TWSE_RWD_DAILY_RESOURCE_ID:
            lambda route: FakeResponse(text=twse_raw)}, clock=lambda: NOW))
    twse_id = twse["raw_result_id"]
    if prior_tpex == "stale":
        refresh_taiwan_official_daily_venue(db, venue="TPEX", trade_date=date(2026, 10, 30), requested_at=NOW,
            refresh_published=False, acquisition=TaiwanOfficialDailyAcquisitionExecutor(fetchers={
                TPEX_DAILY_RESOURCE_ID: lambda route: FakeResponse(text=raw_payload().replace("1151102", "1151030")),
            }, clock=lambda: NOW))
    before = compute_eod_coverage(db, market="TW", expected_trade_date=DAY,
                                taiwan_daily_qualifier=qualify_taiwan_eod_universe, include_published=True)
    assert before.current_count == 1
    assert (before.missing_count, before.stale_count) == ((2, 0) if prior_tpex == "missing" else (0, 2))
    acquire(db, FakeResponse(text="[]"), FakeResponse(text=raw_payload()))
    after = compute_eod_coverage(db, market="TW", expected_trade_date=DAY,
                               taiwan_daily_qualifier=qualify_taiwan_eod_universe, include_published=True)
    assert after.current_count == 3 and after.missing_count == after.stale_count == 0
    assert not after.postcondition_met and "TPEX" in after.missing_published_venues
    assert db.query(MarketDailyPrice).filter_by(stock_id="2330").one().raw_result_id == twse_id
    assert db.query(RawFetchResult).filter_by(source_id=db.get(RawFetchResult, twse_id).source_id).count() == 1
    monkeypatch.setattr("app.market.service.expected_daily_price_date", lambda: DAY)
    universe = TaiwanOfficialDailyBarRepository(db).load_market_universe(trade_date=DAY)
    daily = read_market_daily_snapshot(db, trade_date=DAY)
    assert universe.trade_date == daily.trade_date == DAY
    assert {bar.instrument.symbol for bar in universe.bars} == {row.stock_id for row in daily.rows}
    statements = []
    def observe(conn, cursor, sql, params, context, many):
        statements.append(sql.lstrip().split()[0].upper())
    event.listen(db.get_bind(), "before_cursor_execute", observe)
    try:
        bars = TaiwanBarService(db).read_bars(instrument_id="6488", interval="1d",
            to_time=NOW, limit=60, requested_at=NOW, include_partial=False)
        assert bars.bars[-1].end_at.date() == DAY
        assert bars.bars[-1].close_price == Decimal("760")
        request = SwingScreenRequest(stock_ids=("6488",), as_of_trade_date=DAY, requested_at=NOW)
        assessment = screen_tw_swing_candidates(request, read_tw_swing_evidence(db, request=request)).assessments[0]
        assert SwingReason.DAILY_HISTORY_GAP in assessment.reason_codes  # One new bar does not invent MA60 history.
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", observe)
    assert all(statement in {"SELECT", "PRAGMA"} for statement in statements)


def test_new_source_correction_preserves_receipt_cutoff_and_revision(db):
    from app.db.models import MarketDailyPriceRevision, MarketDailyPriceLineage
    seed(db)
    result, _ = acquire(db, FakeResponse(text="[]"), FakeResponse(text=raw_payload()))
    first_id = result["raw_result_id"]
    corrected = raw_payload().replace('"Close": "760.00"', '"Close": "761.00"')
    later = NOW.replace(minute=30)
    acquire(db, FakeResponse(text="[]"), FakeResponse(text=corrected), now=later)
    current = read_taiwan_latest_daily_evidence(db, stock_id="6488", to_date=DAY, requested_at=later)
    cutoff = read_taiwan_latest_daily_evidence(db, stock_id="6488", to_date=DAY, requested_at=NOW)
    assert current.daily.close_price == Decimal("761") and cutoff.daily.close_price == Decimal("760")
    assert cutoff.daily.raw_result_id == f"raw_fetch_result:{first_id}"
    row = db.query(MarketDailyPrice).filter_by(stock_id="6488").one()
    assert db.query(MarketDailyPriceRevision).filter_by(id=row.id).count() == 2
    assert db.query(MarketDailyPriceLineage).filter_by(daily_price_id=row.id).one().raw_result_id == row.raw_result_id


def primary_payload():
    return json.loads((FIXTURE_ROOT / "tpex_mainboard_partial_excerpt_20261102.json").read_text(
        encoding="utf-8"))["payload"]


def test_recorded_primary_partial_still_attempts_secondary_without_inventing_missing_bar(db):
    seed(db)
    db.add(StockMaster(stock_id="4804", market="TPEX", instrument_type="stock", is_active=True))
    db.commit()
    result, calls = acquire(db, FakeResponse(text=json.dumps(primary_payload())), FakeResponse(text=raw_payload()))
    assert calls == [TPEX_DAILY_RESOURCE_ID, TPEX_DAILY_CLOSE_RESOURCE_ID]
    assert result["parsed_count"] == 2
    assert {row.stock_id for row in db.query(MarketDailyPrice)} == {"6488", "3105"}
    assert db.query(RawFetchResult).count() == 2
    assert "ELIGIBLE_DAILY_TARGETS_MISSING" in result["limitations"]


def test_partial_primary_secondary_only_fills_missing_union_with_separate_lineage(db):
    from app.db.models import MarketDailyPriceLineage, MarketDailyPriceRevision
    seed(db)
    # Fault injection: omit one exact recorded primary row. Prices/dates/units
    # remain recorded values; this is not a claim that the live endpoint omitted it.
    primary = [row for row in primary_payload() if row["SecuritiesCompanyCode"] == "6488"]
    result, calls = acquire(db, FakeResponse(text=json.dumps(primary)), FakeResponse(text=raw_payload()))
    assert calls == [TPEX_DAILY_RESOURCE_ID, TPEX_DAILY_CLOSE_RESOURCE_ID]
    assert result["parsed_count"] == 2
    rows = {row.stock_id: row for row in db.query(MarketDailyPrice)}
    assert set(rows) == {"6488", "3105"}
    assert db.get(SourceRegistry, rows["6488"].source_id).source_name == TPEX_DAILY_QUOTES_SOURCE_NAME
    assert db.get(SourceRegistry, rows["3105"].source_id).source_name == TPEX_DAILY_CLOSE_QUOTES_SOURCE_NAME
    for row in rows.values():
        raw = db.get(RawFetchResult, row.raw_result_id)
        assert raw.source_id == row.source_id and row.trade_date == DAY
        assert row.authority == "exchange" and row.finalization == "final" and row.release_status == "released"
        assert db.query(MarketDailyPriceRevision).filter_by(id=row.id).one().raw_result_id == raw.id
        assert db.query(MarketDailyPriceLineage).filter_by(daily_price_id=row.id).one().raw_result_id == raw.id


@pytest.mark.parametrize("secondary", [FakeResponse(text="denied", status_code=403),
    FakeResponse(text=raw_payload().replace("1151102", "1151030"))])
def test_partial_primary_secondary_failure_keeps_primary_and_missing_truth(db, secondary):
    seed(db)
    primary = [row for row in primary_payload() if row["SecuritiesCompanyCode"] == "6488"]
    result, calls = acquire(db, FakeResponse(text=json.dumps(primary)), secondary)
    assert len(calls) == 2 and result["parsed_count"] == 1
    assert {row.stock_id for row in db.query(MarketDailyPrice)} == {"6488"}
    assert db.query(RawFetchResult).count() == 2
    assert "ELIGIBLE_DAILY_TARGETS_MISSING" in result["limitations"]


def eod_harness(db, monkeypatch, *, extra_missing=False):
    from app.market_data.eod_coverage import reconcile_eod_coverage
    from app.market.daily_ohlcv_platform import qualify_taiwan_eod_universe
    from app.market.providers.tw_official_daily import TPEX_HIGHLIGHT_RESOURCE_ID, TWSE_DAILY_RESOURCE_ID
    from test_tw_published_breadth import payload as synthetic_twse_breadth
    seed(db)
    if extra_missing:
        db.add(StockMaster(stock_id="4804", market="TPEX", instrument_type="stock", is_active=True))
    db.commit()
    clock = [NOW]
    calls = []
    responses = {
        TWSE_RWD_DAILY_RESOURCE_ID: json.loads((FIXTURE_ROOT / "twse_rwd_eod_excerpt_20261102.json").read_text(
            encoding="utf-8"))["payload"],
        # A controlled primary omission exercises the complementary union. The
        # separate recorded-partial test above never invents real missing values.
        TPEX_DAILY_RESOURCE_ID: [row for row in primary_payload() if row["SecuritiesCompanyCode"] == "6488"],
        TPEX_DAILY_CLOSE_RESOURCE_ID: json.loads(raw_payload()),
        TPEX_DATED_DAILY_RESOURCE_ID: {},  # No verified dated website payload in this older replay.
        TPEX_HIGHLIGHT_RESOURCE_ID: {},  # No verified 11/02 breadth supplied.
        TWSE_DAILY_RESOURCE_ID: [],
    }
    # Existing synthetic aggregate fixture models the already-qualified TWSE
    # breadth axis; its counts are not asserted to be real 11/02 market counts.
    responses[TWSE_RWD_DAILY_RESOURCE_ID]["tables"].append(synthetic_twse_breadth()["tables"][-1])
    def fetch(route):
        calls.append(route.resource_id)
        response = responses[route.resource_id]
        return response if isinstance(response, FakeResponse) else FakeResponse(text=json.dumps(response))
    executor = TaiwanOfficialDailyAcquisitionExecutor(fetchers={key: fetch for key in responses}, clock=lambda: clock[0])
    monkeypatch.setattr("app.market_data.eod_coverage.utc_now", lambda: clock[0])
    def reconcile(day=DAY, *, advance=True):
        if advance:
            clock[0] += timedelta(seconds=61)
        return reconcile_eod_coverage(db, market="TW", expected_trade_date=day,
            taiwan_daily_qualifier=qualify_taiwan_eod_universe,
            taiwan_venue_refresher=lambda **kw: refresh_taiwan_official_daily_venue(
                **kw, requested_at=clock[0], acquisition=executor), error_backoff_seconds=60)
    return reconcile, calls, responses, clock


def test_eod_two_calls_resume_secondary_then_breadth_without_refetching_current_twse(db, monkeypatch):
    from app.db.models import MarketDatasetCoverageCheckpoint
    from app.market.providers.tw_official_daily import TPEX_HIGHLIGHT_RESOURCE_ID
    reconcile, calls, responses, clock = eod_harness(db, monkeypatch)
    first = reconcile()
    assert calls == [TWSE_RWD_DAILY_RESOURCE_ID, TPEX_DAILY_RESOURCE_ID]
    assert first["external_call_budget_used"] == 2 and first["current_count"] == 2
    state = first["checkpoint"]["detail"]["venue_route_states"]["TPEX"]
    assert state["attempted_resources"] == [TPEX_DAILY_RESOURCE_ID]
    assert set(state["pending_resources"]) == {TPEX_DAILY_CLOSE_RESOURCE_ID, TPEX_DATED_DAILY_RESOURCE_ID, TPEX_HIGHLIGHT_RESOURCE_ID}
    original_ids = {row.stock_id: row.raw_result_id for row in db.query(MarketDailyPrice)}
    # Existing retry backoff admits zero calls and retains the same state.
    assert reconcile(advance=False)["attempted_count"] == 0
    assert len(calls) == 2
    db.expire_all()  # New job/session reads the committed route continuation.
    second = reconcile()
    assert calls == [TWSE_RWD_DAILY_RESOURCE_ID, TPEX_DAILY_RESOURCE_ID,
                     TPEX_DAILY_CLOSE_RESOURCE_ID, TPEX_HIGHLIGHT_RESOURCE_ID]
    assert second["external_call_budget_used"] == 2 and second["current_count"] == 3
    assert second["published_breadth"] == {"TPEX": False, "TWSE": True}
    assert not second["postcondition_met"]
    assert db.query(MarketDatasetCoverageCheckpoint).count() == 1
    for symbol, raw_id in original_ids.items():
        assert db.query(MarketDailyPrice).filter_by(stock_id=symbol).one().raw_result_id == raw_id
    third = reconcile()
    assert calls[-1] == TPEX_HIGHLIGHT_RESOURCE_ID and len(calls) == 5
    assert third["external_call_budget_used"] == 1 and not third["postcondition_met"]
    assert db.query(MarketDailyPrice).count() == 3


@pytest.mark.parametrize("twse_gap", ["partial_daily", "published_only"])
def test_eod_twse_one_call_each_retry_cannot_starve_tpex_secondary_or_breadth(db, monkeypatch, twse_gap):
    from app.market.providers.tw_official_daily import TPEX_HIGHLIGHT_RESOURCE_ID
    reconcile, calls, responses, clock = eod_harness(db, monkeypatch, extra_missing=True)
    if twse_gap == "partial_daily":
        db.add(StockMaster(stock_id="1589", market="TWSE", instrument_type="stock", is_active=True))
        db.commit()
    else:
        # Preseed qualified TWSE bars, but keep its aggregate unavailable. Every
        # TWSE revisit uses exactly one published-only call, as in the starvation
        # trigger; the current bar's original raw must stay unchanged.
        responses[TWSE_RWD_DAILY_RESOURCE_ID]["tables"].pop()
        refresh_taiwan_official_daily_venue(db, venue="TWSE", trade_date=DAY, requested_at=NOW,
            acquisition=TaiwanOfficialDailyAcquisitionExecutor(fetchers={TWSE_RWD_DAILY_RESOURCE_ID:
                lambda _: FakeResponse(text=json.dumps(responses[TWSE_RWD_DAILY_RESOURCE_ID]))}, clock=lambda: NOW),
            refresh_published=False, max_external_calls=1)
    original_twse = db.query(MarketDailyPrice).filter_by(stock_id="2330").first()
    original_raw = original_twse.raw_result_id if original_twse else None
    results = [reconcile() for _ in range(4)]
    assert all(result["external_call_budget_used"] <= 2 for result in results)
    assert TPEX_DAILY_CLOSE_RESOURCE_ID in calls and TPEX_HIGHLIGHT_RESOURCE_ID in calls
    assert calls.index(TPEX_DAILY_RESOURCE_ID) < calls.index(TPEX_DAILY_CLOSE_RESOURCE_ID) < calls.index(TPEX_HIGHLIGHT_RESOURCE_ID)
    assert all(not result["postcondition_met"] for result in results)
    assert {row.stock_id for row in db.query(MarketDailyPrice)} == {"2330", "6488", "3105"}
    assert all(result["missing_count"] == (2 if twse_gap == "partial_daily" else 1) for result in results[2:])
    if original_raw is not None:
        assert db.query(MarketDailyPrice).filter_by(stock_id="2330").one().raw_result_id == original_raw


@pytest.mark.parametrize("change", ["date", "universe"])
def test_eod_route_continuation_resets_with_existing_checkpoint_identity(db, monkeypatch, change):
    from app.db.models import MarketDatasetCoverageCheckpoint
    reconcile, calls, responses, clock = eod_harness(db, monkeypatch)
    first = reconcile()
    old = first["checkpoint"]
    assert old["detail"]["venue_route_states"]["TPEX"]["attempted_resources"] == [TPEX_DAILY_RESOURCE_ID]
    before = len(calls)
    day = DAY
    if change == "date":
        day += timedelta(days=1)
        clock[0] += timedelta(days=1)
        # Synthetic next-session replay checks lifecycle identity, not real prices.
        for resource, payload in responses.items():
            responses[resource] = json.loads(json.dumps(payload).replace("1151102", "1151103").replace("20261102", "20261103"))
    else:
        db.add(StockMaster(stock_id="8069", market="TPEX", instrument_type="stock", is_active=True))
        db.commit()
    second = reconcile(day)
    assert second["checkpoint"]["id"] != old["id"]
    assert db.query(MarketDatasetCoverageCheckpoint).count() == 2
    assert TPEX_DAILY_RESOURCE_ID in calls[before:]  # Fresh pool, never skip from old state.
    assert second["checkpoint"]["detail"]["venue_route_states"]["TPEX"]["trade_date"] == day.isoformat()
    assert json.loads(db.get(MarketDatasetCoverageCheckpoint, old["id"]).detail_json)["venue_route_states"] == old["detail"]["venue_route_states"]


def test_complementary_sources_retain_independent_correction_revisions_and_cutoffs(db):
    from app.db.models import MarketDailyPriceRevision, MarketDailyPriceLineage
    seed(db)
    primary = [row for row in primary_payload() if row["SecuritiesCompanyCode"] == "6488"]
    first, _ = acquire(db, FakeResponse(text=json.dumps(primary)), FakeResponse(text=raw_payload()))
    original = {row.stock_id: (row.raw_result_id, row.close_price) for row in db.query(MarketDailyPrice)}
    primary[0]["Close"] = str(Decimal(primary[0]["Close"]) + 1)
    changed_secondary = json.loads(raw_payload())
    next(row for row in changed_secondary if row["SecuritiesCompanyCode"] == "3105")["Close"] = "589.00"
    later = NOW + timedelta(minutes=10)
    second, _ = acquire(db, FakeResponse(text=json.dumps(primary)), FakeResponse(text=json.dumps(changed_secondary)), now=later)
    assert first["parsed_count"] == second["parsed_count"] == 2
    for row in db.query(MarketDailyPrice):
        raw_id, old_close = original[row.stock_id]
        cutoff = read_taiwan_latest_daily_evidence(db, stock_id=row.stock_id, to_date=DAY, requested_at=NOW)
        current = read_taiwan_latest_daily_evidence(db, stock_id=row.stock_id, to_date=DAY, requested_at=later)
        assert cutoff.daily.raw_result_id == f"raw_fetch_result:{raw_id}"
        assert cutoff.daily.close_price == Decimal(str(old_close))
        assert current.daily.close_price == Decimal(str(old_close)) + 1
        assert db.query(MarketDailyPriceRevision).filter_by(id=row.id).count() == 2
        assert db.query(MarketDailyPriceLineage).filter_by(daily_price_id=row.id).one().raw_result_id == row.raw_result_id


def test_breadth_only_continuation_succeeds_independently_while_bars_remain_partial(db, monkeypatch):
    from app.market_data.eod_coverage import reconcile_eod_coverage
    from app.market.daily_ohlcv_platform import qualify_taiwan_eod_universe
    from app.market.providers.tw_official_daily import TPEX_HIGHLIGHT_RESOURCE_ID
    from test_tpex_published_breadth import DAY as breadth_day, NOW as breadth_now, RAW as breadth_raw
    db.add_all([StockMaster(stock_id=symbol, market="TPEX", instrument_type="stock", is_active=True)
                for symbol in ("6488", "4804")])
    db.commit()
    clock = [breadth_now]
    calls = []
    # Synthetic stock dates compose the lifecycle with the unchanged, verified
    # 10/22 published breadth bytes. No 11/02 breadth schema/counts are invented.
    raw = raw_payload().replace("1151102", "1151022")
    def fetch(route):
        calls.append(route.resource_id)
        return FakeResponse(text=breadth_raw.decode("utf-8") if route.resource_id == TPEX_HIGHLIGHT_RESOURCE_ID else raw)
    executor = TaiwanOfficialDailyAcquisitionExecutor(fetchers={resource: fetch for resource in (
        TPEX_DAILY_RESOURCE_ID, TPEX_DAILY_CLOSE_RESOURCE_ID, TPEX_DATED_DAILY_RESOURCE_ID, TPEX_HIGHLIGHT_RESOURCE_ID)}, clock=lambda: clock[0])
    monkeypatch.setattr("app.market_data.eod_coverage.utc_now", lambda: clock[0])
    def run():
        return reconcile_eod_coverage(db, market="TW", expected_trade_date=breadth_day,
            taiwan_daily_qualifier=qualify_taiwan_eod_universe, error_backoff_seconds=60,
            taiwan_venue_refresher=lambda **kw: refresh_taiwan_official_daily_venue(
                **kw, requested_at=clock[0], acquisition=executor))
    first = run()
    assert first["external_call_budget_used"] == 2 and not first["postcondition_met"]
    first_raw = db.query(MarketDailyPrice).one().raw_result_id
    clock[0] += timedelta(seconds=61)
    second = run()
    assert calls == [TPEX_DAILY_RESOURCE_ID, TPEX_DAILY_CLOSE_RESOURCE_ID, TPEX_DATED_DAILY_RESOURCE_ID, TPEX_HIGHLIGHT_RESOURCE_ID]
    assert second["external_call_budget_used"] == 2 and second["error_count"] == 0
    assert second["published_breadth"] == {"TPEX": True}
    assert second["current_count"] == second["missing_count"] == 1
    assert not second["postcondition_met"]
    assert db.query(MarketDailyPrice).one().raw_result_id == first_raw
    provider = second["checkpoint"]["detail"]["repair"]["provider_results"][0]
    assert provider["fetch_status"] == provider["parse_status"] == "success"
    assert provider["published_postcondition_met"] and not provider["venue_postcondition_met"]
