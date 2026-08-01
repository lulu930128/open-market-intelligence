# Taiwan Watchlist Radar v2

## 2026-07-29 實際結構審查修正範圍

- 本階段目標是修正已確認會污染 Radar v2 shadow 研究資料的結構性問題，不啟用
  v2 為 active version。
- point-in-time 契約必須拆分市場資料有效時間、來源可用時間、決策時間與實際落庫時間；
  backtest 不得再以落庫時間冒充來源可用時間。
- v2 canonical evaluation 必須覆蓋完整計算母體，v1 mode／Top N 僅能作為 presentation
  projection，不得決定 v2 的研究樣本。
- 市場 regime 必須以 signal decision time 為上限，並保留 minute、breadth、quality、
  source 等可重現證據。
- signal event 必須有明確 observation／active／exit／unobserved 語意；evaluation 與
  event、outcome 與 event 都必須支援多對多關聯。
- backtest 必須真正按 purged walk-forward split 計算 train／validation／test，
  promotion gate 只接受 OOS test-fold 指標與完整母體 coverage。
- feature extraction hash、rule/scoring hash 與 market context identity 必須分離。
- scoring 必須接入可觀察的 strength、freshness 與 timeframe conflict；無法可靠取得時
  要留下 limitation，不得靜默使用滿分。
- overheat outcome 不得產生程式上不可達的 continuation／reversal；公司行動檢查需
  涵蓋所有目前 provider 能辨識且會改變未調整價格路徑的事件。

## 本階段非目標

- 不改變 v1 Radar public response、排序與 snapshot 歷史。
- 不依據目前空白 v2 資料直接調權或宣告命中率。
- 不把尚未有 point-in-time baseline 的結果標記為可 promotion。
- 不處理本 worktree 內與 Radar v2 無關的台股、美股或 frontend 改動。

## Goal

- 將台股 Watchlist Radar 升級為可版本化、可重播、可解釋、可多時間尺度驗證的研究系統。
- 先建立可信的 Outcome v2 與 point-in-time 回測契約，再調整技術訊號加權。
- 分離方向、證據、衝突、風險、信心、急迫度與排序語意。
- 保留 v1 歷史、API 相容性與快速回滾能力，讓 v2 先以 shadow mode 運行。

## Non-goals

- 不做自動下單、券商帳戶操作或保證績效的投資建議。
- 不把 Radar 簡化成單一漲跌預測或以命中率直接產生買賣建議。
- 不在第一階段導入黑盒機器學習、深度學習或自動調參。
- 不在缺少 point-in-time universe 與完整 coverage 前宣稱全台股回測有效。
- 不在 GET/read path 隱性執行大量回補、外部 refresh 或資料寫入。
- 不修改或刪除既有 v1 snapshot、outcome 與使用者資料。
- 不把 backend 市場邏輯搬到 frontend、MCP 或 Kuro。

## Hard constraints

- Repo：`C:\project\Open Market Intelligence`
- 台股是核心市場；其他市場只可作為有明確時間與 freshness 的 context。
- `data/open_market_intelligence.db` 只能透過 additive Alembic migration 演進，不得重建或覆寫。
- v1 public route、既有 response shape、snapshot idempotency 與歷史資料必須保持相容。
- v2 核心 evaluation 必須與 Watchlist group 解耦；group 只負責 membership、mode、rank 與顯示投影。
- 所有分數與 outcome 必須保存 `rule_version`、`feature_version`、`outcome_contract_version` 與 immutable `config_hash`。
- 相同輸入 manifest、版本與設定必須產生相同輸出。
- Feature 只能使用 `source_available_at <= decision_at` 的資料，且 decision 必須落在同一
  台股交易日；trade date 相同不等於當時已可取得。
- T+N 使用台股交易日曆；跨 split label 必須使用 purge / embargo 防止未來資料洩漏。
- Corporate action、stale、partial、missing、provisional、provider failure 與 outcome quality 必須可見。
- `entry_proxy_outcome` 只代表成交價格代理，不得命名或呈現為保證可成交的 executable result。
- 日線 OHLC 無法決定盤中事件先後時，必須回傳 path-order limitation。
- Alert cooldown 與研究樣本去重分離；不得因 UI 去重靜默刪除回測樣本。
- 現有 worktree 有其他進行中變更；本任務不得 revert、格式化或混入無關檔案。

## Context

- 使用者工程草案：`C:\Users\thoma\Downloads\OMI_台股Radar_v2技術規則與回測模型_工程草案_v0.1.txt`
- v1 真相來源：
  - `backend/app/market/indicator_service.py`
  - `backend/app/market/signal_service.py`
  - `backend/app/market/technical_structure.py`
  - `backend/app/watchlists/ranking_service.py`
  - `backend/app/watchlists/radar_service.py`
  - `backend/app/watchlists/radar_outcome_service.py`
  - `backend/app/watchlists/radar_automation.py`
  - `backend/app/routers/watchlists.py`
  - `frontend/src/components/WatchlistRadarPanel.tsx`
- 現有 DB contract：
  - `watchlist_radar_snapshot_run` 以 group/mode/date/rule scope 冪等。
  - `watchlist_radar_snapshot_item` 綁定 snapshot run。
  - `watchlist_radar_outcome` 對每個 snapshot item 只能保存一筆 outcome。
