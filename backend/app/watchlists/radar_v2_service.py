from __future__ import annotations

import json
from datetime import date
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    RadarBacktestRun,
    RadarOutcomePath,
    RadarRuleConfig,
    RadarRuleEvaluation,
    RadarUniverseObservation,
    RadarWatchlistProjection,
    WatchlistRadarSnapshotRun,
)
from app.market.daily_price_repository import TaiwanOfficialDailyBarRepository
from app.market.trading_calendar import next_taiwan_trading_day
from app.market.tw_daily_freshness import read_taiwan_daily_freshness
from app.watchlists.radar_rule_contract import (
    RADAR_V1_FROZEN_AT,
    RADAR_V1_LIFECYCLE_STATUS,
    RADAR_V1_RULE_VERSION,
    RADAR_V2_ACTIVE_OUTCOME_CONFIG_HASH,
    RADAR_V2_ACTIVE_OUTCOME_CONTRACT_VERSION,
    RADAR_V2_ACTIVE_RULE_CONFIG_HASH,
    RADAR_V2_ACTIVE_RULE_VERSION,
    RADAR_V2_RULE_CONFIG_HASH,
    RADAR_V2_RULE_VERSION,
    canonical_config_json,
)


class RadarConfigConflictError(RuntimeError):
    pass


