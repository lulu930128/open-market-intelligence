# Plan

## Milestones

1. Contract 與 seam 盤點
   - Scope：product/architecture、indicator、calendar、daily history、router/OpenAPI。
   - Acceptance：完成 `CapabilityContract.md`，確認無 provider、DB migration、AI/MCP/frontend 範圍。
   - Validation：source inspection 與 worktree diff ownership。

2. Pure calculation 與 read service
   - Scope：新增 `next_session_plan.py`。
   - Acceptance：MA20/60 transition、flat projection、drift、20 日區間、scenario zones、freshness/lifecycle/readiness 均由 backend 產生。
   - Validation：`backend/tests/test_next_session_plan.py`。

3. Public backend contract
   - Scope：新增 response schemas 與唯讀 route。
   - Acceptance：OpenAPI 具有具名 response model；unknown/missing/non-stock 回傳 predictable contract。
   - Validation：API inventory／schema targeted tests。

4. Regression 與交付
   - Scope：compile、targeted tests、backend safe validation、diff audit。
   - Acceptance：相關測試全綠；Progress 記錄已驗證與 deferred items。
   - Validation：repo safe validation wrapper 與 `git diff --check`。

5. Frontend consumer
   - Scope：typed contract、stock-detail hook、next-session panel、i18n、focused E2E。
   - Acceptance：普通台股個股在技術證據下、Overnight 上顯示欄位；frontend 不重算公式/freshness，ETF/指數不載入。
   - Validation：frontend lint/typecheck/build、focused Playwright 與位置/content assertions。

## Stop-and-fix rules

- 若公式等價性、交易日、release/freshness 或 response schema 測試失敗，先修正再進下一步。
- 若實作需要修改 AI/MCP/frontend 或現有 DB schema，停止並重新評估邊界。
- 若相關檔案出現無法安全共存的其他修改，先保留現況並回報，不覆蓋他人工作。

## Decisions

- 2026-08-09：採獨立 route/service，不自動塞入既有 technical report，避免目前 AI 路徑意外取得尚未接線的 capability。
- 2026-08-09：v1 不加入任意 ATR/tick observation band；只輸出可驗證的精確 transition 與自然 scenario zones。
- 2026-08-09：v1 不持久化；未來要做 Radar/outcome/backtest 時再新增 point-in-time snapshot contract。
- 2026-08-09：使用者授權第二階段 frontend 接線；新增獨立 panel/hook，AI/MCP/Radar 邊界不變。
- 2026-08-09：transport/backend warning 送共用「更新狀態」，readiness/freshness/limitation 同時保留在 panel。
