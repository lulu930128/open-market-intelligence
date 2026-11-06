"""Current Snapshot semantics versus retained receipt/PIT truth; isolated caches."""
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import socket
from unittest.mock import Mock

import pytest

from app.config import settings
from app.market import exchange_calendar_cache as calendar
from app.market import tw_corporate_events as events
from app.market.price_map_snapshot_repository import read_price_map_external_revision
from app.market_data.contracts import InstrumentKey
from test_tw_price_map_screening import sessions

NOW = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)
EARLIER = NOW - timedelta(hours=2)
KEY = "twse_instrument_history"
INSTRUMENT = InstrumentKey(market="TW", venue="TWSE", symbol="1102", instrument_type="stock")


@pytest.fixture
def caches(tmp_path, monkeypatch):
    event_path, calendar_path = tmp_path / "events.json", tmp_path / "calendar.json"
    monkeypatch.setattr(settings, "tw_corporate_event_cache_path", event_path)
    monkeypatch.setattr(settings, "market_calendar_cache_path", calendar_path)
    monkeypatch.setattr(socket.socket, "connect", Mock(side_effect=AssertionError("network forbidden")))
    events.invalidate_taiwan_corporate_event_cache()
    calendar.invalidate_exchange_calendar_cache()
    yield event_path, calendar_path
    events.invalidate_taiwan_corporate_event_cache()
    calendar.invalidate_exchange_calendar_cache()


def write_event(path, provider):
    path.write_text(json.dumps({"schema_version": 1, "providers": {KEY: provider}}, default=str), encoding="utf-8")
    events.invalidate_taiwan_corporate_event_cache()


def provider():
    raw_text = "official fixture announcement"
    digest = sha256(raw_text.encode()).hexdigest()
    lineage = {"provider": "twse", "source": "official_suspension_notice", "authority": "exchange",
        "fetched_at": EARLIER.isoformat(), "event_at": "2026-08-03T00:00:00+08:00",
        "content_hash": digest, "raw_receipt_id": "receipt:original"}
    return {**events.PROVIDER_CONFIG[KEY], "fetched_at": EARLIER.isoformat(), "coverage_start": "2026-08-01",
        "coverage_end": "2026-08-31", "entries": [{"event_id": "receipt:original:suspension", "stock_id": "1102",
        "market": "TWSE", "event_type": "suspension", "status": "suspended", "start_date": "2026-08-03",
        "end_date": "2026-08-05", "lineage": lineage}], "evidence_windows": [{
        "window_id": "receipt:original:coverage", "stock_id": "1102", "start_date": "2026-08-01",
        "end_date": "2026-08-31", "complete": True, "event_types": ["ex_dividend", "capital_reduction", "price_basis_change"],
        "lineage": deepcopy(lineage)}], "raw_receipts": [{"receipt_id": "receipt:original",
        "content_hash": digest, "raw_text": raw_text, "url": events.PROVIDER_CONFIG[KEY]["source_url"],
        "fetched_at": EARLIER.isoformat()}]}


def revision():
    return events.taiwan_corporate_event_semantic_revision(available_at=NOW)


def test_empty_instrument_refresh_health_and_unreferenced_receipts_do_not_invalidate(caches, monkeypatch):
    from app.market.providers import tw_trading_status
    before, raw_before = read_price_map_external_revision(), events.taiwan_corporate_event_revision()
    text = "<html>No historical instrument evidence in this response.</html>"
    monkeypatch.setattr(tw_trading_status, "fetch_taiwan_instrument_events", Mock(return_value={
        "status": "unresolved", "entries": [], "evidence_windows": [], "request_count": 1,
        "raw_receipts": [{"receipt_id": "receipt:empty", "raw_text": text,
            "content_hash": sha256(text.encode()).hexdigest(), "url": events.PROVIDER_CONFIG[KEY]["source_url"],
            "fetched_at": EARLIER.isoformat()}]}))
    events.refresh_taiwan_instrument_event_history(instrument=INSTRUMENT,
        start_date=date(2026, 8, 1), end_date=date(2026, 8, 31))
    assert events.taiwan_corporate_event_revision() != raw_before  # Receipt truth retained.
    assert read_price_map_external_revision() == before
    events._write_refresh(updates={}, errors={KEY: "fixture timeout"}, attempted_at=NOW)
    assert read_price_map_external_revision() == before


