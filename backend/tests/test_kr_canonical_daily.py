"""Gateway, persisted reread, lineage, revisions and history coherence proof."""

from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, KRBarEvidence, KRStockMaster, RawFetchResult
from app.kr_market.daily_acquisition import KRDailyAcquisition
from app.kr_market.daily_ohlcv_platform import KRDailyOhlcvPlatform
from app.kr_market.identity import resolve_kr_instrument_identity
from app.kr_market.bar_transaction import KRBarTransaction


NOW = datetime(2026, 9, 11, 9, tzinfo=timezone.utc)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(KRStockMaster(symbol="005930.KS", local_code="005930",
                                 market_segment="KOSPI", asset_type="stock"))
        session.commit()
        yield session
    engine.dispose()


def yahoo_payload(days, close=100):
    return {"chart": {"result": [{"meta": {"symbol": "005930.KS", "currency": "KRW",
            "exchangeTimezoneName": "Asia/Seoul"},
        "timestamp": [int(datetime(2026, 9, day, 0, tzinfo=timezone.utc).timestamp()) for day in days],
        "indicators": {"quote": [{"open": [99] * len(days), "high": [110] * len(days),
            "low": [90] * len(days), "close": [close] * len(days), "volume": [1000] * len(days)}]}}], "error": None}}


def platform(db, fetcher, now=NOW):
    acquisition = KRDailyAcquisition(resolve_kr_instrument_identity(db, "005930"), fetcher=fetcher, clock=lambda: now)
    return KRDailyOhlcvPlatform(db, acquisition=acquisition)


def test_cold_canonical_read_has_no_fetch_or_write(db):
    with patch.object(db, "commit", side_effect=AssertionError("read wrote")):
        result = KRDailyOhlcvPlatform(db).read(symbol="005930", now=NOW)
    assert not result.postcondition_satisfied
    assert result.projection["freshness_status"] == "missing"
    assert db.query(RawFetchResult).count() == 0


def test_refresh_fallback_persists_rereads_and_is_idempotent(db):
    attempts = []
    def fetch(route, requirement):
        attempts.append(route.provider_key)
        if route.provider_key == "krx_data":
            raise OSError("offline fixture")
        return yahoo_payload([9, 10, 11]), "https://example.invalid/yahoo"
    owner = platform(db, fetch)
    result = owner.refresh(symbol="005930", bars=3, now=NOW, require_history_coverage=True)
    assert result.projection["coverage_status"] == "complete"
    assert not result.postcondition_satisfied
    assert not result.projection["venue_scope_verified"]
    assert attempts == ["krx_data", "yahoo_chart"]
    assert result.projection["selected_provider"] == "yahoo_chart"
    assert result.result.persistence.committed
    assert db.query(KRBarEvidence).count() == 3
    assert all(point["lineage"]["raw_receipt_id"] for point in result.projection["points"])
    assert all(point["lineage"]["cache_hit"] for point in result.projection["points"])
    reread = owner.refresh(symbol="005930", bars=3, now=NOW, require_history_coverage=True)
    assert reread.projection["facts_usable"]
    assert not reread.postcondition_satisfied
    assert attempts == ["krx_data", "yahoo_chart"]
    assert db.query(KRBarEvidence).count() == 3


def test_point_in_time_and_malformed_evidence_do_not_become_current(db):
    # Ensure the fixture is parsed by its actual provider adapter.
    def fetch(route, requirement):
        if route.provider_key == "krx_data":
            raise OSError("no KRX fixture")
        return yahoo_payload([11]), "https://example.invalid/feed"
    owner = platform(db, fetch)
    owner.refresh(symbol="005930", bars=1, now=NOW)
    historical = owner.read(symbol="005930", bars=1, now=NOW.replace(hour=8))
    assert historical.projection["points"] == []
    row = db.query(KRBarEvidence).one()
    row.observation_json = "{}"
    db.commit()
    corrupted = owner.read(symbol="005930", bars=1, now=NOW)
    assert not corrupted.postcondition_satisfied
    assert corrupted.result.candidate_rejections[0].reason_code == "KR_OBSERVATION_HASH_MISMATCH"


