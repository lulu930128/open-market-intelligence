# 韓股指數成交量與操作效能改善

## 目標

- 修正 KOSPI 等韓股指數盤中成交量被重複累加、量柱從開啟頁面後逐步墊高的問題。
- 降低韓股指數切換、盤中輪詢與手動更新時的等待與重複工作。
- 讓韓股 intraday API 明確交付成交量語意、單位、累計量與資料品質狀態。
- 掃描韓股前後端主要操作路徑，完成可局部交付的高優先改善並記錄其餘建議。

## 非目標

- 不把韓股提升為與台股相同的產品主線。
- 不重寫共用圖表、韓股 watchlist 或整個 market dashboard。
- 不修改既有 `resource_market`、設定、共用 K 線引擎等未提交工作。
- 不新增付費資料源、全市場無邊界 backfill 或自動交易能力。

## 硬性限制

- Backend 保有成交量語意、freshness、provider merge 與 refresh 策略的真相來源。
- 保留既有 `/api/kr-market/indices/{index_id}/intraday` route 與既有欄位相容性，只做向後相容擴充。
- Naver intraday 頁面量視為區間量，realtime `aq` 視為當日累計量；不得再把累計 snapshot 當成單分鐘量。
- 外部請求必須有 pages、timeout、cache 與輪詢邊界。
- 不刪除、重建或覆蓋 `data/open_market_intelligence.db`。

## 背景

- Repo：`C:\project\Open Market Intelligence`
- 相關系統：`backend/app/kr_market`、KR FastAPI routes、`KRMarketPanel`、`IntradayTrendChart`、KR sidebar。
- 2026-07-15 live runtime 基線：KOSPI intraday 回傳 415 points，但只有 356 個唯一分鐘；最新 point 的 `volume=355816`、`cumulative_volume=null`，前端加總為 19,338,237。
- Naver realtime live payload 同時提供 `aq` 累計量；目前後端把它放入 point `volume`，且保留帶秒 timestamp，造成每次輪詢新增一個累計 snapshot。
- worktree 已有未提交的 resource-market、設定與共用圖表變更，需完整保留。

## 交付物

- 韓股 intraday backend merge/volume 修正與 targeted regression tests。
- 向後相容的成交量 metadata/freshness contract。
- 韓股畫面量單位、來源、輪詢更新與動畫/重複互動改善。
- Targeted backend tests、frontend typecheck/lint/build 與 runtime/browser 證據。
- 本任務 Progress 與後續 API 建議。

## 完成條件

- Realtime point 以分鐘為 canonical key，同一分鐘不因輪詢秒數新增重複點。
- Realtime `volume` 是由累計量差分得到的區間量，`cumulative_volume` 保留 provider 累計值。
- API 提供可供 consumer 正確標示的 volume unit/semantics 與 total volume。
- `refresh=true` 在同交易日已有 cache 時只做 incremental refresh，不重抓完整日資料。
- 韓股 UI 不再把成交量標成台股「張」，且圖表輪詢不會每次重播 reveal animation。
- 相關測試與前端檢查通過；live runtime 若未重啟，需明確標記為 stale-process 限制。

## 開放問題 / 假設

- Naver 指數成交量以千股、成交值以百萬 KRW 呈現；以 provider table/realtime contract 與目前 payload 交叉驗證。
- 初次載入仍需抓取當日多頁分鐘資料；本次先消除重複全量 refresh，是否再做持久化 intraday cache 留作後續評估。
