# Plan

## Milestones

1. Define registry boundary
   - Scope: `backend/app/crypto_market/assets.py`
   - Acceptance: registry can describe asset priority, default subscription mode, CoinGecko id, local TWD pair, global spot, and perpetual support.
   - Validation: import/use from unit tests.

2. Generate backend provider contract from registry
   - Scope: `backend/app/crypto_market/contract.py`
   - Acceptance: existing provider contract API shape remains; `SUPPORTED_INSTRUMENTS` and `COINGECKO_COIN_IDS` are derived from registry.
   - Validation: `python -m unittest backend.tests.test_crypto_market`.

3. Generate default data subscriptions from registry
   - Scope: `backend/app/settings/market_data_subscription.py`
   - Acceptance: registered assets appear in defaults; only BTC is always-on; existing commodity defaults are preserved.
   - Validation: `python -m unittest backend.tests.test_market_data_subscription_settings`.

4. Source-health universe follows registry
   - Scope: `backend/app/crypto_market/source_health.py`
   - Acceptance: source health checks all registered supported spot/perpetual instruments instead of a fixed BTC/ETH/USDT list.
   - Validation: crypto backend tests plus source-health spot check if local API is running.

## Stop-and-fix Rules

- If API response shape breaks, fix before extending coverage.
- If a provider/symbol is not supported by registry capabilities, it must be skipped explicitly, not inferred.
- If tests expose stale hardcoded assumptions, update the implementation or test intent before proceeding.

## Decisions

- 2026-06-26: Use a code registry first, not a DB-backed asset master. This keeps the schema stable while removing multi-file backend hardcoding.
- 2026-06-26: Register major assets but keep non-BTC defaults as `on_select` to avoid unbounded background refresh.
