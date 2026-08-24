# KGI 即時行情後續 Roadmap

本文件記錄 KGI SuperPy 選股即時行情第一版完成後的擴充方向。它不是已完成能力清單；尚未實作或尚未通過正式環境驗證的項目，必須維持 `planned` 或 `provider_not_connected`，不得在 UI / API 宣稱為可用。

## 2026-08-18 實作狀態

- 已完成：selected-symbol SSE、bounded snapshot fallback、近期正式成交、試撮事件分流、1 分 K callback contract、五檔衍生值、來源／freshness／warning 狀態與 viewer lease cleanup。
- 已通過正式 runtime callback：近期成交與五檔衍生值。
- 待交易時段 live acceptance：1 分 K callback 與試撮即時軌跡。
- 尚未開始：alerts、有限 watchlist 多標的訂閱、持久化 tick／盤中 K 歷史，以及美股 KGI provider。
- 已完成：保存的所有試撮快照在同一格依時間合併，以及 KGI Data 四資源 bounded fetch contract。

## KGI Data 回補能力評估

KGI 的 `Quote` callback 與 `Data` 盤中／盤後資料是兩條不同能力線。現有即時畫面使用 `Quote`；若要補回使用者尚未開啟畫面前的資料，應另外建立 bounded `Data.get(...)` adapter，不可把 callback ring buffer 宣稱為歷史資料。

- 已建立白名單 fetch：`取得今日即時成交明細(含五檔報價)`、`取得歷史分K(指定日期前)`、`取得指定日期前幾天的分價量歷史資料`、`批次取得個股盤中行情-含興櫃(tick含試搓)`。
- 正式帳號 bounded smoke 結果：盤中行情快照可用，回傳 1 列；當日成交明細、歷史分 K、分價量均回 `D403`，目前契約狀態是 `plan_restricted`，不是空資料或程式失敗。
- 盤中行情快照只能視為當下狀態；目前未發現可重建完整歷史試撮軌跡的等價 Data table。
- 五檔歷史不可直接假設完整：當日成交明細雖標示「含五檔報價」，帳號仍未取得 schema，開通後需再次做單一標的 bounded schema smoke 才能進 canonical contract。

Data adapter 已可透過明示 POST 回傳 bounded raw records 與逐資源 entitlement；它不在 GET read path 自動執行，也尚未寫入 canonical 歷史表。OMI 的即時試撮軌跡仍只代表 viewer lease 存在期間收到的 callback；既有早盤、尾盤與延後撮合固定時點快照會在同一張盤後明細表合併顯示。

## 已完成的台股來源能力

- KGI 作為選定標的即時行情第一來源，既有 TWSE MIS / DB snapshot 保留為 fallback。
- 僅在使用者查看標的時取得 lease 並訂閱；離開、切換標的或 TTL 到期後釋放，不做全市場常駐收集。
- 可映射最新成交價、時間、單筆量、累計量、開高低、昨收、漲跌與漲跌幅。
- 可映射五檔買賣價量、最佳買賣價、spread 與五檔總量。
- 可辨識盤前／收盤試撮資訊；試撮指示價量不得當成正式成交。
- API 保留 provider、fallback、freshness、warning 與 primary-source 狀態。
- Backend 接收 KGI callback 後，以 selected-symbol SSE 推送 bounded snapshot；EventSource 失敗時退回 1 秒 snapshot polling。既有 quote-depth API 仍保留約 5 秒 polling，負責 canonical 五檔／來源 fallback。
- OMI AI / MCP 可在 viewer lease 存在時使用 KGI quote-depth context，但不得假設未訂閱標的也有即時資料。

## 台股後續擴充優先序

### P1：真實瀏覽器 push

- 由 backend 以 SSE 或 WebSocket 將已選標的事件推送至 frontend。
- 保留 snapshot API 作為首次載入、斷線恢復與 fallback，不讓 frontend 自行重建市場語意。

### P1：近期成交與盤中 K 棒

