# OMI AI Decision Core Contract Map

Last updated: 2026-06-21 20:20 +08:00

本文件是後續開工前的 baseline map。它描述目前 OMI AI decision core 的主要 contract、責任邊界與不能破壞的欄位；不是新規格替代品。

## Public Entry Points

### Backend API

- `POST /api/ai/ask`
  - Router: `backend/app/routers/ai.py`
  - Request model: `AiAskRequest`
  - Response model: `AiAskResponse`
  - Purpose: public OMI AI ask contract for frontend, MCP, Kuro, and future callers.

- `POST /api/ai/ask/stream`
  - Router: `backend/app/routers/ai.py`
  - Purpose: streaming status, evidence, deltas, final result for UI/Kuro progress surfaces.

### MCP Adapter

- `agents/omi_mcp_server/server.py`
  - Public tools: `omi.ask`, `omi.ask_stream`
  - Adapter boundary: thin HTTP client to backend API.
  - Must not import DB, duplicate market logic, or call market-data providers directly.

## Trust Boundary

### Server Policy

Source:

- `backend/app/routers/ai.py`
- `backend/app/ai/ask_policy.py`

Behavior:

- `caller_profile` is only a label.
- Server trust is decided by:
  - `x-omi-ai-trust-token`
  - backend config token match
  - local trusted client allowlist
- Trusted policy controls:
  - `can_call_llm`
  - `can_write`
  - `can_external_fetch`

Hard rule:

- Client-supplied `allow_llm`, `allow_write`, and `allow_external_fetch` must never bypass server-side policy.

## Request Contract

Source: `backend/app/ai/schemas.py`

Core fields:

- `contract_version`
  - Current default: `omi.ai.ask.v2`
- `question`
  - User request, max 4000 chars.
- `target`
  - Usually `{ "type": "auto" }` for external callers.
  - Specific targets can include `tw_stock`, `tw_index`, `tw_futures`, `us_stock`, `watchlist`, or other supported types.
- `mode`
  - `auto`, `data_only`, `brief`, `full`, `analysis`, `report`.
  - `brief` is the compact human summary plus key numbers; `data_only` is compact structured core data where available; `full` returns the complete evidence pack.
  - `report` is trusted/write-sensitive and should not be requested by Kuro default policy.
- `allow_llm`
  - Enables non-persistent LLM analysis only when server policy permits.
- `allow_write`
  - Required for persistent reports/memory-like side effects.
  - Must remain false for Kuro default flow.
- `allow_external_fetch`
  - Allows backend-owned bounded external fetch.
  - Does not authorize frontend/MCP/Kuro to call market APIs directly.
- `market_data_params`
  - Optional bounded market-data shape controls.
  - Current shared controls include `include_intraday`, `payload_level`, `intraday_limit`, and MCP transport-only `include_raw`.
  - `include_raw=false` returns a bounded MCP projection with the human answer, selected decision fields, compact evidence status, and notable timeout/fallback runs; it omits full result packs and raw provider payloads.
  - Frontend/MCP/Kuro may request a smaller or richer payload, but backend owns freshness, slot status, provider policy, and final projection.
- `tool_budget`
  - Controls maximum calls, external fetches, and total seconds.
- `refresh_policy`
  - Default: `stale_first`, `before_answer=true`, `fallback_to_cached=true`.
- `strategy_profile`
  - Current examples include `short_term_momentum` and `technical_swing`.
- `analysis_horizon`
  - `auto`, `intraday`, `short`, `swing`, `long`.
- `conversation_context`
  - Caller context such as Kuro route text or the previous OMI target.
  - Canonical follow-up field: `last_target`.
  - Compatibility aliases: `last_resolution`, `previous_resolution`, `previous_target`, and `target`.

## Response Contract

Source: `backend/app/ai/schemas.py`

Top-level fields that downstream callers should treat as stable:

- `kind`
- `contract_version`
- `ok`
- `question`
- `target`
- `mode`
- `action`
- `strategy_profile`
- `caller_profile`
- `resolution`
- `next_context`
- `clarification`
- `next_actions`
- `answer_ready`
- `report_level`
- `analysis`
- `policy`
- `tool_plan`
- `tool_runs`
- `result`
- `freshness`
- `missing`
- `warnings`
- `source_refs`
- `evidence_passport`
- `error`

Target safety rule:

- A Taiwan stock must resolve to an active `stock_master` row before evidence tools run.
- Unknown targets return `ok=false`, `answer_ready=false`, and `error.code=TARGET_NOT_FOUND` without refresh actions or analysis.
- Successful responses expose `next_context.last_target` for the next follow-up turn.
- Directional price levels expose backend validation; executable decision answers are blocked when valid entry and risk guardrails are not both available.

Backward compatibility rule:

- New fields should be additive.
- Existing fields should not change type without a version bump or compatibility shim.
- Frontend/Kuro should prefer optional-field tolerant parsing.

Related productized payload design:

- `docs/agent-runs/productized-market-payload-contract/ContractDesign.md`
  - Defines `payload_level`, canonical market data slots, slot status values, and the migration path for ChatGPT Web / MCP / Kuro consumers.

## 財務日期語意

- `financial_metric_quarterly.period` / `fiscal_year` / `quarter` identify the accounting period.
- `released_at` and `filed_at` are source-declared dates only; `report_date` remains a deprecated compatibility alias for `released_at`.
- Fetch time stays on `raw_fetch_result.fetched_at` and must never be projected as a report release date.
- Full rules and migration behavior are documented in `docs/architecture/FinancialDateSemantics.md`.

## Analysis Contract

Primary user-facing location:

- `analysis.human_answer`
- `analysis.decision_contract`

Responsible modules:

- `backend/app/ai/answer_composer.py`
- `backend/app/ai/ask_response_support.py`
- `backend/app/ai/decision_contract.py`

Expected answer concepts:

- headline / direct answer
- stance and confidence
- summary
- action plan
- scenarios
- counter evidence
- risks
- data limits
- readable text for frontend/Kuro

### `analysis.decision_contract`

`decision_contract` is an additive v1 projection for downstream consumers. It does not replace `analysis.human_answer`; it normalizes the backend-owned answer into a stable shape so frontend, MCP, Kuro, and future consumers do not need source-specific parsing.

Current shape:

- `kind`: `omi_ai_decision_contract`
- `version`: `decision_contract.v1`
- `intent`
- `answer_source`
- `answer_style`
- `target`
- `headline`
- `text`
- `sections`
  - `summary`
  - `action_plan`
  - `scenarios`
  - `counter_evidence`
  - `risks`
  - `data_limits`
- `readiness`
  - `answer_ready`
  - `has_text`
  - `has_action_plan`
  - `has_scenarios`
  - `has_counter_evidence`
  - `has_risks`
  - `has_data_limits`
  - `has_missing`
  - `has_warnings`
- `freshness`
- `missing`
- `warnings`

Consumer rule:

- Use `analysis.decision_contract` when a stable card, spoken brief, task-wall item, or downstream transformation needs structured sections.
- Keep `analysis.human_answer.text` as the safest direct human-readable answer.
- Do not infer market meaning from missing sections. Use `readiness` and `data_limits` to decide whether to render disabled/partial states.

Do not hide:

- stale data
- missing data
- partial data
- provider failure
- cached fallback
- best-effort output

## Question Understanding

Responsible module:

- `backend/app/ai/decision_core.py`

Current concepts:

- `intent`
  - `entry_decision`
  - `position_risk_decision`
  - `risk_check`
  - `trend_view`
  - `general`
- `analysis_horizon`
  - inferred from question, requested horizon, and strategy profile.
- `position_context`
  - entry price, holding context, stop-loss / take-profit / hold topics.
- `matched_hints`
  - used for transparent routing/debuggability in tests.

Regression principle:

- Add tests for semantic routing, not brittle exact phrasing.

## Evidence And Freshness Contract

Responsible modules:

