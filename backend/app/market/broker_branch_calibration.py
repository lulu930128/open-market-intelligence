from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json
from math import ceil
from typing import Any, Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    BrokerBranchBehaviorFeatureSnapshot,
    BrokerBranchSnapshotQuality,
    SourceRegistry,
)
from app.market.broker_branch_behavior import (
    BROKER_BRANCH_BEHAVIOR_DEFAULT_LOOKBACK_SESSIONS,
    BROKER_BRANCH_BEHAVIOR_MAX_LOOKBACK_SESSIONS,
    BROKER_BRANCH_BEHAVIOR_METHODOLOGY_V0,
    BROKER_BRANCH_BEHAVIOR_MIN_HIGH_COVERAGE_RATIO,
    BROKER_BRANCH_BEHAVIOR_SCOPE_ID_TW,
    BROKER_BRANCH_BEHAVIOR_SCOPE_TYPE_GLOBAL,
    history_status_for_sessions,
)
from app.market.broker_branch_quality import BROKER_BRANCH_COVERAGE_CENSORED
from app.market.trading_calendar import previous_taiwan_trading_day


BROKER_BRANCH_CALIBRATION_REPORT_VERSION = (
    "broker_branch.behavior.readiness_report.v0"
)
BROKER_BRANCH_CALIBRATION_POLICY_VERSION = (
    "broker_branch.behavior.calibration_policy.v0"
)


@dataclass(frozen=True)
class BrokerBranchCalibrationPolicy:
    """Frozen eligibility policy; it is not a classification or score model."""

    version: str = BROKER_BRANCH_CALIBRATION_POLICY_VERSION
    minimum_exploratory_sessions: int = 20
    minimum_calibration_sessions: int = 60
    minimum_production_candidate_sessions: int = 120
    minimum_profile_sessions: int = 20
    minimum_profile_stocks: int = 30
    minimum_profile_reobserved_count: int = 100
    maximum_profile_stock_observation_share: float = 0.20
    train_sessions: int = 60
    validation_sessions: int = 20
    test_sessions: int = 20
    purge_sessions: int = 1
    embargo_sessions: int = 1
    step_sessions: int = 20
    minimum_walk_forward_splits: int = 2

    def __post_init__(self) -> None:
        positive_values = (
            self.minimum_exploratory_sessions,
            self.minimum_calibration_sessions,
            self.minimum_production_candidate_sessions,
            self.minimum_profile_sessions,
            self.minimum_profile_stocks,
            self.minimum_profile_reobserved_count,
            self.train_sessions,
            self.validation_sessions,
            self.test_sessions,
            self.step_sessions,
            self.minimum_walk_forward_splits,
        )
        if any(value <= 0 for value in positive_values):
            raise ValueError("Broker-branch calibration thresholds must be positive.")
        if self.purge_sessions < 0 or self.embargo_sessions < 0:
            raise ValueError("Broker-branch purge and embargo must be non-negative.")
        if not 0 < self.maximum_profile_stock_observation_share <= 1:
            raise ValueError(
                "maximum_profile_stock_observation_share must be in (0, 1]."
            )
        if not (
            self.minimum_exploratory_sessions
            <= self.minimum_calibration_sessions
            <= self.minimum_production_candidate_sessions
        ):
            raise ValueError("Broker-branch history thresholds must be ordered.")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_BROKER_BRANCH_CALIBRATION_POLICY = BrokerBranchCalibrationPolicy()


@dataclass(frozen=True)
class BrokerBranchWalkForwardSplit:
    index: int
    train_start: date
    train_end: date
    validation_start: date
    validation_end: date
    test_start: date
    test_end: date
    purge_sessions: int
    embargo_sessions: int

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "train_start",
            "train_end",
            "validation_start",
            "validation_end",
            "test_start",
            "test_end",
        ):
            payload[key] = payload[key].isoformat()
        return payload