def test_persist_failure_does_not_return_acquired_values_as_success(db):
    def fetch(route, requirement):
        if route.provider_key == "krx_data":
            raise OSError("no KRX fixture")
        return yahoo_payload([11]), "https://example.invalid/feed"
    owner = platform(db, fetch)
    with patch.object(db, "commit", side_effect=RuntimeError("fixture commit failure")):
        with pytest.raises(RuntimeError, match="commit failure"):
            owner.refresh(symbol="005930", bars=1, now=NOW)
    assert db.query(KRBarEvidence).count() == 0
    assert db.query(RawFetchResult).count() == 0


def test_future_completed_request_is_rejected(db):
    with pytest.raises(ValueError, match="future"):
        KRDailyOhlcvPlatform(db).read(symbol="005930", now=NOW, to_date=date(2026, 9, 14))


def krx_payload(days):
    return {"OutBlock_1": [{"ISU_SRT_CD": "005930", "MKT_NM": "KOSPI",
        "TRD_DD": f"202609{day:02}", "TDD_OPNPRC": "99", "TDD_HGPRC": "110",
        "TDD_LWPRC": "90", "TDD_CLSPRC": "100", "ACC_TRDVOL": "1000"} for day in days]}


def test_history_never_stitches_incomplete_provider_series(db):
    def fetch(route, requirement):
        return (krx_payload([11]) if route.provider_key == "krx_data" else yahoo_payload([9, 10])), "https://example.invalid/feed"
    result = platform(db, fetch).refresh(symbol="005930", bars=3, now=NOW, require_history_coverage=True)
    assert not result.postcondition_satisfied
    assert result.projection["points"] == []
    assert db.query(KRBarEvidence).count() == 3


def test_history_gap_is_a_coverage_failure_not_freshness_relabel(db):
    def fetch(route, requirement):
        if route.provider_key == "krx_data":
            raise OSError("no KRX fixture")
        return yahoo_payload([8, 10, 11]), "https://example.invalid/feed"
    owner = platform(db, fetch)
    result = owner.refresh(symbol="005930", bars=3, now=NOW, require_history_coverage=True)
    assert not result.postcondition_satisfied
    assert result.projection["points"] == []
    facts = owner.read(symbol="005930", bars=3, now=NOW)
    assert facts.projection["freshness_status"] == "current"
    assert facts.projection["missing_dates"] == ["2026-09-09"]
    assert facts.projection["facts_usable"]
    assert not facts.projection["decision_usable"]


def test_stale_official_candidate_does_not_prevent_current_fallback(db):
    def fetch(route, requirement):
        return (krx_payload([10]) if route.provider_key == "krx_data" else yahoo_payload([11])), "https://example.invalid/feed"
    result = platform(db, fetch).refresh(symbol="005930", bars=1, now=NOW)
    assert result.projection["freshness_status"] == "current"
    assert not result.postcondition_satisfied
    assert result.projection["selected_provider"] == "yahoo_chart"
    assert result.projection["fallback_used"]


def test_reread_cutoff_advances_only_for_this_explicit_acquisition(db):
    fetched_at = NOW.replace(minute=1)
    def fetch(route, requirement):
        if route.provider_key == "krx_data":
            raise OSError("no KRX fixture")
        return yahoo_payload([11]), "https://example.invalid/feed"
    owner = platform(db, fetch, now=fetched_at)
    assert owner.refresh(symbol="005930", bars=1, now=NOW).projection["facts_usable"]
    assert owner.read(symbol="005930", bars=1, now=NOW).projection["points"] == []
    assert owner.read(symbol="005930", bars=1, now=fetched_at).projection["facts_usable"]


def test_dirty_session_is_rejected_before_fetch_and_preserves_pending_work(db):
    master = db.query(KRStockMaster).one()
    master.market_segment = "KOSDAQ"
    with patch.object(db, "rollback", side_effect=AssertionError("unowned rollback")):
        with pytest.raises(ValueError, match="clean session"):
            KRDailyOhlcvPlatform(db).refresh(symbol="005930", now=NOW)
        with pytest.raises(ValueError, match="clean session"):
            KRBarTransaction(db).persist_bar_acquisition(None, None)
    assert master in db.dirty
    assert master.market_segment == "KOSDAQ"