def test_identical_qualified_result_new_receipt_is_stable_but_pit_still_uses_actual_time(caches):
    path, _ = caches
    original = provider()
    write_event(path, original)
    before = revision()
    current = deepcopy(original)
    current.update(fetched_at=NOW.isoformat(), last_attempt_at=NOW.isoformat(), last_error="health only")
    for item in [*current["entries"], *current["evidence_windows"]]:
        item["lineage"].update(fetched_at=NOW.isoformat(), raw_receipt_id="receipt:refetched")
        for key in ("event_id", "window_id"):
            if key in item:
                item[key] = item[key].replace("original", "refetched")
    current["raw_receipts"][0].update(receipt_id="receipt:refetched", fetched_at=NOW.isoformat())
    write_event(path, current)
    assert revision() == before
    raw_cache = path.read_bytes()
    earlier_cutoff = NOW - timedelta(hours=1)
    earlier = events.read_taiwan_instrument_event_evidence(instrument=INSTRUMENT, available_at=earlier_cutoff)
    visible = events.read_taiwan_instrument_event_evidence(instrument=INSTRUMENT, available_at=NOW)
    assert not earlier["events"] and earlier["limitations"] == ("INSTRUMENT_EVENT_EVIDENCE_INVALID",)
    assert len(visible["events"]) == len(visible["windows"]) == 1
    assert visible["events"][0]["lineage"].fetched_at == NOW
    assert events.taiwan_corporate_event_semantic_revision(available_at=earlier_cutoff) != before
    assert path.read_bytes() == raw_cache  # No timestamp rewriting or PIT mutation.


@pytest.mark.parametrize("change", [
    "event", "interval", "stock", "complete", "families", "coverage", "authority", "source",
    "event_time", "raw_corrupt", "raw_missing", "raw_hash_mismatch", "untrusted_url", "future_receipt", "malformed_families",
])
def test_real_event_coverage_authority_and_qualification_changes_invalidate(caches, change):
    path, _ = caches
    value = provider()
    write_event(path, value)
    before = revision()
    if change == "event": value["entries"][0]["status"] = "tradable"
    elif change == "interval": value["entries"][0]["end_date"] = "2026-08-06"
    elif change == "stock": value["entries"][0]["stock_id"] = "1103"
    elif change == "complete": value["evidence_windows"][0]["complete"] = False
    elif change == "families": value["evidence_windows"][0]["event_types"].pop()
    elif change == "coverage": value["coverage_end"] = "2026-08-30"
    elif change == "authority": value["entries"][0]["lineage"]["authority"] = "vendor"
    elif change == "source": value["entries"][0]["lineage"]["source"] = "different_official_contract"
    elif change == "event_time": value["entries"][0]["lineage"]["event_at"] = "2026-08-04T00:00:00+08:00"
    elif change == "raw_corrupt": value["raw_receipts"][0]["raw_text"] += "tampered"
    elif change == "raw_missing": value["raw_receipts"] = []
    elif change == "raw_hash_mismatch": value["entries"][0]["lineage"]["content_hash"] = "wrong"
    elif change == "untrusted_url": value["raw_receipts"][0]["url"] = "https://example.invalid/notice"
    elif change == "future_receipt": value["entries"][0]["lineage"]["fetched_at"] = (NOW + timedelta(days=1)).isoformat()
    elif change == "malformed_families": value["evidence_windows"][0]["event_types"] = [{}]
    write_event(path, value)
    assert revision() != before


def test_reordered_or_duplicate_instrument_evidence_is_not_a_new_fact(caches):
    path, _ = caches
    value = provider()
    write_event(path, value)
    before = revision()
    value["entries"] *= 2
    value["raw_receipts"] *= 2
    value["evidence_windows"][0]["event_types"].reverse()
    write_event(path, value)
    assert revision() == before


