from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timezone
from math import sqrt
from statistics import mean, median, stdev
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.db.models import (
    RadarBacktestRun,
    RadarFeatureSnapshot,
    RadarOutcomeEventLink,
    RadarOutcomePath,
    RadarRuleEvaluation,
    RadarUniverseObservation,
    StockMaster,
    utc_now,
)
from app.market.tw_daily_freshness import read_taiwan_daily_freshness_batch
from app.market.trading_calendar import TAIWAN_TZ
from app.watchlists.radar_rule_contract import config_hash
from app.watchlists.radar_v2_service import json_dumps, json_loads


@dataclass(frozen=True)
class RadarBacktestRequest:
    rule_version: str
    rule_config_hash: str
    feature_version: str
    feature_config_hash: str
    outcome_contract_version: str
    outcome_config_hash: str
    period_start: date
    period_end: date
    horizon_trading_days: int
    stock_ids: tuple[str, ...] = ()
    scope_key: str | None = None
    minimum_data_quality: float = 0.8
    minimum_coverage_ratio: float = 0.8
    minimum_samples: int = 30
    require_corporate_action_clear: bool = True
    require_point_in_time_universe: bool = True
    require_baseline: bool = True
    train_trading_days: int = 252
    validation_trading_days: int = 63
    test_trading_days: int = 63
    embargo_trading_days: int = 5

    def __post_init__(self) -> None:
        if self.period_end < self.period_start:
            raise ValueError("Radar backtest period_end must not precede period_start.")
        if self.horizon_trading_days <= 0:
            raise ValueError("Radar backtest horizon must be greater than zero.")
        if not 0 <= self.minimum_data_quality <= 1:
            raise ValueError("Radar minimum_data_quality must be between 0 and 1.")
        if not 0 <= self.minimum_coverage_ratio <= 1:
            raise ValueError("Radar minimum_coverage_ratio must be between 0 and 1.")
        if self.minimum_samples <= 0:
            raise ValueError("Radar minimum_samples must be greater than zero.")
        for value in (
            self.train_trading_days,
            self.validation_trading_days,
            self.test_trading_days,
        ):
            if value <= 0:
                raise ValueError("Radar walk-forward windows must be greater than zero.")
        if self.embargo_trading_days < 0:
            raise ValueError("Radar embargo_trading_days must not be negative.")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["period_start"] = self.period_start.isoformat()
        payload["period_end"] = self.period_end.isoformat()
        payload["stock_ids"] = sorted(
            {
                str(stock_id).strip()
                for stock_id in self.stock_ids
                if str(stock_id).strip()
            }
        )
        return payload


@dataclass(frozen=True)
class WalkForwardSplit:
    index: int
    train_start: date
    train_end: date
    validation_start: date
    validation_end: date
    test_start: date
    test_end: date
    purge_trading_days: int
    embargo_trading_days: int


def build_purged_walk_forward_splits(
    trade_dates: Iterable[date],
    *,
    train_trading_days: int,
    validation_trading_days: int,
    test_trading_days: int,
    purge_trading_days: int,
    embargo_trading_days: int,
    step_trading_days: int | None = None,
) -> list[WalkForwardSplit]:
    ordered = sorted(set(trade_dates))
    if purge_trading_days < 0 or embargo_trading_days < 0:
        raise ValueError("Radar purge and embargo must not be negative.")
    for value in (
        train_trading_days,
        validation_trading_days,
        test_trading_days,
    ):
        if value <= 0:
            raise ValueError("Radar walk-forward windows must be greater than zero.")
    step = step_trading_days or test_trading_days
    if step <= 0:
        raise ValueError("Radar walk-forward step must be greater than zero.")

    splits: list[WalkForwardSplit] = []
    start = 0
    split_index = 1
    while True:
        train_start_index = start
        train_end_index = train_start_index + train_trading_days - 1
        validation_start_index = train_end_index + 1 + purge_trading_days
        validation_end_index = (
            validation_start_index + validation_trading_days - 1
        )
        test_start_index = (
            validation_end_index
            + 1
            + purge_trading_days
            + embargo_trading_days
        )
        test_end_index = test_start_index + test_trading_days - 1
        if test_end_index >= len(ordered):
            break
        splits.append(
            WalkForwardSplit(
                index=split_index,
                train_start=ordered[train_start_index],
                train_end=ordered[train_end_index],
                validation_start=ordered[validation_start_index],
                validation_end=ordered[validation_end_index],
                test_start=ordered[test_start_index],
                test_end=ordered[test_end_index],
                purge_trading_days=purge_trading_days,
                embargo_trading_days=embargo_trading_days,
            )
        )
        start += step
        split_index += 1
    return splits


