# Backend Optimization Scan Progress

## Current status

Status: Batch 1 and Batch 2 implemented after checkpoint commit `70ad046`. Runtime lifecycle and AI market payload helper consolidation are now in code with targeted backend validation passing.

## Implementation update - 2026-07-11

### Batch 0 - Baseline

Completed. The current worktree was checkpointed before maintenance, then the fuller Batch 0 backend baseline passed:

```powershell
.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs @(
  'backend\tests\test_ai_ask_stages.py',
  'backend\tests\test_ai_freshness_guard.py',
  'backend\tests\test_jp_market_data.py',
  'backend\tests\test_kr_market_data.py',
  'backend\tests\test_portfolio_holdings.py',
  'backend\tests\test_watchlist_radar_automation.py'
) -BackendTestTimeoutSeconds 240
```

Result:

- `backend compileall`: passed.
- targeted `backend pytest`: passed.
- `git diff --check`: passed.

### Batch 1 - Runtime side-effect boundary

Completed. `backend/app/runtime.py` now owns the startup/shutdown lifecycle:

- database migrations and `init_db`;
- interrupted job marking;
- scheduler startup/shutdown;
- crypto auto-refresh startup/shutdown;
- crypto realtime collector startup/shutdown;
- job executor shutdown.

`backend/app/main.py` now only wires the FastAPI app, middleware, exception handlers, and routers, then delegates lifespan behavior to `app.runtime.lifespan`. This keeps behavior equivalent while making runtime side effects testable without bloating the route registry module.

Regression coverage added in `backend/tests/test_runtime.py`:

- startup initializes DB and background components;
- startup failure after a partial background start triggers cleanup;
- shutdown calls every runtime cleanup step;
- shutdown still attempts remaining cleanup when an earlier step fails.

Targeted validation:

```powershell
.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs @(
  'backend\tests\test_runtime.py',
  'backend\tests\test_system_health.py',
  'backend\tests\test_calendar_status_integration.py'
) -BackendTestTimeoutSeconds 240
```

Result:

- `backend compileall`: passed.
- targeted `backend pytest`: passed.
- `git diff --check`: passed.

### Batch 2 - AI market payload contract helper consolidation

Completed. `backend/app/ai/market_payload_contract.py` now centralizes pure payload contract helpers:

- payload level parsing and aliases (`payload_level`, `detail_level`, `detail`);
- intraday point limit defaults and bounds;
- generic bounded integer request parameter parsing;
- recursive payload presence checks;
- slot envelope construction;
- payload slot status calculation.

`backend/app/ai/tools.py` and `backend/app/ai/agentic_tools.py` now import these helpers instead of carrying separate implementations. The existing response shapes remain unchanged: `result.data.slots`, `result.data.compact.slots`, `analysis.human_answer`, and `analysis.decision_contract` are still assembled by the same higher-level code paths.

Regression coverage added in `backend/tests/test_ai_market_payload_contract.py`:

- payload-level aliases and fallback behavior;
- intraday defaults and override bounds;
- bounded integer parsing across fallback keys;
- slot metadata de-duplication;
- payload presence/status semantics.

Targeted validation:

```powershell
.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs @(
  'backend\tests\test_ai_market_payload_contract.py',
  'backend\tests\test_ai_ask_stages.py',
  'backend\tests\test_ai_freshness_guard.py'
) -BackendTestTimeoutSeconds 240
```

Result:

- `backend compileall`: passed.
- targeted `backend pytest`: passed.
- `git diff --check`: passed.

### Additional stability fix - portfolio context on DB-less AI paths

Full backend validation exposed an existing regression in the AI decision-core tests: some read-only AI assembly paths call `ai_ask.ask(db=None, ...)`, but portfolio saved-position lookup expected a live SQLAlchemy session and called `db.query(...)`.

Fixed by making `portfolio_service.get_position_context_for_scope` return an empty context when no DB session is available. This keeps saved position context additive: missing DB context should not block AI question understanding or answer assembly.

Regression coverage added in `backend/tests/test_portfolio_holdings.py`.

Targeted validation:

```powershell
.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs @(
  'backend\tests\test_ai_decision_core.py',
  'backend\tests\test_portfolio_holdings.py'
) -BackendTestTimeoutSeconds 240
```

Result:

