"""Offline only: bounded calls, identity and provider-stop semantics."""
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path

import pytest

from app.market.providers.twse_mis_guard import TwseMisProviderGuard
from app.observability.provider_http import ProviderHttpError, ProviderHttpFailure, ProviderRequestContext

_path = Path(__file__).resolve().parents[2] / "scripts/diagnostics/tw_mis_z_probe.py"
_spec = importlib.util.spec_from_file_location("tw_mis_z_probe", _path)
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)
NOW = datetime(2026, 10, 20, 2, tzinfo=timezone.utc)
UNIVERSE = [str(1000 + i) for i in range(100)]


def response(codes, *, exchange):
    return {"http_status": 200, "payload": {"rtcode": "0000", "msgArray": [
        {"c": code, "ex": exchange, "d": "20261020", "t": "10:00:00",
         "z": "-" if len(codes) > 1 else "100", "v": "7", "tv": "0", "ts": "0", "pz": "-"}
        for code in codes
    ]}}


def run(fetch=response, **kwargs):
    return probe.run_probe(UNIVERSE, "1005", "tse", rounds=kwargs.pop("rounds", 2),
                           guard=kwargs.pop("guard", TwseMisProviderGuard()),
                           preflight=kwargs.pop("preflight", lambda: None),
                           fetch=fetch, clock=lambda: NOW, wait=kwargs.pop("wait", lambda _: None),
                           **kwargs)


def test_fixed_symbol_and_order_in_each_batch_with_real_clock_separation():
    waits = []
    report = run(wait=waits.append)
    assert report["external_requests"] == 6 <= 8
    assert [row["batch_size"] for row in report["requests"]] == [1, 10, 100] * 2
    assert waits == [10] * 5
    assert all(row["request_codes"][0] == "1005" for row in report["requests"])
    first, second = report["requests"][:2]
    assert first["sample"]["z"] == "100" and second["sample"]["z"] == "-"
    assert first["event_at"] == "2026-10-20T10:00:00+08:00"
    assert first["received_at"] == "2026-10-20T02:00:00+00:00"
    assert first["quote_signature"] != second["quote_signature"]
    assert first["event_age_seconds"] == 0


@pytest.mark.parametrize("kind,count,reason", [
    ("429", 1, "HTTP_429"), ("timeout", 2, "CONSECUTIVE_TIMEOUTS"),
    ("refused", 1, "SOURCE_ERROR"), ("rtcode", 1, "SOURCE_ERROR"),
])
def test_failure_never_retries_or_changes_transport(kind, count, reason):
    calls = []
    def fetch(codes, *, exchange):
        calls.append(codes)
        if kind == "rtcode":
            return {"http_status": 200, "payload": {"rtcode": "5000", "msgArray": []}}
        if kind == "timeout":
            raise TimeoutError()
        status = 429 if kind == "429" else 403
        raise ProviderHttpError("fixture", failure=ProviderHttpFailure(
            context=ProviderRequestContext(market="tw", provider="twse_mis", resource="stock_quote_batch"),
            status="rate_limited" if status == 429 else "error",
            source_url=probe.twse_mis.STOCK_INFO_URL, error_message="fixture",
            http_status_code=status, retry_after_seconds=120,
        ))
    report = run(fetch)
    assert len(calls) == report["external_requests"] == count
    assert report["stop_reason"] == reason


def test_guard_open_and_preflight_denial_make_zero_calls():
    guard = TwseMisProviderGuard()
    attempt = guard.before_request().attempt
    guard.record_http_failure(attempt, 429)
    def forbidden(*a, **kw):
        raise AssertionError("IO forbidden")
    assert run(forbidden, guard=guard)["stop_reason"] == "GUARD_OPEN"
    result = run(forbidden, preflight=lambda: "SERVICE_BUSY")
    assert result["external_requests"] == 0
    assert result["stop_reason"] == "SERVICE_BUSY"


@pytest.mark.parametrize("field,value", [
    ("c", "9999"), ("ex", "otc"), ("d", "20261019"), ("t", "bad"), ("t", "10:01:00"),
])
def test_wrong_symbol_venue_or_clock_cannot_form_comparison(field, value):
    def fetch(codes, *, exchange):
        result = response(codes, exchange=exchange)
        result["payload"]["msgArray"][0][field] = value
        return result
    result = run(fetch)
    assert result["external_requests"] == 1
    assert result["status"] == "stopped"


@pytest.mark.parametrize("rounds", [0, 3, 100])
def test_round_bound(rounds):
    with pytest.raises(ValueError):
        probe.batches(UNIVERSE, "1005", rounds)


def test_one_timeout_then_success_retains_partial_and_reserved_call():
    calls = []
    def fetch(codes, *, exchange):
        calls.append(codes)
        if len(calls) == 1:
            raise TimeoutError()
        return response(codes, exchange=exchange)
    result = run(fetch, rounds=1)
    assert result["status"] == "partial"
    assert result["external_requests"] == 3
    assert result["requests"][0]["timeout"] is True


def test_cli_live_fails_closed_without_cross_process_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "ROOT", tmp_path)
    monkeypatch.setattr(probe, "taiwan_market_session_phase", lambda _: "regular")
    output = tmp_path / ".tmp/probe"
    assert probe.main(["--live", "--output", str(output)]) == 2
    report = json.loads(next(output.glob("*.json")).read_text(encoding="utf-8"))
    assert report["external_requests"] == 0
    assert report["stop_reason"] == "SHARED_RUNTIME_GUARD_AND_LOAD_ADMISSION_UNAVAILABLE"


def test_default_is_offline_and_output_cannot_escape_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "ROOT", tmp_path)
    output = tmp_path / ".tmp/probe"
    assert probe.main(["--output", str(output)]) == 0
    report = json.loads(next(output.glob("*.json")).read_text(encoding="utf-8"))
    assert report["external_requests"] == 0
    assert report["simulated_requests"] == 3
    with pytest.raises(SystemExit):
        probe.main(["--output", str(tmp_path / "outside")])