def test_transaction_replay_is_idempotent_and_timezone_normalized(db):
    captured = []
    transaction = KRBarTransaction(db)
    def persist(requirement, acquisition):
        captured.append((requirement, acquisition))
        return transaction.persist_bar_acquisition(requirement, acquisition)
    def fetch(route, requirement):
        if route.provider_key == "krx_data":
            raise OSError("no KRX fixture")
        return yahoo_payload([11]), "https://example.invalid/feed"
    from zoneinfo import ZoneInfo
    owner = platform(db, fetch, now=NOW.astimezone(ZoneInfo("Asia/Seoul")))
    with patch.object(owner.transaction, "persist_bar_acquisition", side_effect=persist):
        assert owner.refresh(symbol="005930", bars=1, now=NOW).projection["facts_usable"]
    replay = transaction.persist_bar_acquisition(*captured[0])
    assert replay.observations_unchanged == 1
    assert replay.observations_written == replay.receipts_written == 0
    assert db.query(RawFetchResult).one().fetched_at == NOW.replace(tzinfo=None)


def test_revision_does_not_change_earlier_point_in_time_read(db):
    def fetch(route, requirement):
        if route.provider_key == "krx_data":
            raise OSError("no KRX fixture")
        return yahoo_payload([11]), "https://example.invalid/feed"
    platform(db, fetch).refresh(symbol="005930", bars=1, now=NOW)
    later = NOW.replace(minute=5)
    def revised_fetch(route, requirement):
        if route.provider_key == "krx_data":
            raise OSError("no KRX fixture")
        return yahoo_payload([10, 11], close=105), "https://example.invalid/feed"
    owner = platform(db, revised_fetch, now=later)
    owner.refresh(symbol="005930", bars=2, now=later, require_history_coverage=True)
    assert owner.read(symbol="005930", bars=1, now=NOW).projection["points"][0]["close"] == 100
    assert owner.read(symbol="005930", bars=1, now=later).projection["points"][0]["close"] == 105


def test_missing_schema_blocks_refresh_before_provider_call(db):
    KRBarEvidence.__table__.drop(db.get_bind())
    assert "KR_CANONICAL_SCHEMA_NOT_ADOPTED" in KRDailyOhlcvPlatform(db).read(symbol="005930", now=NOW).projection["limitations"]
    with pytest.raises(ValueError, match="schema is not adopted"):
        KRDailyOhlcvPlatform(db).refresh(symbol="005930", now=NOW)


def test_yahoo_historical_request_uses_absolute_bounds(monkeypatch):
    from app.kr_market.providers import yahoo
    calls = []
    class Response:
        url = "https://example.invalid/feed"
        def json(self):
            return yahoo_payload([11])
    monkeypatch.setattr(yahoo, "provider_get", lambda *args, **kwargs: (calls.append(kwargs) or Response()))
    start = NOW.replace(day=1)
    yahoo.fetch_yahoo_chart_payload(symbol="005930.KS", range_value="1mo", interval="1d",
        timeout_seconds=5, start_at=start, end_at=NOW)
    assert calls[0]["params"]["period1"] == int(start.timestamp())
    assert calls[0]["params"]["period2"] == int(NOW.timestamp())
    assert "range" not in calls[0]["params"]


