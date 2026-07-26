# Plan

## Milestones

1. Canonical evidence 與 projection
   - Scope: `ask_finalizer.py`、`decision_envelope_v4.py`、capability normalizers、US/TW/source-health producers。
   - Acceptance: US intraday、TW daily OHLCV、source-health producer-to-final regressions通過。
   - Validation: targeted pytest covering full outward pipeline。

2. Multi-intent routing
   - Scope: `decision_core.py`、`query_plan.py`、explicit/inferred intent 與 domain union。
   - Acceptance: broker-only fast path 只處理純分點請求；複合請求保留所有需求。
   - Validation: decision-core、query-plan 與 ask-stage targeted tests。

3. Refresh reconciliation
   - Scope: tool run outcome、capability outcome、fill-plan remaining actions。
   - Acceptance: 成功 refresh 後不再產生相同 fill action；失敗或無新資料仍保留可解釋的 continuation。
   - Validation: success/unchanged/failure/timeout fixtures 與 outward integration tests。

4. Quality、units 與 trust
   - Scope: availability、freshness、completeness、continuity、unit、decision usability、passport/readiness。
   - Acceptance: valid facts 不因 legacy status 被抹除；volume unit 明確；trust tuple 一致。
   - Validation: pure invariant tests 加 producer-to-final quote regression。

5. MCP 與 standalone adapter parity
   - Scope: repo MCP schema、standalone `OMI_search` schema、structured business rejection。
   - Acceptance: v4 controls 可發現；business rejection `isError=false`；transport/internal failure `isError=true`。
   - Validation: repo MCP tests、standalone adapter tests、tools/list 與 business call smoke。

6. Projection metadata 與 rejected envelope
   - Scope: byte-budget trimming metadata、minimal rejected path、文件。
   - Acceptance: `truncated` 原因完整；unresolved target 不標 ready；public docs v4-only 一致。
   - Validation: budget/rejection contract tests、OpenAPI/docs search、diff check。

7. 全面驗證與 runtime 證明
   - Scope: backend、frontend consumer、HTTP、SSE、repo MCP、standalone adapter。
   - Acceptance: safe validation 全通過，代表性 success/partial/rejected probes 與實際 PID/port 有證據。
   - Validation: `scripts/run-safe-validation.ps1`、launcher log、`/api/ai/tools`、HTTP/SSE/MCP smoke。

## Stop-and-fix rules

- 任一里程碑 targeted regression 失敗時，先修復或明確隔離無關既有失敗，不能帶到下一階段。
- 若修正會要求 raw tool payload 直接外露、讓 consumer 重做 backend quality logic、改 DB schema 或啟動無邊界 refresh，停止並重新設計。
- 若 active runtime 與 checkout 不一致，先以 launcher log、PID、port 與 `/api/ai/tools` 校正，不把 stale runtime 當驗收結果。
- 若 standalone adapter 修改因 workspace 權限受阻，記錄完整 patch 與驗證命令並請求擴充權限，不繞過 sandbox。
- 每完成一個 milestone，更新 `Progress.md` 的變更、測試與已知風險。

## Decisions

- 2026-07-24：先修 canonical projection 共通根因，不為 US intraday、TW daily、source-health 各自加 outward 特例。
- 2026-07-24：fill plan 保持 continuation，不自動遞迴執行全部 action；以 execution reconciliation 避免重複。
- 2026-07-24：quality 拆分各維度，不以單一 global priority 取代現有 max-severity。
- 2026-07-24：Frontend 維持 thin canonical consumer，本專案不在 UI 重做契約判斷。
