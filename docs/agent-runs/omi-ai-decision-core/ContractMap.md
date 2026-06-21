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
  - `auto`, `data_only`, `brief`, `analysis`, `report`.
  - `report` is trusted/write-sensitive and should not be requested by Kuro default policy.
- `allow_llm`
  - Enables non-persistent LLM analysis only when server policy permits.
- `allow_write`
  - Required for persistent reports/memory-like side effects.
  - Must remain false for Kuro default flow.
- `allow_external_fetch`
  - Allows backend-owned bounded external fetch.
  - Does not authorize frontend/MCP/Kuro to call market APIs directly.
- `tool_budget`
  - Controls maximum calls, external fetches, and total seconds.
- `refresh_policy`
  - Default: `stale_first`, `before_answer=true`, `fallback_to_cached=true`.
- `strategy_profile`
  - Current examples include `short_term_momentum` and `technical_swing`.
- `analysis_horizon`
  - `auto`, `intraday`, `short`, `swing`, `long`.
- `conversation_context`
  - Caller context such as Kuro route text or last OMI resolution.

## Response Contract

Source: `backend/app/ai/schemas.py`

Top-level fields that downstream callers should treat as stable:

- `kind`
- `contract_version`
- `question`
- `target`
- `mode`
- `action`
- `strategy_profile`
- `caller_profile`
- `resolution`
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

Backward compatibility rule:

- New fields should be additive.
- Existing fields should not change type without a version bump or compatibility shim.
- Frontend/Kuro should prefer optional-field tolerant parsing.

## Analysis Contract

Primary user-facing location:

- `analysis.human_answer`

Responsible modules:

- `backend/app/ai/answer_composer.py`
- `backend/app/ai/ask_response_support.py`

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

Default budget:

- `max_calls`: 5
- `max_external_fetches`: 3
- `max_total_seconds`: 25

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