def test_equivalent_parsed_evidence_from_new_official_page_hash_does_not_invalidate(caches):
    path, _ = caches
    original = provider()
    write_event(path, original)
    before = revision()
    update = deepcopy(original)
    text = "new official page, same parsed event/window"
    digest = sha256(text.encode()).hexdigest()
    update["raw_receipts"] = [{"receipt_id": "receipt:new-page", "raw_text": text,
        "content_hash": digest, "url": events.PROVIDER_CONFIG[KEY]["source_url"], "fetched_at": NOW.isoformat()}]
    for item in [*update["entries"], *update["evidence_windows"]]:
        item["lineage"].update(content_hash=digest, raw_receipt_id="receipt:new-page", fetched_at=NOW.isoformat())
        if "event_id" in item: item["event_id"] = "new-page:event"
        if "window_id" in item: item["window_id"] = "new-page:window"
    events._write_refresh(updates={KEY: {**update, "merge_instrument_evidence": True}}, errors={}, attempted_at=NOW)
    assert revision() == before


def test_history_coverage_gate_changes_still_invalidate_without_health_wording_churn(caches):
    path, _ = caches
    value = {**events.PROVIDER_CONFIG["twse_ex_dividend_history"], "fetched_at": EARLIER.isoformat(),
             "coverage_start": "2020-01-01", "coverage_end": "2026-10-30", "entries": []}
    payload = {"schema_version": 1, "providers": {"twse_ex_dividend_history": value}}
    def save():
        path.write_text(json.dumps(payload), encoding="utf-8")
        events.invalidate_taiwan_corporate_event_cache()
    save(); before = revision()
    value.update(fetched_at=NOW.isoformat(), last_attempt_at=NOW.isoformat(), retry_count=5)
    save(); assert revision() == before
    value["coverage_end"] = "2026-10-29"
    save(); assert revision() != before
    value["coverage_end"] = "2026-10-30"
    value["last_error"] = "provider failed"
    save(); degraded = revision()
    assert degraded != before  # Existing current-only Corporate Action gate retained.
    value["last_error"] = "different error text, same coverage qualification"
    save(); assert revision() == degraded


def test_legacy_ex_dividend_receipt_cutoff_and_actual_event_fields_are_preserved(caches):
    path, _ = caches
    entry = {"event_id": "ex:1102", "stock_id": "1102", "event_type": "ex_dividend",
             "start_date": "2026-08-20", "end_date": "2026-08-20", "cash_dividend": 2}
    value = {**events.PROVIDER_CONFIG["twse_ex_dividend_history"], "fetched_at": EARLIER.isoformat(),
             "coverage_start": "2020-01-01", "coverage_end": "2026-10-30", "entries": [entry]}
    def save():
        path.write_text(json.dumps({"schema_version": 1, "providers": {"twse_ex_dividend_history": value}}), encoding="utf-8")
        events.invalidate_taiwan_corporate_event_cache()
    save(); before = revision()
    hidden = events.read_taiwan_instrument_event_evidence(instrument=INSTRUMENT, available_at=EARLIER - timedelta(seconds=1))
    visible = events.read_taiwan_instrument_event_evidence(instrument=INSTRUMENT, available_at=NOW)
    assert not hidden["events"] and visible["events"][0]["lineage"].authority == "exchange"
    assert visible["events"][0]["lineage"].fetched_at == EARLIER
    value.update(fetched_at=NOW.isoformat(), last_attempt_at=NOW.isoformat())
    save(); assert revision() == before
    entry["cash_dividend"] = 3
    save(); assert revision() != before


