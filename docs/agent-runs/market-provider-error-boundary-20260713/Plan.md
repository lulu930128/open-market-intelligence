# Market Provider Error Boundary Plan

## Milestones

1. E0 - Contract inventory
   - Scope: router catches/imports, service entrypoints, domain error classes and OpenAPI baseline.
   - Acceptance: all 23 affected operations are mapped before edits.
   - Validation: static `rg` inventory and existing API contract tests.

2. E1 - Shared translation boundary
   - Scope: `observability/provider_http.py` and focused tests.
   - Acceptance: raw provider transport errors become a supplied domain error without losing the cause chain; non-transport errors pass through unchanged.
   - Validation: `backend/tests/test_provider_http.py`.

3. E2 - Market service and router convergence
   - Scope: US, JP and KR service entrypoints plus their routers.
   - Acceptance: routers import domain errors from `errors.py` and contain no `requests` dependency; HTTP 502 mapping remains unchanged.
   - Validation: provider-adapter, market-family and API contract regressions.

4. E3 - Architecture invariant
   - Scope: static router boundary test and durable architecture documentation.
   - Acceptance: future router-level `requests` imports fail tests.
   - Validation: `backend/tests/test_api_contract_inventory.py`.

5. E4 - Convergence
   - Scope: full backend validation, worktree hygiene and production-data read-only checks.
   - Acceptance: all backend tests pass, OpenAPI inventory is stable and no production data or listener is changed.
   - Validation: `.\scripts\run-safe-validation.ps1 -Profile backend`.

## Stop-and-fix rules

- Any changed route path, operation ID, response schema, status code or error detail stops E2.
- Any translated exception that loses `ProviderHttpFailure` context stops E1.
- Any fallback behavior change or new live provider request stops the batch.
- Do not remove service-level transport catches without a focused behavioral test.
- Do not modify production SQLite data to make tests pass.

## Decisions

- 2026-07-13: normalize at decorated service entrypoints because providers may intentionally add market-specific messages before the error reaches the service boundary.
- 2026-07-13: keep FastAPI's existing `fetch_error()` mapper; only replace its input from transport exceptions to domain exceptions.
