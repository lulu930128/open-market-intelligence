"""Versioned durable continuation encoding for JobService-owned callables.

Only source-owned top-level run functions in these task modules can be resumed.
No pickle, arbitrary import path, provider selection, scheduler or executor.
Running work needs an independently audited checkpoint; queued work has no IO.
"""
from datetime import date, datetime
import importlib
import inspect
import math
import hashlib
import json
import types
from typing import get_args, get_origin, get_type_hints, Union

from app.utils.backfill_checkpoint import validate_period_state
from app.utils.owner_checkpoint import validate_owner_state


# Exact admission policy; tests compare it with production route/submission reachability.
# A newly added run_* function does NOT acquire replay authority.
QUEUED_TASKS = frozenset({
    ('app.jobs.backfill_tasks', 'run_twse_daily_price_job'),
    ('app.jobs.backfill_tasks', 'run_tpex_daily_price_job'),
    ('app.jobs.backfill_tasks', 'run_market_daily_metrics_job'),
    ('app.jobs.backfill_tasks', 'run_market_chip_daily_refresh_job'),
    ('app.jobs.backfill_tasks', 'run_market_index_summary_refresh_job'),
    ('app.jobs.backfill_tasks', 'run_taiwan_derivatives_refresh_job'),
    ('app.jobs.backfill_tasks', 'run_taiwan_broker_branch_market_refresh_job'),
    ('app.jobs.backfill_tasks', 'run_taiwan_broker_branch_behavior_shadow_job'),
    ('app.jobs.backfill_tasks', 'run_stock_daily_metrics_history_job'),
    ('app.jobs.backfill_tasks', 'run_market_fundamental_metrics_job'),
    ('app.jobs.backfill_tasks', 'run_taiwan_fundamental_snapshot_refresh_job'),
    ('app.jobs.backfill_tasks', 'run_stock_fundamental_metrics_job'),
    ('app.jobs.backfill_tasks', 'run_stock_shareholding_history_job'),
    ('app.jobs.backfill_tasks', 'run_stock_monthly_revenue_history_job'),
    ('app.jobs.backfill_tasks', 'run_stock_financial_metrics_history_job'),
    ('app.jobs.backfill_tasks', 'run_stock_selection_refresh_job'),
    ('app.jobs.backfill_tasks', 'run_watchlist_group_backfill_job'),
    ('app.jobs.backfill_tasks', 'run_watchlist_group_refresh_latest_job'),
    ('app.jobs.backfill_tasks', 'run_watchlist_radar_auto_snapshot_job'),
    ('app.jobs.backfill_tasks', 'run_watchlist_radar_outcome_reconcile_job'),
    ('app.jobs.backfill_tasks', 'run_us_watchlist_daily_refresh_job'),
    ('app.jobs.backfill_tasks', 'run_us_ohlc_history_repair_job'),
    ('app.jobs.backfill_tasks', 'run_us_priority_ohlc_reconcile_job'),
    ('app.jobs.backfill_tasks', 'run_us_intraday_minute_repair_job'),
    ('app.jobs.backfill_tasks', 'run_us_index_intraday_volume_repair_job'),
    ('app.jobs.backfill_tasks', 'run_cross_market_context_refresh_job'),
    ('app.jobs.backfill_tasks', 'run_us_daily_price_quality_repair_job'),
    ('app.jobs.backfill_tasks', 'run_us_watchlist_resource_refresh_job'),
    ('app.jobs.backfill_tasks', 'run_us_sec_form4_sync_job'),
    ('app.jobs.backfill_tasks', 'run_us_sec_sic_sync_job'),
    ('app.jobs.backfill_tasks', 'run_us_sec_13f_quarter_sync_job'),
    ('app.jobs.backfill_tasks', 'run_us_sec_13f_history_sync_job'),
    ('app.jobs.backfill_tasks', 'run_us_sec_13f_mapping_sync_job'),
    ('app.jobs.backfill_tasks', 'run_jp_watchlist_resource_refresh_job'),
    ('app.jobs.backfill_tasks', 'run_kr_watchlist_resource_refresh_job'),
    ('app.jobs.eod_coverage', 'run_eod_coverage_reconcile_job'),
    ('app.jobs.taiwan_bar_bootstrap', 'run_taiwan_intraday_bar_bootstrap_job'),
    ('app.jobs.taiwan_bar_bootstrap', 'run_taiwan_index_daily_bootstrap_job'),
    ('app.jobs.us_current_market_bootstrap', 'run_us_current_market_bootstrap_job'),
    ('app.jobs.us_index_data_repair_gate', 'run_us_index_data_repair_job'),
    ('app.stocks.bootstrap', 'run_stock_master_bootstrap_job'),
})
PERIOD_TASK_OWNERS = {
    ("app.jobs.backfill_tasks", "run_market_daily_metrics_job"): "daily_metric_source_date",
    ("app.jobs.backfill_tasks", "run_watchlist_radar_auto_snapshot_job"): "radar_snapshot_scope",
    ("app.jobs.backfill_tasks", 'run_twse_daily_price_job'): 'twse_price_month',
    ("app.jobs.backfill_tasks", 'run_tpex_daily_price_job'): 'tpex_price_month',
    ("app.jobs.backfill_tasks", 'run_stock_shareholding_history_job'): 'shareholding_week',
    ("app.jobs.backfill_tasks", 'run_stock_monthly_revenue_history_job'): 'revenue_month',
    ("app.jobs.backfill_tasks", 'run_stock_financial_metrics_history_job'): 'financial_quarter',
}
RESUME_KEY = "job_service_resume_v1"
OWNER_TASKS = {
    ("app.jobs.eod_coverage", "run_eod_coverage_reconcile_job"): "us_eod_symbols",
    ("app.jobs.backfill_tasks", "run_us_priority_ohlc_reconcile_job"): "us_priority_symbols",
    ("app.jobs.taiwan_bar_bootstrap", "run_taiwan_intraday_bar_bootstrap_job"): "tw_bootstrap_children",
}
RADAR_OUTCOME_TASK = ("app.jobs.backfill_tasks", "run_watchlist_radar_outcome_reconcile_job")
ORIGINAL_STATE_MACHINE_TASKS = frozenset({
    ("app.dispatch.tasks", "run_dispatch_delivery_job"),
    ("app.dispatch.tasks", "run_dispatch_schedule_run_job"),
    ("app.jobs.taiwan_intraday_demand", "run_consumer_demand"),
})
ORIGINAL_HANDOFF_TASKS = frozenset({
    ("app.jobs.taiwan_intraday_demand", "run_consumer_demand"),
})


