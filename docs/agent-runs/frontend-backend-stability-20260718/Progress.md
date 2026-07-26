# Progress

## Status

- Current phase: delivery-ready; live launcher restart pending
- Last updated: 2026-07-18 08:06 +08:00

## Completed

- 確認 live runtime：frontend `3000`、backend fallback `8560`，proxy target 一致；direct/proxy health 均穩定回應。
- 找到舊 backend 曾 abrupt `exit_code=-1`，既有 runner 沒有 supervisor loop，tray 也只觀察 state file。
- 新增 `/api/system/livez` 與 `/api/system/readyz`；readiness 只檢查 runtime lifecycle 與 SQLite read-only `SELECT 1`，保留 `/health` contract。
- Service runner 加入最多 3 次 bounded recovery、`2/10/30` 秒 backoff、stable-run reset、child PID/runtime/exit evidence，以及 backend faulthandler/unbuffered output。
- Launcher 改用 readiness 判斷服務狀態，只有 recovery 最終失敗時才顯示 tray warning。
- 統一 browser/server API timeout、typed error、request ID；mutation 不做自動 retry。
- SSE 加入 20 秒連線 timeout 與 150 秒 idle watchdog，並保留使用者 abort 語意。
- Homepage server fetch 由 silent fallback 改成收集 partial failure；watchlist form redirect 帶安全錯誤碼。
- 新增 dashboard connection banner，呈現 backend offline、表單失敗與初始 partial failure；支援舊 backend `/readyz` 404 時回退 `/health`。
- React 檢查修正 readiness 輪詢的 abort-controller race，避免舊請求誤判新請求狀態。
- 新增 Playwright regression，確認 mutation redirect 後錯誤仍可見且 URL 錯誤參數會被清除。
- 補齊 intentional stop 狀態，避免使用者正常停止 backend 時被 tray 誤報為 recovery crash-loop failure。
- Timeout/network/SSE error 現在保留同一個 outbound request ID，方便和 backend log 對照。

## Validation evidence

- Direct backend health：5/5 HTTP 200，約 8-27 ms。
- Frontend proxy health：5/5 HTTP 200，約 8-10 ms。
- Dashboard SSR smoke：3/3 HTTP 200；首次約 6.5 秒，warm 約 1.4-1.5 秒。
- `..\.venv\Scripts\python.exe -m pytest -q tests\test_system_health.py`：`5 passed`，只有既有 sandbox pytest cache warning。
- PowerShell AST：`omi-launcher.ps1`、`run-service-logged.ps1` 均通過。
- Isolated failing-child runner smoke：child exit `7`；啟動 3 次、安排 recovery 2 次、crash-loop stop 1 次，runner 最終保留 exit code `7`。
- `npm run lint`：通過。
- `npm exec tsc -- --noEmit --incremental false --pretty false`：通過。
- `run-safe-validation.ps1 -Profile backend`：compileall、659 個 backend tests、diff check 全數通過。
- `npm run build`：Next.js 16.2.6 production build 在 sandbox 外最終重跑通過；safe wrapper 內曾於 TypeScript worker spawn 遭 Windows `EPERM`，相同指令移出 sandbox 後正常。
- Targeted Playwright：`backend mutation failure remains visible after redirect`，`1 passed`；案例明確模擬 `/readyz` 404 並驗證 `/health` rolling fallback。
- `git diff --check`：通過；僅顯示既有 Windows LF/CRLF 提示。
- Live compatibility probe：backend `8560` `/health` 200；frontend `3000` 正確 proxy `/omi-data/system/health` 200；舊 runtime `/readyz` 404，frontend fallback 仍可工作。

## Decisions made

- 使用 bounded supervisor，不做無限重啟。
- 分開 livez/readyz，不破壞既有 health identity contract。
- 保留 partial/offline 可見狀態，不把連線失敗偽裝成空資料。
- Mutation 不自動 retry，避免重複寫入；SSE 只加 connect/idle watchdog。
- Rolling upgrade 期間前端在 `/readyz` 404 時暫時回退 `/health`，避免新 frontend 對舊 backend 誤報離線。

## Known issues / risks

- 舊 abrupt exit 的 native root cause 尚未重現；本輪先補齊 crash evidence 與 bounded recovery，使下次失敗可診斷且能有限次自癒。
- Daily launcher 仍使用 `next dev`；production frontend mode 留待獨立部署批次。
- Provider 重複 warning 與 Crypto UNIQUE conflict 仍可能產生 log noise，留待 provider/ingestion 專項處理。
- 目前執行中的 tray launcher 是修改前已載入的 process；為避免以不確定 PID 強制中止，未在本輪粗暴殺掉 live services。退出並重開 OMI launcher 後，新的 readiness 監控與 runner recovery 才會進入 live runtime。

## Next step

- 從 tray 選擇 Exit 後重新啟動 OMI launcher，再確認 tray 顯示 `API OK; UI OK` 與實際 `/api/system/readyz` 回 200。
