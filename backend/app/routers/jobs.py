from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.jobs import backfill_tasks, service
from app.jobs.eod_coverage import run_eod_coverage_reconcile_job
from app.jobs.us_current_market_bootstrap import (
    enqueue_us_current_market_bootstrap as enqueue_us_current_market_bootstrap_job,
    normalize_us_current_market_bootstrap_targets,
    run_us_current_market_bootstrap_job,
)
from app.jobs.taiwan_bar_bootstrap import (
    enqueue_taiwan_index_daily_bootstrap,
    enqueue_taiwan_intraday_bar_bootstrap,
    run_taiwan_index_daily_bootstrap_job,
    run_taiwan_intraday_bar_bootstrap_job,
)
from app.jobs.us_index_data_repair_gate import run_us_index_data_repair_job
from app.jobs.job_types import (
    CROSS_MARKET_CONTEXT_REFRESH_JOB_TYPE,
    JP_SCHEDULED_WATCHLIST_RESOURCE_REFRESH_JOB_TYPE,
    JP_WATCHLIST_RESOURCE_REFRESH_JOB_TYPE,
    MARKET_EOD_COVERAGE_RECONCILE_JOB_TYPE,
    TAIWAN_BROKER_BRANCH_BEHAVIOR_SHADOW_JOB_TYPE,
    TAIWAN_BROKER_BRANCH_MARKET_REFRESH_JOB_TYPE,
    TAIWAN_DERIVATIVES_SCHEDULED_REFRESH_JOB_TYPE,
    TAIWAN_INTRADAY_BAR_BOOTSTRAP_JOB_TYPE,
    TAIWAN_INDEX_DAILY_BOOTSTRAP_JOB_TYPE,
    WATCHLIST_RADAR_AUTO_SNAPSHOT_JOB_TYPE,
    WATCHLIST_RADAR_OUTCOME_RECONCILE_JOB_TYPE,
    US_OHLC_HISTORY_REPAIR_JOB_TYPE,
    US_INTRADAY_MINUTE_REPAIR_JOB_TYPE,
    US_INDEX_INTRADAY_VOLUME_REPAIR_JOB_TYPE,
    US_INDEX_DATA_REPAIR_JOB_TYPE,
    US_CURRENT_MARKET_BOOTSTRAP_JOB_TYPE,
    US_PRIORITY_OHLC_RECONCILE_JOB_TYPE,
    US_SEC_FORM4_SYNC_JOB_TYPE,
    US_SEC_13F_HISTORY_SYNC_JOB_TYPE,
    US_SEC_13F_MAPPING_SYNC_JOB_TYPE,
    US_SEC_13F_QUARTER_SYNC_JOB_TYPE,
)
from app.jobs.schemas import (
    JobRunRead,
    TaiwanIndexDailyBootstrapJobRequest,
    TaiwanIntradayBarBootstrapJobRequest,
    USCurrentMarketBootstrapJobRequest,
)
from app.market.tw_index_daily_platform import (
    TAIWAN_INDEX_DAILY_BOOTSTRAP_MAX_SESSIONS,
)
from app.stocks.bootstrap import BOOTSTRAP_JOB_TYPE, run_stock_master_bootstrap_job
from app.us_market.intraday_profiles import (
    US_CURRENT_MARKET_BOOTSTRAP_DEFAULT_MAX_EXTERNAL_CALLS,
)


router = APIRouter()


def _parse_date(value: Any) -> date | None:
    if value is None or isinstance(value, date):
        return value

    return date.fromisoformat(str(value))


def _parse_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                items.append(text)
        return items

    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]

    return []


def _parse_int_list(value: Any) -> list[int]:
    items = _parse_string_list(value)
    return [int(item) for item in items]


def _request_dict(job: Any) -> dict[str, Any]:
    request = service.serialize_job(job).get("request")

    return request if isinstance(request, dict) else {}


