# Progress

## Status

- Current phase: source complete; formal launcher reload pending
- Last updated: 2026-07-26 Asia/Taipei

## Completed

- 已盤點 `taiwan_rules.py`、`calendar_status.py`、`scheduler.py`、daily/fundamental backfill、source health、job queue 與前端 `useTaiwanDataPanel.ts`。
- 已確認目前 `ENABLE_SCHEDULER=false` 導致法人／個股融資券自動排程未啟用；分點排程獨立啟用。
- 已確認前端切頁目前只讀 cache，營收／財報僅用 row count 判斷 current。
- 已查證 TWSE 三大法人完整檔約 20:00、融資融券約 21:00；證券交易法第 36 條的月營運與財報申報期限；TDCC 沒有公開精確發布分鐘。
- 已加入獨立 `ENABLE_TW_STOCK_DETAIL_SCHEDULER`，法人 20:05、融資融券 21:05、分點 16:05、TDCC Saturday 12:05、營收 11/16 日 00:05 與財報法定邊界後 00:05 的排程均不依賴全域 `ENABLE_SCHEDULER`。
- 已加入 startup catch-up、fundamental exact-target completion event、active job dedupe、partial/stale 可重試與 job retry contract。
- 已將切頁 lazy refresh 改為 cache-first expected-key guard；current 只讀本機，stale/missing 才 POST 既有 selection refresh，手動更新仍可強制刷新。
- 已修正已有舊財報季度時不再探測最新可申報季度的問題。

## Validation evidence

- Live API: 2026-07-26 Taiwan expected latest trading date is 2026-07-24。
- Live source health: 2330 institutional/margin/branch/shareholding current through 2026-07-24；revenue through 2026-06；financial through 2026Q1。
- Targeted backend regression：165 passed，涵蓋 release window、scheduler、startup catch-up、dedupe、source health、AI freshness 與 retry。
- Backend safe validation：compileall、全套 backend pytest、`git diff --check` 全部通過；log 在 `.tmp/validation/20260726-165735`。
- Frontend safe validation：ESLint、TypeScript、`git diff --check` 全部通過；log 在 `.tmp/validation/20260726-170140`。
- Frontend production build：Next.js 16.2.6 build 通過。
- Live UI cache smoke：`2330` 依序切換法人、分點、營收、盈餘與籌碼；新增 access log 中只有 cache GET，`selection-refresh POST = 0`。
- Current-code settings probe：`ENABLE_TW_STOCK_DETAIL_SCHEDULER=true`，各時間為 20:05／21:05／16:05／12:05／00:05。
- 目前 launcher-owned backend 仍是 2026-07-26 11:28 啟動的舊 runtime；live calendar 仍回法人 15:10、融資融券 21:10，故不能當成新排程已部署的證據。
- 任務期間出現其他 AI／美股契約相關 dirty changes；本任務未修改或回退它們。

## Decisions made

- Backend 提供所有 expected key 與 side-effect policy；frontend 只比較 key 並呼叫既有 selection refresh。
- 自動排程用獨立 enable flag，不打開會連帶啟動其他市場工作的全域 `ENABLE_SCHEDULER`。
- Fundamental snapshot 完成狀態會記錄 provider event，讓 startup/reconciliation 能對相同 target 去重。

## Known issues / risks

- nStock 分點與 TDCC 沒有官方固定分鐘，只能使用清楚標示的保守窗口。
- 逐公司申報可能早於截止日；本次自動收斂以法定截止為主，早期個股仍可由切頁保險補抓。
- Windows tray 操作的 Computer Use 授權逾時，因此沒有直接殺 PID 或繞過 launcher；正式 runtime 尚待使用 tray `Restart Services` 載入。

## Next step

- 從 OMI tray 選擇 `Restart Services`，再確認 launcher log 出現新 stock-detail schedule、`/api/market/calendar-status?market=tw` 回傳新 release window，以及 startup catch-up jobs/provider events。
