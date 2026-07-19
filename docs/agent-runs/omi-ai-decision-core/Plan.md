# Plan

## Milestones

1. Baseline the current AI contract
   - Scope: `backend/app/ai/schemas.py`, `ask.py`, `ask_execution.py`, `decision_core.py`, `answer_composer.py`, `agentic_tools.py`, `freshness.py`, `agents/omi_mcp_server/server.py`, related tests.
   - Acceptance: Produce a concise map of current request/response fields, trust gates, freshness flow, tool budget behavior, and user-facing answer fields.
   - Validation: `.\.venv\Scripts\python.exe -m unittest backend.tests.test_ai_decision_core backend.tests.test_ai_answer_composer backend.tests.test_ai_freshness_guard backend.tests.test_omi_mcp_server`

2. Define the minimum decision answer contract
   - Scope: Backend AI contract only; no UI redesign.
   - Acceptance: Identify which fields must always be present for entry, position/risk, trend, watchlist, stale-data, and tool-refresh answers.
   - Validation: Add or update tests that assert field presence and semantic behavior rather than exact fragile wording.

3. Harden question understanding and horizon routing
   - Scope: `decision_core.py`, `ask_response_support.py`, tests.
   - Acceptance: Chinese trading questions route consistently to `entry_decision`, `position_risk_decision`, `risk_check`, `trend_view`, or `general`; intraday/swing/long horizon inference remains explicit.
   - Validation: `.\.venv\Scripts\python.exe -m unittest backend.tests.test_ai_decision_core`

4. Harden structured answer composition
   - Scope: `answer_composer.py`, `ask_response_support.py`, `backend/tests/test_ai_answer_composer.py`.
   - Acceptance: Answers preserve `summary`, `action_plan`, `risks`, `data_limits`, and add/use `scenarios` and `counter_evidence` without breaking existing consumers.
   - Validation: `.\.venv\Scripts\python.exe -m unittest backend.tests.test_ai_answer_composer backend.tests.test_ai_ask_stages`

5. Align freshness and bounded external refresh evidence
   - Scope: `freshness.py`, `agentic_tools.py`, `ask_execution.py`, `ask_tool_stage.py`, `test_ai_freshness_guard.py`, `test_omi_mcp_server.py`.
   - Acceptance: stale-first behavior, `tw.refresh_stock_evidence`, `tool_budget`, `tool_plan`, `tool_runs`, cached fallback, and provider failure are visible and bounded.
   - Validation: `.\.venv\Scripts\python.exe -m unittest backend.tests.test_ai_freshness_guard backend.tests.test_omi_mcp_server`

6. Verify public callers
   - Scope: `agents/omi_mcp_server/server.py`, `frontend/src/components/OmiAskDock.tsx`, `frontend/src/hooks/useOmiAskStream.ts`.
   - Acceptance: MCP and frontend consume backend contract without duplicating market logic; any new fields are optional/backward-compatible.
   - Validation:
     - `.\.venv\Scripts\python.exe -m unittest backend.tests.test_omi_mcp_server`
     - `cd frontend; npm run lint`
     - `cd frontend; npm exec tsc -- --noEmit --incremental false`

7. API smoke checks when runtime is available
   - Scope: local backend on `127.0.0.1:8400`.
   - Acceptance: Representative `POST /api/ai/ask` calls return `omi.ai.ask.v2` responses with decision fields, freshness, warnings, and tool evidence as applicable.
   - Validation:
     - `Invoke-RestMethod "http://127.0.0.1:8400/api/system/health"`
     - `Invoke-RestMethod -Method Post "http://127.0.0.1:8400/api/ai/ask" -ContentType "application/json" -Body '<bounded test payload>'`

## Stop-and-fix rules

- 若 baseline tests 失敗，先判斷是本任務造成、既有 unrelated failure、或環境缺套件；不得在失敗未隔離時進下一個 milestone。
- 若發現現有 contract 與 `Prompt.md` 的 hard constraints 衝突，先更新 `Prompt.md` 並回報衝突，不直接硬改。
- 若改動會讓 frontend/MCP/Kuro 必須重做市場邏輯，停止並改回 backend contract 方案。
- 若 external refresh 需要超出 bounded budget、付費 quota、長時間全市場抓取或寫入 report/memory，停止並要求使用者確認。
- 若資料 stale、partial、missing 或 provider failure 被隱藏，該 milestone 不算完成。

## Decisions

- 2026-06-21：第一個長任務選 OMI AI decision core，而不是 Kuro OMI briefing。理由：Kuro 是 OMI 市場分析的下游；先穩定 backend decision contract，Kuro 後續只需呈現、語音化與任務牆整合。
- 2026-06-21：本任務不從零重寫 AI。理由：repo 已有 `decision_core.py`、`answer_composer.py`、`ask_*` stages、freshness guard、agentic tools 與 tests；正確方向是補 contract map、regression 與缺口，而不是大改架構。
- 2026-06-21：bounded external refresh 是 OMI 能力的一部分，但必須由 backend allowlisted tools 和 `tool_budget` 管控；MCP/Kuro 不直接打市場資料 API。
- 2026-07-19：P0 先以獨立 checkpoint 處理 target identity、follow-up context 與 directional price invariants；未知標的和無效價位不得進入可執行 answer contract，完成驗證後先 commit 再推進 freshness/P1。
