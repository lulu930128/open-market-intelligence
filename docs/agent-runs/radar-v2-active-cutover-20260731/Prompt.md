# Taiwan Radar v2 Active Cutover

## 背景

Radar v2 已具備 point-in-time feature、rule evaluation、event、universe observation、
outcome path 與 backtest 資料模型，但目前公開 `/radar`、Frontend、AI context 與 scheduler
仍以 v1 投影為主。v2 雖會評估完整計算 universe，公開結果與持久化 selected projection
仍受 v1 Top-N 影響，尚未形成獨立產品契約。

## 目標

1. 正式建立 `radar_v2.0` active contract。
2. 由 v2 對完整、受 `calculation_limit` 約束的 universe 自行計分、mode 篩選、排序與 Top-N 投影。
3. 由 backend v2 擁有公開 urgency、bucket、direction、priority、action、reason 與 limitations。
4. 台股既有 `/api/watchlists/groups/{group_id}/radar` 預設回傳 v2；`version=v1`
   只保留最後一份既有快照的唯讀歷史，不再動態計算。
5. scheduler 只持久化／reconcile active v2，不再新增 v1 snapshot、v1 outcome 或 shadow run。
6. 提供 v2 latest snapshot、history、outcome summary 與 bounded pending reconciliation。
7. Frontend 的主頁、history 與 outcome surface 都消費同一個 v2 公開契約。

## 非目標

- 不刪除、改寫或轉換 v1 snapshot/outcome 歷史資料。
- 不宣稱 v2 已具備優於 v1 的統計績效。
- 不把台股 Radar 變成自動下單或單句漲跌預測工具。
- 不修改美股、日股、韓股 Radar 的既有必填契約。
- 不做無關重構、dependency upgrade、commit 或 push。

## 硬性限制

- Radar GET 維持唯讀，不得觸發 DB 寫入或昂貴 refresh。
- freshness、stale、partial、missing、provider/data limitations 必須可見。
- v2 的公開方向與文案由 backend 擁有，Frontend 與 AI 不重算市場邏輯。
- v2 運行狀態與回測驗證狀態分開；即使 v2 已為 operational default，
  若 walk-forward / outcome 證據不足仍須顯示 `unverified` 或 `blocked`。
- 所有持久化使用現有 transaction owner，不由 router 手動管理交易。

## 交付物

- `radar_v2.0` active rule、feature、outcome contract 與 config hash。
- v2 完整 universe 公開投影。
- v2 active persistence、latest/history read model、outcome summary 與 reconciliation。
- `/radar` v2 default 與 `version=v1` frozen read-only history。
- v1 write route 明確回 `410 RADAR_V1_FROZEN`，scheduler v2-only。
- Frontend v2 active／history／outcome 呈現、AI context v2 projection。
- targeted backend/frontend tests、safe validation 與 runtime smoke 證據。

## 完成條件

- 相同輸入中，v2 可選出未出現在 v1 Top-N 的股票。
- v2 persistence 的 selected rows 等於 v2 Top-N，不再等於 v1 Top-N。
- `/radar` 預設 `radar_engine.active_version == "radar_v2.0"`。
- `/radar?version=v1` 只能讀取最後一份 v1 persisted snapshot，不會新增或重算資料。
- v2 snapshot/history/outcome read 不依賴 v1 snapshot item。
- scheduler 單一 scope 的 v2 失敗會清楚回報，且不把部分寫入宣稱成功。
- Frontend 與 AI context 顯示 v2 主輸出及未驗證限制。
- Frontend 不呼叫 v1 snapshot/outcome/history/evaluate endpoint。
- 相關測試、typecheck/lint 與 runtime smoke 通過，或失敗已明確隔離為既有問題。