def test_additive_migration_preserves_legacy_rows_and_downgrades(db):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20260912_0086_kr_bar_evidence.py"
    spec = importlib.util.spec_from_file_location("kr_evidence_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    KRBarEvidence.__table__.drop(db.get_bind())
    with db.get_bind().begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()  # Fresh baseline metadata may already contain the table.
            assert inspect(connection).has_table("kr_bar_evidence")
            migration.downgrade()
            assert not inspect(connection).has_table("kr_bar_evidence")
            migration.upgrade()
    assert db.query(KRStockMaster).one().symbol == "005930.KS"
    assert db.query(KRBarEvidence).count() == 0


def test_shadow_compares_same_payload_and_rejects_missing_or_mixed_inputs(db):
    from app.kr_market.daily_shadow import compare_daily_result
    from app.kr_market.sources import parse_yahoo_daily_prices
    payload = yahoo_payload([10, 11])
    def fetch(route, requirement):
        if route.provider_key == "krx_data":
            raise OSError("no KRX fixture")
        return payload, "https://example.invalid/feed"
    resolved = platform(db, fetch).refresh(symbol="005930", bars=2, now=NOW)
    legacy = parse_yahoo_daily_prices(payload, symbol="005930.KS", source_url="https://example.invalid/feed")
    with patch.object(db, "commit", side_effect=AssertionError("shadow wrote")):
        assert compare_daily_result(resolved, legacy_records=legacy)["matched"]
        assert not compare_daily_result(resolved, legacy_records=[])["matched"]
        assert not compare_daily_result(resolved, legacy_records=legacy[:1])["matched"]
        assert not compare_daily_result(resolved, legacy_records=[*legacy, legacy[0]])["matched"]


def test_conflicting_same_receipt_bars_are_rejected_instead_of_last_row_wins(db):
    payload = yahoo_payload([11, 11])
    payload["chart"]["result"][0]["indicators"]["quote"][0]["close"][1] = 105
    def fetch(route, requirement):
        if route.provider_key == "krx_data":
            raise OSError("no KRX fixture")
        return payload, "https://example.invalid/feed"
    result = platform(db, fetch).refresh(symbol="005930", bars=1, now=NOW)
    assert not result.postcondition_satisfied
    assert "KR_PROVIDER_DUPLICATE_BAR_CONFLICT" in result.projection["limitations"]
    assert db.query(KRBarEvidence).count() == 0


def test_canonical_read_does_not_flush_caller_pending_changes(db):
    master = db.query(KRStockMaster).one()
    master.security_name = "Pending edit"
    with patch.object(db, "flush", side_effect=AssertionError("read flushed")):
        KRDailyOhlcvPlatform(db).read(symbol="005930", now=NOW)
    assert master in db.dirty


def test_canonical_consumer_and_public_ask_parity_preserve_lineage_and_limits(db, monkeypatch):
    from app.config import settings
    from app.kr_market import service
    from app.kr_market.daily_projection import read_chart
    from app.kr_market.valuation import read_kr_valuation_price
    from app.ai import ask as ai_ask
    from app.ai.schemas import AiAskRequest
    from app.ai import agentic_tools
    monkeypatch.setattr(settings, "kr_canonical_daily_enabled", True)
    monkeypatch.setattr(agentic_tools, "_now", lambda: NOW)
    def fetch(route, requirement):
        if route.provider_key == "krx_data":
            raise OSError("no KRX fixture")
        return yahoo_payload([9, 10, 11]), "https://example.invalid/feed"
    platform(db, fetch).refresh(symbol="005930", bars=3, now=NOW)
    with patch.object(db, "commit", side_effect=AssertionError("consumer wrote")):
        chart = read_chart(db, symbol="005930", bars=3, now=NOW)
        rows = service.list_kr_daily_prices(db, symbol="005930", limit=3)
        assert chart["points"][-1]["close"] == rows[0].close_price == 100
        assert rows[0].evidence_id == chart["points"][-1]["lineage"]["observation_id"]
        value = read_kr_valuation_price(db, symbol="005930", requested_at=NOW.replace(hour=8))
        assert value.price is None
        result = ai_ask.ask(db=db, payload=AiAskRequest(contract_version="omi.decision.v4",
            question="Read saved Korea daily evidence", target={"type": "kr_stock", "id": "005930.KS"},
            mode="data_only", realtime_policy="cache_only", selection={"required": ["daily.ohlcv"]},
            market_data_params={"bars": 3}, refresh_policy={"mode": "off", "before_answer": False}),
            server_policy=ai_ask.AiAskServerPolicy())
    assert result["contract_version"] == "omi.decision.v4"
    outward = result["evidence"]["data"]["daily.ohlcv"]
    assert outward["points"][-1]["close"] == 100
    assert not outward["decision_usable"]
    assert "KR_PROVIDER_VENUE_COVERAGE_UNVERIFIED" in outward["limitations"]
    assert result["execution"]["refresh_reconciliation"]["provider_fetch_attempted"] is False
    assert outward["points"][-1]["lineage"]["raw_receipt_id"] == rows[0].raw_receipt_id

    # Exercise the real MCP argument adapter and JSON-RPC serialization while
    # substituting only the transport with the same in-process backend owner.
    import importlib.util
    import json
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / "agents/omi_mcp_server/server.py"
    spec = importlib.util.spec_from_file_location("kr_mcp_parity", path)
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)
    def post(path, params=None, payload=None):
        assert path == "/api/ai/ask"
        assert payload["allow_external_fetch"] is False
        return ai_ask.ask(db=db, payload=AiAskRequest.model_validate(payload), server_policy=ai_ask.AiAskServerPolicy())
    monkeypatch.setattr(server, "_api_post", post)
    with patch.object(db, "commit", side_effect=AssertionError("MCP read wrote")):
        response = server._handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "omi.ask", "arguments": {"question": "Read saved Korea daily evidence",
                "target": {"type": "kr_stock", "id": "005930.KS"}, "mode": "data_only",
                "realtime_policy": "cache_only", "refresh_if_missing": False,
                "market_data_params": {"bars": 3}, "selection": {"required": ["daily.ohlcv"]}}}})
    assert response["result"]["isError"] is False
    envelope = json.loads(response["result"]["content"][0]["text"])
    assert envelope["evidence"]["data"]["daily.ohlcv"] == outward