def _retry_config(job: Any) -> tuple[Any, tuple[Any, ...], dict[str, Any]]:
    request = _request_dict(job)
    job_type = job.job_type

    if job_type == BOOTSTRAP_JOB_TYPE:
        return run_stock_master_bootstrap_job, (True,), request

    if job_type == TAIWAN_INTRADAY_BAR_BOOTSTRAP_JOB_TYPE:
        symbols = tuple(_parse_string_list(request.get("symbols")))
        return (
            run_taiwan_intraday_bar_bootstrap_job,
            (symbols, int(request.get("max_symbols", 10))),
            request,
        )

    if job_type == TAIWAN_INDEX_DAILY_BOOTSTRAP_JOB_TYPE:
        date_from = _parse_date(request.get("date_from"))
        date_to = _parse_date(request.get("date_to"))
        if date_from is None or date_to is None:
            raise ValueError("Taiwan index bootstrap retry requires date range")
        return (
            run_taiwan_index_daily_bootstrap_job,
            (
                tuple(_parse_string_list(request.get("index_ids"))),
                date_from,
                date_to,
                int(
                    request.get(
                        "taiex_max_sessions",
                        TAIWAN_INDEX_DAILY_BOOTSTRAP_MAX_SESSIONS,
                    )
                ),
                int(
                    request.get(
                        "tpex_max_sessions",
                        TAIWAN_INDEX_DAILY_BOOTSTRAP_MAX_SESSIONS,
                    )
                ),
            ),
            request,
        )

    if job_type == "market.twse_daily_price_backfill":
        return (
            backfill_tasks.run_twse_daily_price_job,
            (
                str(request.get("stock_id") or job.target),
                _parse_date(request.get("start_date")),
                _parse_date(request.get("end_date")),
                request.get("source_id"),
                float(request.get("sleep_seconds", 0.8)),
                bool(request.get("skip_existing_months", False)),
            ),
            request,
        )

    if job_type == "market.tpex_daily_price_backfill":
        return (
            backfill_tasks.run_tpex_daily_price_job,
            (
                str(request.get("stock_id") or job.target),
                _parse_date(request.get("start_date")),
                _parse_date(request.get("end_date")),
                request.get("source_id"),
                float(request.get("sleep_seconds", 0.8)),
                bool(request.get("skip_existing_months", False)),
            ),
            request,
        )

    if job_type in {
        "market.daily_metrics_backfill",
        "scheduler.market_daily_refresh",
        "scheduler.market_margin_daily_refresh",
    }:
        expected_trade_date = _parse_date(request.get("expected_trade_date"))
        if expected_trade_date is None and job_type.startswith("scheduler."):
            expected_trade_date = _parse_date(job.target)
        return (
            backfill_tasks.run_market_daily_metrics_job,
            (
                _parse_date(request.get("start_date")),
                _parse_date(request.get("end_date")),
                list(request.get("categories") or []),
                int(request.get("lookback_days", 30)),
                bool(request.get("include_today", False)),
                float(request.get("sleep_seconds", 0.2)),
                bool(request.get("skip_existing", True)),
                expected_trade_date,
                request.get("repair") if isinstance(request.get("repair"), dict) else None,
            ),
            request,
        )

    if job_type == "market.index_summary_refresh":
        return (
            backfill_tasks.run_market_index_summary_refresh_job,
            (),
            request,
        )

    if job_type == TAIWAN_DERIVATIVES_SCHEDULED_REFRESH_JOB_TYPE:
        expected_trade_date = _parse_date(request.get("expected_trade_date"))
        if expected_trade_date is None:
            raise ValueError("Taiwan derivatives retry requires expected_trade_date.")
        return (
            backfill_tasks.run_taiwan_derivatives_refresh_job,
            (expected_trade_date,),
            request,
        )

    if job_type == TAIWAN_BROKER_BRANCH_MARKET_REFRESH_JOB_TYPE:
        expected_trade_date = _parse_date(request.get("expected_trade_date"))
        if expected_trade_date is None:
            raise ValueError(
                "Taiwan broker-branch retry requires expected_trade_date."
            )
        return (
            backfill_tasks.run_taiwan_broker_branch_market_refresh_job,
            (
                expected_trade_date,
                float(request.get("sleep_seconds", 0.5)),
                int(request.get("max_stocks", 2500)),
                int(request.get("max_runtime_seconds", 7200)),
            ),
            request,
        )

    if job_type == TAIWAN_BROKER_BRANCH_BEHAVIOR_SHADOW_JOB_TYPE:
        as_of_trade_date = _parse_date(request.get("as_of_trade_date"))
        if as_of_trade_date is None:
            raise ValueError(
                "Broker-branch behavior retry requires as_of_trade_date."
            )
        methodology_version = str(
            request.get("methodology_version") or ""
        ).strip()
        if not methodology_version:
            raise ValueError(
                "Broker-branch behavior retry requires methodology_version."
            )
        return (
            backfill_tasks.run_taiwan_broker_branch_behavior_shadow_job,
            (
                as_of_trade_date,
                int(request.get("lookback_sessions", 120)),
                methodology_version,
            ),
            request,
        )

    if job_type in {
        "market.market_chip_daily_refresh",
        "scheduler.market_chip_daily_refresh",
    }:
        include_today = request.get("include_today")
        return (
            backfill_tasks.run_market_chip_daily_refresh_job,
            (
                _parse_string_list(request.get("index_ids")) or ["TAIEX", "TPEX"],
                _parse_date(request.get("trade_date")),
                include_today if isinstance(include_today, bool) else None,
                bool(request.get("force", False)),
            ),
            request,
        )

    if job_type == "market.stock_daily_metrics_history_backfill":
        return (
            backfill_tasks.run_stock_daily_metrics_history_job,
            (
                str(request.get("stock_id") or job.target),
                _parse_date(request.get("start_date")),
                _parse_date(request.get("end_date")),
                list(request.get("categories") or []),
                float(request.get("sleep_seconds", 0.2)),
                bool(request.get("skip_existing", True)),
            ),
            request,
        )

    if job_type == "market.fundamental_metrics_backfill":
        return (
            backfill_tasks.run_market_fundamental_metrics_job,
            (
                list(request.get("categories") or []),
                bool(request.get("force", False)),
                float(request.get("sleep_seconds", 0.2)),
            ),
            request,
        )

    if job_type in {
        "scheduler.tw_stock_detail_shareholding_distribution_refresh",
        "scheduler.tw_stock_detail_monthly_revenue_refresh",
        "scheduler.tw_stock_detail_financial_metrics_refresh",
    }:
        return (
            backfill_tasks.run_taiwan_fundamental_snapshot_refresh_job,
            (
                str(request.get("category")),
                str(request.get("dataset")),
                str(request.get("expected_key")),
                str(request.get("completion_target")),
                float(request.get("sleep_seconds", 0.2)),
            ),
            request,
        )

    if job_type == "market.stock_fundamental_metrics_backfill":
        return (
            backfill_tasks.run_stock_fundamental_metrics_job,
            (
                str(request.get("stock_id") or job.target),
                list(request.get("categories") or []),
                bool(request.get("force", False)),
                float(request.get("sleep_seconds", 0.2)),
            ),
            request,
        )

    if job_type == "market.stock_shareholding_history_backfill":
        return (
            backfill_tasks.run_stock_shareholding_history_job,
            (
                str(request.get("stock_id") or job.target),
                _parse_date(request.get("from_date")),
                _parse_date(request.get("to_date")),
                int(request.get("lookback_weeks", 52)),
                float(request.get("sleep_seconds", 0.2)),
                bool(request.get("skip_existing", True)),
            ),
            request,
        )

    if job_type == "market.stock_monthly_revenue_history_backfill":
        return (
            backfill_tasks.run_stock_monthly_revenue_history_job,
            (
                str(request.get("stock_id") or job.target),
                _parse_date(request.get("from_period")),
                _parse_date(request.get("to_period")),
                int(request.get("lookback_months", 120)),
                float(request.get("sleep_seconds", 0.2)),
                bool(request.get("skip_existing", True)),
            ),
            request,
        )

    if job_type == "market.stock_financial_metrics_history_backfill":
        return (
            backfill_tasks.run_stock_financial_metrics_history_job,
            (
                str(request.get("stock_id") or job.target),
                request.get("from_fiscal_year"),
                request.get("from_quarter"),
                request.get("to_fiscal_year"),
                request.get("to_quarter"),
                int(request.get("lookback_quarters", 40)),
                float(request.get("sleep_seconds", 0.2)),
                bool(request.get("skip_existing", True)),
            ),
            request,
        )

    if job_type == "market.stock_selection_refresh":
        return (
            backfill_tasks.run_stock_selection_refresh_job,
            (
                str(request.get("stock_id") or job.target),
                request.get("include_today"),
                float(request.get("sleep_seconds", 0.05)),
                str(request.get("profile") or "full"),
            ),
            request,
        )

    if job_type == "watchlist.group_daily_price_backfill":
        return (
            backfill_tasks.run_watchlist_group_backfill_job,
            (
                int(request.get("group_id") or job.target),
                _parse_date(request.get("start_date")),
                _parse_date(request.get("end_date")),
                request.get("source_id"),
                request.get("tpex_source_id"),
                bool(request.get("include_children", True)),
                bool(request.get("enabled_only", True)),
                float(request.get("sleep_seconds", 0.8)),
                bool(request.get("skip_existing_months", True)),
            ),
            request,
        )

    if job_type == "watchlist.group_daily_price_refresh_latest":
        return (
            backfill_tasks.run_watchlist_group_refresh_latest_job,
            (
                int(request.get("group_id") or job.target),
                _parse_date(request.get("to_date")),
                int(request.get("lookback_days", 14)),
                bool(request.get("include_today", False)),
                request.get("source_id"),
                request.get("tpex_source_id"),
                bool(request.get("include_children", True)),
                bool(request.get("enabled_only", True)),
                float(request.get("sleep_seconds", 0.8)),
                bool(request.get("skip_existing_months", True)),
            ),
            request,
        )

    if job_type == WATCHLIST_RADAR_AUTO_SNAPSHOT_JOB_TYPE:
        group_ids = request.get("group_ids")
        return (
            backfill_tasks.run_watchlist_radar_auto_snapshot_job,
            (
                _parse_int_list(group_ids) if group_ids else None,
                str(request.get("modes") or "action"),
                bool(request.get("include_children", True)),
                bool(request.get("enabled_only", True)),
                int(request.get("max_results", 30)),
                int(request.get("calculation_limit", 100)),
                bool(request.get("use_intraday", False)),
                int(request.get("intraday_limit", 30)),
                _parse_date(request.get("evaluate_before_date")) or date.today(),
                int(request.get("evaluate_lookback_days", 10)),
                bool(request.get("save_snapshots", True)),
            ),
            request,
        )

    if job_type == WATCHLIST_RADAR_OUTCOME_RECONCILE_JOB_TYPE:
        group_ids = request.get("group_ids")
        return (
            backfill_tasks.run_watchlist_radar_outcome_reconcile_job,
            (
                _parse_int_list(group_ids) if group_ids else None,
                str(request.get("modes") or "action"),
                int(request.get("limit", 200)),
                int(request.get("initialize_limit", 200)),
                _parse_date(request.get("as_of_trade_date")),
            ),
            request,
        )

    if job_type in {"us_market.watchlist_daily_refresh", "scheduler.us_market_daily_refresh"}:
        group_id = request.get("group_id")
        return (
            backfill_tasks.run_us_watchlist_daily_refresh_job,
            (
                int(group_id) if group_id is not None else None,
                bool(request.get("include_children", True)),
                bool(request.get("enabled_only", True)),
                str(request.get("outputsize") or "compact"),
                bool(request.get("adjusted", False)),
                float(request.get("sleep_seconds", 12.0)),
            ),
            request,
        )

    if job_type == CROSS_MARKET_CONTEXT_REFRESH_JOB_TYPE:
        return (
            backfill_tasks.run_cross_market_context_refresh_job,
            (
                _parse_string_list(request.get("stock_ids")),
                int(request.get("max_symbols", 8)),
                str(request.get("provider") or "auto"),
                str(request.get("outputsize") or "compact"),
                int(request.get("max_runtime_seconds", 120)),
            ),
            request,
        )

    if job_type == MARKET_EOD_COVERAGE_RECONCILE_JOB_TYPE:
        return (
            run_eod_coverage_reconcile_job,
            (
                str(request.get("market") or ""),
                bool(request.get("repair", True)),
                _parse_date(request.get("expected_trade_date")),
                int(request.get("max_symbols", 250)),
                int(request.get("max_runtime_seconds", 600)),
                float(request.get("sleep_seconds", 1.0)),
                int(request.get("max_consecutive_errors", 5)),
                int(request.get("error_backoff_seconds", 1800)),
            ),
            request,
        )

    if job_type == US_OHLC_HISTORY_REPAIR_JOB_TYPE:
        return (
            backfill_tasks.run_us_ohlc_history_repair_job,
            (
                str(request.get("symbol") or job.target.split(":", 1)[0]),
                str(request.get("timeframe") or "daily"),
                int(request.get("bars", 180)),
                str(request.get("provider") or "yahoo_chart"),
                bool(request.get("adjusted", False)),
                int(request.get("max_provider_calls", 2)),
                bool(request.get("force_full", False)),
            ),
            request,
        )

    if job_type == US_PRIORITY_OHLC_RECONCILE_JOB_TYPE:
        return (
            backfill_tasks.run_us_priority_ohlc_reconcile_job,
            (
                int(request.get("max_runtime_seconds", 600)),
                request.get("cursor_symbol"),
                int(request.get("max_symbols", 20)),
                int(request.get("max_external_calls", 20)),
                int(request.get("max_provider_attempts", 2)),
            ),
            request,
        )

    if job_type == US_INTRADAY_MINUTE_REPAIR_JOB_TYPE:
        after_group_id = request.get("after_group_id")
        return (
            backfill_tasks.run_us_intraday_minute_repair_job,
            (
                bool(request.get("apply", False)),
                int(request.get("max_groups", 200)),
                int(request.get("max_candidate_rows", 10_000)),
                int(after_group_id) if after_group_id is not None else None,
            ),
            request,
        )

    if job_type == US_INDEX_INTRADAY_VOLUME_REPAIR_JOB_TYPE:
        after_bar_id = request.get("after_bar_id")
        return (
            backfill_tasks.run_us_index_intraday_volume_repair_job,
            (
                bool(request.get("apply", False)),
                int(request.get("max_rows", 10_000)),
                int(after_bar_id) if after_bar_id is not None else None,
            ),
            request,
        )

    if job_type == US_INDEX_DATA_REPAIR_JOB_TYPE:
        requested_at = str(request.get("requested_at") or "").strip()
        if not requested_at:
            raise ValueError("US index repair retry requires requested_at")
        return (
            run_us_index_data_repair_job,
            (
                requested_at,
                _parse_string_list(request.get("missing_daily_symbols")),
                _parse_string_list(request.get("missing_quote_symbols")),
                int(request.get("daily_max_external_calls", 12)),
                int(request.get("quote_max_external_calls", 12)),
                int(request.get("max_runtime_seconds", 600)),
            ),
            request,
        )

    if job_type == US_CURRENT_MARKET_BOOTSTRAP_JOB_TYPE:
        max_external_calls = int(
            request.get(
                "max_external_calls",
                US_CURRENT_MARKET_BOOTSTRAP_DEFAULT_MAX_EXTERNAL_CALLS,
            )
        )
        if max_external_calls < 1 or max_external_calls > 20:
            raise ValueError(
                "bootstrap max_external_calls must be between 1 and 20"
            )
        equity, indexes = normalize_us_current_market_bootstrap_targets(
            equity_symbols=_parse_string_list(request.get("equity_symbols")),
            index_symbols=_parse_string_list(request.get("index_symbols")),
        )
        normalized_request = {
            "equity_symbols": equity,
            "index_symbols": indexes,
            "max_external_calls": max_external_calls,
        }
        return (
            run_us_current_market_bootstrap_job,
            (",".join(equity), ",".join(indexes), max_external_calls),
            normalized_request,
        )

    if job_type == "us_market.watchlist_resource_refresh":
        group_id = request.get("group_id")
        return (
            backfill_tasks.run_us_watchlist_resource_refresh_job,
            (
                int(group_id) if group_id is not None else None,
                bool(request.get("include_children", True)),
                bool(request.get("enabled_only", True)),
                bool(request.get("include_daily", True)),
                bool(request.get("include_sec_facts", True)),
                bool(request.get("include_profile", True)),
                bool(request.get("include_actions", False)),
                str(request.get("outputsize") or "compact"),
                bool(request.get("adjusted", False)),
                float(request.get("sleep_seconds", 12.0)),
            ),
            request,
        )

    if job_type == US_SEC_FORM4_SYNC_JOB_TYPE:
        return (
            backfill_tasks.run_us_sec_form4_sync_job,
            (
                str(request.get("scope") or "symbol"),
                request.get("symbol"),
                int(request["group_id"]) if request.get("group_id") is not None else None,
                bool(request.get("include_children", True)),
                bool(request.get("enabled_only", True)),
                _parse_date(request.get("from_date")),
                _parse_date(request.get("to_date")),
                int(request.get("max_symbols", 25)),
                int(request.get("max_filings_per_symbol", 50)),
            ),
            request,
        )

    if job_type == US_SEC_13F_QUARTER_SYNC_JOB_TYPE:
        return (
            backfill_tasks.run_us_sec_13f_quarter_sync_job,
            (
                str(request.get("period_key") or ""),
                str(request.get("source_url") or ""),
                bool(request.get("force_download", False)),
                bool(request.get("force_rebuild", False)),
            ),
            request,
        )

    if job_type == US_SEC_13F_MAPPING_SYNC_JOB_TYPE:
        return (
            backfill_tasks.run_us_sec_13f_mapping_sync_job,
            (
                _parse_string_list(request.get("cusips")),
                int(request.get("max_identifiers", 25)),
                bool(request.get("refresh", False)),
                bool(request.get("rebuild_projections", True)),
            ),
            request,
        )

    if job_type == US_SEC_13F_HISTORY_SYNC_JOB_TYPE:
        return (
            backfill_tasks.run_us_sec_13f_history_sync_job,
            (
                int(request.get("max_releases", 4)),
                bool(request.get("refresh_manifest", True)),
                bool(request.get("include_completed", False)),
                bool(request.get("force_download", False)),
                bool(request.get("force_rebuild", False)),
                bool(request.get("stop_on_error", False)),
                bool(request.get("rebuild_projections", True)),
            ),
            request,
        )

    if job_type in {
        JP_WATCHLIST_RESOURCE_REFRESH_JOB_TYPE,
        JP_SCHEDULED_WATCHLIST_RESOURCE_REFRESH_JOB_TYPE,
    }:
        group_id = request.get("group_id")
        return (
            backfill_tasks.run_jp_watchlist_resource_refresh_job,
            (
                int(group_id) if group_id is not None else None,
                bool(request.get("include_children", True)),
                bool(request.get("enabled_only", True)),
                bool(request.get("include_daily", True)),
                bool(request.get("include_fundamentals", False)),
                str(request.get("outputsize") or "compact"),
                str(request.get("provider") or "auto"),
                float(request.get("sleep_seconds", 1.0)),
            ),
            request,
        )

    if job_type == "us_market.daily_price_quality_repair":
        return (
            backfill_tasks.run_us_daily_price_quality_repair_job,
            (
                request.get("symbol"),
                bool(request.get("dry_run", True)),
                int(request.get("limit", 1000)),
                bool(request.get("refresh", False)),
                str(request.get("outputsize") or "compact"),
                bool(request.get("adjusted", False)),
                float(request.get("sleep_seconds", 0.0)),
            ),
            request,
        )

    raise ValueError(f"Job type '{job_type}' does not support retry.")


