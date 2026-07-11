from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    WatchlistGroup,
    WatchlistRadarOutcome,
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


def _active_root_group_ids(db: Session) -> list[int]:
    groups = watchlist_service.list_groups(db=db, is_active=True)
    return [
        int(group.id)
        for group in groups
        if isinstance(group, WatchlistGroup) and group.parent_id is None
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

    return _active_root_group_ids(db)


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
    outcome_count = (
        db.query(WatchlistRadarOutcome)
        .filter(WatchlistRadarOutcome.snapshot_run_id == snapshot_run_id)
        .count()
    )
    if outcome_count == 0:
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

    if total_scopes == 0:
        return {
            "status": "skipped",
            "message": "No active root watchlist groups found for radar automation.",
            "requested_count": 0,
            "success_count": 0,
            "saved_count": 0,
            "evaluated_count": 0,
            "skipped_count": 0,
            "error_count": 0,
            "results": [],
        }

    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    saved_count = 0
    evaluated_count = 0
    skipped_count = 0
    processed = 0

    for group_id in resolved_group_ids:
        for mode in resolved_modes:
            processed += 1
            if progress_callback is not None:
                progress_callback(
                    processed - 1,
                    total_scopes,
                    f"Processing watchlist radar group {group_id} mode {mode}.",
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

            row: dict[str, Any] = {
                "group_id": group_id,
                "mode": mode,
                "status": "success",
                "evaluated_snapshots": evaluated,
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
                )
                snapshot = radar_outcome_service.save_watchlist_radar_snapshot(
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

            saved_count += 1
            row.update(
                {
                    "snapshot_status": "saved",
                    "snapshot_id": snapshot.get("id"),
                    "snapshot_date": str(snapshot.get("snapshot_date")),
                    "radar_count": snapshot.get("radar_count", 0),
                    "stale_stock_count": snapshot.get("stale_stock_count", 0),
                    "is_current": snapshot.get("is_current", True),
                }
            )
            results.append(row)

    if progress_callback is not None:
        progress_callback(total_scopes, total_scopes, "Watchlist radar automation completed.")

    error_count = len(errors)
    status = "success"
    if error_count and (saved_count or evaluated_count):
        status = "partial_success"
    elif error_count:
        status = "error"
    elif saved_count == 0 and evaluated_count == 0:
        status = "skipped"

    return {
        "status": status,
        "requested_count": total_scopes,
        "success_count": sum(1 for row in results if row.get("status") == "success"),
        "saved_count": saved_count,
        "evaluated_count": evaluated_count,
        "skipped_count": skipped_count,
        "error_count": error_count,
        "group_ids": resolved_group_ids,
        "modes": resolved_modes,
        "evaluate_before_date": before_date.isoformat(),
        "results": results,
        "errors": errors,
    }
