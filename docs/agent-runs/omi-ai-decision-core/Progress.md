# Progress

## Status

- Current phase: outward contract implemented and regression-validated; live restart and fixed-condition performance benchmark pending
- Last updated: 2026-07-19 22:49 +08:00

## Completed

- Read `$productized-project-workflow` skill and `references/task-doc-templates.md`.
- Read OMI repo-level `AGENTS.md`.
- Confirmed `docs/agent-runs` did not previously exist in this repo.
- Inspected OMI AI-related structure:
  - `backend/app/ai/decision_core.py`
  - `backend/app/ai/decision_engine.py`
  - `backend/app/ai/answer_composer.py`
  - `backend/app/ai/ask.py`
  - `backend/app/ai/ask_execution.py`
  - `backend/app/ai/schemas.py`
  - `backend/app/ai/freshness.py`
  - `backend/app/ai/agentic_tools.py`
  - `backend/app/routers/ai.py`
  - `agents/omi_mcp_server/server.py`
- Inspected representative regression tests:
  - `backend/tests/test_ai_decision_core.py`
  - `backend/tests/test_ai_answer_composer.py`
  - `backend/tests/test_ai_freshness_guard.py`
- Created initial task docs:
  - `docs/agent-runs/omi-ai-decision-core/Prompt.md`
  - `docs/agent-runs/omi-ai-decision-core/Plan.md`
  - `docs/agent-runs/omi-ai-decision-core/Progress.md`
- Added pre-implementation planning references:
  - `docs/agent-runs/omi-ai-decision-core/ContractMap.md`
  - `docs/agent-runs/omi-ai-decision-core/BaselineTestsAndGaps.md`
- 2026-07-07: Ran the minimal AI contract baseline through the repo safe-validation wrapper; backend compileall, targeted pytest, and diff check passed.
- 2026-07-07: Added `backend/app/ai/decision_contract.py` as an additive `analysis.decision_contract` v1 projection.
- 2026-07-07: Wired `decision_contract` into `ask_response_stage.assemble_response_analysis` after backend `human_answer` is built.
- 2026-07-07: Added regression coverage confirming `decision_contract` includes intent, target, answer source/style, normalized sections, readiness flags, freshness, missing, and warnings.
- 2026-07-19: Hardened Taiwan stock resolution so position cost tokens do not become stock ids, conflicting explicit targets require clarification, and inactive/unknown master symbols return `TARGET_NOT_FOUND` before evidence execution.
- 2026-07-19: Added canonical `next_context.last_target` output while preserving `last_resolution` and related input aliases for existing OMI Dock/MCP callers.
- 2026-07-19: Added long-side price-level invariants. Above-market pullback zones are reclassified as resistance, invalid stops/invalidation levels are omitted, and executable decision output is blocked when entry and risk guardrails are not both valid.
- 2026-07-19: Added `backend/tests/test_ai_p0_safety.py` with 15 focused P0 regressions.
- 2026-07-19: Saved the completed P0 safety slice as commit `d863b14` (`fix(ai): harden P0 decision safety`).
- 2026-07-19: Separated table availability from release-calendar freshness. Taiwan monthly revenue now uses a conservative market-wide filing boundary, and table evidence exposes `availability`, `freshness`, `expected`, and `row_count` independently.
- 2026-07-19: Preserved `target.market` for `data_freshness` across Ask normalization, backend execution, the public API, tool catalog, and MCP. TW/US/JP/KR/CRYPTO/ALL now route to market-owned readers; unsupported explicit markets return `UNSUPPORTED_MARKET` instead of silently falling back to TW.
- 2026-07-19: Split US selected-provider freshness from fallback-provider health. Canonical daily selection reuses the existing chart provider rule; a stale Alpha Vantage fallback remains visible without downgrading current Yahoo evidence to stale.
- 2026-07-19: Enforced `max_total_seconds` as a response wall-clock deadline. Timeout runs return `status=timeout`, request cooperative cancellation, distinguish market-cache writes from user-data writes, and explicitly report cached fallback state.
- 2026-07-19: Added `backend/tests/test_ai_p1_reliability.py` for P1 freshness, market routing, provider selection, and timeout/fallback regressions.
- 2026-07-19: Closed P2 intraday semantics: closed, waiting, opening, stale-session, or zero-point evidence no longer produces a valid intraday score; an intraday request falls back explicitly to `short` / `daily` with `horizon_fallback_reason`.
- 2026-07-19: Separated full-market breadth from OMI sample rankings in both field names and human labels. Sample leaders now expose additive `sample_*` aliases and include the tracked sample count in user-facing sections.
- 2026-07-19: Added MCP `include_raw=false` as a bounded transport projection while preserving `include_raw=true` as the backward-compatible default.
- 2026-07-19: Split quarterly financial accounting period, source-declared release/filing dates, and raw fetch time. Migration `20260719_0037` clears known MOPS history rows whose fetch date polluted `report_date`.
- 2026-07-19: Added dedicated `broker_branch` and `data_freshness` intents, removed duplicated status labels, changed empty target fallback to `市場`, and aligned US bearish titles with the shared negative-score threshold.
- 2026-07-19: Added `backend/tests/test_ai_p2_semantics.py` and expanded MCP, market-brief, and migration regression assertions.

