# Radar v2 到期結果結算修復

## 目標

- 修正 Radar v2 outcome backlog 因固定批次與未到期 horizon 混排而飢餓，確保已到期的 T+1／T+3／T+5 能公平結算。
- 讓 late daily bar、週末與 runtime 啟動後都有 bounded reconcile 路徑。
- 由 backend 明確提供 pending 原因與資料日期，讓歷史畫面用自然語言呈現結算狀態與資料限制。

## 非目標

- 不改 Radar v1 frozen history。
- 不改 Radar v2 現行選股規則、分數或 active-version 邊界。
- 不在 GET history/read path 觸發 refresh 或 outcome 寫入。
- 不在未確認前改寫 production SQLite outcome 資料。

## 硬限制

- 保留 worktree 既有且與本案無關的變更，所有 patch 維持局部。
- backend 擁有交易日、到期判斷、freshness、pending reason 與 limitation 語意。
- reconcile 只讀取已保存 OHLC；外部 provider refresh 維持獨立、bounded job。
- UI operation failure 送到共用「更新狀態」，不得新增重複 inline error banner。
- 不重啟共用 tray/runtime；需要 browser smoke 時使用隔離 runtime。

## 背景

- Repo：`C:\project\Open Market Intelligence`
- 影響面：Watchlist Radar v2 backend service、scheduler/job、API、history modal 與 SQLite 查詢。
- 已確認根因：每次 200 筆限制先放入 83 個當期 candidate，再以 evaluation 粒度加入最舊 pending；同一 evaluation 未到期的 T+3/T+5 會持續占位，導致 2026-08-05 只結算 4/30、2026-08-06 0/30。

## 交付項目

- 大 backlog starvation regression。
- due-only、path-granularity、公平輪替的 reconciler 與統計。
- 獨立 reconcile job、late-price handoff、週末／啟動 safety net、明確 POST endpoint。
- additive outcome summary/item contract 與 Radar v2 history UI。
- targeted backend tests、frontend lint/typecheck 與聚焦 UI 驗證。

## 完成條件

- 超過 200 筆 backlog 時，已到期的較新 T+1 不再被未到期或持續缺 bar 的舊 horizon 永久阻塞。
- 2026-08-07 於 2026-08-08（週六）顯示尚未到期，預期 T+1 交易日為 2026-08-10。
- 已到期但缺 bar、可結算、未到期三種 pending 狀態可由 backend contract 明確區分。
- 手動「重新檢查結果」建立 bounded job，完成後 reload；失敗保留舊資料並送共用更新狀態。
- 預設 UI 不顯示 raw limitation code，MAE 使用風險色且不加正號。

## 假設

- 本次先沿用既有資料表；只有 `EXPLAIN QUERY PLAN` 證明需要時才提出 migration/index。
- production catch-up 會在 dry-run 數量確認後另行取得使用者同意。
