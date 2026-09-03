from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from app.market_data.contracts import CanonicalModel


TAIWAN_INDEX_RESOLUTION_VERSION = "tw.index.resolution.v3"
TAIWAN_INDEX_HEADLINE_COMPATIBILITY_VERSION = (
    "compatibility.current_data_core.v1"
)
TAIWAN_INDEX_HEADLINE_COMPATIBILITY_LIMITATION = (
    "INDEX_HEADLINE_COMPATIBILITY_FALLBACK"
)
TAIWAN_INDEX_ACQUISITION_POLICIES = frozenset(
    {"cache_only", "prefer_live", "require_live", "unspecified"}
)


TaiwanIndexCandidateKind = Literal[
    "intraday_last_trade",
    "index_summary",
    "completed_daily_bar",
    "official_close",
]


class TaiwanIndexTruthCandidate(CanonicalModel):
    candidate: TaiwanIndexCandidateKind
    value: float | int | None = None
    raw_value: float | int | None = None
    event_time: str | None = None
    trade_date: str | None = None
    source: str | None = None
    provider: str | None = None
    authority: str | None = None
    finalization: str | None = None
    official: bool | None = None
    release_status: str | None = None
    reconciliation_status: str | None = None
    age_seconds: int | None = None
    stale_after_seconds: int | None = None
    eligible: bool
    confirmation_evidence: str | None = None
    previous_close: float | int | None = None
    previous_close_trade_date: str | None = None
    previous_close_source: str | None = None
    previous_close_provider: str | None = None
    previous_close_authority: str | None = None
    previous_close_finalization: str | None = None
    change: float | int | None = None
    change_pct: float | int | None = None


class TaiwanIndexTruthObservation(CanonicalModel):
    value: float | int | None = None
    observed_at: str | None = None
    trade_date: str | None = None
    source: str | None = None
    provider: str | None = None
    authority: str
    finalization: str
    semantics: str
    decision_usable: bool
    previous_close: float | int | None = None
    previous_close_trade_date: str | None = None
    previous_close_source: str | None = None
    previous_close_provider: str | None = None
    previous_close_authority: str | None = None
    previous_close_finalization: str | None = None
    change: float | int | None = None
    change_pct: float | int | None = None


class ResolvedTaiwanIndexTruth(CanonicalModel):
    """Typed, market-owned Taiwan index headline truth.

    Acquisition is intentionally outside this contract. The model validates
    the one selected observation, its finality/authority, and the evidence that
    explains why it was selected before API and AI consumers project it.
    """

    resolution_version: str
    resolution_id: str
    acquisition_policy: str
    index_id: str | None = None
    phase: str
    expected_trade_date: str | None = None
    selected_candidate: TaiwanIndexCandidateKind | None = None
    selected_value: float | int | None = None
    selected_source: str | None = None
    selected_provider: str | None = None
    selected_authority: str
    selected_finalization: str
    official_source: bool
    official_close_confirmed: bool
    provisional_estimate: bool
    selected_event_time: str | None = None
    selected_trade_date: str | None = None
    selected_previous_close: float | int | None = None
    selected_previous_close_trade_date: str | None = None
    selected_previous_close_source: str | None = None
    selected_previous_close_provider: str | None = None
    selected_previous_close_authority: str | None = None
    selected_previous_close_finalization: str | None = None
    selected_change: float | int | None = None
    selected_change_pct: float | int | None = None
    selection_reason: str
    last_trade_available: bool
    last_trade_price: float | int | None = None
    last_trade_time: str | None = None
    last_trade_is_current_session: bool
    official_close_available: bool
    official_close_status: str
    official_close_price: float | int | None = None
    official_close_trade_date: str | None = None
    official_close_source: str | None = None
    official_close_raw: float | int | None = None
    official_close_display: str | None = None
    official_close_precision: int | None = None
    current_observation: TaiwanIndexTruthObservation | None = None
    quote_semantics: str
    delivery_status: str
    freshness_status: str
    decision_usable: bool
    coverage_status: str
    candidates: tuple[TaiwanIndexTruthCandidate, ...]
    warnings: tuple[str, ...]


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