def build_broker_branch_walk_forward_splits(
    high_coverage_dates: Iterable[date],
    *,
    policy: BrokerBranchCalibrationPolicy = (
        DEFAULT_BROKER_BRANCH_CALIBRATION_POLICY
    ),
) -> list[BrokerBranchWalkForwardSplit]:
    """Build deterministic, non-overlapping label-gap windows.

    The input must contain only sessions that already passed the coverage gate.
    This function plans evaluation windows; it does not claim validation ran.
    """

    ordered = sorted(set(high_coverage_dates))
    splits: list[BrokerBranchWalkForwardSplit] = []
    start = 0
    split_index = 1
    while True:
        train_start_index = start
        train_end_index = train_start_index + policy.train_sessions - 1
        validation_start_index = train_end_index + 1 + policy.purge_sessions
        validation_end_index = (
            validation_start_index + policy.validation_sessions - 1
        )
        test_start_index = (
            validation_end_index
            + 1
            + policy.purge_sessions
            + policy.embargo_sessions
        )
        test_end_index = test_start_index + policy.test_sessions - 1
        if test_end_index >= len(ordered):
            break
        splits.append(
            BrokerBranchWalkForwardSplit(
                index=split_index,
                train_start=ordered[train_start_index],
                train_end=ordered[train_end_index],
                validation_start=ordered[validation_start_index],
                validation_end=ordered[validation_end_index],
                test_start=ordered[test_start_index],
                test_end=ordered[test_end_index],
                purge_sessions=policy.purge_sessions,
                embargo_sessions=policy.embargo_sessions,
            )
        )
        start += policy.step_sessions
        split_index += 1
    return splits


def _candidate_sessions(*, as_of_trade_date: date, lookback_sessions: int) -> list[date]:
    latest = previous_taiwan_trading_day(as_of_trade_date, include_value=True)
    sessions: list[date] = []
    current = latest
    for _ in range(lookback_sessions):
        sessions.append(current)
        current = previous_taiwan_trading_day(current, include_value=False)
    return sorted(sessions)


def _safe_rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator > 0 else None


def _json_list(value: str | None) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return ["invalid_warnings_json"]
    if not isinstance(parsed, list):
        return ["invalid_warnings_json"]
    return list(
        dict.fromkeys(
            item
            for item in (str(entry).strip() for entry in parsed)
            if item
        )
    )


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _profile_gate_reasons(
    row: BrokerBranchBehaviorFeatureSnapshot,
    *,
    policy: BrokerBranchCalibrationPolicy,
) -> list[str]:
    reasons: list[str] = []
    if int(row.session_count or 0) < policy.minimum_profile_sessions:
        reasons.append("profile_sessions_below_minimum")
    if int(row.stock_count or 0) < policy.minimum_profile_stocks:
        reasons.append("profile_stocks_below_minimum")
    if int(row.reobserved_count or 0) < policy.minimum_profile_reobserved_count:
        reasons.append("profile_reobserved_denominator_below_minimum")
    concentration = row.max_stock_observation_share
    if concentration is None:
        reasons.append("profile_concentration_missing")
    elif concentration > policy.maximum_profile_stock_observation_share:
        reasons.append("profile_concentration_above_maximum")
    return reasons


