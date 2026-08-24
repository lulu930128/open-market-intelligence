from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import date
import hashlib
from itertools import groupby
import json
from math import sqrt

from sqlalchemy.orm import Session

from app.db.models import (
    BrokerBranchBehaviorFeatureSnapshot,
    BrokerBranchSnapshotQuality,
    BrokerBranchTradeDaily,
    SourceRegistry,
    utc_now,
)
from app.market.broker_branch import NSTOCK_BRANCH_SOURCE_NAME
from app.market.broker_branch_quality import (
    BROKER_BRANCH_COVERAGE_CENSORED,
    reconcile_nstock_snapshot_quality_from_trade_rows,
)
from app.market.trading_calendar import (
    next_taiwan_trading_day,
    previous_taiwan_trading_day,
)
from app.market.tw_universe import list_taiwan_stock_ids


BROKER_BRANCH_BEHAVIOR_METHODOLOGY_V0 = "broker_branch.behavior.shadow.v0"
BROKER_BRANCH_BEHAVIOR_DEFAULT_LOOKBACK_SESSIONS = 120
BROKER_BRANCH_BEHAVIOR_MAX_LOOKBACK_SESSIONS = 120
BROKER_BRANCH_BEHAVIOR_MIN_HIGH_COVERAGE_RATIO = 0.95
BROKER_BRANCH_BEHAVIOR_SCOPE_TYPE_GLOBAL = "global"
BROKER_BRANCH_BEHAVIOR_SCOPE_ID_TW = "TW"

ProgressCallback = Callable[[int | None, int | None, str | None], None]


@dataclass(frozen=True)
class BrokerBranchBehaviorObservation:
    source_id: int
    stock_id: str
    trade_date: date
    branch_code: str
    buy_lots: int | None
    sell_lots: int | None
    net_lots: int | None

    @property
    def direction(self) -> int:
        value = int(self.net_lots or 0)
        if value > 0:
            return 1
        if value < 0:
            return -1
        return 0

    @property
    def gross_lots(self) -> int:
        return abs(int(self.buy_lots or 0)) + abs(int(self.sell_lots or 0))


@dataclass(frozen=True)
class _BrokerBranchBehaviorSourcePlan:
    source_id: int
    candidate_session_count: int
    high_coverage_session_count: int
    universe_count: int
    min_session_coverage_ratio: float | None
    coverage_status: str
    history_status: str
    source_as_of: date | None
    input_fingerprint: str
    warnings: tuple[str, ...]
    features: tuple[
        tuple[str, dict[str, int | float | None]],
        ...,
    ]