def encode(value):
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if type(value) in (date, datetime):
        return {"type": type(value).__name__, "value": value.isoformat()}
    if type(value) in (tuple, list):
        return {"type": type(value).__name__, "value": [encode(v) for v in value]}
    if type(value) is dict and all(type(k) is str for k in value):
        return {"type": "dict", "value": {k: encode(v) for k, v in value.items()}}
    raise ValueError("JOB_RESUME_ARGUMENT_UNSUPPORTED")


def decode(value, *, _depth=0):
    if _depth > 20:
        raise ValueError("JOB_RESUME_ARGUMENT_TOO_DEEP")
    if type(value) is not dict:
        if value is None or type(value) in (str, int, bool):
            return value
        if type(value) is float and math.isfinite(value):
            return value
        raise ValueError("JOB_RESUME_ARGUMENT_INVALID")
    if set(value) != {"type", "value"} or type(value["type"]) is not str:
        raise ValueError("JOB_RESUME_ARGUMENT_INVALID")
    kind, data = value["type"], value["value"]
    if kind == "date" and type(data) is str:
        return date.fromisoformat(data)
    if kind == "datetime" and type(data) is str:
        return datetime.fromisoformat(data)
    if kind in ("tuple", "list") and type(data) is list:
        items = [decode(v, _depth=_depth + 1) for v in data]
        return tuple(items) if kind == "tuple" else items
    if kind == "dict" and type(data) is dict and all(type(k) is str for k in data):
        return {k: decode(v, _depth=_depth + 1) for k, v in data.items()}
    raise ValueError("JOB_RESUME_ARGUMENT_INVALID")


