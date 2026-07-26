# Plan

## Milestones

1. Inspect radar, DB, migration, and frontend contracts.
   - Scope: backend watchlist radar, models, migrations, frontend panel.
   - Acceptance: clear boundaries for explicit write endpoint and local-only evaluation.
   - Validation: repository reads and diff review.

2. Add backend closed-loop persistence and evaluation.
   - Scope: SQLAlchemy models, Alembic migration, schemas, service, watchlist routes.
   - Acceptance: snapshot creation is idempotent and outcome evaluation returns bucket-aware summary.
   - Validation: targeted backend tests and migration test updates.

3. Add Today Radar UI affordance.
   - Scope: `WatchlistRadarPanel` and i18n/type definitions as needed.
   - Acceptance: user can save/evaluate and see latest outcome status without changing individual stock radar badges.
   - Validation: frontend lint and TypeScript check.

4. Run safe validation and document residual risks.
   - Scope: backend compile/tests, frontend profile, diff check.
   - Acceptance: failures are fixed or isolated with a clear reason.
   - Validation: `run-safe-validation.ps1` targeted profiles or equivalent commands.

## Stop-and-fix rules

- If migration tests fail, fix schema/revision handling before frontend work.
- If outcome logic cannot identify next-day local bars, return an explicit unevaluable status instead of guessing.
- If API changes break existing radar response shape, stop and preserve compatibility.
- If validation indicates unrelated dirty worktree failures, isolate them and report rather than reverting user changes.

## Decisions

- 2026-07-07: Use explicit POST endpoints for snapshot/evaluation so GET radar remains side-effect free.
- 2026-07-07: Treat outcome as signal-quality evaluation, not buy/sell performance.
