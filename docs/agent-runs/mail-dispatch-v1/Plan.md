# Plan

## Milestones

1. Backend persistence and API
   - Scope: SQLAlchemy models, Alembic migration, dispatch schemas/service/router.
   - Acceptance: CRUD recipient groups, preview payloads, and delivery listing work through service functions and API shapes.
   - Validation: `.\.venv\Scripts\python.exe -m compileall backend\app`

2. Mail sender and job integration
   - Scope: SMTP sender, delivery job task, `JobRun` queue wiring.
   - Acceptance: sending without SMTP configuration records an error delivery; SMTP code path is unit-testable without network.
   - Validation: focused backend tests.

3. Settings UI first version
   - Scope: `SettingsDock` dispatch panel, frontend API helper, i18n labels.
   - Acceptance: user can manage recipients, preview, send, and see delivery history from Settings.
   - Validation: `npm exec tsc -- --noEmit --incremental false --pretty false`, `npm run lint`, `npm run build`.

4. Final verification and progress update
   - Scope: docs progress and touched-file checks.
   - Acceptance: `Progress.md` records validation evidence and known risks.
   - Validation: `git diff --check -- <touched files>`.

## Stop-and-fix rules

- If backend tests fail, fix backend before moving to UI.
- If SMTP secrets or recipient addresses risk being exposed in frontend logs or persisted payloads beyond intended delivery records, stop and revise the trust boundary.
- If preview requires expensive or mutating data refresh, stop and keep v1 preview read-only.
- If UI changes require broad redesign of SettingsDock, stop and reduce scope.

## Decisions

- 2026-06-22: V1 is manual-only. Scheduling and rapid move triggers are deferred so the sending/delivery contract can stabilize first.
- 2026-06-22: Use SMTP from Python standard library for v1 to avoid new dependencies.
- 2026-06-22: Reuse OMI report/overview builders instead of duplicating market logic in dispatch.