- 建立有固定上限的 recent-trades ring buffer，提供價、量、方向判讀所需的原始欄位與事件時間。
- 聚合或直接使用 provider 的 1 分 K，供當日走勢與 K 線使用；需處理重連、重複事件、缺口與 session 邊界。
- 第一版不做無界限 tick 落庫，也不把 KGI 當成歷史日 K 的唯一來源。

### P2：五檔與試撮衍生訊號

- 五檔買賣量不平衡、spread 變化、`diff_bid_vol` / `diff_ask_vol` 等短線觀察值。
- 試撮價格與量的時間序列、異常跳動與開盤／收盤前提示。
- 價格、成交量與 spread 的 bounded alerts；警示需帶來源、時間與 freshness。

### P2：有限 watchlist 訂閱

- 只訂閱畫面可見或使用者明確選定的一小組 watchlist 標的。
- 設定連線、標的數、事件速率與退訂上限；不發展成全市場 collector。

### 保留既有來源的資料

- 歷史日 K、基本面、籌碼、官方收盤價與全市場掃描仍由既有專責來源提供。
- KGI 盤中資料是即時 context；正式收盤與交易日事實仍以交易所／既有 canonical provider 為準。

## 美股 KGI 能力確認

依 KGI SuperPy 官方文件及本機安裝的 `kgisuperpy 2.1.0` API surface，美股提供 WebSocket callback 型即時行情：

- `USQuote.subscribe_all(symbol)`：最新成交加最佳一檔買賣價量。
- `USQuote.subscribe_tick(symbol)`：最新成交、OHLC、單筆量、累計量、漲跌與成交金額。
- `USQuote.subscribe_bidask(symbol)`：best bid / best ask 與各自數量。
- `USQuote.subscribe_kbar(symbol)`：即時 1 分 K callback。

官方欄位只有最佳一檔買賣價量，未提供台股式五檔陣列。因此美股第一版應標示為 Level 1，不得在 UI 稱為「五檔」。

官方參考：

- [美股訂閱 Tick 與 BidAsk](https://superpy.kgieworld.com.tw/kgipythonapi/guide/us/quoteSubscribeAll)
- [美股訂閱 Tick](https://superpy.kgieworld.com.tw/kgipythonapi/guide/us/quoteSubscribeTick)
- [美股訂閱 BidAsk](https://superpy.kgieworld.com.tw/kgipythonapi/guide/us/quoteSubscribeBidAsk)
- [美股 callback 與 KBar](https://superpy.kgieworld.com.tw/kgipythonapi/guide/us/quoteSetCB)
- [美股使用條件](https://superpy.kgieworld.com.tw/kgipythonapi/guide/us/terms)
- [美股連線數](https://superpy.kgieworld.com.tw/kgipythonapi/guide/us/connectionCount)

## 美股第一版建議邊界

- 沿用 quote-only bridge 與相同登入生命週期，但 IPC action、subscription state 與 symbol namespace 必須按 `market=us` 隔離。
- 使用者選到美股後才呼叫 `USQuote.subscribe_all`；必要時另訂 1 分 K，不做全市場常駐。
- KGI 第一來源提供 latest trade、OHLC、volume、best bid / ask、spread、1 分 K、source health 與 freshness。
- 既有美股 provider 保留為第二來源；fallback 時需揭露 KGI 未連線、無權限、stale 或 market closed。
- AI compact context 可加入 Level 1、spread、盤中量價與 1 分 K，但不能把 Level 1 推論成完整 order book。
- 台股仍是 OMI 核心市場；美股即時資料作為台股研究的跨市場 context layer。

## 尚待正式環境驗證

- KGI 美股目前沒有模擬環境；測試只能在正式環境做 bounded quote-only 訂閱。
- 文件顯示 API 支援即時行情，但帳號實際行情權限、交易所 entitlement、標的覆蓋與 `delay_time` 行為仍須用真實 callback 證明。
- 連線數與每條連線可訂閱標的數依會員等級而異；文件中的 A+ 範例不能直接當成本帳號上限。
- 驗證前狀態保持 `planned/provider_not_connected`。建議在美股交易時段只測一檔（例如 `AAPL` 或 `TSM`），記錄 subscribe event、第一筆 callback、`delay_time`、事件時間與退訂結果，全程不呼叫 Account / Order / position API。
