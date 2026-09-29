"""TWSE MIS provider IO and parsing for current-session market breadth."""

from __future__ import annotations

from math import isfinite

import math
from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta, timezone
from threading import Lock
from time import monotonic

from app.market.index_parsers import as_float, as_int, parse_trade_date, regular_stock_code
from app.market.providers import http_get, twse_mis
from app.market.providers.tw_current_market import CurrentMarketProviderPayload
from app.market.providers.twse_mis_guard import (
    TWSE_MIS_PROVIDER_GUARD,
    TwseMisGuardDecision,
    response_failure_metadata,
)
from app.market.tw_market_breadth_contract import (
    TW_MARKET_BREADTH_STOCK_STATE_VERSION,
    TW_MARKET_BREADTH_VERSION,
    classify_twse_mis_breadth_coverage,
    breadth_classification_diagnostics,
    resolve_twse_mis_breadth_price_state,
)
from app.market_data.contracts import OperationalStatus
from app.market.trading_calendar import TAIWAN_SESSION_CLOSE_TIME, TAIWAN_CLOSE_RESOLUTION_TIME


TAIPEI_TZ = timezone(timedelta(hours=8))
_CACHE_TTL_SECONDS = 30
_BATCH_SIZE = 100
_MAX_CODES = 2_000
_RESCUE_MAX_SYMBOLS = 32
_RESCUE_MAX_BATCHES = 1
_RESCUE_TIMEOUT_SECONDS = 4
_RESCUE_BACKOFF_SECONDS = 60
_RESCUE_FAILURE_BACKOFF_SECONDS = 300

UniverseReader = Callable[[str], list[str]]

_CACHE: dict[str, dict[str, object]] = {}
_LAST_GOOD: dict[str, dict[str, object]] = {}
_STOCK_ROWS: dict[str, list[dict[str, object]]] = {}
_REFRESH_LOCK = Lock()


def _chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _snapshot_time(message: dict[str, object]) -> datetime | None:
    trade_date = parse_trade_date(message.get("d") or message.get("^"))
    time_text = str(message.get("t") or message.get("%") or "")
    if trade_date is None or not time_text:
        return None
    try:
        hour, minute, second = (int(part) for part in time_text.split(":"))
        return datetime(
            trade_date.year,
            trade_date.month,
            trade_date.day,
            hour,
            minute,
            second,
            tzinfo=TAIPEI_TZ,
        )
    except (TypeError, ValueError):
        return None


def _prices_equal(left: float | None, right: float | None) -> bool:
    return left is not None and right is not None and abs(left - right) < 0.000001


