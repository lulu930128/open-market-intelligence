# Plan

## Milestones

1. Backend readiness 與 launcher lifecycle hardening
   - Scope: `backend/app/routers/system.py`、health tests、`scripts/omi-launcher.ps1`、`scripts/run-service-logged.ps1`。
   - Acceptance: livez/readyz contract 可測；runner crash recovery 有上限、backoff、stable reset 與 exit evidence；tray 以 readiness 判斷 API 狀態。
   - Validation: targeted backend pytest、PowerShell AST parse、isolated failing-child runner smoke。

2. Frontend request contract hardening
   - Scope: `frontend/src/lib/api.ts`、AI SSE hook、server-only backend fetch helper。
   - Acceptance: typed error 保留 backend request ID；GET/mutation/server/SSE 都有可覆寫的 bounded timeout；external abort 不被誤判為 timeout。
   - Validation: frontend lint、TypeScript typecheck、production build。

3. Visible degraded state
   - Scope: homepage initial fetch、watchlist form routes、dashboard connection banner、i18n。
   - Acceptance: initial partial failure 與 form failure 不再 silent；backend offline/ready 可以週期檢查；正常狀態不增加常駐警告。
   - Validation: targeted browser route interception/runtime probe、frontend E2E 或最接近的 smoke。

4. Cross-boundary regression
   - Scope: backend/frontend/launcher final diff 與 runtime。
   - Acceptance: existing `/health`、proxy route、dynamic launcher port 與 dashboard core flow不回歸。
   - Validation: `run-safe-validation.ps1` 的相關 profile、isolated current-code backend、live proxy probes、`git diff --check`。

## Stop-and-fix rules

- 若 runner 會在 launcher 結束或 intentional stop 後復活 child process，立即停止並修正。
- 若 readiness GET 造成 DB mutation、migration 或 provider refresh，立即停止並修正。
- 若 frontend timeout 中止合法 AI/refresh 長任務，先調整 contract 或 endpoint override，再進下一步。
- 若 UI 把 partial/offline 隱藏成正常空資料，視為未完成。
- 若 targeted validation 失敗，先修正，不以 broad fallback 掩蓋。

## Decisions

- 2026-07-18：將 production frontend mode、provider log storm 與 Crypto UNIQUE conflict 留到後續，避免和連線 contract/lifecycle 一次混改。
- 2026-07-18：不自動重試 mutation；先提供 typed error、timeout 與明確使用者重試。
- 2026-07-18：保留 `/api/system/health` 作 compatibility/identity endpoint，新增 livez/readyz 而不是改變既有語意。
