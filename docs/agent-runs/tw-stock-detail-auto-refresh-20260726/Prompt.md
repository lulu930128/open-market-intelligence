# 台股個股資料面板自動更新

## Goal

- 讓台股個股頁的籌碼、法人、分點、營收與盈餘資料，在各自正式發布／申報邊界後五分鐘自動補抓。
- 保留切換頁籤時的 lazy refresh 保險：本機資料已達 expected key 時不碰 provider，缺漏或過舊時才補抓。
- 排程、啟動補漏、provider readiness、partial/stale 與 job 結果均可觀測且可重試。

## Non-goals

- 不把 OMI 改成自動交易或自動下單系統。
- 不隱藏 provider failure、partial、stale、missing 或沒有統一發布時刻的事實。
- 不用無上限輪詢追逐逐公司申報，也不在 frontend 重做市場 freshness 邏輯。
- 不修改本次任務開始前已存在的其他 worktree 變更。

## Hard constraints

- Backend 是 expected key、refresh policy、scheduler 與 provider side effect 的真相來源。
- 完整三大法人個股檔採 TWSE 約 20:00 的正式產製時間，首次自動抓取為交易日 20:05。
- 融資融券採 TWSE 約 21:00 的正式產製時間，首次自動抓取為交易日 21:05。
- nStock 分點沒有公開固定分鐘，沿用保守 16:00 availability window，首次抓取 16:05，並保留 bounded reconciliation。
- TDCC 只承諾每週最後營業日結束後編製，沒有公開固定分鐘；沿用 Saturday 12:00 保守窗口，12:05 起做 bounded hourly reconciliation。
- 營收與財報是逐公司申報：營收在一般公司截止日後的每月 11 日 00:05 先收斂，保險延長族群在 16 日 00:05 再收斂；財報在各法定截止日結束後五分鐘收斂。
- 本機已達 expected key 時不得再發 provider request；啟動補漏與切頁保險仍保留。

## Context

- Repo: `C:\project\Open Market Intelligence`
- Related systems: backend scheduler、job queue、TWSE/TPEx/TDCC/nStock providers、source health、frontend stock detail tabs。
- Current known state: `ENABLE_SCHEDULER=false`，只有分點與部分市場籌碼排程獨立啟用；法人與個股融資券排程因此未啟用。前端切頁只讀 cache，手動更新才會觸發 provider，且營收／財報只用 row count 判斷。

## Deliverables

- 台股個股資料獨立排程設定、startup catch-up、bounded reconciliation 與 job/provider event。
- 營收與財報 expected key／release window。
- 前端 cache-first freshness guard：最新直接顯示，stale/missing 才啟動 selection refresh。
- Targeted backend/frontend tests、safe validation 與 runtime 排程證據。

## Done criteria

- Runtime scheduler 能列出法人 20:05、融資券 21:05、分點 16:05、TDCC Saturday 12:05 起補漏、營收 11/16 日 00:05 起補漏、財報四個法定收斂日 00:05 起補漏。
- 相同 expected key 已完成時 scheduler 不重複 enqueue provider fetch。
- 台股頁籤切換先讀本機；cache 已 current 時不 POST selection refresh，stale/missing 時才 POST。
- Targeted tests 與 repo 安全驗證通過，既有無關 dirty files 未被修改。

## Open questions / assumptions

- 「對應時間 5 分鐘」解讀為「發布／申報邊界後 5 分鐘」，不是每五分鐘永久輪詢。
- TDCC 與 nStock 沒有公開固定分鐘，因此其窗口是清楚標示的保守 policy，不宣稱為官方保證。