def _number(value: Any) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _candidate_change_projection(
    *,
    value: Any,
    previous_close: Any,
    explicit_change: Any = None,
    explicit_change_pct: Any = None,
    previous_close_trade_date: Any = None,
    previous_close_source: Any = None,
    previous_close_provider: Any = None,
    previous_close_authority: Any = None,
    previous_close_finalization: Any = None,
) -> dict[str, Any]:
    selected_value = _number(value)
    selected_previous_close = _number(previous_close)
    if selected_value is not None and selected_previous_close is not None:
        selected_change: float | int | None = (
            round(float(selected_value) - float(selected_previous_close), 10)
        )
        selected_change_pct: float | int | None = (
            selected_change / selected_previous_close * 100
            if selected_previous_close != 0
            else None
        )
    else:
        selected_change = _number(explicit_change)
        selected_change_pct = _number(explicit_change_pct)
    return {
        "previous_close": selected_previous_close,
        "previous_close_trade_date": (
            _json_value(previous_close_trade_date)
            if selected_previous_close is not None
            else None
        ),
        "previous_close_source": (
            str(previous_close_source or "") or None
            if selected_previous_close is not None
            else None
        ),
        "previous_close_provider": (
            str(previous_close_provider or "") or None
            if selected_previous_close is not None
            else None
        ),
        "previous_close_authority": (
            str(previous_close_authority or "") or None
            if selected_previous_close is not None
            else None
        ),
        "previous_close_finalization": (
            str(previous_close_finalization or "") or None
            if selected_previous_close is not None
            else None
        ),
        "change": selected_change,
        "change_pct": selected_change_pct,
    }


