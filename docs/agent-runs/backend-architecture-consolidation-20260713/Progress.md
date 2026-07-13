# OMI Backend Architecture Consolidation Progress

## Status

- Program state: implementation, verification and checkpoint commit completed.
- Current phase: M9 convergence completed.
- Last updated: 2026-07-13 10:12 Asia/Taipei.
- Baseline branch: `codex-kr-market-readiness`.
- Baseline commit: `910a1caf3c88e6aeee217a03067dc3efddb8b827`.
- Baseline worktree: clean at planning start.
- Branch relation at planning start: ahead of `origin/codex-kr-market-readiness` by 5 commits.
- Checkpoint commit: `1a4e847 refactor: consolidate backend architecture boundaries`.

## Milestone tracker

| Milestone | Status | Last good commit | Validation |
| --- | --- | --- | --- |
| M0 Baseline and contract inventory | completed | `910a1ca` | `547 passed, 1 warning`; inventories validated |
| M1 Taiwan index provider boundary | completed | working tree | `556 passed, 1 warning` |
| M2 Transaction ownership map | completed | working tree | `175 passed`; five-market owner contract |
| M3 Market service façades | completed | working tree | `115 passed`; US/JP/KR chart projections |
| M4 Crypto/resource audit | completed | working tree | `86 passed, 1 warning`; REST provider boundaries |
| M5 AI answer composer pure modules | completed | working tree | targeted AI contract suite passed |
| M6 AI tool context projections | completed | working tree | targeted AI tool/projection suite passed |
| M7 Router/API regrouping | completed | working tree | `28 passed`; OpenAPI contract unchanged |
| M8 Conditional DB model decision | completed | working tree | Option A; `6 passed`; metadata contract protected |
| M9 Convergence and final verification | completed | working tree | `580 passed, 1 warning`; 9/9 runtime probes HTTP 200 |

Allowed status values for future updates: `pending`, `in_progress`, `blocked`, `completed`, `deferred`.

## Completed before this program

- Historical backend scan and Batches 0-5 are recorded under `docs/agent-runs/backend-optimization-scan-20260711/`.
- Runtime side effects were moved behind `backend/app/runtime.py` lifecycle coordination.
- AI payload-level/slot helpers were consolidated in `backend/app/ai/market_payload_contract.py`.
- US/JP/KR router error and refresh enqueue patterns received a shared helper slice.
- Provider HTTP context/error classification and source-health primitives were consolidated.
- JP source-health parity and `availability_only` behavior were added.
- US/JP/KR provider IO ownership was moved into explicit provider modules.
- Provider adapter compatibility and context are covered by `backend/tests/test_market_provider_adapters.py`.
- Checkpoint commit `910a1ca` was created with a clean worktree.

## Planning completed in this program

- Created `Prompt.md` with goal, non-goals, hard constraints, scope, deliverables and done criteria.
- Created `Plan.md` with M0-M9 dependency order, slices, acceptance criteria, validation matrix, commit strategy and stop rules.
- Chose Taiwan index provider separation as the first implementation milestone after inventory.
- Made DB model splitting conditional on metadata/migration/import evidence.
- Preserved legacy wrappers and public seams as an explicit compatibility strategy.

## M0 completed in this program

- Reran the full backend baseline from commit `910a1ca` before production edits.
- Created `ArchitectureMap.md` with route, service, provider IO and dependency-boundary inventories.
- Created `CompatibilityMatrix.md` with public route, private wrapper, monkeypatch and consumer seams.
- Created `TransactionOwnership.md` with current commit/rollback/refresh ownership and target policies.
- Counted 325 FastAPI route decorators across 18 router modules.
- Counted 78 ORM model classes and 33 Alembic revisions; the latest revision is `20260709_0033_portfolio_holdings.py`.
- Confirmed that Taiwan provider IO is spread across `indices.py` and several stateful refresh/backfill modules, so M1 begins with the stateless index transport boundary and preserves stateful exceptions.
- Confirmed that transaction movement must follow explicit service-by-service decisions rather than a mechanical shared abstraction.

## M1 completed in this program

- Added `backend/app/market/providers/` for TWSE OpenAPI/RWD/5-second index, TPEX, TWSE MIS, Yahoo, nStock and TAIFEX read paths.
- Routed provider calls through `ProviderRequestContext(market="tw", provider, resource, target)` and bounded timeout handling.
- Removed direct `app.http_client` imports from the six inventoried Taiwan stateless read modules.
- Added `backend/app/market/index_parsers.py` for pure normalization and TWSE/TPEX market-daily parsing.
- Kept `indices.http_get`, `_fetch_json` and existing `_fetch_*` names as compatibility seams.
- Kept cache, fallback, DB coverage and transaction behavior in the existing service owners.
- Added nine adapter/parser/compatibility tests.

