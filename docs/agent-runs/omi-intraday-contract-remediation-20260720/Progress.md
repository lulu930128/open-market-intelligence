# Progress

## Status

- Current phase: implementation and isolated runtime verification complete; main-runtime restart probe pending
- Last updated: 2026-07-20 21:43 +08:00

## Completed

- Read repo instructions, product direction, backend architecture, task workflow, AI contract map and freshness probe matrix.
- Read the 2026-07-20 MCP intraday health report and directly verified representative backend and local MCP paths.
- Confirmed the current worktree is heavily modified and established a no-revert, backend/MCP-only ownership boundary.
- Created this task's Prompt, Plan and Progress documents.
- Completed the P0 truth-contract fixes: exchange-timestamp freshness, shared calendar/session classification, deterministic display price, valid index OHLC/volume projection, TWSE MIS diagnostics, request coalescing and circuit protection.
- Completed the P1 execution-contract fixes: explicit provider policy, strict fallback prevention, bounded domain refresh, negative-scope routing, N225 aliases, JP holiday handling and KR stale-stock age gates.
- Completed the P2 observability/trading-mode fixes: per-domain Evidence Passport trust, split operational/live-feed/database/coverage health, disposition batch-auction metadata and dedupe, local 1m-to-5m overlay and unchanged-snapshot suppression.
- Added focused regression coverage for the reported contract failures and preserved the existing public API fields additively.
- Ran isolated HTTP smoke tests on port `18400` with a temporary database; stopped the temporary process and removed its temporary state afterward.
- Kept all frontend calendar/professional-mode files, the active backend on `8400`, the frontend on `3000` and the main SQLite database untouched.

## Validation evidence

- `/api/system/readyz`: backend runtime responds on the launcher-selected URL.
- Local MCP `initialize`, `tools/list`, `tools/call`: transport is healthy and `TARGET_NOT_FOUND` currently projects as MCP `isError=true`.
- `/api/market/quote-depth/2330?refresh=false`: final 2026-07-20 snapshot is available; live depth is unavailable after close.
- `/api/market/intraday/2330/history`: 1m reaches 13:30 while cached 5m stops at 12:58:05.
- `/api/market/indices/summary` vs `/api/market/indices/TAIEX/intraday`: summary/direct time, price and volume disagree.
- `/api/market/calendar-status?market=all`: JP holiday is recognized by calendar owner, but JP market reader still reports `regular`.
- Negative-scope Ask request still routes to `omi.read_stock_broker_branch`.
- Focused remediation regression: 62 tests passed before full-suite validation; the final quote-depth refresh-outcome slice passed 38 focused tests.
- Final safe backend validation: `856 passed in 118.60s`; `compileall` and `git diff --check` also passed. Log: `.tmp/validation/20260720-213930`.
- Isolated negative-scope HTTP probe selected `omi.read_stock_quote`, requested only quote/intraday, excluded chips/fundamentals/broker branch and executed no generic external refresh.
- Isolated global-health probe returned TW/US/JP/KR/CRYPTO dimensions, JP `closed_holiday`, and domain-specific `as_of_by_domain` timestamps.
- Isolated bounded external probe attempted only quote and intraday, preserved requested/effective provider evidence, reported no fallback for `auto`, and selected the usable intraday price without treating after-close depth as live.
- OpenAPI smoke confirmed the additive quote freshness/diagnostics/session fields and intraday disposition/provenance fields.

## Decisions made

- Continue from the existing uncommitted outward-contract and calendar work rather than reverting or reconstructing it.
- Add focused tests before changing each owner because current runtime and source have recently drifted.
- Do not touch frontend professional-mode or calendar-feature files during backend remediation.
- Treat quote/intraday/technical/chips/fundamentals/cross-market trust independently; an unavailable depth or domain must not invalidate usable evidence from another domain.
- Keep `debug` in `diagnostics_level`, not as an answer `mode`; keep `transport_ok` internal to adapter diagnostics.

## Known issues / risks

- The active backend on `8400` predates these source changes; final production-port/MCP deployment proof still requires a clean restart.
- The external `OMI_search` checkout is outside the current writable repo root and may need separate approval for synchronization.
- Active background collectors can write logs/provider events while tests run; deterministic unit/contract tests are the primary proof for failure handling.
- The isolated provider smoke ran after the Taiwan close, so mid-session live semantics are proven by deterministic fixtures rather than a live exchange session.

## Next step

- Restart the active backend/MCP when safe, then repeat the representative health, negative-scope, strict-provider and business-error calls against the launcher-selected URL.
