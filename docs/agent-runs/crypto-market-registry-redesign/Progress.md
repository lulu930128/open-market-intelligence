# Progress

## Status

- Current phase: completed
- Last updated: 2026-06-26 22:05 Asia/Taipei

## Completed

- Confirmed current backend hardcodes crypto assets in provider contract, default subscriptions, and source health.
- Confirmed local runtime currently refreshes BTC always-on while ETH/USDT are stale/on-select.
- Added a backend crypto asset registry for BTC, ETH, USDT, SOL, BNB, XRP, DOGE, TON, and LINK.
- Generated provider instruments, CoinGecko IDs, default subscription items, source-health coverage, service defaults, and auto-refresh targets from the registry.
- Kept background auto-refresh conservative: only always-on assets enter the scheduler; non-BTC assets default to on-select.
- Added provider-contract and subscription tests for the expanded registry.
- Added a crypto-specific watchlist service/API backed by `AppSetting` so custom crypto groups/items persist without polluting Taiwan stock watchlists.
- Updated the Crypto sidebar to follow the Taiwan watchlist layout: the upper Crypto tree reads the persisted crypto watchlist directly, the resource commodity/currency reference stays fixed, status sits below the list, and group/asset management stays in the bottom action area.
- Aligned the Crypto sidebar visual shell with the Taiwan/US/JP sidebar rhythm: selected summary header plus Reload, shared row heights and active colors, scroll list, status block, and bottom management controls.
- Matched the Crypto bottom management controls to the existing sidebar form template and added an initial default crypto root group when no persisted crypto watchlist setting exists.

## Validation Evidence

- `.\.venv\Scripts\python.exe -m compileall backend\app\crypto_market backend\app\settings` passed.
- `$env:PYTHONPATH='backend'; .\.venv\Scripts\python.exe -m unittest backend.tests.test_crypto_market backend.tests.test_market_data_subscription_settings` passed, 28 tests.
- Schema smoke confirmed `CryptoProviderContractRead` accepts `assets` and 35 generated instruments.
- Crypto watchlist smoke confirmed a `SOL` item can be persisted and listed from an in-memory DB.
- `npm exec tsc -- --noEmit --incremental false` passed.
- `npm run lint` passed.
- `Invoke-WebRequest http://127.0.0.1:3000/?market=crypto` returned 200.
- Live `/api/crypto-market/watchlists/tree` returned one default root group from backend config while the local `app_setting` table still had no persisted `crypto_watchlist` row.

## Decisions Made

- Build a backend code registry first and preserve existing database schema/API response shapes.
- Expose registry metadata through `provider-contract.assets` so frontend can later consume the backend asset universe.
- Use `AppSetting` JSON for crypto sidebar watchlists in this phase; reserve full DB tables for future crypto ranking/radar workflows.
- Keep Crypto sidebar behavior aligned with the Taiwan sidebar pattern; avoid separate top/bottom watchlist sources or duplicate selector controls.

## Known Issues / Risks

- Binance/OKX support flags are based on conventional public symbols; live exchange availability is still verified during refresh and unsupported combinations must fail visibly.
- The registry is code-backed, not user-editable DB-backed yet; a real self-selected coin universe still needs a later asset-master/settings design.
- Frontend asset options are now expanded to the backend registry's current asset set, but they are still statically mirrored instead of fully consuming `provider-contract.assets`.

## Next Step

- Wire frontend crypto selectors/types directly to `provider-contract.assets` so future backend registry additions appear without a frontend code edit.