def _classify_message(
    message: dict[str, object],
    market: str,
    *, cached_state: dict | None = None,
) -> dict[str, object] | None:
    code = regular_stock_code(message.get("c"))
    if code is None:
        return None
    trade_date = parse_trade_date(message.get("d") or message.get("^"))
    snapshot_at = _snapshot_time(message)
    if cached_state is not None and snapshot_at is not None:
        prior_at = cached_state.get("price_as_of")
        if isinstance(prior_at, datetime) and prior_at > snapshot_at:
            # An out-of-order receipt cannot replace a newer actual trade.
            # Retain the prior companion, but do not count this as current receipt coverage.
            return None
    previous_close = as_float(message.get("y"))
    if previous_close is not None and (not isfinite(previous_close) or previous_close <= 0):
        previous_close = None
    price_state = resolve_twse_mis_breadth_price_state(
        trade_date=trade_date,
        snapshot_as_of=snapshot_at,
        last_trade_price=message.get("z"),
        cumulative_volume_lots=message.get("v"),
        last_trade_volume_lots=message.get("tv"),
        indicative_price=message.get("pz"),
        indicative_volume_lots=message.get("ps"),
        indicative_status=message.get("ts"),
        cached_state=cached_state,
    )
    price_state.pop("cache_update", None)
    latest_price = as_float(price_state.get("current_price"))
    direction: str | None = None
    if latest_price is not None and previous_close is not None:
        direction = (
            "advance"
            if latest_price > previous_close
            else "decline"
            if latest_price < previous_close
            else "unchanged"
        )
    cumulative_volume = as_int(price_state.get("cumulative_volume_lots"))
    estimated_trade_value = (
        int(latest_price * cumulative_volume * 1000)
        if latest_price is not None
        and cumulative_volume is not None
        and cumulative_volume >= 0
        else None
    )
    limit_up = as_float(message.get("u"))
    limit_down = as_float(message.get("w"))
    if limit_up is not None and (not isfinite(limit_up) or limit_up <= 0):
        limit_up = None
    if limit_down is not None and (not isfinite(limit_down) or limit_down <= 0):
        limit_down = None
    if limit_up is not None and limit_down is not None and limit_up < limit_down:
        limit_up = limit_down = None
    return {
        "code": code,
        "market": market,
        "trade_date": trade_date,
        "as_of": snapshot_at,
        **price_state,
        "price_lineage": cached_state.get("lineage") if cached_state and price_state["price_source"] == "session_cache" else None,
        "current_price": latest_price,
        "previous_close": previous_close,
        "open_price": as_float(message.get("o")),
        "high_price": as_float(message.get("h")),
        "low_price": as_float(message.get("l")),
        "cumulative_volume_lots": cumulative_volume,
        "estimated_trade_value": estimated_trade_value,
        "direction": direction,
        "is_limit_up": (
            latest_price >= limit_up
        ) if latest_price is not None and limit_up is not None and limit_up > 0 else None,
        "is_limit_down": (
            latest_price is not None
            and limit_down is not None
            and limit_down > 0 and latest_price <= limit_down
        ) if latest_price is not None and limit_down is not None and limit_down > 0 else None,
    }


def _fetch_messages(
    codes: list[str],
    market: str,
    timeout_seconds: int,
    *,
    initial_decision: TwseMisGuardDecision | None = None,
    diagnostics: dict[str, object] | None = None,
) -> tuple[list[dict[str, object]], int, int]:
    batches = list(_chunks(codes, _BATCH_SIZE))
    messages: list[dict[str, object]] = []
    failed = 0
    skipped = 0
    failures = []
    external_calls = 0
    started_at = monotonic()
    for index, batch in enumerate(batches):
        decision = (
            initial_decision
            if index == 0 and initial_decision is not None
            else TWSE_MIS_PROVIDER_GUARD.before_request()
        )
        if not decision.allowed:
            skipped += len(batches) - index
            failures.append({"batch_ordinal": index + 1, "reason": "guard_open", "attempted": False})
            break
        attempt = decision.attempt
        if attempt is None:
            raise RuntimeError("TWSE MIS guard allowed a request without an attempt token")
        remaining_seconds = timeout_seconds - (monotonic() - started_at)
        if remaining_seconds <= 0:
            TWSE_MIS_PROVIDER_GUARD.cancel_attempt(attempt)
            skipped += len(batches) - index
            failures.append({"batch_ordinal": index + 1, "reason": "budget_exhausted", "attempted": False})
            break
        external_calls += 1
        try:
            batch_messages = twse_mis.fetch_stock_messages(
                batch,
                exchange="otc" if market == "TPEX" else "tse",
                timeout_seconds=max(1, math.ceil(remaining_seconds)),
                request=http_get,
            )
        except Exception as exc:
            status_code, headers = response_failure_metadata(exc)
            if status_code is not None:
                TWSE_MIS_PROVIDER_GUARD.record_http_failure(
                    attempt,
                    status_code,
                    headers=headers,
                )
            else:
                TWSE_MIS_PROVIDER_GUARD.record_failure(
                    attempt,
                    detail_code=f"TWSE_MIS_{type(exc).__name__.upper()}"
                )
            failed += 1
            failures.append({"batch_ordinal": index + 1, "attempted": True,
                "reason": "rate_limited" if status_code == 429 else "http_error" if status_code else
                          "timeout" if "timeout" in type(exc).__name__.lower() else
                          "parse_error" if isinstance(exc, (ValueError, TypeError)) else "transport_error",
                "http_status": status_code,
            })
            if status_code == 429 or not TWSE_MIS_PROVIDER_GUARD.snapshot().allowed:
                skipped += len(batches) - index - 1
                break
        else:
            messages.extend(batch_messages)
            TWSE_MIS_PROVIDER_GUARD.record_success(attempt)
    if diagnostics is not None:
        diagnostics.update(attempted_batch_count=external_calls, failed_batch_count=failed, skipped_batch_count=skipped,
            batch_failures=failures, elapsed_ms=round((monotonic() - started_at) * 1000))
    return messages, failed, external_calls


