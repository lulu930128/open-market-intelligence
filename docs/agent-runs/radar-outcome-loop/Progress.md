# Progress

## Status

- Current phase: v1 history modal implemented
- Last updated: 2026-07-07 18:00 Asia/Taipei

## Completed

- Inspected watchlist radar route/service/schema, SQLAlchemy model layout, migration pattern, and local daily price model.
- Established v1 scope: Taiwan radar snapshots and next available trading-day outcome from local `market_daily_price`.
- Added DB models and Alembic migration for radar snapshot runs, frozen snapshot items, and next-day outcomes.
- Added backend service, schemas, and watchlist endpoints for explicit snapshot save, outcome evaluation, and latest outcome summary.
- Added focused backend tests for idempotent snapshot saves, bucket-aware hit scoring, pending next-day data, and migration table coverage.
- Added Taiwan radar panel controls for saving snapshots, evaluating next-day outcomes, and reading the latest outcome summary.
- Confirmed local DB kept multiple snapshot dates for group 3: `2026-07-06` and `2026-07-07`; the disappearance was a latest-only UI/API limitation, not data overwrite.
- Added radar outcome history API so multiple snapshot dates can be listed and selected.
- Added targeted snapshot evaluation by `snapshot_run_id`, so older days can be evaluated without forcing the latest snapshot.
- Added a modal-style radar snapshot history view from the Taiwan radar panel.

## Validation evidence

- `.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs backend\tests\test_watchlist_radar_outcome.py,backend\tests\test_database_migrations.py` passed.
- `.\scripts\run-safe-validation.ps1 -Profile frontend` passed.
- Direct `npm exec tsc -- --noEmit --incremental false` passed before the safe frontend profile.
- Direct `$env:PYTHONPATH = 'backend'; .\.venv\Scripts\python.exe -m pytest backend\tests\test_watchlist_radar_outcome.py -q` passed after adding history support.
- Direct `npm exec tsc -- --noEmit --incremental false` passed after adding the history modal.

## Decisions made

- Use explicit write/evaluate endpoints to avoid hidden DB side effects on GET/read paths.
- Store frozen radar item evidence JSON so future rule changes do not mutate historical observations.
- Keep auto-calibration and LLM rule suggestions out of v1.
- Limit frontend controls to Taiwan watchlist radar; US/JP/KR radar panels keep their existing read-only behavior until those markets have their own outcome source mapping.
- Keep the main radar surface compact; multi-day snapshot browsing belongs in a modal instead of expanding the main panel.

## Known issues / risks

- Worktree already contains many unrelated modified files; implementation must avoid broad cleanup or revert.
- Outcome scoring is intentionally coarse in v1 and should be calibrated with real sample review before changing radar weights.
- Browser runtime validation was not run in this pass; safe frontend lint/typecheck passed.
- Main panel still shows the latest snapshot summary by default; older dates are available through the history modal.

## Next step

- Use the history modal on a Taiwan watchlist group to compare `2026-07-06` and `2026-07-07`, then review bucket-level hit/miss behavior after evaluation.
