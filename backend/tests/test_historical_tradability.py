from datetime import date, datetime, timezone
from hashlib import sha256
from unittest.mock import Mock

import pytest
from sqlalchemy import text

from app.market import tw_corporate_events as events
from app.market.providers import tw_trading_status as adapter
from app.market_data.contracts import InstrumentKey
from app.market.tw_bar_service import TaiwanBarService
from test_tw_daily_candidate_repository import db, _source_and_raw, _daily_row

INSTRUMENT = InstrumentKey(market="TW", venue="TWSE", symbol="2330", instrument_type="stock")
FETCHED = datetime(2026, 8, 25, tzinfo=timezone.utc)
NOTICE = "Example (code: 2330). Capital reduction. Trading of the old stocks will be suspended during the period of August 20, 2026 to August 20, 2026. The new shares will be listed and available for exchange on August 21, 2026."
URL = adapter.TWSE_ANNOUNCEMENTS_URL


def batch(text=NOTICE):
    digest = sha256(text.encode()).hexdigest()
    receipt_id = "receipt:" + digest
    entries, limits = adapter.parse_twse_instrument_announcements(text=text, url=URL,
        instrument=INSTRUMENT, fetched_at=FETCHED, receipt_id=receipt_id)
    return {"status": "success", "entries": entries, "evidence_windows": [], "request_count": 1,
        "limitations": limits, "raw_receipts": [{"receipt_id": receipt_id, "content_hash": digest,
        "url": URL, "raw_text": text, "fetched_at": FETCHED.isoformat()}]}


def test_official_acquisition_cache_and_query_only_bar_adoption(db, tmp_path, monkeypatch):
    from app.config import settings
    from app.db.models import StockMaster
    from app.sources.defaults import TWSE_DAILY_TRADING_SOURCE_NAME
    monkeypatch.setattr(settings, "tw_corporate_event_cache_path", tmp_path / "corporate.json")
    monkeypatch.setattr(adapter, "fetch_taiwan_instrument_events", Mock(return_value=batch()))
    source, raw = _source_and_raw(db, source_name=TWSE_DAILY_TRADING_SOURCE_NAME,
        parser_type="twse_daily_trading", priority=1)
    raw.fetched_at = datetime(2026, 8, 24, tzinfo=timezone.utc)
    raw.status_code = 200
    db.add(StockMaster(stock_id="2330", market="TWSE", stock_name="fixture", instrument_type="stock"))
    db.add_all([_daily_row(source=source, raw=raw, trade_date=date(2026, 8, 19)),
                _daily_row(source=source, raw=raw, trade_date=date(2026, 8, 21))])
    db.commit()
    kwargs = dict(instrument=INSTRUMENT, start_date=date(2026, 8, 19), end_date=date(2026, 8, 21))
    events.refresh_taiwan_instrument_event_history(**kwargs)
    revision = events.taiwan_corporate_event_revision()
    events.refresh_taiwan_instrument_event_history(**kwargs)
    cache = events.read_taiwan_corporate_event_cache()
    assert len(cache["providers"]["twse_instrument_history"]["entries"]) == 3
    assert sorted(path.name for path in tmp_path.glob("*.json")) == ["corporate.json"]
    db.execute(text("PRAGMA query_only=ON"))
    query = dict(instrument_id="2330", interval="1d", from_time=datetime(2026, 8, 19, tzinfo=timezone.utc),
        to_time=datetime(2026, 8, 22, tzinfo=timezone.utc), limit=50)
    old = TaiwanBarService(db).read_bars(**query, requested_at=datetime(2026, 8, 24, 12, tzinfo=timezone.utc))
    current = TaiwanBarService(db).read_bars(**query, requested_at=datetime(2026, 8, 26, tzinfo=timezone.utc))
    assert not old.nontrading_dates and not old.history.requested_coverage_satisfied
    assert current.nontrading_dates == (date(2026, 8, 20),)
    assert current.history.requested_coverage_satisfied
    assert old.identity.series_revision != current.identity.series_revision
    assert all(not bar.derivation_kind for bar in current.bars)
    assert db.execute(text("PRAGMA query_only")).scalar() == 1


def test_unknown_or_tampered_event_evidence_never_establishes_status(tmp_path):
    import json
    target = tmp_path / "corporate.json"
    assert not events.read_taiwan_instrument_event_evidence(instrument=INSTRUMENT,
        available_at=FETCHED, path=target)["events"]
    value = batch()
    value["raw_receipts"][0]["raw_text"] += "tampered"
    target.write_text(json.dumps({"schema_version": 1, "providers": {"twse_instrument_history": {
        "market": "TWSE", **value}}}), encoding="utf-8")
    evidence = events.read_taiwan_instrument_event_evidence(instrument=INSTRUMENT, available_at=FETCHED, path=target)
    assert not evidence["events"] and evidence["limitations"]


@pytest.mark.parametrize("text", [NOTICE.replace("2330", "9999"),
    NOTICE + " correction", "Example (code: 2330) margin purchases suspended."])
def test_notice_parser_does_not_guess(text):
    assert batch(text)["entries"] == []


def test_event_coverage_required_for_unchanged_price_basis():
    empty = {"events": (), "windows": (), "limitations": ()}
    kwargs = dict(prior_date=date(2026, 8, 19), trade_date=date(2026, 8, 20))
    assert events.resolve_taiwan_price_basis(empty, **kwargs).status == "unknown"
    from app.market_data.contracts import SourceLineage
    lineage = SourceLineage.model_validate(batch()["entries"][0]["lineage"])
    window = {"start_date": date(2026, 8, 1), "end_date": date(2026, 8, 31),
        "complete": True, "event_types": ["ex_dividend", "capital_reduction", "price_basis_change"], "lineage": lineage}
    complete = {**empty, "windows": (window,)}
    assert events.resolve_taiwan_price_basis(complete, **kwargs).status == "unchanged"
    changed = {**complete, "events": ({"event_type": "capital_reduction", "start_date": date(2026, 8, 20), "lineage": lineage},)}
    assert events.resolve_taiwan_price_basis(changed, **kwargs).status == "changed"
    assert events.resolve_taiwan_price_basis({**empty, "windows": ({**window, "event_types": ["ex_dividend"]},)}, **kwargs).status == "unknown"


def test_existing_event_consumers_do_not_inherit_instrument_cache_health(tmp_path):
    result = events.list_taiwan_corporate_events(date_from=date(2026, 8, 1),
        date_to=date(2026, 9, 1), now=FETCHED, cache_path=tmp_path / "empty.json")
    assert not any(key.endswith("_instrument_history") for key in result["sources"])


def test_acquisition_failure_retains_cache_and_precise_blocker(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "fetch_taiwan_instrument_events", Mock(return_value=batch()))
    kwargs = dict(instrument=INSTRUMENT, start_date=date(2026, 8, 19), end_date=date(2026, 8, 21), cache_path=tmp_path / "events.json")
    events.refresh_taiwan_instrument_event_history(**kwargs)
    monkeypatch.setattr(adapter, "fetch_taiwan_instrument_events", Mock(side_effect=TimeoutError()))
    result = events.refresh_taiwan_instrument_event_history(**kwargs)
    assert result["reason"] == "OFFICIAL_INSTRUMENT_HISTORY_ACQUISITION_FAILED"
    evidence = events.read_taiwan_instrument_event_evidence(instrument=INSTRUMENT, available_at=FETCHED, path=kwargs["cache_path"])
    assert len(evidence["events"]) == 3
