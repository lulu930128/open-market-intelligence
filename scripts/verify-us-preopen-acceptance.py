"""Offline JSON snapshot comparator; never a refresh, runtime or market-truth owner.

Input envelope and exit codes are documented in the G-C/G-D Runbook.md.
PASS means the stated check passed, never deployment or live acceptance.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from unittest.mock import patch
from zoneinfo import ZoneInfo

VERSION = "omi.us.preopen.export.v1"
MISSING = object()
# Paths are projections of public REST contracts, not provider/freshness policy.
PATHS = {
    "symbol": "/truth/instrument/symbol",
    "trade_date": "/series/trade_date",
    "session_scope": "/series/requested_scope",
    "interval": "/series/interval",
    "quote_date": "/truth/quote_observation/trade_date",
    "quote_event_at": "/truth/quote_observation/event_at",
    "quote_fetched_at": "/truth/quote_observation/fetched_at",
    "quote_freshness": "/truth/quote_observation/freshness",
    "quote_provider_snapshot_freshness": "/truth/quote_observation/provider_snapshot_freshness",
    "quote_provider": "/truth/quote_observation/selected_provider",
    "quote_source": "/truth/quote_observation/selected_source",
    "quote_limitations": "/truth/quote_observation/limitations",
    "quote_research_usable": "/truth/quote_observation/research_usable",
    "point_count": "/series/observed_interval_count",
    "expected_point_count": "/series/regular_session_coverage/expected_point_count",
    "missing_slot_count": "/series/regular_session_coverage/missing_slot_count",
    "gap_count": "/series/regular_session_coverage/gap_count",
    "duplicate_count": "/series/regular_session_coverage/duplicate_count",
    "non_monotonic_count": "/series/regular_session_coverage/non_monotonic_count",
    "off_grid_count": "/series/regular_session_coverage/off_grid_count",
    "unfinalized_count": "/series/regular_session_coverage/unfinalized_count",
    "coverage_status": "/series/regular_session_coverage/coverage_status",
    "bars_provider": "/truth/health/intraday/resolved_health/selected_provider",
    "bars_source": "/truth/health/intraday/resolved_health/selected_source",
    "bars_event_at": "/truth/health/intraday/resolved_health/selected_event_at",
    "bars_freshness": "/truth/health/intraday/freshness",
    "bars_limitations": "/truth/health/intraday/resolved_health/limitations",
    "bars_facts_usable": "/truth/health/intraday/resolved_health/facts_usable",
    "bars_research_usable": "/truth/health/intraday/resolved_health/research_usable",
    "source_status": "/trend/source_status/status",
    "decision_usable": "/trend/decision_usable",
    "volume_based_decision_usable": "/trend/points/0/volume_based_decision_usable",
    "volume": "/trend/points/0/volume",
    "point_quality": "/trend/points",
    # REST series does not expose receipt time. Absence stays UNVERIFIED.
    "bars_fetched_at": "/trend/bar_source_status/provider_snapshot_as_of",
}
IDENTITY = ("symbol", "trade_date", "session_scope", "interval")
COUNTS = {key for key in PATHS if key.endswith("count")}
FLAGS = {key for key in PATHS if key.endswith("usable")}
TIMES = {key for key in PATHS if key.endswith("_at")}
DATES = {"trade_date", "quote_date"}
ENUMS = {
    "coverage_status": {"complete", "partial", "missing"},
    "session_scope": {"regular"}, "interval": {"1m"},
    **{key: {"fresh", "delayed", "stale", "missing", "unknown"}
       for key in ("quote_freshness", "quote_provider_snapshot_freshness", "bars_freshness")},
}


class InvalidExport(ValueError):
    """Messages contain field identifiers only, never private input values."""


def pointer(payload, path):
    if not isinstance(path, str) or not path.startswith("/"):
        raise InvalidExport("mapping_requires_JSON_pointer")
    current = payload
    for token in path[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            current = current.get(token, MISSING)
        elif isinstance(current, list) and token.isdecimal():
            current = current[int(token)] if int(token) < len(current) else MISSING
        else:
            return MISSING
    return current


def iso_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise InvalidExport("invalid_ISO_date")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise InvalidExport("invalid_ISO_date") from None


def timestamp(value):
    if not isinstance(value, str) or not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", value):
        raise InvalidExport("invalid_aware_timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise InvalidExport("invalid_aware_timestamp") from None
    if result.tzinfo is None or result.utcoffset() is None:
        raise InvalidExport("invalid_aware_timestamp")
    return result


def validate_value(key, value):
    if value is MISSING or value is None:
        return
    if key == "point_quality":
        if not isinstance(value, list):
            raise InvalidExport("invalid_point_quality")
        for point in value:
            if not isinstance(point, dict):
                raise InvalidExport("invalid_point_quality")
            timestamp(point.get("time"))
            for field in ("volume", "decision_usable", "volume_based_decision_usable"):
                validate_value(field, point.get(field, MISSING))
        return
    if key in COUNTS and (type(value) is not int or value < 0):
        raise InvalidExport(f"invalid_count:{key}")
    if key in FLAGS and type(value) is not bool:
        raise InvalidExport(f"invalid_boolean:{key}")
    if key in TIMES:
        timestamp(value)
    elif key in DATES:
        iso_date(value)
    elif key.endswith("limitations"):
        if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
            raise InvalidExport(f"invalid_limitations:{key}")
    elif key == "volume":
        if type(value) not in (float, int) or not 0 <= value < float("inf"):
            raise InvalidExport("invalid_volume")
    elif key not in COUNTS | FLAGS and (not isinstance(value, str) or not value.strip()):
        raise InvalidExport(f"invalid_string:{key}")
    if key in ENUMS and value not in ENUMS[key]:
        raise InvalidExport(f"invalid_enum:{key}")


def validate_backend(payload):
    # Public typed schemas are authoritative. Import lazily so --help is stdlib-only.
    # Their calendar dependency imports Settings; suppress implicit dotenv reads.
    from pydantic_settings.sources import DotEnvSettingsSource
    with patch.object(DotEnvSettingsSource, "_read_env_files", return_value={}):
        from app.us_market.market_truth_contracts import USMarketTruthSnapshot, USIntradaySeriesProjection
    try:
        truth = payload["truth"]
        series = payload["series"]
        if truth.get("contract_version") != "omi.market.us_truth_snapshot.v1":
            raise InvalidExport("invalid_truth_contract_version")
        if series.get("contract_version") != "omi.market.us_intraday_series_projection.v1":
            raise InvalidExport("invalid_series_contract_version")
        USMarketTruthSnapshot.model_validate(truth)
        USIntradaySeriesProjection.model_validate(series)
    except (ValueError, TypeError, KeyError, AttributeError):
        raise InvalidExport("invalid_public_typed_schema") from None
    if truth["instrument"] != series["instrument"]:
        raise InvalidExport("backend_instrument_mismatch")
    if truth["truth_revision"] != series["truth_revision"]:
        raise InvalidExport("backend_revision_mismatch")
    if truth["component_revisions"].get("intraday_revision") != series["intraday_revision"]:
        raise InvalidExport("backend_intraday_revision_mismatch")
    # Do not materialize schema defaults into the exported evidence.
    if "trend" in payload:
        trend = payload["trend"]
        if not isinstance(trend, dict):
            raise InvalidExport("invalid_trend")
        for key, expected in (("symbol", truth["instrument"]["symbol"]),
                              ("trade_date", series["trade_date"]),
                              ("session_scope", series["requested_scope"]), ("interval", "1m")):
            if trend.get(key) != expected:
                raise InvalidExport(f"trend_identity_mismatch:{key}")
        if "point_count" in trend and trend["point_count"] != series["observed_interval_count"]:
            raise InvalidExport("trend_count_mismatch")
        if "points" in trend and (not isinstance(trend["points"], list) or len(trend["points"]) != series["observed_interval_count"]):
            raise InvalidExport("trend_points_count_mismatch")


def normalize(document, surface):
    if not isinstance(document, dict) or document.get("schema") != VERSION:
        raise InvalidExport("invalid_export_schema")
    if document.get("surface") != surface or document.get("mode") not in {"fixture", "observed"}:
        raise InvalidExport("invalid_export_metadata")
    timestamp(document.get("captured_at"))
    identity = document.get("identity")
    if not isinstance(identity, dict) or set(identity) != set(IDENTITY):
        raise InvalidExport("invalid_identity")
    for key, value in identity.items():
        if value is None:
            raise InvalidExport("null_identity")
        validate_value(key, value)
    if not re.fullmatch(r"[A-Z0-9^.=\-]{1,24}", identity["symbol"]):
        raise InvalidExport("invalid_symbol")
    payload = document.get("payload")
    if not isinstance(payload, dict):
        raise InvalidExport("invalid_payload")
    if surface == "backend":
        if "mapping" in document:
            raise InvalidExport("backend_mapping_not_allowed")
        validate_backend(payload)
        mapping = PATHS
        observed = set(PATHS)
    else:
        mapping = document.get("mapping")
        observed = document.get("observed_fields")
        if not isinstance(mapping, dict) or not set(mapping) <= set(PATHS):
            raise InvalidExport("invalid_mapping_fields")
        if not isinstance(observed, list) or any(not isinstance(k, str) for k in observed) or not set(observed) <= set(mapping):
            raise InvalidExport("invalid_observed_fields")
        if any(not isinstance(v, str) or not v.startswith("/") for v in mapping.values()):
            raise InvalidExport("mapping_requires_JSON_pointer")
    values = {key: pointer(payload, mapping[key]) if key in observed else MISSING for key in PATHS}
    for key, value in values.items():
        validate_value(key, value)
        if key in IDENTITY and value is not MISSING and value != identity[key]:
            raise InvalidExport(f"payload_identity_mismatch:{key}")
    for prefix in ("quote", "bars"):
        event, fetched = values[f"{prefix}_event_at"], values[f"{prefix}_fetched_at"]
        if event not in (None, MISSING) and fetched not in (None, MISSING) and timestamp(fetched) < timestamp(event):
            raise InvalidExport(f"receipt_before_event:{prefix}")
        for value in (event, fetched):
            if value not in (None, MISSING) and timestamp(value) > timestamp(document["captured_at"]):
                raise InvalidExport(f"evidence_after_capture:{prefix}")
    if values["quote_date"] not in (None, MISSING) and values["quote_event_at"] not in (None, MISSING):
        if timestamp(values["quote_event_at"]).astimezone(ZoneInfo("America/New_York")).date() != iso_date(values["quote_date"]):
            raise InvalidExport("quote_event_date_mismatch")
    return document, values, mapping


def cell(status, reason, **extra):
    return {"status": status, "reason": reason, **extra}


def compare(documents):
    normalized, errors = {}, {}
    for surface, document in documents.items():
        try:
            normalized[surface] = normalize(document, surface)
        except (InvalidExport, TypeError, KeyError, AttributeError) as exc:
            errors[surface] = str(exc) if isinstance(exc, InvalidExport) else "invalid_export_structure"
    gates = {key: cell("UNVERIFIED", "no_input") for key in ("Source", "Runtime", "MCP", "Frontend")}
    result = {"contract": "omi.us.preopen.report.v1", "overall": "UNVERIFIED", "gates": gates,
              "errors": errors, "comparisons": {}, "quality": {},
              "live_gate": "UNVERIFIED", "product_gate": "UNVERIFIED",
              "loaded_source_attestation": "UNVERIFIED", "network_calls": 0,
              "scope": "exported_JSON_consistency_only; not deployment or live acceptance"}
    backend = normalized.get("backend")
    if backend:
        doc, values, paths = backend
        fields = {key: cell("UNVERIFIED" if value is MISSING or value is None else "PASS",
                            "missing" if value is MISSING else "explicit_null" if value is None else "observed",
                            evidence_path=paths[key]) for key, value in values.items()}
        result["backend_fields"] = fields
        gates["Source"] = cell("UNVERIFIED", "backend_export_schema_valid_only; source_test_and_loaded_hash_unattested")
        result["backend_schema_validation"] = "PASS"
        gates["Runtime"] = cell("UNVERIFIED" if doc["mode"] == "fixture" else "PARTIAL",
                                "synthetic_fixture" if doc["mode"] == "fixture" else "snapshot_only_loaded_source_unattested")
        result["quality"] = {key: fields[key] | {"reported_value": None if values[key] is MISSING else values[key]}
                             for key in ("quote_freshness", "coverage_status", "decision_usable", "volume_based_decision_usable")}
    for surface, label in (("mcp", "MCP"), ("frontend", "Frontend")):
        if surface not in normalized:
            continue
        doc, values, paths = normalized[surface]
        fields = {}
        if backend and doc["identity"] != backend[0]["identity"]:
            gates[label] = cell("BLOCKED", "cross_surface_identity_mismatch")
            continue
        for key in PATHS:
            expected = backend[1][key] if backend else MISSING
            actual = values[key]
            if expected is MISSING or actual is MISSING:
                status, reason = "UNVERIFIED", "field_not_observed"
            elif (expected is None) != (actual is None):
                status, reason = "BLOCKED", "null_value_mismatch"
            elif expected is None:
                status, reason = "UNVERIFIED", "both_explicit_null"
            elif key == "point_quality":
                required = ("time", "volume", "decision_usable", "volume_based_decision_usable")
                if any(any(k not in p for k in required) for p in (*expected, *actual)):
                    status, reason = "UNVERIFIED", "per_point_quality_not_observed"
                else:
                    left = [{k: p[k] for k in required} for p in expected]
                    right = [{k: p[k] for k in required} for p in actual]
                    status, reason = ("PASS", "all_point_quality_equal") if left == right else ("BLOCKED", "point_quality_mismatch")
            else:
                left = timestamp(expected) if key in TIMES else sorted(expected) if key.endswith("limitations") else expected
                right = timestamp(actual) if key in TIMES else sorted(actual) if key.endswith("limitations") else actual
                status, reason = ("PASS", "equal") if left == right else ("BLOCKED", "value_mismatch")
            fields[key] = cell(status, reason, evidence_path=paths.get(key), backend_path=PATHS[key])
        result["comparisons"][surface] = fields
        states = {v["status"] for v in fields.values()}
        status = "BLOCKED" if "BLOCKED" in states else "PARTIAL" if "UNVERIFIED" in states else "PASS"
        if not backend:
            status = "UNVERIFIED"
        if doc["mode"] == "fixture" and status != "BLOCKED":
            gates[label] = cell("UNVERIFIED", "synthetic_fixture", snapshot_comparison=status)
        elif backend and backend[0]["mode"] != doc["mode"]:
            gates[label] = cell("BLOCKED", "fixture_observed_mode_mismatch")
        else:
            gates[label] = cell(status, "exported_fields_only")
    for surface, error in errors.items():
        gates[{"backend": "Source", "mcp": "MCP", "frontend": "Frontend"}[surface]] = cell("BLOCKED", error)
    states = {v["status"] for v in gates.values()}
    result["overall"] = "BLOCKED" if "BLOCKED" in states else "PARTIAL" if backend else "UNVERIFIED"
    return result


def read_document(path):
    # Reject UNC / remote paths and non-JSON targets before opening anything.
    if path.suffix.lower() != ".json" or str(path).startswith(("\\\\", "//")):
        raise InvalidExport("local_JSON_file_required")
    if path.stat().st_size > 16 * 1024 * 1024:
        raise InvalidExport("export_exceeds_16MiB")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise InvalidExport("duplicate_JSON_key")
            result[key] = value
        return result

    def invalid_constant(_value):
        raise InvalidExport("nonfinite_JSON_number")

    raw = path.read_bytes()
    try:
        return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=pairs, parse_constant=invalid_constant), hashlib.sha256(raw).hexdigest()
    except (UnicodeError, json.JSONDecodeError):
        raise InvalidExport("invalid_JSON_encoding_or_syntax") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for surface in ("backend", "mcp", "frontend"):
        parser.add_argument(f"--{surface}-json", type=Path, help="explicit sanitized local export")
    parser.add_argument("--fixture-dir", type=Path, help="optional backend.json/mcp.json/frontend.json; fixture mode only")
    args = parser.parse_args(argv)
    documents, hashes, load_errors = {}, {}, {}
    if args.fixture_dir and any(getattr(args, f"{s}_json") for s in ("backend", "mcp", "frontend")):
        parser.error("--fixture-dir cannot be combined with explicit exports")
    if args.fixture_dir and str(args.fixture_dir).startswith(("\\\\", "//")):
        parser.error("fixture directory must be local")
    for surface in ("backend", "mcp", "frontend"):
        path = args.fixture_dir / f"{surface}.json" if args.fixture_dir else getattr(args, f"{surface}_json")
        if path is None:
            continue
        if args.fixture_dir and not path.exists():
            continue
        try:
            document, digest = read_document(path)
            if args.fixture_dir and (not isinstance(document, dict) or document.get("mode") != "fixture"):
                raise InvalidExport("fixture_directory_requires_fixture_mode")
            documents[surface], hashes[surface] = document, digest
        except (OSError, InvalidExport) as exc:
            load_errors[surface] = str(exc) if isinstance(exc, InvalidExport) else "local_export_read_failed"
    report = compare(documents)
    report["input_sha256"] = hashes
    for surface, error in load_errors.items():
        report["errors"][surface] = error
        report["gates"][{"backend": "Source", "mcp": "MCP", "frontend": "Frontend"}[surface]] = cell("BLOCKED", error)
        report["overall"] = "BLOCKED"
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 2 if report["overall"] == "BLOCKED" else 0 if report["overall"] == "PASS" else 1


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    raise SystemExit(main())
