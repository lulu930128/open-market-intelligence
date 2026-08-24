# Plan

Status: complete（2026-08-22；runtime adoption 與 startup catch-up 已驗證）

## Milestones

1. 固定 contract 與 persistence
   - Scope: dataset registry、SQLAlchemy model、Alembic migration、Pydantic projection。
   - Acceptance: checkpoint 可 idempotent 保存 expected date、universe hash、coverage counts 與 resume cursor。
   - Validation: `pytest backend/tests/test_eod_coverage.py backend/tests/test_database_migrations.py`

2. 實作 cache-only coverage 與 bounded repair
   - Scope: TW/US universe owner、coverage query、TW bulk source refresh、US bounded per-symbol shard。
   - Acceptance: current/stale/missing 分類正確；US 已 current symbol 不重抓；partial/provider failure 保留進度。
   - Validation: `pytest backend/tests/test_eod_coverage.py backend/tests/test_market_daily_parse_pipeline.py`

3. 串接 tracked job、scheduler 與 startup catch-up
   - Scope: job task、dedupe、APScheduler periodic/startup job、config/env。
   - Acceptance: `ENABLE_SCHEDULER=false` 時 coverage scheduler 仍可獨立啟動；同 market 不會同時跑兩個 reconcile。
   - Validation: `pytest backend/tests/test_eod_coverage_scheduler.py backend/tests/test_calendar_status_integration.py`

4. 串接 cache-only API 與完成 regression
   - Scope: GET/POST router、OpenAPI、README/operation notes、migration/registry/API tests。
   - Acceptance: GET 無 provider I/O；POST 回 202 tracked job；safe backend validation 通過。
   - Validation: `.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs @('backend\tests\test_eod_coverage.py','backend\tests\test_eod_coverage_scheduler.py','backend\tests\test_database_migrations.py','backend\tests\test_market_data_registry.py','backend\tests\test_api_contract_inventory.py')`

## Stop-and-fix rules

- 若 migration 會 drop/recreate 既有 market tables、測試資料列遺失或 downgrade 無法安全說明，先修正再進下一步。
- 若 TW bulk parser 會以少量 payload 覆蓋較完整同日資料，先加入 regression guard。
- 若 US repair 可能無界執行、使用 Alpha Vantage quota、重複掃 current symbols 或在 rate limit 後密集重試，先修正。
- 若 GET path 產生 provider I/O、DB write 或 job side effect，停止並調整 owner。
- 若 current product truth 或現有 dirty Market Data Foundation diff 與本計畫衝突，暫停並更新 Prompt.md。

## Decisions

- 2026-08-22：v1 只處理 latest completed-session daily OHLCV；全市場 intraday/depth 不在可重建範圍。
- 2026-08-22：TW 與 US 都以正式 full-market stock universe 計算 coverage；watchlist 只可作 consumer，不作 universe truth。
- 2026-08-22：US 無 bulk daily provider時採 bounded shard＋durable resume，不宣稱單次全市場完成，也不自動消耗 Alpha Vantage quota。
- 2026-08-22：coverage checkpoint 與 JobRun 分工；checkpoint 保存 dataset state，JobRun 保存每次 execution evidence。
