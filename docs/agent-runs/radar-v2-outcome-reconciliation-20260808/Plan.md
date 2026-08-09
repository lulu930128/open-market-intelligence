# 計畫

## 執行狀態

- Milestone 1－4：已完成並通過 targeted regression、typecheck、lint 與單一 UI E2E。
- Milestone 5：production 唯讀 dry-run 已完成；依計畫停在實際 outcome catch-up 寫入前，等待使用者確認。

## Milestones

1. 建立 starvation regression
   - 範圍：83 個當期 candidate、超過 200 筆 pending path、混合已到期與未到期 horizon。
   - 驗收：已到期的新 T+1 在單次 bounded reconcile 內被選取，未到期 T+3/T+5 不占用 due budget。
   - 驗證：`pytest backend/tests/test_watchlist_radar_active_v2.py -q -p no:cacheprovider`

2. due-only 公平 reconciler
   - 範圍：path 粒度選取、due cutoff、缺 bar 輪替、candidate 初始化分離、可觀測統計。
   - 驗收：batch limit 只套用到期 path；相同 evaluation 合併 due horizons；future horizon 不阻塞。
   - 驗證：Radar v2 outcome／active targeted tests 與 compile check。

3. job、scheduler 與 late-data handoff
   - 範圍：獨立 reconcile job、daily-price completion handoff、週末／啟動 safety net、`partial_success`。
   - 驗收：未完成的 mature due work 可見；not-due 不算失敗；job bounded 且 idempotent。
   - 驗證：scheduler/job targeted tests 與 API contract tests。

4. API 與 UI contract
   - 範圍：POST reconcile、pending reason、日期／統計欄位、自然語言限制、MAE 呈現與 status event。
   - 驗收：GET 純讀；手動操作排入 reconcile job；錯誤集中到更新狀態；舊 payload 保留。
   - 驗證：frontend lint/typecheck、聚焦 E2E／browser screenshot。

5. production dry-run
   - 範圍：只讀 `EXPLAIN QUERY PLAN`、due／pending 影響數量與預估 batch。
   - 驗收：先向使用者報告數量與風險，未確認前不執行 outcome 寫入。
   - 驗證：read-only SQLite query 與 live GET 對照。

## Stop-and-fix 規則

- 若 regression 無法精確重現 4/30 starvation，停止修改 reconciler 並重新確認 fixture。
- 若需要 schema migration、外部 provider refresh、共用 runtime restart 或 production DB 寫入，先停止並取得確認。
- 若 UI 需要自行推算交易日或 freshness，停止並補 backend contract。
- 任何 targeted test 失敗先修復或證明與本案無關，再進下一 milestone。

## 決策

- GET history 維持無副作用；reconcile 使用明確 POST job。
- outcome 初始化與 due reconcile 採不同 budget。
- pending selection 以 `horizon_end_trade_date`、舊 `evaluated_at`、path id 排序，缺 bar 項目更新時間後輪替。
- frontend 預設顯示本地化限制摘要；raw code 僅保留於進階診斷。