@router.get("", response_model=list[JobRunRead])
def list_jobs(
    status_filter: str | None = Query(default=None, alias="status"),
    job_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    include_payload: bool = Query(
        default=True,
        description="When false, omit request payload and return a compact result summary for polling UIs.",
    ),
    db: Session = Depends(get_db),
):
    jobs = service.list_jobs(
        db=db,
        status=status_filter,
        job_type=job_type,
        limit=limit,
        include_payload=include_payload,
    )
    return [service.serialize_job(job, include_payload=include_payload) for job in jobs]


@router.post(
    "/taiwan/bootstrap-index-daily-bars",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def enqueue_taiwan_index_daily_bootstrap_operator(
    request: TaiwanIndexDailyBootstrapJobRequest,
    db: Session = Depends(get_db),
):
    """Explicit bounded canonical Base-1d bootstrap; never invoked from GET."""

    try:
        job, _created = enqueue_taiwan_index_daily_bootstrap(
            db,
            index_ids=request.index_ids,
            date_from=request.date_from,
            date_to=request.date_to,
            taiex_max_sessions=request.taiex_max_sessions,
            tpex_max_sessions=request.tpex_max_sessions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return service.serialize_job(job)


@router.post(
    "/taiwan/bootstrap-intraday-bars",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def enqueue_taiwan_intraday_bar_bootstrap_operator(
    request: TaiwanIntradayBarBootstrapJobRequest,
    db: Session = Depends(get_db),
):
    """Explicit operator-owned command; never runs from GET or startup."""

    try:
        job, _created = enqueue_taiwan_intraday_bar_bootstrap(
            db,
            symbols=request.symbols,
            max_symbols=request.max_symbols,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return service.serialize_job(job)


@router.post(
    "/us-market/bootstrap-current-cache",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def enqueue_us_current_market_bootstrap_operator(
    request: USCurrentMarketBootstrapJobRequest,
    db: Session = Depends(get_db),
):
    """Explicit operator-owned enqueue; never runs from GET or startup."""

    try:
        job, _created = enqueue_us_current_market_bootstrap_job(
            db,
            equity_symbols=",".join(request.equity_symbols),
            index_symbols=",".join(request.index_symbols),
            max_external_calls=request.max_external_calls,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return service.serialize_job(job)


@router.get("/{job_id}", response_model=JobRunRead)
def get_job(
    job_id: int,
    db: Session = Depends(get_db),
):
    try:
        return service.serialize_job(service.get_job(db, job_id))
    except service.JobRunNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post("/{job_id}/retry", response_model=JobRunRead, status_code=status.HTTP_202_ACCEPTED)
def retry_job(
    job_id: int,
    db: Session = Depends(get_db),
):
    try:
        previous_job = service.get_job(db, job_id)
        task, task_args, request = _retry_config(previous_job)
    except service.JobRunNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    job, _created = service.enqueue_job(
        db=db,
        job_type=previous_job.job_type,
        target=previous_job.target,
        request=request,
        progress_total=max(previous_job.progress_total, 1),
        message=f"Retry queued from job {previous_job.id}.",
        task=task,
        task_args=task_args,
        dedupe_active=False,
    )
    return service.serialize_job(job)
