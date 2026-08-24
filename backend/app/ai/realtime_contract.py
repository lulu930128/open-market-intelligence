from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any
from zoneinfo import ZoneInfo

from app.market.calendar_status import (
    build_jp_calendar_status,
    build_kr_calendar_status,
    build_taiwan_calendar_status,
    build_us_calendar_status,
)
from app.market.trading_calendar import normalize_taiwan_session_phase


LIVE_MAX_AGE_SECONDS = 180
DELAYED_MAX_AGE_SECONDS = 900
DELAYED_EXCESS_TOLERANCE_SECONDS = 180
EXPECTED_PROVIDER_DELAY_SECONDS = {
    "jp": 900,
    "japan": 900,
    "kr": 1200,
    "korea": 1200,
}
CONTINUOUS_MARKETS = {"crypto", "cryptocurrency", "24x7", "24/7"}
OPEN_MARKET_STATUSES = {
    "open",
    "regular",
    "preopen",
    "pre_market",
    "after_hours",
    "closing_auction",
}
ACTIVE_SESSION_STATUSES = {
    "open",
    "regular",
    "regular_live",
    "preopen",
    "preopen_auction",
    "pre_market",
    "after_hours",
    "closing_auction",
}
INTERVAL_SECONDS = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1_800,
    "60m": 3_600,
    "1h": 3_600,
}
COMPLETED_SESSION_PHASES = {
    "daily_close",
    "post_close",
    "post_close_snapshot",
    "latest_session_close",
    "market_closed",
    "closed",
}
COMPLETED_SESSION_SEMANTICS = {
    "latest_completed_session",
    "latest_session_close",
    "daily_close",
    "final_snapshot",
}
OBSERVATION_TIME_KEYS = {
    "end_at",
    "event_at",
    "event_time",
    "quote_time",
    "selected_event_at",
    "start_at",
    "to_time",
    "bar_time",
    "time",
    "as_of",
}
RECEIVED_TIME_KEYS = {"received_at", "fetched_at", "generated_at", "updated_at"}
PRICE_KEYS = {
    "price",
    "latest_price",
    "last_price",
    "last_trade_price",
    "close",
    "close_price",
    "open_price",
    "high_price",
    "low_price",
    "best_bid_price",
    "best_ask_price",
    "bid",
    "ask",
}


