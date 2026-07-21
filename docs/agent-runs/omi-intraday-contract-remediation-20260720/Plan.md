# Plan

## Milestones

1. Baseline and ownership map — completed
   - Scope: current dirty worktree, live runtime, relevant market/AI/MCP owners and focused tests.
   - Acceptance: every reported issue maps to a current owner, regression test and runtime acceptance probe; overlapping frontend/calendar work is excluded.
   - Validation: `git status --short`, focused `rg`, current targeted tests, read-only API probes.

2. P0 truth contract — completed
   - Scope: TW quote/depth/intraday/index projection, shared session status, provider failure telemetry and bounded TWSE MIS protection.
   - Acceptance: stale data cannot be live; canonical display price is deterministic; direct/summary index fields preserve valid OHLC/volume and age; request storms are bounded.
   - Validation: market provider/index/intraday tests plus new P0 contract regressions.

3. P1 execution and routing contract — completed
   - Scope: provider selection/strict mode, refresh domains, negation-aware Query Plan, quote aliases, JP aliases/holiday and KR stock age gate.
   - Acceptance: requested/effective provider is visible, strict mode does not fallback, excluded domains are never executed, cross-market session semantics align with calendar.
   - Validation: AI outward-contract, JP/KR market, MCP schema and provider fallback tests.

4. P2 health and special trading modes — completed
   - Scope: domain health/passports, disposition metadata/dedupe, 1m-to-5m consistency and provenance.
   - Acceptance: domain failures do not contaminate unrelated trust; disposition stocks are not continuous trading; unchanged snapshots do not become fake bars; timeframe lag is visible or eliminated.
   - Validation: payload/passport, disposition and intraday-history regressions.

5. Consumer and runtime verification — code/test complete; main-runtime restart probe pending
   - Scope: main MCP, external `OMI_search` additive projection, full backend suite and bounded live HTTP/MCP smoke.
   - Acceptance: HTTP and MCP preserve business failures, live-health fields and compatibility; restarted processes serve the current source revision.
   - Validation: safe backend profile, external adapter tests, MCP initialize/tools/list/tools/call, acceptance probes from the source report.

## Stop-and-fix rules

- If an existing modified file belongs to the ex-dividend/calendar or professional-mode work, preserve it and avoid editing unless the health contract cannot be fixed elsewhere.
- If a P0/P1 change causes a targeted regression, fix it before moving to the next milestone.
- Do not validate a circuit breaker by generating an unbounded provider storm; use deterministic tests and at most bounded live probes.
- If the running backend/MCP predates source changes, classify the result as runtime drift and do not call the code fix failed until the correct process is restarted.
- If a proposed fix hides stale/partial/provider failure or moves market logic into a consumer, reject it and return to the backend owner.

## Decisions

- 2026-07-20: Treat the issue list as one long remediation program, but implement in P0/P1/P2 checkpoints so each slice remains reviewable and testable.
- 2026-07-20: Keep frontend professional-mode and calendar-feature files outside this task; only additive backend/MCP contract synchronization is in scope.
- 2026-07-20: Use backend market services and AI Query Plan as truth owners; adapters remain thin.
- 2026-07-20: Validate changed source with an isolated backend and temporary database so the active `8400` backend, frontend work and local database remain untouched.
- 2026-07-20: Defer the final main-runtime/MCP restart probe until the active process can be restarted safely; this is deployment verification, not an unresolved code defect.
