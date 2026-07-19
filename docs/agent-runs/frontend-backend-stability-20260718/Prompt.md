# 前後端連線穩定性第一批優化

## Goal

- 讓 OMI 在 backend 暫時失效、連線半斷、請求逾時或 SSE 長時間無資料時，可以有界地恢復、清楚分類錯誤，並讓使用者看見降級狀態。
- 將 process liveness、backend readiness、frontend proxy connectivity 分成可驗證的 contract。

## Non-goals

- 本次不切換日常 frontend 到 production standalone mode。
- 本次不調整市場資料、AI decision、freshness 或 consumer payload contract。
- 本次不對非冪等 mutation 自動重試，也不新增大型重試框架或 circuit-breaker dependency。
- 本次不處理 provider error storm、Crypto persistence UNIQUE conflict 或全域 log rotation；這些保留為後續 bounded package。

## Hard constraints

- 保留既有 `/api/system/health`、frontend `/omi-data` rewrite、launcher port fallback 與公開 API response compatibility。
- Backend runner 只允許有限次 crash recovery，必須有 backoff 與 crash-loop stop；launcher 結束或使用者停止服務時不得自行復活 process。
- Frontend timeout 必須允許 endpoint 明確覆寫；AI SSE 使用 connect/idle watchdog，不以過短的總時間中止合法長任務。
- 初始載入可保留 partial data，但不可再把 backend failure 靜默偽裝成正常空資料。
- 不刪除或重建本機 SQLite，不觸發外部大量 refresh、付費 quota、報告或 memory 寫入。

## Context

- Repo: `C:\project\Open Market Intelligence`
- Related systems: FastAPI backend、Next.js frontend、Windows tray launcher、SQLite runtime。
- 目前實際 runtime 是 frontend `127.0.0.1:3000` 經 `/omi-data` proxy 到 backend `127.0.0.1:8560`。
- 2026-07-17 backend log 曾記錄 `exit_code=-1` 且沒有 graceful shutdown/traceback；現有 service runner 在 child process 結束後直接退出，tray timer 只顯示狀態。
- Browser GET 已有 20 秒 timeout；mutation、Server Component/form route fetch 與 AI SSE watchdog 仍不一致。
- `page.tsx` 與 server form routes 目前會 catch-all 後 fallback/redirect，使用者看不到 backend failure。

## Deliverables

- Backend `/api/system/livez` 與 `/api/system/readyz`，保留 `/api/system/health`。
- Launcher 使用 readiness 做持續狀態判定；service runner 增加 bounded restart、backoff、stable-run reset 與 crash evidence。
- Frontend 共用 typed API error、request correlation ID、GET/mutation timeout policy。
- AI SSE connect timeout 與 idle watchdog。
- Server-side backend fetch helper；首頁與 watchlist form failure 產生可見、可重試的連線警告。
- Targeted tests、safe validation、isolated runner smoke、live API/proxy/browser verification。

## Done criteria

- Backend readiness 在 runtime 與 DB 正常時回 `200 ready`，其中任一未就緒時回 `503 not_ready`；liveness 不依賴 DB。
- Child process 非零退出時 runner 依設定最多重啟有限次；launcher 消失或正常退出不重啟；超限後停止並留下可讀 log。
- 一般 GET、mutation、server fetch 與 SSE 都不會無限等待，且 timeout/HTTP/network/abort 可被區分。
- 首頁初始 partial failure 與 server form failure 在 UI 可見，backend 恢復後可重新整理恢復完整資料。
- Targeted backend tests、frontend lint/typecheck/build、PowerShell AST/smoke、safe full validation 與 end-to-end runtime probes通過。

## Open questions / assumptions

- `exit_code=-1` 的原始 native/process 原因目前沒有足夠 traceback；本批先讓下一次 failure 可診斷並可有界恢復，不宣稱已修掉未知 crash root cause。
- Mutation 預設 timeout 採保守長值，個別長操作仍可用既有 `timeoutMs` 覆寫。