def resolve(module, name):
    if type(module) is not str or type(name) is not str or (module, name) not in QUEUED_TASKS:
        raise ValueError("JOB_RESUME_TASK_UNSUPPORTED")
    task = getattr(importlib.import_module(module), name, None)
    if not inspect.isfunction(task) or task.__module__ != module or task.__qualname__ != name:
        raise ValueError("JOB_RESUME_TASK_UNSUPPORTED")
    return task


def describe(task, args, lane):
    module, name = getattr(task, "__module__", None), getattr(task, "__name__", None)
    if resolve(module, name) is not task:
        raise ValueError("JOB_RESUME_TASK_UNSUPPORTED")
    return {"module": module, "name": name, "args": encode(args), "lane": lane}


def validate(descriptor):
    if type(descriptor) is not dict or set(descriptor) != {
        "module", "name", "args", "lane", "previous_status", "previous_result", "checkpoint",
    }:
        raise ValueError("JOB_RESUME_DESCRIPTOR_INVALID")
    if descriptor["lane"] not in ("default", "market_interactive", "market_background", "market_completed"):
        raise ValueError("JOB_RESUME_LANE_INVALID")
    if descriptor["previous_status"] not in ("queued", "running"):
        raise ValueError("JOB_RESUME_STATE_INVALID")
    checkpoint = descriptor["checkpoint"]
    if type(checkpoint) is not dict or type(checkpoint.get("safe_point")) is not str:
        raise ValueError("JOB_RESUME_CHECKPOINT_INVALID")
    identity = (descriptor["module"], descriptor["name"])
    if not all(type(value) is str for value in identity):
        raise ValueError("JOB_RESUME_TASK_UNSUPPORTED")
    if checkpoint["safe_point"] == "owner_transaction_complete":
        if (identity not in OWNER_TASKS
                or set(checkpoint) != {"safe_point", "owner", "state", "current", "total", "job_id", "binding"}
                or checkpoint["owner"] != OWNER_TASKS[identity]
                or descriptor["previous_status"] != "running"
                or type(checkpoint["job_id"]) is not int or checkpoint["job_id"] <= 0
                or checkpoint["binding"] != period_binding(identity, decode(descriptor["args"]))):
            raise ValueError("JOB_RESUME_CHECKPOINT_UNSUPPORTED")
        validate_owner_state(checkpoint["state"], safe=True)
        if (checkpoint["state"]["owner"] != checkpoint["owner"]
                or checkpoint["current"] != len(checkpoint["state"]["results"])
                or checkpoint["total"] != len(checkpoint["state"]["items"])):
            raise ValueError("JOB_RESUME_CHECKPOINT_INVALID")
    elif checkpoint["safe_point"] == "period_transaction_complete":
        if (identity not in PERIOD_TASK_OWNERS
                or set(checkpoint) != {"safe_point", "owner", "state", "current", "total", "job_id", "binding"}
                or checkpoint["owner"] != PERIOD_TASK_OWNERS[identity]
                or descriptor["previous_status"] != "running"
                or type(checkpoint["job_id"]) is not int or checkpoint["job_id"] <= 0
                or checkpoint["binding"] != period_binding(identity, decode(descriptor["args"]))):
            raise ValueError("JOB_RESUME_CHECKPOINT_UNSUPPORTED")
        validate_period_state(checkpoint["state"])
        _validate_period_identity(checkpoint["owner"], checkpoint["state"]["identity"])
        if (checkpoint["current"] != checkpoint["state"]["completed"]
                or checkpoint["total"] != len(checkpoint["state"]["items"])):
            raise ValueError("JOB_RESUME_CHECKPOINT_INVALID")
    elif checkpoint["safe_point"] == "radar_outcome_transaction_complete":
        from app.watchlists.radar_rule_contract import RADAR_V2_ACTIVE_CONTRACT
        if (identity != RADAR_OUTCOME_TASK
                or set(checkpoint) != {"safe_point", "evaluation_id", "contract", "job_id", "binding"}
                or descriptor["previous_status"] != "running"
                or type(checkpoint["evaluation_id"]) is not int or checkpoint["evaluation_id"] <= 0
                or type(checkpoint["job_id"]) is not int or checkpoint["job_id"] <= 0
                or checkpoint["contract"] != RADAR_V2_ACTIVE_CONTRACT["outcome_config_hash"]
                or checkpoint["binding"] != period_binding(identity, decode(descriptor["args"]))):
            raise ValueError("JOB_RESUME_CHECKPOINT_UNSUPPORTED")
    elif checkpoint["safe_point"] != "not_started" and (
        identity != ("app.jobs.backfill_tasks", "run_taiwan_broker_branch_market_refresh_job")
        or checkpoint["safe_point"] not in {
            "before_universe", "before_probe", "before_stock", "stock_transaction_complete",
        }
    ):
        raise ValueError("JOB_RESUME_CHECKPOINT_UNSUPPORTED")
    if checkpoint["safe_point"] == "not_started" and descriptor["previous_status"] != "queued":
        raise ValueError("JOB_RESUME_NOT_STARTED_PROVENANCE_INVALID")
    task = resolve(descriptor["module"], descriptor["name"])
    args = decode(descriptor["args"])
    if type(args) is not tuple:
        raise ValueError("JOB_RESUME_ARGS_INVALID")
    bound = inspect.signature(task).bind(0, *args)
    hints = get_type_hints(task)
    for name, value in bound.arguments.items():
        if name in hints and not _matches_type(value, hints[name]):
            raise ValueError("JOB_RESUME_ARGUMENT_TYPE_INVALID")
    return task, args