## Validation evidence

- `rg --files backend/app/ai`: confirmed AI modules are already split into decision, answer, freshness, orchestration, stage, schema, and tool modules.
- `git status --short --untracked-files=all`: before creating task docs, only `agents/omi_mcp_server/README.md` and `agents/omi_mcp_server/server.py` were modified from the previous prompt/tool-policy work.
- `Test-Path docs\agent-runs`: returned `False` before this task; this is the first OMI long-task doc set.
- Static inspection found the downstream Kuro `market_preflight.py` fallback still points to `http://127.0.0.1:8300`; this is recorded as a downstream planning gap and was not changed in this pass.
- `.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs @('backend\tests\test_ai_decision_core.py','backend\tests\test_ai_answer_composer.py','backend\tests\test_ai_freshness_guard.py','backend\tests\test_ai_ask_stages.py','backend\tests\test_omi_mcp_server.py')`: passed.
- `.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs @('backend\tests\test_ai_ask_stages.py','backend\tests\test_ai_answer_composer.py')`: passed after adding `decision_contract`.
- `.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs @('backend/tests/test_ai_p0_safety.py','backend/tests/test_ai_ask_refactor_modules.py','backend/tests/test_ai_decision_core.py','backend/tests/test_ai_technical_analysis.py','backend/tests/test_ai_decision_engine.py','backend/tests/test_ai_answer_composer.py','backend/tests/test_ai_ask_stages.py','backend/tests/test_ai_market_payload_contract.py','backend/tests/test_ai_freshness_guard.py','backend/tests/test_ai_supplemental_contexts.py','backend/tests/test_omi_mcp_server.py')`: 174 passed on 2026-07-19.
- `.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs <P0/P1 + decision core + MCP + TW/US/JP/KR market set>`: compileall passed, 321 tests passed, and `git diff --check` passed on 2026-07-19; logs: `.tmp/validation/20260719-194941`.
- Current-code local DB smoke (no external refresh): TW 2330 monthly revenue `2026-04-01` is `availability=available`, `freshness=stale`, expected `2026-06-01`, and the human answer names the stale domain; US freshness keeps `market=US`; NVDA selects `yahoo_chart/current` while Alpha Vantage remains a stale fallback and the main passport remains `current`; ALL returns distinct TW/US/JP/KR/CRYPTO market states.
- `run-safe-validation.ps1 -Profile backend` passed compileall, 230 targeted P0/P1/P2 tests, and `git diff --check`; logs: `.tmp/validation/20260719-202149`.
- Migration regression explicitly downgraded a temporary SQLite database to `20260718_0036`, inserted one contaminated MOPS-history row and one legitimate source-date row, then upgraded to head and verified only the known fetch-date pollution was cleared.

## Decisions made

- Start with OMI AI decision core before Kuro OMI briefing because OMI owns market reasoning, freshness, tool orchestration, and answer contract.
- Keep this first pass as task documentation and planning scaffold only; do not change AI runtime behavior until the baseline contract and regression map are explicit.
- Treat `backend/app/ai/answer_composer.py` as the primary user-facing wording/structured-answer layer; frontend and MCP should consume, not reconstruct, the decision.
- Treat bounded external refresh as backend-owned OMI behavior through `allow_external_fetch`, `tool_budget`, `refresh_policy`, `tool_plan`, and `tool_runs`.
- Add `analysis.decision_contract` as a normalized projection instead of moving or rewriting `analysis.human_answer`; this keeps existing callers compatible while giving Kuro/frontend a stable structured surface.
- Keep P0 response changes additive: `ok`, `error`, and `next_context` extend `omi.ai.ask.v2`; existing response fields remain in place.
- Treat invalid target identity and invalid directional price levels as hard answer-readiness boundaries, not wording-only warnings.
- Treat availability, release-calendar freshness, and provider health as separate facts. A row existing in SQLite does not make it current, and an unused fallback provider does not define selected-evidence freshness.
- Treat full-market breadth and OMI sample rankings as separate scopes. Legacy ranking keys remain for compatibility, but new consumers should prefer `sample_*` fields and display the sample count.
- Treat `include_raw` as an MCP transport concern only. It may reduce payload size but may not bypass backend evidence construction, freshness checks, or trust policy.
- Treat financial `period`, `released_at`, `filed_at`, and `raw_fetch_result.fetched_at` as distinct clocks; unknown source dates remain `null` rather than borrowing fetch time.
- `allow_write` continues to gate report/memory or other user-data persistence. Allowed bounded external refresh may write market cache independently and is exposed as `writes_market_cache`, not as a user-data write.
- A hard response deadline may return while a currently blocking provider call finishes in a daemon worker; the run exposes `cancellation_requested` and `background_completion_possible`, while Taiwan multi-step refreshes stop cooperatively at the next cancellation boundary.
- Do not run the baseline test subset as part of this documentation-only pass; record the exact commands in `BaselineTestsAndGaps.md` for the first implementation session.

