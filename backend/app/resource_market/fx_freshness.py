from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import json
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


FxFreshnessPurpose = Literal["spot_quote", "adr_alignment", "daily_trend"]

FX_TIMEZONE_NAME = "America/New_York"
FX_SPOT_DELAYED_AFTER_SECONDS = 30 * 60
FX_SPOT_STALE_AFTER_SECONDS = 4 * 60 * 60
FX_FUTURE_TOLERANCE_SECONDS = 5 * 60
FX_HOLIDAY_CALENDAR_LIMITATION = "fx_holiday_calendar_unverified"


@dataclass(frozen=True)
class FxFreshnessEvaluation:
    purpose: FxFreshnessPurpose
    status: str
    usable: bool
    session_status: str
    session_reason: str
    expected_data_date: date | None
    actual_data_date: date | None
    event_time: datetime | None
    fetched_at: datetime | None
    event_age_seconds: int | None
    fetch_age_seconds: int | None
    next_expected_update_at: datetime | None
    refresh_eligible: bool
    stale_after_seconds: int | None
    reason_codes: tuple[str, ...]
    limitations: tuple[str, ...] = (FX_HOLIDAY_CALENDAR_LIMITATION,)

    def as_payload(self) -> dict[str, Any]:
        return {
            "purpose": self.purpose,
            "status": self.status,
            "usable": self.usable,
            "session_status": self.session_status,
            "session_reason": self.session_reason,
            "expected_data_date": _iso(self.expected_data_date),
            "actual_data_date": _iso(self.actual_data_date),
            "event_time": _iso(self.event_time),
            "fetched_at": _iso(self.fetched_at),
            "event_age_seconds": self.event_age_seconds,
            "fetch_age_seconds": self.fetch_age_seconds,
            "next_expected_update_at": _iso(self.next_expected_update_at),
            "refresh_eligible": self.refresh_eligible,
            "stale_after_seconds": self.stale_after_seconds,
            "reason_codes": list(self.reason_codes),
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class _FxSession:
    status: str
    reason: str
    latest_completed_data_date: date
    next_open_at: datetime | None


def fx_daily_data_date(
    bar_time: datetime | None,
    raw_payload_json: str | dict[str, Any] | None = None,
) -> date | None:
    """Resolve a provider-labelled FX daily bar to its local data date."""

    if bar_time is None:
        return None
    timezone_name = _provider_exchange_timezone(raw_payload_json)
    if timezone_name:
        try:
            return _as_utc(bar_time).astimezone(ZoneInfo(timezone_name)).date()
        except ZoneInfoNotFoundError:
            pass
    return _as_utc(bar_time).date()


def latest_completed_fx_data_date(now: datetime) -> date:
    return _fx_session(_as_utc(now)).latest_completed_data_date


def evaluate_fx_freshness(
    *,
    purpose: FxFreshnessPurpose,
    now: datetime,
    event_time: datetime | None = None,
    fetched_at: datetime | None = None,
    data_date: date | None = None,
    expected_data_date: date | None = None,
    provider_failure: bool = False,
) -> FxFreshnessEvaluation:
    if purpose not in {"spot_quote", "adr_alignment", "daily_trend"}:
        raise ValueError(f"unsupported FX freshness purpose: {purpose}")

    checked_at = _as_utc(now)
    normalized_event_time = _as_optional_utc(event_time)
    normalized_fetched_at = _as_optional_utc(fetched_at)
    session = _fx_session(checked_at)
    actual_data_date = data_date or _event_data_date(normalized_event_time)
    expected = (
        expected_data_date
        if expected_data_date is not None
        else session.latest_completed_data_date
        if purpose == "daily_trend"
        else None
    )
    event_age = _age_seconds(checked_at, normalized_event_time)
    fetch_age = _age_seconds(checked_at, normalized_fetched_at)
    next_expected_update = (
        _next_daily_completion_at(checked_at)
        if purpose == "daily_trend"
        else session.next_open_at
    )

    if normalized_event_time is None and actual_data_date is None:
        return _evaluation(
            purpose=purpose,
            status="missing",
            usable=False,
            session=session,
            expected_data_date=expected,
            actual_data_date=None,
            event_time=None,
            fetched_at=normalized_fetched_at,
            event_age_seconds=None,
            fetch_age_seconds=fetch_age,
            next_expected_update_at=next_expected_update,
            refresh_eligible=session.status == "open",
            stale_after_seconds=(
                FX_SPOT_STALE_AFTER_SECONDS if purpose == "spot_quote" else None
            ),
            reason_codes=("fx_observation_missing",),
        )

    if normalized_event_time is not None and event_age is not None and event_age < -FX_FUTURE_TOLERANCE_SECONDS:
        return _evaluation(
            purpose=purpose,
            status="future",
            usable=False,
            session=session,
            expected_data_date=expected,
            actual_data_date=actual_data_date,
            event_time=normalized_event_time,
            fetched_at=normalized_fetched_at,
            event_age_seconds=event_age,
            fetch_age_seconds=fetch_age,
            next_expected_update_at=next_expected_update,
            refresh_eligible=session.status == "open",
            stale_after_seconds=(
                FX_SPOT_STALE_AFTER_SECONDS if purpose == "spot_quote" else None
            ),
            reason_codes=("fx_event_time_in_future",),
        )

    if purpose in {"adr_alignment", "daily_trend"}:
        result = _evaluate_date_aligned(
            purpose=purpose,
            session=session,
            expected_data_date=expected,
            actual_data_date=actual_data_date,
        )
    else:
        result = _evaluate_spot(
            session=session,
            event_age_seconds=event_age,
            actual_data_date=actual_data_date,
        )

    status, usable, refresh_eligible, reason_codes = result
    if provider_failure:
        status = "provider_failure"
        reason_codes = (*reason_codes, "fx_provider_refresh_failed")

    return _evaluation(
        purpose=purpose,
        status=status,
        usable=usable,
        session=session,
        expected_data_date=expected,
        actual_data_date=actual_data_date,
        event_time=normalized_event_time,
        fetched_at=normalized_fetched_at,
        event_age_seconds=event_age,
        fetch_age_seconds=fetch_age,
        next_expected_update_at=next_expected_update,
        refresh_eligible=refresh_eligible,
        stale_after_seconds=(
            FX_SPOT_STALE_AFTER_SECONDS if purpose == "spot_quote" else None
        ),
        reason_codes=reason_codes,
    )


def _evaluate_date_aligned(
    *,
    purpose: FxFreshnessPurpose,
    session: _FxSession,
    expected_data_date: date | None,
    actual_data_date: date | None,
) -> tuple[str, bool, bool, tuple[str, ...]]:
    if expected_data_date is None or actual_data_date is None:
        return (
            "missing",
            False,
            session.status == "open",
            ("fx_data_date_missing",),
        )
    if actual_data_date > expected_data_date:
        return (
            "future",
            False,
            session.status == "open",
            ("fx_observation_after_expected_date",),
        )
    if actual_data_date < expected_data_date:
        return (
            "stale",
            False,
            session.status == "open",
            ("fx_observation_before_expected_date",),
        )
    if purpose == "adr_alignment":
        return "current", True, False, ("fx_matches_adr_trade_date",)
    return (
        "latest_completed_session",
        True,
        False,
        ("fx_latest_completed_daily_session",),
    )


def _evaluate_spot(
    *,
    session: _FxSession,
    event_age_seconds: int | None,
    actual_data_date: date | None,
) -> tuple[str, bool, bool, tuple[str, ...]]:
    if event_age_seconds is None:
        return "missing", False, session.status == "open", ("fx_event_time_missing",)
    if session.status in {"closed", "maintenance"}:
        if (
            actual_data_date is not None
            and actual_data_date >= session.latest_completed_data_date
        ):
            return (
                "latest_completed_session",
                True,
                False,
                (f"fx_{session.status}_latest_completed_session",),
            )
        return (
            "stale",
            False,
            False,
            (f"fx_{session.status}_observation_behind",),
        )
    if event_age_seconds > FX_SPOT_STALE_AFTER_SECONDS:
        return "stale", False, True, ("fx_spot_age_exceeded",)
    if event_age_seconds > FX_SPOT_DELAYED_AFTER_SECONDS:
        return "delayed", True, False, ("fx_spot_best_effort_delay",)
    return "current", True, False, ("fx_spot_within_live_window",)


def _fx_session(now: datetime) -> _FxSession:
    local = now.astimezone(_fx_timezone())
    weekday = local.weekday()
    local_clock = local.timetz().replace(tzinfo=None)
    at_or_after_close = local_clock >= time(17, 0)
    before_sunday_open = local_clock < time(17, 0)

    if weekday == 5 or (weekday == 6 and before_sunday_open) or (weekday == 4 and at_or_after_close):
        return _FxSession(
            status="closed",
            reason="fx_weekend_close",
            latest_completed_data_date=(
                local.date() if weekday == 4 else _previous_weekday(local.date())
            ),
            next_open_at=_next_fx_open(local).astimezone(timezone.utc),
        )
    if weekday in {0, 1, 2, 3} and time(17, 0) <= local_clock < time(18, 0):
        next_open = datetime.combine(
            local.date(),
            time(18, 0),
            tzinfo=_fx_timezone(),
        )
        return _FxSession(
            status="maintenance",
            reason="fx_daily_maintenance",
            latest_completed_data_date=local.date(),
            next_open_at=next_open.astimezone(timezone.utc),
        )
    return _FxSession(
        status="open",
        reason="fx_24x5_session_open",
        latest_completed_data_date=_latest_completed_daily_date(local),
        next_open_at=None,
    )


def _latest_completed_daily_date(local: datetime) -> date:
    if local.weekday() < 5 and local.time() >= time(17, 0):
        return local.date()
    return _previous_weekday(local.date())


def _previous_weekday(value: date) -> date:
    candidate = value - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def _next_fx_open(local: datetime) -> datetime:
    timezone_value = _fx_timezone()
    days_until_sunday = (6 - local.weekday()) % 7
    candidate_date = local.date() + timedelta(days=days_until_sunday)
    candidate = datetime.combine(candidate_date, time(17, 0), tzinfo=timezone_value)
    if candidate <= local:
        candidate += timedelta(days=7)
    return candidate


def _next_daily_completion_at(now: datetime) -> datetime:
    local = now.astimezone(_fx_timezone())
    candidate_date = local.date()
    if local.weekday() >= 5 or local.time() >= time(17, 0):
        candidate_date += timedelta(days=1)
    while candidate_date.weekday() >= 5:
        candidate_date += timedelta(days=1)
    candidate = datetime.combine(
        candidate_date,
        time(17, 0),
        tzinfo=_fx_timezone(),
    )
    return candidate.astimezone(timezone.utc)


def _fx_timezone():
    try:
        return ZoneInfo(FX_TIMEZONE_NAME)
    except ZoneInfoNotFoundError:
        return timezone(timedelta(hours=-5))


def _event_data_date(value: datetime | None) -> date | None:
    return value.astimezone(_fx_timezone()).date() if value is not None else None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _as_optional_utc(value: datetime | None) -> datetime | None:
    return _as_utc(value) if value is not None else None


def _provider_exchange_timezone(
    raw_payload_json: str | dict[str, Any] | None,
) -> str | None:
    payload: Any = raw_payload_json
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError):
            return None
    if not isinstance(payload, dict):
        return None
    timezone_name = payload.get("exchange_timezone_name")
    return timezone_name.strip() if isinstance(timezone_name, str) else None


def _age_seconds(now: datetime, value: datetime | None) -> int | None:
    if value is None:
        return None
    return int((now - value).total_seconds())


def _evaluation(
    *,
    purpose: FxFreshnessPurpose,
    status: str,
    usable: bool,
    session: _FxSession,
    expected_data_date: date | None,
    actual_data_date: date | None,
    event_time: datetime | None,
    fetched_at: datetime | None,
    event_age_seconds: int | None,
    fetch_age_seconds: int | None,
    next_expected_update_at: datetime | None,
    refresh_eligible: bool,
    stale_after_seconds: int | None,
    reason_codes: tuple[str, ...],
) -> FxFreshnessEvaluation:
    return FxFreshnessEvaluation(
        purpose=purpose,
        status=status,
        usable=usable,
        session_status=session.status,
        session_reason=session.reason,
        expected_data_date=expected_data_date,
        actual_data_date=actual_data_date,
        event_time=event_time,
        fetched_at=fetched_at,
        event_age_seconds=event_age_seconds,
        fetch_age_seconds=fetch_age_seconds,
        next_expected_update_at=next_expected_update_at,
        refresh_eligible=refresh_eligible,
        stale_after_seconds=stale_after_seconds,
        reason_codes=reason_codes,
    )


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