- `backend compileall`: passed.
- targeted `backend pytest`: passed.
- `git diff --check`: passed.

### Final backend validation

After the runtime, payload-helper, and portfolio-context fixes, the full backend profile passed:

```powershell
.\scripts\run-safe-validation.ps1 -Profile backend -BackendTestTimeoutSeconds 600
```

Result:

- `backend compileall`: passed.
- `backend pytest backend/tests`: passed.
- `git diff --check`: passed.

This final run was repeated after adding startup-failure cleanup coverage for `RuntimeCoordinator`.

### Batch 3 - Market-family router helper pass

Completed first router-level slice. `backend/app/routers/market_family_helpers.py` now centralizes:

- provider fetch error mapping to `502`;
- market watchlist group error mapping;
- market watchlist item error mapping;
- watchlist group target formatting (`all` vs `group:{id}`);
- serialized job enqueue wrapper used by market-family router refresh endpoints.

`backend/app/routers/us_market.py`, `backend/app/routers/jp_market.py`, and `backend/app/routers/kr_market.py` now use the shared helper for their watchlist error mapping and resource refresh job enqueue paths. Route paths, response models, query parameters, service calls, job type strings, request envelope keys, and task argument order are preserved.

Regression coverage added in `backend/tests/test_market_family_router_helpers.py`.

Targeted validation:

```powershell
.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs @(
  'backend\tests\test_market_family_router_helpers.py',
  'backend\tests\test_us_market_data.py',
  'backend\tests\test_jp_market_data.py',
  'backend\tests\test_kr_market_data.py'
) -BackendTestTimeoutSeconds 360
```

Result:

- `backend compileall`: passed.
- targeted `backend pytest`: passed.
- `git diff --check`: passed.

Full backend validation after this Batch 3 slice:

```powershell
.\scripts\run-safe-validation.ps1 -Profile backend -BackendTestTimeoutSeconds 600
```

Result:

- `backend compileall`: passed.
- `backend pytest backend/tests`: passed.
- `git diff --check`: passed.

Remaining Batch 3 work:

- Consider whether scheduler enqueue functions should also adopt the same helper, but only if it does not hide schedule-specific request fields such as `schedule` and calendar release metadata.
- Consider a second pass over Taiwan `watchlists.py`; it has older local patterns and visible whitespace churn, so it should be handled as its own bounded cleanup rather than folded into US/JP/KR router helper extraction.

## Evidence collected

- Product docs are now filled and usable, not blank templates. Key direction: backend owns market data, freshness, AI reasoning, tool orchestration, and answer contract.
- README and AGENTS align on Taiwan-first, local-first, freshness-visible, bounded refresh behavior.
- Existing `architecture-hardening-1-2-4` completed product baseline, payload slot invariant, and frontend navigation hardening.
- Existing `productized-market-payload-contract` says backend/MCP/frontend slot skeleton is connected, but Kuro consumption and market-specific enrichment remain.
- Existing `omi-ai-decision-core` says `analysis.decision_contract` is additive and should not replace `analysis.human_answer`.
- Current worktree is heavily dirty: `git diff --stat` showed 60 tracked files changed with about 3622 insertions and 583 deletions, plus untracked portfolio/watchlist automation files.

## Static backend shape

- Route modules: 18 router files; largest route surface is `backend/app/routers/market.py` with 60 route decorators.
- Largest backend modules by line count:
  - `backend/app/ai/answer_composer.py`: 3843 lines
  - `backend/app/ai/tools.py`: 3304 lines
  - `backend/app/ai/agentic_tools.py`: 2930 lines
  - `backend/app/us_market/service.py`: 2845 lines
  - `backend/app/crypto_market/service.py`: 2518 lines
  - `backend/app/db/models.py`: 2448 lines
  - `backend/app/market/indices.py`: 2425 lines
  - `backend/app/jp_market/service.py`: 2392 lines
  - `backend/app/kr_market/service.py`: 2381 lines
  - `backend/app/routers/market.py`: 1787 lines
- Backend tests exist and are broad: 47 files under `backend/tests`.
- Alembic migration chain exists through `20260709_0033_portfolio_holdings.py`.

## Findings

### P0 - Dirty worktree makes a broad backend refactor unsafe

The repo currently has large in-progress changes across backend, frontend, tests, docs, and new untracked files. A backend optimization should not start as a sweeping refactor until the current branch is validated or checkpointed.

