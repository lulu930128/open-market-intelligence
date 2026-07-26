# 韓股後端 v1 實作計畫

## Milestone 1: Repo Alignment

- Read existing JP/US market implementation, scheduler, source health, migration style.
- Confirm product docs do not add extra binding product facts.
- Acceptance: implementation choices align with current OMI market module boundaries.

## Milestone 2: Data Contract

- Add KR stock master, daily price, company fundamental, investor trade, watchlist tables.
- Add parser dataclasses and normalization rules for Korean local codes and Yahoo suffixes.
- Acceptance: unit tests can parse KRX/OpenDART/Yahoo shaped mocked payloads.

## Milestone 3: Service And API

- Add CRUD/search/list, daily refresh, resource summary, source health, watchlist refresh, OHLC endpoints.
- Add source health snapshots for `market="kr"`.
- Acceptance: route registration tests pass and service works on in-memory SQLite.

## Milestone 4: Runtime Integration

- Add job types, tracked background job wrapper, optional scheduler config, refresh execution market defaults.
- Keep Korean scheduler disabled by default.
- Acceptance: scheduler unit tests can verify cron registration only when enabled.

## Milestone 5: Verification

- Run targeted KR tests.
- Run compile/syntax check.
- Run only broader tests touched by scheduler/settings if targeted changes require it.
- Stop and fix if failures are caused by this task.

## Failure Handling

- Live provider failures are not blockers for tests; mocked payload tests define parser correctness.
- If KRX live endpoint details are unstable, keep fetch wrapper narrow and surface provider failure instead of hiding it.
- If existing dirty worktree causes unrelated failures, report them separately and avoid reverting user changes.
