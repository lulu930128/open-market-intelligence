# Progress

## Status

- Current phase: full snapshot review details implemented
- Last updated: 2026-07-23 Asia/Taipei

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
- Fixed the history modal's hard-coded 12-item preview limit. History dates now
  load summary-only payloads, while the selected snapshot lazily loads up to 200
  frozen items so a 30-item run displays every hit, miss, neutral, pending, and
  unevaluable row.
- Projected the frozen Radar item evidence stored in `raw_item_json` into the
  outcome read contract, including signals, factor scores, price levels,
  indicator snapshots, and context evidence.
- Reworked each historical stock row into a compact summary with a collapsed
  detail section for snapshot indicators and next-day evaluation evidence.
- Kept pre-evaluation snapshots reviewable by returning saved snapshot items
  with `not_evaluated` status even before outcome rows exist.

## Validation evidence

- `.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs backend\tests\test_watchlist_radar_outcome.py,backend\tests\test_database_migrations.py` passed.
- `.\scripts\run-safe-validation.ps1 -Profile frontend` passed.
- Direct `npm exec tsc -- --noEmit --incremental false` passed before the safe frontend profile.
- Direct `$env:PYTHONPATH = 'backend'; .\.venv\Scripts\python.exe -m pytest backend\tests\test_watchlist_radar_outcome.py -q` passed after adding history support.
- Direct `npm exec tsc -- --noEmit --incremental false` passed after adding the history modal.
- 2026-07-23 targeted backend regression and API inventory:
  `21 passed, 30 subtests passed`.
- 2026-07-23 targeted frontend ESLint and TypeScript no-emit checks passed.
- 2026-07-23 focused Playwright regression
  `Taiwan radar history evaluates the selected snapshot` passed against the
  existing port 3000 dev server. It asserts summary-only history loading,
  selected-snapshot `item_limit=200`, 30 rendered rows, a visible rank-30 miss,
  collapsed-by-default detail, and expanded RSI evidence.
- Read-only local DB/service verification for snapshot run 183
  (`group_id=3`, `2026-07-20`) returned all 30 items, miss ranks
  `16, 22, 24, 25`, neutral rank `26`, and indicator snapshots for all 30 rows.

## Decisions made

- Use explicit write/evaluate endpoints to avoid hidden DB side effects on GET/read paths.
- Store frozen radar item evidence JSON so future rule changes do not mutate historical observations.
- Keep auto-calibration and LLM rule suggestions out of v1.
- Limit frontend controls to Taiwan watchlist radar; US/JP/KR radar panels keep their existing read-only behavior until those markets have their own outcome source mapping.
- Keep the main radar surface compact; multi-day snapshot browsing belongs in a modal instead of expanding the main panel.

## Known issues / risks

- Worktree already contains many unrelated modified files; implementation must avoid broad cleanup or revert.
- Outcome scoring is intentionally coarse in v1 and should be calibrated with real sample review before changing radar weights.
- Main panel still shows the latest snapshot summary by default; older dates are available through the history modal.
- The currently running backend PID 23484 on port 8400 was started without
  reload and still exposes the pre-change OpenAPI contract. It must be restarted
  through the normal OMI launcher before the new selected-snapshot route is live.

## Next step

- Restart OMI through the normal launcher, then open the 2026-07-20 group 3
  snapshot and review all 30 rows plus their collapsed indicator evidence.
