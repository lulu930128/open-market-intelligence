from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
from typing import Any

from sqlalchemy.orm import Query, Session

from app.db.models import (
    JobRun,
    MarketChipDaily,
    MarketIntradayBar,
    StockMaster,
    TaiwanMarketMinuteState,
    TaiwanStockQuoteSnapshot,
)
from app.market.calendar_status import build_taiwan_calendar_status
from app.market.indices import get_market_index_summary
from app.market.quote_depth import TAIWAN_STOCK_QUOTE_DEPTH_LIVE_MAX_AGE_SECONDS
from app.market.quote_contract_health import (
    build_taiwan_quote_provider_availability,
    build_taiwan_quote_scheduler_contract,
)
from app.market.taiwan_market_state import SUPPORTED_MARKETS
from app.market.trading_calendar import TAIWAN_TZ
from app.market.taiwan_rules import (
    TAIWAN_DATASET_FINANCIAL_METRICS,
    TAIWAN_DATASET_INSTITUTIONAL_TRADE,
    TAIWAN_DATASET_MARGIN_TRADING,
    TAIWAN_DATASET_SPECS,
    TaiwanDatasetSpec,
    expected_date_for_dataset,
    expected_financial_metrics_period,
    is_equity_only_dataset_required,
)
from app.observability.provider_health import (
    enrich_source_health_entries,
    sync_source_health_snapshots,
)
from app.observability.status_taxonomy import summarize_status_dimensions
from app.observability.source_health_contract import (
    daily_row_status,
    freshness_lag_days as _freshness_lag,
    generated_at as _generated_at,
    summarize_source_health,
)


MARKET_CHIP_RESOURCE = "market_chip_daily"
DAILY_METRIC_REPAIR_JOB_TYPES = {
    TAIWAN_DATASET_INSTITUTIONAL_TRADE: "scheduler.market_daily_refresh",
    TAIWAN_DATASET_MARGIN_TRADING: "scheduler.market_margin_daily_refresh",
}


@dataclass(frozen=True)
class TaiwanSourceHealthEntry:
    resource: str
    label: str
    frequency: str
    target: str
    status: str
    ok: bool
    row_count: int
    required: bool = True
    latest_data_date: date | None = None
    latest_data_key: str | None = None
    latest_updated_at: datetime | None = None
    expected_data_date: date | None = None
    expected_data_key: str | None = None
    freshness_lag_days: int | None = None
    release_status: str | None = None
    release_is_released: bool | None = None
    release_at: str | None = None
    next_release_at: str | None = None
    data_quality: str = "unknown"
    reason: str = ""
    provider: str | None = None
    source: str | None = None
    latest_observed_at: datetime | None = None
    age_seconds: int | None = None
    stale_after_seconds: int | None = None
    health_dimensions: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource": self.resource,
            "label": self.label,
            "frequency": self.frequency,
            "target": self.target,
            "status": self.status,
            "ok": self.ok,
            "row_count": self.row_count,
            "required": self.required,
            "latest_data_date": self.latest_data_date.isoformat() if self.latest_data_date else None,
            "latest_data_key": self.latest_data_key,
            "latest_updated_at": self.latest_updated_at.isoformat() if self.latest_updated_at else None,
            "expected_data_date": self.expected_data_date.isoformat() if self.expected_data_date else None,
            "expected_data_key": self.expected_data_key,
            "freshness_lag_days": self.freshness_lag_days,
            "release_status": self.release_status,
            "release_is_released": self.release_is_released,
            "release_at": self.release_at,
            "next_release_at": self.next_release_at,
            "data_quality": self.data_quality,
            "reason": self.reason,
            "provider": self.provider,
            "source": self.source,
            "latest_observed_at": (
                self.latest_observed_at.isoformat()
                if self.latest_observed_at
                else None
            ),
            "age_seconds": self.age_seconds,
            "stale_after_seconds": self.stale_after_seconds,
            "health_dimensions": self.health_dimensions or {},
        }


def _normalized_stock_id(stock_id: str | None) -> str | None:
    normalized = (stock_id or "").strip()
    return normalized or None


def _normalized_index_id(index_id: str | None) -> str | None:
    normalized = (index_id or "").strip().upper()
    return normalized or None


def _target(*, stock_id: str | None = None, index_id: str | None = None) -> str:
    return stock_id or index_id or "all"


