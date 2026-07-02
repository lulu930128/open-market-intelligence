# Plan

## Milestones

1. Contract and storage
   - Scope: ORM model, Alembic migration, Pydantic/API schema.
   - Acceptance: empty SQLite migration creates `taiwan_stock_quote_snapshot`.
   - Validation: `.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs backend\tests\test_database_migrations.py`

2. Backend fetch/parse service
   - Scope: selected-stock TWSE MIS fetch, quote-depth parser, session phase, cache, snapshot upsert.
   - Acceptance: mocked MIS payload returns five bid and ask levels with lots, best bid/ask, spread, phase, and source metadata.
   - Validation: `.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs backend\tests\test_taiwan_stock_quote_depth.py`

3. Frontend stock detail integration
   - Scope: `TaiwanStockQuoteDepth` type, selected-stock polling, right-column quote depth panel.
   - Acceptance: `today` stock view renders quote-depth status without moving K-line layout or duplicating selection controls.
   - Validation: `.\scripts\run-safe-validation.ps1 -Profile frontend`

4. End-to-end safety pass
   - Scope: backend/frontend quick validation.
   - Acceptance: quick profile passes.
   - Validation: `.\scripts\run-safe-validation.ps1 -Profile quick`

## Stop-and-fix rules

- If migration or model metadata diverges, fix schema before frontend work.
- If TWSE MIS parsing cannot distinguish empty depth from provider failure, return a visible `source_unavailable` or `no_depth` status.
- If frontend text overflows or the right column becomes unstable, reduce density before adding more metrics.

## Decisions

- 2026-06-30: Keep five-level quote-depth backend-owned and selected-stock only to avoid all-market polling and provider load.
- 2026-06-30: Use distinct phases for `closed_waiting_preopen`, `preopen_auction`, `regular_live`, `closing_auction`, `post_close_snapshot`, and `market_closed` so UI can label data honestly.
