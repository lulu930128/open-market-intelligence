# Plan

## Milestones

1. Canonical instrument contract
   - Scope: non-mutating read normalization、watchlist read DTO、Taiwan selection state。
   - Acceptance: `ETF` 舊值在新 UI contract 統一為 `etf`，但不重寫 stock master；ETF selection 不靠群組名稱或前端代號推論。
   - Validation: targeted unit tests and frontend typecheck.

2. ETF backend capability
   - Scope: provider/parser、models、Alembic migration、service、schemas、GET/POST routes、provider events。
   - Acceptance: cache-only GET、最多 2-call refresh、profile/NAV idempotent upsert、partial/missing/stale 可見。
   - Validation: `backend/tests/test_tw_etf_capability.py` and migration tests.

3. ETF frontend work surface
   - Scope: ETF profile/NAV panel、company-only data gating、shared 更新狀態 integration。
   - Acceptance: ETF 保留行情／技術面，不顯示營收／財報 tabs；provider failure 不產生重複 inline banner。
   - Validation: frontend lint/typecheck/build and focused UI check if runtime is safely available.

4. Regression and boundary audit
   - Scope: targeted backend/front-end validation、diff audit。
   - Acceptance: ordinary stock path unchanged；AI/MCP outward interface has no task-generated diff。
   - Validation: safe validation profiles, `git diff --check`, targeted path audit.

## Stop-and-fix rules

- 若 migration 無法從目前 head 升級且保留資料，先修正再做 UI。
- 若 provider parser 無法在正常、empty、malformed payload 間明確區分，先修正 contract。
- 若 ETF selection 仍可因 route hydration 丟失 type，先修正 state propagation。
- 若 frontend 為 ETF 發出 company revenue/financial refresh，視為 regression，先修正再交付。
- 若變更碰到 AI/MCP/Kuro outward contract，立即縮回本任務邊界。

## Decisions

- 2026-08-09：profile 使用 TWSE OpenAPI；盤後 NAV 使用 MOPS 指定日期查詢；不自動化抓取 e添富頁面。
- 2026-08-09：本期不宣稱即時 iNAV；`daily_close_nav` 與未來 `intraday_estimated_nav` 保持不同 capability。
- 2026-08-09：沿用現有 `StockDetailPanel` 行情／技術骨架，僅替換 ETF 的資料面板，避免大規模 chart refactor。
- 2026-08-09：為隔離 AI/MCP outward contract，不重寫 `stock_master.instrument_type` 原始 casing；canonical `etf` 僅由新 watchlist／ETF API／selection contract 投影。