def point_in_time_daily_coverage(
    *,
    db: Session,
    as_of_date: date,
    required_history_days: int = 250,
    stock_ids: Iterable[str] = (),
) -> dict[str, Any]:
    if required_history_days <= 0:
        raise ValueError("required_history_days must be greater than zero.")
    normalized_stock_ids = sorted(
        {
            str(stock_id).strip()
            for stock_id in stock_ids
            if str(stock_id).strip()
        }
    )
    if not normalized_stock_ids:
        universe_rows = (
            db.query(StockMaster.stock_id)
            .filter(StockMaster.is_active.is_(True))
            .filter(StockMaster.market.in_(("TWSE", "TPEX")))
            .order_by(StockMaster.stock_id.asc())
            .limit(5001)
            .all()
        )
        if len(universe_rows) > 5000:
            raise ValueError("Radar backtest universe exceeds the 5000-symbol bound.")
        normalized_stock_ids = [
            str(row.stock_id)
            for row in universe_rows
        ]
    evidence = read_taiwan_daily_freshness_batch(
        db,
        stock_ids=normalized_stock_ids,
        checked_at=datetime.combine(
            as_of_date,
            time(23, 59, 59),
            tzinfo=TAIWAN_TZ,
        ),
        expected_date=as_of_date,
    )
    coverage = [
        {
            "stock_id": stock_id,
            "history_days": item.row_count,
            "latest_trade_date": item.latest_date,
            "has_as_of_bar": item.latest_date == as_of_date,
            "eligible": (
                item.row_count >= required_history_days
                and item.latest_date == as_of_date
            ),
        }
        for stock_id in normalized_stock_ids
        for item in [evidence[stock_id]]
        if item.latest_date is not None
    ]
    covered_ids = {row["stock_id"] for row in coverage}
    missing_ids = [
        stock_id for stock_id in normalized_stock_ids if stock_id not in covered_ids
    ]
    eligible = [row for row in coverage if row["eligible"]]
    requested_count = len(normalized_stock_ids)
    coverage_ratio = len(eligible) / requested_count if requested_count else 0.0
    return {
        "scope": "bounded_local_price_universe",
        "as_of_date": as_of_date,
        "required_history_days": required_history_days,
        "requested_count": requested_count,
        "observed_count": len(coverage),
        "eligible_count": len(eligible),
        "coverage_ratio": coverage_ratio,
        "eligible_stock_ids": [row["stock_id"] for row in eligible],
        "missing_stock_ids": missing_ids,
        "stocks": coverage,
        "limitations": [
            "point_in_time_receipt_availability_applied",
            "point_in_time_listing_membership_unavailable",
            "delisted_and_survivorship_coverage_not_proven",
        ],
    }


