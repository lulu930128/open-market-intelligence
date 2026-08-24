# 台美全市場 EOD Coverage Checkpoint v1

## Goal

- 讓 backend 對台股與美股的 latest completed-session daily OHLCV 維護可持久化的全市場 coverage checkpoint。
- 將尾盤／盤後補齊從個股頁面的按需讀取中分離，改由明確 job、scheduler 與 startup catch-up 擁有。
- 即使工作中途因程式或電腦關閉而中斷，下一次啟動仍可從 SQLite 既有資料與 checkpoint 繼續，不必重新由第一檔開始。

## Non-goals

- 不保存全市場逐筆、即時 quote、order book 或 intraday bars。
- 不承諾電腦關機期間仍能執行；只在下次 backend 啟動後補抓可重建的 completed-session EOD 資料。
- 不在本次新增付費 provider、broker execution 或自主交易行為。
- 不把美股 ETF、test issue 或尚未被官方 symbol directory 列為 active 的標的混入 v1 stock universe。
- 不做無界歷史 backfill；v1 repair 只追 latest completed-session checkpoint。

## Hard constraints

- Repo: `C:\project\Open Market Intelligence`
- GET 必須是 cache-only，不得暗中 call provider 或啟動 subscription。
- 台股 universe 使用 active TWSE／TPEx ordinary stocks；台股 EOD refresh 使用既有 TWSE／TPEx official bulk sources。
- 美股 universe 使用 active Nasdaq Trader symbol directory 中的 non-ETF、non-test stocks；現有 daily provider 只能逐 symbol，因此 repair 必須有每次 symbols、timeout、sleep、錯誤數與 runtime 上限，且不得消耗 Alpha Vantage quota。
- Partial、stale、missing、provider failure、interrupted 與 rate-limited 必須如實保存，不得用成功狀態掩蓋。
- Provider／parser 不直接擁有 checkpoint transaction；coverage service 擁有 checkpoint commit／rollback。
- 既有 `market_daily_price`、`us_daily_price` 與 public per-symbol API shape 保持相容。
- migration 不得刪除、重建或清空 `data/open_market_intelligence.db`。

## Context

- Related systems: Market Data Foundation、TW/US market services、SQLite、JobRun、APScheduler、HTTP API。
- 2026-08-22 本機 active universe：台股 1,973 檔；美股 non-ETF、non-test stock 7,427 檔。
- 2026-08-21 本機 coverage：台股 `market_daily_price` 僅 132/1,973；美股 enabled watchlist 亦有大量 stale／missing。
- 現有 `tw.daily.ohlcv` 與 `us.daily.ohlcv` registry 是 per-symbol bounded contract，尚無 full-market lifecycle owner。
- 現有美股 scheduler 只處理 watchlist，且逐檔 sleep；無法代表 full-market coverage。

## Capability contract

| 項目 | v1 contract |
|---|---|
| Product scope | 台股 reference market 與美股 first-class research market 的 completed-session EOD data foundation；不產生交易建議。 |
| Target | TW：active TWSE/TPEX ordinary stocks。US：active Nasdaq Trader non-ETF、non-test stocks。symbol 依既有 owner normalize。 |
| Provider | TW：TWSE/TPEx official bulk。US：Nasdaq Trader 只擁有 universe；daily OHLCV 暫由 Yahoo chart bounded per-symbol repair，不使用 Alpha Vantage quota。 |
| Resource | Finalized daily OHLCV；checkpoint 另保存 expected date、universe identity、current/stale/missing/partial 與 cursor。 |
| Freshness | TW Asia/Taipei latest released trade date；US America/New_York 16:05 後 latest completed trade date。 |
| Request bounds | TW 最多 2 個 official bulk calls。US 每個 job 有 max symbols、sleep、max errors 與 max runtime；scheduler job max_instances=1。 |
| Persistence | 新增 migration table；同 dataset/scope/expected date/universe hash idempotent upsert；每日保留歷史 checkpoint。 |
| Failure | Provider error、rate limit、empty/partial payload、interruption均保留 checkpoint 與 job evidence；不把 missing 轉成 0。 |
| Transaction | TW source pipeline 各自 commit；US per-symbol store 各自 commit；coverage service 在每個可恢復邊界 upsert checkpoint。 |
| Public API | Cache-only GET `/api/market-data/eod-coverage`；explicit POST `/api/market-data/eod-coverage/reconcile` 回 202 JobRun。 |
| AI contract | v1 不新增 decision slot；後續可讓既有 `market_daily_price.full_market_coverage` missing flag consume checkpoint。 |
| Consumer | Frontend/MCP 可只讀 backend checkpoint，不重算 universe/freshness/provider semantics。 |
| Validation | Pure coverage、service persistence、bounded repair、scheduler/startup、API/OpenAPI、migration regression。 |

## Deliverables

- Coverage checkpoint model 與 Alembic migration。
- 台美 universe coverage 計算與 cache-only projection。
- 台股 official bulk repair、美股 bounded resumable repair 與 tracked job。
- Scheduler periodic reconciliation 與 startup catch-up。
- GET/POST API、registry contract、設定與操作文件。
- Targeted backend tests 與 migration validation。

## Done criteria

- 空白 SQLite 可 migrate 到 head，且 legacy/current data 不被破壞。
- 測試能證明 TW/US current、stale、missing 分類與 universe hash 穩定。
- 中斷後再跑時，已 current symbols 不會重新抓取，cursor/progress 可繼續。
- GET 不執行 provider I/O；POST 與 scheduler 只建立 bounded tracked job。
- 台股 partial bulk payload 不會 destructive replace 較完整的同日資料。
- 相關 targeted tests 與 backend safe validation 通過。

## Open questions / assumptions

- 美股現有 provider 無單次全市場 OHLCV endpoint；v1 以 bounded shard 可續跑補齊，checkpoint 會如實顯示尚未完成。若要保證每個交易日快速全市場完成，後續仍需可合法使用的 bulk EOD provider。
- 本功能依賴 OMI backend 啟動；電腦關機時不會執行，啟動後只補可重建 EOD，不偽造關機期間即時 snapshot。
