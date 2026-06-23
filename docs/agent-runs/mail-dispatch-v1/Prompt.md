# Mail Dispatch V1

## Goal

- Add a first-version manual mail dispatch workflow to OMI settings: recipient groups, fixed report preview, immediate send, and delivery history.

## Non-goals

- No scheduled dispatch in v1.
- No rapid market move trigger in v1.
- No rich template editor, unsubscribe flow, open tracking, or bulk marketing workflow.
- No frontend access to SMTP secrets.

## Hard constraints

- Mail sending must run through backend services and background jobs, not from frontend code.
- Secrets must stay in environment variables or local secret files, not persisted in app tables.
- Preview must work without SMTP configuration.
- Send must fail predictably when SMTP is not configured.
- Delivery history must record success/error and enough context for retry/debug.
- Existing OMI market logic, watchlist logic, AI report logic, and scheduler behavior should not be duplicated in the frontend.

## Context

- Repo: `C:\project\Open Market Intelligence`
- Backend already has FastAPI routers, SQLAlchemy models, Alembic migrations, `JobRun`, and scheduler/job worker infrastructure.
- `backend/app/ai/reports.py` already builds watchlist brief envelopes from local watchlist/radar evidence.
- First version should reuse those existing report builders and avoid a new market-analysis path.
- Worktree already contains unrelated changes from prior settings/data work; this task must only touch mail-dispatch-related files.

## Deliverables

- DB models and migration for dispatch recipient groups and delivery records.
- Backend dispatch service, SMTP sender, templates, schemas, router, and job task.
- Settings UI section for manual dispatch configuration, preview, send, and history.
- Focused tests for preview, delivery persistence, and SMTP-not-configured behavior.

## Done criteria

- User can create/list/update/delete recipient groups.
- User can preview a fixed report for either all-market overview or a Taiwan watchlist group.
- User can queue immediate send to a recipient group.
- Delivery records are visible from the UI.
- Backend and frontend validation pass for the touched surfaces.

## Open questions / assumptions

- V1 uses SMTP via environment variables; provider-specific APIs such as Gmail API or Resend are deferred.
- V1 supports Taiwan watchlist reports first. US/JP can be added later after the contract is stable.
- "All total analysis" maps to OMI market overview in v1, not an LLM-generated full daily letter.