Recommended first action: run a targeted backend baseline and decide whether the current dirty set is expected to be preserved as one work package.

### P1 - Runtime side effects are coupled to app startup

`backend/app/main.py` startup currently runs migrations, initializes DB, marks interrupted jobs, starts scheduler, starts crypto auto-refresh, and starts crypto realtime collectors. Config defaults keep several background components enabled, including Taiwan futures scheduler, watchlist radar scheduler, dispatch scheduler, crypto auto-refresh, and crypto WebSocket collector.

This is product-relevant behavior, but it makes tests, local smoke checks, and route-only imports more fragile. The safe optimization is a runtime coordinator/app-factory style boundary, not simply disabling defaults.

### P1 - Market payload contract helper logic is duplicated

`backend/app/ai/tools.py` and `backend/app/ai/agentic_tools.py` both carry payload-level parsing, intraday limit, slot envelope, compact market context, and slot status logic. This creates drift risk for MCP/frontend/Kuro consumers.

Recommended direction: extract a small shared `market_payload_contract` helper with regression tests, then migrate call sites one slice at a time.

### P1 - Market-family routers duplicate HTTP error and job enqueue patterns

US/JP/KR routers repeat similar `_fetch_error`, `_group_error`, `_item_error`, watchlist CRUD, watchlist resource refresh, and job enqueue logic. The duplication is now large enough that future market surfaces will copy inconsistent behavior.

Recommended direction: introduce shared router/service helpers for market-family watchlist errors and queued refresh request envelopes while preserving every public route.

### P2 - External HTTP policy is mostly present but not enforced uniformly

`backend/app/http_client.py` centralizes `requests.Session` with `trust_env` policy, but several modules directly import `requests` and provider-specific functions own timeout/error behavior. Some usage is only exception typing, but the contract is not yet mechanically enforced.

Recommended direction: document and enforce provider request helpers that always carry timeout, provider identity, source URL, error classification, and optional provider event recording.

### P2 - Source-health patterns are repeated per market

TW/US/KR/crypto/resource source-health modules already exist and are valuable. The repeated shape suggests a shared source-health entry contract could reduce drift, but this should happen after slot contract consolidation.

### P2 - DB transaction ownership is inconsistent by design but undocumented

Many services commit internally while routers pass a request-scoped session. This is common in the repo today, but long-running refresh, background jobs, and API writes need clearer service contracts: which functions commit, which only mutate, and which are idempotent.

### P3 - Large files should be split by responsibility, not by line count

The largest files are real hotspots, but line count alone is not a good refactor target. The safe split order is pure projection helpers first, then provider adapters/source-health projections, then route grouping. Avoid moving business logic just to make files smaller.

## Recommended execution order

1. Batch 0: validate/checkpoint current dirty worktree.
2. Batch 1: introduce runtime side-effect boundary.
3. Batch 2: consolidate AI market payload contract helpers.
4. Batch 3: extract market-family router/job enqueue helpers.
5. Batch 4: normalize provider HTTP/source-health policy.
6. Batch 5: split large service modules only where prior batches expose stable seams.

## Validation status

Ran minimal backend validation after writing this scan:

```powershell
.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs @('backend\tests\test_system_health.py') -SkipGitCheck -BackendTestTimeoutSeconds 120
```

Result:

- `backend compileall`: passed.
- `backend pytest backend\tests\test_system_health.py`: passed.
- Validation wrapper observed existing listeners on `3000` (`node`) and `8400` (`python`), so any later runtime smoke should confirm actual launcher-selected URLs before assuming fixed ports.

Also ran:

```powershell
git diff --check -- docs/agent-runs/backend-optimization-scan-20260711
```

Result: passed.

Recommended fuller Batch 0 baseline:

```powershell
.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs @(
  'backend\tests\test_ai_ask_stages.py',
  'backend\tests\test_ai_freshness_guard.py',
  'backend\tests\test_jp_market_data.py',
  'backend\tests\test_kr_market_data.py',
  'backend\tests\test_portfolio_holdings.py',
  'backend\tests\test_watchlist_radar_automation.py'
)
```

## Next step

Start with Batch 0. If it passes, implement Batch 1 as the first real backend optimization because it reduces test/runtime fragility before changing AI or market logic.
