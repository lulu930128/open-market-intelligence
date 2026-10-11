"""Sanitized SYNTHETIC exports, public production schemas, no connector or live IO."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from app.market_data.contracts import EvidenceFreshness, ResolvedEvidenceStatus
from app.us_market.market_truth import read_us_historical_intraday_trend, read_us_market_truth_bundle
from test_us_market_truth_snapshot import _bar, _fake_components, _install_fake_components

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify-us-preopen-acceptance.py"
spec = importlib.util.spec_from_file_location("us_gd_verifier", SCRIPT)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)
UTC = timezone.utc


@pytest.fixture
def exports(monkeypatch):
    quote, intraday, daily = _fake_components()
    start = datetime(2026, 8, 31, 13, 30, tzinfo=UTC)
    event = datetime(2026, 8, 28, 19, 59, tzinfo=UTC)
    bars = tuple(_bar(observation_id=f"gd-{i}", start_at=start + timedelta(minutes=i),
                      end_at=start + timedelta(minutes=i + 1), close="200") for i in range(390))
    quote = quote.model_copy(update={
        "quote": quote.quote.model_copy(update={"trade_date": event.date(),
            "lineage": quote.quote.lineage.model_copy(update={"event_at": event, "fetched_at": event + timedelta(seconds=2)})}),
        "health": quote.health.model_copy(update={"status": ResolvedEvidenceStatus.STALE, "selected_event_at": event, "research_usable": False}),
        "candidates": tuple(c.model_copy(update={"freshness": EvidenceFreshness.STALE, "event_at": event}) for c in quote.candidates),
    })
    intraday = intraday.model_copy(update={"bars": bars})
    _install_fake_components(monkeypatch, (quote, intraday, daily))
    now = datetime(2026, 9, 1, 1, tzinfo=UTC)
    bundle = read_us_market_truth_bundle(object(), symbol="AAPL", evaluated_at=now, requested_scope="regular")
    trend = read_us_historical_intraday_trend(object(), symbol="AAPL", trade_date=date(2026, 8, 31), evaluated_at=now)
    backend = {"schema": verifier.VERSION, "surface": "backend", "mode": "fixture",
        "captured_at": now.isoformat(),
        "identity": {"symbol": "AAPL", "trade_date": "2026-08-31", "session_scope": "regular", "interval": "1m"},
        "payload": {"truth": bundle.snapshot.model_dump(mode="json"),
                    "series": bundle.series.model_dump(mode="json"), "trend": trend}}
    # This mapping is a SYNTHETIC test of exports, not a claimed actual MCP schema.
    result = {"backend": backend}
    for surface in ("mcp", "frontend"):
        result[surface] = {**deepcopy(backend), "surface": surface,
                           "mapping": dict(verifier.PATHS), "observed_fields": list(verifier.PATHS)}
    return result


def test_consistent_fixture_is_not_live_or_runtime_pass(exports):
    result = verifier.compare(exports)
    assert result["errors"] == {}
    assert result["overall"] == "PARTIAL"
    assert result["gates"]["Source"]["status"] == "UNVERIFIED"
    assert result["backend_schema_validation"] == "PASS"
    assert result["gates"]["Runtime"]["status"] == "UNVERIFIED"
    assert result["gates"]["MCP"]["status"] == "UNVERIFIED"
    for surface in ("mcp", "frontend"):
        checks = result["comparisons"][surface]
        assert checks["point_count"]["status"] == "PASS"
        assert checks["quote_freshness"]["status"] == "PASS"
        assert checks["bars_fetched_at"]["status"] == "UNVERIFIED"
    assert result["live_gate"] == result["product_gate"] == "UNVERIFIED"


def test_backend_only_and_no_input_never_pass(exports):
    result = verifier.compare({"backend": exports["backend"]})
    assert result["overall"] == "PARTIAL"
    assert result["gates"]["MCP"]["status"] == result["gates"]["Frontend"]["status"] == "UNVERIFIED"
    assert verifier.compare({})["overall"] == "UNVERIFIED"
    assert verifier.compare({"mcp": exports["mcp"]})["overall"] == "UNVERIFIED"


def test_stale_quote_is_independent_of_complete_bars(exports):
    result = verifier.compare(exports)
    assert result["quality"]["quote_freshness"]["reported_value"] == "stale"
    assert result["quality"]["coverage_status"]["reported_value"] == "complete"
    assert result["quality"]["decision_usable"]["reported_value"] is False
    assert result["comparisons"]["mcp"]["quote_source"]["evidence_path"] == "/truth/quote_observation/selected_source"


@pytest.mark.parametrize("key,path,value", [
    ("point_count", ("series", "observed_interval_count"), 378),
    ("quote_date", ("truth", "quote_observation", "trade_date"), "2026-08-31"),
    ("quote_source", ("truth", "quote_observation", "selected_source"), "yahoo.chart.1m"),
    ("quote_freshness", ("truth", "quote_observation", "freshness"), "fresh"),
    ("decision_usable", ("trend", "decision_usable"), True),
    ("bars_limitations", ("truth", "health", "intraday", "resolved_health", "limitations"), ["PARTIAL_US_MARKET_VOLUME"]),
])
def test_cross_surface_mismatch_blocked(exports, key, path, value):
    target = exports["mcp"]["payload"]
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    result = verifier.compare(exports)
    assert result["overall"] == "BLOCKED"
    assert result["gates"]["MCP"]["status"] == "BLOCKED"


def test_mapping_does_not_invent_unobserved_fields(exports):
    exports["mcp"]["observed_fields"].remove("quote_source")
    result = verifier.compare(exports)
    assert result["comparisons"]["mcp"]["quote_source"]["status"] == "UNVERIFIED"
    del exports["mcp"]["payload"]["truth"]["quote_observation"]["fetched_at"]
    result = verifier.compare(exports)
    assert result["comparisons"]["mcp"]["quote_fetched_at"]["status"] == "UNVERIFIED"


def test_explicit_null_is_not_zero_or_missing(exports):
    assert exports["backend"]["payload"]["trend"]["points"][0]["volume"] is None
    result = verifier.compare(exports)
    assert result["comparisons"]["mcp"]["volume"]["reason"] == "both_explicit_null"
    exports["mcp"]["payload"]["trend"]["points"][0]["volume"] = 0
    assert verifier.compare(exports)["comparisons"]["mcp"]["volume"]["status"] == "BLOCKED"
    for document in exports.values():
        document["payload"]["trend"]["points"][0]["volume"] = 0
    assert verifier.compare(exports)["comparisons"]["mcp"]["volume"]["status"] == "PASS"


@pytest.mark.parametrize("field,value", [("captured_at", "2026-10-10"), ("captured_at", "2026-10-10T10:00:00"),
    ("captured_at", "2026-02-30T10:00:00Z"), ("surface", "MCP"), ("mode", "live"), ("schema", "v0")])
def test_bad_metadata_is_blocked(exports, field, value):
    exports["backend"][field] = value
    result = verifier.compare(exports)
    assert result["overall"] == "BLOCKED"
    assert result["gates"]["Source"]["status"] == "BLOCKED"


@pytest.mark.parametrize("value", ["20261009", "2026-02-30", "2026-10-09T00:00:00Z", None, 0])
def test_bad_date_is_blocked(exports, value):
    exports["backend"]["identity"]["trade_date"] = value
    assert verifier.compare(exports)["overall"] == "BLOCKED"


@pytest.mark.parametrize("mutation", ["schema", "revision", "identity", "time", "receipt", "count", "mapping", "boolean"])
def test_schema_and_semantic_errors_fail_closed(exports, mutation):
    doc = exports["backend"]
    if mutation == "schema":
        del doc["payload"]["truth"]["health"]
    elif mutation == "revision":
        doc["payload"]["series"]["truth_revision"] = "f" * 64
    elif mutation == "identity":
        exports["mcp"]["identity"]["symbol"] = "SSO"
    elif mutation == "time":
        doc["payload"]["truth"]["quote_observation"]["event_at"] = "bad"
    elif mutation == "receipt":
        doc["payload"]["truth"]["quote_observation"]["fetched_at"] = "2020-01-01T00:00:00Z"
    elif mutation == "count":
        doc["payload"]["series"]["observed_interval_count"] = "390"
    elif mutation == "mapping":
        exports["mcp"]["mapping"]["quote_source"] = {"constant": "yahoo.chart.quote"}
    else:
        exports["mcp"]["payload"]["trend"]["decision_usable"] = "false"
    assert verifier.compare(exports)["overall"] == "BLOCKED"


def test_observed_exports_still_require_loaded_source_and_product_attestation(exports):
    for doc in exports.values():
        doc["mode"] = "observed"
    result = verifier.compare(exports)
    assert result["gates"]["Source"]["status"] == "UNVERIFIED"
    assert result["gates"]["Source"]["reason"] == "backend_export_schema_valid_only; source_test_and_loaded_hash_unattested"
    assert result["gates"]["Runtime"]["status"] == "PARTIAL"
    assert result["gates"]["MCP"]["status"] == "PARTIAL"
    assert result["loaded_source_attestation"] == "UNVERIFIED"
    assert result["product_gate"] == "UNVERIFIED"


def test_later_point_volume_flag_mismatch_is_not_hidden_by_first_point(exports):
    exports["mcp"]["payload"]["trend"]["points"][100]["volume_based_decision_usable"] = True
    result = verifier.compare(exports)
    assert result["comparisons"]["mcp"]["point_quality"]["status"] == "BLOCKED"


@pytest.mark.parametrize("field", ["mode", "surface", "schema", "captured_at"])
def test_object_in_metadata_is_structured_blocker(exports, field):
    exports["backend"][field] = {"invalid": True}
    assert verifier.compare(exports)["overall"] == "BLOCKED"


def test_cli_fixture_directory_has_no_network_database_or_dotenv_access(exports, tmp_path):
    for surface, document in exports.items():
        (tmp_path / f"{surface}.json").write_text(json.dumps(document), encoding="utf-8")
    guard = '''
import sys, runpy
from pathlib import Path
def audit(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo', 'sqlite3.connect'}:
        raise RuntimeError('forbidden IO')
    if event == 'open' and isinstance(args[0], str):
        name = Path(args[0]).name
        if name.startswith('.env') or name.endswith(('.db', '.sqlite', '.sqlite3')):
            raise RuntimeError('forbidden private file')
sys.addaudithook(audit)
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
'''
    completed = subprocess.run([sys.executable, "-B", "-c", guard, str(SCRIPT), "--fixture-dir", str(tmp_path)],
                               capture_output=True, text=True, timeout=30)
    assert completed.returncode == 1, completed.stderr
    assert completed.stdout, completed.stderr
    report = json.loads(completed.stdout)
    assert report["overall"] == "PARTIAL"
    assert report["network_calls"] == 0
    assert set(report["input_sha256"]) == {"backend", "mcp", "frontend"}
    assert set(p.name for p in tmp_path.iterdir()) == {"backend.json", "mcp.json", "frontend.json"}


@pytest.mark.parametrize("raw", ['{"a":1,"a":2}', '{"a":NaN}', '[1,2]', '{bad'])
def test_cli_invalid_json_is_structured_blocker(raw, tmp_path, capsys):
    path = tmp_path / "backend.json"
    path.write_text(raw, encoding="utf-8")
    assert verifier.main(["--backend-json", str(path)]) == 2
    assert json.loads(capsys.readouterr().out)["overall"] == "BLOCKED"


def test_help_and_no_args_are_inert():
    help_result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--help"], capture_output=True, text=True, timeout=10)
    assert help_result.returncode == 0
    assert "--live-read" not in help_result.stdout
    result = subprocess.run([sys.executable, "-B", str(SCRIPT)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert json.loads(result.stdout)["overall"] == "UNVERIFIED"
