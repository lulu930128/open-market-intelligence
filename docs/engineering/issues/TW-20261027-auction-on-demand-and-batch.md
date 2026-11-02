# TW 單股盤前試撮按需刷新與多檔批次：設計紀錄

日期：2026-10-27。狀態：**已紀錄、未實作新功能**。此文件是限縮範圍的工程觀察與候選方案，不代表正式 Runtime/Frontend 已驗收。

## 目前已驗證

- 10/27 盤前透過 OMI 正式 omi.ask 以 prefer_live 並明確允許有界刷新，2330、2317、6488 皆能取得今天的 MIS 試撮價、量、事件時間並寫入 Raw Receipt / Canonical；之後 cache_only 讀取可重取證據。
- backend/app/market/taiwan_realtime_platform.py：TW_REALTIME_MAX_AGE_SECONDS = 15。這是有效期限，**不是每隔 15 秒必須背景取得**；過期保留 stale，而非將試撮當實際成交。
- backend/app/market/providers/twse_mis.py：get_stock_response(codes) 支援以管線符號組合多碼且最多 20 檔（OMI 設定上限，不是官方硬限制），fetch_stock_messages(codes) 亦為批次；twse_mis_current_breadth.py 市場廣度每批 100 檔。混合 TWSE/TPEx 應分 Venue 並驗證資源資格，不直接假定同請求混合可用。
- 目前正式單股 Provider Descriptor 在 tw_public_quote.py 與 tw_realtime_capabilities.py 的 MIS Quote / Auction / Depth 均 max_symbols_per_call=1、SINGLE_SYMBOL_ONLY；twse_mis_realtime_acquisition.py 也只取 get_stock_response([symbol])。**底層 HTTP 能多檔，不等於已支援一次多股 Canonical 寫入**。
- backend/app/routers/market.py：GET /quote-depth/{stock_id} 為純讀，POST /quote-depth/{stock_id}/refresh 為顯式有界取得；backend/app/routers/tw_public_quotes.py 同樣有單股公開報價 read/refresh 路徑。未發現正式多股 batch refresh route；omi.ask 的 tw_stock 仍為單 Target。
- frontend/src/components/stock-detail/useTaiwanQuoteDepth.ts：詳細頁輪詢 GET，並未直接接入上述 POST 按需 Refresh，因此 stale 畫面可能不更新。既有 Viewer Lease / SSE Presentation Stream 不等於 Canonical Quote/Auction Freshness。
- 背景 Quote Contract Scheduler 目前屬小規模驗收 Canary；截至 08:50 source health 僅驗收 2330，08:30 不合格、08:50 合格，非全市場持續刷新。
- Source Health 曾因舊的 2026-08-26 ProviderEvent failure 顯示 unavailable，即使 2026-10-27 MIS 已成功回應；ProviderEvent Freshness 與最新成功 Receipt 證據需要在既有 Source Health Owner 檢視，不能將舊錯誤視為現在 API 停用。

## 後續最小實作方向（未執行）

1. **單股按需**：使用者選股、展開報價區或點選刷新時，先讀原 Canonical Freshness。若超過 15 秒再經已有 POST Refresh Owner 有界取得、等待回傳、重新讀取；GET 永遠保持無副作用。加 in-flight dedup／timeout／guard／429/backoff；換股、隱藏或離開頁面不得持續為已離開的股票刷新。標記 event_time、stale、provisional；不得將 pz 試撮價寫成 z 成交價。
2. **多檔**：若後續要實作，沿既有 Gateway/Planner/Provider Adapter/Transaction 以最多 20 檔分批並依 Venue 分組；一次原始回應可承載多筆訊息，每股仍獨立驗證 identity、日期、trade session、Quality、Raw Receipt Lineage 與 per-stock failure。共用 Provider Guard、timeout、rate limit、call budget；不可再建立第二套 Provider Manager、Cache、Gateway 或 Consumer parser。
3. **回歸 Gate**：單股 stale GET 零 I/O、顯式刷新後可讀回；未取得試撮不得偽造；批次超過 20、缺 symbol、重複 symbol、跨 Venue、部分失敗、429 等需 fail-closed 或 partial。UI 需檢查 stale / provisional 標籤與是否確實使用正式刷新指令。
4. Live/Runtime/Frontend 仍需以已載入版本、實際 API／頁面與盤中事件驗收；Source 可行不等於部署完成。

**目前結論：單股按需已具正式 API 能力；多檔 MIS Transport 已存在，但完整多股 Canonical Refresh 尚未實作。本輪只留紀錄。**


## 2026-10-27 09:09–09:13 正式盤中觀測（本次診斷補記）

- 09:09 Workspace Canonical：TWSE 本輪收到 399/1080、方向合格 19；TPEx 收到 396/887、方向合格 38；兩個市場均 partial、decision_usable=false，均有 failed batch，缺少大量實際 z。
- 09:12 最新讀取：TWSE 598/1080、合格 31；TPEx 793/887、合格 75。09:13 再次讀取又縮小到 TWSE 299/1080、合格 10，TPEx 396/887、合格 40。這代表**最新一次有界掃描的 Coverage 會上下波動**，不是跨時間累加式全市場完整度。
- 09:13 詳細原因：TWSE 第 4 批 timeout，其後 7 批 budget_exhausted；TPEx 第 5 批 timeout，其後 4 批 budget_exhausted。missing_z_rescue 均為 skipped：剩餘工作預算不足。Provider response 是否在其他時段恢復尚未以此證據證明。
- 針對 2330、6488 的明確 prefer_live 個股查詢均因 TWSE_MIS_PREVIOUS_TRANSPORT_IN_FLIGHT 失敗，兩次 external_calls=0，未實際發出新 HTTP；2330 最後報價 Event Time 09:07:55，累計 9102 張但 last_trade_price=None；6488 最後可查到 09:01:57 的 845 元實際成交證據，但已 stale。
- 原因路徑：backend/app/market/providers/twse_mis_breadth_evidence.py::bounded_fetch 使用 _IN_FLIGHT[venue] 限制最多一個尚未完成的來源傳輸；Caller Deadline 過期不代表 OS socket worker 已停止，因此仍持有 slot，單股 Refresh 與全市場 Breadth 會競爭同 Venue Slot。這是既有 bounded worker 防止資源爆量的保護；不是可以直接取消 Lock 或 reset IO Slots 的理由。
- backend/app/market/providers/twse_mis_current_breadth.py::_cache 在 partial 時仍更新目前 TTL Cache，但只有完整無 Failed/Skipped/Deadline 的快照才提升至 _LAST_GOOD；_stale 只在刷新整體失敗或 Circuit Open 路徑使用。由此可合理解釋不同時間的最新 Partial Received/Directional Coverage 下降；**並不表示 Source 回填先前未知值或已取得完整 Universe**。
- 判斷：指數正式盤中資料流正常提供當日值；MIS 批次廣度目前不足以供決策。此次發現應列為「正式盤中 Operational Blocker／Architecture Risk」，不應直接判成 Parsing Code Defect；單股按需與多股批次的設計必須保留 Shared Venue In-Flight、Guard 與有限資源的公平調度，避免多股並行觸發更多阻擋。

後續 Gate（尚未實作）：調查超時批次的 transport latency 和 scan budget、單一 Venue in-flight 長度／恢復時間、partial snapshot vs Last-Good 的呈現、z 缺值及補查資格；以不增加無界 IO／不竄改成交價的原則做定點壓測與修復。無使用者額外授權前不重啟 Backend、不強制 reset in-flight、不改 DB／Source 或自行擴大為架構重構。