def _wilson_interval(successes: int, total: int) -> tuple[float, float] | None:
    if total <= 0:
        return None
    z = 1.96
    probability = successes / total
    denominator = 1 + (z * z / total)
    center = (
        probability + (z * z / (2 * total))
    ) / denominator
    margin = (
        z
        * sqrt(
            (probability * (1 - probability) / total)
            + (z * z / (4 * total * total))
        )
        / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def _mean_interval(values: list[float]) -> tuple[float, float] | None:
    if not values:
        return None
    average = mean(values)
    if len(values) == 1:
        return average, average
    margin = 1.96 * stdev(values) / sqrt(len(values))
    return average - margin, average + margin


def _metric_summary(values: list[float]) -> dict[str, Any]:
    interval = _mean_interval(values)
    return {
        "count": len(values),
        "average": mean(values) if values else None,
        "median": median(values) if values else None,
        "mean_confidence_interval_95": list(interval) if interval else None,
    }


def _evaluation_metrics(
    rows: list[
        tuple[RadarRuleEvaluation, RadarFeatureSnapshot, RadarOutcomePath]
    ],
) -> dict[str, Any]:
    summary_states = Counter(
        outcome.summary_state for _evaluation, _feature, outcome in rows
    )
    directional_rows = [
        (evaluation, outcome)
        for evaluation, _feature, outcome in rows
        if evaluation.direction != 0 and outcome.close_r is not None
    ]
    positive_direction_count = sum(
        1 for _evaluation, outcome in directional_rows if float(outcome.close_r) > 0
    )
    direction_interval = _wilson_interval(
        positive_direction_count,
        len(directional_rows),
    )
    close_r_values = [float(outcome.close_r) for _, outcome in directional_rows]
    mfe_r_values = [
        float(outcome.mfe_r)
        for _, outcome in directional_rows
        if outcome.mfe_r is not None
    ]
    mae_r_values = [
        float(outcome.mae_r)
        for _, outcome in directional_rows
        if outcome.mae_r is not None
    ]
    directed_return_values = [
        float(outcome.signal_close_return_pct) * evaluation.direction
        for evaluation, _feature, outcome in rows
        if evaluation.direction != 0
        and outcome.signal_close_return_pct is not None
    ]
    return {
        "sample_count": len(rows),
        "directional_sample_count": len(directional_rows),
        "summary_state_counts": dict(sorted(summary_states.items())),
        "direction_accuracy": (
            positive_direction_count / len(directional_rows)
            if directional_rows
            else None
        ),
        "direction_accuracy_confidence_interval_95": (
            list(direction_interval) if direction_interval else None
        ),
        "close_r": _metric_summary(close_r_values),
        "mfe_r": _metric_summary(mfe_r_values),
        "mae_r": _metric_summary(mae_r_values),
        "directed_signal_close_return_pct": _metric_summary(
            directed_return_values
        ),
        "expectancy_r": mean(close_r_values) if close_r_values else None,
    }


def _as_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _taiwan_date(value: datetime) -> date:
    normalized = (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )
    return normalized.astimezone(TAIWAN_TZ).date()


def _point_in_time_universe(
    *,
    db: Session,
    request: RadarBacktestRequest,
) -> dict[str, Any]:
    query = (
        db.query(RadarUniverseObservation)
        .filter(RadarUniverseObservation.rule_version == request.rule_version)
        .filter(
            RadarUniverseObservation.rule_config_hash
            == request.rule_config_hash
        )
        .filter(RadarUniverseObservation.snapshot_date >= request.period_start)
        .filter(RadarUniverseObservation.snapshot_date <= request.period_end)
        .filter(
            RadarUniverseObservation.universe_scope
            == "complete_calculation_universe"
        )
    )
    if request.stock_ids:
        query = query.filter(
            RadarUniverseObservation.stock_id.in_(request.stock_ids)
        )
    rows = query.all()
    status_priority = {
        "absent": 0,
        "error": 1,
        "no_data": 2,
        "evaluated": 3,
    }
    collapsed: dict[tuple[date, str], str] = {}
    for row in rows:
        key = (row.snapshot_date, row.stock_id)
        status = str(row.observation_status or "error")
        previous = collapsed.get(key)
        if previous is None or status_priority.get(
            status,
            -1,
        ) > status_priority.get(previous, -1):
            collapsed[key] = status
    status_counts = Counter(collapsed.values())
    requested_count = len(collapsed)
    evaluated_count = status_counts.get("evaluated", 0)
    return {
        "available": bool(collapsed),
        "scope": "complete_calculation_universe",
        "requested_count": requested_count,
        "evaluated_count": evaluated_count,
        "coverage_ratio": (
            evaluated_count / requested_count if requested_count else 0.0
        ),
        "status_counts": dict(sorted(status_counts.items())),
        "trade_dates": sorted({key[0] for key in collapsed}),
        "units": collapsed,
    }


def _serialize_run(row: RadarBacktestRun) -> dict[str, Any]:
    return {
        "id": row.id,
        "run_key": row.run_key,
        "status": row.status,
        "rule_version": row.rule_version,
        "rule_config_hash": row.rule_config_hash,
        "feature_version": row.feature_version,
        "feature_config_hash": row.feature_config_hash,
        "outcome_contract_version": row.outcome_contract_version,
        "outcome_config_hash": row.outcome_config_hash,
        "period_start": row.period_start,
        "period_end": row.period_end,
        "purge_trading_days": row.purge_trading_days,
        "embargo_trading_days": row.embargo_trading_days,
        "requested_sample_count": row.requested_sample_count,
        "eligible_sample_count": row.eligible_sample_count,
        "excluded_sample_count": row.excluded_sample_count,
        "coverage_ratio": row.coverage_ratio,
        "horizons": json_loads(row.horizons_json, []),
        "universe": json_loads(row.universe_json, {}),
        "coverage": json_loads(row.coverage_json, {}),
        "splits": json_loads(row.split_json, {}),
        "baseline": json_loads(row.baseline_json, {}),
        "metrics": json_loads(row.metrics_json, {}),
        "limitations": json_loads(row.limitations_json, []),
        "error_message": row.error_message,
        "started_at": row.started_at,
        "completed_at": row.completed_at,
    }


def get_latest_radar_backtest_v2(
    *,
    db: Session,
    rule_version: str,
    rule_config_hash: str,
    scope_key: str | None = None,
) -> dict[str, Any] | None:
    rows = (
        db.query(RadarBacktestRun)
        .filter(RadarBacktestRun.rule_version == rule_version)
        .filter(RadarBacktestRun.rule_config_hash == rule_config_hash)
        .order_by(
            RadarBacktestRun.completed_at.desc(),
            RadarBacktestRun.id.desc(),
        )
        .limit(100)
        .all()
    )
    for row in rows:
        payload = _serialize_run(row)
        if (
            scope_key is None
            or payload["universe"].get("scope_key") == scope_key
        ):
            return payload
    return None


def run_radar_backtest_v2(
    *,
    db: Session,
    request: RadarBacktestRequest,
    commit: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    request_payload = request.to_dict()
    run_key = config_hash(request_payload)
    existing = (
        db.query(RadarBacktestRun)
        .filter(RadarBacktestRun.run_key == run_key)
        .one_or_none()
    )
    if existing is not None and existing.status in {"completed", "blocked"}:
        return _serialize_run(existing)

    try:
        query = (
            db.query(
                RadarRuleEvaluation,
                RadarFeatureSnapshot,
                RadarOutcomePath,
            )
            .join(
                RadarFeatureSnapshot,
                RadarFeatureSnapshot.id
                == RadarRuleEvaluation.feature_snapshot_id,
            )
            .join(
                RadarOutcomePath,
                RadarOutcomePath.evaluation_id == RadarRuleEvaluation.id,
            )
            .filter(RadarRuleEvaluation.rule_version == request.rule_version)
            .filter(
                RadarRuleEvaluation.rule_config_hash
                == request.rule_config_hash
            )
            .filter(
                RadarFeatureSnapshot.feature_version
                == request.feature_version
            )
            .filter(
                RadarFeatureSnapshot.feature_config_hash
                == request.feature_config_hash
            )
            .filter(
                RadarOutcomePath.outcome_contract_version
                == request.outcome_contract_version
            )
            .filter(
                RadarOutcomePath.outcome_config_hash
                == request.outcome_config_hash
            )
            .filter(
                RadarOutcomePath.horizon_trading_days
                == request.horizon_trading_days
            )
            .filter(
                RadarFeatureSnapshot.signal_trade_date
                >= request.period_start
            )
            .filter(
                RadarFeatureSnapshot.signal_trade_date
                <= request.period_end
            )
        )
        if request.stock_ids:
            query = query.filter(
                RadarFeatureSnapshot.stock_id.in_(request.stock_ids)
            )
        rows = query.order_by(
            RadarFeatureSnapshot.signal_trade_date.asc(),
            RadarFeatureSnapshot.stock_id.asc(),
            RadarRuleEvaluation.id.asc(),
        ).all()

        universe = _point_in_time_universe(db=db, request=request)
        outcome_ids = [int(outcome.id) for _, _, outcome in rows]
        event_ids_by_outcome: dict[int, set[int]] = {}
        if outcome_ids:
            for outcome_id, event_id in (
                db.query(
                    RadarOutcomeEventLink.outcome_path_id,
                    RadarOutcomeEventLink.signal_event_id,
                )
                .filter(RadarOutcomeEventLink.outcome_path_id.in_(outcome_ids))
                .all()
            ):
                event_ids_by_outcome.setdefault(int(outcome_id), set()).add(
                    int(event_id)
                )

        excluded_reasons: Counter[str] = Counter()
        eligible_rows: list[
            tuple[RadarRuleEvaluation, RadarFeatureSnapshot, RadarOutcomePath]
        ] = []
        seen_event_ids: set[int] = set()
        samples_without_event_identity = 0
        for evaluation, feature, outcome in rows:
            reason: str | None = None
            source_available_at = (
                feature.source_available_at or feature.available_at
            )
            decision_at = evaluation.decision_at or evaluation.evaluated_at
            if _as_naive_utc(source_available_at) > _as_naive_utc(decision_at):
                reason = "feature_source_available_after_decision"
            elif _as_naive_utc(feature.effective_at) > _as_naive_utc(decision_at):
                reason = "feature_effective_after_decision"
            elif _taiwan_date(decision_at) != feature.signal_trade_date:
                reason = "decision_outside_signal_trade_date"
            elif feature.data_quality_score < request.minimum_data_quality:
                reason = "feature_data_quality_below_minimum"
            elif outcome.status != "evaluated":
                reason = f"outcome_status:{outcome.status}"
            elif (
                request.require_corporate_action_clear
                and outcome.corporate_action_status != "checked_clear"
            ):
                reason = (
                    "corporate_action_status:"
                    + outcome.corporate_action_status
                )
            linked_event_ids = set(event_ids_by_outcome.get(int(outcome.id), set()))
            if outcome.signal_event_id is not None:
                linked_event_ids.add(int(outcome.signal_event_id))
            if reason is None and linked_event_ids.intersection(seen_event_ids):
                reason = "duplicate_signal_event"
            if reason is not None:
                excluded_reasons[reason] += 1
                continue
            if linked_event_ids:
                seen_event_ids.update(linked_event_ids)
            else:
                samples_without_event_identity += 1
            eligible_rows.append((evaluation, feature, outcome))

        requested_count = int(universe["requested_count"])
        eligible_count = len(eligible_rows)
        coverage_ratio = float(universe["coverage_ratio"])
        full_sample_metrics = _evaluation_metrics(eligible_rows)
        trade_dates = list(universe["trade_dates"])
        splits = build_purged_walk_forward_splits(
            trade_dates,
            train_trading_days=request.train_trading_days,
            validation_trading_days=request.validation_trading_days,
            test_trading_days=request.test_trading_days,
            purge_trading_days=request.horizon_trading_days,
            embargo_trading_days=request.embargo_trading_days,
        )
        split_results: list[dict[str, Any]] = []
        oos_rows_by_evaluation: dict[
            int,
            tuple[RadarRuleEvaluation, RadarFeatureSnapshot, RadarOutcomePath],
        ] = {}
        oos_universe_keys: set[tuple[date, str]] = set()
        for split in splits:
            train_rows = [
                row
                for row in eligible_rows
                if split.train_start <= row[1].signal_trade_date <= split.train_end
            ]
            validation_rows = [
                row
                for row in eligible_rows
                if (
                    split.validation_start
                    <= row[1].signal_trade_date
                    <= split.validation_end
                )
            ]
            test_rows = [
                row
                for row in eligible_rows
                if split.test_start <= row[1].signal_trade_date <= split.test_end
            ]
            for row in test_rows:
                oos_rows_by_evaluation[int(row[0].id)] = row
            split_universe_keys = {
                key
                for key in universe["units"]
                if split.test_start <= key[0] <= split.test_end
            }
            oos_universe_keys.update(split_universe_keys)
            split_evaluated_count = sum(
                1
                for key in split_universe_keys
                if universe["units"][key] == "evaluated"
            )
            split_results.append(
                {
                    **asdict(split),
                    "train_metrics": _evaluation_metrics(train_rows),
                    "validation_metrics": _evaluation_metrics(validation_rows),
                    "test_metrics": _evaluation_metrics(test_rows),
                    "test_universe_requested_count": len(split_universe_keys),
                    "test_universe_evaluated_count": split_evaluated_count,
                    "test_universe_coverage_ratio": (
                        split_evaluated_count / len(split_universe_keys)
                        if split_universe_keys
                        else 0.0
                    ),
                }
            )
        oos_rows = list(oos_rows_by_evaluation.values())
        oos_metrics = _evaluation_metrics(oos_rows)
        oos_universe_evaluated_count = sum(
            1
            for key in oos_universe_keys
            if universe["units"][key] == "evaluated"
        )
        oos_coverage_ratio = (
            oos_universe_evaluated_count / len(oos_universe_keys)
            if oos_universe_keys
            else 0.0
        )
        metrics = {
            "promotion_basis": "walk_forward_test_only",
            "oos": oos_metrics,
            "diagnostic_full_sample": full_sample_metrics,
        }

        baseline = {
            "status": "unavailable",
            "reason": "point_in_time_market_or_sector_baseline_not_configured",
        }
        limitations = [
            "bounded_local_universe_only",
            "point_in_time_listing_membership_unavailable",
            "market_sector_matched_baseline_unavailable",
        ]
        if not universe["available"]:
            limitations.append("point_in_time_universe_observations_unavailable")
        if not splits:
            limitations.append("insufficient_dates_for_walk_forward")
        if samples_without_event_identity:
            limitations.append("some_samples_lack_signal_event_identity")

        gate_checks = {
            "point_in_time_universe_available": (
                bool(universe["available"])
                or not request.require_point_in_time_universe
            ),
            "walk_forward_splits_available": bool(splits),
            "minimum_oos_samples": (
                int(oos_metrics["sample_count"]) >= request.minimum_samples
            ),
            "minimum_oos_universe_coverage": (
                oos_coverage_ratio >= request.minimum_coverage_ratio
            ),
            "baseline_available": (
                baseline["status"] == "ready" or not request.require_baseline
            ),
        }
        passed_gate = all(gate_checks.values())
        failed_gates = [key for key, passed in gate_checks.items() if not passed]
        completed_at = now or utc_now()
        values = {
            "run_key": run_key,
            "status": "completed" if passed_gate else "blocked",
            "rule_version": request.rule_version,
            "rule_config_hash": request.rule_config_hash,
            "feature_version": request.feature_version,
            "feature_config_hash": request.feature_config_hash,
            "outcome_contract_version": request.outcome_contract_version,
            "outcome_config_hash": request.outcome_config_hash,
            "period_start": request.period_start,
            "period_end": request.period_end,
            "purge_trading_days": request.horizon_trading_days,
            "embargo_trading_days": request.embargo_trading_days,
            "requested_sample_count": requested_count,
            "eligible_sample_count": eligible_count,
            "excluded_sample_count": max(0, requested_count - eligible_count),
            "coverage_ratio": coverage_ratio,
            "horizons_json": json_dumps(
                [request.horizon_trading_days]
            ),
            "universe_json": json_dumps(
                {
                    "scope": "complete_calculation_universe",
                    "scope_key": request.scope_key,
                    "stock_ids": request_payload["stock_ids"],
                    "point_in_time_available": universe["available"],
                    "observation_status_counts": universe["status_counts"],
                }
            ),
            "coverage_json": json_dumps(
                {
                    "minimum_data_quality": request.minimum_data_quality,
                    "minimum_coverage_ratio": request.minimum_coverage_ratio,
                    "minimum_samples": request.minimum_samples,
                    "passed_gate": passed_gate,
                    "gate_checks": gate_checks,
                    "failed_gates": failed_gates,
                    "full_period_universe_coverage_ratio": coverage_ratio,
                    "oos_universe_requested_count": len(oos_universe_keys),
                    "oos_universe_evaluated_count": (
                        oos_universe_evaluated_count
                    ),
                    "oos_universe_coverage_ratio": oos_coverage_ratio,
                    "excluded_reason_counts": dict(
                        sorted(excluded_reasons.items())
                    ),
                }
            ),
            "split_json": json_dumps(
                {
                    "strategy": "purged_walk_forward",
                    "promotion_metric_scope": "test_only",
                    "splits": split_results,
                }
            ),
            "baseline_json": json_dumps(baseline),
            "metrics_json": json_dumps(metrics),
            "limitations_json": json_dumps(
                list(dict.fromkeys(limitations))
            ),
            "error_message": (
                None
                if passed_gate
                else (
                    "Backtest promotion gates failed: "
                    + ", ".join(failed_gates)
                )
            ),
            "started_at": now or utc_now(),
            "completed_at": completed_at,
        }
        if existing is None:
            existing = RadarBacktestRun(**values)
            db.add(existing)
        else:
            for key, value in values.items():
                setattr(existing, key, value)
        db.flush()
        result = _serialize_run(existing)
        if commit:
            db.commit()
        return result
    except Exception:
        if commit:
            db.rollback()
        raise


__all__ = [
    "RadarBacktestRequest",
    "WalkForwardSplit",
    "build_purged_walk_forward_splits",
    "get_latest_radar_backtest_v2",
    "point_in_time_daily_coverage",
    "run_radar_backtest_v2",
]
