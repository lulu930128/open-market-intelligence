# Progress

## Status

Implementation and validation complete.

## Confirmed Findings

- UI active scope: `group_id=4`, `mode=action`.
- Scheduler default scope: active root groups only.
- Live history counts: group 4 = 0, group 3 = 3.
- Scheduler runtime is enabled independently from the core market scheduler.
- Existing job result counts reused snapshots as saved.
- Daily-only radar data can be stale while the live intraday radar is current.

## Decisions

- Keep backend as the snapshot and outcome source of truth.
- Preserve existing database rows and public API shapes.
- Use explicit POST/job paths for writes; no GET side effects.
- Retry only after the configured close-time gate and short-circuit once coverage is complete.
- Keep retries bounded to the configured reconciliation window.
- Evaluate only the exact next Taiwan trading day; never substitute a later available date.
- Prefer daily bars and fall back only to intraday data that reaches the closing session.

## Validation Evidence

- Targeted radar/scheduler/ranking regression: 55 passed.
- Backend safe validation: compileall passed, 597 tests passed, diff check passed.
- Backend validation logs: `.tmp/validation/20260713-141620`.
- Frontend safe validation: lint passed, TypeScript no-emit check passed, diff check passed.
- Frontend validation logs: `.tmp/validation/20260713-140856`.
- Isolated runtime on port 43216: health OK, 290 OpenAPI paths, 5 radar paths, snapshot/history routes present.
- Isolated port 43216 released after verification.
- Live read-only coverage audit for 2026-07-13: 34 expected active action-mode scopes, 0 covered before the configured 15:45 run, 4 previous snapshots pending evaluation.
- Production radar tables remained unchanged during validation: 12 snapshot runs, 155 snapshot items, 108 outcomes.

## Delivered Behavior

- Empty group configuration resolves all active groups, including UI child groups.
- Stale snapshot dates are rejected and reported instead of saved.
- Job results distinguish created and existing snapshots and include actual coverage.
- Reconciliation retries missing snapshots and pending evaluations from 15:45 through 18:15.
- Intraday requests share a per-job stock cache across groups.
- Outcome evaluation accepts daily bars or complete closing-session intraday bars for the exact next trading day.