def period_binding(identity, args):
    payload = json.dumps([identity, encode(args)], sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validate_period_identity(owner, identity):
    """Reject malformed private context before consuming a paused obligation."""
    valid = False
    dates = []
    if owner in {"twse_price_month", "tpex_price_month", "revenue_month", "financial_quarter", "shareholding_week"}:
        price = owner in {"twse_price_month", "tpex_price_month"}
        valid = (len(identity) == (5 if price else 2)
                 and type(identity[0]) is str and bool(identity[0])
                 and type(identity[1]) is int and identity[1] > 0)
        dates = identity[2:] if price else []
    elif owner == "daily_metric_source_date":
        valid = (len(identity) == 4 and all(type(values) is list and
                 all(type(value) is str for value in values) for values in identity[2:]))
        dates = identity[:2]
    elif owner == "radar_snapshot_scope":
        valid = len(identity) == 3 and all(type(value) is str and bool(value) for value in identity)
        dates = identity[:1]
    try:
        valid = valid and all(type(value) is str and date.fromisoformat(value).isoformat() == value for value in dates)
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("JOB_RESUME_PERIOD_IDENTITY_INVALID")


def _matches_type(value, hint):
    origin, options = get_origin(hint), get_args(hint)
    if origin in (Union, types.UnionType):
        return any(_matches_type(value, option) for option in options)
    if origin is list:
        return type(value) is list and all(_matches_type(item, options[0]) for item in value)
    if origin is tuple:
        if len(options) == 2 and options[1] is Ellipsis:
            return type(value) is tuple and all(_matches_type(item, options[0]) for item in value)
        return type(value) is tuple and len(value) == len(options) and all(
            _matches_type(item, option) for item, option in zip(value, options))
    if hint is float:
        return type(value) in (int, float) and math.isfinite(value)
    return type(value) is hint
