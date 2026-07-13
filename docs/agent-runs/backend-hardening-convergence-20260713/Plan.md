# OMI Backend Hardening Convergence Plan

## Execution result

- H0-H4 completed on 2026-07-13 against checkpoint `1a4e847`.
- Full backend: `586 passed` with no warning summary.
- Runtime smoke: 11/11 read-only endpoints returned HTTP 200; isolated listener cleaned up.
- Public API inventory remained 326 total operations and 325 `/api/*` operations.
- Five Taiwan futures operation IDs, response item schemas and handler import seams remained unchanged.

## Milestones

1. H0 - Baseline and risk inventory
   - Scope: checkpoint status, pytest/unittest parity, warnings, router transaction and OpenAPI inventory.
   - Acceptance: each proposed change is tied to reproduced evidence.
   - Validation: clean worktree, 580-test runner comparison, warning-as-error reproduction and static router scan.

2. H1 - SQLite and CI validation convergence
   - Scope: `resource_market/maintenance.py`, focused test and `.github/workflows/ci.yml`.
   - Acceptance: explicit DateTime bind processing; CI invokes pytest over `backend/tests`.
   - Validation: focused warning-as-error test, resource-market suite and CI-equivalent pytest command.

3. H2 - Taiwan futures domain/job boundary
   - Scope: domain-specific refresh-issue recording service, jobs service usage and focused transaction tests.
   - Acceptance: router no longer imports `JobRun` or directly commits; success/partial/error job behavior remains characterized.
   - Validation: Taiwan futures, jobs and router contract targeted suites.

4. H3 - Taiwan futures route-family split
   - Scope: `routers/tw_market_futures.py`, `routers/market.py` include/re-export and OpenAPI inventory.
   - Acceptance: five route contracts and handler identities remain unchanged.
   - Validation: exact operation ID/response-schema assertions and total operation count.

5. H4 - Convergence
   - Scope: direct transaction/HTTP/placeholder rescan, architecture docs, full backend and isolated API smoke.
   - Acceptance: no accidental capability enablement or contract drift; all processes cleaned up.
   - Validation: `run-safe-validation.ps1 -Profile backend`, read-only runtime probes and diff hygiene.

## Stop-and-fix rules

- Any operation ID, response model, query default or route count drift stops H3.
- Any changed job status/result semantics stops H2 until characterized.
- Any warning-as-error failure from a new project code path stops H4.
- No live provider or database migration is used to make tests pass.
- Do not normalize unrelated transaction owners mechanically.

## Decisions

- 2026-07-13: use pytest in CI because it is already installed, is the repo-local validation runner and collected the same 580 baseline tests as unittest.
- 2026-07-13: fix only the reproduced raw SQL datetime bind; do not register a process-global sqlite3 adapter.
- 2026-07-13: move Taiwan futures issue recording to a domain service and use `jobs.service.update_progress` rather than direct router commit.
