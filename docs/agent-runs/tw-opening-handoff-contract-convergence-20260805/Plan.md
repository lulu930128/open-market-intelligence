# Plan

## Milestone status

| Milestone | Status | Evidence |
|---|---|---|
| M0 | completed | Approved planning baseline and task documents |
| M1 | completed | Consumer inventory, capability contract and deterministic resolver tests |
| M2-M4 | completed | Presentation/observation contract, same-session price retention, replay and bounded slots |
| M5-M7 | completed | Persisted intraday fallback, non-decision/NLU cleanup, freshness/source-health alignment |
| M8 | completed | Public snapshot compatibility, full backend suite and frontend production build |
| M9 | completed | Separate port/SQLite/locks, disabled background work, REST/OpenAPI/repo MCP smoke |
| Gate R | passed | Official tray restart and formal REST/frontend/repo MCP verification passed |
| M10 | in progress | Formal rollout passed; staged live-session acceptance remains pending |

## Approval gates

- **Gate P — Plan approval:** current gate. Before the user approves these documents, no source, test, schema, snapshot, scheduler, DB or runtime modification is authorized.
- **Gate S — Schema expansion:** default is no migration. If M2 proves a schema change is required, stop and submit a separate migration/backup/rollback proposal.
- **Gate R — Formal runtime rollout:** passed on 2026-08-05 after explicit approval, official tray restart, runtime identity checks, formal DB integrity/revision checks and representative REST/frontend/repo MCP verification.
- **Git gate:** commit and push always require separate explicit user instruction.

## Work packages

| Package | Scope | Priority | Primary issues |
|---|---|---|---|
| F | 08:00 presentation-session rollover, evidence-driven opening/closing handoff and usability axes | P0-T | HO-001, HO-005, HO-006, HO-007 |
| G | Same-session actual-trade retention | P0-T | HO-002 |
| H | Replay fidelity and boundary capture matrix | P0-E | HO-003, HO-004 |
| A | `prefer_live` persisted intraday cache fallback | P0-R | RT-001 |
| B | Non-decision outward payload cleanup | P0-R | RT-002 |
| C | Negation-aware matched-hint diagnostics | P1 | RT-003 |
| D | Canonical data-freshness aggregation | P1 | RT-004 |
| E | Source-health historical-event clarification | P2 | RT-005 |

## Milestones

### M0 — Freeze evidence baseline and approve direction

- Scope:
  - Preserve the 2026-08-05 formal runtime, raw persisted quote snapshots, replay output, DB rows, digest and dirty-worktree inventory as planning evidence.
  - Finalize `Prompt.md`, `IssueMap.md`, `AcceptanceMatrix.md`, `Plan.md` and `Progress.md`.
- Acceptance:
  - User can see goals, non-goals, hard constraints, P0 ordering, exact time cases, owners and stop conditions.
  - No implementation files or runtime state changed.
- Validation:
  - Strict UTF-8 readback.
  - Required headings and issue IDs present.
  - Markdown link/path check.
  - `git diff --check -- docs/agent-runs/tw-opening-handoff-contract-convergence-20260805`
- Exit gate:
  - Wait for explicit plan approval.

### M1 — Inventory consumers and define the canonical observation resolver

- Scope:
  - Re-read current source after approval; do not rely on planning-time line numbers.
  - Inventory all consumers of presentation/session date, automatic Frontend refresh, quote placeholders, auction, last trade, freshness and decision-usability fields.
  - Write deterministic failing tests for T01～T12 and T15～T19 before implementation.
  - Decide whether the pure resolver is a new module or a safe generalization of an existing market contract.
- Likely files:
  - `backend/app/market/trading_calendar.py` — market clock only; ideally no provider logic change.
  - `backend/app/market/quote_depth.py`.
  - `backend/app/market/tw_market_breadth_contract.py`.
  - New pure market resolver only if it removes real duplication.
  - `backend/tests/test_taiwan_stock_quote_depth.py`.
  - `backend/tests/test_market_index_daily_stats.py` or a focused new pure-contract test module.
- Acceptance:
  - Tests demonstrate the current 09:00 clock-only failure.
  - Resolver input/output and compatibility projection are documented in code/tests.
  - `trading_calendar.py` remains free of `z/pz/ps/ts` parsing.
  - Exact outward fields are additive or have a proven compatibility mapping.
- Validation:

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  backend\tests\test_taiwan_stock_quote_depth.py `
  backend\tests\test_market_index_daily_stats.py
```

- Stop-and-fix:
  - If consumer inventory reveals a breaking field dependency, stop and update the plan before changing meaning.

### M2 — Implement the 08:00 day rollover and evidence-driven opening/closing handoff