def _resolution_id(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def _presentation_trade_date(
    calendar_status: dict[str, Any],
    *,
    timezone_name: str,
) -> date | None:
    presentation_session = calendar_status.get("presentation_session")
    if not isinstance(presentation_session, dict):
        return None
    return index_candidate_date(
        presentation_session.get("trade_date"),
        timezone_name=timezone_name,
    )


def _candidate_selection_key(
    candidate: dict[str, Any],
    *,
    timezone_name: str,
) -> tuple[int, datetime]:
    candidate_kind = str(candidate.get("candidate") or "")
    if candidate_kind == "official_close":
        semantic_priority = 500
    elif candidate_kind == "completed_daily_bar":
        authority = str(candidate.get("authority") or "").casefold()
        release_status = str(candidate.get("release_status") or "").casefold()
        semantic_priority = (
            450
            if candidate.get("official") is True
            and authority in {"exchange", "official_exchange"}
            and release_status == "released"
            else 400
        )
    elif candidate_kind == "index_summary":
        semantic_priority = 200
    else:
        semantic_priority = 100
    event_time = index_candidate_datetime(
        candidate.get("event_time"),
        timezone_name=timezone_name,
    ) or datetime.min.replace(tzinfo=ZoneInfo(timezone_name))
    return semantic_priority, event_time


def _selection_reason(candidate: dict[str, Any]) -> str:
    candidate_kind = str(candidate.get("candidate") or "")
    return {
        "official_close": "confirmed_official_close",
        "completed_daily_bar": "qualified_completed_daily_bar",
        "index_summary": "same_trade_date_summary_fallback",
        "intraday_last_trade": "same_trade_date_intraday_fallback",
    }.get(candidate_kind, "same_trade_date_candidate_selected")


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
        **_candidate_change_projection(
            value=value,
            previous_close=(
                observation.get("previous_close")
                if observation.get("previous_close") is not None
                else intraday.get("previous_close")
            ),
            explicit_change=observation.get("change"),
            explicit_change_pct=observation.get("change_pct"),
            previous_close_trade_date=observation.get("previous_close_trade_date"),
            previous_close_source=observation.get("previous_close_source"),
            previous_close_provider=observation.get("previous_close_provider"),
            previous_close_authority=observation.get("previous_close_authority"),
            previous_close_finalization=observation.get(
                "previous_close_finalization"
            ),
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
    presentation_trade_date = _presentation_trade_date(
        calendar_status,
        timezone_name=timezone_name,
    )
    active_session_phase = phase in {
        "regular",
        "regular_live",
        "closing_auction",
        "close_resolution",
    }
    current_trading_day_phase = active_session_phase or phase in {
        "post_close",
        "post_close_snapshot",
        "market_closed",
    }
    expected_trade_date = (
        current_date
        if calendar_status.get("is_trading_day") is True
        and current_trading_day_phase
        else presentation_trade_date or previous_trading_day
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
        **_candidate_change_projection(
            value=(
                latest_point.get("price")
                if latest_point and latest_point.get("price") is not None
                else latest_point.get("close")
                if latest_point
                else None
            ),
            previous_close=(
                latest_point.get("previous_close")
                if latest_point
                and latest_point.get("previous_close") is not None
                else (intraday or {}).get("previous_close")
                if (intraday or {}).get("previous_close") is not None
                else snapshot.get("previous_close")
            ),
            explicit_change=(intraday or {}).get("change"),
            explicit_change_pct=(intraday or {}).get("change_pct"),
            previous_close_trade_date=(intraday or {}).get(
                "previous_close_trade_date"
            ),
            previous_close_source=(intraday or {}).get("previous_close_source"),
            previous_close_provider=(intraday or {}).get(
                "previous_close_provider"
            ),
            previous_close_authority=(intraday or {}).get(
                "previous_close_authority"
            ),
            previous_close_finalization=(intraday or {}).get(
                "previous_close_finalization"
            ),
        ),
    }

    summary_time = snapshot.get("as_of")
    summary_observed_at = index_candidate_datetime(
        summary_time,
        timezone_name=timezone_name,
    )
    summary_age_seconds = (
        max(int((checked_at - summary_observed_at).total_seconds()), 0)
        if summary_observed_at is not None
        else None
    )
    summary_fresh_for_phase = bool(
        phase not in {"regular", "regular_live", "closing_auction"}
        or (
            summary_age_seconds is not None
            and summary_age_seconds <= 240
        )
    )
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
        "age_seconds": summary_age_seconds,
        "stale_after_seconds": 240,
        "eligible": bool(
            (
                snapshot.get("close") is not None
                or snapshot.get("value") is not None
            )
            and expected_trade_date is not None
            and summary_date == expected_trade_date
            and summary_fresh_for_phase
        ),
        **_candidate_change_projection(
            value=(
                snapshot.get("close")
                if snapshot.get("close") is not None
                else snapshot.get("value")
            ),
            previous_close=snapshot.get("previous_close"),
            explicit_change=snapshot.get("change"),
            explicit_change_pct=snapshot.get("change_pct"),
            previous_close_trade_date=snapshot.get(
                "previous_close_trade_date"
            ),
            previous_close_source=snapshot.get("previous_close_source"),
            previous_close_provider=snapshot.get("previous_close_provider"),
            previous_close_authority=snapshot.get("previous_close_authority"),
            previous_close_finalization=snapshot.get(
                "previous_close_finalization"
            ),
        ),
    }

    completed_trade_date = index_candidate_date(
        snapshot.get("completed_daily_trade_date"),
        timezone_name=timezone_name,
    )
    completed_daily_candidate = {
        "candidate": "completed_daily_bar",
        "value": snapshot.get("completed_daily_close"),
        "event_time": _json_value(snapshot.get("completed_daily_event_time")),
        "trade_date": (
            completed_trade_date.isoformat() if completed_trade_date else None
        ),
        "source": snapshot.get("completed_daily_source"),
        "provider": snapshot.get("completed_daily_provider"),
        "authority": snapshot.get("completed_daily_authority"),
        "finalization": snapshot.get("completed_daily_finalization"),
        "official": bool(snapshot.get("completed_daily_official")),
        "release_status": snapshot.get("completed_daily_release_status"),
        "reconciliation_status": snapshot.get(
            "completed_daily_reconciliation_status"
        ),
        "eligible": bool(
            snapshot.get("completed_daily_qualified") is True
            and snapshot.get("completed_daily_close") is not None
            and expected_trade_date is not None
            and completed_trade_date == expected_trade_date
            and str(snapshot.get("completed_daily_finalization") or "")
            in {"final", "corrected"}
        ),
        **_candidate_change_projection(
            value=snapshot.get("completed_daily_close"),
            previous_close=snapshot.get("completed_daily_previous_close"),
            explicit_change=snapshot.get("completed_daily_change"),
            explicit_change_pct=snapshot.get("completed_daily_change_pct"),
            previous_close_trade_date=snapshot.get(
                "completed_daily_previous_close_trade_date"
            ),
            previous_close_source=snapshot.get(
                "completed_daily_previous_close_source"
            ),
            previous_close_provider=snapshot.get(
                "completed_daily_previous_close_provider"
            ),
            previous_close_authority=snapshot.get(
                "completed_daily_previous_close_authority"
            ),
            previous_close_finalization=snapshot.get(
                "completed_daily_previous_close_finalization"
            ),
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
        and explicit_official_status in {"confirmed", "official", "final"}
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
            "provider": snapshot.get("official_close_provider"),
            "authority": snapshot.get("official_close_authority"),
            "finalization": snapshot.get("official_close_finalization"),
            "eligible": summary_official_confirmed,
            "confirmation_evidence": (
                "explicit_official_status"
                if explicit_official_status in {"confirmed", "official", "final"}
                else None
            ),
            **_candidate_change_projection(
                value=official_price,
                previous_close=snapshot.get("official_close_previous_close"),
                explicit_change=snapshot.get("official_close_change"),
                explicit_change_pct=snapshot.get("official_close_change_pct"),
                previous_close_trade_date=snapshot.get(
                    "official_close_previous_close_trade_date"
                ),
                previous_close_source=snapshot.get(
                    "official_close_previous_close_source"
                ),
                previous_close_provider=snapshot.get(
                    "official_close_previous_close_provider"
                ),
                previous_close_authority=snapshot.get(
                    "official_close_previous_close_authority"
                ),
                previous_close_finalization=snapshot.get(
                    "official_close_previous_close_finalization"
                ),
            ),
        }
    official_confirmed = bool(official_candidate["eligible"])

    completed_daily_is_official_close = bool(
        completed_daily_candidate["eligible"]
        and completed_daily_candidate["official"] is True
        and str(completed_daily_candidate.get("authority") or "").casefold()
        in {"exchange", "official_exchange"}
        and str(completed_daily_candidate.get("release_status") or "").casefold()
        == "released"
        and str(completed_daily_candidate.get("finalization") or "").casefold()
        in {"final", "corrected"}
    )
    official_close_from_completed_daily = bool(
        completed_daily_is_official_close and not official_confirmed
    )
    if official_close_from_completed_daily:
        official_candidate = {
            "candidate": "official_close",
            "value": completed_daily_candidate["value"],
            "raw_value": completed_daily_candidate["value"],
            "event_time": completed_daily_candidate["event_time"],
            "trade_date": completed_daily_candidate["trade_date"],
            "source": completed_daily_candidate["source"],
            "provider": completed_daily_candidate["provider"],
            "eligible": True,
            "confirmation_evidence": "release_qualified_completed_daily",
            **{
                key: completed_daily_candidate.get(key)
                for key in (
                    "previous_close",
                    "previous_close_trade_date",
                    "previous_close_source",
                    "previous_close_provider",
                    "previous_close_authority",
                    "previous_close_finalization",
                    "change",
                    "change_pct",
                )
            },
        }
        official_confirmed = True

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
    if completed_daily_candidate["eligible"] and phase in {
        "post_close",
        "post_close_snapshot",
        "market_closed",
    } and official_close_from_completed_daily:
        selected_candidate = completed_daily_candidate
        selection_reason = "qualified_completed_daily_bar"
    elif official_confirmed and phase in {
        "post_close",
        "post_close_snapshot",
        "market_closed",
    }:
        selected_candidate = official_candidate
        selection_reason = "confirmed_official_close"
    elif completed_daily_candidate["eligible"] and phase in {
        "post_close",
        "post_close_snapshot",
        "market_closed",
    }:
        selected_candidate = completed_daily_candidate
        selection_reason = "qualified_completed_daily_bar"
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
            for candidate in (
                official_candidate,
                intraday_candidate,
                summary_candidate,
                completed_daily_candidate,
            )
            if candidate["eligible"]
            and not (
                official_close_from_completed_daily
                and candidate is official_candidate
            )
        ]
        if eligible:
            selected_candidate = max(
                eligible,
                key=lambda candidate: _candidate_selection_key(
                    candidate,
                    timezone_name=timezone_name,
                ),
            )
            selection_reason = _selection_reason(selected_candidate)

    closing_auction = phase == "closing_auction"
    post_close_current_day = bool(
        calendar_status.get("is_trading_day") is True
        and phase in {"post_close", "post_close_snapshot", "market_closed"}
    )
    if (
        post_close_current_day
        and selected_candidate is not None
        and selected_candidate.get("candidate")
        not in {"official_close", "completed_daily_bar"}
    ):
        selection_reason = (
            "latest_same_trade_date_candidate_pending_confirmation"
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
        and explicit_official_status in {"confirmed", "official", "final"}
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
        or (
            selected_candidate is not None
            and selected_candidate.get("candidate") == "completed_daily_bar"
        )
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
        or (
            selected_candidate is not None
            and selected_candidate.get("candidate") == "completed_daily_bar"
        )
        else "unavailable"
    )
    selected_trade_date = (
        selected_candidate.get("trade_date")
        if isinstance(selected_candidate, dict)
        else None
    )
    completed_session_phase = phase in {
        "preopen_pending",
        "preopen",
        "post_close",
        "post_close_snapshot",
        "market_closed",
    }
    decision_usable = bool(
        selected_candidate is not None
        and selected_trade_date
        and expected_trade_date is not None
        and selected_trade_date == expected_trade_date.isoformat()
        and (
            not completed_session_phase
            or (
                selected_candidate.get("candidate")
                in {"official_close", "completed_daily_bar"}
                and (
                    selected_candidate.get("candidate") == "completed_daily_bar"
                    or official_close_status
                    in {"confirmed", "confirmed_latest_session"}
                )
            )
        )
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
    explicit_selected_authority = (
        str(selected_candidate.get("authority") or "").strip().casefold()
        if isinstance(selected_candidate, dict)
        else ""
    )
    selected_authority = (
        "official_exchange"
        if explicit_selected_authority in {"exchange", "official_exchange"}
        else "derived_proxy"
        if explicit_selected_authority in {"derived", "derived_proxy"}
        else explicit_selected_authority
        or _index_candidate_authority(
            source=selected_source,
            provider=selected_provider,
        )
    )
    selected_finalization = (
        "unknown"
        if selected_candidate is None
        else "final"
        if selected_candidate.get("candidate")
        in {"official_close", "completed_daily_bar"}
        and (
            selected_candidate.get("candidate") == "completed_daily_bar"
            or official_close_status in {"confirmed", "confirmed_latest_session"}
        )
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
        and selected_candidate.get("candidate")
        in {"official_close", "completed_daily_bar"}
        and official_close_status in {"confirmed", "confirmed_latest_session"}
    )
    selected_provisional_estimate = bool(
        selected_finalization == "provisional"
        or selected_authority == "derived_proxy"
    )
    freshness_status = (
        "current"
        if decision_usable and active_session_phase
        else "stale"
        if phase in {"regular", "regular_live", "closing_auction"}
        and (
            selected_candidate is not None
            or intraday_candidate.get("value") is not None
        )
        else "latest_completed_session"
        if selected_candidate is not None
        else "missing"
    )
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
        "selected_previous_close": (
            selected_candidate.get("previous_close")
            if isinstance(selected_candidate, dict)
            else None
        ),
        "selected_previous_close_trade_date": (
            selected_candidate.get("previous_close_trade_date")
            if isinstance(selected_candidate, dict)
            else None
        ),
        "selected_previous_close_source": (
            selected_candidate.get("previous_close_source")
            if isinstance(selected_candidate, dict)
            else None
        ),
        "selected_previous_close_provider": (
            selected_candidate.get("previous_close_provider")
            if isinstance(selected_candidate, dict)
            else None
        ),
        "selected_previous_close_authority": (
            selected_candidate.get("previous_close_authority")
            if isinstance(selected_candidate, dict)
            else None
        ),
        "selected_previous_close_finalization": (
            selected_candidate.get("previous_close_finalization")
            if isinstance(selected_candidate, dict)
            else None
        ),
        "selected_change": (
            selected_candidate.get("change")
            if isinstance(selected_candidate, dict)
            else None
        ),
        "selected_change_pct": (
            selected_candidate.get("change_pct")
            if isinstance(selected_candidate, dict)
            else None
        ),
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
                "previous_close": resolution_core["selected_previous_close"],
                "previous_close_trade_date": resolution_core[
                    "selected_previous_close_trade_date"
                ],
                "previous_close_source": resolution_core[
                    "selected_previous_close_source"
                ],
                "previous_close_provider": resolution_core[
                    "selected_previous_close_provider"
                ],
                "previous_close_authority": resolution_core[
                    "selected_previous_close_authority"
                ],
                "previous_close_finalization": resolution_core[
                    "selected_previous_close_finalization"
                ],
                "change": resolution_core["selected_change"],
                "change_pct": resolution_core["selected_change_pct"],
            }
            if selected_candidate is not None
            else None
        ),
        "quote_semantics": quote_semantics,
        "delivery_status": delivery_status,
        "freshness_status": freshness_status,
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
            completed_daily_candidate,
            official_candidate,
        ],
        "warnings": warnings,
    }