def _universe_definition(market: str) -> dict[str, object]:
    return {
        "authority": "omi_stock_master",
        "inclusion_rule": (
            f"market={market}, is_active=true, instrument_type=stock, "
            "four_digit_numeric_security_code"
        ),
        "instrument_type_policy": (
            "Non-stock instruments are excluded when StockMaster classifies "
            "them separately; ETF/ETN treatment therefore depends on registry classification."
        ),
        "missing_quote_policy": "unknown_not_unchanged",
        "official_full_market": False,
    }


def _label(market: str) -> str:
    return f"{'上市' if market == 'TWSE' else '上櫃'}即時廣度（註冊範圍）"


def _cache(market: str, payload: dict[str, object] | None) -> None:
    _CACHE[market] = {
        **_CACHE.get(market, {}),
        "expires_at": monotonic() + _CACHE_TTL_SECONDS,
        "payload": payload,
    }
    if payload is not None and payload.get("failed_batch_count", 0) == 0 and not payload.get("skipped_batch_count"):
        _LAST_GOOD[market] = payload


def _stale(market: str, *, circuit_open: bool) -> dict[str, object] | None:
    payload = _LAST_GOOD.get(market)
    if payload is None:
        return None
    guard = TWSE_MIS_PROVIDER_GUARD.snapshot()
    return {
        **payload,
        "acquisition_fallback": True,
        "latest_attempt_status": "blocked" if circuit_open else "failed",
        "source": "twse_mis_live_breadth_stale",
        "warnings": [
            *[str(item) for item in payload.get("warnings") or []],
            (
                "TWSE MIS breadth refresh is temporarily suspended by the provider circuit breaker."
                if circuit_open
                else "TWSE MIS breadth refresh failed; returning the last successful snapshot."
            ),
        ],
        "provider_guard": {
            "status": "circuit_open" if circuit_open else "degraded",
            "retry_after_seconds": (
                guard.retry_after_seconds if circuit_open else None
            ),
        },
    }


