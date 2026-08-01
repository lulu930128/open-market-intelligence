import logging
from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import StockMaster
from app.db.session import SessionLocal
from app.market.broker_branch import ensure_broker_branch_daily
from app.market.backfill import backfill_tpex_trading_stock, backfill_twse_stock_day
from app.market.daily_metrics_backfill import ensure_stock_daily_metrics
from app.market.financial_metrics_history_backfill import ensure_stock_financial_metrics_history
from app.market.monthly_revenue_history_backfill import ensure_stock_monthly_revenue_history
from app.market.shareholding_history_backfill import ensure_stock_shareholding_history
from app.market.calendar_status import expected_taiwan_trade_date
from app.market.taiwan_rules import (
    TAIWAN_DATASET_BROKER_BRANCH,
    TAIWAN_DATASET_DAILY_PRICE,
    TAIWAN_DATASET_INSTITUTIONAL_TRADE,
    TAIWAN_DATASET_MARGIN_TRADING,
    TAIWAN_DATASET_SHAREHOLDING_DISTRIBUTION,
    TAIWAN_REFRESH_BROKER_BRANCH,
    TAIWAN_REFRESH_DAILY_PRICE,
    TAIWAN_REFRESH_INSTITUTIONAL_TRADE,
    TAIWAN_REFRESH_MARGIN_TRADING,
    TAIWAN_REFRESH_SHAREHOLDING_DISTRIBUTION,
    TAIWAN_REFRESH_STEP_LABELS,
    normalize_refresh_profile,
    refresh_profile_steps,
)
from app.observability.provider_health import record_provider_event


logger = logging.getLogger(__name__)
ProgressCallback = Callable[[int | None, int | None, str | None], None]
CancellationCheck = Callable[[], bool]
SessionFactory = Callable[[], Session]
SHAREHOLDING_NO_CHANGE_COOLDOWN = timedelta(hours=1)
_FAILED_STEP_STATUSES = {"error", "failed", "failure", "timeout", "cancelled"}
_PARTIAL_STEP_STATUSES = {"partial", "partial_success", "completed_with_error"}


def expected_daily_price_date(*, include_today: bool | None = None) -> date | None:
    return expected_taiwan_trade_date(
        TAIWAN_DATASET_DAILY_PRICE,
        include_today=include_today,
    )


def expected_institutional_trade_date(*, include_today: bool | None = None) -> date | None:
    return expected_taiwan_trade_date(
        TAIWAN_DATASET_INSTITUTIONAL_TRADE,
        include_today=include_today,
    )


def expected_margin_trade_date(*, include_today: bool | None = None) -> date | None:
    return expected_taiwan_trade_date(
        TAIWAN_DATASET_MARGIN_TRADING,
        include_today=include_today,
    )


def expected_broker_branch_date(*, include_today: bool | None = None) -> date | None:
    return expected_taiwan_trade_date(
        TAIWAN_DATASET_BROKER_BRANCH,
        include_today=include_today,
    )


def _step_status(result: dict) -> str:
    status = result.get("status")
    return status if isinstance(status, str) else "success"


def _changed_row_count(result: dict) -> int:
    counts = []
    for key in ("inserted_count", "updated_count", "created_count"):
        value = result.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int) and value > 0:
            counts.append(value)
    if counts:
        return sum(counts)
    if str(result.get("status") or "") in {"inserted", "updated", "created"}:
        return 1
    return 0


def _result_error_messages(result: dict[str, Any], *, limit: int = 5) -> list[str]:
    messages: list[str] = []

    def add(value: Any) -> None:
        message = str(value or "").strip()
        if message and message not in messages:
            messages.append(message[:1_000])

    for key in ("error_message", "error"):
        add(result.get(key))
    nested_results = result.get("results")
    if isinstance(nested_results, dict):
        nested_items = list(nested_results.values())
    elif isinstance(nested_results, list):
        nested_items = nested_results
    else:
        nested_items = []
    for item in nested_items:
        if len(messages) >= limit:
            break
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").strip().lower()
        if status in _FAILED_STEP_STATUSES or item.get("error_message") or item.get("error"):
            add(item.get("error_message") or item.get("error"))
    if not messages and str(result.get("status") or "").strip().lower() in _FAILED_STEP_STATUSES:
        add(result.get("message"))
    return messages[:limit]


def _step_provider(key: str, result: dict[str, Any]) -> str | None:
    provider = str(result.get("provider") or "").strip()
    if provider:
        return provider
    if key == TAIWAN_REFRESH_SHAREHOLDING_DISTRIBUTION:
        return "tdcc"
    return None