M1 validation:

- Targeted Taiwan/provider suite: `56 passed`.
- Full backend: `556 passed, 1 warning`.
- Full logs: `.tmp/validation/20260713-081445`.
- `git diff --check`: passed.

## M2 completed in this program

- Added five-market transaction characterization covering Taiwan, US, JP, KR and crypto.
- Added rollback-and-re-raise behavior to representative TW/US/JP/KR commit owners; crypto already matched the policy.
- Confirmed a representative Taiwan query helper does not commit or rollback.
- Kept transaction-owning refresh functions in their current service files for the first M3 extraction.

M2 validation:

- Targeted transaction and market regression: `175 passed`.
- Logs: `.tmp/validation/20260713-081914`.
- `git diff --check`: passed.

## M3-M4 completed in this program

- Extracted DB-write-free OHLC aggregation/projection into US, JP and KR `chart_projection.py` modules.
- Kept service entrypoints and private patch names bound through the original service façades.
- Kept refresh, cache and transaction ownership in the original market services.
- Added crypto and resource REST provider namespaces with bounded request context; realtime/WebSocket lifecycle and persistence were not moved.
- Preserved legacy `_request_json` and `fetch_yahoo_chart_payload` wrappers as compatibility seams.

M3-M4 validation:

- Market projection targeted suite: `115 passed`.
- Crypto/resource targeted suite: `86 passed, 1 warning`.
- Full backend after M4: `567 passed, 1 warning`.
- Logs: `.tmp/validation/20260713-082510`, `.tmp/validation/20260713-082755`, `.tmp/validation/20260713-082826`.

## M5-M6 completed in this program

- Extracted answer localization/text projection into `answer_localization.py`.
- Extracted source-health/data-limit classification and confidence caps into `answer_data_limits.py`.
- Extracted scenario, counter-evidence and position projections into `answer_scenarios.py`.
- Kept high-level question-aware, watchlist and digest assembly in `answer_composer.py`, with compatibility re-exports for moved private names.
- Added shared AI market-context projection for source refs, timestamps, freshness, resource counts and compact slots/context.
- Kept tool registry, schemas, budget, planner and execution policy in their existing façades.

M5-M6 validation:

- Answer composer and pure-module regressions passed.
- AI tool/context projection regressions passed.
- Logs: `.tmp/validation/20260713-084314`, `.tmp/validation/20260713-084655`.

## M7-M8 completed in this program

- Moved the five Taiwan index routes to `routers/tw_market_indices.py`.
- Included the subrouter from `routers/market.py` and re-exported handler names to preserve import identity.
- Confirmed 326 total OpenAPI operations, 325 under `/api/*`, with unchanged operation IDs and response models for all five moved routes.
- Chose DB model Option A: keep one `db/models.py` and one `Base.metadata` registry.
- Recorded the evidence in `DatabaseModelDecision.md`: 103 model consumers, 78 tables/mappers, 45 foreign keys, 677 indexes, 184 constraints and direct Alembic metadata coupling.
- Added contract tests for route inventory, handler identity, ORM registry/table count and foreign-key resolution.

M7-M8 validation:

- Router/OpenAPI targeted suite: `28 passed`.
- DB model and migration contract suite: `6 passed`.
- Logs: `.tmp/validation/20260713-095834`, `.tmp/validation/20260713-100011`.

## M9 completed in this program

- Repeated the direct HTTP ownership scan. Remaining direct transport is intentional: generic connectors, LLM transport, stateful backfill/history/futures workflows and the canonical provider HTTP layer.
- Removed unused imports found during the final static scan without deleting compatibility façade aliases.
- Ran the complete backend safe-validation profile against the final working tree.
- Started the current-code FastAPI app in an isolated process with lifespan disabled and no migration, scheduler or provider refresh.
- Probed nine read-only endpoints covering health, Taiwan calendar, US/JP/KR stocks, crypto/resource provider contracts, AI tools and OpenAPI; all returned HTTP 200.
- Confirmed all five Taiwan index paths remained present in runtime OpenAPI, then stopped and verified cleanup of the isolated process.

M9 validation:

- `backend compileall`: passed.
- `backend pytest backend/tests`: `580 passed, 1 warning in 75.86s`.
- `git diff --check`: passed.
- Full logs: `.tmp/validation/20260713-100213`.
- Runtime smoke: 9/9 read-only probes passed on isolated port `43213`.

## Baseline validation evidence

Fresh M0 full backend validation:

```powershell
.\scripts\run-safe-validation.ps1 -Profile backend -BackendTestTimeoutSeconds 600
```

