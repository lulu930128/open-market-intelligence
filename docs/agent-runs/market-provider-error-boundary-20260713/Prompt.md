# Market Provider Error Boundary

## Goal

- Move US, JP and KR provider transport-error normalization out of FastAPI routers and into the backend service/domain boundary.
- Preserve every affected route's HTTP status and error detail while removing direct `requests` knowledge from router modules.

## Non-goals

- Do not redesign provider fallback order, refresh policy, source-health semantics or provider payload parsing.
- Do not change public paths, methods, query defaults, response schemas or operation IDs.
- Do not modify frontend, MCP, Kuro, database schema or production SQLite data.
- Do not perform live provider refresh, backfill, report/memory writes or delivery actions.
- Do not normalize Taiwan, crypto, connector or AI transport errors in this slice.

## Hard constraints

- Canonical provider failures must retain their cause chain so `provider_http_failure()` can still recover provider context.
- Unhandled `requests.RequestException` from the 23 affected service entrypoints must become the matching US, JP or KR `MarketDataFetchError`.
- Router behavior remains HTTP 502 with the same `detail=str(exc)` contract.
- Market error classes must be imported from each market's `errors.py`, not legacy source/service re-export seams.
- Router modules must not import the `requests` package.

## Context

- Repo: `C:\project\Open Market Intelligence`
- Baseline branch: `codex-kr-market-readiness`
- Baseline checkpoint: `1a4e84762de3aa56dc6447b9edfeebc6271dc3ec`
- Current backend validation: 597 tests passed on 2026-07-13.
- Current architecture scan: 23 `requests.RequestException` catches across `routers/us_market.py`, `routers/jp_market.py` and `routers/kr_market.py`.
- Existing canonical transport layer: `backend/app/observability/provider_http.py`.

## Deliverables

- Reusable typed provider transport-to-domain error decorator.
- Decorated US, JP and KR service entrypoints for all 23 affected route operations.
- Routers that catch only market-domain errors for provider failures.
- Static architecture invariant and runtime error-translation regressions.
- Updated backend architecture and task progress evidence.

## Done criteria

- No router under `backend/app/routers/` imports `requests`.
- No affected router catches `requests.RequestException`.
- Representative raw timeout failures become the correct market-domain error with the original exception as cause.
- Provider failure metadata remains discoverable through a translated domain error.
- OpenAPI remains 326 total operations and 325 `/api/*` operations.
- Full backend safe validation passes without warning summary.

## Open questions / assumptions

- Service modules may retain local `requests` catches where they implement fallback or best-effort behavior; this task only removes transport ownership from routers.
- Existing provider-specific domain messages, such as J-Quants HTTP status messages, take precedence and must not be rewrapped.