- 2026-07-29 唯讀 coverage 稽核：
  - `market_daily_price` 日期範圍為 2012-04-23 至 2026-07-29。
  - 最新交易日只有 83 個 stock rows。
  - 自 2024 年起至少有 250 個不同交易日、且更新至 2026-07-28 的 stock id 為 82 個。
  - Radar snapshot 範圍為 2026-06-18 至 2026-07-29，涵蓋 189 個不同 stock id。
- 因此初期回測是 bounded local research；未通過 coverage gate 前不是全市場績效聲明。

## Data contract

- `radar_feature_snapshot`
  - 保存 stock、effective/source-available/observed time、feature basis、input manifest、
    data quality 與 feature version。
- `radar_rule_evaluation`
  - 保存 v1/v2 的 decision time、direction、evidence、conflict、risk、confidence、priority、
    bucket 與 tags。
- `radar_signal_event`
  - 保存 onset、persistence、observation、unobserved、exit、retrigger 與穩定 event identity。
- `radar_universe_observation`
  - 保存完整 bounded calculation universe 的 evaluated/no-data/error/absent 狀態與 coverage 分母。
- `radar_evaluation_event_link` / `radar_outcome_event_link`
  - 保存 evaluation/outcome 與所有 active events 的 many-to-many 關聯。
- `radar_watchlist_projection`
  - 保存 group、mode、rank 與顯示投影，不擁有技術真相。
- `radar_outcome_path`
  - 每個 evaluation/event/horizon 保存 signal-reference 與 entry-proxy outcome、R 值、flags 與品質。
- `radar_backtest_run`
  - 保存 universe、coverage、split、purge/embargo、baseline、config 與統計輸出。

上述是責任模型；實際 SQL table 數量可在保持正規化、查詢效率與 migration 安全下調整。

## Scoring contract

- 技術方向、證據、衝突、風險、信心與 priority 分開。
- Signal 分為 event、state、modifier，並依 family 聚合與飽和。
- 需同時保存家族內衝突、跨家族衝突與時間框架衝突。
- 絕對分數使用固定公式與固定 cap；批次相對位置另存 `rank_percentile`。
- Context 初期只輸出 alignment / contradiction；不得靜默改寫 technical direction。
- `instrument_regime` 與 `market_regime` 分開；regime 權重在證明增量價值前只作實驗設定。

## Outcome contract

- 預設 horizons：T+1、T+3、T+5。
- 同時保存：
  - signal reference outcome：相對訊號收盤價。
  - entry proxy outcome：盤後訊號預設相對 T+1 open；不宣稱真實成交。
- 保存原始 OHLC、return、MFE/MAE、ATR-normalized R、非互斥 flags 與 UI summary state。
- Outcome flags 至少包含：
  - `intraday_triggered`
  - `close_confirmed`
  - `adverse_triggered`
  - `reversed`
  - `whipsaw`
  - `invalidated`
- 非方向型 compression、volatility、overheated 必須使用各自 outcome contract，不套用單一方向 hit/miss。
- Raw metrics 與 summary state 分開保存，summary state 可重算。

## Deliverables

- Radar v2 任務文件、工程設計與版本化設定。
- Additive Alembic migration 與 ORM models。
- v1 golden cases 與相容性 regression tests。
- Outcome v2、多 horizon 與 canonical event/evaluation service。
- Coverage audit、point-in-time backtest runner 與防洩漏 split contract。
- Signal Family v2、固定 normalization、conflict/risk/confidence 分數。
- Instrument/market regime contract 與 shadow evaluation。
- Backend API schema、shadow endpoints/fields 與 v1 fallback。
- Radar v2 summary-first frontend 呈現與 outcome path detail。
- Targeted backend/frontend/migration/API/runtime validation evidence。

## Done criteria

- v1 既有測試與 public contract 保持通過，歷史資料未被覆寫。
- 同一 feature snapshot 可重複計算 v1 與 v2，不複製 group-dependent 技術真相。
- T+1/T+3/T+5 outcome 可獨立 pending/evaluated，且沒有未來資料洩漏。
- Corporate action 與 entry proxy limitation 有明確狀態；缺資料時不猜測。
- 分數可逐 family / signal 解釋，絕對 grade 不受 Watchlist 組成影響。
- Backtest 輸出 coverage、樣本數、排除原因、baseline、confidence interval 與 regime stability。
- v2 可 shadow 運行，前端可辨識 v1/v2、資料品質與 outcome path。
- active version 可切回 v1，且回滾不需刪除 v2 資料。
- Tier 3/4 相關驗證通過，並完成至少一個本機 API/data smoke。

## Open questions / assumptions

- 初始 signal type factor、family cap、ATR outcome threshold、regime weight 與 context limit 都是實驗 config，不是已核准產品常數。
- 初期只使用本機既有資料，不主動做全市場外部歷史回補。
- Corporate event 能力若尚未提供足夠 adjusted-return contract，outcome 必須標記 partial/unevaluable，而不是套用不可靠修正。
- v2 初期預設 shadow-only；正式切換門檻由回測與前向觀察結果決定，不預先用單一 hit rate 定義。
