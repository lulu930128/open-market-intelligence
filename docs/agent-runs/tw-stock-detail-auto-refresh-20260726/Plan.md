# Plan

## Milestones

1. 查證與 freshness contract
   - Scope: TWSE/TPEx/TDCC/MOPS/nStock 時點、expected key、calendar/source health。
   - Acceptance: 固定時點與無固定時點的資料源被分開建模，時間與假設可見。
   - Validation: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_taiwan_rules.py backend\tests\test_trading_calendar.py`

2. Backend 自動更新
   - Scope: config、scheduler、startup catch-up、fundamental snapshot job、dedupe/event。
   - Acceptance: 五個頁籤所需資料都有獨立排程；latest skip、stale retry、partial observable。
   - Validation: targeted scheduler/fundamental tests and API job/provider-event probes。

3. Frontend 切頁保險
   - Scope: calendar expected key、cache-first freshness guard、selection refresh trigger。
   - Acceptance: current cache 不觸發 provider；stale/missing 保留 lazy refresh。
   - Validation: TypeScript typecheck、targeted Playwright route assertions when practical。

4. Runtime convergence
   - Scope: safe validation、launcher restart、actual scheduler/job/API evidence。
   - Acceptance: launcher-owned runtime 載入新 jobs，代表性 endpoint 與排程可見。
   - Validation: `.\scripts\run-safe-validation.ps1 -Profile backend`、frontend validation、launcher log/API probes。

## Stop-and-fix rules

- 若 expected key 在發布窗口前提前推進，先修正再進下一步。
- 若 scheduler 可能永久輪詢、重複全市場抓取或把 partial 當 complete，先修正再進下一步。
- 若 frontend current 判斷無法區分 cache 與 provider side effect，先修正再進下一步。
- 若測試或 runtime 證據與 code 不一致，不把 isolated test 當部署完成。

## Decisions

- 2026-07-26：採發布／申報邊界後五分鐘，不採永久每五分鐘輪詢。
- 2026-07-26：完整三大法人採 20:00、融資融券採 21:00 的正式產製時間。
- 2026-07-26：TDCC/nStock 沒有官方固定分鐘，採可見的保守窗口加 bounded reconciliation。
- 2026-07-26：營收分一般截止與保險延長截止兩次收斂；財報依年度／Q1／Q2／Q3 法定截止日收斂。
