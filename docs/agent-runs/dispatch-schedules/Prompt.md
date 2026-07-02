# 定時派報 v1

## Goal

在既有派報功能上新增可由 UI 手動設定的定時派報：使用者可以選收件群組、模板、市場/自選群組、雷達設定、內容深度、寄送時間與執行日期，後端依排程自動 queue 既有 mail delivery job。

## Non-goals

- 不做自動交易或下單。
- 不做大漲/大跌觸發派報；先保留為後續版本。
- 不在 frontend 重做寄信或市場資料邏輯。
- 不讓 GET/read path 產生寄信 side effect。

## Constraints

- 台股仍是核心；美股只作為總覽 context。
- 排程設定必須存在 backend DB，不能只存在瀏覽器 local state。
- 寄送要重用既有 dispatch preview / delivery / job queue path。
- 同一排程同一分鐘只能觸發一次，避免 scheduler tick 重複寄信。
- SMTP secrets 仍只由環境變數提供，不落 DB 或前端。

## Deliverables

- `dispatch_schedule` migration 與 ORM model。
- `/api/dispatch/schedules` CRUD 與立即試跑 API。
- scheduler tick 掃描 due schedules。
- 派報設定 dialog 的排程管理 UI。
- README / env example / tests。

## Done Criteria

- 可以建立、編輯、刪除排程。
- 排程到點會 queue `dispatch.mail_delivery`。
- 手動試跑會 queue delivery，但不阻擋下一次正式排程。
- 測試覆蓋 migration、建立排程與 run key dedupe。
