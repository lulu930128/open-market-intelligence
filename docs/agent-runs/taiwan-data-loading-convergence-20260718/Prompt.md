# 台股工作台資料載入與刷新收斂

## Goal

- 讓台股工作台在本機 cache 可用時快速進入可操作狀態，不因 TPEx、TDCC、TWSE、Yahoo 或其他 provider 暫時失敗而阻塞整個首頁。
- 將「讀取既有資料」與「外部資料刷新／回補」拆成可辨識、可觀察、可有界執行的 backend contract。
- 收斂 K 線、Radar、排行與法人／籌碼資料的重複 request、重複計算與 component-mount refresh，讓相同 target、交易日與 profile 不會被無限制重跑。
- 保留並強化 freshness、stale、partial、missing、provider failure 與背景更新狀態；效能改善不得以隱藏資料缺口換取。
- 建立可重複的效能與失敗模式驗證，使後續可以用測試與 runtime evidence 判斷是否真正改善。

## Non-goals

- 本專案不重做 OMI dashboard 視覺設計，也不改變台股作為核心市場的產品定位。
- 不把其他市場一起納入第一批實作；共用 contract 可以保留擴充能力，但驗收先以台股工作台為準。
- 不保證外部 provider 永遠成功，也不以無限制 retry、延長 timeout 或全域關閉 TLS 驗證掩蓋來源問題。
- 不重建、清空或覆蓋 `data/open_market_intelligence.db`。
- 不改變 Radar 的交易判斷、排行公式或 AI decision core；本專案只處理資料取得、計算重用、freshness 與呈現節奏。
- 不把 frontend 變成 freshness、provider fallback 或 refresh policy 的真相來源。
- 不順便處理與本問題無關的 Crypto persistence、跨市場 payload 或大型 module decomposition。

## Hard constraints

- Backend 保持市場資料、freshness、refresh policy、job orchestration 與 provider health 的唯一真相來源。
- GET/read path 預設必須輕量且可預測；需要外部 HTTP、長時間回補或資料寫入時，必須由明確 refresh contract 或 bounded job 擁有。
- Cache-first 不等於假裝資料是 current。所有回應與 UI 必須保留資料日期、freshness、warnings、partial/missing 與 provider failure。
- Refresh 必須有 target、profile、range、timeout、provider、交易日與結果摘要；同一 dedupe key 不得因頁面 reload 或 component remount 重複啟動。
- 不對 mutation 自動做不安全 retry，不允許相同 refresh job 因網路重送造成重複副作用。
- TDCC TLS 問題只能用 scoped trust／CA、正確 provider endpoint 或可驗證 transport 修復；不得全域設定 `verify=False`。
- Public route、query parameter 與 response shape 預設保持相容。若契約必須演進，應先增加 additive field／explicit mode，並補 contract tests。
- Radar snapshot 由 backend scheduler／job／service 擁有；GET read path 不隱性建立 snapshot。
- DB schema 若需要新增 snapshot 或 dedupe state，必須使用 Alembic migration，並保留 upgrade、rollback 說明與 model contract tests。
- 實作前必須重新檢查目前 dirty worktree，避免覆蓋 `frontend-backend-stability-20260718`、market capability 或使用者既有變更。

## Context

- Repo：`C:\project\Open Market Intelligence`
- Related systems：Next.js frontend、FastAPI backend、SQLite、watchlist jobs、Radar/ranking services、Taiwan market providers、provider events、source health。
- 2026-07-18 live runtime 已確認 frontend `127.0.0.1:3000`、backend `127.0.0.1:8400`，health 與 frontend proxy 正常；本問題不是固定 port 或 proxy 失聯。
- 首頁 Server Component 先等待 index summary 與多市場基礎資料，之後才等待台股 Radar、OHLC 與 indicators。index summary timeout 會把後續等待串成累加延遲。
- 目前 index summary cold request 約 5.7 秒；frontend log 同日有多次 20 秒 timeout，SSR request 曾耗時 21.9–24.6 秒。
- 2330 本機 OHLC cache 約 8 ms、indicators 約 24 ms、法人歷史約 8 ms；慢點主要出現在讀取時觸發 ensure/backfill、selection refresh 或 active-tab refresh。
- Watchlist group 3 有 83 檔。Radar 目前完整但每次即時計算約 1.6–5 秒；排行 client 以每批 3 檔依序載入，83 檔需要約 28 次 request。
- 最近 group refresh job 對 83 檔使用每檔 5 秒節流，結果 73 成功、10 失敗；component-local dedupe 無法跨 remount 或重新整理保證唯一執行。
- 2330 法人資料已到 2026-07-17，但 chips profile 同時刷新法人、融資券、分點與集保；TDCC shareholding refresh 因 Python TLS certificate validation 失敗，導致 composite job partial。
- 既有 `frontend-backend-stability-20260718` 專案處理 readiness、timeout 與 visible degraded state，並明確把 market-data refresh 與 provider storm列為 non-goal；本專案是後續獨立收斂批次。
- 詳細基線見 `Baseline.md`。

