"""Bounded MIS batch comparison. Default offline; never writes a market DB.

The CLI live gate currently refuses a standalone process: the production MIS
guard and venue IO slots are process-local. A runtime-owned execution seam is
required before live admission can safely share their state. Do not replace
that gate with a new guard, a CLI boolean or a different HTTP client.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from math import isfinite
from pathlib import Path
import sys
from time import monotonic, sleep
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.market.providers import twse_mis  # noqa: E402
from app.market.providers.twse_mis_breadth_evidence import bounded_fetch, AcquisitionDeadlineExceeded  # noqa: E402
from app.market.trading_calendar import taiwan_market_session_phase, taiwan_now  # noqa: E402
from app.observability.provider_http import provider_http_failure  # noqa: E402

FIELDS = ("c", "ex", "d", "t", "tlong", "z", "v", "tv", "ts", "pz")
SIZES = (1, 10, 100)
MAX_REQUESTS = 8
TIMEOUT_SECONDS = 8
INTERVAL_SECONDS = 10


def batches(universe: list[str], observed: str, rounds: int) -> list[list[str]]:
    if rounds not in (1, 2):
        raise ValueError("rounds must be 1 or 2")
    if len(universe) != len(set(universe)) or len(universe) < 100 or observed not in universe:
        raise ValueError("A unique validated venue universe of at least 100 symbols is required")
    if any(not code.isascii() or not code.isdigit() or len(code) != 4 for code in universe):
        raise ValueError("Only validated four-digit ordinary stocks are supported")
    fixed = [observed] + sorted(code for code in universe if code != observed)
    return [fixed[:size] for _ in range(rounds) for size in SIZES]


def positive(value: object) -> bool:
    try:
        return not isinstance(value, bool) and isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError):
        return False


def summarize(payload: object, codes: list[str], observed: str, exchange: str,
              received: datetime) -> dict:
    if not isinstance(payload, dict) or str(payload.get("rtcode", "")) not in ("", "0000"):
        raise ValueError("PROVIDER_PAYLOAD_UNAVAILABLE")
    messages = payload.get("msgArray")
    if not isinstance(messages, list) or len(messages) > len(codes):
        raise ValueError("PROVIDER_RESPONSE_SHAPE_INVALID")
    if any(not isinstance(row, dict) for row in messages):
        raise ValueError("PROVIDER_ROW_SHAPE_INVALID")
    symbols = [str(row.get("c", "")) for row in messages]
    if len(symbols) != len(set(symbols)) or any(code not in codes for code in symbols):
        raise ValueError("PROVIDER_SYMBOL_IDENTITY_MISMATCH")
    if any(row.get("ex") not in (None, exchange) for row in messages):
        raise ValueError("PROVIDER_VENUE_IDENTITY_MISMATCH")
    matched = next((row for row in messages if str(row.get("c")) == observed), None)
    sample = {key: str(matched[key])[:96] for key in FIELDS if key in matched} if matched else None
    event_time = None
    if sample:
        try:
            event_time = datetime.strptime(sample["d"] + " " + sample["t"], "%Y%m%d %H:%M:%S").replace(
                tzinfo=taiwan_now(received).tzinfo)
        except (KeyError, ValueError):
            pass
    signature = hashlib.sha256(json.dumps(sample, sort_keys=True).encode()).hexdigest() if sample else None
    return {
        "rtcode": payload.get("rtcode"), "payload_keys": sorted(str(k) for k in payload),
        "returned": len(messages), "positive_z_count": sum(positive(row.get("z")) for row in messages),
        "observed_symbol": observed, "sample": sample, "quote_signature": signature,
        "received_at": received.isoformat(), "event_at": event_time.isoformat() if event_time else None,
        "event_age_seconds": (received - event_time).total_seconds() if event_time else None,
        "same_session_date": event_time.date() == taiwan_now(received).date() if event_time else False,
        "interpretation": "raw_field_presence_only_not_decision_price",
    }


def fetch_payload(codes: list[str], *, exchange: str) -> dict:
    """Existing public adapter, existing transport, bounded wall wait; no retries."""
    metadata = {}

    def observed_request(url, **kwargs):
        response = twse_mis.get(
            url, provider=twse_mis.PROVIDER, resource="stock_quote_batch",
            target=f"count:{len(codes)}", timeout_seconds=kwargs.pop("timeout"), **kwargs,
        )
        metadata["http_status"] = response.status_code
        return response

    def fetch(*, exchange):
        return twse_mis._fetch_payload(
            channel="|".join(f"{exchange}_{code}.tw" for code in codes),
            resource="stock_quote_batch", target=f"count:{len(codes)}",
            timeout_seconds=TIMEOUT_SECONDS, request=observed_request,
        )

    payload = bounded_fetch(fetch, TIMEOUT_SECONDS, exchange=exchange)
    return {"payload": payload, "http_status": metadata.get("http_status")}


def run_probe(universe: list[str], observed: str, exchange: str, *, rounds: int,
              guard, preflight: Callable[[], str | None], fetch: Callable,
              clock=lambda: datetime.now(timezone.utc), timer=monotonic, wait=sleep) -> dict:
    """Purely injected orchestration; production admission belongs to the runtime."""
    if exchange not in ("tse", "otc"):
        raise ValueError("Unsupported venue")
    plan = batches(universe, observed, rounds)
    report = {"venue": exchange, "observed_symbol": observed, "rounds": rounds,
              "universe_digest": hashlib.sha256("|".join(sorted(universe)).encode()).hexdigest(),
              "requests": [], "external_requests": 0, "status": "complete",
              "limits": {"max_requests": MAX_REQUESTS, "timeout_seconds": TIMEOUT_SECONDS,
                         "interval_seconds": INTERVAL_SECONDS},
              "limitations": ["Sequential requests are not an atomic snapshot.",
                              "Positive raw z does not establish actual-trade qualification or a 15s SLO."]}
    consecutive_timeouts = 0
    for codes in plan:
        if report["requests"]:
            wait(INTERVAL_SECONDS)
        blocker = preflight()
        if blocker:
            report.update(status="blocked", stop_reason=blocker)
            break
        if report["external_requests"] >= MAX_REQUESTS:
            report.update(status="blocked", stop_reason="REQUEST_LIMIT")
            break
        decision = guard.before_request()
        if not decision.allowed or decision.attempt is None:
            report.update(status="blocked", stop_reason="GUARD_OPEN")
            break
        started = timer()
        entry = {"ordinal": len(report["requests"]) + 1, "batch_size": len(codes),
                 "request_at": clock().isoformat(), "request_codes": codes,
                 "request_shape": {"exchange": exchange, "json": "1", "delay": "0"},
                 "guard": decision.detail_code, "http_status": None}
        report["requests"].append(entry)
        # Reserve before IO; an unknown timeout never refunds the request.
        report["external_requests"] += 1
        try:
            result = fetch(codes, exchange=exchange)
            entry["http_status"] = result["http_status"]
            entry.update(summarize(result["payload"], codes, observed, exchange, clock()))
            if not entry["same_session_date"] or entry["event_age_seconds"] < 0:
                raise ValueError("OBSERVED_SYMBOL_EVENT_NOT_COMPARABLE")
            guard.record_success(decision.attempt)
            consecutive_timeouts = 0
        except Exception as exc:
            failure = provider_http_failure(exc)
            status = failure.http_status_code if failure else None
            timeout = isinstance(exc, (TimeoutError, AcquisitionDeadlineExceeded)) or (
                failure is not None and failure.status == "timeout")
            if status is not None:
                guard.record_http_failure(
                    decision.attempt, status,
                    headers={"Retry-After": str(failure.retry_after_seconds)}
                    if failure.retry_after_seconds is not None else None,
                )
            else:
                guard.record_failure(decision.attempt)
            entry.update(error=type(exc).__name__, http_status=status or entry["http_status"],
                         timeout=timeout, received_at=clock().isoformat())
            report["status"] = "partial"
            consecutive_timeouts = consecutive_timeouts + 1 if timeout else 0
            if not timeout or consecutive_timeouts >= 2:
                report.update(status="stopped", stop_reason=(
                    "HTTP_429" if status == 429 else "CONSECUTIVE_TIMEOUTS" if timeout else "SOURCE_ERROR"))
                break
        finally:
            entry["duration_seconds"] = timer() - started
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--offline", action="store_true", help="Synthetic bounded fixture (default)")
    modes.add_argument("--live", action="store_true", help="Evaluate live admission; fail closed without shared guard")
    parser.add_argument("--rounds", type=int, choices=(1, 2), default=1)
    parser.add_argument("--venue", choices=("tse", "otc"), default="tse")
    parser.add_argument("--output", type=Path, default=ROOT / ".tmp" / "tw-mis-z-probe")
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if not output.is_relative_to((ROOT / ".tmp").resolve()):
        parser.error("All output must remain under the repository .tmp directory")
    now = datetime.now(timezone.utc)
    if args.live:
        phase = taiwan_market_session_phase(now)
        report = {
            "mode": "live", "observed_at": now.isoformat(), "venue": args.venue,
            "market_phase": phase, "external_requests": 0,
            "status": "not_applicable" if phase != "regular" else "blocked",
            "stop_reason": "OUTSIDE_REGULAR_SESSION" if phase != "regular"
            else "SHARED_RUNTIME_GUARD_AND_LOAD_ADMISSION_UNAVAILABLE",
            "limitations": [
                "The existing MIS guard and venue IO slots are process-local.",
                "A new CLI process cannot inherit the serving backend cooldown or reserve its IO slot.",
                "No runtime-owned raw 1/10/100 diagnostic admission exists; no alternate transport is used.",
                "StockMaster/venue validation and load admission must precede any future live invocation.",
            ],
        }
        code = 2
    else:
        from app.market.providers.twse_mis_guard import TwseMisProviderGuard
        fixed_time = datetime.fromisoformat("2026-10-20T02:00:00+00:00")
        universe = [str(1000 + i) for i in range(100)]
        def fixture(codes, *, exchange):
            return {"http_status": 200, "payload": {"rtcode": "0000", "msgArray": [
                {"c": code, "ex": exchange, "d": "20261020", "t": "10:00:00",
                 "z": "-", "v": "5", "tv": "0", "ts": "0", "pz": "-"} for code in codes
            ]}}
        report = run_probe(universe, "1000", args.venue, rounds=args.rounds,
                           guard=TwseMisProviderGuard(), preflight=lambda: None,
                           fetch=fixture, clock=lambda: fixed_time, wait=lambda _: None)
        report.update(mode="offline", external_requests=0, simulated_requests=len(report["requests"]),
                      fixture="synthetic_not_real_stockmaster_or_market_evidence")
        code = 0
    output.mkdir(parents=True, exist_ok=True)
    target = output / f"{args.venue}-{now.strftime('%Y%m%dT%H%M%S%fZ')}.json"
    with target.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(json.dumps({"status": report["status"], "external_requests": report["external_requests"],
                      "receipt": str(target)}, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