def _date_or_none(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _key_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return None
    return str(value)


def _release_window(calendar_status: dict[str, Any], key: str) -> dict[str, Any]:
    windows = calendar_status.get("release_windows")
    if not isinstance(windows, dict):
        return {}
    window = windows.get(key)
    return window if isinstance(window, dict) else {}


def _expected_date(window: dict[str, Any]) -> date | None:
    value = window.get("expected_trade_date")
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _status_for(
    *,
    row_count: int,
    latest_data_date: date | None,
    expected_data_date: date | None = None,
    freshness_required: bool = False,
) -> tuple[str, bool, str, str]:
    return daily_row_status(
        row_count=row_count,
        latest_data_date=latest_data_date,
        expected_data_date=expected_data_date,
        freshness_required=freshness_required,
        empty_reason="No local rows are available for this resource.",
        current_reason="Latest local row is aligned with the expected Taiwan release window.",
        available_reason="Local rows are available; no exact release-date target is enforced.",
    )


def _latest_or_none(query: Query, *order_by):
    return query.order_by(*order_by).first()


def _taiwan_now(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(TAIWAN_TZ)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(TAIWAN_TZ)


def _taiwan_observed_at(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=TAIWAN_TZ)
    return value.astimezone(TAIWAN_TZ)


def _calendar_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _expected_observation_date(calendar_status: dict[str, Any]) -> date | None:
    presentation = calendar_status.get("presentation_session")
    if isinstance(presentation, dict):
        presentation_trade_date = _calendar_date(presentation.get("trade_date"))
        if presentation_trade_date is not None:
            return presentation_trade_date

    current_date = _calendar_date(calendar_status.get("date"))
    if (
        current_date is not None
        and calendar_status.get("is_trading_day")
        and calendar_status.get("phase") in {"regular", "post_close"}
    ):
        return current_date
    return _calendar_date(calendar_status.get("previous_trading_day"))


def _realtime_observation_status(
    *,
    row_count: int,
    latest_data_date: date | None,
    expected_data_date: date | None,
    observed_at: datetime | None,
    current_time: datetime,
    phase: str,
    stale_after_seconds: int,
) -> tuple[str, bool, str, str, int | None]:
    if row_count <= 0 or observed_at is None:
        return (
            "empty",
            False,
            "empty",
            "No local realtime observations are available for this resource.",
            None,
        )

    age_seconds = max(int((current_time - observed_at).total_seconds()), 0)
    if (
        latest_data_date is not None
        and expected_data_date is not None
        and latest_data_date < expected_data_date
    ):
        if phase in {"preopen_pending", "preopen"}:
            return (
                "pending",
                False,
                "pending",
                "The presentation session has rolled forward, but current-session "
                "realtime observations are not expected until the preopen/live window.",
                age_seconds,
            )
        return (
            "stale",
            False,
            "stale",
            f"Latest observation date {latest_data_date.isoformat()} is behind expected "
            f"{expected_data_date.isoformat()}.",
            age_seconds,
        )
    if phase == "regular" and age_seconds > stale_after_seconds:
        return (
            "stale",
            False,
            "stale",
            f"Latest observation is {age_seconds}s old during the live session; "
            f"threshold is {stale_after_seconds}s.",
            age_seconds,
        )
    if phase == "regular":
        return (
            "current",
            True,
            "ok",
            "Latest observation is within the live-session freshness threshold.",
            age_seconds,
        )
    return (
        "available",
        True,
        "ok",
        "Latest completed-session observation is available outside the live session.",
        age_seconds,
    )


def _stock_quote_entry(
    db: Session,
    *,
    stock_id: str | None,
    calendar_status: dict[str, Any],
    current_time: datetime,
    required: bool,
) -> TaiwanSourceHealthEntry:
    query = db.query(TaiwanStockQuoteSnapshot)
    if stock_id is not None:
        query = query.filter(TaiwanStockQuoteSnapshot.stock_id == stock_id)
        row_count = query.count()
        latest = _latest_or_none(
            query,
            TaiwanStockQuoteSnapshot.quote_time.desc(),
            TaiwanStockQuoteSnapshot.id.desc(),
        )
    else:
        # A random row from the entire quote table is not evidence for an
        # all-market quote contract.  Global health is owned by the bounded
        # scheduler universe below.
        row_count = 0
        latest = None
    observed_at = _taiwan_observed_at(latest.quote_time if latest else None)
    latest_data_date = latest.trade_date if latest else None
    expected_data_date = _expected_observation_date(calendar_status)
    status_value, ok, data_quality, reason, age_seconds = _realtime_observation_status(
        row_count=row_count,
        latest_data_date=latest_data_date,
        expected_data_date=expected_data_date,
        observed_at=observed_at,
        current_time=current_time,
        phase=str(calendar_status.get("phase") or "unknown"),
        stale_after_seconds=TAIWAN_STOCK_QUOTE_DEPTH_LIVE_MAX_AGE_SECONDS,
    )
    request_live = {
        "version": "tw.quote.health.v1",
        "axis": "request_live",
        "status": status_value if stock_id else "not_requested",
        "target": stock_id,
        "row_count": row_count,
        "latest_data_date": (
            latest_data_date.isoformat() if latest_data_date else None
        ),
        "expected_data_date": (
            expected_data_date.isoformat() if expected_data_date else None
        ),
        "latest_observed_at": (
            observed_at.isoformat() if observed_at else None
        ),
        "age_seconds": age_seconds,
        "stale_after_seconds": (
            TAIWAN_STOCK_QUOTE_DEPTH_LIVE_MAX_AGE_SECONDS
        ),
        "provider": getattr(latest, "provider", None) if latest else None,
        "source": getattr(latest, "source", None) if latest else None,
        "reason": (
            reason
            if stock_id
            else "No single-symbol live quote was requested."
        ),
    }
    scheduler_contract = build_taiwan_quote_scheduler_contract(
        db,
        trade_date=expected_data_date,
        current_time=current_time,
        stock_id=stock_id,
    )
    provider_availability = build_taiwan_quote_provider_availability(
        db,
        stock_id=stock_id,
    )
    if stock_id is None:
        scheduler_status = str(scheduler_contract.get("status") or "missing")
        status_value = (
            "current"
            if scheduler_status == "ready"
            else "pending"
            if scheduler_status in {"pending", "not_configured"}
            else "partial"
            if scheduler_status == "partial"
            else "disabled"
            if scheduler_status == "disabled"
            else "empty"
        )
        ok = scheduler_status == "ready"
        data_quality = (
            "ok" if ok else "pending" if status_value == "pending" else "partial"
        )
        reason = (
            "Bounded quote scheduler contract is complete."
            if ok
            else "Bounded quote scheduler contract is not complete: "
            f"status={scheduler_status}."
        )
        row_count = int(scheduler_contract.get("captured_count") or 0)
        latest_data_date = expected_data_date if row_count else None
    return TaiwanSourceHealthEntry(
        resource="taiwan_stock_quote_snapshot",
        label="Taiwan stock quote snapshot",
        frequency="realtime",
        target=(
            stock_id
            or str(scheduler_contract.get("target") or "unconfigured")
        ),
        status=status_value,
        ok=ok,
        row_count=row_count,
        required=required,
        latest_data_date=latest_data_date,
        latest_data_key=observed_at.isoformat() if observed_at else None,
        latest_updated_at=getattr(latest, "fetched_at", None) if latest else None,
        expected_data_date=expected_data_date,
        freshness_lag_days=_freshness_lag(expected_data_date, latest_data_date),
        data_quality=data_quality,
        reason=reason,
        provider=getattr(latest, "provider", None) if latest else "twse_mis",
        source=getattr(latest, "source", None) if latest else None,
        latest_observed_at=observed_at,
        age_seconds=age_seconds,
        stale_after_seconds=TAIWAN_STOCK_QUOTE_DEPTH_LIVE_MAX_AGE_SECONDS,
        health_dimensions={
            "version": "tw.quote.health.v1",
            "request_live": request_live,
            "scheduler_contract": scheduler_contract,
            "provider_availability": provider_availability,
        },
    )


def _stock_intraday_entry(
    db: Session,
    *,
    stock_id: str | None,
    calendar_status: dict[str, Any],
    current_time: datetime,
    required: bool,
) -> TaiwanSourceHealthEntry:
    query = db.query(MarketIntradayBar).filter(MarketIntradayBar.interval == "1m")
    if stock_id is not None:
        query = query.filter(MarketIntradayBar.stock_id == stock_id)
    row_count = query.count()
    latest = _latest_or_none(
        query,
        MarketIntradayBar.bar_time.desc(),
        MarketIntradayBar.id.desc(),
    )
    observed_at = _taiwan_observed_at(latest.bar_time if latest else None)
    latest_data_date = observed_at.date() if observed_at else None
    expected_data_date = _expected_observation_date(calendar_status)
    stale_after_seconds = 20 * 60
    status_value, ok, data_quality, reason, age_seconds = _realtime_observation_status(
        row_count=row_count,
        latest_data_date=latest_data_date,
        expected_data_date=expected_data_date,
        observed_at=observed_at,
        current_time=current_time,
        phase=str(calendar_status.get("phase") or "unknown"),
        stale_after_seconds=stale_after_seconds,
    )
    return TaiwanSourceHealthEntry(
        resource="market_intraday_bar_1m",
        label="Taiwan stock intraday 1m bars",
        frequency="realtime",
        target=_target(stock_id=stock_id),
        status=status_value,
        ok=ok,
        row_count=row_count,
        required=required,
        latest_data_date=latest_data_date,
        latest_data_key=observed_at.isoformat() if observed_at else None,
        latest_updated_at=getattr(latest, "updated_at", None) if latest else None,
        expected_data_date=expected_data_date,
        freshness_lag_days=_freshness_lag(expected_data_date, latest_data_date),
        data_quality=data_quality,
        reason=reason,
        provider=getattr(latest, "provider", None) if latest else "yahoo_finance_chart",
        source=getattr(latest, "source", None) if latest else None,
        latest_observed_at=observed_at,
        age_seconds=age_seconds,
        stale_after_seconds=stale_after_seconds,
    )


def _market_minute_state_entry(
    db: Session,
    *,
    calendar_status: dict[str, Any],
    current_time: datetime,
    required: bool,
) -> TaiwanSourceHealthEntry:
    query = db.query(TaiwanMarketMinuteState)
    row_count = query.count()
    latest = _latest_or_none(
        query,
        TaiwanMarketMinuteState.minute_at.desc(),
        TaiwanMarketMinuteState.id.desc(),
    )
    observed_at = _taiwan_observed_at(latest.minute_at if latest else None)
    latest_data_date = latest.trade_date if latest else None
    expected_data_date = _expected_observation_date(calendar_status)
    stale_after_seconds = 90
    status_value, ok, data_quality, reason, age_seconds = _realtime_observation_status(
        row_count=row_count,
        latest_data_date=latest_data_date,
        expected_data_date=expected_data_date,
        observed_at=observed_at,
        current_time=current_time,
        phase=str(calendar_status.get("phase") or "unknown"),
        stale_after_seconds=stale_after_seconds,
    )
    if latest is not None and latest.quality_status not in {"ready", "current"}:
        status_value = "partial" if latest.quality_status == "partial" else status_value
        ok = False if status_value == "partial" else ok
        data_quality = latest.quality_status
        reason = (
            f"Latest minute state quality is {latest.quality_status}; "
            "inspect the underlying TWSE/TPEX breadth sources."
        )
    if latest is not None:
        latest_markets = {
            str(row.market or "").upper()
            for row in (
                db.query(TaiwanMarketMinuteState)
                .filter(TaiwanMarketMinuteState.trade_date == latest.trade_date)
                .filter(TaiwanMarketMinuteState.minute_at == latest.minute_at)
                .all()
            )
            if row.market
        }
        missing_markets = sorted(SUPPORTED_MARKETS - latest_markets)
        if missing_markets:
            status_value = "partial"
            ok = False
            data_quality = "partial"
            reason = (
                "Latest minute state does not cover all Taiwan markets; missing "
                f"{', '.join(missing_markets)}."
            )
    return TaiwanSourceHealthEntry(
        resource="taiwan_market_minute_state",
        label="Taiwan minute-level market state",
        frequency="minute",
        target="all",
        status=status_value,
        ok=ok,
        row_count=row_count,
        required=required,
        latest_data_date=latest_data_date,
        latest_data_key=observed_at.isoformat() if observed_at else None,
        latest_updated_at=getattr(latest, "updated_at", None) if latest else None,
        expected_data_date=expected_data_date,
        freshness_lag_days=_freshness_lag(expected_data_date, latest_data_date),
        data_quality=data_quality,
        reason=reason,
        provider=getattr(latest, "source", None) if latest else None,
        source=getattr(latest, "source", None) if latest else None,
        latest_observed_at=observed_at,
        age_seconds=age_seconds,
        stale_after_seconds=stale_after_seconds,
    )


def _market_breadth_entries(
    db: Session,
    *,
    index_id: str | None,
    calendar_status: dict[str, Any],
    current_time: datetime,
    required: bool,
) -> list[TaiwanSourceHealthEntry]:
    try:
        summary = get_market_index_summary(db, force_refresh=False)
    except Exception as exc:
        return [
            TaiwanSourceHealthEntry(
                resource="market_breadth",
                label="Taiwan market breadth",
                frequency="realtime",
                target=_target(index_id=index_id),
                status="error",
                ok=False,
                row_count=0,
                required=required,
                data_quality="error",
                reason=f"Cached market breadth could not be read: {exc}",
            )
        ]

    summary_as_of = _taiwan_observed_at(summary.get("as_of"))
    expected_data_date = _expected_observation_date(calendar_status)
    entries: list[TaiwanSourceHealthEntry] = []
    for item in summary.get("indices") or []:
        if not isinstance(item, dict):
            continue
        candidate_index_id = str(item.get("index_id") or "").upper()
        if candidate_index_id not in {"TAIEX", "TPEX"}:
            continue
        if index_id is not None and candidate_index_id != index_id:
            continue
        breadth = item.get("breadth") if isinstance(item.get("breadth"), dict) else {}
        breadth_status = (
            item.get("breadth_status")
            if isinstance(item.get("breadth_status"), dict)
            else {}
        )
        observed_at = (
            _taiwan_observed_at(breadth.get("snapshot_as_of"))
            or _taiwan_observed_at(breadth.get("as_of"))
            or summary_as_of
        )
        latest_data_date = _calendar_date(breadth.get("trade_date"))
        raw_status = str(breadth_status.get("status") or "failed")
        age_seconds = (
            max(int((current_time - observed_at).total_seconds()), 0)
            if observed_at is not None
            else None
        )
        if not breadth:
            status_value, ok, data_quality = "empty", False, "empty"
            reason = "Cached index summary does not contain market breadth."
        elif (
            latest_data_date
            and expected_data_date
            and latest_data_date < expected_data_date
            and str(calendar_status.get("phase") or "unknown")
            in {"preopen_pending", "preopen"}
        ):
            status_value, ok, data_quality = "pending", False, "pending"
            reason = (
                "The presentation session has rolled forward, but current-session "
                "market breadth is still pending."
            )
        elif latest_data_date and expected_data_date and latest_data_date < expected_data_date:
            status_value, ok, data_quality = "stale", False, "stale"
            reason = (
                f"Breadth date {latest_data_date.isoformat()} is behind expected "
                f"{expected_data_date.isoformat()}."
            )
        elif raw_status == "ready":
            status_value, ok, data_quality = "current", True, "ok"
            reason = "Cached market breadth is complete for the latest expected session."
        elif raw_status == "partial":
            status_value, ok, data_quality = "partial", False, "partial"
            reason = str(
                breadth_status.get("reason")
                or "Cached market breadth has partial constituent coverage."
            )
        elif raw_status == "pending":
            status_value, ok, data_quality = "pending", False, "pending"
            reason = str(
                breadth_status.get("reason")
                or "Regular-session market breadth is pending."
            )
        else:
            status_value, ok, data_quality = "error", False, "error"
            reason = str(
                breadth_status.get("reason") or "Cached market breadth is unavailable."
            )
        entries.append(
            TaiwanSourceHealthEntry(
                resource="market_breadth",
                label=f"{candidate_index_id} market breadth",
                frequency="realtime",
                target=candidate_index_id,
                status=status_value,
                ok=ok,
                row_count=int(breadth.get("total_count") or 0),
                required=required,
                latest_data_date=latest_data_date,
                latest_data_key=str(breadth.get("scope") or "") or None,
                latest_updated_at=observed_at,
                expected_data_date=expected_data_date,
                freshness_lag_days=_freshness_lag(expected_data_date, latest_data_date),
                data_quality=data_quality,
                reason=reason,
                provider=str(breadth.get("source") or "") or None,
                source=str(breadth.get("source") or "") or None,
                latest_observed_at=observed_at,
                age_seconds=age_seconds,
                stale_after_seconds=15,
            )
        )
    return entries


def _stock_master_entry(
    db: Session,
    *,
    stock_id: str | None,
) -> TaiwanSourceHealthEntry:
    query = db.query(StockMaster)
    if stock_id is not None:
        query = query.filter(StockMaster.stock_id == stock_id)

    row_count = query.count()
    latest = _latest_or_none(query, StockMaster.updated_at.desc(), StockMaster.id.desc())
    status_value, ok, data_quality, reason = _status_for(
        row_count=row_count,
        latest_data_date=None,
    )
    return TaiwanSourceHealthEntry(
        resource="stock_master",
        label="Stock master",
        frequency="master",
        target=_target(stock_id=stock_id),
        status=status_value,
        ok=ok,
        row_count=row_count,
        latest_updated_at=getattr(latest, "updated_at", None) if latest else None,
        data_quality=data_quality,
        reason=reason,
    )


def _json_dict(value: str | None) -> dict[str, Any]:
    try:
        payload = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _daily_metric_repair_health(
    db: Session,
    *,
    dataset_key: str,
    expected_data_date: date | None,
    latest_data_date: date | None,
    release_is_released: bool | None,
) -> dict[str, Any] | None:
    job_type = DAILY_METRIC_REPAIR_JOB_TYPES.get(dataset_key)
    if job_type is None or expected_data_date is None:
        return None
    if latest_data_date is not None and latest_data_date >= expected_data_date:
        return {
            "status": "resolved",
            "expected_trade_date": expected_data_date.isoformat(),
            "observed_max_trade_date": latest_data_date.isoformat(),
        }
    if release_is_released is not True:
        return {
            "status": "not_due",
            "expected_trade_date": expected_data_date.isoformat(),
            "observed_max_trade_date": (
                latest_data_date.isoformat() if latest_data_date else None
            ),
        }

    target = expected_data_date.isoformat()
    job = (
        db.query(JobRun)
        .filter(JobRun.job_type == job_type, JobRun.target == target)
        .order_by(JobRun.created_at.desc(), JobRun.id.desc())
        .first()
    )
    if job is None:
        return {
            "status": "pending_detection",
            "expected_trade_date": target,
            "observed_max_trade_date": (
                latest_data_date.isoformat() if latest_data_date else None
            ),
        }

    request = _json_dict(job.request_json)
    result = _json_dict(job.result_json)
    repair = request.get("repair") if isinstance(request.get("repair"), dict) else {}
    repair_result = (
        result.get("repair") if isinstance(result.get("repair"), dict) else {}
    )
    if job.status in {"queued", "running"}:
        status = "repairing" if repair else "initial_refresh_running"
    elif repair and job.status == "error":
        status = (
            "exhausted"
            if int(repair.get("attempt") or 0) >= int(repair.get("max_attempts") or 1)
            else "retry_wait"
        )
    elif job.status == "error":
        status = "detected"
    elif job.status == "success":
        status = "outcome_mismatch"
    else:
        status = "pending_detection"

    return {
        "status": status,
        "job_id": job.id,
        "job_status": job.status,
        "repair_key": repair.get("repair_key"),
        "expected_trade_date": target,
        "observed_max_trade_date": (
            latest_data_date.isoformat() if latest_data_date else None
        ),
        "detected_at": repair.get("detected_at"),
        "attempt": repair.get("attempt"),
        "max_attempts": repair.get("max_attempts"),
        "next_retry_at": repair.get("next_retry_at"),
        "last_error": job.error_message or repair.get("last_error"),
        "resolved_at": repair_result.get("resolved_at"),
    }


def _dataset_entry(
    db: Session,
    *,
    spec: TaiwanDatasetSpec,
    stock: StockMaster | None,
    stock_id: str | None,
    calendar_status: dict[str, Any],
    now: datetime | None,
) -> TaiwanSourceHealthEntry:
    required = is_equity_only_dataset_required(spec, stock)
    target = _target(stock_id=stock_id)
    window = _release_window(calendar_status, spec.key)
    expected_data_date = (
        _expected_date(window) or expected_date_for_dataset(spec.key, now=now)
        if spec.has_expected_date
        else None
    )
    expected_data_key = window.get("expected_data_key")
    if not isinstance(expected_data_key, str) or not expected_data_key:
        expected_data_key = (
            expected_financial_metrics_period(now=now)
            if spec.key == TAIWAN_DATASET_FINANCIAL_METRICS
            else None
        )

    if not required:
        return TaiwanSourceHealthEntry(
            resource=spec.key,
            label=spec.label,
            frequency=spec.frequency,
            target=target,
            status="not_applicable",
            ok=True,
            row_count=0,
            required=False,
            expected_data_date=expected_data_date,
            expected_data_key=expected_data_key,
            release_status=window.get("status"),
            release_is_released=window.get("is_released"),
            release_at=window.get("release_at"),
            next_release_at=window.get("next_release_at"),
            data_quality="not_applicable",
            reason="This resource is equity-only and is not required for this instrument type.",
        )

    query = db.query(spec.model)
    if stock_id is not None and hasattr(spec.model, "stock_id"):
        query = query.filter(spec.model.stock_id == stock_id)

    row_count = query.count()
    order_by = [spec.latest_column.desc()]
    if hasattr(spec.model, "updated_at"):
        order_by.append(spec.model.updated_at.desc())
    order_by.append(spec.model.id.desc())
    latest = _latest_or_none(query, *order_by)
    latest_value = getattr(latest, spec.latest_column.key, None) if latest else None
    latest_data_date = _date_or_none(latest_value)
    latest_data_key = _key_or_none(latest_value)
    latest_updated_at = getattr(latest, "updated_at", None) if latest else None
    repair_health = _daily_metric_repair_health(
        db,
        dataset_key=spec.key,
        expected_data_date=expected_data_date,
        latest_data_date=latest_data_date,
        release_is_released=window.get("is_released"),
    )
    status_value, ok, data_quality, reason = _status_for(
        row_count=row_count,
        latest_data_date=latest_data_date,
        expected_data_date=expected_data_date,
        freshness_required=spec.has_expected_date,
    )
    if expected_data_key and row_count > 0 and latest_data_key:
        if latest_data_key >= expected_data_key:
            status_value = "current"
            ok = True
            data_quality = "current"
            reason = "Latest local key reaches the expected release key."
        else:
            status_value = "stale"
            ok = False
            data_quality = "stale"
            reason = "Latest local key is behind the expected release key."
    if (
        spec.key == "shareholding_distribution_weekly"
        and window.get("status") == "pending"
        and ok
    ):
        status_value = "pending"
        data_quality = "pending_release"
        reason = (
            "Latest local row matches the latest released TDCC observation; "
            "the next conservative publication window is still pending."
        )

    return TaiwanSourceHealthEntry(
        resource=spec.key,
        label=spec.label,
        frequency=spec.frequency,
        target=target,
        status=status_value,
        ok=ok,
        row_count=row_count,
        latest_data_date=latest_data_date,
        latest_data_key=latest_data_key,
        latest_updated_at=latest_updated_at,
        expected_data_date=expected_data_date,
        expected_data_key=expected_data_key,
        freshness_lag_days=_freshness_lag(expected_data_date, latest_data_date),
        release_status=window.get("status"),
        release_is_released=window.get("is_released"),
        release_at=window.get("release_at"),
        next_release_at=window.get("next_release_at"),
        data_quality=data_quality,
        reason=reason,
        health_dimensions={"repair": repair_health} if repair_health else None,
    )


def _market_chip_entry(
    db: Session,
    *,
    index_id: str | None,
    calendar_status: dict[str, Any],
) -> TaiwanSourceHealthEntry:
    window = _release_window(calendar_status, MARKET_CHIP_RESOURCE)
    expected_data_date = _expected_date(window)
    query = db.query(MarketChipDaily)
    if index_id is not None:
        query = query.filter(MarketChipDaily.index_id == index_id)

    row_count = query.count()
    latest = _latest_or_none(
        query,
        MarketChipDaily.trade_date.desc(),
        MarketChipDaily.updated_at.desc(),
        MarketChipDaily.id.desc(),
    )
    latest_data_date = latest.trade_date if latest else None
    status_value, ok, data_quality, reason = _status_for(
        row_count=row_count,
        latest_data_date=latest_data_date,
        expected_data_date=expected_data_date,
        freshness_required=True,
    )
    return TaiwanSourceHealthEntry(
        resource=MARKET_CHIP_RESOURCE,
        label="Market chip daily",
        frequency="daily",
        target=_target(index_id=index_id),
        status=status_value,
        ok=ok,
        row_count=row_count,
        latest_data_date=latest_data_date,
        latest_updated_at=getattr(latest, "updated_at", None) if latest else None,
        expected_data_date=expected_data_date,
        freshness_lag_days=_freshness_lag(expected_data_date, latest_data_date),
        release_status=window.get("status"),
        release_is_released=window.get("is_released"),
        data_quality=data_quality,
        reason=reason,
    )


def _summary(entries: list[TaiwanSourceHealthEntry]) -> dict[str, int]:
    return summarize_source_health(
        entries,
        counted_statuses=("empty", "stale", "not_applicable", "error"),
    )


def build_taiwan_source_health(
    db: Session,
    *,
    stock_id: str | None = None,
    dataset: str | None = None,
    index_id: str | None = None,
    now: datetime | None = None,
    sync_snapshots: bool = False,
) -> dict[str, Any]:
    normalized_stock_id = _normalized_stock_id(stock_id)
    normalized_index_id = _normalized_index_id(index_id)
    normalized_dataset = (dataset or "").strip() or None
    stock = (
        db.query(StockMaster)
        .filter(StockMaster.stock_id == normalized_stock_id)
        .first()
        if normalized_stock_id is not None
        else None
    )
    calendar_status = build_taiwan_calendar_status(now=now)
    current_time = _taiwan_now(now)
    realtime_required = normalized_dataset in {
        "taiwan_stock_quote_snapshot",
        "market_intraday_bar_1m",
        "market_breadth",
        "taiwan_market_minute_state",
    }
    entries = [
        _stock_master_entry(db, stock_id=normalized_stock_id),
        *[
            _dataset_entry(
                db,
                spec=spec,
                stock=stock,
                stock_id=normalized_stock_id,
                calendar_status=calendar_status,
                now=now,
            )
            for spec in TAIWAN_DATASET_SPECS
        ],
        _market_chip_entry(
            db,
            index_id=normalized_index_id,
            calendar_status=calendar_status,
        ),
        _stock_quote_entry(
            db,
            stock_id=normalized_stock_id,
            calendar_status=calendar_status,
            current_time=current_time,
            required=realtime_required,
        ),
        _stock_intraday_entry(
            db,
            stock_id=normalized_stock_id,
            calendar_status=calendar_status,
            current_time=current_time,
            required=realtime_required,
        ),
        _market_minute_state_entry(
            db,
            calendar_status=calendar_status,
            current_time=current_time,
            required=realtime_required,
        ),
        *_market_breadth_entries(
            db,
            index_id=normalized_index_id,
            calendar_status=calendar_status,
            current_time=current_time,
            required=realtime_required,
        ),
    ]
    if normalized_dataset is not None:
        entries = [entry for entry in entries if entry.resource == normalized_dataset]
    entry_dicts = enrich_source_health_entries(
        db,
        market="tw",
        entries=[entry.to_dict() for entry in entries],
    )
    generated_at = _generated_at()
    if sync_snapshots:
        sync_source_health_snapshots(
            db,
            market="tw",
            entries=entry_dicts,
            checked_at=generated_at,
        )

    summary = _summary(entries)
    summary["status_dimensions"] = summarize_status_dimensions(entry_dicts)
    return {
        "kind": "taiwan_source_health",
        "generated_at": generated_at.isoformat(),
        "filters": {
            "stock_id": normalized_stock_id,
            "dataset": normalized_dataset,
            "index_id": normalized_index_id,
        },
        "market_calendar": {
            "checked_at": calendar_status.get("checked_at"),
            "date": calendar_status.get("date"),
            "phase": calendar_status.get("phase"),
            "reason": calendar_status.get("reason"),
            "is_trading_day": calendar_status.get("is_trading_day"),
        },
        "summary": summary,
        "entries": entry_dicts,
    }


__all__ = [
    "TaiwanSourceHealthEntry",
    "build_taiwan_source_health",
]