def _build_payload(
    market: str,
    codes: list[str],
    messages: list[dict[str, object]],
    failed_batches: int,
    *, prior_states: dict[str, dict] | None = None,
) -> dict[str, object] | None:
    code_set = set(codes)
    prior_states = prior_states or {}
    # Pick the latest message per instrument before classification; receipt order
    # must not double count a symbol or make an older event replace a newer one.
    unique_messages = {}
    for message in messages:
        code = str(message.get("c") or "")
        if code not in code_set:
            continue
        previous = unique_messages.get(code)
        if previous is None or (str(message.get("d")), str(message.get("t"))) >= (str(previous.get("d")), str(previous.get("t"))):
            unique_messages[code] = message
    rows = [
        row
        for message in unique_messages.values()
        for row in [_classify_message(message, market, cached_state=prior_states.get(str(message.get("c"))))]
        if row is not None and row["code"] in code_set
    ]
    if not rows:
        _STOCK_ROWS[market] = []
        return None
    _STOCK_ROWS[market] = [dict(row) for row in rows]
    received_codes = {str(row["code"]) for row in rows}
    advance = sum(row.get("direction") == "advance" for row in rows)
    decline = sum(row.get("direction") == "decline" for row in rows)
    unchanged = sum(row.get("direction") == "unchanged" for row in rows)
    classified = advance + decline + unchanged
    universe = len(codes)
    not_received = max(universe - len(received_codes), 0)
    aggregate_unknown = max(universe - classified, 0)
    received_unclassified = max(aggregate_unknown - not_received, 0)
    coverage_reason_counts = classify_twse_mis_breadth_coverage(
        rows,
        universe_count=universe,
    )
    directional_unavailable = aggregate_unknown - coverage_reason_counts["valid_no_trade"]
    event_times = [row["as_of"] for row in rows if isinstance(row.get("as_of"), datetime)]
    price_times = [
        row["price_as_of"]
        for row in rows
        if isinstance(row.get("price_as_of"), datetime)
    ]
    trade_dates = [row["trade_date"] for row in rows if isinstance(row.get("trade_date"), date)]
    sessions = {str(row.get("market_session") or "unknown") for row in rows}
    session = next(iter(sessions)) if len(sessions) == 1 else "mixed"
    pending = session == "preopen" and classified == 0
    warnings: list[str] = []
    if directional_unavailable > 0:
        warnings.append(
            f"Some {market} MIS quotes did not expose a confirmed current-session actual trade."
        )
    if failed_batches > 0:
        warnings.append(f"{failed_batches} {market} MIS quote batch(es) failed.")
    trade_values = [
        int(row["estimated_trade_value"])
        for row in rows
        if row.get("estimated_trade_value") is not None
    ]
    trade_value = sum(trade_values) if trade_values else None
    indicative = [row for row in rows if row.get("indicative_match_available")]
    auction_advance = sum(
        as_float(row.get("indicative_match_price")) is not None
        and as_float(row.get("previous_close")) is not None
        and float(row["indicative_match_price"]) > float(row["previous_close"])
        for row in indicative
    )
    auction_decline = sum(
        as_float(row.get("indicative_match_price")) is not None
        and as_float(row.get("previous_close")) is not None
        and float(row["indicative_match_price"]) < float(row["previous_close"])
        for row in indicative
    )
    auction_unchanged = sum(
        _prices_equal(
            as_float(row.get("indicative_match_price")),
            as_float(row.get("previous_close")),
        )
        for row in indicative
    )
    auction_coverage = auction_advance + auction_decline + auction_unchanged
    auction_status = (
        "provisional"
        if session in {"preopen", "closing_auction"} and auction_coverage > 0
        else "unavailable"
        if session in {"preopen", "closing_auction"}
        else "not_applicable"
    )
    source_prefix = (
        "twse_mis_tpex_live_breadth" if market == "TPEX" else "twse_mis_live_breadth"
    )
    return {
        "market": market,
        "version": TW_MARKET_BREADTH_VERSION,
        "state_contract_version": TW_MARKET_BREADTH_STOCK_STATE_VERSION,
        "price_states": {
            # A received newer volume observation invalidates an old companion.
            # An absent/out-of-order receipt does not erase historical evidence.
            **{code: state for code, state in prior_states.items()
               if code in code_set and code not in received_codes
               and state.get("trade_date") == max(trade_dates, default=None)},
            **{
                str(row["code"]): {
                    "trade_date": row["trade_date"], "price": row["current_price"],
                    "price_as_of": row["price_as_of"], "has_actual_trade": True,
                    "lineage": row.get("price_lineage"),
                    "previous_close": (
                        prior_states.get(str(row["code"]), {}).get("previous_close")
                        if row.get("price_source") == "session_cache" else row.get("previous_close")
                    ),
                    "cumulative_volume_lots": (
                        prior_states.get(str(row["code"]), {}).get("cumulative_volume_lots")
                        if row.get("price_source") == "session_cache" else row.get("cumulative_volume_lots")
                    ),
                }
                for row in rows if row.get("has_actual_trade") and row.get("price_as_of")
            },
        },
        "status": (
            "pending_regular_session"
            if pending
            else "ready"
            if directional_unavailable == 0 and failed_batches == 0
            else "partial"
        ),
        "market_session": session,
        "price_semantics": "actual_trade_only",
        "decision_usable": (
            not pending
            and classified > 0
            and directional_unavailable == 0
            and failed_batches == 0
        ),
        "is_provisional": session in {"preopen", "regular", "closing_auction"},
        "scope": "full_market_registered_stock_universe",
        "universe_source": f"StockMaster active {market} stock universe",
        "universe_definition": _universe_definition(market),
        "label": _label(market),
        "trade_date": max(trade_dates) if trade_dates else None,
        "advance_count": advance,
        "decline_count": decline,
        "unchanged_count": unchanged,
        "total_count": universe,
        "universe_count": universe,
        "limits": {
            "universe_count": universe,
            **{
                side: {
                    "observed_count": sum(row.get(f"is_limit_{side}") is True for row in rows),
                    "evaluated_count": sum(isinstance(row.get(f"is_limit_{side}"), bool) for row in rows),
                    "unknown_count": universe - sum(isinstance(row.get(f"is_limit_{side}"), bool) for row in rows),
                }
                for side in ("up", "down")
            },
        },
        "limit_up_count": sum(row.get("is_limit_up") is True for row in rows) if universe and len(rows) == universe and all(isinstance(row.get("is_limit_up"), bool) for row in rows) else None,
        "limit_down_count": sum(row.get("is_limit_down") is True for row in rows) if universe and len(rows) == universe and all(isinstance(row.get("is_limit_down"), bool) for row in rows) else None,
        "trade_value": trade_value,
        "trade_value_is_estimate": trade_value is not None,
        "trade_value_semantics": (
            "estimated_latest_price_x_cumulative_volume_lots"
            if trade_value is not None
            else "unavailable"
        ),
        "trade_value_confidence": "medium" if trade_value is not None else None,
        "source": (
            source_prefix
            if directional_unavailable == 0 and failed_batches == 0
            else f"{source_prefix}_partial"
        ),
        "as_of": max(event_times) if event_times else datetime.now(TAIPEI_TZ),
        "snapshot_as_of": max(event_times) if event_times else None,
        "oldest_price_as_of": min(price_times) if price_times else None,
        "newest_price_as_of": max(price_times) if price_times else None,
        "coverage_count": classified,
        "classified_count": classified,
        "closing_match_coverage_count": sum(
            row.get("direction") in {"advance", "decline", "unchanged"}
            and isinstance(row.get("price_as_of"), datetime)
            and row["price_as_of"].date() == row.get("trade_date")
            and TAIWAN_SESSION_CLOSE_TIME <= row["price_as_of"].time()
            <= TAIWAN_CLOSE_RESOLUTION_TIME
            for row in rows
        ),
        "coverage_ratio": classified / universe if universe else 0.0,
        "unknown_count": aggregate_unknown,
        "received_unclassified_count": received_unclassified,
        "coverage_reason_counts": coverage_reason_counts,
        "classification_diagnostics": breadth_classification_diagnostics(rows),
        "message_count": len(received_codes),
        "missing_count": not_received,
        "not_received_count": not_received,
        "failed_batch_count": failed_batches,
        "component_stock_rows": [dict(row) for row in rows],
        "auction_breadth": {
            "market": market,
            "status": auction_status,
            "market_session": session,
            "scope": "full_market_registered_stock_universe",
            "trade_date": max(trade_dates) if trade_dates else None,
            "as_of": max(event_times) if event_times else None,
            "advance_count": auction_advance,
            "decline_count": auction_decline,
            "unchanged_count": auction_unchanged,
            "coverage_count": auction_coverage,
            "unknown_count": max(universe - auction_coverage, 0),
            "universe_count": universe,
            "price_semantics": "auction_indicative",
            "is_provisional": auction_status == "provisional",
            "decision_usable": False,
            "source": "twse_mis_pz_ts",
        },
        "warnings": warnings,
    }