def json_dumps(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _outcome_limitation_objects(value: str | None) -> list[dict[str, Any]]:
    limitations = json_loads(value, [])
    if not isinstance(limitations, list):
        return [{"code": "malformed_outcome_limitations"}]
    normalized: list[dict[str, Any]] = []
    for limitation in limitations:
        if isinstance(limitation, dict):
            normalized.append(dict(limitation))
        elif isinstance(limitation, str):
            normalized.append({"code": limitation})
        else:
            normalized.append(
                {
                    "code": "unrecognized_outcome_limitation",
                    "value": str(limitation),
                }
            )
    return normalized


def _outcome_horizon_dates(
    signal_trade_date: date,
    horizon_trading_days: int,
) -> list[date]:
    dates: list[date] = []
    current = signal_trade_date
    for _ in range(max(int(horizon_trading_days), 0)):
        current = next_taiwan_trading_day(
            current,
            include_value=False,
        )
        dates.append(current)
    return dates


def ensure_rule_config(
    *,
    db: Session,
    contract_type: str,
    version: str,
    config_hash: str,
    config: dict[str, Any],
    status: str = "shadow",
    description: str | None = None,
    code_commit_sha: str | None = None,
) -> RadarRuleConfig:
    canonical = canonical_config_json(config)
    existing = (
        db.query(RadarRuleConfig)
        .filter(RadarRuleConfig.contract_type == contract_type)
        .filter(RadarRuleConfig.version == version)
        .filter(RadarRuleConfig.config_hash == config_hash)
        .one_or_none()
    )
    if existing is not None:
        if canonical_config_json(json_loads(existing.config_json, {})) != canonical:
            raise RadarConfigConflictError(
                "Radar config hash resolved to different canonical content."
            )
        return existing

    row = RadarRuleConfig(
        contract_type=contract_type,
        version=version,
        config_hash=config_hash,
        status=status,
        config_json=canonical,
        description=description,
        code_commit_sha=code_commit_sha,
    )
    db.add(row)
    db.flush()
    return row


def get_radar_v2_validation_readiness(
    *,
    db: Session,
    group_id: int | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    backtest_query = (
        db.query(RadarBacktestRun)
        .filter(
            RadarBacktestRun.rule_version
            == RADAR_V2_ACTIVE_RULE_VERSION
        )
        .filter(
            RadarBacktestRun.rule_config_hash
            == RADAR_V2_ACTIVE_RULE_CONFIG_HASH
        )
    )
    backtest_rows = (
        backtest_query.order_by(
            RadarBacktestRun.completed_at.desc(),
            RadarBacktestRun.id.desc(),
        )
        .limit(100)
        .all()
    )
    scope_key = (
        f"watchlist_group:{group_id}:{mode}"
        if group_id is not None and group_id > 0 and mode is not None
        else None
    )
    if scope_key is not None:
        backtest_rows = [
            row
            for row in backtest_rows
            if json_loads(row.universe_json, {}).get("scope_key")
            == scope_key
        ]
    latest_backtest = backtest_rows[0] if backtest_rows else None
    completed_backtest_count = sum(
        row.status == "completed" for row in backtest_rows
    )

    outcome_query = (
        db.query(RadarOutcomePath)
        .join(
            RadarUniverseObservation,
            RadarUniverseObservation.evaluation_id
            == RadarOutcomePath.evaluation_id,
        )
        .filter(
            RadarUniverseObservation.rule_version
            == RADAR_V2_ACTIVE_RULE_VERSION
        )
        .filter(
            RadarUniverseObservation.rule_config_hash
            == RADAR_V2_ACTIVE_RULE_CONFIG_HASH
        )
        .filter(RadarUniverseObservation.selected.is_(True))
        .filter(
            RadarOutcomePath.outcome_contract_version
            == RADAR_V2_ACTIVE_OUTCOME_CONTRACT_VERSION
        )
        .filter(
            RadarOutcomePath.outcome_config_hash
            == RADAR_V2_ACTIVE_OUTCOME_CONFIG_HASH
        )
    )
    if group_id is not None and group_id > 0:
        outcome_query = outcome_query.filter(
            RadarUniverseObservation.group_id == group_id
        )
    if mode is not None:
        outcome_query = outcome_query.filter(
            RadarUniverseObservation.mode == mode
        )
    outcome_count = int(
        outcome_query.with_entities(
            func.count(func.distinct(RadarOutcomePath.id))
        ).scalar()
        or 0
    )
    pending_outcome_count = int(
        outcome_query.filter(
            RadarOutcomePath.status == "pending"
        )
        .with_entities(
            func.count(func.distinct(RadarOutcomePath.id))
        )
        .scalar()
        or 0
    )
    finalized_outcome_count = max(
        0,
        outcome_count - pending_outcome_count,
    )
    validation_status = (
        "verified"
        if latest_backtest is not None
        and latest_backtest.status == "completed"
        else "blocked"
        if latest_backtest is not None
        and latest_backtest.status == "blocked"
        else "unverified"
    )
    limitations: list[dict[str, Any]] = []
    if latest_backtest is None:
        limitations.append(
            {
                "code": "walk_forward_incremental_value_not_verified",
            }
        )
    elif latest_backtest.status != "completed":
        limitations.append(
            {
                "code": "latest_backtest_gate_not_passed",
                "status": latest_backtest.status,
                "run_id": latest_backtest.id,
            }
        )
    if outcome_count == 0:
        limitations.append({"code": "active_outcomes_not_available"})
    elif pending_outcome_count:
        limitations.append(
            {
                "code": "active_outcomes_pending",
                "count": pending_outcome_count,
            }
        )
    return {
        "operational_status": "active",
        "validation_status": validation_status,
        "backtest_status": (
            latest_backtest.status if latest_backtest is not None else "missing"
        ),
        "latest_backtest_id": (
            latest_backtest.id if latest_backtest is not None else None
        ),
        "completed_backtest_count": completed_backtest_count,
        "outcome_count": outcome_count,
        "finalized_outcome_count": finalized_outcome_count,
        "pending_outcome_count": pending_outcome_count,
        "limitations": limitations,
    }


def get_latest_radar_v2_projection(
    *,
    db: Session,
    group_id: int,
    mode: str,
    max_results: int = 30,
    minimum_snapshot_date: date | None = None,
) -> dict[str, Any] | None:
    run_query = (
        db.query(WatchlistRadarSnapshotRun)
        .filter(WatchlistRadarSnapshotRun.group_id == group_id)
        .filter(WatchlistRadarSnapshotRun.mode == mode)
        .filter(
            WatchlistRadarSnapshotRun.radar_rule_version
            == RADAR_V2_ACTIVE_RULE_VERSION
        )
    )
    if minimum_snapshot_date is not None:
        run_query = run_query.filter(
            WatchlistRadarSnapshotRun.snapshot_date
            >= minimum_snapshot_date
        )
    run = run_query.order_by(
        WatchlistRadarSnapshotRun.snapshot_date.desc(),
        WatchlistRadarSnapshotRun.id.desc(),
    ).first()
    if run is None:
        return None
    snapshot_date = run.snapshot_date
    request_meta = json_loads(run.request_json, {})
    radar_meta: dict[str, Any] = {
        "group_id": run.group_id,
        "include_children": run.include_children,
        "mode": run.mode,
        "max_results": run.max_results,
        "requested_stock_count": run.requested_stock_count,
        "ranked_count": run.ranked_count,
        "matched_count": run.matched_count,
        "radar_count": run.radar_count,
        "no_data_count": run.no_data_count,
        "error_count": run.error_count,
        "trade_date": run.trade_date,
        "target_trade_date": run.target_trade_date,
        "is_current": run.is_current,
        "current_stock_count": run.current_stock_count,
        "stale_stock_count": run.stale_stock_count,
        "buckets": json_loads(run.buckets_json, []),
        "data_limitations": json_loads(
            run.data_limitations_json,
            [],
        ),
        "radar_engine": request_meta.get("radar_engine") or {},
        "radar_v2_summary": request_meta.get("radar_v2_summary") or {},
    }

    projection_rows = (
        db.query(RadarWatchlistProjection)
        .join(
            RadarRuleEvaluation,
            RadarRuleEvaluation.id
            == RadarWatchlistProjection.evaluation_id,
        )
        .filter(RadarWatchlistProjection.group_id == group_id)
        .filter(RadarWatchlistProjection.mode == mode)
        .filter(
            RadarWatchlistProjection.snapshot_date == snapshot_date
        )
        .filter(RadarWatchlistProjection.selected.is_(True))
        .filter(
            RadarRuleEvaluation.rule_version
            == RADAR_V2_ACTIVE_RULE_VERSION
        )
        .filter(
            RadarRuleEvaluation.rule_config_hash
            == RADAR_V2_ACTIVE_RULE_CONFIG_HASH
        )
        .order_by(
            RadarWatchlistProjection.rank.asc(),
            RadarWatchlistProjection.id.asc(),
        )
        .all()
    )
    limit = max(1, min(int(max_results), 200))
    results: list[dict[str, Any]] = []
    projection_meta_loaded = False
    for row in projection_rows:
        projection = json_loads(row.projection_json, {})
        if (
            not projection_meta_loaded
            and isinstance(projection.get("radar_meta"), dict)
        ):
            radar_meta.update(projection["radar_meta"])
            projection_meta_loaded = True
        item = projection.get("item")
        if not isinstance(item, dict):
            continue
        results.append(dict(item))
    results = results[:limit]
    for rank, item in enumerate(results, start=1):
        item["rank"] = rank

    observations = (
        db.query(RadarUniverseObservation)
        .filter(RadarUniverseObservation.group_id == group_id)
        .filter(RadarUniverseObservation.mode == mode)
        .filter(RadarUniverseObservation.snapshot_date == snapshot_date)
        .filter(
            RadarUniverseObservation.rule_version
            == RADAR_V2_ACTIVE_RULE_VERSION
        )
        .filter(
            RadarUniverseObservation.rule_config_hash
            == RADAR_V2_ACTIVE_RULE_CONFIG_HASH
        )
        .all()
    )
    active_observations = [
        row for row in observations if row.observation_status != "absent"
    ]
    evaluated_count = sum(
        row.observation_status == "evaluated"
        for row in active_observations
    )
    no_data_count = sum(
        row.observation_status == "no_data"
        for row in active_observations
    )
    error_count = sum(
        row.observation_status == "error"
        for row in active_observations
    )
    calculated_at = max(
        (row.observed_at for row in observations),
        default=run.updated_at,
    )
    payload = dict(radar_meta)
    payload.update(
        {
            "group_id": group_id,
            "include_children": bool(
                radar_meta.get("include_children", True)
            ),
            "mode": mode,
            "max_results": limit,
            "requested_stock_count": int(
                radar_meta.get(
                    "requested_stock_count",
                    len(active_observations),
                )
                or 0
            ),
            "ranked_count": int(
                radar_meta.get("ranked_count", evaluated_count) or 0
            ),
            "matched_count": int(
                radar_meta.get("matched_count", len(projection_rows)) or 0
            ),
            "radar_count": len(results),
            "no_data_count": int(
                radar_meta.get("no_data_count", no_data_count) or 0
            ),
            "error_count": int(
                radar_meta.get("error_count", error_count) or 0
            ),
            "trade_date": radar_meta.get("trade_date")
            or snapshot_date.isoformat(),
            "target_trade_date": radar_meta.get("target_trade_date")
            or snapshot_date.isoformat(),
            "is_current": bool(radar_meta.get("is_current", True)),
            "current_stock_count": int(
                radar_meta.get("current_stock_count", evaluated_count) or 0
            ),
            "stale_stock_count": int(
                radar_meta.get("stale_stock_count", 0) or 0
            ),
            "buckets": list(radar_meta.get("buckets") or []),
            "results": results,
            "cache_status": "v2_snapshot",
            "snapshot_id": run.id,
            "snapshot_date": snapshot_date,
            "calculated_at": calculated_at,
            "radar_engine": {
                "active_version": RADAR_V2_ACTIVE_RULE_VERSION,
                "active_config_hash": RADAR_V2_ACTIVE_RULE_CONFIG_HASH,
                "shadow_version": RADAR_V2_RULE_VERSION,
                "shadow_config_hash": RADAR_V2_RULE_CONFIG_HASH,
                "mode": "active",
                "rollback_version": RADAR_V1_RULE_VERSION,
                "technical_direction_owner": "backend",
                "legacy_status": RADAR_V1_LIFECYCLE_STATUS,
                "legacy_frozen_at": RADAR_V1_FROZEN_AT,
            },
        }
    )
    summary = dict(radar_meta.get("radar_v2_summary") or {})
    summary["evaluated_count"] = len(results)
    summary["universe_evaluated_count"] = evaluated_count
    summary["universe_scope"] = "complete_calculation_universe"
    summary["readiness"] = get_radar_v2_validation_readiness(
        db=db,
        group_id=group_id,
        mode=mode,
    )
    payload["radar_v2_summary"] = summary
    return payload


def list_radar_v2_projection_history(
    *,
    db: Session,
    group_id: int,
    mode: str,
    limit: int = 30,
) -> list[dict[str, Any]]:
    runs = (
        db.query(WatchlistRadarSnapshotRun)
        .filter(WatchlistRadarSnapshotRun.group_id == group_id)
        .filter(WatchlistRadarSnapshotRun.mode == mode)
        .filter(
            WatchlistRadarSnapshotRun.radar_rule_version
            == RADAR_V2_ACTIVE_RULE_VERSION
        )
        .order_by(
            WatchlistRadarSnapshotRun.snapshot_date.desc(),
            WatchlistRadarSnapshotRun.id.desc(),
        )
        .limit(max(1, min(int(limit), 120)))
        .all()
    )
    output: list[dict[str, Any]] = []
    for run in runs:
        observations = (
            db.query(RadarUniverseObservation)
            .filter(RadarUniverseObservation.group_id == group_id)
            .filter(RadarUniverseObservation.mode == mode)
            .filter(
                RadarUniverseObservation.snapshot_date
                == run.snapshot_date
            )
            .filter(
                RadarUniverseObservation.rule_version
                == RADAR_V2_ACTIVE_RULE_VERSION
            )
            .filter(
                RadarUniverseObservation.rule_config_hash
                == RADAR_V2_ACTIVE_RULE_CONFIG_HASH
            )
            .all()
        )
        output.append(
            {
            "group_id": group_id,
            "mode": mode,
            "snapshot_date": run.snapshot_date,
            "rule_version": RADAR_V2_ACTIVE_RULE_VERSION,
            "rule_config_hash": RADAR_V2_ACTIVE_RULE_CONFIG_HASH,
            "universe_observed_count": len(observations),
            "selected_count": sum(row.selected for row in observations),
            "observed_at": max(
                (row.observed_at for row in observations),
                default=run.updated_at,
            ),
        }
        )
    return output


def list_radar_v2_scope_stock_ids(
    *,
    db: Session,
    group_id: int,
    mode: str,
    period_start: date,
    period_end: date,
) -> list[str]:
    return [
        str(stock_id)
        for (stock_id,) in (
            db.query(RadarUniverseObservation.stock_id)
            .filter(RadarUniverseObservation.group_id == group_id)
            .filter(RadarUniverseObservation.mode == mode)
            .filter(
                RadarUniverseObservation.snapshot_date >= period_start
            )
            .filter(
                RadarUniverseObservation.snapshot_date <= period_end
            )
            .filter(
                RadarUniverseObservation.rule_version
                == RADAR_V2_ACTIVE_RULE_VERSION
            )
            .filter(
                RadarUniverseObservation.rule_config_hash
                == RADAR_V2_ACTIVE_RULE_CONFIG_HASH
            )
            .filter(
                RadarUniverseObservation.observation_status == "evaluated"
            )
            .distinct()
            .order_by(RadarUniverseObservation.stock_id.asc())
            .all()
        )
    ]


def get_radar_v2_outcome_summary(
    *,
    db: Session,
    group_id: int,
    mode: str,
    snapshot_date: date | None = None,
    horizon_trading_days: int = 1,
    item_limit: int = 30,
) -> dict[str, Any]:
    if snapshot_date is None:
        snapshot_date = (
            db.query(func.max(WatchlistRadarSnapshotRun.snapshot_date))
            .filter(WatchlistRadarSnapshotRun.group_id == group_id)
            .filter(WatchlistRadarSnapshotRun.mode == mode)
            .filter(
                WatchlistRadarSnapshotRun.radar_rule_version
                == RADAR_V2_ACTIVE_RULE_VERSION
            )
            .scalar()
        )
    if snapshot_date is None:
        return {
            "status": "no_snapshot",
            "group_id": group_id,
            "mode": mode,
            "snapshot_date": None,
            "horizon_trading_days": horizon_trading_days,
            "rule_version": RADAR_V2_ACTIVE_RULE_VERSION,
            "outcome_contract_version": (
                RADAR_V2_ACTIVE_OUTCOME_CONTRACT_VERSION
            ),
            "total_count": 0,
            "finalized_count": 0,
            "pending_count": 0,
            "latest_available_trade_date": None,
            "last_reconciled_at": None,
            "pending_reason_counts": {},
            "summary_state_counts": {},
            "items": [],
            "data_limitations": ["active_radar_v2_snapshot_not_available"],
        }
    observations = (
        db.query(RadarUniverseObservation)
        .filter(RadarUniverseObservation.group_id == group_id)
        .filter(RadarUniverseObservation.mode == mode)
        .filter(RadarUniverseObservation.snapshot_date == snapshot_date)
        .filter(RadarUniverseObservation.selected.is_(True))
        .filter(
            RadarUniverseObservation.rule_version
            == RADAR_V2_ACTIVE_RULE_VERSION
        )
        .filter(
            RadarUniverseObservation.rule_config_hash
            == RADAR_V2_ACTIVE_RULE_CONFIG_HASH
        )
        .order_by(
            RadarUniverseObservation.source_rank.asc(),
            RadarUniverseObservation.stock_id.asc(),
        )
        .all()
    )
    evaluation_ids = [
        int(row.evaluation_id)
        for row in observations
        if row.evaluation_id is not None
    ]
    outcome_rows = (
        db.query(RadarOutcomePath)
        .filter(RadarOutcomePath.evaluation_id.in_(evaluation_ids))
        .filter(
            RadarOutcomePath.outcome_contract_version
            == RADAR_V2_ACTIVE_OUTCOME_CONTRACT_VERSION
        )
        .filter(
            RadarOutcomePath.outcome_config_hash
            == RADAR_V2_ACTIVE_OUTCOME_CONFIG_HASH
        )
        .filter(
            RadarOutcomePath.horizon_trading_days
            == horizon_trading_days
        )
        .all()
        if evaluation_ids
        else []
    )
    by_evaluation = {row.evaluation_id: row for row in outcome_rows}
    stock_ids = sorted({row.stock_id for row in observations})
    latest_available_trade_date = read_taiwan_daily_freshness(db).latest_date
    expected_dates_by_evaluation: dict[int, list[date]] = {}
    for observation in observations:
        if observation.evaluation_id is None:
            continue
        outcome = by_evaluation.get(observation.evaluation_id)
        signal_trade_date = (
            outcome.signal_trade_date
            if outcome is not None
            else observation.snapshot_date
        )
        expected_dates_by_evaluation[int(observation.evaluation_id)] = (
            _outcome_horizon_dates(
                signal_trade_date,
                horizon_trading_days,
            )
        )
    expected_dates = sorted(
        {
            trade_date
            for dates in expected_dates_by_evaluation.values()
            for trade_date in dates
        }
    )
    stock_id_set = set(stock_ids)
    daily_repository = TaiwanOfficialDailyBarRepository(db)
    available_daily_bars = {
        (bar.instrument.symbol, trade_date)
        for trade_date in expected_dates
        for bar in daily_repository.load_market_universe(
            trade_date=trade_date,
            include_etf=True,
        ).bars
        if bar.instrument.symbol in stock_id_set
    }
    last_reconciled_at = max(
        (
            outcome.evaluated_at
            for outcome in outcome_rows
            if outcome.evaluated_at is not None
        ),
        default=None,
    )
    summary_state_counts: dict[str, int] = {}
    pending_reason_counts: dict[str, int] = {}
    items: list[dict[str, Any]] = []
    for observation in observations:
        outcome = by_evaluation.get(observation.evaluation_id)
        status = outcome.status if outcome is not None else "pending"
        summary_state = (
            outcome.summary_state if outcome is not None else "pending"
        )
        summary_state_counts[summary_state] = (
            summary_state_counts.get(summary_state, 0) + 1
        )
        horizon_dates = expected_dates_by_evaluation.get(
            int(observation.evaluation_id)
            if observation.evaluation_id is not None
            else -1,
            [],
        )
        horizon_end_trade_date = (
            outcome.horizon_end_trade_date
            if outcome is not None
            else horizon_dates[-1]
            if horizon_dates
            else None
        )
        pending_reason: str | None = None
        if status == "pending":
            if (
                horizon_end_trade_date is not None
                and latest_available_trade_date is not None
                and horizon_end_trade_date
                > latest_available_trade_date
            ):
                pending_reason = "not_due"
            elif horizon_dates and all(
                (observation.stock_id, trade_date)
                in available_daily_bars
                for trade_date in horizon_dates
            ):
                pending_reason = "ready_to_reconcile"
            else:
                pending_reason = "awaiting_daily_bar"
            pending_reason_counts[pending_reason] = (
                pending_reason_counts.get(pending_reason, 0) + 1
            )
        if len(items) >= max(0, min(int(item_limit), 200)):
            continue
        items.append(
            {
                "evaluation_id": observation.evaluation_id,
                "stock_id": observation.stock_id,
                "stock_name": observation.stock_name,
                "source_rank": observation.source_rank,
                "status": status,
                "summary_state": summary_state,
                "horizon_end_trade_date": horizon_end_trade_date,
                "pending_reason": pending_reason,
                "signal_close_return_pct": (
                    outcome.signal_close_return_pct
                    if outcome is not None
                    else None
                ),
                "signal_mfe_pct": (
                    outcome.signal_mfe_pct
                    if outcome is not None
                    else None
                ),
                "signal_mae_pct": (
                    outcome.signal_mae_pct
                    if outcome is not None
                    else None
                ),
                "outcome_quality": (
                    outcome.outcome_quality
                    if outcome is not None
                    else "unknown"
                ),
                "limitations": (
                    _outcome_limitation_objects(outcome.limitations_json)
                    if outcome is not None
                    else [{"code": "outcome_not_evaluated"}]
                ),
            }
        )
    total_count = len(observations)
    pending_count = sum(
        by_evaluation.get(observation.evaluation_id) is None
        or by_evaluation[observation.evaluation_id].status == "pending"
        for observation in observations
    )
    finalized_count = max(0, total_count - pending_count)
    all_pending_not_due = bool(pending_count) and (
        pending_reason_counts.get("not_due", 0) == pending_count
    )
    data_limitations: list[str] = []
    if pending_reason_counts.get("not_due"):
        data_limitations.append("pending_outcomes_not_due")
    if pending_reason_counts.get("awaiting_daily_bar"):
        data_limitations.append("pending_outcomes_awaiting_daily_bars")
    if pending_reason_counts.get("ready_to_reconcile"):
        data_limitations.append("pending_outcomes_ready_to_reconcile")
    return {
        "status": (
            "not_due"
            if all_pending_not_due
            else "not_evaluated"
            if not outcome_rows
            else "pending"
            if pending_count
            else "evaluated"
        ),
        "group_id": group_id,
        "mode": mode,
        "snapshot_date": snapshot_date,
        "horizon_trading_days": horizon_trading_days,
        "rule_version": RADAR_V2_ACTIVE_RULE_VERSION,
        "outcome_contract_version": (
            RADAR_V2_ACTIVE_OUTCOME_CONTRACT_VERSION
        ),
        "total_count": total_count,
        "finalized_count": finalized_count,
        "pending_count": pending_count,
        "latest_available_trade_date": latest_available_trade_date,
        "last_reconciled_at": last_reconciled_at,
        "pending_reason_counts": dict(
            sorted(pending_reason_counts.items())
        ),
        "summary_state_counts": dict(sorted(summary_state_counts.items())),
        "items": items,
        "data_limitations": data_limitations,
    }


def list_radar_v2_outcome_history(
    *,
    db: Session,
    group_id: int,
    mode: str,
    horizon_trading_days: int = 1,
    limit: int = 30,
) -> list[dict[str, Any]]:
    dates = [
        row["snapshot_date"]
        for row in list_radar_v2_projection_history(
            db=db,
            group_id=group_id,
            mode=mode,
            limit=limit,
        )
    ]
    return [
        get_radar_v2_outcome_summary(
            db=db,
            group_id=group_id,
            mode=mode,
            snapshot_date=snapshot_date,
            horizon_trading_days=horizon_trading_days,
            item_limit=0,
        )
        for snapshot_date in dates
    ]


__all__ = [
    "RadarConfigConflictError",
    "ensure_rule_config",
    "get_latest_radar_v2_projection",
    "get_radar_v2_outcome_summary",
    "get_radar_v2_validation_readiness",
    "json_dumps",
    "json_loads",
    "list_radar_v2_outcome_history",
    "list_radar_v2_projection_history",
    "list_radar_v2_scope_stock_ids",
]