## Known issues / risks

- The listener already running on `127.0.0.1:8400` was not restarted, so HTTP smoke would exercise pre-change code. P1 used current-code direct DB smoke instead; restart and live API verification remain before publishing.
- The first implementation milestone may reveal existing test failures unrelated to the decision-core work; those must be isolated before code changes continue.
- Kuro still has a downstream fallback URL gap recorded in `ContractMap.md`; this implementation slice does not modify Kuro.
- `decision_contract` v1 is intentionally a projection. Consumer adoption in OMI Ask UI and Kuro remains a follow-up.

## Next step

- Continue outward-contract implementation with cross-consumer regression and live runtime smoke after restart.

## 2026-07-19 outward-contract implementation

- Added `query_plan.py` and a true Taiwan quote-only reader. Quote-only execution now calls identity, latest daily quote, and scoped quote freshness only; technical, broker, fundamentals, chips, cross-market, intraday, and provider refresh paths are explicitly excluded.
- Added independent `payload_level` and `diagnostics_level` request/response dimensions while preserving legacy request modes.
- Added layered readiness fields and changed price-level safety handling from whole-answer blocking to unsafe-section blocking.
- Removed Human Answer, reasoning, position decision, and decision contract from public `data_only` projections; deterministic derived evidence remains available.
- Fixed explicit market resolution to preserve `target.market`.
- Split slot availability from freshness additively while keeping the legacy slot `status` field.
- Made selected technical score/title/summary derive from the same aggregate score model; original timeframe title/summary remain available as additive detail.
- Updated both MCP adapters so backend business failure drives `isError`; successful empty results remain non-errors. Removed the external `OMI_search` hardcoded success projection.
- Added detached timeout job metadata, a capability-aware dedupe request, request deadline/cancellation fields, and public job status projection.
- Added canonical position math that reads the scoped compact quote, preserves cost/latest/return through safety blocking, and blocks only unsafe price-level or trading-action sections.
- Added a dedicated broker-branch reader and freshness path so broker queries do not load or inherit warnings from monthly revenue, fundamentals, technicals, chips, or unrelated providers.
- Added market-breadth answer semantics, selected-provider/fallback-provider separation, slot `usability`, stable float display, and response-finalizer preservation of assembly-declared sections.
- Hardened detached job completion so production file-backed SQLite uses an independent worker session while in-memory regression sessions are finalized on the owning thread; this removed cross-thread `no such table: job_run` warnings.
- Focused regression: 105 outward-contract, timeout, freshness, semantics, overnight-impact, and slot tests passed.
- Full backend validation: compileall passed, all 790 backend tests passed without unhandled-thread warnings, and `git diff --check` passed; logs: `.tmp/validation/20260719-224639`.
- Main-repo MCP behavior is covered by the full backend suite. External `C:\GPT_MCPtool\OMI_search` discovery tests passed 23/23, and downstream Kuro `market_preflight` plus `tool_policy_omi` tests passed 12/12.

## Remaining verification boundary

- The 70% serialized-byte reduction and 50% warm-cache p50 latency reduction remain experimental targets, not completed claims. They still require a fixed query, target, date range, DB snapshot, cache state, run count, reader/provider counters, p50, and p95 measurement after the updated runtime is restarted.
- The currently listening backend on port 8400 predates these changes, so HTTP smoke against it would not validate the new code. No running service was restarted in this implementation pass.
- ChatGPT MCP and Kuro contract compatibility are covered by adapter/downstream regression tests; a final live consumer smoke remains appropriate after restart.
