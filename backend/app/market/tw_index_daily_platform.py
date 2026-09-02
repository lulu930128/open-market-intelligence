"""Explicit refresh command for official Taiwan index Base-1d candidates."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import time as time_module
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.market.daily_ohlcv_platform import (
    TaiwanDailyRefreshResult,
    TaiwanOfficialDailyPlatform,
)
from app.market.daily_price_candidates import TaiwanCompletedDailyCandidateReader
from app.market.daily_price_repository import TaiwanOfficialDailyBarRepository
from app.market.daily_price_transaction import TaiwanOfficialDailyTransaction
from app.market.providers.tw_index_daily_bars import (
    TAIEX_DAILY_PARSER_VERSION,
    TAIEX_DAILY_RESOURCE_ID,
    TAIEX_OFFICIAL_DAILY_DESCRIPTOR,
    TaiwanIndexDailyBarAcquisitionExecutor,
    parse_taiex_official_daily_bars,
    parse_tpex_official_5s_series,
)
from app.market.providers import tpex, twse
from app.market.taiwan_rules import expected_daily_price_date
from app.market.trading_calendar import (
    TAIWAN_TZ,
    latest_completed_taiwan_session_date,
    previous_taiwan_trading_day,
)
from app.market.tw_instrument import resolve_taiwan_instrument
from app.market.tw_bar_service import TaiwanBarService
from app.market.tw_bar_contracts import (
    TAIEX_OFFICIAL_DAILY_SOURCE,
    TPEX_DERIVED_DAILY_PROVIDER,
    TPEX_OFFICIAL_5S_COMPONENT_SOURCE,
    TPEX_OFFICIAL_5S_PARSER_VERSION,
)
from app.market.tw_bar_materialization_transaction import (
    TaiwanBarMaterializationTransaction,
)
from app.market.tw_daily_reconciliation import TaiwanDailyReconciliationTransaction
from app.market_data.integration_contracts import (
    AcquisitionResourceAttempt,
    AcquisitionStatus,
    AcquisitionSummary,
    InstrumentTarget,
    PersistenceSummary,
    RawFetchReceiptV1,
    RefreshRequirementV1,
)
from app.market_data.gateway import BarAcquisitionResult
from app.market_data.policies import DataPurpose

TAIWAN_INDEX_DAILY_BOOTSTRAP_MAX_SESSIONS = 300


class HttpResponseLike(Protocol):
    status_code: int
    text: str
    headers: Mapping[str, str]
    url: Any


TpexDailyFetcher = Callable[[date], HttpResponseLike]
TaiexHistoryFetcher = Callable[[date], HttpResponseLike]
Sleeper = Callable[[float], None]


def _header(response: HttpResponseLike, name: str) -> str | None:
    for key, value in response.headers.items():
        if str(key).casefold() == name.casefold():
            return str(value)
    return None


def refresh_taiex_official_daily_bar(
    db: Session,
    *,
    trade_date: date,
    requested_at: datetime | None = None,
    acquisition: TaiwanIndexDailyBarAcquisitionExecutor | None = None,
) -> TaiwanDailyRefreshResult:
    """Acquire one release-qualified TAIEX 1d candidate through shared planning."""

    effective_requested_at = requested_at or datetime.now(TAIWAN_TZ)
    if (
        effective_requested_at.tzinfo is None
        or effective_requested_at.utcoffset() is None
    ):
        raise ValueError("requested_at must be timezone-aware")
    expected_date = expected_daily_price_date(now=effective_requested_at)
    if trade_date != expected_date:
        raise ValueError(
            "TAIEX official daily refresh trade_date must equal latest released "
            f"session ({expected_date})"
        )
    instrument = resolve_taiwan_instrument(db, "TAIEX")
    requirement = RefreshRequirementV1(
        dataset_id="tw.daily.ohlcv",
        target=InstrumentTarget(instrument=instrument),
        from_date=trade_date,
        to_date=trade_date,
        requested_at=effective_requested_at,
        purpose=DataPurpose.REPAIR,
        max_provider_attempts=1,
        max_external_calls=1,
        timeout_seconds=30,
        max_symbols=1,
        max_range_days=1,
        postcondition=(
            f"Latest persisted official TAIEX Base-1d candidate reaches "
            f"{trade_date.isoformat()}."
        ),
    )
    return TaiwanOfficialDailyPlatform(
        reader=TaiwanCompletedDailyCandidateReader(
            TaiwanOfficialDailyBarRepository(db)
        ),
        transaction=TaiwanOfficialDailyTransaction(db),
        acquisition=acquisition or TaiwanIndexDailyBarAcquisitionExecutor(),  # type: ignore[arg-type]
        descriptors=(TAIEX_OFFICIAL_DAILY_DESCRIPTOR,),
    ).refresh_instrument(requirement)


def _month_starts(date_from: date, date_to: date) -> tuple[date, ...]:
    current = date(date_from.year, date_from.month, 1)
    values: list[date] = []
    while current <= date_to:
        values.append(current)
        current = (
            date(current.year + 1, 1, 1)
            if current.month == 12
            else date(current.year, current.month + 1, 1)
        )
    return tuple(values)


def _bootstrap_postcondition(
    db: Session,
    *,
    index_id: str,
    date_from: date,
    date_to: date,
    required_sessions: int,
    expected_latest_trade_date: date | None,
) -> dict[str, Any]:
    reread_at = datetime.now(TAIWAN_TZ)
    series = TaiwanBarService(db).read_bars(
        instrument_id=index_id,
        interval="1d",
        from_time=datetime.combine(date_from, time.min, tzinfo=TAIWAN_TZ),
        to_time=datetime.combine(date_to, time.max, tzinfo=TAIWAN_TZ),
        limit=max(required_sessions, 1),
        include_partial=False,
        requested_at=reread_at,
    )
    in_range = tuple(
        bar
        for bar in series.bars
        if date_from <= bar.start_at.astimezone(TAIWAN_TZ).date() <= date_to
    )
    dates = tuple(bar.start_at.astimezone(TAIWAN_TZ).date() for bar in in_range)
    latest_trade_date = max(dates, default=None)
    satisfied = bool(
        required_sessions > 0
        and len(set(dates)) >= required_sessions
        and latest_trade_date == expected_latest_trade_date
    )
    return {
        "required_session_count": required_sessions,
        "qualified_bar_count": len(set(dates)),
        "postcondition_latest_trade_date": latest_trade_date,
        "postcondition_checked_at": reread_at,
        "postcondition_satisfied": satisfied,
    }


def bootstrap_taiex_official_daily_history(
    db: Session,
    *,
    date_from: date,
    date_to: date,
    max_sessions: int = TAIWAN_INDEX_DAILY_BOOTSTRAP_MAX_SESSIONS,
    requested_at: datetime | None = None,
    fetcher: TaiexHistoryFetcher | None = None,
) -> dict[str, Any]:
    """Materialize bounded TAIEX history one official monthly receipt at a time."""

    if date_from > date_to:
        raise ValueError("TAIEX history date_from must not exceed date_to")
    if (
        max_sessions < 1
        or max_sessions > TAIWAN_INDEX_DAILY_BOOTSTRAP_MAX_SESSIONS
    ):
        raise ValueError("TAIEX history max_sessions must be between 1 and 300")
    if (date_to - date_from).days > 550:
        raise ValueError("TAIEX history range exceeds the bounded 300-session window")
    effective_requested_at = requested_at or datetime.now(TAIWAN_TZ)
    if (
        effective_requested_at.tzinfo is None
        or effective_requested_at.utcoffset() is None
    ):
        raise ValueError("requested_at must be timezone-aware")
    instrument = resolve_taiwan_instrument(db, "TAIEX")
    planned_sessions = plan_tpex_completed_derived_daily_history(
        date_from=date_from,
        date_to=date_to,
        max_sessions=max_sessions,
    )
    transaction = TaiwanOfficialDailyTransaction(db)
    receipts_written = bars_written = bars_unchanged = 0
    raw_result_ids: list[int] = []
    observed_dates: list[date] = []
    months_processed: list[str] = []
    # Walk backward so a bounded request always retains the most recent
    # sessions instead of silently filling the budget with the oldest month.
    for month_start in reversed(_month_starts(date_from, date_to)):
        month_end = (
            date(month_start.year + 1, 1, 1)
            if month_start.month == 12
            else date(month_start.year, month_start.month + 1, 1)
        ) - timedelta(days=1)
        range_start = max(month_start, date_from)
        range_end = min(month_end, date_to)
        response = (
            fetcher(month_start)
            if fetcher is not None
            else twse.get_response(
                twse.INDEX_DAILY_OHLC_URL,
                timeout_seconds=30,
                params={"response": "json", "date": month_start.strftime("%Y%m%d")},
            )
        )
        raw_text = str(response.text or "")
        content_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        fetched_at = datetime.now(timezone.utc)
        receipt = RawFetchReceiptV1(
            provider=TAIEX_OFFICIAL_DAILY_DESCRIPTOR.provider_key,
            source=TAIEX_OFFICIAL_DAILY_SOURCE,
            resource_id=TAIEX_DAILY_RESOURCE_ID,
            fetched_at=fetched_at,
            method="GET",
            url=str(response.url or twse.INDEX_DAILY_OHLC_URL),
            status_code=int(response.status_code),
            content_type=_header(response, "content-type"),
            content_hash=content_hash,
            raw_text=raw_text,
            parser_version=TAIEX_DAILY_PARSER_VERSION,
            error_message=(
                None
                if 200 <= int(response.status_code) < 300
                else f"HTTP {response.status_code}"
            ),
        )
        if receipt.error_message:
            raise ValueError(receipt.error_message)
        observations = parse_taiex_official_daily_bars(
            raw_text,
            instrument=instrument,
            fetched_at=fetched_at,
            content_hash=content_hash,
            from_date=range_start,
            to_date=range_end,
        )
        if len(observed_dates) + len(observations) > max_sessions:
            remaining = max_sessions - len(observed_dates)
            observations = observations[-remaining:] if remaining > 0 else ()
        if not observations:
            continue
        requirement = RefreshRequirementV1(
            dataset_id="tw.daily.ohlcv",
            target=InstrumentTarget(instrument=instrument),
            from_date=observations[0].start_at.date(),
            to_date=observations[-1].start_at.date(),
            requested_at=effective_requested_at,
            purpose=DataPurpose.REPAIR,
            max_provider_attempts=1,
            max_external_calls=1,
            timeout_seconds=30,
            max_symbols=1,
            max_range_days=31,
            postcondition="Persist bounded official TAIEX Base-1d history.",
        )
        acquisition = BarAcquisitionResult(
            summary=AcquisitionSummary(
                attempted=True,
                status=AcquisitionStatus.COMPLETED,
                providers_attempted=(TAIEX_OFFICIAL_DAILY_DESCRIPTOR.provider_key,),
                resource_attempts=(
                    AcquisitionResourceAttempt(
                        provider=TAIEX_OFFICIAL_DAILY_DESCRIPTOR.provider_key,
                        resource_id=TAIEX_DAILY_RESOURCE_ID,
                    ),
                ),
                external_calls=1,
            ),
            observations=tuple(observations),
            receipts=(receipt,),
        )
        persistence = transaction.persist_bar_acquisition(requirement, acquisition)
        receipts_written += persistence.receipts_written
        bars_written += persistence.observations_written
        bars_unchanged += persistence.observations_unchanged
        raw_result_ids.extend(persistence.raw_result_ids)
        observed_dates.extend(item.start_at.date() for item in observations)
        months_processed.append(month_start.isoformat())
        if len(observed_dates) >= max_sessions:
            break
    postcondition = _bootstrap_postcondition(
        db,
        index_id="TAIEX",
        date_from=date_from,
        date_to=date_to,
        required_sessions=len(planned_sessions),
        expected_latest_trade_date=(planned_sessions[-1] if planned_sessions else None),
    )
    return {
        "contract_version": "tw.index_daily.bootstrap.v1",
        "status": (
            "success"
            if postcondition["postcondition_satisfied"]
            else "partial"
            if observed_dates
            else "failed"
        ),
        "index_id": "TAIEX",
        "requested_from": date_from,
        "requested_to": date_to,
        "max_sessions": max_sessions,
        "months_processed": months_processed,
        "observed_sessions": len(observed_dates),
        "earliest_trade_date": min(observed_dates, default=None),
        "latest_trade_date": max(observed_dates, default=None),
        "receipts_written": receipts_written,
        "bars_written": bars_written,
        "bars_unchanged": bars_unchanged,
        "raw_result_ids": list(dict.fromkeys(raw_result_ids)),
        **postcondition,
    }


def refresh_tpex_completed_derived_daily_bar(
    db: Session,
    *,
    trade_date: date,
    requested_at: datetime | None = None,
    fetcher: TpexDailyFetcher | None = None,
    max_attempts: int = 3,
    retry_backoff_seconds: float = 1.0,
    sleeper: Sleeper = time_module.sleep,
    allow_historical: bool = False,
) -> PersistenceSummary:
    """Fetch one real post-close 5s receipt and materialize Base-1d atomically."""

    effective_requested_at = requested_at or datetime.now(TAIWAN_TZ)
    if (
        effective_requested_at.tzinfo is None
        or effective_requested_at.utcoffset() is None
    ):
        raise ValueError("requested_at must be timezone-aware")
    expected_date = latest_completed_taiwan_session_date(effective_requested_at)
    if trade_date != expected_date and not (
        allow_historical and trade_date < expected_date
    ):
        raise ValueError(
            "TPEX derived daily refresh trade_date must equal latest completed "
            f"session ({expected_date})"
        )
    if max_attempts < 1 or max_attempts > 3:
        raise ValueError("TPEX daily refresh max_attempts must be between 1 and 3")
    if retry_backoff_seconds < 0 or retry_backoff_seconds > 30:
        raise ValueError("TPEX daily retry_backoff_seconds must be between 0 and 30")
    response: HttpResponseLike | None = None
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = (
                fetcher(trade_date)
                if fetcher is not None
                else tpex.get_response(
                    tpex.INDEX_5S_URL,
                    timeout_seconds=30,
                    params={
                        "response": "json",
                        "date": trade_date.strftime("%Y/%m/%d"),
                    },
                )
            )
            if 200 <= int(response.status_code) < 300:
                break
            last_error = ValueError(f"HTTP {response.status_code}")
        except Exception as exc:
            last_error = exc
            response = None
        if attempt < max_attempts:
            sleeper(retry_backoff_seconds * attempt)
    if response is None or not 200 <= int(response.status_code) < 300:
        detail = str(last_error or "provider response unavailable")
        raise ValueError(
            f"TPEX_COMPLETED_DAILY_ACQUISITION_FAILED after {max_attempts} attempts: {detail}"
        ) from last_error
    raw_text = str(response.text or "")
    content_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    fetched_at = datetime.now(timezone.utc)
    receipt = RawFetchReceiptV1(
        provider=TPEX_DERIVED_DAILY_PROVIDER,
        source=TPEX_OFFICIAL_5S_COMPONENT_SOURCE,
        resource_id="tpex_index_5s",
        fetched_at=fetched_at,
        method="GET",
        url=str(response.url or tpex.INDEX_5S_URL),
        status_code=int(response.status_code),
        content_type=_header(response, "content-type"),
        content_hash=content_hash,
        raw_text=raw_text,
        parser_version=TPEX_OFFICIAL_5S_PARSER_VERSION,
        error_message=(
            None
            if 200 <= int(response.status_code) < 300
            else f"HTTP {response.status_code}"
        ),
    )
    if receipt.error_message is not None:
        raise ValueError(receipt.error_message)
    parsed = parse_tpex_official_5s_series(
        raw_text,
        instrument=resolve_taiwan_instrument(db, "TPEX"),
        fetched_at=fetched_at,
        content_hash=content_hash,
        expected_trade_date=trade_date,
    )
    persistence = TaiwanBarMaterializationTransaction(
        db
    ).persist_tpex_completed_daily_acquisition(
        receipt=receipt,
        components=parsed.components,
        formal_close_component=parsed.formal_close_component,
        as_of=effective_requested_at,
    )
    try:
        TaiwanDailyReconciliationTransaction(db).reconcile_tpex_daily_stat(
            trade_date=trade_date
        )
    except ValueError as exc:
        if str(exc) != "TPEX_OFFICIAL_DAILY_STAT_EVIDENCE_MISSING":
            raise
    return persistence


def plan_tpex_completed_derived_daily_history(
    *,
    date_from: date,
    date_to: date,
    max_sessions: int = TAIWAN_INDEX_DAILY_BOOTSTRAP_MAX_SESSIONS,
) -> tuple[date, ...]:
    """Return the bounded completed-session plan without provider I/O or writes."""

    if date_from > date_to:
        raise ValueError("TPEX history date_from must not exceed date_to")
    if (
        max_sessions < 1
        or max_sessions > TAIWAN_INDEX_DAILY_BOOTSTRAP_MAX_SESSIONS
    ):
        raise ValueError("TPEX history max_sessions must be between 1 and 300")
    cursor = previous_taiwan_trading_day(date_to, include_value=True)
    sessions: list[date] = []
    while cursor >= date_from and len(sessions) < max_sessions:
        sessions.append(cursor)
        cursor = previous_taiwan_trading_day(cursor, include_value=False)
    sessions.reverse()
    return tuple(sessions)


def bootstrap_tpex_completed_derived_daily_history(
    db: Session,
    *,
    date_from: date,
    date_to: date,
    max_sessions: int = TAIWAN_INDEX_DAILY_BOOTSTRAP_MAX_SESSIONS,
    requested_at: datetime | None = None,
    fetcher: TpexDailyFetcher | None = None,
    max_attempts: int = 3,
    retry_backoff_seconds: float = 1.0,
    sleeper: Sleeper = time_module.sleep,
) -> dict[str, Any]:
    """Bounded historical TPEX 5s materialization without synthetic OHLC."""

    effective_requested_at = requested_at or datetime.now(TAIWAN_TZ)
    sessions = plan_tpex_completed_derived_daily_history(
        date_from=date_from,
        date_to=date_to,
        max_sessions=max_sessions,
    )
    results: list[dict[str, Any]] = []
    for trade_date in sessions:
        try:
            persistence = refresh_tpex_completed_derived_daily_bar(
                db,
                trade_date=trade_date,
                requested_at=effective_requested_at,
                fetcher=fetcher,
                max_attempts=max_attempts,
                retry_backoff_seconds=retry_backoff_seconds,
                sleeper=sleeper,
                allow_historical=True,
            )
            results.append(
                {
                    "trade_date": trade_date,
                    "status": "success",
                    "receipts_written": persistence.receipts_written,
                    "bars_written": persistence.observations_written,
                    "bars_unchanged": persistence.observations_unchanged,
                    "raw_result_ids": list(persistence.raw_result_ids),
                }
            )
        except Exception as exc:
            db.rollback()
            results.append(
                {
                    "trade_date": trade_date,
                    "status": "failed",
                    "failure_reason": f"{type(exc).__name__}: {exc}",
                }
            )
    success_count = sum(item["status"] == "success" for item in results)
    postcondition = _bootstrap_postcondition(
        db,
        index_id="TPEX",
        date_from=date_from,
        date_to=date_to,
        required_sessions=len(sessions),
        expected_latest_trade_date=(sessions[-1] if sessions else None),
    )
    return {
        "contract_version": "tw.index_daily.bootstrap.v1",
        "status": (
            "success"
            if (
                results
                and success_count == len(results)
                and postcondition["postcondition_satisfied"]
            )
            else "partial"
            if success_count
            else "failed"
        ),
        "index_id": "TPEX",
        "requested_from": date_from,
        "requested_to": date_to,
        "max_sessions": max_sessions,
        "processed_sessions": len(results),
        "successful_sessions": success_count,
        "failed_sessions": len(results) - success_count,
        "receipts_written": sum(
            int(item.get("receipts_written") or 0) for item in results
        ),
        "bars_written": sum(int(item.get("bars_written") or 0) for item in results),
        "bars_unchanged": sum(
            int(item.get("bars_unchanged") or 0) for item in results
        ),
        "results": results,
        **postcondition,
    }


__all__ = [
    "TAIWAN_INDEX_DAILY_BOOTSTRAP_MAX_SESSIONS",
    "bootstrap_taiex_official_daily_history",
    "bootstrap_tpex_completed_derived_daily_history",
    "plan_tpex_completed_derived_daily_history",
    "refresh_taiex_official_daily_bar",
    "refresh_tpex_completed_derived_daily_bar",
]