def resolve_taiwan_index_truth(
    *,
    intraday: dict[str, Any] | None,
    index_snapshot: dict[str, Any] | None,
    calendar_status: dict[str, Any],
    index_id: str | None = None,
    acquisition_policy: str = "unspecified",
) -> ResolvedTaiwanIndexTruth:
    """Return the validated Taiwan index truth used by all consumers."""

    return ResolvedTaiwanIndexTruth.model_validate(
        resolve_taiwan_index_quote_state(
            intraday=intraday,
            index_snapshot=index_snapshot,
            calendar_status=calendar_status,
            index_id=index_id,
            acquisition_policy=acquisition_policy,
        )
    )


def project_taiwan_index_headline(
    index_item: dict[str, Any],
) -> dict[str, Any] | None:
    """Project one resolved headline, with an explicit bounded compatibility seam."""

    raw_resolution = index_item.get("resolution")
    validation_limitation: str | None = None
    try:
        truth = ResolvedTaiwanIndexTruth.model_validate(raw_resolution)
        if truth.resolution_version != TAIWAN_INDEX_RESOLUTION_VERSION:
            validation_limitation = "INDEX_HEADLINE_RESOLUTION_VERSION_UNSUPPORTED"
            truth = None
    except ValidationError:
        truth = None
        validation_limitation = (
            "INDEX_HEADLINE_RESOLUTION_INVALID"
            if raw_resolution is not None
            else "INDEX_HEADLINE_RESOLUTION_MISSING"
        )

    if truth is not None:
        return {
            "index_id": truth.index_id or str(index_item.get("index_id") or ""),
            "status": truth.coverage_status,
            "value": truth.selected_value,
            "previous_close": truth.selected_previous_close,
            "change": truth.selected_change,
            "change_pct": truth.selected_change_pct,
            "event_time": truth.selected_event_time,
            "trade_date": truth.selected_trade_date,
            "source": truth.selected_source,
            "provider": truth.selected_provider,
            "selected_candidate": truth.selected_candidate,
            "authority": truth.selected_authority,
            "finalization": truth.selected_finalization,
            "official_source": truth.official_source,
            "official_close_confirmed": truth.official_close_confirmed,
            "provisional_estimate": truth.provisional_estimate,
            "selection_reason": truth.selection_reason,
            "acquisition_policy": truth.acquisition_policy,
            "resolution_version": truth.resolution_version,
            "resolution_id": truth.resolution_id,
            "official_close_status": truth.official_close_status,
            "official": truth.official_close_confirmed,
            "provisional": truth.provisional_estimate,
            "decision_usable": truth.decision_usable,
            "coverage_status": truth.coverage_status,
            "quote_semantics": truth.quote_semantics,
            "delivery_status": truth.delivery_status,
            "freshness_status": truth.freshness_status,
            "warnings": list(truth.warnings),
            "limitations": [],
            "compatibility_fallback": False,
            "compatibility_fallback_reason": None,
        }

    current_data_core = index_item.get("current_data_core")
    has_current_data_core = bool(
        isinstance(current_data_core, dict)
        and isinstance(current_data_core.get("index"), dict)
    )
    current = (
        current_data_core.get("index")
        if has_current_data_core
        else index_item.get("current_observation")
        if isinstance(index_item.get("current_observation"), dict)
        else index_item
        if _number(index_item.get("close")) is not None
        or _number(index_item.get("value")) is not None
        else None
    )
    if current is None:
        return None
    resolved_health = (
        current.get("resolved_health")
        if isinstance(current.get("resolved_health"), dict)
        else {}
    )
    source = current.get("source")
    provider = current.get("provider")
    change_projection = _candidate_change_projection(
        value=(
            current.get("close")
            if current.get("close") is not None
            else current.get("value")
        ),
        previous_close=current.get("previous_close"),
        explicit_change=current.get("change"),
        explicit_change_pct=(
            current.get("change_pct")
            if current.get("change_pct") is not None
            else index_item.get("change_pct")
        ),
        previous_close_trade_date=current.get("previous_close_trade_date"),
        previous_close_source=current.get("previous_close_source"),
        previous_close_provider=current.get("previous_close_provider"),
        previous_close_authority=current.get("previous_close_authority"),
        previous_close_finalization=current.get(
            "previous_close_finalization"
        ),
    )
    limitation_codes = list(
        dict.fromkeys(
            [
                TAIWAN_INDEX_HEADLINE_COMPATIBILITY_LIMITATION,
                validation_limitation,
                *[str(value) for value in current.get("limitations") or []],
                *[
                    str(value)
                    for value in resolved_health.get("limitations") or []
                ],
            ]
        )
    )
    limitation_codes = [value for value in limitation_codes if value]
    return {
        "index_id": str(current.get("index_id") or index_item.get("index_id") or ""),
        "status": str(
            resolved_health.get("status") or current.get("status") or "missing"
        ),
        "value": _number(
            current.get("close")
            if current.get("close") is not None
            else current.get("value")
        ),
        "previous_close": change_projection["previous_close"],
        "change": change_projection["change"],
        "change_pct": change_projection["change_pct"],
        "event_time": current.get("as_of") or current.get("observed_at"),
        "trade_date": current.get("trade_date"),
        "source": source,
        "provider": provider,
        "selected_candidate": (
            "compatibility_current_data_core"
            if has_current_data_core
            else "compatibility_index_summary"
        ),
        "authority": _index_candidate_authority(
            source=source,
            provider=provider,
        ),
        "finalization": "unknown",
        "official_source": bool(current.get("official")),
        "official_close_confirmed": False,
        "provisional_estimate": bool(current.get("provisional")),
        "selection_reason": (
            "compatibility_current_data_core_fallback"
            if has_current_data_core
            else "compatibility_index_summary_fallback"
        ),
        "acquisition_policy": str(
            index_item.get("acquisition_policy") or "cache_only"
        ),
        "resolution_version": TAIWAN_INDEX_HEADLINE_COMPATIBILITY_VERSION,
        "resolution_id": "",
        "official_close_status": "not_available_yet",
        "official": False,
        "provisional": bool(current.get("provisional")),
        "decision_usable": bool(current.get("decision_usable")),
        "coverage_status": str(
            resolved_health.get("status") or current.get("status") or "missing"
        ),
        "quote_semantics": (
            "compatibility_current_data_core"
            if has_current_data_core
            else "compatibility_index_summary"
        ),
        "delivery_status": str(current.get("status") or "missing"),
        "freshness_status": str(resolved_health.get("status") or "unknown"),
        "warnings": limitation_codes,
        "limitations": limitation_codes,
        "compatibility_fallback": True,
        "compatibility_fallback_reason": validation_limitation,
    }