def test_weekly_aggregation_keeps_missing_volume_unknown():
    from types import SimpleNamespace
    from app.kr_market.chart_projection import aggregate_daily_rows
    rows = [SimpleNamespace(trade_date=date(2026, 9, day), open_price=1, high_price=2,
        low_price=1, close_price=2, adjusted_close=None, trade_volume=volume)
        for day, volume in [(9, 100), (10, None)]]
    assert aggregate_daily_rows(rows, "weekly")[0]["volume"] is None


def test_chart_history_command_fills_history_even_when_latest_day_is_cached(db, monkeypatch):
    from app.kr_market import daily_projection
    attempts = []
    def fetch(route, requirement):
        attempts.append(route.provider_key)
        if route.provider_key == "krx_data":
            raise OSError("no KRX fixture")
        return yahoo_payload([9, 10, 11]), "https://example.invalid/feed"
    owner = platform(db, fetch)
    owner.refresh(symbol="005930", bars=1, now=NOW)
    monkeypatch.setattr(daily_projection, "KRDailyOhlcvPlatform", lambda db: owner)
    chart = daily_projection.read_chart(db, symbol="005930", bars=3, now=NOW, acquire=True)
    assert chart["point_count"] == 3
    assert chart["resolved_evidence"]["coverage_status"] == "complete"
    assert len(attempts) == 4


def test_partial_history_keeps_newly_persisted_facts_without_second_acquisition(db, monkeypatch):
    from app.kr_market import daily_projection
    calls = []
    def fetch(route, requirement):
        calls.append(route.provider_key)
        if route.provider_key == "krx_data":
            raise OSError("no KRX fixture")
        return yahoo_payload([11]), "https://example.invalid/feed"
    owner = platform(db, fetch, now=NOW.replace(minute=1))
    monkeypatch.setattr(daily_projection, "KRDailyOhlcvPlatform", lambda db: owner)
    chart = daily_projection.read_chart(db, symbol="005930", bars=3, now=NOW, acquire=True)
    assert chart["point_count"] == 1
    assert chart["resolved_evidence"]["coverage_status"] == "partial"
    assert chart["resolved_evidence"]["facts_usable"]
    assert not chart["resolved_evidence"]["decision_usable"]
    assert "KR_HISTORY_COVERAGE_UNMET" in chart["resolved_evidence"]["limitations"]
    assert chart["backfill"]["observations_inserted"] == 1
    assert calls == ["krx_data", "yahoo_chart"]
    assert owner.read(symbol="005930", bars=1, now=NOW).projection["points"] == []