Result:

- `backend compileall`: passed.
- `backend pytest backend/tests`: `547 passed, 1 warning`.
- `git diff --check`: passed.
- Validation logs: `.tmp/validation/20260713-075524`.
- Warning: existing Python 3.12 SQLite datetime adapter deprecation from SQLAlchemy test execution.

Provider-boundary targeted evidence:

- `backend/tests/test_market_provider_adapters.py`: `12 passed`.
- US/JP/KR market targeted regressions passed before checkpoint commit.

This is the implementation baseline for M1. Any M1 production change must add targeted provider tests and rerun the full backend profile before the milestone is closed.

## Planning document validation

Docs-only checks completed on 2026-07-13:

- Strict UTF-8 readback passed for the new program docs and updated historical pointers.
- No Unicode replacement characters were found.
- No trailing whitespace or extra blank line at EOF was found.
- All referenced core files and targeted test paths exist in the current checkout.
- `git diff --check` passed for tracked documentation changes.
- Backend tests were not rerun because this planning turn changed documentation only; the latest code baseline remains the previously completed `547 passed, 1 warning` run.

## Decisions made

- Treat this as a separate long-running program rather than extending the historical scan indefinitely.
- Use `docs/architecture/BackendArchitecture.md` as durable architecture truth; task docs record execution state and evidence.
- Keep Taiwan first in execution order.
- Move provider IO and pure projection before transaction-owning service logic.
- Keep service modules as compatibility façades during decomposition.
- Preserve tests that patch private `_fetch_*` seams until each seam has an explicit migration decision.
- Use one main responsibility per commit and run full backend after every cross-module slice.
- Do not run live providers, paid quota, backfill or write-heavy smoke by default.
- Keep the DB model registry consolidated because M8 evidence does not support a low-risk split.
- Keep intentionally stateful provider workflows separate from stateless REST adapters.
- Treat high-level AI assembly and tool execution as façades; only move pure leaf projections with characterization coverage.

## Known issues / risks

### Current architecture risks

- US/JP/KR service façades remain large because transaction-owning refresh, watchlist, fundamentals and resource workflows were deliberately not split together with pure chart projection.
- `answer_composer.py` still owns high-level question-aware, watchlist and digest assembly. Further movement requires semantic answer characterization, not line-count-driven extraction.
- `ai/tools.py` and `ai/agentic_tools.py` still own registry/planner/budget/execution policy; shared market-context projection is extracted, but execution policy should remain centralized until a separate contract exists.
- `db/models.py` remains large by decision. Import density, foreign-key resolution and Alembic metadata coupling make a cosmetic split higher risk than value.
- Planned or optional provider capabilities remain unavailable by design, including JP disclosures, KR planned resources, optional CoinGlass paths and the unimplemented KGI futures slot. They are not exposed as completed default capabilities.

### Validation and runtime risks

- Compatibility wrappers and re-export aliases are still required by current tests and consumers; they should only be removed after a zero-consumer inventory.
- Exact AI wording remains a compatibility surface. Future high-level composer movement needs broader characterization than the pure-module tests added here.
- Transaction policy is characterized across representative TW/US/JP/KR/crypto owners, but not every legacy owner has been normalized. New ownership movement must add an explicit commit/rollback test.
- Runtime ports are launcher-selected. The final smoke used an isolated current-code port rather than assuming `8400`/`3000`.
- Full backend has one known Python 3.12 SQLite datetime adapter deprecation warning from SQLAlchemy test execution; this is the clearest bounded follow-up cleanup.
- Frontend validation was not run because no frontend file or public OpenAPI contract changed.
- Git has reported many unreachable loose objects during auto packing. Repository pruning is not part of this program unless separately requested.

### Scope risks

- A "big cleanup" can become an unreviewable rewrite if multiple responsibility groups are moved together.
- Cross-market abstractions can erase legitimate market differences; reuse must follow contract evidence.
- Removing wrappers early can break routers, jobs, AI tools, tests or external consumers even when runtime behavior appears unchanged.

## Resume checklist

At the start of every continuation:

1. Read `Prompt.md`, `Plan.md`, `Progress.md`.
2. Run `git status --short --branch` and `git log -1`.
3. Check whether HEAD still descends from the recorded last good commit.
4. Inspect new user/other-process changes; do not revert them.
5. Re-read the milestone's actual entrypoints and tests.
6. Update current phase and last-updated timestamp.
7. Run the minimum baseline required by that milestone.
8. Stop if the baseline is already failing or the worktree scope is ambiguous.

## Next step

The architecture consolidation was committed as `1a4e847`. Follow-up hardening is tracked in `docs/agent-runs/backend-hardening-convergence-20260713/`.
