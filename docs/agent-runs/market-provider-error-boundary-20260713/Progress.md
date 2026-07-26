# Market Provider Error Boundary Progress

## Status

- Current phase: implementation and validation complete; ready for checkpoint review.
- Last updated: 2026-07-13 14:43 Asia/Taipei.

## Completed

- Read the current product direction, backend hardening continuation notes and canonical provider HTTP layer.
- Confirmed 23 router-level `requests.RequestException` catches: US 9, JP 5 and KR 9.
- Added typed `translate_provider_http_errors()` to the canonical provider HTTP module.
- Preserved the original transport exception as cause so `provider_http_failure()` can still recover structured provider context.
- Applied the boundary to all 23 affected US, JP and KR public service entrypoints.
- Changed market routers to import fetch errors from each market's `errors.py` module.
- Removed all `requests` imports and transport catches from backend router modules.
- Preserved the existing HTTP 502 and `detail=str(exc)` route contract.
- Added static router transport-boundary coverage and service/route translation regressions.
- Updated the durable backend architecture contract.

## Validation evidence

- Shared provider HTTP regression: 9 passed.
- Cross-market targeted regression: 144 passed, 56 subtests passed.
- Representative US, JP and KR raw timeouts reached routes as HTTP 502 with unchanged detail.
- Router transport scan: `router_transport_imports=0`.
- OpenAPI read-only inventory: 326 total operations and 325 `/api/*` operations.
- Full backend safe validation: 602 passed in 70.15 seconds; compileall and diff check passed.
- Full validation logs: `.tmp/validation/20260713-144025`.
- Production radar tables remained unchanged: 12 snapshot runs, 155 snapshot items and 108 outcomes.
- Existing listeners were not restarted: backend PID 19240 and frontend PID 47972 still have 2026-07-11 start times.

## Decisions made

- Normalize at decorated service entrypoints because providers may intentionally add market-specific messages before an error reaches the service boundary.
- Keep FastAPI's existing `fetch_error()` mapper; only replace its input from transport exceptions to domain exceptions.
- Leave local service-level `requests` catches in place where they own provider fallback or best-effort behavior.
- Keep provider-specific domain errors untouched and preserve canonical provider failure metadata through exception chaining.

## Known issues / risks

- The worktree also contains completed backend-hardening and radar-snapshot changes; those remain the existing local baseline and were not reverted.
- Current `8400/3000` processes predate the local changes and require a normal service restart before the new runtime behavior is active.
- The first provider HTTP focused command was run from repo root and failed collection because `app` was not on the import path; rerunning from the established `backend` test working directory passed.
- Two ad hoc OpenAPI one-liners had PowerShell quoting errors; the here-string probe and invariant test both passed with 326/325 operations.

## Next step

- Review the combined changed-file scope and create a checkpoint commit when requested before starting another architecture slice.
