"""TWSE MIS provider IO and parsing for current-session market breadth."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from threading import Lock
from time import monotonic

from app.market.index_parsers import as_float, as_int, parse_trade_date, regular_stock_code
from app.market.providers import http_get, twse_mis
from app.market.providers.tw_current_market import CurrentMarketProviderPayload
from app.market.providers.twse_mis_guard import (
    TWSE_MIS_PROVIDER_GUARD,
    response_failure_metadata,
)
from app.market.tw_market_breadth_contract import (
    TW_MARKET_BREADTH_STOCK_STATE_VERSION,
    TW_MARKET_BREADTH_VERSION,
    resolve_twse_mis_breadth_price_state,
)
from app.market_data.contracts import OperationalStatus


TAIPEI_TZ = timezone(timedelta(hours=8))
_CACHE_TTL_SECONDS = 30
_BATCH_SIZE = 100
_MAX_CODES = 2_000
_MAX_WORKERS = 2

UniverseReader = Callable[[str], list[str]]

_CACHE: dict[str, dict[str, object]] = {}
_LAST_GOOD: dict[str, dict[str, object]] = {}
_STOCK_ROWS: dict[str, list[dict[str, object]]] = {}
_STOCK_STATE: dict[str, dict[str, object]] = {}
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
) -> dict[str, object] | None:
    code = regular_stock_code(message.get("c"))
    if code is None:
        return None
    trade_date = parse_trade_date(message.get("d") or message.get("^"))
    snapshot_at = _snapshot_time(message)
    previous_close = as_float(message.get("y"))
    state_key = f"{market}:{code}"
    price_state = resolve_twse_mis_breadth_price_state(
        trade_date=trade_date,
        snapshot_as_of=snapshot_at,
        last_trade_price=message.get("z"),
        cumulative_volume_lots=message.get("v"),
        indicative_price=message.get("pz"),
        indicative_volume_lots=message.get("ps"),
        indicative_status=message.get("ts"),
        cached_state=_STOCK_STATE.get(state_key),
    )
    cache_update = price_state.pop("cache_update", None)
    if isinstance(cache_update, dict):
        _STOCK_STATE[state_key] = cache_update
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
    return {
        "code": code,
        "market": market,
        "trade_date": trade_date,
        "as_of": snapshot_at,
        **price_state,
        "current_price": latest_price,
        "previous_close": previous_close,
        "open_price": as_float(message.get("o")),
        "high_price": as_float(message.get("h")),
        "low_price": as_float(message.get("l")),
        "cumulative_volume_lots": cumulative_volume,
        "estimated_trade_value": estimated_trade_value,
        "direction": direction,
        "is_limit_up": (
            latest_price is not None and limit_up is not None and latest_price >= limit_up
        ),
        "is_limit_down": (
            latest_price is not None
            and limit_down is not None
            and latest_price <= limit_down
        ),
    }


def _fetch_messages(
    codes: list[str],
    market: str,
    timeout_seconds: int,
) -> tuple[list[dict[str, object]], int]:
    batches = list(_chunks(codes, _BATCH_SIZE))
    messages: list[dict[str, object]] = []
    failed = 0
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
        futures = [
            executor.submit(
                twse_mis.fetch_stock_messages,
                batch,
                exchange="otc" if market == "TPEX" else "tse",
                timeout_seconds=timeout_seconds,
                request=http_get,
            )
            for batch in batches
        ]
        for future in as_completed(futures):
            try:
                messages.extend(future.result())
            except Exception as exc:
                status_code, headers = response_failure_metadata(exc)
                if status_code is not None:
                    TWSE_MIS_PROVIDER_GUARD.record_http_failure(
                        status_code,
                        headers=headers,
                    )
                else:
                    TWSE_MIS_PROVIDER_GUARD.record_failure(
                        detail_code=f"TWSE_MIS_{type(exc).__name__.upper()}"
                    )
                failed += 1
    return messages, failed


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
        "expires_at": monotonic() + _CACHE_TTL_SECONDS,
        "payload": payload,
    }
    if payload is not None:
        _LAST_GOOD[market] = payload


def _stale(market: str, *, circuit_open: bool) -> dict[str, object] | None:
    payload = _LAST_GOOD.get(market)
    if payload is None:
        return None
    guard = TWSE_MIS_PROVIDER_GUARD.snapshot()
    return {
        **payload,
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
) -> dict[str, object] | None:
    code_set = set(codes)
    rows = [
        row
        for message in messages
        for row in [_classify_message(message, market)]
        if row is not None and row["code"] in code_set
    ]
    if not rows:
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
    if aggregate_unknown > 0:
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
        "status": (
            "pending_regular_session"
            if pending
            else "ready"
            if aggregate_unknown == 0 and failed_batches == 0
            else "partial"
        ),
        "market_session": session,
        "price_semantics": "actual_trade_only",
        "decision_usable": (
            not pending
            and classified > 0
            and aggregate_unknown == 0
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
        "limit_up_count": sum(bool(row.get("is_limit_up")) for row in rows),
        "limit_down_count": sum(bool(row.get("is_limit_down")) for row in rows),
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
            if aggregate_unknown == 0 and failed_batches == 0
            else f"{source_prefix}_partial"
        ),
        "as_of": max(event_times) if event_times else datetime.now(TAIPEI_TZ),
        "snapshot_as_of": max(event_times) if event_times else None,
        "oldest_price_as_of": min(price_times) if price_times else None,
        "newest_price_as_of": max(price_times) if price_times else None,
        "coverage_count": classified,
        "classified_count": classified,
        "coverage_ratio": classified / universe if universe else 0.0,
        "unknown_count": aggregate_unknown,
        "received_unclassified_count": received_unclassified,
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


def read_twse_mis_current_breadth(
    scope: str,
    timeout_seconds: int,
    *,
    universe_reader: UniverseReader,
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
    if cached and monotonic() < float(cached["expires_at"]):
        payload = cached.get("payload")
        return CurrentMarketProviderPayload(
            payload=payload if isinstance(payload, dict) else None,
            status="cached" if isinstance(payload, dict) else "missing",
            url=twse_mis.STOCK_INFO_URL,
        )
    with _REFRESH_LOCK:
        cached = _CACHE.get(market)
        if cached and monotonic() < float(cached["expires_at"]):
            payload = cached.get("payload")
            return CurrentMarketProviderPayload(
                payload=payload if isinstance(payload, dict) else None,
                status="cached" if isinstance(payload, dict) else "missing",
                url=twse_mis.STOCK_INFO_URL,
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
            messages, failed_batches = _fetch_messages(
                codes,
                market,
                timeout_seconds,
            )
            payload = _build_payload(market, codes, messages, failed_batches)
            if payload is None:
                raise ValueError("TWSE MIS breadth returned no canonical candidate")
            _cache(market, payload)
            if failed_batches == 0:
                TWSE_MIS_PROVIDER_GUARD.record_success()
            return CurrentMarketProviderPayload(
                payload=payload,
                status="available" if failed_batches == 0 else "partial",
                url=twse_mis.STOCK_INFO_URL,
                operational_status=(
                    OperationalStatus.HEALTHY
                    if failed_batches == 0
                    else OperationalStatus.DEGRADED
                ),
                detail_code=(
                    "TWSE_MIS_BREADTH_AVAILABLE"
                    if failed_batches == 0
                    else "TWSE_MIS_BREADTH_PARTIAL"
                ),
            )
        except Exception as exc:
            status_code, headers = response_failure_metadata(exc)
            guard = (
                TWSE_MIS_PROVIDER_GUARD.record_http_failure(
                    status_code,
                    headers=headers,
                )
                if status_code is not None
                else TWSE_MIS_PROVIDER_GUARD.record_failure(
                    detail_code=f"TWSE_MIS_{type(exc).__name__.upper()}"
                )
            )
            stale = _stale(
                market,
                circuit_open=not TWSE_MIS_PROVIDER_GUARD.snapshot().allowed,
            )
            return CurrentMarketProviderPayload(
                payload=stale,
                status="stale" if stale else "failed",
                url=twse_mis.STOCK_INFO_URL,
                status_code=status_code,
                error=None if stale else f"{type(exc).__name__}: {exc}",
                operational_status=(
                    OperationalStatus.RATE_LIMITED
                    if status_code == 429
                    else OperationalStatus.FAILED
                ),
                detail_code=guard.detail_code,
                retry_after_seconds=guard.retry_after_seconds,
                cooldown_until=guard.cooldown_until,
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
    _STOCK_STATE.clear()
    TWSE_MIS_PROVIDER_GUARD.reset()


__all__ = [
    "get_cached_current_breadth_stock_rows",
    "read_twse_mis_current_breadth",
    "reset_twse_mis_current_breadth_provider",
]
