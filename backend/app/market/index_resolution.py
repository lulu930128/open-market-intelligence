from __future__ import annotations

from datetime import date, datetime, time
import hashlib
import json
from typing import Any
from zoneinfo import ZoneInfo


TAIWAN_INDEX_RESOLUTION_VERSION = "tw.index.resolution.v1"
TAIWAN_INDEX_ACQUISITION_POLICIES = frozenset(
    {"cache_only", "prefer_live", "require_live", "unspecified"}
)


def normalize_index_acquisition_policy(value: Any) -> str:
    normalized = str(value or "prefer_live").strip().lower()
    if normalized not in TAIWAN_INDEX_ACQUISITION_POLICIES:
        raise ValueError(
            "acquisition_policy must be one of: cache_only, prefer_live, "
            "require_live."
        )
    return normalized


def index_candidate_datetime(
    value: Any,
    *,
    timezone_name: str,
) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text_value = str(value or "").strip()
        if not text_value or len(text_value) <= 10:
            return None
        try:
            parsed = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
        except ValueError:
            return None
    market_timezone = ZoneInfo(timezone_name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=market_timezone)
    return parsed.astimezone(market_timezone)


def index_candidate_date(
    value: Any,
    *,
    timezone_name: str,
) -> date | None:
    parsed_at = index_candidate_datetime(
        value,
        timezone_name=timezone_name,
    )
    if parsed_at is not None:
        return parsed_at.date()
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def latest_intraday_point(
    intraday: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(intraday, dict):
        return None
    points = intraday.get("points")
    points = points if isinstance(points, list) else []
    for point in reversed(points):
        if isinstance(point, dict):
            return point
    return None


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _resolution_id(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def _index_candidate_authority(
    *,
    source: Any,
    provider: Any,
) -> str:
    identity = " ".join(
        part.casefold()
        for part in (str(source or "").strip(), str(provider or "").strip())
        if part
    )
    if any(
        marker in identity
        for marker in (
            "derived",
            "estimate",
            "proxy",
            "synthetic",
            "snapshot_aggregation",
        )
    ):
        return "derived_proxy"
    if any(
        marker in identity
        for marker in (
            "twse_index_5s",
            "twse_openapi",
            "tpex_openapi",
            "market_index_daily_stat",
            "twse_mis",
        )
    ) or str(provider or "").strip().casefold() in {"twse", "tpex"}:
        return "official_exchange"
    if identity:
        return "provider"
    return "unknown"


def _intraday_official_candidate(
    intraday: dict[str, Any] | None,
    *,
    expected_trade_date: date | None,
    timezone_name: str,
) -> dict[str, Any] | None:
    observation = (
        intraday.get("current_observation")
        if isinstance(intraday, dict)
        and isinstance(intraday.get("current_observation"), dict)
        else None
    )
    if observation is None:
        return None
    semantics = str(observation.get("price_semantics") or "").casefold()
    if semantics not in {"official_index_close", "official_close"}:
        return None
    observed_at = observation.get("observed_at")
    trade_date = index_candidate_date(
        observed_at or intraday.get("trade_date"),
        timezone_name=timezone_name,
    )
    value = observation.get("value")
    eligible = bool(
        isinstance(value, (int, float))
        and observation.get("decision_usable") is True
        and expected_trade_date is not None
        and trade_date == expected_trade_date
    )
    return {
        "candidate": "official_close",
        "value": value if eligible else None,
        "raw_value": value,
        "event_time": _json_value(observed_at),
        "trade_date": trade_date.isoformat() if trade_date else None,
        "source": observation.get("provider") or intraday.get("source"),
        "provider": observation.get("provider") or intraday.get("provider"),
        "eligible": eligible,
        "confirmation_evidence": (
            "intraday_official_close_observation" if eligible else None
        ),
    }


def resolve_taiwan_index_quote_state(
    *,
    intraday: dict[str, Any] | None,
    index_snapshot: dict[str, Any] | None,
    calendar_status: dict[str, Any],
    index_id: str | None = None,
    acquisition_policy: str = "unspecified",
) -> dict[str, Any]:
    """Resolve Taiwan cash-index candidates without performing IO.

    Candidate acquisition belongs to the caller.  This function owns only
    session/date validation, official-close confirmation, deterministic
    selection, and the outward resolution identity.
    """

    normalized_policy = normalize_index_acquisition_policy(acquisition_policy)
    snapshot = index_snapshot if isinstance(index_snapshot, dict) else {}
    timezone_name = str(calendar_status.get("timezone") or "Asia/Taipei")
    checked_at = index_candidate_datetime(
        calendar_status.get("checked_at"),
        timezone_name=timezone_name,
    ) or datetime.now(ZoneInfo(timezone_name))
    phase = str(calendar_status.get("phase") or "unknown")
    current_date = index_candidate_date(
        calendar_status.get("date"),
        timezone_name=timezone_name,
    ) or checked_at.date()
    previous_trading_day = index_candidate_date(
        calendar_status.get("previous_trading_day"),
        timezone_name=timezone_name,
    )
    expected_trade_date = (
        current_date
        if calendar_status.get("is_trading_day") is True
        and phase not in {"preopen_pending", "preopen", "market_closed"}
        else previous_trading_day
    )

    latest_point = latest_intraday_point(intraday)
    intraday_time = (
        latest_point.get("event_time")
        or latest_point.get("bar_time")
        or latest_point.get("time")
        if latest_point
        else None
    )
    intraday_date = index_candidate_date(
        intraday_time or (intraday or {}).get("trade_date"),
        timezone_name=timezone_name,
    )
    intraday_observed_at = index_candidate_datetime(
        intraday_time,
        timezone_name=timezone_name,
    )
    intraday_age_seconds = (
        max(int((checked_at - intraday_observed_at).total_seconds()), 0)
        if intraday_observed_at is not None
        else None
    )
    intraday_fresh_for_phase = bool(
        phase not in {"regular", "regular_live", "closing_auction"}
        or (
            intraday_age_seconds is not None
            and intraday_age_seconds <= 240
        )
    )
    intraday_candidate = {
        "candidate": "intraday_last_trade",
        "value": (
            latest_point.get("price")
            if latest_point and latest_point.get("price") is not None
            else latest_point.get("close")
            if latest_point
            else None
        ),
        "event_time": _json_value(intraday_time),
        "trade_date": intraday_date.isoformat() if intraday_date else None,
        "source": str((intraday or {}).get("source") or "market_index_intraday"),
        "provider": (intraday or {}).get("provider"),
        "age_seconds": intraday_age_seconds,
        "stale_after_seconds": 240,
        "eligible": bool(
            latest_point
            and (
                latest_point.get("price") is not None
                or latest_point.get("close") is not None
            )
            and expected_trade_date is not None
            and intraday_date == expected_trade_date
            and intraday_fresh_for_phase
        ),
    }

    summary_time = snapshot.get("as_of")
    summary_date = index_candidate_date(
        snapshot.get("time")
        or snapshot.get("trade_date")
        or summary_time,
        timezone_name=timezone_name,
    )
    summary_candidate = {
        "candidate": "index_summary",
        "value": (
            snapshot.get("close")
            if snapshot.get("close") is not None
            else snapshot.get("value")
        ),
        "event_time": _json_value(summary_time),
        "trade_date": summary_date.isoformat() if summary_date else None,
        "source": str(snapshot.get("source") or "market_index_summary"),
        "provider": snapshot.get("provider"),
        "eligible": bool(
            (
                snapshot.get("close") is not None
                or snapshot.get("value") is not None
            )
            and expected_trade_date is not None
            and summary_date == expected_trade_date
        ),
    }

    explicit_official_status = str(
        snapshot.get("official_close_status") or ""
    ).casefold()
    official_source = str(
        snapshot.get("official_close_source")
        or snapshot.get("source")
        or ""
    )
    source_is_official = any(
        marker in official_source.casefold()
        for marker in (
            "twse_index_5s_snapshot",
            "twse_openapi",
            "tpex_openapi",
            "market_index_daily_stat",
        )
    )
    after_confirmation_deadline = bool(
        summary_date is not None
        and (
            summary_date < current_date
            or checked_at.time() >= time(13, 33)
        )
    )
    official_price = (
        snapshot.get("official_close_price")
        if snapshot.get("official_close_price") is not None
        else summary_candidate["value"]
    )
    official_trade_date = (
        index_candidate_date(
            snapshot.get("official_close_trade_date"),
            timezone_name=timezone_name,
        )
        or summary_date
    )
    summary_official_confirmed = bool(
        official_price is not None
        and expected_trade_date is not None
        and official_trade_date == expected_trade_date
        and (
            explicit_official_status in {"confirmed", "official", "final"}
            or source_is_official and after_confirmation_deadline
        )
    )
    official_candidate = _intraday_official_candidate(
        intraday,
        expected_trade_date=expected_trade_date,
        timezone_name=timezone_name,
    )
    if official_candidate is None or not official_candidate["eligible"]:
        official_candidate = {
            "candidate": "official_close",
            "value": official_price if summary_official_confirmed else None,
            "raw_value": official_price,
            "event_time": _json_value(
                snapshot.get("official_close_time") or summary_time
            ),
            "trade_date": (
                official_trade_date.isoformat() if official_trade_date else None
            ),
            "source": official_source or None,
            "provider": snapshot.get("provider"),
            "eligible": summary_official_confirmed,
            "confirmation_evidence": (
                "explicit_official_status"
                if explicit_official_status in {"confirmed", "official", "final"}
                else "official_source_after_confirmation_deadline"
                if summary_official_confirmed
                else None
            ),
        }
    official_confirmed = bool(official_candidate["eligible"])

    warnings: list[str] = []
    candidate_dates = {
        str(candidate["trade_date"])
        for candidate in (intraday_candidate, summary_candidate)
        if candidate.get("value") is not None and candidate.get("trade_date")
    }
    if len(candidate_dates) > 1:
        warnings.append(
            "Taiwan index intraday and summary candidates belong to different "
            "trade dates."
        )

    selected_candidate: dict[str, Any] | None = None
    selection_reason = "no_eligible_candidate"
    if official_confirmed and phase in {
        "post_close",
        "post_close_snapshot",
        "market_closed",
    }:
        selected_candidate = official_candidate
        selection_reason = "confirmed_official_close"
    elif phase in {"regular", "regular_live", "closing_auction"}:
        if intraday_candidate["eligible"]:
            selected_candidate = intraday_candidate
            selection_reason = "active_session_prefers_intraday_last_trade"
        elif summary_candidate["eligible"]:
            selected_candidate = summary_candidate
            selection_reason = (
                "active_session_intraday_unavailable_summary_fallback"
            )
    else:
        eligible = [
            candidate
            for candidate in (intraday_candidate, summary_candidate)
            if candidate["eligible"]
        ]
        if eligible:
            selected_candidate = max(
                eligible,
                key=lambda candidate: (
                    index_candidate_datetime(
                        candidate.get("event_time"),
                        timezone_name=timezone_name,
                    )
                    or datetime.min.replace(tzinfo=ZoneInfo(timezone_name))
                ),
            )
            selection_reason = (
                "latest_same_trade_date_candidate_pending_confirmation"
            )

    closing_auction = phase == "closing_auction"
    post_close_current_day = bool(
        calendar_status.get("is_trading_day") is True
        and phase in {"post_close", "post_close_snapshot", "market_closed"}
    )
    official_close_status = (
        "confirmed"
        if official_confirmed
        else "closing_auction_pending"
        if closing_auction
        else "pending"
        if post_close_current_day
        else "confirmed_latest_session"
        if summary_candidate["eligible"]
        and summary_date is not None
        and summary_date < current_date
        and source_is_official
        else "not_available_yet"
    )
    selected_value = (
        selected_candidate.get("value")
        if isinstance(selected_candidate, dict)
        else None
    )
    quote_semantics = (
        "official_close"
        if official_close_status == "confirmed"
        else "closing_auction_last_trade"
        if closing_auction
        else "official_close_pending"
        if official_close_status == "pending"
        else "current_session_last_trade"
        if phase in {"regular", "regular_live"}
        else "latest_completed_session"
        if official_close_status == "confirmed_latest_session"
        else "unavailable"
    )
    delivery_status = (
        "official_close"
        if official_close_status == "confirmed"
        else "closing_auction"
        if closing_auction
        else "official_close_pending"
        if official_close_status == "pending"
        else "latest_completed_session"
        if official_close_status == "confirmed_latest_session"
        else "unavailable"
    )
    selected_trade_date = (
        selected_candidate.get("trade_date")
        if isinstance(selected_candidate, dict)
        else None
    )
    decision_usable = bool(
        selected_candidate is not None
        and selected_trade_date
        and expected_trade_date is not None
        and selected_trade_date == expected_trade_date.isoformat()
        and not (
            closing_auction
            and selected_candidate.get("candidate") != "official_close"
        )
    )
    selected_source = (
        selected_candidate.get("source")
        if isinstance(selected_candidate, dict)
        else None
    )
    selected_provider = (
        selected_candidate.get("provider")
        if isinstance(selected_candidate, dict)
        else None
    )
    selected_authority = _index_candidate_authority(
        source=selected_source,
        provider=selected_provider,
    )
    selected_finalization = (
        "unknown"
        if selected_candidate is None
        else "final"
        if selected_candidate.get("candidate") == "official_close"
        and official_close_status in {"confirmed", "confirmed_latest_session"}
        else "intraday"
        if phase in {"regular", "regular_live", "closing_auction"}
        else "final"
        if official_close_status == "confirmed_latest_session"
        and selected_authority == "official_exchange"
        else "provisional"
    )
    selected_official_source = selected_authority == "official_exchange"
    selected_official_close_confirmed = bool(
        selected_finalization == "final"
        and selected_candidate is not None
        and selected_candidate.get("candidate") == "official_close"
        and official_close_status in {"confirmed", "confirmed_latest_session"}
    )
    selected_provisional_estimate = selected_finalization == "provisional"
    resolution_core = {
        "version": TAIWAN_INDEX_RESOLUTION_VERSION,
        "index_id": str(index_id or snapshot.get("index_id") or "").upper()
        or None,
        "phase": phase,
        "expected_trade_date": (
            expected_trade_date.isoformat() if expected_trade_date else None
        ),
        "selected_candidate": (
            selected_candidate.get("candidate")
            if isinstance(selected_candidate, dict)
            else None
        ),
        "selected_value": selected_value,
        "selected_source": selected_source,
        "selected_provider": selected_provider,
        "selected_authority": selected_authority,
        "selected_finalization": selected_finalization,
        "official_source": selected_official_source,
        "official_close_confirmed": selected_official_close_confirmed,
        "provisional_estimate": selected_provisional_estimate,
        "selected_event_time": (
            selected_candidate.get("event_time")
            if isinstance(selected_candidate, dict)
            else None
        ),
        "selected_trade_date": selected_trade_date,
        "selection_reason": selection_reason,
        "acquisition_policy": normalized_policy,
    }
    resolution_id = _resolution_id(resolution_core)
    return {
        "resolution_version": TAIWAN_INDEX_RESOLUTION_VERSION,
        "resolution_id": resolution_id,
        "acquisition_policy": normalized_policy,
        **{
            key: value
            for key, value in resolution_core.items()
            if key not in {"version", "acquisition_policy"}
        },
        "last_trade_available": intraday_candidate["eligible"],
        "last_trade_price": (
            intraday_candidate["value"]
            if intraday_candidate["eligible"]
            else None
        ),
        "last_trade_time": intraday_candidate["event_time"],
        "last_trade_is_current_session": intraday_candidate["eligible"],
        "official_close_available": official_confirmed,
        "official_close_status": official_close_status,
        "official_close_price": (
            official_candidate["value"] if official_confirmed else None
        ),
        "official_close_trade_date": (
            official_candidate["trade_date"] if official_confirmed else None
        ),
        "official_close_source": (
            official_candidate["source"] if official_confirmed else None
        ),
        "official_close_raw": (
            official_candidate["raw_value"] if official_confirmed else None
        ),
        "official_close_display": (
            f"{float(official_candidate['value']):,.2f}"
            if official_confirmed
            and isinstance(official_candidate["value"], (int, float))
            else None
        ),
        "official_close_precision": 2 if official_confirmed else None,
        "current_observation": (
            {
                "value": selected_value,
                "observed_at": resolution_core["selected_event_time"],
                "trade_date": selected_trade_date,
                "source": resolution_core["selected_source"],
                "provider": resolution_core["selected_provider"],
                "authority": resolution_core["selected_authority"],
                "finalization": resolution_core["selected_finalization"],
                "semantics": quote_semantics,
                "decision_usable": decision_usable,
            }
            if selected_candidate is not None
            else None
        ),
        "quote_semantics": quote_semantics,
        "delivery_status": delivery_status,
        "decision_usable": decision_usable,
        "coverage_status": (
            "complete"
            if decision_usable and not warnings
            else "partial"
            if selected_candidate is not None
            else "missing"
        ),
        "candidates": [
            intraday_candidate,
            summary_candidate,
            official_candidate,
        ],
        "warnings": warnings,
    }


__all__ = [
    "TAIWAN_INDEX_ACQUISITION_POLICIES",
    "TAIWAN_INDEX_RESOLUTION_VERSION",
    "index_candidate_date",
    "index_candidate_datetime",
    "latest_intraday_point",
    "normalize_index_acquisition_policy",
    "resolve_taiwan_index_quote_state",
]