- Scope:
  - Implement package F.
  - On an authoritative Taiwan trading day, switch the backend-owned presentation session to today at 08:00 Asia/Taipei while keeping unavailable current-session numeric facts null.
  - Verify whether existing Frontend polling crosses the boundary; only if it does not, add one bounded 08:00 refetch and preserve null-to-`"-"` presentation without duplicating calendar logic.
  - Keep previous-session close/date separately labeled and do not call the quote provider solely to create the empty today-session frame.
  - Resolve market clock and provider/instrument phase separately.
  - Preserve trial evidence across a 09:00 request boundary when provider event/flags remain auction-indicative.
  - Apply symmetric delayed-close behavior through the official confirmation window.
  - Update AI temporal/semantic usability without turning fresh auction facts into execution-grade data.
- Likely files:
  - Pure market observation resolver.
  - `backend/app/market/quote_depth.py`.
  - `backend/app/ai/realtime_contract.py`.
  - `backend/app/ai/market_context/taiwan_projection.py`.
  - Existing Frontend market-date/refresh/presentation owner only if M1 proves the current behavior cannot meet T01～T03.
  - Related schemas/capability projection only if required.
- Acceptance:
  - T01～T10 and T15～T19 deterministic cases pass.
  - 07:59:59、08:00:00、08:01:00 and non-trading-day clock fixtures prove the rollover boundary in Asia/Taipei.
  - An already-open Frontend updates to today's session at 08:00 and renders unavailable current-session numeric fields as `"-"`; no provider event is created solely by the rollover.
  - `pz` remains auction-only.
  - `facts_usable` can be true while execution/price decision usability is false.
  - Existing breadth scope/coverage and index live/official separation remain unchanged.
- Validation:

```powershell
.\.venv\Scripts\python.exe -m compileall backend\app\market backend\app\ai
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  backend\tests\test_taiwan_stock_quote_depth.py `
  backend\tests\test_ai_realtime_contract.py `
  backend\tests\test_ai_market_context_projection.py `
  backend\tests\test_intraday_contract_remediation.py
```

- Stop-and-fix:
  - Any test or payload promotes auction indicative evidence to actual trade.
  - Any alias is reimplemented in Frontend/MCP/AI consumer code.

### M3 — Retain confirmed same-session actual trade without inventing price

- Scope:
  - Implement package G.
  - Reuse existing persisted quote rows or canonical intraday evidence to locate the latest confirmed current-session actual price.
  - Keep trade occurrence, price availability, price source and `price_as_of` separate.
  - Do not cross stock, market or trade date.
- Default design:
  - Query an existing current-session confirmed actual-trade row or consume an existing canonical helper.
  - Do not add migration or an unbounded in-memory truth store.
  - If no confirmed price exists, return explicit price-missing semantics even when cumulative volume/OHL prove trades occurred.
- Acceptance:
  - T11 and T12 pass with and without cache.
  - T14 13:24-style snapshots retain the original event time of any same-session cached price.
  - Provider failure fallback and normal `z="-"` behavior have distinct reason codes.
- Validation:

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  backend\tests\test_taiwan_stock_quote_depth.py `
  backend\tests\test_intraday_contract_remediation.py `
  backend\tests\test_ai_realtime_contract.py
```

- Stop-and-fix:
  - If authoritative `price_as_of` cannot be expressed with existing schema, stop at Gate S.

### M4 — Repair replay fidelity and fixed-slot acceptance coverage

- Scope:
  - Implement package H.
  - Preserve captured indicative evidence in replay.
  - Add captured/projected contract metadata only if required for old rows.
  - Add bounded slots `09:01`, `09:02`, `13:31`, `13:33`, subject to scheduler cost verification.
  - Preserve GET replay read-only behavior.
- Likely files:
  - `backend/app/market/quote_depth.py`.
  - scheduler registration owner for `TAIWAN_QUOTE_CONTRACT_SLOTS`.
  - quote replay schemas and tests.
  - `backend/tests/test_taiwan_stock_quote_depth.py`.
- Acceptance:
  - Saved and replayed `indicative_match_*` fields agree.
  - Existing 2026-08-05 rows no longer project contradictory semantics.
  - New slots are idempotent, deduped and bounded to the canary contract.
  - Replay returns `read_path_side_effects=false`.
- Validation:

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  backend\tests\test_taiwan_stock_quote_depth.py `
  backend\tests\test_api_contract_inventory.py
```

- Read-only API probe after isolated rollout:

```powershell
Invoke-RestMethod "http://127.0.0.1:<isolated-port>/api/market/quote-depth/2330/replay?trade_date=2026-08-05"
```

### M5 — Implement persisted intraday fallback