def _rescue_missing_z(
    market: str, codes: list[str], messages: list[dict[str, object]],
    payload: dict[str, object], *, prior_states: dict[str, dict] | None,
    remaining_seconds: float,
) -> tuple[dict[str, object], int]:
    """Bounded second pass within the existing refresh, using the same guard/receipt."""
    today = datetime.now(TAIPEI_TZ).date()
    candidates = {
        str(row["code"]): row for row in payload["component_stock_rows"]
        if row.get("trade_date") == today
        and (as_int(row.get("cumulative_volume_lots")) or 0) > 0
        and not row.get("has_actual_trade")
        and row.get("market_session") in {"regular", "closing_auction", "close_resolution"}
    }
    diagnostics = dict(
        status="not_needed", candidate_count=len(candidates), selected_count=0,
        resolved_count=0, unresolved_count=0, attempted_batch_count=0,
        failed_batch_count=0, skipped_batch_count=0, batch_failures=[],
        max_symbols=_RESCUE_MAX_SYMBOLS, max_batches=_RESCUE_MAX_BATCHES,
        timeout_seconds=_RESCUE_TIMEOUT_SECONDS, backoff_seconds=_RESCUE_BACKOFF_SECONDS,
    )
    payload["missing_z_rescue"] = diagnostics
    if not candidates:
        return payload, 0
    state = _CACHE.setdefault(market, {})
    if monotonic() < float(state.get("rescue_next_at", 0)):
        diagnostics["status"] = "backoff"
        return payload, 0
    budget = min(_RESCUE_TIMEOUT_SECONDS, math.floor(remaining_seconds))
    if payload.get("failed_batch_count") or payload.get("skipped_batch_count") or budget < 1:
        diagnostics["status"] = "skipped"
        return payload, 0
    # Rotate over current candidates; persistent missing-z symbols cannot starve
    # the rest of the universe. This is cadence metadata, not another price store.
    cursor = str(state.get("rescue_cursor") or "")
    ordered = sorted(candidates)
    ordered = [code for code in ordered if code > cursor] + [code for code in ordered if code <= cursor]
    selected = ordered[:min(_RESCUE_MAX_SYMBOLS, _BATCH_SIZE * _RESCUE_MAX_BATCHES)]
    state.update(rescue_next_at=monotonic() + _RESCUE_BACKOFF_SECONDS, rescue_cursor=selected[-1])
    batch_diagnostics: dict[str, object] = {}
    rescued_messages, failed, calls = _fetch_messages(
        selected, market, budget, diagnostics=batch_diagnostics,
    )
    accepted = {}
    for message in rescued_messages:
        code = str(message.get("c") or "")
        if code not in selected:
            continue
        row = _classify_message(message, market)  # Only new actual z; no inferred/cache price.
        original = candidates[code]
        if (row is None or row.get("trade_date") != today or row.get("price_source") != "z"
            or not row.get("has_actual_trade") or row["as_of"] < original["as_of"]
            or (as_int(row.get("cumulative_volume_lots")) or 0) < original["cumulative_volume_lots"]):
            continue
        previous = accepted.get(code)
        if previous is None or _snapshot_time(message) >= _snapshot_time(previous):
            accepted[code] = message
    blocked = bool(failed or batch_diagnostics.get("skipped_batch_count"))
    if blocked:
        state["rescue_next_at"] = monotonic() + _RESCUE_FAILURE_BACKOFF_SECONDS
        diagnostics["backoff_seconds"] = _RESCUE_FAILURE_BACKOFF_SECONDS
    diagnostics.update(
        status="blocked" if blocked else "complete" if len(accepted) == len(selected) else "partial",
        selected_count=len(selected), resolved_count=len(accepted),
        unresolved_count=len(selected) - len(accepted),
        attempted_batch_count=calls, failed_batch_count=failed,
        skipped_batch_count=batch_diagnostics.get("skipped_batch_count", 0),
        batch_failures=batch_diagnostics.get("batch_failures", []),
    )
    if accepted:
        refreshed = _build_payload(
            market, codes,
            [message for message in messages if str(message.get("c") or "") not in accepted]
            + list(accepted.values()), 0, prior_states=prior_states,
        )
        if refreshed is not None:
            # Full acquisition diagnostics stay independent of the rescue pass.
            for key in ("attempted_batch_count", "failed_batch_count", "skipped_batch_count", "batch_failures", "elapsed_ms"):
                if key in payload:
                    refreshed[key] = payload[key]
            payload = refreshed
    payload["missing_z_rescue"] = diagnostics
    return payload, calls


