# OMI Runtime 與資料載入穩定性根除

## Goal

- Backend 實際遇到 Windows excluded range、listener race 或 bind failure 時，launcher 能有界地重新選擇可用 port、同步 proxy environment，並恢復 Backend 與 Frontend。
- 台股日 K 技術指標計算保留交易日缺口語意，同時避免在每個移動平均視窗重複查詢交易日曆。
- 區域市場輪詢只讀本機 cache；provider/history refresh 不再由每 5 秒的 UI read path 隱性觸發，避免 SQLite connection pool 與單寫入鎖被耗盡。

## Non-goals

- 不重構 OMI 的市場資料模型、Radar v2 scoring 或 AI decision contract。
- 不以增加 frontend timeout、SQLAlchemy pool size 或 SQLite busy timeout 掩蓋長交易與重複 refresh。
- 不刪除、重建、vacuum 或覆蓋 `data/open_market_intelligence.db`。
- 不處理與本次 log 證據無關的既有 crypto UNIQUE constraint 噪音或其他 dirty-worktree 功能。

## Hard constraints

- Backend 保有 freshness、provider refresh、交易日與 Radar snapshot 語意的唯一真相來源。
- `8400`／`3000` 只是 preferred ports；實際 URL 以 launcher `selected=` 與 live runtime 為準。
- Radar 盤後 default request 必須繼續優先命中 persisted daily snapshot；盤中/custom parameters 才可完整計算。
- Launcher recovery 必須 bounded，不能形成無限換 port 或 crash loop。
- 保留使用者及其他流程現有未提交變更；只做 localized diff，不 revert、commit 或 push。

## Context

- Repo: `C:\project\Open Market Intelligence`
- Related systems: Windows launcher、PowerShell service runner、FastAPI、Next.js proxy、SQLite、台股 indicators、區域市場 tape、Radar v2。
- Current known state:
  - 2026-08-16 12:37 Backend 在 `127.0.0.1:8400` 四次得到 `WinError 10013`，runner 最後進入 crash-loop stop；Frontend `3000` 仍存活並持續得到 `ECONNREFUSED`。
  - Windows 目前 excluded range `8344-8443` 包含 `8400`。
  - `/api/market/indicators/2330/daily` 曾超過 20 秒；240 筆唯讀 benchmark 約 4.643 秒，舊 gap 判斷對照約 0.034 秒。
  - 2026-08-12／13 分別有 216／300 次 QueuePool timeout；區域市場 tape 每 5 秒以 `ensure_history=true` 讀取兩個美股指數，讓 provider refresh 與 SQLite 寫入進入輪詢 read path。
  - 盤後 Radar snapshot 路徑仍存在，現有 snapshot 讀取約 39-289 ms；目前空白主要是 Backend outage，full-compute 才受 indicator 回歸連帶影響。

## Deliverables

- PowerShell runner bind-failure classification 與 launcher bounded port recovery。
- 台股 indicator gap prefix/precomputation 與 correctness/performance regression tests。
- 區域市場 tape cache-first query 修正與防止 polling refresh 的 contract test。
- 任務進度、targeted tests、安全驗證與 bounded live/runtime 採用證據。

## Done criteria

- 模擬 Backend bind failure 時 runner 不在同一個 port 無效重試，launcher recovery contract 能辨認專用 exit code並重建 proxy-owned Frontend。
- 合法長假與缺漏交易日測試皆通過；240／1000 筆計算不再隨 MA window 重複交易日曆查詢，2330 240 筆 benchmark 明顯低於 Frontend 20 秒 budget。
- 區域市場 polling request 的 `ensure_history` 為 `false`，provider/history refresh 不再由 tape poll 觸發。
- Targeted backend tests、PowerShell AST、frontend lint/typecheck 與最小安全驗證通過。
- 正式 launcher 採用新程式後，live readiness、Frontend proxy、2330 K 線與盤後 Radar representative request 都有成功證據。

## Open questions / assumptions

- 假設 8 月 12／13 的 connection pool storm 主要由多個區域 tape 實例重複執行 `ensure_history=true` 所致；會以 call-site contract 與相關 service behavior 測試驗證，不以擴 pool 取代根因修復。
- 若正式 runtime adoption 需要結束既有 tray，僅操作已驗證屬於本 repo launcher 的精確 process lineage。
