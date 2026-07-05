# 韓股 v1 進度

## Current Status

- Backend v1 implementation is in place, including watchlist resource readiness and bounded refresh observability.
- Basic frontend workbench is wired into the existing market dashboard structure.

## Decisions

- 韓股 v1 follows JP market API shape where practical.
- KRX/OpenDART are the official-source direction; Yahoo chart is allowed only as visible per-symbol daily price fallback.
- Korean market scheduler remains disabled by default.
- GET endpoints read local DB state; refresh endpoints and jobs perform external IO.
- Frontend uses the existing sidebar, ranking, chart, resource slot, settings, jobs and OmiAsk dock patterns; no separate KR app shell is introduced.
- KR frontend v1 stays lighter than JP/TW where backend evidence is still limited, while keeping source health, stale and provider failure visible.

## Completed

- Confirmed `docs/product/` files are TODO templates only.
- Confirmed existing JP/US backend patterns for market data, watchlists, jobs, scheduler, source health.
- Added KR SQLAlchemy models and Alembic migration.
- Added `app.kr_market` parser/source/service/source-health/trading-calendar module.
- Added `/api/kr-market` FastAPI router.
- Added KR watchlist resource refresh job type, task wrapper, optional scheduler registration, and refresh execution policy.
- Added mocked KR backend tests for parser, DB upsert, source health, watchlist refresh, ranking, OHLC, readiness and route registration.
- Updated README and `.env.example` with KR provider settings and limitations.
- Added KR frontend types, preload wiring, URL state, sidebar entry, watchlist explorer, ranking/radar panel, detail panel, data slots, source-health view and refresh controls.
- Enabled KR in shared market switchers, refresh execution settings, job status filters and source disclosure settings.
- Added Traditional Chinese KR UI copy, with concise English/Japanese market summaries for the shared market picker.
- Added an idempotent `scripts/seed-kr-tech-watchlist.py` seed for the user-provided Korean tech stock hierarchy.
- Applied KR DB migration `20260705_0030` to the local SQLite database and seeded `科技股` with 39 groups, 68 watchlist items and 65 unique stock master rows.
- Added `/api/kr-market/watchlists/readiness` for read-only watchlist data coverage checks across daily price, investor trades and fundamentals.
- Extended KR watchlist resource refresh to include investor trading data by default, support bounded `max_symbols`, and report complete/partial/failed symbol counts plus resource-level success/error counts.
- Confirmed a bounded 3-symbol live refresh currently updates daily prices through Yahoo fallback while KRX investor trading returns provider errors; the backend keeps this visible as `partial_success` instead of hiding or aborting the batch.

## Known Issues

- KRX Data Marketplace direct download endpoint behavior still requires live hardening; daily price currently falls back to Yahoo chart, and investor trading is visible as provider error in live smoke.
- OpenDART fundamentals require `OPENDART_API_KEY`; without it refresh should be skipped with visible explanation.
- Korean holiday handling is a conservative fixed-holiday/weekend approximation; lunar and ad hoc KRX holidays need a future official calendar source.
- AI Korean stock decision brief is still deferred.
- Browser/runtime visual smoke has not been run yet; current verification is backend compile/tests, safe validation, Alembic current, local KR seed summary and bounded KR live refresh smoke.

## Next Step

- Wire readiness and partial resource status into the KR frontend surface, then run a browser smoke through the KR tab.
