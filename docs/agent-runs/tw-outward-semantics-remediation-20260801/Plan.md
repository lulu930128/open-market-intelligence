# 實作計畫

## 里程碑 0：基線與施工邊界（已完成）

驗收條件：

- 建立 `Prompt.md`、`Plan.md`、`Progress.md`。
- 記錄 branch、dirty worktree、既有測試基線與可重現的 7/31 問題 probe。
- 將高風險問題轉成精準 regression/invariant tests。

驗證：

```powershell
$env:PYTHONPATH=(Resolve-Path '.\backend').Path
.\.venv\Scripts\python.exe -m pytest -q backend\tests\test_intraday_contract_remediation.py backend\tests\test_ai_market_context_projection.py backend\tests\test_ai_realtime_contract.py backend\tests\test_ai_capability_contract.py
```

## 里程碑 1：canonical index session/candidate contract（已完成）

實作：

- 統一 current session、previous completed session、intraday candidate、official candidate 的選擇語意。
- 隔離不同 `trade_date` 的 OHLC、trade value、official close 與 intraday point。
- 以 additive 欄位提供 reconciliation、selected candidate 與 source date。

驗收條件：

- TPEX/TWSE 在 current session 不會混入前一交易日 low/high/trade value。
- 收盤後仍可正確選擇 latest completed session。
- 缺資料、closing auction、post-close pending 與 stale point 都有明確狀態。

## 里程碑 2：breadth 與 public quality contract（已完成）

實作：

- 修正 `universe_count`、`coverage_count`、`classified_count`、`unknown_count` 的來源與合併方式。
- TWSE/TPEX universe definition 使用正確 market。
- 修正 composite index realtime root metadata。
- 補齊 `market.sample_ranking` 的 path、scope 與 unit semantics。

驗收條件：

- breadth 可對帳且 overflow 不被靜默隱藏。
- TWSE/TPEX component 與 combined 結果一致。
- 全數 live child 的 composite payload 可被 `require_live` 接受；mixed/partial 仍保守降級。
- sample ranking 不再產生 `volume_unit_missing`，且不冒充全市場排行。

## 里程碑 3：群族／產業共用 snapshot（已完成）

實作：

- 建立 market-owned canonical group/sector snapshot。
- 對齊 AI market context、watchlist group、sector/industry 與 consumer projection。
- 共用 universe、as-of、freshness、warnings、fallback 與 coverage。

驗收條件：

- 同一 request/run 不重複用不同資料面計算同一群族。
- group/sector consumer 對同一成分股集與 snapshot version 產生一致結果。
- fallback/partial 狀態對外可見。

## 里程碑 4：fill resolution 與 source lineage（已完成）

實作：

- 將 fill 結果分類為 success、no-op、blocked、partial、failed。
- 補 dependency / source health 映射，避免 capability 無法回溯實際 owner。
- 保留 bounded refresh 與 trust policy。

驗收條件：

- no-op 不再被誤當成功補齊。
- 每個 public capability 能指出資料來源、資料日期與 refresh 結果。
- GET/read path 不引入昂貴或無界 side effect。

## 里程碑 5：volume baseline warming 與 authority（已完成）

實作：

- 明示 same-time baseline 的 warming_up、sample size、expected days 與 authority。
- 區分 session cumulative、interval bar 與 provider-specific volume。

驗收條件：

- 歷史不足時不輸出偽精確比率。
- `warming_up` 與 `insufficient_history` 能被 AI/MCP/UI 同樣辨識。

## 里程碑 6：對外 consumer 與 runtime 驗證（進行中）

驗證層次：

1. market service / projection targeted tests。
2. `omi.decision.v4` public envelope。
3. MCP `initialize -> tools/list -> omi.ask`。
4. Frontend consumer projection（Kuro 已由使用者明確移出本輪範圍）。
5. 正式 launcher 選定的 backend/frontend port 與 live runtime。

目前進度：第 1、2、3、5 層已完成；第 4 層已完成 MCP adapter 的實際 payload
驗證，Frontend OMI dock 顯示驗收留待下一階段。Kuro 不再是本任務完成條件。

驗收條件：

- schema、semantics、freshness、warnings、missing 與 source lineage 跨 consumer 一致。
- runtime 證據來自正式 launcher，不以 isolated test port 代替 production proof。

## 里程碑 7：Planner、target 與 response projection P0（已完成）

實作：

- 建立 selection origin precedence，explicit required 不受 NLP exclude 影響。
- 在台股代號解析前遮罩 ISO date、民國／西元日期與獨立年份。
- Required list projection 以 requested limit／pagination cardinality 驗證完整性；
  無法在 budget 內保留時回明確 budget error，不宣稱 preserved。
- Regulation 與 capability inventory 使用 scope-aware intent allowlist。

驗收條件：

- 2026-08-01 驗收報告 P0-1 至 P0-4 與 capability inventory 案例都有 regression。
- explicit selection 與自然語言 inference 的 origin 可在 public selection 中稽核。
- compact response 的 `required_payload_preserved` 與實際 Top-N 數量一致。

## 里程碑 8：數值、availability、freshness 與 index P1（已完成）

實作：

- 正式收盤問句採 bounded quote-only contract，不自動擴張 general payload。
- 修正 optional capability 污染、融資融券來源單位與 quote availability invariant。
- 分離 trade/event/release/fetch/compute/serve time，避免 request time 冒充資料事件時間；
  基本面 release planner 依使用者決定延後，不在本輪接入 Radar。
- 標準化 TAIEX intraday bar classification、daily OHLCV adapter 與 index auction applicability。

驗收條件：

- 2026-08-01 驗收報告 P1-1 至 P1-9 都有明確 fixed／not-applicable／deferred 結果。
- selected capability quality 不受未選取資料污染。
- public v4、MCP 與 Frontend 不重算單位、availability 或 freshness。

## 里程碑 9：Radar v2 公開輸出接線（已完成）

實作：

- `watchlist.radar` 明示 active engine、v2 item、完整 universe、readiness 與 limitations。
- HTTP、AI v4、MCP snapshot 與 Frontend type/rendering 使用同一 backend projection。
- 保留 v1 frozen read-only 相容面，不新增 v1 寫入。

驗收條件：

- 所有 active Radar item 都標示 `radar_v2.0`，且 unverified/backtest missing 不被隱藏。
- Public Radar payload 不包含基本面 factor，也不依賴基本面 availability。
- Kuro 不列入本輪驗證面。

## 里程碑 10：跨 consumer 與正式 runtime 驗證（已完成）

- Targeted backend contract regression、MCP initialize/tools/list/omi.ask、frontend
  typecheck/lint 與正式 launcher live smoke 均通過。
- 不執行手動 Radar snapshot/backtest POST，不觸發大量外部 refresh。
- regression、frontend typecheck/lint 已通過；正式 launcher 於 17:16 嚴格識別並重啟
  source 較舊的 backend。live `omi.decision.v4` 已證明 active Radar v2、aggregate
  freshness current、quality ready、trust high，且 required capabilities 無 blocked。

## Stop-and-fix 規則

- 新增 regression 若揭露既有不一致，先局部修正 owner，不擴大成 unrelated rewrite。
- 任一里程碑若需要 DB migration、破壞相容性、外部大量 refresh 或付費 quota，先暫停並向使用者確認。
- 驗證失敗先判定是否由本次 diff 造成；相關失敗必須在進入下一里程碑前修正。
- 若 Radar 公開接線需要把基本面納入 scoring 或讓 consumer 重算 v2 邏輯，停止並維持現有 backend 邊界。