def _numeric_observation(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _has_price_observation(value: Any, *, depth: int = 0) -> bool:
    if depth > 6:
        return False
    if isinstance(value, dict):
        if any(
            key in value and _numeric_observation(value.get(key))
            for key in PRICE_KEYS
        ):
            return True
        return any(
            _has_price_observation(child, depth=depth + 1)
            for child in value.values()
            if isinstance(child, (dict, list))
        )
    if isinstance(value, list):
        return any(
            _has_price_observation(child, depth=depth + 1)
            for child in value[-100:]
            if isinstance(child, (dict, list))
        )
    return False


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text or len(text) <= 10:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _latest_time(value: Any, *, keys: set[str]) -> datetime | None:
    candidates: list[datetime] = []

    def visit(item: Any, *, depth: int) -> None:
        if depth > 6:
            return
        if isinstance(item, dict):
            for key, child in item.items():
                if key in keys:
                    parsed = _parse_datetime(child)
                    if parsed is not None:
                        candidates.append(parsed)
                if isinstance(child, (dict, list)):
                    visit(child, depth=depth + 1)
        elif isinstance(item, list):
            for child in item[-100:]:
                if isinstance(child, (dict, list)):
                    visit(child, depth=depth + 1)

    visit(value, depth=0)
    return max(candidates) if candidates else None


def _first_text(value: Any, *keys: str) -> str | None:
    if not isinstance(value, dict):
        return None
    for key in keys:
        raw = value.get(key)
        if isinstance(raw, (dict, list, tuple, set)):
            continue
        text = str(raw or "").strip()
        if text:
            return text
    freshness = value.get("freshness")
    if isinstance(freshness, dict):
        return _first_text(freshness, *keys)
    return None


def _nested_text(
    value: Any,
    *,
    container_key: str,
    nested_keys: tuple[str, ...],
) -> str | None:
    if not isinstance(value, dict):
        return None
    nested = value.get(container_key)
    if isinstance(nested, dict):
        text = _first_text(nested, *nested_keys)
        if text:
            return text
    freshness = value.get("freshness")
    if isinstance(freshness, dict):
        return _nested_text(
            freshness,
            container_key=container_key,
            nested_keys=nested_keys,
        )
    return None


def _first_bool(value: Any, *keys: str) -> bool | None:
    if not isinstance(value, dict):
        return None
    for key in keys:
        if isinstance(value.get(key), bool):
            return bool(value[key])
    freshness = value.get("freshness")
    if isinstance(freshness, dict):
        return _first_bool(freshness, *keys)
    return None


def _first_int(value: Any, *keys: str) -> int | None:
    if not isinstance(value, dict):
        return None
    for key in keys:
        raw = value.get(key)
        if isinstance(raw, bool):
            continue
        try:
            parsed = int(raw)
        except (TypeError, ValueError):
            continue
        if parsed >= 0:
            return parsed
    freshness = value.get("freshness")
    if isinstance(freshness, dict):
        return _first_int(freshness, *keys)
    return None


def _freshness_text(value: Any, *keys: str) -> str | None:
    if not isinstance(value, dict):
        return None
    freshness = value.get("freshness")
    if not isinstance(freshness, dict):
        return None
    return _first_text(freshness, *keys)


def _completed_session_label(value: str | None) -> bool:
    normalized = str(value or "").strip().casefold().replace("-", "_")
    return (
        normalized in COMPLETED_SESSION_PHASES
        or normalized in COMPLETED_SESSION_SEMANTICS
        or normalized.endswith("_daily_close")
        or normalized.endswith("_session_close")
    )


def _has_observation(value: Any, *, depth: int = 0) -> bool:
    if depth > 6:
        return False
    if isinstance(value, dict):
        if _has_price_observation(value, depth=depth):
            return True
        for key in ("points", "bars", "series"):
            child = value.get(key)
            if isinstance(child, list) and child:
                return True
            if isinstance(child, dict) and child:
                return True
        return any(
            _has_observation(child, depth=depth + 1)
            for child in value.values()
            if isinstance(child, (dict, list))
        )
    if isinstance(value, list):
        return any(
            _has_observation(child, depth=depth + 1)
            for child in value[-100:]
            if isinstance(child, (dict, list))
        )
    return False


def _interval_seconds(value: Any, *, depth: int = 0) -> int | None:
    if depth > 6:
        return None
    if isinstance(value, dict):
        for key in ("effective_interval_seconds", "interval_seconds"):
            parsed = _first_int(value, key)
            if parsed:
                return parsed
        for key in (
            "effective_interval",
            "interval",
            "bar_interval",
            "source_interval",
        ):
            normalized = str(value.get(key) or "").strip().casefold()
            if normalized in INTERVAL_SECONDS:
                return INTERVAL_SECONDS[normalized]
        for child in value.values():
            if isinstance(child, (dict, list)):
                parsed = _interval_seconds(child, depth=depth + 1)
                if parsed:
                    return parsed
    elif isinstance(value, list):
        for child in value[-100:]:
            if isinstance(child, (dict, list)):
                parsed = _interval_seconds(child, depth=depth + 1)
                if parsed:
                    return parsed
    return None


def _is_intraday_bar_observation(value: Any, interval_seconds: int | None) -> bool:
    if interval_seconds is None or interval_seconds >= 86_400:
        return False
    if not isinstance(value, dict):
        return False
    kind = str(value.get("kind") or "").casefold()
    if "intraday" in kind or "bar" in kind:
        return True
    return any(key in value for key in ("points", "bars", "series"))


def _age_seconds(now: datetime, observed_at: datetime | None) -> int | None:
    if observed_at is None:
        return None
    return max(int((now - observed_at).total_seconds()), 0)


def _calendar_completed_session(
    *,
    market_key: str,
    event_at: datetime | None,
    checked_at: datetime,
) -> bool:
    if event_at is None:
        return False

    aliases = {
        "tw": "tw",
        "taiwan": "tw",
        "tw_stock": "tw",
        "tw_index": "tw",
        "us": "us",
        "usa": "us",
        "us_stock": "us",
        "jp": "jp",
        "japan": "jp",
        "jp_stock": "jp",
        "jp_index": "jp",
        "kr": "kr",
        "korea": "kr",
        "kr_stock": "kr",
        "kr_index": "kr",
    }
    normalized_market = aliases.get(market_key)
    builders = {
        "tw": build_taiwan_calendar_status,
        "us": build_us_calendar_status,
        "jp": build_jp_calendar_status,
        "kr": build_kr_calendar_status,
    }
    builder = builders.get(normalized_market or "")
    if builder is None:
        return False

    calendar = builder(now=checked_at)
    phase = str(calendar.get("phase") or "").casefold()
    release_window_keys = {
        "tw": "market_daily_price",
        "us": "us_daily_price",
        "jp": "jp_daily_price",
        "kr": "kr_daily_price",
    }
    release_windows = (
        calendar.get("release_windows")
        if isinstance(calendar.get("release_windows"), dict)
        else {}
    )
    release_window = release_windows.get(
        release_window_keys.get(normalized_market or "", "")
    )
    released_trade_date = (
        str(release_window.get("expected_trade_date") or "")
        if isinstance(release_window, dict)
        else ""
    )
    expected_session_date = (
        str(calendar.get("date") or "")
        if calendar.get("is_trading_day") is True
        and phase in {"post_close", "post_close_snapshot", "after_hours"}
        else released_trade_date
        or str(calendar.get("previous_trading_day") or "")
    )
    if not expected_session_date:
        return False
    try:
        market_timezone = ZoneInfo(
            str(calendar.get("timezone") or "UTC")
        )
    except (KeyError, ValueError):
        market_timezone = ZoneInfo("UTC")
    return (
        event_at.astimezone(market_timezone).date().isoformat()
        == expected_session_date
    )


def classify_observation(
    value: Any,
    *,
    market: str | None,
    realtime_policy: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    checked_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    market_name = str(market or "unknown").strip()
    market_key = market_name.casefold()
    event_at = _latest_time(value, keys=OBSERVATION_TIME_KEYS)
    received_at = _latest_time(value, keys=RECEIVED_TIME_KEYS)
    event_age_seconds = _age_seconds(checked_at, event_at)
    received_age_seconds = _age_seconds(checked_at, received_at)
    market_status = (
        _nested_text(
            value,
            container_key="market_status",
            nested_keys=("status", "market_status"),
        )
        or _first_text(
            value,
            "market_status",
            "current_session_phase",
            "session_phase",
            "session",
        )
        or ("continuous" if market_key in CONTINUOUS_MARKETS else "unknown")
    )
    session_phase = _nested_text(
        value,
        container_key="market_status",
        nested_keys=(
            "phase",
            "current_session_phase",
            "session_phase",
            "session",
        ),
    ) or _first_text(
        value,
        "current_session_phase",
        "session_phase",
        "session",
    )
    canonical_session_phase = (
        normalize_taiwan_session_phase(session_phase)
        if market_key
        in {"tw", "taiwan", "tw_stock", "tw_index", "tw_futures"}
        else str(session_phase or "").strip().casefold().replace("-", "_")
    )
    quote_semantics = _first_text(value, "quote_semantics")
    instrument_phase = _first_text(value, "instrument_phase")
    explicit_status = _first_text(value, "freshness_status", "status")
    freshness_status = _freshness_text(value, "freshness_status", "status")
    explicit_live = _first_bool(value, "is_live", "is_realtime") is True
    explicit_stale = _first_bool(value, "is_stale") is True
    latest_session = _first_bool(value, "is_latest_session_quote") is True
    historical = (
        _first_bool(value, "is_historical") is True
        or str(quote_semantics or "").casefold().startswith("historical_")
    )
    has_observation = _has_observation(value)
    interval_seconds = _interval_seconds(value)
    intraday_bar_observation = _is_intraday_bar_observation(
        value,
        interval_seconds,
    )
    continuous = market_key in CONTINUOUS_MARKETS
    expected_provider_delay_seconds = (
        _first_int(value, "expected_provider_delay_seconds")
        if isinstance(value, dict)
        else None
    )
    expected_provider_delay_source = (
        "payload"
        if expected_provider_delay_seconds is not None
        else "omi_market_provider_policy"
        if market_key in EXPECTED_PROVIDER_DELAY_SECONDS
        else "generic_realtime_policy"
    )
    if expected_provider_delay_seconds is None:
        expected_provider_delay_seconds = EXPECTED_PROVIDER_DELAY_SECONDS.get(
            market_key,
            0,
        )
    delayed_window_seconds = max(
        expected_provider_delay_seconds + DELAYED_EXCESS_TOLERANCE_SECONDS,
        DELAYED_MAX_AGE_SECONDS
        if expected_provider_delay_seconds == 0
        else 0,
    )
    excess_delay_seconds = (
        max(event_age_seconds - expected_provider_delay_seconds, 0)
        if event_age_seconds is not None
        else None
    )

    state = "unavailable"
    observation_mode = "unavailable"
    reason = "No usable price or bar observation was returned."

    if has_observation:
        if historical:
            state = "historical"
            observation_mode = "historical_close"
            reason = (
                "Value represents the explicitly requested historical completed "
                "session, not the latest session or a live quote."
            )
        elif continuous:
            observation_mode = (
                "on_demand_snapshot" if received_at is not None else "cached_snapshot"
            )
            if (
                event_age_seconds is not None
                and event_age_seconds <= LIVE_MAX_AGE_SECONDS
                and received_age_seconds is not None
                and received_age_seconds <= LIVE_MAX_AGE_SECONDS
            ):
                state = "live"
                reason = "Continuous-market event and receipt times are within the live window."
            elif (
                event_age_seconds is not None
                and event_age_seconds <= DELAYED_MAX_AGE_SECONDS
                and received_age_seconds is not None
                and received_age_seconds <= DELAYED_MAX_AGE_SECONDS
            ):
                state = "delayed"
                reason = "Continuous-market snapshot is recent but outside the live window."
            else:
                state = "stale"
                reason = "Continuous-market snapshot is older than the delayed window."
        else:
            normalized_market_status = str(market_status or "").casefold()
            normalized_session_phase = canonical_session_phase
            normalized_semantics = str(quote_semantics or "").casefold()
            market_open = (
                normalized_market_status in OPEN_MARKET_STATUSES
                or normalized_session_phase in OPEN_MARKET_STATUSES
            )
            active_session = (
                normalized_market_status in ACTIVE_SESSION_STATUSES
                or normalized_session_phase in ACTIVE_SESSION_STATUSES
            )
            calendar_completed_session = _calendar_completed_session(
                market_key=market_key,
                event_at=event_at,
                checked_at=checked_at,
            )
            explicitly_completed = (
                latest_session
                or _completed_session_label(normalized_semantics)
                or _completed_session_label(normalized_session_phase)
                or (
                    not explicit_stale
                    and (
                        _completed_session_label(explicit_status)
                        or _completed_session_label(freshness_status)
                    )
                )
                or (
                    normalized_market_status
                    in {"closed", "latest_session_close", "closed_holiday"}
                    and _completed_session_label(normalized_session_phase)
                )
            )
            # A completed-session label is not sufficient when the observation
            # has a timestamp: it must match the calendar's latest completed
            # trade date. This prevents an older Friday close from being
            # promoted to Monday's latest session.
            completed_session = bool(
                calendar_completed_session
                or event_at is None
                and explicitly_completed
            )
            active_observation = active_session and not (
                explicitly_completed and event_at is None
            )
            if (
                active_observation
                and intraday_bar_observation
                and event_age_seconds is not None
                and event_age_seconds
                <= max(
                    LIVE_MAX_AGE_SECONDS,
                    int(interval_seconds or 0)
                    + DELAYED_EXCESS_TOLERANCE_SECONDS,
                )
            ):
                state = "live"
                observation_mode = (
                    "current_partial_bar"
                    if _first_bool(value, "is_partial", "bar_is_partial") is True
                    else "current_interval_bar"
                )
                reason = (
                    "Current-session intraday bar is within its interval-aware "
                    "observation window."
                )
            elif (
                active_observation
                and (
                    explicit_live
                    or explicit_status == "live"
                    or latest_session
                )
                and event_age_seconds is not None
                and event_age_seconds <= LIVE_MAX_AGE_SECONDS
            ):
                state = "live"
                observation_mode = "live_quote"
                reason = "Quote belongs to the active session and is within the live window."
            elif (
                active_observation
                and event_age_seconds is not None
                and event_age_seconds <= delayed_window_seconds
            ):
                state = "delayed"
                observation_mode = "intraday_snapshot"
                reason = (
                    "Active-session observation is within the declared provider "
                    "delay window."
                )
            elif not active_observation and completed_session:
                state = "latest_completed_session"
                observation_mode = "session_close"
                reason = "Market is not live; value represents the latest completed session."
            elif (
                normalized_session_phase == "daily_close"
                and (calendar_completed_session or event_at is None)
            ):
                state = "final_snapshot"
                observation_mode = "daily_close"
                reason = "Value is a completed daily close, not a live quote."
            else:
                state = "stale"
                observation_mode = "cached_snapshot"
                reason = "Observation cannot be tied to a live or latest completed session."

    if realtime_policy == "require_live":
        policy_satisfied = state == "live"
    else:
        policy_satisfied = has_observation
    facts_usable = state in {
        "live",
        "delayed",
        "final_snapshot",
        "historical",
        "latest_completed_session",
    }
    intraday_research_usable = bool(
        has_observation and state in {"live", "delayed"}
    )
    normalized_instrument_phase = str(instrument_phase or "").casefold()
    auction_observation = bool(
        normalized_instrument_phase
        in {
            "preopen_auction",
            "opening_auction_delayed",
            "closing_auction",
            "closing_auction_delayed",
        }
        or _first_bool(
            value,
            "auction_indicative_available",
            "indicative_match_available",
        )
        is True
        or "indicative" in str(quote_semantics or "").casefold()
    )
    explicit_actual_price_usable = _first_bool(
        value,
        "price_decision_usable",
        "last_trade_available",
        "actual_trade_price_available",
    )
    observed_price_available = _has_price_observation(value)
    actual_price_usable = bool(
        explicit_actual_price_usable
        if explicit_actual_price_usable is not None
        else observed_price_available or intraday_bar_observation
    )
    execution_grade_usable = bool(
        state == "live"
        and policy_satisfied
        and actual_price_usable
        and not auction_observation
    )
    refresh_possible_now = (
        continuous
        or str(market_status).casefold() in OPEN_MARKET_STATUSES
        or canonical_session_phase in OPEN_MARKET_STATUSES
    )
    refresh_recommended = (
        state in {"stale", "unavailable"}
        or realtime_policy == "require_live"
        and state != "live"
        and refresh_possible_now
    )
    status_class = (
        "blocked"
        if not policy_satisfied or not facts_usable
        else "limited"
        if state == "delayed"
        else "ready"
    )

    return {
        "version": "omi.realtime.observation.v1",
        "policy": realtime_policy,
        "state": state,
        "temporal_freshness": state,
        "status_class": status_class,
        "policy_satisfied": policy_satisfied,
        "contract_compliant": policy_satisfied,
        "facts_usable": facts_usable,
        "intraday_research_usable": intraday_research_usable,
        "semantic_usability": (
            "usable_for_intraday_research"
            if intraday_research_usable
            else "usable_for_completed_session_research"
            if facts_usable
            else "unusable"
        ),
        "execution_grade_usable": execution_grade_usable,
        "price_decision_usable": actual_price_usable and not auction_observation,
        "auction_research_usable": auction_observation and intraday_research_usable,
        "decision_usable": facts_usable and policy_satisfied,
        "refresh_recommended": refresh_recommended,
        "refresh_possible_now": refresh_possible_now,
        "observation_mode": observation_mode,
        "market": market_name,
        "market_status": market_status,
        "session_phase": session_phase,
        "canonical_session_phase": canonical_session_phase or None,
        "instrument_phase": instrument_phase,
        "observation_kind": (
            "intraday_bar" if intraday_bar_observation else "quote_snapshot"
        ),
        "effective_interval_seconds": interval_seconds,
        "quote_semantics": quote_semantics,
        "is_historical": historical,
        "event_time": event_at.isoformat() if event_at else None,
        "received_at": received_at.isoformat() if received_at else None,
        "checked_at": checked_at.isoformat(),
        "event_age_seconds": event_age_seconds,
        "expected_provider_delay_seconds": expected_provider_delay_seconds,
        "expected_provider_delay_source": expected_provider_delay_source,
        "delay_tolerance_seconds": DELAYED_EXCESS_TOLERANCE_SECONDS,
        "excess_delay_seconds": excess_delay_seconds,
        "received_age_seconds": received_age_seconds,
        "reason": reason,
    }


def annotate_selected_data(
    projected_data: dict[str, Any],
    *,
    target: dict[str, Any],
    selection: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    assessments: dict[str, dict[str, Any]] = {}
    market = str(target.get("market") or target.get("type") or "unknown")
    realtime_policy = str(selection.get("realtime_policy") or "prefer_live")
    for capability_id in ("quote.snapshot", "intraday.bars"):
        value = projected_data.get(capability_id)
        if value in (None, {}, []):
            continue
        assessment = classify_observation(
            value,
            market=market,
            realtime_policy=realtime_policy,
            now=now,
        )
        assessments[capability_id] = assessment
    return assessments
