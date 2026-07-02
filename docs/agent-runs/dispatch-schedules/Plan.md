# Plan

## Milestone 1: Backend Contract

- Add DB model and Alembic migration for dispatch schedules.
- Add Pydantic create/update/read schemas.
- Add service functions for CRUD, due detection, run key dedupe, and manual run.
- Add router endpoints under `/api/dispatch/schedules`.

Acceptance:

- Service rejects malformed send time/day/timezone.
- Deleting a recipient group disables dependent schedules instead of leaving active broken jobs.

## Milestone 2: Scheduler Runtime

- Add a lightweight interval job that scans enabled schedules.
- Keep it independent from `ENABLE_SCHEDULER` so mail schedules do not require enabling market-data batch jobs.
- Log checked/queued/error counts.

Acceptance:

- A due schedule queues exactly one delivery for the same local date/time.

## Milestone 3: Frontend Settings

- Extend dispatch API client with schedule types and functions.
- Add schedule form/list to the existing dispatch settings dialog.
- Reuse current report controls as the source of schedule content.

Acceptance:

- Desktop layout remains scannable.
- UI exposes enabled/paused, last run, errors, and run-now.

## Milestone 4: Validation

- Run Python compile and dispatch/migration tests.
- Run frontend lint/typecheck if local dependencies are available.
- Update README and `.env.example`.

Stop-and-fix:

- Do not leave failing tests from files touched in this task.
- If unrelated dirty worktree failures appear, isolate them in the final notes.
