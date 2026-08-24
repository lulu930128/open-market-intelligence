# KGI SuperPy 選取個股即時行情與成交流

## 目標

- 將凱基 KGI SuperPy 設計為台股選取個股的即時行情、五檔與試撮第一來源。
- 只有使用者正在查看個股時才建立 quote-only 訂閱；沒有 viewer 時取消訂閱。
- 凱基尚未就緒、斷線、過期或設定不完整時，沿用既有 TWSE MIS / 本機快照路徑。
- 憑證只放在本機 `.env`，不進前端、API payload、log 或版本控制。
- 第二階段將已選個股的 KGI callback 建成 bounded market stream：近期成交、1 分 K、五檔衍生值與試撮軌跡，並由 SSE 推送給前端。
- Quote Depth 一般盤右欄顯示即時成交；試撮進行中顯示試撮即時，試撮結束後可切換保存快照觀看。
- 以明示 POST 建立 KGI Data bounded fetch，白名單涵蓋盤中快照、當日成交明細、歷史分 K 與分價量，並逐項揭露 entitlement。

## 非目標

- 不串接持倉、帳務、下單、改單、刪單或自動交易。
- 不將 KGI 擴大成全市場常駐 collector。
- 不以 KGI 自動取代 canonical 歷史分鐘 K、盤後日資料、官方收盤價或大盤廣度來源；Data records 在 schema 與權限完成驗收前保持 bounded raw response。
- 不在本階段建立無界限 tick／K 棒資料庫，也不建立自動警示或交易觸發器。
- 不修改既有資料庫 schema。

## 硬限制

- Backend 擁有 provider 選擇、freshness、試撮語意與 fallback 真相。
- Frontend 只管理 viewer lease，不自行判斷 provider 或改寫市場語意。
- KGI SDK 必須是選配依賴，未安裝或未填憑證時 OMI 仍可正常使用既有來源。
- KGI SDK 置於獨立 quote-only 子程序；子程序命令面只允許行情訂閱生命週期。
- 只有收到當日且 freshness 合格的 KGI event 後才能升為第一來源。
- 近期成交只能表達價格相對前筆的 `up/down/flat`；provider 未提供主動買賣方時，不得推論成內外盤或買賣方向。
- SSE read path 不得自行建立 provider 訂閱；只有既有 viewer lease 能啟動行情，斷線時仍保留 snapshot polling fallback。

## 第二階段能力契約

- Market / target：台股上市櫃普通股與 ETF 的整股代號；沿用 `StockMaster.stock_id` normalization。
- Provider：`kgisuperpy 2.1.0` 正式環境、帳號密碼登入、選定標的才訂閱；TWSE MIS / 本機 snapshot 維持第二來源。
- Resource：`Quote.subscribe_all(..., odd_lot=False)` 的 Tick、五檔、`diff_*`、`simtrade`，另訂 `Quote.subscribe_kbar(..., minute=1)`。
- Timestamp：quote 為 `YYYYMMDDHHMMSS`、KBar 為 `YYYYMMDDHHMM`，都以 `Asia/Taipei` 解讀；另外保留 OMI UTC received time。
- Bounds：每個 lease symbol 最多保留 60 筆正式成交、120 筆試撮觀察與 120 根 1 分 K；最後一位 viewer 離開後清除。
- Persistence：只放 provider manager process memory，不改 DB schema；歷史圖表仍使用既有 canonical service。
- Failure：disabled、warming、stale、reconnecting、permission failure 與 KBar unavailable 都要可見；quote 成功但 KBar 失敗時不得讓整體 quote fallback。
- Public API：新增單檔 bounded snapshot 與 SSE stream；public schema 只暴露行情欄位、capability status、source 與 warning，不暴露 credentials 或 SDK internals。
- Consumer：frontend 只呈現 backend 的 recent trades、auction observations、KBar 與 depth metrics，不自行重算 freshness 或推論成交方向。

## 完成條件

- 選取個股會建立有 TTL 的 KGI quote lease，切換或離開時會退訂。
- 多個 viewer 可共用同一檔訂閱，不重複建立 WebSocket topic。
- KGI event 可映射到既有 quote-depth public contract，包含五檔與 `simtrade` 試撮。
- KGI 不可用時回傳既有來源，並可見 primary source 狀態與 fallback 原因。
- `.env.example`、安裝腳本與 README 說明需要填寫的欄位。
- targeted backend tests、frontend typecheck/lint 與安全驗證通過。
- 一般盤 Quote Depth 右欄能由 SSE 顯示近期成交；試撮盤與 replay 右欄維持正確試撮語意。
- Backend snapshot 能揭露 recent trades、auction observations、1 分 K、五檔不平衡、spread 與 `diff_bid_vol` / `diff_ask_vol`，並保留 bounded limits、source 與 freshness。
