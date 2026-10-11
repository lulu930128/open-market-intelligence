"""G-A source evidence only: synthetic payloads and isolated in-memory stores."""

from datetime import datetime, timezone
import json

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db.models import Base, USStockMaster, USQuoteSnapshot
from app.us_market import intraday_materializer as materializer
from app.us_market.intraday_acquisition import USIntradayAcquisitionExecutor
from app.us_market.intraday_platform import USIntradayMarketPlatform
from app.us_market.market_data.descriptors import YAHOO_QUOTE_DESCRIPTOR, YAHOO_QUOTE_RESOURCE_ID
from app.us_market.market_truth import read_us_market_truth_snapshot
from test_us_intraday_materializer import _yahoo_quote_payload


NOW = datetime(2026, 10, 9, 15, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def isolated_diagnostics(monkeypatch):
    monkeypatch.setattr(materializer, "_LAST_RUNS", {})
    monkeypatch.setattr(materializer, "_RUN_COUNTERS", {})


def test_symbol_diagnostics_are_bounded_sanitized_and_detached():
    result = {
        "lane_id": "equity_active", "status": "failed", "results": [
            None, {"symbol": "https://secret.invalid/?token=secret"},
            {"symbol": "AMD", "status": "failed", "reason": "refresh_postcondition_unsatisfied",
             "postcondition_reasons": ["REQUIRED_EVIDENCE_MISSING", "SECRET_TOKEN",
                                       "REQUIRED_EVIDENCE_MISSING", {"token": "secret"}],
             "resolved_status": "missing", "acquisition_attempted": True,
             "persistence_committed": False, "external_calls": 1,
             "selected_provider": "yahoo_chart", "raw": {"token": "secret"},
             "exception_message": "secret", "url": "https://secret.invalid",
             "account": "secret", "error_type": "SECRET_TOKEN"},
            {"symbol": "AMD", "status": "success"},
            {"symbol": "SSO", "status": {"token": "secret"}, "reason": "SECRET_TOKEN",
             "resolved_status": "SECRET_TOKEN", "selected_provider": "SECRET_TOKEN",
             "external_calls": True, "acquisition_attempted": "true",
             "persistence_committed": 1, "postcondition_reasons": "SECRET_TOKEN"},
            {"symbol": "TSM", "status": "success"},
        ],
    }
    materializer._record_last_run("quote.snapshot", result)
    result["results"][2]["postcondition_reasons"].append("REQUIRED_FACTS_UNUSABLE")
    summary = materializer.us_intraday_materializer_runtime_summary()
    items = summary["runs_by_lane"]["equity_active"]["quote.snapshot"]["symbol_runs"]
    assert items == [
        {"symbol": "AMD", "status": "failed", "reason": "refresh_postcondition_unsatisfied",
         "postcondition_reason_codes": ["REQUIRED_EVIDENCE_MISSING"], "resolved_status": "missing",
         "attempted": True, "persisted": False, "external_calls": 1, "provider": "yahoo_chart"},
        {"symbol": "SSO"},
    ]
    assert "secret" not in json.dumps(summary).lower()
    items[0]["symbol"] = "MUTATED"
    summary["last_quote_run"]["symbol_runs"][0]["postcondition_reason_codes"].clear()
    stored = materializer.us_intraday_materializer_runtime_summary()["last_quote_run"]["symbol_runs"]
    assert stored[0]["symbol"] == "AMD"
    assert stored[0]["postcondition_reason_codes"] == ["REQUIRED_EVIDENCE_MISSING"]


@pytest.mark.parametrize("value", [None, "raw secret", {"raw": "secret"}, [1, [], {}]])
def test_invalid_diagnostic_shapes_do_not_escape(value):
    assert materializer._symbol_run_diagnostics(value) == []


@pytest.mark.parametrize("reason,stage", [
    ("post_acquisition_exception", "post_acquisition"),
    ("pre_acquisition_exception", "pre_acquisition_or_acquisition"),
])
@pytest.mark.parametrize("error_type", ["OperationalError", "TimeoutError", "ValidationError", "SECRET_TOKEN"])
def test_failure_classification_discloses_only_fixed_identifiers(reason, stage, error_type):
    result = materializer._symbol_run_diagnostics([{
        "symbol": "AMD", "status": "failed", "reason": reason, "error_type": error_type,
        "failure_stage": "SECRET_TOKEN", "message": "https://secret.invalid?token=secret",
        "exception": RuntimeError("secret"), "raw": {"account": "secret"},
    }])[0]
    assert result["failure_stage"] == stage
    if error_type == "SECRET_TOKEN":
        assert "error_type" not in result
    else:
        assert result["error_type"] == error_type
    assert "secret" not in json.dumps(result).lower()


def test_health_get_uses_memory_without_sql_or_provider(monkeypatch):
    from app.routers import system
    from sqlalchemy.engine import Engine

    materializer._record_last_run("quote.snapshot", {
        "lane_id": "equity_active", "status": "failed",
        "results": [{"symbol": "AMD", "status": "failed",
                     "reason": "pre_acquisition_exception", "external_calls": 0}],
    })

    def forbidden(*args, **kwargs):
        pytest.fail("Health GET attempted DB/provider IO")

    monkeypatch.setattr(Engine, "connect", forbidden)
    monkeypatch.setattr(materializer, "SessionLocal", forbidden)
    monkeypatch.setattr(USIntradayAcquisitionExecutor, "_fetch", forbidden)
    monkeypatch.setattr(USIntradayMarketPlatform, "refresh_quote", forbidden)
    monkeypatch.setattr(USIntradayMarketPlatform, "refresh_intraday_bars", forbidden)
    # Invoke the registered synchronous GET endpoint: no server lifecycle,
    # TestClient dependency, or Windows asyncio socketpair under offline guard.
    route = next(route for route in system.router.routes if route.path == "/health")
    assert route.methods == {"GET"}
    payload = route.endpoint()
    assert '"symbol": "AMD"' in json.dumps(payload)
    assert '"reason": "pre_acquisition_exception"' in json.dumps(payload)


@pytest.mark.parametrize("outcome", ["success", "malformed", "exception", "persist_failure"])
def test_amd_quote_real_source_pipeline_and_health(outcome, monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    calls = []
    with Session(engine) as db:
        db.add(USStockMaster(symbol="AMD", security_name="Synthetic AMD", exchange="NASDAQ",
                             asset_type="stock", is_etf=False))
        db.commit()

    def fetch(route, requirement):
        calls.append((route.resource_id, requirement.target.instrument.symbol))
        if outcome == "exception":
            raise RuntimeError("secret diagnostic must never escape")
        payload = {} if outcome == "malformed" else _yahoo_quote_payload(NOW, symbol="AMD")
        return payload, "https://fixture.invalid/AMD?token=synthetic-secret"

    def platform_factory(db):
        return USIntradayMarketPlatform(
            db, acquisition=USIntradayAcquisitionExecutor(
                fetchers={YAHOO_QUOTE_RESOURCE_ID: fetch}, clock=lambda: NOW),
            quote_descriptors=(YAHOO_QUOTE_DESCRIPTOR,),
        )

    def fail_snapshot_insert(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith(f"INSERT INTO {USQuoteSnapshot.__tablename__} "):
            raise OperationalError("synthetic insert", {}, RuntimeError("secret persistence error"))

    if outcome == "persist_failure":
        event.listen(engine, "before_cursor_execute", fail_snapshot_insert)
    try:
        result = materializer.materialize_us_intraday_capability(
            "quote.snapshot", configured_symbols="AMD", lane_id="equity_active", now=NOW,
            max_provider_calls=1, max_external_calls=1,
            session_factory=lambda: Session(engine), platform_factory=platform_factory,
        )
        diagnostic = materializer.us_intraday_materializer_runtime_summary()["last_quote_run"]["symbol_runs"][0]
        assert diagnostic["symbol"] == "AMD"
        assert diagnostic["external_calls"] == 1
        assert calls == [(YAHOO_QUOTE_RESOURCE_ID, "AMD")]
        assert "secret" not in json.dumps(diagnostic).lower()
        assert "raw" not in diagnostic
        if outcome == "success":
            assert result["status"] == "success"
            assert diagnostic["attempted"] is True and diagnostic["persisted"] is True
            assert diagnostic["provider"] == "yahoo_chart"
            assert diagnostic["postcondition_reason_codes"] == []
            with Session(engine) as db:
                row = db.query(USQuoteSnapshot).one()
                assert row.symbol == "AMD" and row.raw_result_id is not None
                read = platform_factory(db).read_quote(symbol="AMD", now=NOW)
                assert read.result.resolved.quote.lineage.cache_hit is True
                assert read.result.resolved.quote.lineage.fetched_at == NOW
                truth = read_us_market_truth_snapshot(db, symbol="AMD", evaluated_at=NOW)
                assert truth.quote_observation is not None
                assert truth.quote_observation.selected_provider == "yahoo_chart"
                assert truth.quote_observation.fetched_at == NOW
            # A second recurring run must explain its cache noop, without fetch.
            materializer.materialize_us_intraday_capability(
                "quote.snapshot", configured_symbols="AMD", lane_id="equity_active", now=NOW,
                max_provider_calls=1, max_external_calls=1,
                session_factory=lambda: Session(engine), platform_factory=platform_factory,
            )
            cached = materializer.us_intraday_materializer_runtime_summary()["last_quote_run"]["symbol_runs"][0]
            assert cached["reason"] == "canonical_cache_already_satisfied"
            assert cached["attempted"] is False and cached["persisted"] is False
            assert cached["external_calls"] == 0 and len(calls) == 1
        else:
            assert result["status"] == "failed"
            if outcome == "persist_failure":
                assert diagnostic["reason"] == "post_acquisition_exception"
                assert diagnostic["error_type"] == "OperationalError"
                assert diagnostic["failure_stage"] == "post_acquisition"
                assert diagnostic["attempted"] is True
                assert "persisted" not in diagnostic  # No persistence result was returned.
            else:
                assert diagnostic["reason"] == "refresh_postcondition_unsatisfied"
                assert "REQUIRED_EVIDENCE_MISSING" in diagnostic["postcondition_reason_codes"]
            with Session(engine) as db:
                assert db.query(USQuoteSnapshot).count() == 0
    finally:
        engine.dispose()


def test_caught_timeout_is_safe_and_capability_runs_stay_separate():
    class FakeDb:
        def rollback(self):
            pass

        def close(self):
            pass

    class Platform:
        def read_quote(self, **kwargs):
            raise LookupError("synthetic cache miss")

        def refresh_quote(self, **kwargs):
            raise TimeoutError("secret token=https://fixture.invalid/private")

    materializer.materialize_us_intraday_capability(
        "quote.snapshot", configured_symbols="AMD", lane_id="equity_active", now=NOW,
        max_provider_calls=1, max_external_calls=1,
        session_factory=FakeDb, platform_factory=lambda db: Platform(),
    )
    materializer._record_last_run("intraday.bars", {
        "lane_id": "equity_active", "status": "success", "results": [
            {"symbol": "SSO", "status": "success", "external_calls": 0},
        ],
    })
    runs = materializer.us_intraday_materializer_runtime_summary()["runs_by_lane"]["equity_active"]
    quote = runs["quote.snapshot"]["symbol_runs"][0]
    assert quote["error_type"] == "TimeoutError"
    assert quote["failure_stage"] == "pre_acquisition_or_acquisition"
    assert "attempted" not in quote and "persisted" not in quote
    assert "secret" not in json.dumps(runs).lower()
    assert runs["intraday.bars"]["symbol_runs"][0]["symbol"] == "SSO"
