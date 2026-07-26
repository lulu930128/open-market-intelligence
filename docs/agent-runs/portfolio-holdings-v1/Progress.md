# Portfolio Holdings V1 Progress

## Current Status

- Backend, AI contract, and sidebar UI implementation in progress.
- Chosen direction: portfolio holdings are a backend domain, not watchlist item metadata.
- V1 markets: TW, US, JP, KR. Crypto is excluded because holding units and instrument semantics differ.

## Decisions

- Store one aggregate active holding per market/symbol for V1.
- Treat `cost_amount / quantity` as the average entry price used by AI position analysis.
- Keep watchlist groups and "持股中" separate so category management remains clean.

## Validation Evidence

- `.\.venv\Scripts\python.exe -m compileall backend\app` passed.
- `$env:PYTHONPATH='backend'; .\.venv\Scripts\python.exe -m pytest -p no:cacheprovider backend\tests\test_portfolio_holdings.py backend\tests\test_ai_ask_stages.py backend\tests\test_database_migrations.py` passed: 18 tests.
- `npm exec tsc -- --noEmit --incremental false` passed.
- `npm run lint` passed.
- `git diff --check` passed; only Git LF/CRLF warnings were printed.

## Known Follow-Ups

- Multi-lot tracking and broker import can be layered later without changing sidebar selection semantics.
- Crypto holdings need a separate asset/instrument/venue-aware position model.