- Scope:
  - Implement package A / RT-001.
  - Split `intraday_requested`, `provider_refresh_allowed` and `cached_fallback_allowed`.
  - Permit `history(refresh=False)` when external fetch is denied and fallback is allowed.
  - Preserve a semantic difference between proactive policy cache use and provider-error fallback.
- Likely files:
  - `backend/app/ai/ask_execution.py`.
  - `backend/app/ai/market_context/taiwan_stock.py`.
  - Tests in `test_ai_decision_core.py`, `test_intraday_contract_remediation.py`, `test_ai_tool_boundaries.py`.
- Acceptance:
  - Persisted hit works under `prefer_live + external false + fallback true`.
  - Provider mock/event/telemetry prove no provider attempt.
  - Explicit `fallback_to_cached=false` remains respected.
- Validation:

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  backend\tests\test_ai_decision_core.py `
  backend\tests\test_intraday_contract_remediation.py `
  backend\tests\test_ai_tool_boundaries.py
```

### M6 — Clean non-decision payload and NLU diagnostics

- Scope:
  - Implement packages B and C / RT-002 and RT-003.
  - Keep technical evidence but remove actionable decision projection for quote/data-freshness modes.
  - Make effective matched hints negation-aware; preserve raw diagnostics only with explicit labeling.
- Likely files:
  - `backend/app/ai/decision_envelope.py` and v4 compatibility projection.
  - `backend/app/ai/decision_core.py`.
  - `backend/tests/test_ai_decision_envelope.py`.
  - `backend/tests/test_ai_decision_core.py`.
- Acceptance:
  - Data-only decision container is empty/non-actionable.
  - Entry/risk decision cases retain required levels and position semantics.
  - Negated risk/exit hints do not appear as effective matches.
- Validation:

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  backend\tests\test_ai_decision_envelope.py `
  backend\tests\test_ai_decision_core.py `
  backend\tests\test_ai_answer_composer.py
```

### M7 — Align canonical freshness and source-health diagnostics

- Scope:
  - Implement packages D and E / RT-004 and RT-005.
  - Keep temporal freshness, required availability, completeness and decision usability separate.
  - Qualify historical latest-event status/time so it cannot be read as current-row freshness.
- Likely files:
  - `backend/app/ai/data_quality_contract.py`.
  - `backend/app/ai/market_context/source_health_context.py`.
  - `backend/app/market/source_health.py` and provider health projection if canonical owner requires it.
  - capability/outward tests.
- Acceptance:
  - Required blocked/unavailable cases cannot aggregate to fully ready/current.
  - Historical provider errors remain visible without overriding a current healthy row.
  - No frontend hardcode is needed.
- Validation:

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  backend\tests\test_ai_capability_contract.py `
  backend\tests\test_ai_outward_contract.py `
  backend\tests\test_ai_market_context_projection.py `
  backend\tests\test_ai_supplemental_contexts.py `
  backend\tests\test_market_source_health.py