- `backend/app/ai/freshness.py`
- `backend/app/ai/evidence_builder.py`
- `backend/app/ai/evidence_passport.py`
- `backend/app/ai/tools.py`
- `backend/app/ai/reports.py`

Required visibility:

- `freshness`
- `missing`
- `warnings`
- `source_refs`
- `evidence_passport`
- source health entries inside `analysis_digest` / `analysis.human_answer` when relevant.

Taiwan-first rule:

- Data freshness must respect Taiwan trading day, dataset frequency, holidays, session status, and partial provider coverage.

P1 freshness semantics:

- `availability`: whether local rows exist for the requested scope.
- `freshness`: `current`, `stale`, `unknown`, or `missing` according to a dataset release calendar or an explicit TTL policy.
- `expected`: the latest conservatively expected dataset date/period; it must not be inferred from row existence.
- Taiwan monthly revenue uses a market-wide conservative deadline of the 15th because 2026 rules allow insurers and public companies with an insurance subsidiary to file by then.
- Official basis: [TWSE public-company filing schedule](https://twse-regulation.twse.com.tw/m/Controls/GetFile.ashx?FID=0000366147) and the [FSC special filing rules](https://law.fsc.gov.tw/EngLawContent.aspx?id=2800&lan=C).
- `data_freshness.target.market` is preserved end to end. Supported outward values are `TW`, `US`, `JP`, `KR`, `CRYPTO`, and `ALL`; unsupported explicit markets must not fall back to TW.
- US daily evidence names `selected_provider`, `selected_provider_status`, `fallback_provider_summary`, and overall `provider_health` separately. Only selected-evidence staleness controls the main freshness judgment.

## Tool Refresh Contract

Responsible module:

- `backend/app/ai/agentic_tools.py`

Current tool concepts:

- `ALLOWED_TOOLS`
- `DEFAULT_TOOL_BUDGET`
- `normalize_tool_budget`
- `tool_plan`
- `tool_runs`
- external fetch marker
- cache-write marker
- market-cache versus user-data-write markers
- timeout/cancellation/fallback markers

Default budget:

- `max_calls`: 5
- `max_external_fetches`: 3
- `max_total_seconds`: 25

Wall-clock rule:

- `max_total_seconds` is a response deadline, not only a planning hint.
- A tool that crosses the remaining deadline returns `status=timeout`; it must not be labeled success.
- `fallback_to_cached=true` is reflected by `fallback_used` and `cached_data_returned`.
- `cancellation_requested` and `background_completion_possible` make the worker boundary explicit for consumers.
- `writes_market_cache` does not imply `writes_user_data`; report/memory writes remain behind the separate write policy.

Hard rules:

- OMI can autonomously supplement external data through allowlisted backend tools.
- Every external fetch must be bounded and visible.
- Over-budget, blocked, or failed tools should produce explicit evidence instead of silent degradation.
- `allow_write=false` must not generate persistent AI reports or memories.

## Downstream Consumers

### Frontend

- `frontend/src/components/OmiAskDock.tsx`
- `frontend/src/hooks/useOmiAskStream.ts`

Role:

- Render backend answer and structured fields.
- Do not re-run market logic.

### Kuro

- `C:\project\kuro\Open-LLM-VTuber\src\open_llm_vtuber\mcpp\market_preflight.py`
- `C:\project\kuro\Open-LLM-VTuber\src\open_llm_vtuber\agent\agents\basic_memory_agent.py`

Role:

- Ask OMI for market intelligence.
- Preserve OMI warnings and data limits.
- Transform result into conversation, briefing, Reader, task wall, or spoken output.
- Do not infer market decisions locally.

## Known Baseline Gaps

- Kuro `market_preflight.py` still has a fallback `OMI_API_BASE_URL` of `http://127.0.0.1:8300`; OMI repo rules now say backend default is `8400`.
- Contract shape is distributed across `schemas.py`, `answer_composer.py`, `ask_response_support.py`, and tests; later implementation may benefit from a small `decision_contract` helper or docs page, but not before baseline tests are reviewed.
- Runtime API smoke checks were not executed while creating this map.
