from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    WatchlistGroup,
    WatchlistRadarOutcome,
    WatchlistRadarSnapshotItem,
    WatchlistRadarSnapshotRun,
)
from app.watchlists import (
    radar_outcome_service,
    radar_service,
    service as watchlist_service,
)


ProgressCallback = Callable[[int | None, int | None, str | None], None]


def _split_csv(value: str | Sequence[str] | None) -> list[str]:
    if value is None:
        return []

    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]

    return [str(item).strip() for item in value if str(item).strip()]


def _parse_group_ids(value: str | Sequence[int | str] | None) -> list[int] | None:
    items = _split_csv(value) if isinstance(value, str) else value
    if not items:
        return None

    group_ids: list[int] = []
    for item in items:
        try:
            group_id = int(item)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid watchlist radar group id: {item!r}.") from exc
        if group_id <= 0:
            raise ValueError(f"Invalid watchlist radar group id: {item!r}.")
        group_ids.append(group_id)

    return list(dict.fromkeys(group_ids))


def _normalize_modes(value: str | Sequence[str] | None) -> list[str]:
    modes = [mode.lower() for mode in _split_csv(value)]
    return list(dict.fromkeys(modes or ["action"]))


def _active_group_ids(db: Session) -> list[int]:
    groups = watchlist_service.list_groups(db=db, is_active=True)
    return [
        int(group.id)
        for group in groups
        if isinstance(group, WatchlistGroup)
    ]


def _resolve_group_ids(
    db: Session,
    group_ids: str | Sequence[int | str] | None,
) -> list[int]:
    parsed_group_ids = _parse_group_ids(group_ids)
    if parsed_group_ids is not None:
        for group_id in parsed_group_ids:
            watchlist_service.get_group(db=db, group_id=group_id)
        return parsed_group_ids

    return _active_group_ids(db)


def get_watchlist_radar_daily_coverage(
    *,
    db: Session,
    snapshot_date: date,
    group_ids: str | Sequence[int | str] | None = None,
    modes: str | Sequence[str] | None = "action",
    include_children: bool = True,
    enabled_only: bool = True,
    evaluate_lookback_days: int = 10,
    radar_rule_version: str = radar_outcome_service.RADAR_RULE_VERSION,
) -> dict[str, Any]:
    resolved_group_ids = _resolve_group_ids(db=db, group_ids=group_ids)
    resolved_modes = _normalize_modes(modes)
    expected_scopes = [
        (group_id, mode)
        for group_id in resolved_group_ids
        for mode in resolved_modes
    ]

    covered_scopes: set[tuple[int, str]] = set()
    if expected_scopes:
        rows = (
            db.query(
                WatchlistRadarSnapshotRun.group_id,
                WatchlistRadarSnapshotRun.mode,
            )
            .filter(WatchlistRadarSnapshotRun.group_id.in_(resolved_group_ids))
            .filter(WatchlistRadarSnapshotRun.mode.in_(resolved_modes))
            .filter(WatchlistRadarSnapshotRun.snapshot_date == snapshot_date)
            .filter(WatchlistRadarSnapshotRun.include_children.is_(include_children))
            .filter(WatchlistRadarSnapshotRun.enabled_only.is_(enabled_only))
            .filter(WatchlistRadarSnapshotRun.radar_rule_version == radar_rule_version)
            .all()
        )
        covered_scopes = {(int(group_id), str(mode)) for group_id, mode in rows}

    missing_scopes = [
        {"group_id": group_id, "mode": mode}
        for group_id, mode in expected_scopes
        if (group_id, mode) not in covered_scopes
    ]
    expected_count = len(expected_scopes)
    covered_count = expected_count - len(missing_scopes)
    pending_evaluations: list[dict[str, Any]] = []
    for group_id, mode in expected_scopes:
        runs = _recent_runs_to_evaluate(
            db=db,
            group_id=group_id,
            mode=mode,
            before_date=snapshot_date,
            lookback_days=evaluate_lookback_days,
            radar_rule_version=radar_rule_version,
        )
        pending_evaluations.extend(
            {
                "group_id": group_id,
                "mode": mode,
                "snapshot_run_id": run.id,
                "snapshot_date": run.snapshot_date.isoformat(),
            }
            for run in runs
            if _run_needs_evaluation(db, run.id)
        )

    if expected_count == 0:
        status = "no_groups"
    elif missing_scopes:
        status = "partial" if covered_count else "missing"
    else:
        status = "complete"

    return {
        "status": status,
        "complete": not missing_scopes,
        "reconciliation_complete": not missing_scopes and not pending_evaluations,
        "snapshot_date": snapshot_date.isoformat(),
        "expected_count": expected_count,
        "covered_count": covered_count,
        "missing_count": len(missing_scopes),
        "missing_scopes": missing_scopes,
        "pending_evaluation_count": len(pending_evaluations),
        "pending_evaluations": pending_evaluations,
        "group_ids": resolved_group_ids,
        "modes": resolved_modes,
    }


