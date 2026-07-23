# Plan

## Milestones

1. Baseline and architecture
   - Scope：盤點 v2 finalizer、readiness、slots、HTTP/SSE、Frontend、repo MCP、OMI_search、Kuro 與 runtime。
   - Acceptance：完成 `Prompt.md`、`Architecture.md`、`Plan.md`、`Progress.md`，列出 canonical invariants 與 compatibility strategy。
   - Validation：UTF-8 讀回、相關檔案與既有 diff review。

2. Canonical backend contract
   - Scope：新增 `omi.decision.v3` schema、projection、readiness evaluator、slot/freshness normalization。
   - Acceptance：正常、clarification、error response 都能由同一 builder 產生；v2 保持可用。
   - Validation：新增 pure contract tests，執行 targeted backend pytest。

3. Scope and streaming correctness
   - Scope：regional market default target、SSE final/done business semantics。
   - Acceptance：JP/KR/US 不落入 Taiwan market reader；business failure 不被 transport completion 覆蓋。
   - Validation：scope-resolution regressions、streaming regressions、representative API probes。

4. In-repo consumers
   - Scope：Frontend OMI Ask Dock、repo MCP。
   - Acceptance：兩者明確要求 v3，只讀 canonical sections；v2 fallback 只供 compatibility。
   - Validation：MCP unit tests、Frontend lint/typecheck、必要的 OMI smoke。

5. External consumers
   - Scope：`C:\GPT_MCPtool\OMI_search`、`C:\project\kuro\Open-LLM-VTuber`。
   - Acceptance：外部 adapter request v3、只 forward canonical contract、runtime URL 跟隨 launcher；Kuro final/error/readiness snapshot 使用 v3。
   - Validation：各 repo/資料夾既有 syntax/unit tests、MCP initialize/list/call、Kuro runtime smoke（若服務可啟動）。

6. Full contract validation and handoff
   - Scope：safe validation、live HTTP/SSE/MCP、付費 API bounded probe（只有 credential/trust/budget 可用時）。
   - Acceptance：done criteria 全部有證據，未完成項目明確隔離。
   - Validation：
     - `.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs <targeted tests>`
     - `.\scripts\run-safe-validation.ps1 -Profile frontend`
     - `/api/ai/tools`、`/api/ai/ask`、`/api/ai/ask/stream`
     - MCP `initialize`、`tools/list`、`tools/call`

## Stop-and-fix rules

- 任一 v2 compatibility regression 發生時，先修正再切換 consumer。
- 任一 market scope 仍可能靜默落入錯誤市場時，不得宣稱 gateway 收斂完成。
- 任一 stale／missing／blocked evidence 仍可得到 executable `decision_ready=true` 時，停止 consumer rollout。
- SSE final/done、HTTP/MCP business error 不一致時，停止 transport rollout。
- External API／LLM 超出 budget、無 source refs、無 provider failure 回報或需要未確認 secret 時，停止該驗證，不以 mock 宣稱 live 完成。
- Dirty worktree 若與本任務檔案重疊，保留既有改動並採 localized patch，不重置、不覆寫。

## Decisions

- Decision：一個語意出口不等於一個物理 protocol；HTTP、SSE、MCP 共用同一 canonical final envelope。
- Decision：資料面與維運面 API 保留；只有 AI decision plane 收斂為 `omi.ask`。
- Decision：v3 是 canonical domain response；v2 是 compatibility response，不由 consumer 同時混讀。
- Decision：Backend 產生 reader-profile projection；adapter 不自行重算 readiness、freshness 或 market semantics。
- Decision：OMI internal AI 使用 canonical evidence model 產生 v3，不解析自己輸出的自然語言。
- Decision：paid API 是可選、受政策約束的 evidence/analysis provider，不是 readiness bypass。
