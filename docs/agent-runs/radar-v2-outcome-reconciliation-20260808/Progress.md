# 進度

## 狀態

- 目前階段：implementation complete / production catch-up approval gate
- 最後更新：2026-08-08（Asia/Taipei）

## 已完成

- 從實際 UI、live API、SQLite、scheduler 與 service trace 確認 starvation root cause。
- 使用者已確認 due-only reconciler、獨立 POST job、backend pending reason 與最終 UI 方向。
- 已建立 83 個 candidates、201 筆舊 due backlog 與 1 筆新 due T+1 的 starvation regression。
- 已將 candidate outcome 初始化與 due path batch 分離，並以舊 `evaluated_at` 優先輪替缺 bar 項目。
- 已完成獨立 tracked reconcile job、daily-price completion handoff、啟動／週末 safety net 與 retry contract。
- 已完成 POST reconcile、backend pending reason 與前端自然語言呈現；raw limitation code 預設收合於進階診斷。
- 已完成 production SQLite 唯讀 dry-run，未執行任何 Radar outcome 寫入或 runtime restart。

## 驗證證據

- Group 3 calculation universe 有 83 candidates；舊實作 200 筆上限只剩 117 backlog slots。
- pending evaluation 排名使 2026-08-05 僅 rank 114-117 的 4 筆進入批次，與 UI 的 4/30 完全一致。
- 2026-08-06 所需 daily bar 已存在，但 outcome 仍為 0/30，排除「當下 OHLC 缺失」為主因。
- backend targeted suite：55 passed、60 subtests passed。
- frontend：TypeScript `--noEmit` 通過；ESLint 通過。
- 單一 Playwright smoke：`Taiwan radar uses v2 outcome history without v1 writes` 1 passed；復用既有 3000 dev runtime，未重啟服務。
- production 最新日線為 2026-08-07；科技股 group 3 的 T+1 狀態為：08/05 已定案 4、可檢查 26；08/06 可檢查 30；08/07 尚未到期 24、可檢查 6。
- 全部 active contract 目前有 1,323 筆 mature pending path；group 3 有 164 筆（T+1 134、T+5 30），其 horizon end bar 皆存在。
- production query plan 使用 `radar_outcome_path.status` index，另以 temp B-tree 排序；目前 backlog 規模無需為本案新增 migration。

## 已做決策

- 不修改 v1、Radar v2 rule/scoring 或 frozen history。
- 不在 production DB 執行 catch-up，直到 code validation 與 dry-run 數量獲得再次確認。

## 已知風險

- `data/open_market_intelligence.db` 約 14.6 GB 且由現行 runtime 持續更新；dry-run 數量是唯讀時間點快照。
- worktree 有大量其他功能變更，相關 dirty 檔案僅能套用局部 patch。

## 下一步

- 等待使用者確認是否允許對 production DB 執行 bounded catch-up；確認前維持唯讀。