def _recent_runs_to_evaluate(
    *,
    db: Session,
    group_id: int,
    mode: str,
    before_date: date,
    lookback_days: int,
    radar_rule_version: str,
) -> list[WatchlistRadarSnapshotRun]:
    earliest_date = before_date - timedelta(days=max(1, min(lookback_days, 365)))
    return (
        db.query(WatchlistRadarSnapshotRun)
        .filter(WatchlistRadarSnapshotRun.group_id == group_id)
        .filter(WatchlistRadarSnapshotRun.mode == mode)
        .filter(WatchlistRadarSnapshotRun.radar_rule_version == radar_rule_version)
        .filter(WatchlistRadarSnapshotRun.snapshot_date < before_date)
        .filter(WatchlistRadarSnapshotRun.snapshot_date >= earliest_date)
        .order_by(
            WatchlistRadarSnapshotRun.snapshot_date.desc(),
            WatchlistRadarSnapshotRun.id.desc(),
        )
        .all()
    )


def _run_needs_evaluation(db: Session, snapshot_run_id: int) -> bool:
    item_count = (
        db.query(WatchlistRadarSnapshotItem)
        .filter(WatchlistRadarSnapshotItem.snapshot_run_id == snapshot_run_id)
        .count()
    )
    if item_count == 0:
        return False

    outcome_count = (
        db.query(WatchlistRadarOutcome)
        .filter(WatchlistRadarOutcome.snapshot_run_id == snapshot_run_id)
        .count()
    )
    if outcome_count < item_count:
        return True

    pending_count = (
        db.query(WatchlistRadarOutcome)
        .filter(WatchlistRadarOutcome.snapshot_run_id == snapshot_run_id)
        .filter(WatchlistRadarOutcome.status == "pending")
        .count()
    )
    return pending_count > 0