def wilson_interval(
    numerator: int,
    denominator: int,
    *,
    z: float = 1.959963984540054,
) -> tuple[float | None, float | None]:
    if denominator <= 0:
        return None, None
    successes = max(0, min(int(numerator), int(denominator)))
    total = int(denominator)
    estimate = successes / total
    z_squared = z * z
    denominator_term = 1 + z_squared / total
    center = (estimate + z_squared / (2 * total)) / denominator_term
    margin = (
        z
        * sqrt(
            estimate * (1 - estimate) / total
            + z_squared / (4 * total * total)
        )
        / denominator_term
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def history_status_for_sessions(high_coverage_session_count: int) -> str:
    count = max(int(high_coverage_session_count), 0)
    if count < 20:
        return "insufficient_history"
    if count < 60:
        return "exploratory_only"
    if count < 120:
        return "calibration_candidate"
    return "production_candidate"


def calculate_branch_behavior_feature(
    observations: Iterable[BrokerBranchBehaviorObservation],
    *,
    eligible_session_pairs: dict[date, date],
    usable_quality_keys: set[tuple[int, str, date]],
) -> dict[str, int | float | None]:
    valid_observations = [item for item in observations if item.direction != 0]
    by_stock_date = {
        (item.stock_id, item.trade_date): item for item in valid_observations
    }

    eligible_initial_count = 0
    reobserved_count = 0
    opposite_observed_count = 0
    same_direction_observed_count = 0
    censored_count = 0

    for item in valid_observations:
        next_session = eligible_session_pairs.get(item.trade_date)
        if next_session is None:
            continue
        current_quality_key = (item.source_id, item.stock_id, item.trade_date)
        next_quality_key = (item.source_id, item.stock_id, next_session)
        if (
            current_quality_key not in usable_quality_keys
            or next_quality_key not in usable_quality_keys
        ):
            continue

        eligible_initial_count += 1
        next_observation = by_stock_date.get((item.stock_id, next_session))
        if next_observation is None or next_observation.direction == 0:
            censored_count += 1
            continue

        reobserved_count += 1
        if next_observation.direction == item.direction:
            same_direction_observed_count += 1
        else:
            opposite_observed_count += 1

    observation_count = len(valid_observations)
    gross_visible_lots = sum(item.gross_lots for item in valid_observations)
    net_visible_lots = sum(int(item.net_lots or 0) for item in valid_observations)
    gross_netting_ratio = (
        max(0.0, min(1.0, 1 - abs(net_visible_lots) / gross_visible_lots))
        if gross_visible_lots > 0
        else None
    )
    stock_observation_counts = Counter(
        item.stock_id for item in valid_observations
    )
    max_stock_observation_share = (
        max(stock_observation_counts.values()) / observation_count
        if observation_count
        else None
    )

    reappearance_rate = _rate(reobserved_count, eligible_initial_count)
    reverse_rate = _rate(opposite_observed_count, reobserved_count)
    same_direction_rate = _rate(
        same_direction_observed_count,
        reobserved_count,
    )
    censored_rate = _rate(censored_count, eligible_initial_count)
    reappearance_interval = wilson_interval(
        reobserved_count,
        eligible_initial_count,
    )
    reverse_interval = wilson_interval(
        opposite_observed_count,
        reobserved_count,
    )
    same_direction_interval = wilson_interval(
        same_direction_observed_count,
        reobserved_count,
    )
    censored_interval = wilson_interval(
        censored_count,
        eligible_initial_count,
    )

    return {
        "observation_count": observation_count,
        "eligible_initial_count": eligible_initial_count,
        "reobserved_count": reobserved_count,
        "opposite_observed_count": opposite_observed_count,
        "same_direction_observed_count": same_direction_observed_count,
        "censored_count": censored_count,
        "session_count": len(
            {item.trade_date for item in valid_observations}
        ),
        "stock_count": len(stock_observation_counts),
        "gross_visible_lots": gross_visible_lots,
        "net_visible_lots": net_visible_lots,
        "reappearance_rate": reappearance_rate,
        "reappearance_interval_low": reappearance_interval[0],
        "reappearance_interval_high": reappearance_interval[1],
        "reverse_given_reappearance_rate": reverse_rate,
        "reverse_interval_low": reverse_interval[0],
        "reverse_interval_high": reverse_interval[1],
        "same_direction_given_reappearance_rate": same_direction_rate,
        "same_direction_interval_low": same_direction_interval[0],
        "same_direction_interval_high": same_direction_interval[1],
        "censored_rate": censored_rate,
        "censored_interval_low": censored_interval[0],
        "censored_interval_high": censored_interval[1],
        "gross_netting_ratio": gross_netting_ratio,
        "observed_sequence_persistence": same_direction_rate,
        "max_stock_observation_share": max_stock_observation_share,
    }


def _bounded_trading_sessions(
    *,
    as_of_trade_date: date,
    lookback_sessions: int,
) -> list[date]:
    latest = previous_taiwan_trading_day(
        as_of_trade_date,
        include_value=True,
    )
    sessions: list[date] = []
    current = latest
    for _ in range(lookback_sessions):
        sessions.append(current)
        current = previous_taiwan_trading_day(current, include_value=False)
    return sorted(sessions)


def _quality_fingerprint(
    rows: Iterable[BrokerBranchSnapshotQuality],
    *,
    methodology_version: str,
    as_of_trade_date: date,
    lookback_sessions: int,
) -> str:
    digest = hashlib.sha256()
    digest.update(
        (
            f"{methodology_version}|{as_of_trade_date.isoformat()}|"
            f"{lookback_sessions}\n"
        ).encode("utf-8")
    )
    for row in rows:
        digest.update(
            (
                f"{row.source_id}|{row.stock_id}|"
                f"{row.expected_trade_date.isoformat()}|"
                f"{row.raw_result_id or ''}|{row.provider_trade_date or ''}|"
                f"{row.coverage_status}|{row.fetch_status}|"
                f"{row.observed_branch_count}\n"
            ).encode("utf-8")
        )
    return digest.hexdigest()


def _upsert_feature_snapshot(
    db: Session,
    *,
    source_id: int,
    branch_code: str,
    as_of_trade_date: date,
    lookback_sessions: int,
    methodology_version: str,
    feature: dict[str, int | float | None],
    candidate_session_count: int,
    high_coverage_session_count: int,
    universe_count: int,
    min_session_coverage_ratio: float | None,
    coverage_status: str,
    history_status: str,
    source_as_of: date | None,
    input_fingerprint: str,
    warnings: list[str],
) -> BrokerBranchBehaviorFeatureSnapshot:
    branch_identity_key = f"{source_id}:{branch_code}"
    row = (
        db.query(BrokerBranchBehaviorFeatureSnapshot)
        .filter(BrokerBranchBehaviorFeatureSnapshot.source_id == source_id)
        .filter(
            BrokerBranchBehaviorFeatureSnapshot.branch_identity_key
            == branch_identity_key
        )
        .filter(
            BrokerBranchBehaviorFeatureSnapshot.scope_type
            == BROKER_BRANCH_BEHAVIOR_SCOPE_TYPE_GLOBAL
        )
        .filter(
            BrokerBranchBehaviorFeatureSnapshot.scope_id
            == BROKER_BRANCH_BEHAVIOR_SCOPE_ID_TW
        )
        .filter(
            BrokerBranchBehaviorFeatureSnapshot.as_of_trade_date
            == as_of_trade_date
        )
        .filter(
            BrokerBranchBehaviorFeatureSnapshot.lookback_sessions
            == lookback_sessions
        )
        .filter(
            BrokerBranchBehaviorFeatureSnapshot.methodology_version
            == methodology_version
        )
        .one_or_none()
    )
    if row is None:
        row = BrokerBranchBehaviorFeatureSnapshot(
            source_id=source_id,
            branch_identity_key=branch_identity_key,
            branch_code=branch_code,
            scope_type=BROKER_BRANCH_BEHAVIOR_SCOPE_TYPE_GLOBAL,
            scope_id=BROKER_BRANCH_BEHAVIOR_SCOPE_ID_TW,
            as_of_trade_date=as_of_trade_date,
            lookback_sessions=lookback_sessions,
            methodology_version=methodology_version,
        )
        db.add(row)

    for key, value in feature.items():
        setattr(row, key, value)
    row.candidate_session_count = candidate_session_count
    row.high_coverage_session_count = high_coverage_session_count
    row.universe_count = universe_count
    row.min_session_coverage_ratio = min_session_coverage_ratio
    row.coverage_status = coverage_status
    row.history_status = history_status
    row.calibration_status = "uncalibrated"
    row.decision_usable = False
    row.source_as_of = source_as_of
    row.price_source_as_of = None
    row.derived_as_of = as_of_trade_date
    row.computed_at = utc_now()
    row.input_fingerprint = hashlib.sha256(
        f"{input_fingerprint}|{branch_identity_key}".encode("utf-8")
    ).hexdigest()
    row.warnings_json = json.dumps(
        list(dict.fromkeys(warnings)),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    db.flush()
    return row


def _observation_stream(
    db: Session,
    *,
    source_id: int,
    trade_dates: list[date],
) -> Iterator[BrokerBranchBehaviorObservation]:
    query = (
        db.query(
            BrokerBranchTradeDaily.source_id,
            BrokerBranchTradeDaily.stock_id,
            BrokerBranchTradeDaily.trade_date,
            BrokerBranchTradeDaily.branch_code,
            BrokerBranchTradeDaily.buy_lots,
            BrokerBranchTradeDaily.sell_lots,
            BrokerBranchTradeDaily.net_lots,
        )
        .filter(BrokerBranchTradeDaily.source_id == source_id)
        .filter(BrokerBranchTradeDaily.trade_date.in_(trade_dates))
        .filter(BrokerBranchTradeDaily.branch_code != "")
        .order_by(
            BrokerBranchTradeDaily.branch_code.asc(),
            BrokerBranchTradeDaily.stock_id.asc(),
            BrokerBranchTradeDaily.trade_date.asc(),
        )
        .yield_per(5000)
    )
    for row in query:
        yield BrokerBranchBehaviorObservation(
            source_id=int(row.source_id),
            stock_id=str(row.stock_id),
            trade_date=row.trade_date,
            branch_code=str(row.branch_code),
            buy_lots=row.buy_lots,
            sell_lots=row.sell_lots,
            net_lots=row.net_lots,
        )


def _delete_stale_feature_rows(
    db: Session,
    *,
    source_id: int,
    as_of_trade_date: date,
    lookback_sessions: int,
    methodology_version: str,
    selected_identity_keys: set[str],
) -> int:
    existing = (
        db.query(
            BrokerBranchBehaviorFeatureSnapshot.id,
            BrokerBranchBehaviorFeatureSnapshot.branch_identity_key,
        )
        .filter(BrokerBranchBehaviorFeatureSnapshot.source_id == source_id)
        .filter(
            BrokerBranchBehaviorFeatureSnapshot.scope_type
            == BROKER_BRANCH_BEHAVIOR_SCOPE_TYPE_GLOBAL
        )
        .filter(
            BrokerBranchBehaviorFeatureSnapshot.scope_id
            == BROKER_BRANCH_BEHAVIOR_SCOPE_ID_TW
        )
        .filter(
            BrokerBranchBehaviorFeatureSnapshot.as_of_trade_date
            == as_of_trade_date
        )
        .filter(
            BrokerBranchBehaviorFeatureSnapshot.lookback_sessions
            == lookback_sessions
        )
        .filter(
            BrokerBranchBehaviorFeatureSnapshot.methodology_version
            == methodology_version
        )
        .all()
    )
    stale_ids = [
        int(row.id)
        for row in existing
        if str(row.branch_identity_key) not in selected_identity_keys
    ]
    deleted_count = 0
    for offset in range(0, len(stale_ids), 500):
        chunk = stale_ids[offset : offset + 500]
        deleted_count += (
            db.query(BrokerBranchBehaviorFeatureSnapshot)
            .filter(BrokerBranchBehaviorFeatureSnapshot.id.in_(chunk))
            .delete(synchronize_session=False)
        )
    return deleted_count


def materialize_broker_branch_behavior_shadow(
    db: Session,
    *,
    as_of_trade_date: date,
    lookback_sessions: int = BROKER_BRANCH_BEHAVIOR_DEFAULT_LOOKBACK_SESSIONS,
    methodology_version: str = BROKER_BRANCH_BEHAVIOR_METHODOLOGY_V0,
    progress: ProgressCallback | None = None,
) -> dict[str, object]:
    """Transaction-owning bounded materialization for V0 shadow features."""
    bounded_lookback = int(lookback_sessions)
    if not 2 <= bounded_lookback <= BROKER_BRANCH_BEHAVIOR_MAX_LOOKBACK_SESSIONS:
        raise ValueError(
            "lookback_sessions must be between 2 and "
            f"{BROKER_BRANCH_BEHAVIOR_MAX_LOOKBACK_SESSIONS}"
        )
    normalized_methodology = str(methodology_version).strip()
    if not normalized_methodology or len(normalized_methodology) > 80:
        raise ValueError("methodology_version must contain 1-80 characters")

    sessions = _bounded_trading_sessions(
        as_of_trade_date=as_of_trade_date,
        lookback_sessions=bounded_lookback,
    )
    universe = list_taiwan_stock_ids(db)
    if not universe:
        return {
            "status": "insufficient_data",
            "reason": "empty_universe",
            "as_of_trade_date": as_of_trade_date,
            "lookback_sessions": bounded_lookback,
            "profiles_written": 0,
        }

    sources = (
        db.query(SourceRegistry)
        .filter(SourceRegistry.source_name == NSTOCK_BRANCH_SOURCE_NAME)
        .order_by(SourceRegistry.id.asc())
        .all()
    )
    if not sources:
        return {
            "status": "insufficient_data",
            "reason": "source_missing",
            "as_of_trade_date": as_of_trade_date,
            "lookback_sessions": bounded_lookback,
            "profiles_written": 0,
        }

    source_ids = [int(source.id) for source in sources]
    available_dates = {
        row[0]
        for row in (
            db.query(BrokerBranchTradeDaily.trade_date)
            .filter(BrokerBranchTradeDaily.source_id.in_(source_ids))
            .filter(BrokerBranchTradeDaily.trade_date.in_(sessions))
            .distinct()
            .all()
        )
    }
    reconciliation_created_count = 0
    reconciliation_updated_count = 0
    try:
        for index, trade_date in enumerate(sorted(available_dates), start=1):
            result = reconcile_nstock_snapshot_quality_from_trade_rows(
                db,
                source_name=NSTOCK_BRANCH_SOURCE_NAME,
                expected_trade_date=trade_date,
                stock_ids=universe,
                max_stocks=len(universe),
            )
            reconciliation_created_count += int(result.get("created_count") or 0)
            reconciliation_updated_count += int(result.get("updated_count") or 0)
            if progress and (index == 1 or index == len(available_dates)):
                progress(
                    index,
                    max(len(available_dates), 1),
                    "Reconciling broker-branch snapshot quality for shadow features.",
                )
        db.commit()

        quality_rows = (
            db.query(BrokerBranchSnapshotQuality)
            .filter(BrokerBranchSnapshotQuality.source_id.in_(source_ids))
            .filter(
                BrokerBranchSnapshotQuality.expected_trade_date.in_(sessions)
            )
            .order_by(
                BrokerBranchSnapshotQuality.source_id.asc(),
                BrokerBranchSnapshotQuality.expected_trade_date.asc(),
                BrokerBranchSnapshotQuality.stock_id.asc(),
            )
            .all()
        )
        quality_by_source: dict[int, list[BrokerBranchSnapshotQuality]] = defaultdict(
            list
        )
        for row in quality_rows:
            quality_by_source[int(row.source_id)].append(row)

        rows_read = 0
        source_plans: list[_BrokerBranchBehaviorSourcePlan] = []
        universe_count = len(universe)
        for source in sources:
            source_id = int(source.id)
            selected_quality = quality_by_source.get(source_id, [])
            usable_quality_keys = {
                (source_id, row.stock_id, row.expected_trade_date)
                for row in selected_quality
                if row.coverage_status == BROKER_BRANCH_COVERAGE_CENSORED
            }
            daily_usable_counts = Counter(
                row.expected_trade_date
                for row in selected_quality
                if row.coverage_status == BROKER_BRANCH_COVERAGE_CENSORED
            )
            daily_coverage_ratios = {
                trade_date: daily_usable_counts.get(trade_date, 0) / universe_count
                for trade_date in sessions
            }
            high_coverage_dates = {
                trade_date
                for trade_date, ratio in daily_coverage_ratios.items()
                if ratio >= BROKER_BRANCH_BEHAVIOR_MIN_HIGH_COVERAGE_RATIO
            }
            eligible_session_pairs = {
                trade_date: next_session
                for trade_date in sessions
                if (next_session := next_taiwan_trading_day(trade_date))
                in high_coverage_dates
                and trade_date in high_coverage_dates
                and next_session <= as_of_trade_date
            }
            high_coverage_session_count = len(high_coverage_dates)
            history_status = history_status_for_sessions(
                high_coverage_session_count
            )
            coverage_status = (
                "insufficient_session_coverage"
                if high_coverage_session_count < 2
                else "high_coverage_window"
                if high_coverage_session_count == len(sessions)
                else "partial_window"
            )
            min_session_coverage_ratio = (
                min(daily_coverage_ratios.values())
                if daily_coverage_ratios
                else None
            )
            source_as_of = (
                max(
                    row.expected_trade_date
                    for row in selected_quality
                    if row.coverage_status == BROKER_BRANCH_COVERAGE_CENSORED
                )
                if usable_quality_keys
                else None
            )
            fingerprint = _quality_fingerprint(
                selected_quality,
                methodology_version=normalized_methodology,
                as_of_trade_date=as_of_trade_date,
                lookback_sessions=bounded_lookback,
            )
            warnings = [
                "shadow_only_not_advertised",
                "ranked_top_n_absence_is_censored",
                "current_universe_used_as_historical_coverage_proxy",
                "uncalibrated_not_decision_usable",
                "price_context_not_computed",
            ]
            if history_status != "production_candidate":
                warnings.append(history_status)

            features: list[
                tuple[str, dict[str, int | float | None]]
            ] = []
            observation_stream = _observation_stream(
                db,
                source_id=source_id,
                trade_dates=sorted(high_coverage_dates),
            )
            for branch_code, group in groupby(
                observation_stream,
                key=lambda item: item.branch_code,
            ):
                observations = list(group)
                rows_read += len(observations)
                feature = calculate_branch_behavior_feature(
                    observations,
                    eligible_session_pairs=eligible_session_pairs,
                    usable_quality_keys=usable_quality_keys,
                )
                if int(feature["observation_count"] or 0) == 0:
                    continue
                features.append((branch_code, feature))

            source_plans.append(
                _BrokerBranchBehaviorSourcePlan(
                    source_id=source_id,
                    candidate_session_count=len(sessions),
                    high_coverage_session_count=high_coverage_session_count,
                    universe_count=universe_count,
                    min_session_coverage_ratio=min_session_coverage_ratio,
                    coverage_status=coverage_status,
                    history_status=history_status,
                    source_as_of=source_as_of,
                    input_fingerprint=fingerprint,
                    warnings=tuple(warnings),
                    features=tuple(features),
                )
            )

        # The observation query intentionally streams a large result set. End
        # that read snapshot before attempting any feature writes; otherwise a
        # concurrent WAL writer can make SQLite reject the read-to-write
        # transaction upgrade with SQLITE_BUSY_SNAPSHOT.
        quality_by_source.clear()
        del quality_rows
        db.rollback()
        if db.get_bind().dialect.name == "sqlite":
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")

        profiles_written = 0
        profiles_deleted = 0
        source_results: list[dict[str, object]] = []
        for plan in source_plans:
            selected_identity_keys: set[str] = set()
            for branch_code, feature in plan.features:
                row = _upsert_feature_snapshot(
                    db,
                    source_id=plan.source_id,
                    branch_code=branch_code,
                    as_of_trade_date=as_of_trade_date,
                    lookback_sessions=bounded_lookback,
                    methodology_version=normalized_methodology,
                    feature=feature,
                    candidate_session_count=plan.candidate_session_count,
                    high_coverage_session_count=(
                        plan.high_coverage_session_count
                    ),
                    universe_count=plan.universe_count,
                    min_session_coverage_ratio=(
                        plan.min_session_coverage_ratio
                    ),
                    coverage_status=plan.coverage_status,
                    history_status=plan.history_status,
                    source_as_of=plan.source_as_of,
                    input_fingerprint=plan.input_fingerprint,
                    warnings=list(plan.warnings),
                )
                selected_identity_keys.add(row.branch_identity_key)
                profiles_written += 1

            profiles_deleted += _delete_stale_feature_rows(
                db,
                source_id=plan.source_id,
                as_of_trade_date=as_of_trade_date,
                lookback_sessions=bounded_lookback,
                methodology_version=normalized_methodology,
                selected_identity_keys=selected_identity_keys,
            )
            source_results.append(
                {
                    "source_id": plan.source_id,
                    "candidate_session_count": plan.candidate_session_count,
                    "high_coverage_session_count": (
                        plan.high_coverage_session_count
                    ),
                    "history_status": plan.history_status,
                    "coverage_status": plan.coverage_status,
                    "source_as_of": plan.source_as_of,
                    "input_fingerprint": plan.input_fingerprint,
                    "profile_count": len(selected_identity_keys),
                }
            )

        db.commit()
    except Exception:
        db.rollback()
        raise

    if progress:
        progress(
            max(profiles_written, 1),
            max(profiles_written, 1),
            "Broker-branch shadow behavior materialization completed.",
        )

    return {
        "status": "completed",
        "mode": "shadow",
        "advertised": False,
        "decision_usable": False,
        "as_of_trade_date": as_of_trade_date,
        "lookback_sessions": bounded_lookback,
        "methodology_version": normalized_methodology,
        "candidate_session_count": len(sessions),
        "quality_rows_created": reconciliation_created_count,
        "quality_rows_updated": reconciliation_updated_count,
        "rows_read": rows_read,
        "profiles_written": profiles_written,
        "profiles_deleted": profiles_deleted,
        "source_results": source_results,
    }