def read_twse_mis_current_breadth(
    scope: str,
    timeout_seconds: int,
    *,
    universe_reader: UniverseReader,
    prior_states: dict[str, dict] | None = None,
) -> CurrentMarketProviderPayload:
    market = str(scope or "").strip().upper()
    if market not in {"TWSE", "TPEX"}:
        return CurrentMarketProviderPayload(
            payload=None,
            status="failed",
            url=twse_mis.STOCK_INFO_URL,
            error=f"unsupported Taiwan breadth venue: {market}",
            external_calls=0,
        )
    cached = _CACHE.get(market)
    if cached and monotonic() < float(cached.get("expires_at", 0)):
        payload = cached.get("payload")
        return CurrentMarketProviderPayload(
            payload=payload if isinstance(payload, dict) else None,
            status="cached" if isinstance(payload, dict) else "missing",
            url=twse_mis.STOCK_INFO_URL,
            external_calls=0,
        )
    with _REFRESH_LOCK:
        cached = _CACHE.get(market)
        if cached and monotonic() < float(cached.get("expires_at", 0)):
            payload = cached.get("payload")
            return CurrentMarketProviderPayload(
                payload=payload if isinstance(payload, dict) else None,
                status="cached" if isinstance(payload, dict) else "missing",
                url=twse_mis.STOCK_INFO_URL,
                external_calls=0,
            )
        decision = TWSE_MIS_PROVIDER_GUARD.before_request()
        if not decision.allowed:
            stale = _stale(market, circuit_open=True)
            return CurrentMarketProviderPayload(
                payload=stale,
                status="stale" if stale else "failed",
                url=twse_mis.STOCK_INFO_URL,
                status_code=429 if decision.status == "rate_limited" else None,
                error=None if stale else decision.detail_code,
                operational_status=(
                    OperationalStatus.RATE_LIMITED
                    if decision.status == "rate_limited"
                    else OperationalStatus.UNAVAILABLE
                ),
                detail_code=decision.detail_code,
                retry_after_seconds=decision.retry_after_seconds,
                cooldown_until=decision.cooldown_until,
                external_calls=0,
            )
        initial_attempt = decision.attempt
        if initial_attempt is None:
            raise RuntimeError("TWSE MIS guard allowed a request without an attempt token")
        external_calls = 0
        provider_io_started = False
        batch_diagnostics: dict[str, object] = {}
        started_at = monotonic()
        try:
            codes = list(dict.fromkeys(universe_reader(market)))
            minimum = 500 if market == "TWSE" else 250
            if len(codes) < minimum:
                raise ValueError(
                    f"registered {market} stock universe is too small: {len(codes)}"
                )
            if len(codes) > _MAX_CODES:
                raise ValueError(
                    f"registered {market} stock universe exceeds {_MAX_CODES} codes"
                )
            messages, failed_batches, external_calls = _fetch_messages(
                codes,
                market,
                timeout_seconds,
                initial_decision=decision, diagnostics=batch_diagnostics,
            )
            provider_io_started = True
            incomplete_batches = failed_batches + int(batch_diagnostics.get("skipped_batch_count", 0))
            payload = _build_payload(market, codes, messages, incomplete_batches, prior_states=prior_states)
            if payload is None:
                raise ValueError("TWSE MIS breadth returned no canonical candidate")
            payload.update(batch_diagnostics, failed_batch_count=failed_batches)
            payload, rescue_calls = _rescue_missing_z(
                market, codes, messages, payload, prior_states=prior_states,
                remaining_seconds=timeout_seconds - (monotonic() - started_at),
            )
            external_calls += rescue_calls
            _cache(market, payload)
            guard = TWSE_MIS_PROVIDER_GUARD.snapshot()
            return CurrentMarketProviderPayload(
                payload=payload,
                status="available" if incomplete_batches == 0 else "partial",
                url=twse_mis.STOCK_INFO_URL,
                status_code=429 if guard.status == "rate_limited" else 200,
                operational_status=(
                    OperationalStatus.RATE_LIMITED
                    if guard.status == "rate_limited"
                    else OperationalStatus.HEALTHY
                    if incomplete_batches == 0 and guard.allowed
                    else OperationalStatus.DEGRADED
                ),
                detail_code=(
                    guard.detail_code
                    if not guard.allowed
                    else "TWSE_MIS_BREADTH_AVAILABLE"
                    if incomplete_batches == 0
                    else "TWSE_MIS_BREADTH_PARTIAL"
                ),
                retry_after_seconds=(
                    guard.retry_after_seconds if not guard.allowed else None
                ),
                cooldown_until=(guard.cooldown_until if not guard.allowed else None),
                external_calls=external_calls,
            )
        except Exception as exc:
            # Rows belong to the latest attempt, not the last successful batch.
            _STOCK_ROWS[market] = []
            status_code, headers = response_failure_metadata(exc)
            guard = (
                TWSE_MIS_PROVIDER_GUARD.snapshot()
                if provider_io_started
                else TWSE_MIS_PROVIDER_GUARD.cancel_attempt(initial_attempt)
            )
            stale = _stale(
                market,
                circuit_open=not TWSE_MIS_PROVIDER_GUARD.snapshot().allowed,
            )
            return CurrentMarketProviderPayload(
                payload=stale,
                status="stale" if stale else "failed",
                url=twse_mis.STOCK_INFO_URL,
                status_code=429 if guard.status == "rate_limited" else status_code,
                error=None if stale else f"{type(exc).__name__}: {exc}",
                operational_status=(
                    OperationalStatus.RATE_LIMITED
                    if status_code == 429 or guard.status == "rate_limited"
                    else OperationalStatus.FAILED
                ),
                detail_code=guard.detail_code,
                retry_after_seconds=guard.retry_after_seconds,
                cooldown_until=guard.cooldown_until,
                external_calls=external_calls,
                diagnostics=batch_diagnostics,
            )


def get_cached_current_breadth_stock_rows(
    market: str | None = None,
) -> list[dict[str, object]]:
    markets = [str(market).strip().upper()] if market else ["TWSE", "TPEX"]
    return [
        dict(row)
        for venue in markets
        for row in _STOCK_ROWS.get(venue, [])
    ]


def reset_twse_mis_current_breadth_provider() -> None:
    _CACHE.clear()
    _LAST_GOOD.clear()
    _STOCK_ROWS.clear()
    TWSE_MIS_PROVIDER_GUARD.reset()


__all__ = [
    "get_cached_current_breadth_stock_rows",
    "read_twse_mis_current_breadth",
    "reset_twse_mis_current_breadth_provider",
]