def test_calendar_identical_verified_data_and_health_are_stable_but_facts_invalidate(caches):
    update = calendar.CalendarCacheUpdate(provider="twse", source="official_calendar",
        source_url="https://www.twse.com.tw/holiday", fetched_at=EARLIER,
        holidays={date(2026, 1, 1): "New Year"}, verified_years=frozenset({2026}))
    calendar.write_exchange_calendar_refresh(updates={"tw": update}, errors={}, attempted_at=EARLIER)
    before = read_price_map_external_revision()
    calendar.write_exchange_calendar_refresh(updates={"tw": replace(update, fetched_at=NOW)}, errors={}, attempted_at=NOW)
    assert read_price_map_external_revision() == before
    calendar.write_exchange_calendar_refresh(updates={}, errors={"tw": "fixture failed"}, attempted_at=NOW)
    assert read_price_map_external_revision() == before
    assert calendar.cached_market_holiday("tw", date(2026, 1, 1)).name == "New Year"
    calendar.write_exchange_calendar_refresh(updates={"tw": replace(update, holidays={date(2026, 1, 2): "Correction"})}, errors={}, attempted_at=NOW)
    changed_holiday = read_price_map_external_revision()
    assert changed_holiday != before
    calendar.write_exchange_calendar_refresh(updates={"tw": replace(update,
        holidays={date(2026, 1, 2): "Correction"}, verified_years=frozenset({2026, 2027}))}, errors={}, attempted_at=NOW)
    assert read_price_map_external_revision() != changed_holiday


def test_builtin_calendar_emergency_algorithm_and_quality_versions_remain_dependencies(caches, monkeypatch):
    from app.market import trading_calendar, technical_evidence, tw_technical_service
    before = read_price_map_external_revision()
    with monkeypatch.context() as m:
        m.setattr(trading_calendar, "TAIWAN_MARKET_HOLIDAYS", {2026: {date(2026, 9, 11): "fixture closed"}})
        assert read_price_map_external_revision() != before
    with monkeypatch.context() as m:
        m.setattr(trading_calendar, "TAIWAN_EMERGENCY_MARKET_CLOSURES", {date(2026, 9, 11):
            type("Closure", (), {"name": "fixture", "reason_code": "TYPHOON", "source": "official"})()})
        assert read_price_map_external_revision() != before
    with monkeypatch.context() as m:
        m.setattr(technical_evidence, "INDICATOR_ALGORITHM_VERSION", "fixture-new-algorithm")
        assert read_price_map_external_revision() != before
    with monkeypatch.context() as m:
        m.setattr(tw_technical_service, "INPUT_QUALITY_VERSION", "fixture-new-quality")
        assert read_price_map_external_revision() != before


@pytest.mark.parametrize("identity", ["provider", "source", "source_url"])
def test_calendar_source_identity_remains_a_dependency(caches, identity):
    update = calendar.CalendarCacheUpdate(provider="twse", source="official_calendar",
        source_url="https://www.twse.com.tw/holiday", fetched_at=EARLIER,
        holidays={date(2026, 1, 1): "New Year"}, verified_years=frozenset({2026}))
    calendar.write_exchange_calendar_refresh(updates={"tw": update}, errors={}, attempted_at=EARLIER)
    before = read_price_map_external_revision()
    calendar.write_exchange_calendar_refresh(updates={"tw": replace(update, **{identity: "changed_identity"})}, errors={}, attempted_at=NOW)
    assert read_price_map_external_revision() != before


def test_published_ready_empty_partial_headers_survive_metadata_but_rebuild_on_real_change(caches, sessions):
    from app.jobs.taiwan_price_map_snapshot_scheduler import produce_taiwan_price_map_snapshots
    from test_tw_price_map_screening import seed, payload, NOW as SNAPSHOT_NOW
    from app.db.models import TaiwanPriceMapSnapshot
    with sessions() as db:
        seed(db, 3)
    def build(**kw):
        symbol = kw["stock_id"]
        return {**payload(zones=symbol != "2332", stock_id=symbol), "decision_usable": symbol != "2331"}
    first = produce_taiwan_price_map_snapshots(session_factory=sessions, builder=build, clock=lambda: SNAPSHOT_NOW)
    assert first["publication_status_counts"] == {"ready": 1, "partial": 1, "empty": 1}
    before = read_price_map_external_revision()
    events._write_refresh(updates={KEY: {"merge_instrument_evidence": True, "entries": [], "raw_receipts": []}},
        errors={}, attempted_at=NOW)
    events._write_refresh(updates={}, errors={KEY: "empty acquisition failed"}, attempted_at=NOW)
    assert read_price_map_external_revision() == before
    unchanged = produce_taiwan_price_map_snapshots(session_factory=sessions,
        builder=Mock(side_effect=AssertionError("metadata recompute")), clock=lambda: SNAPSHOT_NOW)
    assert unchanged["attempted"] == 0 and unchanged["skipped_reason_counts"] == {"current_published": 3}
    write_event(caches[0], provider())
    assert read_price_map_external_revision() != before
    changed = produce_taiwan_price_map_snapshots(session_factory=sessions, builder=build, clock=lambda: SNAPSHOT_NOW)
    assert changed["published"] == 3
    with sessions() as db:
        assert all(row.corporate_revision == read_price_map_external_revision()
                   for row in db.query(TaiwanPriceMapSnapshot).all())