def _report_fingerprint(payload: dict[str, Any]) -> str:
    stable_payload = json.loads(
        json.dumps(payload, ensure_ascii=False, sort_keys=True)
    )
    for source in stable_payload.get("evidence", {}).get("sources", []):
        # Operational compute time remains visible in the report, but it must
        # not change the evidence identity when the same materialized inputs
        # are evaluated again.
        source.pop("computed_at_min", None)
        source.pop("computed_at_max", None)
    encoded = json.dumps(
        stable_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _empty_report(
    *,
    requested_as_of: date | None,
    lookback_sessions: int,
    methodology_version: str,
    policy: BrokerBranchCalibrationPolicy,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "contract_version": BROKER_BRANCH_CALIBRATION_REPORT_VERSION,
        "mode": "read_only",
        "status": "snapshot_missing",
        "selection": {
            "requested_as_of": _iso(requested_as_of),
            "resolved_as_of": None,
            "lookback_sessions": lookback_sessions,
            "methodology_version": methodology_version,
        },
        "calibration_policy": policy.to_dict(),
        "evidence": {
            "source_count": 0,
            "profile_count": 0,
            "high_coverage_session_count": 0,
            "history_status": "insufficient_history",
            "sources": [],
        },
        "walk_forward": {
            "status": "not_eligible_history",
            "split_count": 0,
            "minimum_required_splits": policy.minimum_walk_forward_splits,
            "validation_results_present": False,
            "splits": [],
        },
        "promotion": {
            "decision": "shadow_only",
            "production_ready": False,
            "advertise_behavior": False,
            "enable_flow_risk": False,
            "enable_radar_integration": False,
            "blocked_by": [
                "materialized_feature_snapshot_missing",
                "walk_forward_validation_not_run",
                "source_rights_not_verified",
            ],
        },
        "boundaries": {
            "provider_fetches": 0,
            "database_writes": 0,
            "branch_identity_disclosed": False,
            "classification_computed": False,
            "flow_risk_computed": False,
            "radar_changed": False,
            "source_rights_verified": False,
            "effective_dated_universe_available": False,
        },
    }
    report["evidence_fingerprint"] = _report_fingerprint(report)
    return report


def build_broker_branch_readiness_report(
    db: Session,
    *,
    as_of_trade_date: date | None = None,
    lookback_sessions: int = BROKER_BRANCH_BEHAVIOR_DEFAULT_LOOKBACK_SESSIONS,
    methodology_version: str = BROKER_BRANCH_BEHAVIOR_METHODOLOGY_V0,
    policy: BrokerBranchCalibrationPolicy = (
        DEFAULT_BROKER_BRANCH_CALIBRATION_POLICY
    ),
) -> dict[str, Any]:
    """Build a bounded, aggregate-only readiness report without mutating state."""

    bounded_lookback = int(lookback_sessions)
    if not 2 <= bounded_lookback <= BROKER_BRANCH_BEHAVIOR_MAX_LOOKBACK_SESSIONS:
        raise ValueError(
            "lookback_sessions must be between 2 and "
            f"{BROKER_BRANCH_BEHAVIOR_MAX_LOOKBACK_SESSIONS}"
        )
    normalized_methodology = str(methodology_version).strip()
    if not normalized_methodology or len(normalized_methodology) > 80:
        raise ValueError("methodology_version must contain 1-80 characters")

    base_query = (
        db.query(BrokerBranchBehaviorFeatureSnapshot)
        .autoflush(False)
        .filter(
            BrokerBranchBehaviorFeatureSnapshot.scope_type
            == BROKER_BRANCH_BEHAVIOR_SCOPE_TYPE_GLOBAL
        )
        .filter(
            BrokerBranchBehaviorFeatureSnapshot.scope_id
            == BROKER_BRANCH_BEHAVIOR_SCOPE_ID_TW
        )
        .filter(
            BrokerBranchBehaviorFeatureSnapshot.lookback_sessions
            == bounded_lookback
        )
        .filter(
            BrokerBranchBehaviorFeatureSnapshot.methodology_version
            == normalized_methodology
        )
    )
    resolved_as_of = as_of_trade_date
    if resolved_as_of is None:
        resolved_as_of = base_query.with_entities(
            func.max(BrokerBranchBehaviorFeatureSnapshot.as_of_trade_date)
        ).scalar()
    if resolved_as_of is None:
        return _empty_report(
            requested_as_of=as_of_trade_date,
            lookback_sessions=bounded_lookback,
            methodology_version=normalized_methodology,
            policy=policy,
        )

    rows = (
        base_query.filter(
            BrokerBranchBehaviorFeatureSnapshot.as_of_trade_date
            == resolved_as_of
        )
        .order_by(
            BrokerBranchBehaviorFeatureSnapshot.source_id.asc(),
            BrokerBranchBehaviorFeatureSnapshot.branch_identity_key.asc(),
        )
        .all()
    )
    if not rows:
        return _empty_report(
            requested_as_of=as_of_trade_date,
            lookback_sessions=bounded_lookback,
            methodology_version=normalized_methodology,
            policy=policy,
        )

    source_ids = sorted({int(row.source_id) for row in rows})
    source_names = {
        int(source_id): str(source_name)
        for source_id, source_name in (
            db.query(SourceRegistry.id, SourceRegistry.source_name)
            .autoflush(False)
            .filter(SourceRegistry.id.in_(source_ids))
            .all()
        )
    }
    candidate_sessions = _candidate_sessions(
        as_of_trade_date=resolved_as_of,
        lookback_sessions=bounded_lookback,
    )

    source_reports: list[dict[str, Any]] = []
    all_high_coverage_dates: set[date] | None = None
    profile_gate_counts: Counter[str] = Counter()
    eligible_profile_count = 0
    diagnostic_totals: Counter[str] = Counter()
    all_warnings: set[str] = set()
    evidence_identity: list[str] = []
    consistency_issues: list[str] = []

    for source_id in source_ids:
        source_rows = [row for row in rows if int(row.source_id) == source_id]
        universe_counts = {int(row.universe_count or 0) for row in source_rows}
        stored_high_counts = {
            int(row.high_coverage_session_count or 0) for row in source_rows
        }
        universe_count = next(iter(universe_counts)) if len(universe_counts) == 1 else 0
        stored_high_count = (
            next(iter(stored_high_counts)) if len(stored_high_counts) == 1 else -1
        )
        if len(universe_counts) != 1 or universe_count <= 0:
            consistency_issues.append(f"source_{source_id}_universe_count_inconsistent")
        if len(stored_high_counts) != 1:
            consistency_issues.append(
                f"source_{source_id}_stored_high_coverage_count_inconsistent"
            )

        daily_counts = {
            trade_date: int(stock_count)
            for trade_date, stock_count in (
                db.query(
                    BrokerBranchSnapshotQuality.expected_trade_date,
                    func.count(
                        func.distinct(BrokerBranchSnapshotQuality.stock_id)
                    ),
                )
                .autoflush(False)
                .filter(BrokerBranchSnapshotQuality.source_id == source_id)
                .filter(
                    BrokerBranchSnapshotQuality.expected_trade_date.in_(
                        candidate_sessions
                    )
                )
                .filter(
                    BrokerBranchSnapshotQuality.coverage_status
                    == BROKER_BRANCH_COVERAGE_CENSORED
                )
                .group_by(BrokerBranchSnapshotQuality.expected_trade_date)
                .all()
            )
        }
        required_stock_count = (
            ceil(universe_count * BROKER_BRANCH_BEHAVIOR_MIN_HIGH_COVERAGE_RATIO)
            if universe_count > 0
            else 1
        )
        high_coverage_dates = {
            trade_date
            for trade_date, stock_count in daily_counts.items()
            if stock_count >= required_stock_count
        }
        if stored_high_count != len(high_coverage_dates):
            consistency_issues.append(
                f"source_{source_id}_stored_vs_recomputed_high_coverage_mismatch"
            )
        all_high_coverage_dates = (
            set(high_coverage_dates)
            if all_high_coverage_dates is None
            else all_high_coverage_dates & high_coverage_dates
        )

        source_gate_counts: Counter[str] = Counter()
        source_eligible_profiles = 0
        for row in source_rows:
            reasons = _profile_gate_reasons(row, policy=policy)
            if reasons:
                source_gate_counts.update(reasons)
                profile_gate_counts.update(reasons)
            else:
                source_eligible_profiles += 1
                eligible_profile_count += 1
            diagnostic_totals.update(
                {
                    "observation_count": int(row.observation_count or 0),
                    "eligible_initial_count": int(row.eligible_initial_count or 0),
                    "reobserved_count": int(row.reobserved_count or 0),
                    "opposite_observed_count": int(
                        row.opposite_observed_count or 0
                    ),
                    "same_direction_observed_count": int(
                        row.same_direction_observed_count or 0
                    ),
                    "censored_count": int(row.censored_count or 0),
                }
            )
            all_warnings.update(_json_list(row.warnings_json))
            evidence_identity.append(
                "|".join(
                    (
                        str(row.source_id),
                        row.branch_identity_key,
                        row.as_of_trade_date.isoformat(),
                        row.methodology_version,
                        row.input_fingerprint,
                    )
                )
            )
            if row.source_as_of is not None and row.source_as_of > resolved_as_of:
                consistency_issues.append(f"source_{source_id}_source_lookahead")
            if row.price_source_as_of is not None and row.price_source_as_of > resolved_as_of:
                consistency_issues.append(f"source_{source_id}_price_lookahead")
            if row.derived_as_of > resolved_as_of:
                consistency_issues.append(f"source_{source_id}_derived_lookahead")

        source_reports.append(
            {
                "source_id": source_id,
                "source_name": source_names.get(source_id, "unknown"),
                "profile_count": len(source_rows),
                "profile_gate_eligible_count": source_eligible_profiles,
                "profile_gate_failure_counts": dict(sorted(source_gate_counts.items())),
                "candidate_session_count": len(candidate_sessions),
                "high_coverage_session_count": len(high_coverage_dates),
                "high_coverage_first_date": _iso(min(high_coverage_dates))
                if high_coverage_dates
                else None,
                "high_coverage_last_date": _iso(max(high_coverage_dates))
                if high_coverage_dates
                else None,
                "history_status": history_status_for_sessions(
                    len(high_coverage_dates)
                ),
                "universe_count": universe_count,
                "minimum_covered_stock_count": required_stock_count,
                "source_as_of": _iso(
                    max(
                        (
                            row.source_as_of
                            for row in source_rows
                            if row.source_as_of is not None
                        ),
                        default=None,
                    )
                ),
                "computed_at_min": _iso(
                    min((row.computed_at for row in source_rows), default=None)
                ),
                "computed_at_max": _iso(
                    max((row.computed_at for row in source_rows), default=None)
                ),
            }
        )

    common_high_coverage_dates = all_high_coverage_dates or set()
    high_coverage_session_count = len(common_high_coverage_dates)
    history_status = history_status_for_sessions(high_coverage_session_count)
    splits = build_broker_branch_walk_forward_splits(
        common_high_coverage_dates,
        policy=policy,
    )
    if high_coverage_session_count < policy.minimum_production_candidate_sessions:
        walk_forward_status = "not_eligible_history"
    elif len(splits) < policy.minimum_walk_forward_splits:
        walk_forward_status = "insufficient_planned_splits"
    else:
        walk_forward_status = "split_plan_ready_validation_not_run"

    blocked_by: list[str] = []
    if high_coverage_session_count < policy.minimum_calibration_sessions:
        blocked_by.append("high_coverage_history_below_calibration_minimum")
    if high_coverage_session_count < policy.minimum_production_candidate_sessions:
        blocked_by.append("high_coverage_history_below_production_minimum")
    if len(splits) < policy.minimum_walk_forward_splits:
        blocked_by.append("walk_forward_split_count_below_minimum")
    blocked_by.extend(
        (
            "walk_forward_validation_not_run",
            "v1_classification_not_implemented",
            "effective_dated_universe_not_available",
            "source_rights_not_verified",
        )
    )
    if consistency_issues:
        blocked_by.append("materialized_evidence_inconsistent")
    blocked_by = list(dict.fromkeys(blocked_by))

    if high_coverage_session_count < policy.minimum_calibration_sessions:
        promotion_decision = "shadow_only"
        status = "exploratory_only"
    elif high_coverage_session_count < policy.minimum_production_candidate_sessions:
        promotion_decision = "calibration_candidate_only"
        status = "calibration_candidate"
    else:
        promotion_decision = "walk_forward_required"
        status = "production_candidate_unvalidated"

    deterministic_evidence_fingerprint = hashlib.sha256(
        "\n".join(sorted(evidence_identity)).encode("utf-8")
    ).hexdigest()
    report = {
        "contract_version": BROKER_BRANCH_CALIBRATION_REPORT_VERSION,
        "mode": "read_only",
        "status": status,
        "selection": {
            "requested_as_of": _iso(as_of_trade_date),
            "resolved_as_of": resolved_as_of.isoformat(),
            "lookback_sessions": bounded_lookback,
            "methodology_version": normalized_methodology,
        },
        "calibration_policy": policy.to_dict(),
        "evidence": {
            "source_count": len(source_ids),
            "profile_count": len(rows),
            "profile_gate_eligible_count": eligible_profile_count,
            "profile_gate_failure_counts": dict(sorted(profile_gate_counts.items())),
            "high_coverage_session_count": high_coverage_session_count,
            "history_status": history_status,
            "materialized_evidence_fingerprint": (
                deterministic_evidence_fingerprint
            ),
            "diagnostic_totals": {
                **dict(diagnostic_totals),
                "reappearance_rate": _safe_rate(
                    diagnostic_totals["reobserved_count"],
                    diagnostic_totals["eligible_initial_count"],
                ),
                "reverse_given_reappearance_rate": _safe_rate(
                    diagnostic_totals["opposite_observed_count"],
                    diagnostic_totals["reobserved_count"],
                ),
                "same_direction_given_reappearance_rate": _safe_rate(
                    diagnostic_totals["same_direction_observed_count"],
                    diagnostic_totals["reobserved_count"],
                ),
                "censored_rate": _safe_rate(
                    diagnostic_totals["censored_count"],
                    diagnostic_totals["eligible_initial_count"],
                ),
                "independence_assumption": "not_met_correlated_observations",
            },
            "warnings": sorted(all_warnings),
            "consistency_issues": sorted(set(consistency_issues)),
            "sources": source_reports,
        },
        "walk_forward": {
            "status": walk_forward_status,
            "split_count": len(splits),
            "minimum_required_splits": policy.minimum_walk_forward_splits,
            "validation_results_present": False,
            "splits": [split.to_dict() for split in splits],
        },
        "promotion": {
            "decision": promotion_decision,
            "production_ready": False,
            "advertise_behavior": False,
            "enable_flow_risk": False,
            "enable_radar_integration": False,
            "blocked_by": blocked_by,
        },
        "boundaries": {
            "provider_fetches": 0,
            "database_writes": 0,
            "branch_identity_disclosed": False,
            "classification_computed": False,
            "flow_risk_computed": False,
            "radar_changed": False,
            "source_rights_verified": False,
            "effective_dated_universe_available": False,
            "top_n_absence_semantics": "unknown_not_ranked",
            "aggregate_rates_are_diagnostic_only": True,
        },
    }
    report["evidence_fingerprint"] = _report_fingerprint(report)
    return report


def render_broker_branch_readiness_markdown(report: dict[str, Any]) -> str:
    selection = report["selection"]
    evidence = report["evidence"]
    promotion = report["promotion"]
    walk_forward = report["walk_forward"]
    boundaries = report["boundaries"]
    blockers = promotion.get("blocked_by") or []
    source_rows = evidence.get("sources") or []
    lines = [
        "# 分點行為引擎 Readiness／邊界報告",
        "",
        "## 結論",
        "",
        f"- 狀態：`{report['status']}`。",
        f"- Promotion：`{promotion['decision']}`；production ready = "
        f"`{str(bool(promotion['production_ready'])).lower()}`。",
        f"- Evidence fingerprint：`{report['evidence_fingerprint']}`。",
        "",
        "## 資料範圍",
        "",
        f"- as-of：`{selection.get('resolved_as_of')}`。",
        f"- lookback：`{selection['lookback_sessions']}` 個台股交易日。",
        f"- methodology：`{selection['methodology_version']}`。",
        f"- high-coverage sessions："
        f"`{evidence['high_coverage_session_count']}`。",
        f"- materialized profiles：`{evidence['profile_count']}`；"
        f"profile gate eligible：`{evidence['profile_gate_eligible_count']}`。",
        "",
        "## Source evidence",
        "",
        "| Source | Profiles | High coverage | History | Source as-of |",
        "| --- | ---: | ---: | --- | --- |",
    ]
    for source in source_rows:
        lines.append(
            f"| `{source['source_name']}` | {source['profile_count']} | "
            f"{source['high_coverage_session_count']} | "
            f"`{source['history_status']}` | "
            f"`{source.get('source_as_of')}` |"
        )
    if not source_rows:
        lines.append("| 無 materialized snapshot | 0 | 0 | `insufficient_history` | - |")
    lines.extend(
        [
            "",
            "## Walk-forward",
            "",
            f"- 狀態：`{walk_forward['status']}`。",
            f"- 可規劃 split：`{walk_forward['split_count']}`；最低要求："
            f"`{walk_forward['minimum_required_splits']}`。",
            "- 本報告只建立 split 計畫，不把未執行的 OOS validation 宣稱為通過。",
            "",
            "## Promotion blockers",
            "",
        ]
    )
    lines.extend(f"- `{blocker}`" for blocker in blockers)
    lines.extend(
        [
            "",
            "## 執行邊界",
            "",
            f"- Provider fetch：`{boundaries['provider_fetches']}`。",
            f"- Database write：`{boundaries['database_writes']}`。",
            "- 未揭露 branch identity；未計算 classification 或 flow-risk；未修改 Radar。",
            "- Top15 未出現仍是 `unknown_not_ranked`；aggregate rates 只作診斷，"
            "不視為獨立樣本的機率估計。",
            "- 來源授權與 effective-dated historical universe 尚未完成，"
            "因此即使 session 數量增加也不會自動 promotion。",
            "",
        ]
    )
    return "\n".join(lines)