def _evaluate_recent_runs(
    *,
    db: Session,
    group_id: int,
    mode: str,
    before_date: date,
    lookback_days: int,
    radar_rule_version: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    summaries: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    runs = _recent_runs_to_evaluate(
        db=db,
        group_id=group_id,
        mode=mode,
        before_date=before_date,
        lookback_days=lookback_days,
        radar_rule_version=radar_rule_version,
    )

    for run in runs:
        if not _run_needs_evaluation(db, run.id):
            continue

        try:
            summary = radar_outcome_service.evaluate_watchlist_radar_outcome(
                db=db,
                group_id=group_id,
                mode=mode,
                snapshot_run_id=run.id,
                radar_rule_version=radar_rule_version,
            )
        except Exception as exc:
            db.rollback()
            errors.append(
                {
                    "group_id": group_id,
                    "mode": mode,
                    "snapshot_run_id": run.id,
                    "snapshot_date": run.snapshot_date.isoformat(),
                    "status": "error",
                    "error_message": str(exc),
                }
            )
            continue

        snapshot = summary.get("snapshot") or {}
        summaries.append(
            {
                "snapshot_run_id": snapshot.get("id") or run.id,
                "snapshot_date": str(snapshot.get("snapshot_date") or run.snapshot_date),
                "status": summary.get("status"),
                "total_count": summary.get("total_count", 0),
                "hit_count": summary.get("hit_count", 0),
                "miss_count": summary.get("miss_count", 0),
                "pending_count": summary.get("pending_count", 0),
            }
        )

    return summaries, errors


def run_watchlist_radar_automation(
    *,
    db: Session,
    group_ids: str | Sequence[int | str] | None = None,
    modes: str | Sequence[str] | None = "action",
    include_children: bool = True,
    enabled_only: bool = True,
    max_results: int = 30,
    calculation_limit: int = 100,
    ma_windows: str | None = None,
    volume_ma_windows: str | None = None,
    volume_ratio_threshold: float | None = None,
    use_intraday: bool = False,
    intraday_limit: int = 30,
    evaluate_before_date: date | None = None,
    evaluate_lookback_days: int = 10,
    save_snapshots: bool = True,
    radar_rule_version: str = radar_outcome_service.RADAR_RULE_VERSION,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    resolved_group_ids = _resolve_group_ids(db=db, group_ids=group_ids)
    resolved_modes = _normalize_modes(modes)
    before_date = evaluate_before_date or date.today()
    total_scopes = len(resolved_group_ids) * len(resolved_modes)
    total_steps = total_scopes * 2

    if total_scopes == 0:
        return {
            "status": "skipped",
            "message": "No active watchlist groups found for radar automation.",
            "requested_count": 0,
            "success_count": 0,
            "saved_count": 0,
            "existing_count": 0,
            "evaluated_count": 0,
            "skipped_count": 0,
            "invalid_count": 0,
            "error_count": 0,
            "group_ids": [],
            "modes": resolved_modes,
            "evaluate_before_date": before_date.isoformat(),
            "coverage": {
                "status": "no_groups",
                "complete": True,
                "reconciliation_complete": True,
                "snapshot_date": before_date.isoformat(),
                "expected_count": 0,
                "covered_count": 0,
                "missing_count": 0,
                "missing_scopes": [],
                "pending_evaluation_count": 0,
                "pending_evaluations": [],
                "group_ids": [],
                "modes": resolved_modes,
            },
            "results": [],
            "errors": [],
        }

    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    saved_count = 0
    existing_count = 0
    evaluated_count = 0
    skipped_count = 0
    invalid_count = 0
    processed = 0
    intraday_overlay_cache: dict[str, dict | None] | None = (
        {} if use_intraday else None
    )

    for group_id in resolved_group_ids:
        for mode in resolved_modes:
            processed += 1
            if progress_callback is not None:
                progress_callback(
                    processed - 1,
                    total_steps,
                    f"Saving watchlist radar group {group_id} mode {mode}.",
                )

            row: dict[str, Any] = {
                "group_id": group_id,
                "mode": mode,
                "status": "success",
                "evaluated_snapshots": [],
            }

            if not save_snapshots:
                row["snapshot_status"] = "skipped"
                row["message"] = "Snapshot save skipped by scheduler calendar gate."
                skipped_count += 1
                results.append(row)
                continue

            request = {
                "group_id": group_id,
                "include_children": include_children,
                "enabled_only": enabled_only,
                "mode": mode,
                "max_results": max_results,
                "ma_windows": ma_windows,
                "volume_ma_windows": volume_ma_windows,
                "calculation_limit": calculation_limit,
                "volume_ratio_threshold": volume_ratio_threshold,
                "use_intraday": use_intraday,
                "intraday_limit": intraday_limit,
                "source": "scheduler.watchlist_radar_auto_snapshot",
            }

            try:
                radar = radar_service.get_watchlist_group_radar(
                    db=db,
                    group_id=group_id,
                    include_children=include_children,
                    enabled_only=enabled_only,
                    mode=mode,
                    max_results=max_results,
                    ma_windows=ma_windows,
                    volume_ma_windows=volume_ma_windows,
                    calculation_limit=calculation_limit,
                    volume_ratio_threshold=volume_ratio_threshold,
                    use_intraday=use_intraday,
                    intraday_limit=intraday_limit,
                    intraday_overlay_cache=intraday_overlay_cache,
                )
                observed_snapshot_date = (
                    radar_outcome_service.watchlist_radar_snapshot_date(radar)
                )
                if observed_snapshot_date != before_date:
                    error_message = (
                        "Radar snapshot date does not match the expected trading date: "
                        f"expected={before_date.isoformat()} "
                        f"observed={observed_snapshot_date.isoformat()}."
                    )
                    error = {
                        "group_id": group_id,
                        "mode": mode,
                        "status": "error",
                        "snapshot_status": "stale",
                        "expected_snapshot_date": before_date.isoformat(),
                        "observed_snapshot_date": observed_snapshot_date.isoformat(),
                        "error_message": error_message,
                    }
                    errors.append(error)
                    results.append({**row, **error})
                    invalid_count += 1
                    continue

                save_result = radar_outcome_service.save_watchlist_radar_snapshot_with_status(
                    db=db,
                    radar=radar,
                    request=request,
                    enabled_only=enabled_only,
                    radar_rule_version=radar_rule_version,
                )
            except Exception as exc:
                db.rollback()
                error = {
                    "group_id": group_id,
                    "mode": mode,
                    "status": "error",
                    "error_message": str(exc),
                }
                errors.append(error)
                results.append({**row, **error})
                continue

            snapshot = save_result.snapshot
            if save_result.created:
                saved_count += 1
                snapshot_status = "created"
            else:
                existing_count += 1
                snapshot_status = "existing"
            row.update(
                {
                    "snapshot_status": snapshot_status,
                    "snapshot_id": snapshot.get("id"),
                    "snapshot_date": str(snapshot.get("snapshot_date")),
                    "radar_count": snapshot.get("radar_count", 0),
                    "stale_stock_count": snapshot.get("stale_stock_count", 0),
                    "is_current": snapshot.get("is_current", True),
                }
            )
            results.append(row)

    evaluation_processed = 0
    for group_id in resolved_group_ids:
        for mode in resolved_modes:
            evaluation_processed += 1
            if progress_callback is not None:
                progress_callback(
                    total_scopes + evaluation_processed - 1,
                    total_steps,
                    f"Evaluating watchlist radar group {group_id} mode {mode}.",
                )

            evaluated, evaluation_errors = _evaluate_recent_runs(
                db=db,
                group_id=group_id,
                mode=mode,
                before_date=before_date,
                lookback_days=evaluate_lookback_days,
                radar_rule_version=radar_rule_version,
            )
            evaluated_count += len(evaluated)
            errors.extend(evaluation_errors)

            result_row = next(
                (
                    item
                    for item in results
                    if item.get("group_id") == group_id and item.get("mode") == mode
                ),
                None,
            )
            if result_row is not None:
                result_row["evaluated_snapshots"] = evaluated
                if evaluation_errors:
                    result_row["evaluation_errors"] = evaluation_errors

    if progress_callback is not None:
        progress_callback(total_steps, total_steps, "Watchlist radar automation completed.")

    coverage = get_watchlist_radar_daily_coverage(
        db=db,
        snapshot_date=before_date,
        group_ids=resolved_group_ids,
        modes=resolved_modes,
        include_children=include_children,
        enabled_only=enabled_only,
        evaluate_lookback_days=evaluate_lookback_days,
        radar_rule_version=radar_rule_version,
    )
    error_count = len(errors)
    status = "success"
    if error_count and (saved_count or existing_count or evaluated_count):
        status = "partial_success"
    elif error_count:
        status = "error"
    elif save_snapshots and not coverage["complete"]:
        status = "error"
    elif save_snapshots and not coverage["reconciliation_complete"]:
        status = "partial_success"
    elif not save_snapshots and evaluated_count == 0:
        status = "skipped"

    return {
        "status": status,
        "requested_count": total_scopes,
        "success_count": sum(1 for row in results if row.get("status") == "success"),
        "saved_count": saved_count,
        "existing_count": existing_count,
        "evaluated_count": evaluated_count,
        "skipped_count": skipped_count,
        "invalid_count": invalid_count,
        "error_count": error_count,
        "group_ids": resolved_group_ids,
        "modes": resolved_modes,
        "evaluate_before_date": before_date.isoformat(),
        "coverage": coverage,
        "results": results,
        "errors": errors,
    }