```

### M8 — Contract compatibility and full backend validation

- Scope:
  - Run API/consumer inventory again against final diff.
  - Update response schemas, public capability fields, MCP offline snapshot/digest and Frontend types only if outward fields changed.
  - Verify no unrelated migration, scheduler or dispatch behavior changed.
- Acceptance:
  - REST path/method/operation inventory remains compatible.
  - Public snapshot and live schema agree.
  - Frontend/MCP do not reproduce session or freshness logic.
  - All targeted regressions pass before full profile.
- Validation:

```powershell
.\scripts\run-safe-validation.ps1 -Profile backend
git diff --check
```

- Conditional Frontend validation:

```powershell
.\scripts\run-safe-validation.ps1 -Profile frontend
```

Run the frontend profile only if compiled Frontend source/types change; do not add browser/e2e unless an actual UI risk exists.

### M9 — Isolated runtime and public REST/repo MCP smoke

- Scope:
  - Use a separate port and separate SQLite copy/temporary DB.
  - Disable all schedulers, stock-master bootstrap, crypto auto-refresh/WS and external fetch.
  - Verify representative quote, replay, AI and MCP behavior without production DB mutation.
- Acceptance:
  - Contract version/digest match source.
  - T02/T07/T11/T12 replay or clock fixtures project correctly.
  - `prefer_live + external false + fallback true` produces persisted evidence without provider I/O.
  - Data-only decision payload is non-actionable.
  - Job/provider-event counts remain unchanged except explicitly seeded isolated evidence.
- Validation evidence to record:
  - Isolated PID/command/port.
  - DB path/revision/quick check.
  - Scheduler-disable environment.
  - REST responses.
  - Repo MCP `initialize -> tools/list -> omi.ask` protocol smoke.
  - Exact process shutdown.
- Exit gate:
  - Update `Progress.md`, report results and wait at Gate R.

### M10 — Formal launcher rollout and staged live acceptance

- Scope:
  - After Gate R, preflight formal DB read-only integrity/revision and current process ownership.
  - Restart only the official OMI-owned backend/frontend through the launcher flow.
  - Verify actual selected ports, PID/path/source identity, ready/health, public digest and representative outward response.
  - Run live acceptance at the next available Taiwan trading session.
- Time windows:
  - 07:59～08:01 presentation-session rollover; no MIS call solely for placeholder state.
  - 08:50～08:59 preopen auction.
  - 09:00～09:02 opening handoff using new fixed slots.
  - 09:05～09:20 stable intraday/cache/freshness.
  - 13:24～13:34 closing handoff and official close.
- Acceptance:
  - `AcceptanceMatrix.md` live rows are recorded surface by surface.
  - Conditions that do not naturally occur stay `not_observed`.
  - Any P0 failure triggers stop-and-fix before closeout.
- Read-only representative probes:

```powershell
Invoke-RestMethod "http://127.0.0.1:<selected-port>/api/system/health"
Invoke-RestMethod "http://127.0.0.1:<selected-port>/api/ai/tools"
Invoke-RestMethod "http://127.0.0.1:<selected-port>/api/market/quote-depth/2330/replay?trade_date=<date>"
Invoke-RestMethod "http://127.0.0.1:<selected-port>/api/system/provider-events?limit=20"
```

### M11 — Closeout and handoff

- Scope:
  - Update issue status, validation evidence, live/not-observed matrix and known limitations.
  - Summarize changed files and diff scope.
  - Do not commit/push unless explicitly requested.
- Acceptance:
  - No outstanding required work is hidden.
  - Production DB, provider calls, runtime changes and public contract changes are auditable.
  - Remaining limitations have owner, reason and next verification window.

## Stop-and-fix rules

- If 08:00 uses Frontend-local trading-day logic, reuses yesterday's value as today's price, encodes unavailable numeric facts as zero/string, or triggers provider I/O solely for rollover, stop and fix the backend contract boundary.
- If a weekend/holiday becomes today's active trading session at 08:00, stop and fix authoritative calendar gating.
- If a test, replay or public payload promotes `pz` to actual trade, stop immediately and fix the canonical market owner.
- If time alone changes individual-security auction applicability or actual-trade status, stop and return to the resolver contract.
- If same-session cache loses `price_as_of`, crosses a trade date or derives price from non-trade evidence, stop.
- If replay output differs from stored public evidence without explicit version metadata, stop.
- If `allow_external_fetch=false` produces a provider call/event, stop and fix policy boundaries.
- If GET replay/read paths write DB or enqueue jobs, stop.
- If implementation unexpectedly needs a migration, stop at Gate S; do not add an ad hoc column.
- If a public field meaning must break compatibility, stop and present consumer impact/transition plan.
- If targeted tests fail, do not proceed to full validation.
- If full backend validation fails, isolate and fix task-related failures before runtime work.
- If isolated runtime identity, DB path or scheduler-disable state is uncertain, do not start smoke.
- If formal runtime path/PID/port/digest differs from validated source, classify `runtime_drift` and stop live acceptance.
- If a P0 live-session case fails, do not mark the project complete even if all deterministic tests pass.
- If dirty-worktree overlap makes an exact localized diff unsafe, stop and report the overlapping files.

## Decisions

- 2026-08-05：On an authoritative Taiwan trading day, OMI changes its presentation session to today at 08:00 Asia/Taipei; until current-session facts arrive, backend numeric values remain null and Frontend displays `"-"`.
- 2026-08-05：The 08:00 product rollover is not TWSE preopen; it must not imply auction/live data, manufacture a provider event, or apply on weekends/holidays.
- 2026-08-05：Previous close may remain only as a separately dated reference; an already-open screen must cross the 08:00 boundary without manual reload.
- 2026-08-05：P0 transition truth and evidence integrity precede the original A/B packages because 8/5 persisted runtime evidence confirmed real boundary defects.
- 2026-08-05：Market clock, instrument phase and observation semantics are separate axes; `trading_calendar.py` remains the market-clock owner.
- 2026-08-05：`pz` is auction-only and never an actual-trade fallback.
- 2026-08-05：Same-session actual-trade retention must preserve original event time; volume/OHL without price remain price-missing.
- 2026-08-05：Replay is a public acceptance surface and must preserve persisted evidence.
- 2026-08-05：No migration by default; no broad search for delayed-open securities.
- 2026-08-05：Formal runtime rollout occurs only after targeted/full validation, isolated smoke and Gate R.
- 2026-08-05：Gate R passed on launcher-selected backend `8400` and frontend `3270`; exact live-session windows remain a separate acceptance stage.