def _run_refresh_step(
    *,
    key: str,
    label: str,
    step_index: int,
    step_total: int,
    progress: ProgressCallback | None,
    results: dict[str, dict],
    action: Callable[[], dict],
) -> None:
    if progress is not None:
        progress(step_index - 1, step_total, f"{label}更新中。")

    try:
        result = action()
        status = _step_status(result).strip().lower()
        changed_rows = _changed_row_count(result)
        error_messages = _result_error_messages(result)
        refresh_outcome = (
            "failed"
            if status in _FAILED_STEP_STATUSES
            else "partial"
            if status in _PARTIAL_STEP_STATUSES
            else "skipped"
            if status == "skipped" or status.startswith("skipped_")
            else "updated"
            if changed_rows > 0
            else "unchanged"
        )
        results[key] = {
            "label": label,
            "status": status,
            "refresh_outcome": refresh_outcome,
            "changed_row_count": changed_rows,
            "result": result,
            "provider": _step_provider(key, result),
            "error_message": error_messages[0] if error_messages else None,
            "error_messages": error_messages,
        }
    except Exception as exc:
        results[key] = {
            "label": label,
            "status": "error",
            "refresh_outcome": "failed",
            "changed_row_count": 0,
            "result": None,
            "provider": (
                "tdcc"
                if key == TAIWAN_REFRESH_SHAREHOLDING_DISTRIBUTION
                else None
            ),
            "error_message": str(exc),
            "error_messages": [str(exc)],
        }

    if progress is not None:
        progress(step_index, step_total, f"{label}更新完成。")


def _record_shareholding_refresh_outcome(
    *,
    stock_id: str,
    result: dict[str, Any],
    session_factory: SessionFactory | None = None,
) -> bool:
    outcome = str(result.get("refresh_outcome") or "unknown")
    now = datetime.now(timezone.utc)
    detail: dict[str, Any] = {
        "refresh_outcome": outcome,
        "changed_row_count": int(result.get("changed_row_count") or 0),
        "error_message": result.get("error_message"),
    }
    if outcome == "unchanged":
        detail["next_eligible_refresh_at"] = (
            now + SHAREHOLDING_NO_CHANGE_COOLDOWN
        ).isoformat()
    telemetry_db: Session | None = None
    try:
        telemetry_db = (session_factory or SessionLocal)()
        record_provider_event(
            telemetry_db,
            market="tw",
            provider="tdcc",
            resource=TAIWAN_DATASET_SHAREHOLDING_DISTRIBUTION,
            target=stock_id,
            status=(
                "failed"
                if str(result.get("status") or "").lower()
                in _FAILED_STEP_STATUSES
                else "success"
            ),
            event_type=(
                "refresh_no_change"
                if outcome == "unchanged"
                else "refresh_updated"
                if outcome == "updated"
                else "refresh_failed"
            ),
            event_time=now,
            observed_at=now,
            message=(
                "TDCC shareholding refresh returned no newer rows; cooldown applied."
                if outcome == "unchanged"
                else "TDCC shareholding refresh outcome recorded."
            ),
            detail=detail,
        )
        return True
    except Exception:
        if telemetry_db is not None:
            try:
                telemetry_db.rollback()
            except Exception:
                logger.exception(
                    "Shareholding refresh telemetry rollback failed stock_id=%s",
                    stock_id,
                )
        logger.exception(
            "Shareholding refresh telemetry persistence failed stock_id=%s outcome=%s",
            stock_id,
            outcome,
        )
        return False
    finally:
        if telemetry_db is not None:
            try:
                telemetry_db.close()
            except Exception:
                logger.exception(
                    "Shareholding refresh telemetry session close failed stock_id=%s",
                    stock_id,
                )


def _get_stock_market(db: Session, stock_id: str) -> str | None:
    stock = db.query(StockMaster).filter(StockMaster.stock_id == stock_id).first()

    if stock is None:
        return None

    return stock.market.upper()


def _expected_refresh_trade_date(
    step_key: str,
    *,
    include_today: bool | None,
) -> date:
    expected_by_step = {
        TAIWAN_REFRESH_DAILY_PRICE: expected_daily_price_date,
        TAIWAN_REFRESH_INSTITUTIONAL_TRADE: expected_institutional_trade_date,
        TAIWAN_REFRESH_MARGIN_TRADING: expected_margin_trade_date,
        TAIWAN_REFRESH_BROKER_BRANCH: expected_broker_branch_date,
    }
    expected_date = expected_by_step[step_key](include_today=include_today)
    if expected_date is None:
        raise ValueError(f"No expected trade date is configured for refresh step '{step_key}'.")

    return expected_date