@pytest.mark.parametrize("venue", ["TWSE", "TPEX"])
@pytest.mark.parametrize("result_kind", ["empty", "same", "duplicate"])
def test_bounded_history_refresh_preserves_coverage_digest_and_matcher(caches, monkeypatch, venue, result_kind):
    from types import SimpleNamespace
    from app.market.price_map_snapshot_repository import snapshot_matches
    from app.market.stock_price_map_schemas import METHODOLOGY_VERSION

    key = f"{venue.lower()}_ex_dividend_history"
    entry = {"event_id": "ex:1102", "stock_id": "1102", "market": venue,
        "event_type": "ex_dividend", "start_date": "2026-10-20", "end_date": "2026-10-20",
        "cash_dividend": 2}
    events._write_refresh(updates={key: {"entries": [entry], "coverage_start": date(2022, 1, 1),
        "coverage_end": date(2026, 10, 30), "coverage_years": list(range(2022, 2027))}},
        errors={}, attempted_at=EARLIER)
    before, raw_before = read_price_map_external_revision(), events.taiwan_corporate_event_revision()
    calendar_before = calendar.exchange_calendar_semantic_revision("tw")
    row = SimpleNamespace(input_revision=1, parameter_revision="fixture", corporate_revision=before,
        basis_date=date(2026, 10, 30), methodology_version=METHODOLOGY_VERSION)
    expected = dict(input_revision=1, parameter_revision="fixture", corporate_revision=before, basis_date=row.basis_date)
    assert snapshot_matches(row, **expected)
    result = [] if result_kind == "empty" else [entry] * (2 if result_kind == "duplicate" else 1)
    fetch = Mock(return_value=result)
    monkeypatch.setattr(events, f"fetch_{venue.lower()}_ex_dividend_history", fetch)
    instrument = INSTRUMENT.model_copy(update={"venue": venue})
    events.refresh_taiwan_price_basis_events(instrument=instrument,
        start_date=date(2026, 10, 19), end_date=date(2026, 10, 29), cache_path=caches[0])
    fetch.assert_called_once()
    after = read_price_map_external_revision()
    stored = events.read_taiwan_corporate_event_cache()["providers"][key]
    assert (stored["coverage_start"], stored["coverage_end"], stored["coverage_years"]) == (
        "2022-01-01", "2026-10-30", list(range(2022, 2027)))
    assert stored["entries"] == [entry]
    assert calendar.exchange_calendar_semantic_revision("tw") == calendar_before
    assert events.taiwan_corporate_event_revision() != raw_before
    assert after == before
    assert snapshot_matches(row, **{**expected, "corporate_revision": after})


@pytest.mark.parametrize("change", ["event", "coverage"])
def test_bounded_history_real_changes_still_invalidate(caches, monkeypatch, change):
    key = "twse_ex_dividend_history"
    entry = {"event_id": "ex:1102", "stock_id": "1102", "event_type": "ex_dividend",
        "start_date": "2026-10-20", "end_date": "2026-10-20", "cash_dividend": 2}
    events._write_refresh(updates={key: {"entries": [entry], "coverage_start": date(2022, 1, 1),
        "coverage_end": date(2026, 10, 30), "coverage_years": list(range(2022, 2027))}},
        errors={}, attempted_at=EARLIER)
    before = read_price_map_external_revision()
    changed = {**entry, "cash_dividend": 3} if change == "event" else entry
    monkeypatch.setattr(events, "fetch_twse_ex_dividend_history", Mock(return_value=[changed]))
    events.refresh_taiwan_price_basis_events(instrument=INSTRUMENT,
        start_date=date(2026, 10, 19), end_date=date(2026, 10, 31) if change == "coverage" else date(2026, 10, 29))
    assert read_price_map_external_revision() != before