## User experience contract

- 首頁 shell 與既有 cache 應先顯示；非關鍵 index/provider request 不得阻塞整頁。
- K 線、法人與籌碼分頁先呈現最近可用資料，再個別顯示背景更新狀態與資料日期。
- 背景 refresh 失敗時保留 cache，並顯示是哪個 resource/provider 失敗；不得把 composite partial 寫成「全部撈取不到」。
- Radar 可以先顯示最近有效 snapshot，再明確標示 snapshot 日期與是否正在重算。
- 使用者手動要求 refresh 時要看得到 job 狀態；單純切換股票、分頁或重新整理頁面不應無條件啟動全群組 refresh。

## Deliverables

- 本任務的 `Prompt.md`、`Plan.md`、`Progress.md` 與 `Baseline.md`。
- Cache-only/read-only API contract，以及與 explicit refresh/job contract 的責任分界。
- 首頁非阻塞資料載入與 cache-first degraded state。
- K 線與法人／籌碼的 stale-while-revalidate 流程，並移除 component-mount 的重複昂貴 refresh。
- Refresh server-side dedupe、交易日／profile key 與可觀察 job outcome。
- Radar/ranking 計算重用與 snapshot read path。
- TDCC／TPEx transport failure 的結構化 provider event、source-health 狀態與安全 fallback。
- K 線 timestamp ordering/uniqueness invariant。
- Targeted backend/frontend tests、safe validation、fault-injection smoke 與 live runtime benchmark evidence。

## Done criteria

- 在 provider timeout／TLS failure 的測試情境下，首頁仍於 5 秒內回傳可操作 shell 與可用 cache，不等待 20 秒 frontend timeout。
- Cache-only OHLC、institutional 與已存在 Radar snapshot 的本機 10 次 probe，p95 各不超過 250 ms、250 ms、750 ms；benchmark 必須記錄 payload size 與 runtime mode。
- Cache-only GET 的 targeted tests 能證明不呼叫 provider HTTP、不執行 refresh job、不 commit 資料。
- 同一 market/target/profile/trade-date 的 refresh 在跨 component remount、重送或並發請求時最多只有一個 active job；後續 caller 取得相同 job reference 或明確 deduped outcome。
- 選取一檔股票或切換資料 tab 不會自動啟動 83 檔全群組 refresh。
- 法人／籌碼畫面在 composite refresh partial 時仍能顯示已成功的本機資源，並指出失敗 resource、provider、資料日期與 warning。
- Radar warm snapshot 不重新計算整個群組；snapshot miss 的計算有明確 job/timeout 邊界，且不在 GET read path 隱性寫入。
- K 線 API 與前端投影都保證 timestamp 遞增且唯一；相關 regression test 能重現並攔截 duplicate/out-of-order payload。
- TDCC transport 不使用全域 TLS bypass；TPEx／TDCC 失敗都能在 provider events/source health 看見安全 URL、resource、target、error type 與 fallback 狀態。
- 相關 backend targeted tests、frontend lint/typecheck、必要 build/E2E、safe validation 與 live browser/runtime smoke 全數通過。
- `Progress.md` 記錄每個 milestone 的驗證證據、殘留風險與最終效能比較。

## Open questions / assumptions

- 第一批以目前主要台股 group 3、2330 與一檔上櫃股票作為代表情境；正式驗收仍需加入空 cache、stale cache、provider failure 與休市日案例。
- Radar snapshot 可能可以重用既有 automation/outcome persistence；在確認 schema 與 transaction owner 前，不預設需要新增資料表。
- Index summary 的公開相容行為需先盤點 consumer。若無法立即改變既有預設，frontend 應先使用明確 cache-only mode，並逐步淘汰隱性 refresh。
- 效能門檻以本機開發 runtime 的可重複 probe 為主，不把單次數字當作跨硬體 SLA；若 payload 顯著增大，需同時記錄大小與解析成本。
