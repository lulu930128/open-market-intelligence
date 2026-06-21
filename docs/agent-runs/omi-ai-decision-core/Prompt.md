# OMI AI Decision Core

## Goal

- 將 OMI AI decision core 收斂成可長期維護、可測試、可被 Kuro/MCP/frontend 穩定消費的技術決策契約。
- OMI 回答股票與市場問題時，優先輸出 evidence-backed 的決策結構：目前狀態、情境、回測區、進場條件、失效條件、風險與反證，而不是單句「買/賣/會漲」。
- 讓資料 freshness、external API bounded refresh、tool evidence、source health 與 data limits 在 backend answer contract 中一致可見。

## Non-goals

- 不做自動下單、交易執行、投資保證或「預測一定漲跌」功能。
- 不重寫整個 OMI AI pipeline；優先沿用既有 `backend/app/ai/*` stage/refactor 架構。
- 不把市場邏輯搬到 frontend、MCP adapter 或 Kuro。
- 不在本任務直接擴大到所有海外市場完整產品化；台股仍是核心，其他市場只作為 context layer 或既有 US flow 的相容面。
- 不新增大範圍 dependency upgrade、schema rewrite、UI redesign 或 unrelated cleanup。

## Hard constraints

- Repo: `C:\project\Open Market Intelligence`
- 台股是核心市場；其他市場不得反向主導 OMI 的資料模型與回答契約。
- `backend/app/ai/` 是 AI evidence、question routing、decision core、answer contract 與 tool orchestration 的主要邊界。
- `agents/omi_mcp_server/` 必須保持 thin adapter：呼叫 backend API，不直接讀寫 DB，不複製市場邏輯。
- `frontend/src/components/OmiAskDock.tsx` 只呈現 backend `analysis.human_answer` / structured answer；不得重新推導市場判斷。
- `data/open_market_intelligence.db` 不得刪除、重建或覆蓋。任何 DB schema 變更都必須走 migration。
- `allow_external_fetch=true` 允許 OMI 自主用外部 API 補資料，但必須 bounded：目標、資料範圍、次數、timeout、來源、寫入 cache policy 與失敗回報都要可見。
- `allow_write=false` 時不得產生持久化 report、memory 或其他長期 side effect；市場資料 cache/backfill 只能依既有 refresh policy 與 tool budget 執行。
- stale、partial、missing、best-effort、provider failure 不得被隱藏或改寫成確定結論。
- 預設 backend port 是 `127.0.0.1:8400`；不要恢復舊 `8300` 假設。

## Context

- Repo root: `C:\project\Open Market Intelligence`
- Repo instructions: `AGENTS.md` 已定義 OMI 為 local-first 市場情報與交易決策研究工作台，AI decision core 是產品核心。
- Public AI API surface:
  - `backend/app/routers/ai.py`
  - `POST /api/ai/ask`
  - `POST /api/ai/ask/stream`
  - Trust boundary 由 `x-omi-ai-trust-token`、local allowlist 與 `AiAskServerPolicy` 決定。
- Request/response contract:
  - `backend/app/ai/schemas.py`
  - `AiAskRequest` 包含 `contract_version=omi.ai.ask.v2`、`allow_llm`、`allow_write`、`allow_external_fetch`、`tool_budget`、`refresh_policy`、`analysis_horizon`。
  - `AiAskResponse` 包含 `analysis`、`policy`、`tool_plan`、`tool_runs`、`freshness`、`missing`、`warnings`、`source_refs`、`evidence_passport`。
- Current backend AI modules:
  - `backend/app/ai/decision_core.py`：question understanding、intent、horizon、position context。
  - `backend/app/ai/decision_engine.py`：score/stance/technical level helpers。
  - `backend/app/ai/answer_composer.py`：user-facing wording 與 structured answer contract。
  - `backend/app/ai/ask.py` / `ask_execution.py` / `ask_*_stage.py`：ask pipeline 與 mode execution。
  - `backend/app/ai/freshness.py`：台股 evidence freshness guard。
  - `backend/app/ai/agentic_tools.py`：allowlisted external tool definitions、budget normalization、tool execution evidence。
- Current external caller surface:
  - `agents/omi_mcp_server/server.py`
  - `agents/omi_mcp_server/README.md`
  - MCP exposes `omi.ask` / `omi.ask_stream` and now defaults backend API to `8400`.
- Current regression surfaces:
  - `backend/tests/test_ai_decision_core.py`
  - `backend/tests/test_ai_answer_composer.py`
  - `backend/tests/test_ai_decision_engine.py`
  - `backend/tests/test_ai_evidence_builder.py`
  - `backend/tests/test_ai_freshness_guard.py`
  - `backend/tests/test_ai_ask_stages.py`
  - `backend/tests/test_omi_mcp_server.py`
- Prior context from project memory:
  - `answer_composer.py` is the right layer for user-facing OMI wording and structured answer contract changes.
  - Low-risk answer upgrades should add fields such as `scenarios` and `counter_evidence` without breaking existing `summary`, `action_plan`, `risks`, and `data_limits`.
  - Freshness-controlled answers should keep `stale_first`, `refresh_policy`, `tw.refresh_stock_evidence`, `tool_budget`, `allow_external_fetch`, and cached fallback visible.

## Deliverables

- A reviewed AI decision contract map covering `question_understanding`, `analysis.human_answer`, `policy`, `tool_plan`, `tool_runs`, `freshness`, `missing`, `warnings`, `source_refs`, and `evidence_passport`.
- Focused backend changes, if inspection shows gaps, in the existing AI modules rather than in frontend/MCP/Kuro.
- Regression tests for entry decision, position/risk decision, trend view, stale data, bounded external refresh, and MCP-facing `omi.ask` behavior.
- Frontend/MCP compatibility notes only where response shape or display expectations change.
- Updated `Progress.md` after each milestone with concrete validation evidence.

## Done criteria

- For representative questions like:
  - `2330 現在可以買嗎？如果等回檔看哪裡？`
  - `我買在2390，要續抱、減碼還是停損？`
  - `今天盤中可以追嗎？跌到哪裡要防守？`
  - `請用中線波段角度分析目前標的`
  OMI returns structured, evidence-backed answers with scenarios, counter-evidence, actionable levels when available, data limits, and freshness/tool evidence.
- `allow_external_fetch=true` uses only bounded allowlisted tools and returns `tool_plan` / `tool_runs`; over-budget or disallowed actions are blocked or reported clearly.
- `allow_write=false` does not persist AI reports/memory and does not bypass trust policy.
- Stale/partial/provider failure states remain visible in `analysis.human_answer` or response metadata.
- Existing API/MCP/frontend consumers keep working with the same `omi.ai.ask.v2` contract, or any contract extension is backward-compatible.
- Relevant backend tests pass, and any unrun validation is documented with exact commands.

## Open questions / assumptions

- Assumption: first implementation pass should remain Taiwan-first and focus on `tw_stock`, `tw_index`, `tw_futures`, watchlist, and existing `us_stock` compatibility rather than expanding new markets.
- Assumption: Kuro should consume OMI output only after this backend contract is stable; Kuro should not compensate for missing market logic.
- Open question: whether to formalize a machine-readable `decision_contract` schema in addition to existing `analysis.human_answer` fields. Decide after baseline inspection.