def project_taiwan_index_quote_side(
    index_item: dict[str, Any],
) -> dict[str, Any] | None:
    """Project resolved index truth into the shared intraday quote-side shape."""

    headline = project_taiwan_index_headline(index_item)
    if headline is None:
        return None

    value = _number(headline.get("value"))
    previous_close = _number(headline.get("previous_close"))
    event_time = headline.get("event_time")
    source = str(headline.get("source") or "") or None
    provider = str(headline.get("provider") or "") or None
    selected_candidate = str(headline.get("selected_candidate") or "")
    limitations = list(
        dict.fromkeys(
            [
                *(
                    str(item)
                    for item in headline.get("limitations") or []
                    if item
                ),
                *(
                    str(item)
                    for item in headline.get("warnings") or []
                    if item
                ),
            ]
        )
    )
    raw_resolution = (
        index_item.get("resolution")
        if isinstance(index_item.get("resolution"), dict)
        else {}
    )
    selected_age_seconds = next(
        (
            candidate.get("age_seconds")
            for candidate in raw_resolution.get("candidates") or []
            if isinstance(candidate, dict)
            and candidate.get("candidate") == selected_candidate
        ),
        None,
    )
    current_trade_available = bool(
        value is not None and selected_candidate == "intraday_last_trade"
    )
    current_observation = (
        {
            "value": value,
            "observed_at": event_time,
            "confirmed_at": None,
            "price_semantics": headline.get("quote_semantics") or "unavailable",
            "provider": provider,
            "source": source,
            "status": headline.get("freshness_status") or "unknown",
            "is_fallback": bool(headline.get("compatibility_fallback")),
            "limitations": limitations,
            "previous_close": previous_close,
            "previous_close_trade_date": raw_resolution.get(
                "selected_previous_close_trade_date"
            ),
            "previous_close_source": raw_resolution.get(
                "selected_previous_close_source"
            ),
            "previous_close_provider": raw_resolution.get(
                "selected_previous_close_provider"
            ),
            "previous_close_status": (
                "current" if previous_close is not None else "missing"
            ),
            "freshness_status": headline.get("freshness_status") or "unknown",
            "decision_usable": bool(headline.get("decision_usable")),
        }
        if value is not None
        else None
    )
    return {
        "current_observation": current_observation,
        "previous_close": previous_close,
        "price_diagnostics": {
            "history_price_source": None,
            "latest_history_time": None,
            "latest_history_price": None,
            "latest_actual_trade_time": event_time,
            "latest_actual_trade_price": value,
            "current_price_source": source,
            "lag_seconds": selected_age_seconds,
            "current_trade_available": current_trade_available,
            "current_trade_unavailable_reason": (
                None
                if current_trade_available
                else "canonical_index_current_trade_unavailable"
            ),
            "current_price_applied_to_history": False,
        },
        "capabilities": {
            "supports_volume": False,
            "supports_vwap": False,
            "supports_price_limit": False,
            "supports_quote_depth": False,
        },
        "source": source,
        "trade_date": headline.get("trade_date"),
        "updated_at": event_time,
        "resolution_version": headline.get("resolution_version"),
        "resolution_id": headline.get("resolution_id"),
        "selected_candidate": headline.get("selected_candidate"),
        "quote_semantics": headline.get("quote_semantics"),
        "limitations": limitations,
    }


__all__ = [
    "TAIWAN_INDEX_ACQUISITION_POLICIES",
    "TAIWAN_INDEX_HEADLINE_COMPATIBILITY_LIMITATION",
    "TAIWAN_INDEX_HEADLINE_COMPATIBILITY_VERSION",
    "TAIWAN_INDEX_RESOLUTION_VERSION",
    "ResolvedTaiwanIndexTruth",
    "TaiwanIndexTruthCandidate",
    "TaiwanIndexTruthObservation",
    "index_candidate_date",
    "index_candidate_datetime",
    "latest_intraday_point",
    "normalize_index_acquisition_policy",
    "project_taiwan_index_headline",
    "project_taiwan_index_quote_side",
    "resolve_taiwan_index_quote_state",
    "resolve_taiwan_index_truth",
]
