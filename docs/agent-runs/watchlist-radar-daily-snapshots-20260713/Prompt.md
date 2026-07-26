# Watchlist Radar Daily Snapshots

## Goal

讓台股 Watchlist Radar 對所有 UI 可選的 active group，在每個交易日收盤後保存一份可回測快照，並在後續交易日資料可用時自動評估 T+1 outcome。

## Runtime Evidence

- 2026-07-13 畫面選取 `group_id=4`，`action` mode 有雷達結果，但 snapshot history 為空。
- 既有 2026-07-09、2026-07-10 scheduler jobs 顯示 success，但只處理 active root groups。
- `group_id=3` 有歷史，`group_id=4` 沒有歷史，證明 scheduler scope 與 UI scope 不一致。
- 2026-07-10 job 回報 `saved_count=8`，實際只新增兩筆 snapshot；其餘 scope 重用了舊資料日期的 snapshot，屬於假成功計數。

## Requirements

- `SCHEDULER_WATCHLIST_RADAR_GROUP_IDS` 留空時涵蓋所有 active groups，不只 root groups。
- snapshot 必須符合 scheduler 預期交易日；stale radar 不得冒充當日快照。
- idempotent 重跑必須區分 `created` 與 `existing`。
- 每日 job 結果必須包含 coverage，列出缺漏 scope。
- 服務晚啟動或首次執行失敗時，收盤後要能 bounded retry。
- 既有 manual snapshot API 與 outcome API contract 保持相容。

## Non-goals

- 不刪除或重寫既有 SQLite snapshot/outcome。
- 不在 GET/read path 隱性寫入 snapshot。
- 不擴大成全市場無邊界歷史回補。
- 不改變 radar rule version 或命中判定規則。

## Done Criteria

- active child group 會被預設 automation scope 覆蓋。
- stale payload 會被拒絕保存並出現在 job errors/coverage missing。
- 同日重跑回報 existing，不增加資料列也不誤增 saved count。
- reconciliation 在設定時間前不執行，時間後可補跑，完整 coverage 後不重複 enqueue。
- targeted tests、backend validation 與 isolated API smoke 通過。