def _ensure_current_month_daily_prices(
    *,
    db: Session,
    stock_id: str,
    target_date: date,
    sleep_seconds: float,
) -> dict:
    start_date = date(target_date.year, target_date.month, 1)
    market = _get_stock_market(db=db, stock_id=stock_id)

    if market == "TWSE":
        return backfill_twse_stock_day(
            db=db,
            stock_id=stock_id,
            start_date=start_date,
            end_date=target_date,
            sleep_seconds=sleep_seconds,
            skip_existing_months=True,
        )

    if market == "TPEX":
        return backfill_tpex_trading_stock(
            db=db,
            stock_id=stock_id,
            start_date=start_date,
            end_date=target_date,
            sleep_seconds=sleep_seconds,
            skip_existing_months=True,
        )

    return {
        "status": "skipped",
        "stock_id": stock_id,
        "start_date": start_date,
        "end_date": target_date,
        "message": f"Daily price refresh is not configured for market='{market}'.",
    }


def refresh_selected_stock_data(
    *,
    db: Session,
    stock_id: str,
    include_today: bool | None = None,
    sleep_seconds: float = 0.05,
    profile: str | None = "full",
    steps: Iterable[str] | None = None,
    progress: ProgressCallback | None = None,
    should_cancel: CancellationCheck | None = None,
) -> dict:
    if steps is None:
        refresh_profile = normalize_refresh_profile(profile)
        requested_steps = refresh_profile_steps(refresh_profile)
    else:
        refresh_profile = "custom"
        requested_steps = tuple(
            dict.fromkeys(
                str(step or "").strip()
                for step in steps
                if str(step or "").strip()
            )
        )
        unknown_steps = [
            step for step in requested_steps if step not in TAIWAN_REFRESH_STEP_LABELS
        ]
        if unknown_steps:
            raise ValueError(
                "Unsupported Taiwan refresh step(s): "
                + ", ".join(unknown_steps)
            )
        if not requested_steps:
            raise ValueError("steps must contain at least one Taiwan refresh step.")
    step_total = len(requested_steps)
    results: dict[str, dict] = {}
    expected_trade_dates = {
        step: _expected_refresh_trade_date(
            step,
            include_today=include_today,
        )
        for step in requested_steps
        if step
        in {
            TAIWAN_REFRESH_DAILY_PRICE,
            TAIWAN_REFRESH_INSTITUTIONAL_TRADE,
            TAIWAN_REFRESH_MARGIN_TRADING,
            TAIWAN_REFRESH_BROKER_BRANCH,
        }
    }
    daily_price_date = expected_trade_dates.get(TAIWAN_REFRESH_DAILY_PRICE)
    institutional_trade_date = expected_trade_dates.get(
        TAIWAN_REFRESH_INSTITUTIONAL_TRADE
    )
    margin_trade_date = expected_trade_dates.get(TAIWAN_REFRESH_MARGIN_TRADING)
    branch_trade_date = expected_trade_dates.get(TAIWAN_REFRESH_BROKER_BRANCH)

    refresh_steps: dict[str, Callable[[], dict]] = {
        "daily_price": (
            lambda: _ensure_current_month_daily_prices(
                db=db,
                stock_id=stock_id,
                target_date=expected_trade_dates[TAIWAN_REFRESH_DAILY_PRICE],
                sleep_seconds=sleep_seconds,
            )
        ),
        "institutional_trade": (
            lambda: ensure_stock_daily_metrics(
                db=db,
                stock_id=stock_id,
                start_date=expected_trade_dates[TAIWAN_REFRESH_INSTITUTIONAL_TRADE],
                end_date=expected_trade_dates[TAIWAN_REFRESH_INSTITUTIONAL_TRADE],
                categories=["institutional_trade"],
                sleep_seconds=sleep_seconds,
                skip_existing=True,
            )
        ),
        "margin_trading": (
            lambda: ensure_stock_daily_metrics(
                db=db,
                stock_id=stock_id,
                start_date=expected_trade_dates[TAIWAN_REFRESH_MARGIN_TRADING],
                end_date=expected_trade_dates[TAIWAN_REFRESH_MARGIN_TRADING],
                categories=["margin_trading"],
                sleep_seconds=sleep_seconds,
                skip_existing=True,
            )
        ),
        "broker_branch": (
            lambda: {
                "status": "success",
                "rows": len(
                    ensure_broker_branch_daily(
                        db=db,
                        stock_id=stock_id,
                        trade_date=expected_trade_dates[TAIWAN_REFRESH_BROKER_BRANCH],
                    )
                ),
            }
        ),
        "shareholding_distribution": (
            lambda: ensure_stock_shareholding_history(
                db=db,
                stock_id=stock_id,
                lookback_weeks=52,
                sleep_seconds=sleep_seconds,
                skip_existing=True,
            )
        ),
        "monthly_revenue": (
            lambda: ensure_stock_monthly_revenue_history(
                db=db,
                stock_id=stock_id,
                lookback_months=120,
                sleep_seconds=sleep_seconds,
                skip_existing=True,
            )
        ),
        "financial_metrics": (
            lambda: ensure_stock_financial_metrics_history(
                db=db,
                stock_id=stock_id,
                lookback_quarters=40,
                sleep_seconds=sleep_seconds,
                skip_existing=True,
            )
        ),
    }

    cancelled = False
    for step_index, step_key in enumerate(requested_steps, start=1):
        if should_cancel is not None and should_cancel():
            cancelled = True
            break
        label = TAIWAN_REFRESH_STEP_LABELS[step_key]
        action = refresh_steps[step_key]
        _run_refresh_step(
            key=step_key,
            label=label,
            step_index=step_index,
            step_total=step_total,
            progress=progress,
            results=results,
            action=action,
        )
        if (
            step_key == TAIWAN_REFRESH_SHAREHOLDING_DISTRIBUTION
            and step_key in results
        ):
            _record_shareholding_refresh_outcome(
                stock_id=stock_id,
                result=results[step_key],
            )
        if should_cancel is not None and should_cancel():
            cancelled = True
            break

    error_count = sum(
        1
        for result in results.values()
        if str(result.get("status") or "").lower() in _FAILED_STEP_STATUSES
    )
    partial_count = sum(
        1
        for result in results.values()
        if str(result.get("status") or "").lower() in _PARTIAL_STEP_STATUSES
    )
    skipped_count = sum(
        1
        for result in results.values()
        if str(result.get("status") or "").lower() == "skipped"
        or str(result.get("status") or "").lower().startswith("skipped_")
    )
    completed_count = len(results) - error_count - partial_count - skipped_count
    refreshed_count = sum(
        1 for result in results.values() if result["refresh_outcome"] == "updated"
    )
    unchanged_count = sum(
        1 for result in results.values() if result["refresh_outcome"] == "unchanged"
    )
    changed_row_count = sum(
        int(result["changed_row_count"]) for result in results.values()
    )

    failed_steps = [
        {
            "dataset": step_key,
            "label": result.get("label"),
            "provider": result.get("provider"),
            "target": stock_id,
            "status": result.get("status"),
            "refresh_outcome": result.get("refresh_outcome"),
            "error_message": result.get("error_message"),
            "retryable": True,
        }
        for step_key, result in results.items()
        if result.get("refresh_outcome") in {"failed", "partial"}
    ][:5]

    if cancelled:
        status = "timeout"
    elif error_count == len(results):
        status = "error"
    elif error_count or partial_count:
        status = "partial_success"
    elif completed_count == 0:
        status = "skipped"
    else:
        status = "success"

    refresh_outcome = (
        "failed"
        if status in {"error", "timeout"}
        else "partial"
        if status == "partial_success"
        else "updated"
        if refreshed_count
        else "skipped"
        if status == "skipped"
        else "unchanged"
    )
    return {
        "status": status,
        "refresh_outcome": refresh_outcome,
        "message": (
            "Selected stock data refresh stopped at the wall-clock deadline."
            if cancelled
            else "Selected stock data refresh completed with updated rows."
            if refreshed_count
            else "Selected stock data refresh completed; no newer rows were obtained."
        ),
        "stock_id": stock_id,
        "include_today": include_today,
        "profile": refresh_profile,
        "daily_price_date": daily_price_date,
        "institutional_trade_date": institutional_trade_date,
        "margin_trade_date": margin_trade_date,
        "broker_branch_date": branch_trade_date,
        "requested_count": step_total,
        "refreshed_count": refreshed_count,
        "refreshed_count_semantics": "datasets_with_inserted_or_updated_rows",
        "completed_count": completed_count,
        "partial_count": partial_count,
        "unchanged_count": unchanged_count,
        "changed_row_count": changed_row_count,
        "skipped_count": skipped_count,
        "error_count": error_count,
        "error_message": (
            failed_steps[0].get("error_message") if failed_steps else None
        ),
        "failed_steps": failed_steps,
        "cancelled": cancelled,
        "results": results,
    }


__all__ = ["refresh_selected_stock_data"]