def test_bounded_history_new_event_keeps_actual_receipt_cutoff(caches, monkeypatch):
    key = "twse_ex_dividend_history"
    events._write_refresh(updates={key: {"entries": [], "coverage_start": date(2022, 1, 1),
        "coverage_end": date(2026, 10, 30)}}, errors={}, attempted_at=EARLIER)
    entry = {"event_id": "ex:1102", "stock_id": "1102", "event_type": "ex_dividend",
        "start_date": "2026-10-20", "end_date": "2026-10-20", "cash_dividend": 2}
    monkeypatch.setattr(events, "fetch_twse_ex_dividend_history", Mock(return_value=[entry]))
    events.refresh_taiwan_price_basis_events(instrument=INSTRUMENT,
        start_date=date(2026, 10, 19), end_date=date(2026, 10, 29))
    stored = events.read_taiwan_corporate_event_cache()["providers"][key]
    received = datetime.fromisoformat(stored["fetched_at"])
    assert stored["coverage_fetched_at"] == EARLIER.isoformat()
    assert received > EARLIER
    hidden = events.read_taiwan_instrument_event_evidence(
        instrument=INSTRUMENT, available_at=received - timedelta(seconds=1))
    visible = events.read_taiwan_instrument_event_evidence(instrument=INSTRUMENT, available_at=received)
    assert not hidden["events"]
    assert len(visible["events"]) == 1 and visible["events"][0]["lineage"].fetched_at == received


def test_bounded_history_refresh_does_not_rebuild_published_ready_partial_empty(caches, sessions, monkeypatch):
    from app.jobs.taiwan_price_map_snapshot_scheduler import produce_taiwan_price_map_snapshots
    from test_tw_price_map_screening import seed, payload, NOW as SNAPSHOT_NOW
    key = "twse_ex_dividend_history"
    events._write_refresh(updates={key: {"entries": [], "coverage_start": date(2022, 1, 1),
        "coverage_end": date(2026, 10, 30), "coverage_years": list(range(2022, 2027))}},
        errors={}, attempted_at=EARLIER)
    with sessions() as db:
        seed(db, 3)
    def build(**kw):
        symbol = kw["stock_id"]
        return {**payload(zones=symbol != "2332", stock_id=symbol), "decision_usable": symbol != "2331"}
    first = produce_taiwan_price_map_snapshots(session_factory=sessions, builder=build, clock=lambda: SNAPSHOT_NOW)
    assert first["publication_status_counts"] == {"ready": 1, "partial": 1, "empty": 1}
    fetch = Mock(return_value=[])
    monkeypatch.setattr(events, "fetch_twse_ex_dividend_history", fetch)
    events.refresh_taiwan_price_basis_events(instrument=INSTRUMENT,
        start_date=date(2026, 10, 19), end_date=date(2026, 10, 29))
    unchanged = produce_taiwan_price_map_snapshots(session_factory=sessions,
        builder=Mock(side_effect=AssertionError("bounded refresh recompute")), clock=lambda: SNAPSHOT_NOW)
    assert unchanged["attempted"] == 0
    assert unchanged["skipped_reason_counts"] == {"current_published": 3}
    events.refresh_taiwan_price_basis_events(instrument=INSTRUMENT,
        start_date=date(2026, 10, 30), end_date=date(2026, 10, 31))
    changed = produce_taiwan_price_map_snapshots(session_factory=sessions, builder=build, clock=lambda: SNAPSHOT_NOW)
    assert changed["published"] == 3
    assert fetch.call_count == 2
