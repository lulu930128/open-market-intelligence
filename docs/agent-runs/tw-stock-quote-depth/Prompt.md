# Taiwan Stock Quote Depth

## Goal

- Add a Taiwan stock five-level quote-depth path for the selected stock detail view, with session-aware labeling for preopen auction, regular live trading, closing auction, empty early-morning wait state, and post-close final snapshot.

## Non-goals

- Do not build a full order book history collector or all-market polling job.
- Do not add automated trading, order routing, broker integration, or execution controls.
- Do not redesign the whole stock detail page.
- Do not hide missing, stale, empty, or provider-failed quote data.

## Hard constraints

- Taiwan stock data remains a backend-owned market-data contract; frontend only renders the response.
- External TWSE MIS fetches must be bounded to one requested stock and short cached to avoid repeated provider hits.
- Five-level quote sizes must be labeled as lots, not shares.
- API responses must expose phase, freshness/status, provider/source, fetched time, and error or empty-state messages.
- DB schema changes must go through Alembic migration.

## Context

- Repo: `C:\project\Open Market Intelligence`
- Related systems: backend market data, SQLite/Alembic, `/api/market/*`, Next.js stock detail UI.
- Current known state:
  - `backend/app/market/intraday.py` already fetches TWSE MIS `getStockInfo.jsp` for selected stocks.
  - Live probes confirmed `a/b/f/g` fields provide ask prices, bid prices, ask lots, and bid lots for TWSE/TPEX symbols.
  - Prior memory notes warn TWSE MIS availability can fail in this environment, so fallback and visible freshness are required.

## Deliverables

- Backend quote-depth service that parses TWSE MIS five-level quote data and persists latest snapshots.
- Alembic migration and ORM model for Taiwan stock quote snapshots.
- Market API endpoint for selected-stock quote depth.
- Frontend type, polling state, and right-column quote-depth panel in `StockDetailPanel`.
- Focused backend tests and safe validation evidence.

## Done criteria

- `GET /api/market/quote-depth/{stock_id}` returns a typed, session-aware response for a known Taiwan stock.
- The stock detail right column shows five-level depth on the `today` timeframe and clear empty/status states outside live windows.
- Unit tests cover parsing, session boundaries, and migration table creation.
- Safe validation passes or any remaining failure is clearly isolated.

## Open questions / assumptions

- Use TWSE MIS as the first provider because existing OMI code already depends on it for intraday snapshots.
- Store only bounded snapshots for selected stocks; broader archival collection can be designed later if needed.
