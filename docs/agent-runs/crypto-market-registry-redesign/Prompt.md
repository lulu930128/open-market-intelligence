# Crypto Market Registry Redesign

## Goal

- Redesign the crypto backend so major crypto assets are declared once in a backend registry and then used to derive provider instruments, market-cap ids, default subscription items, and source-health coverage.

## Non-goals

- Do not add exchange private APIs, order placement, automatic trading, or execution-adjacent behavior.
- Do not migrate existing crypto data tables in this step.
- Do not make every registered asset always-on by default.
- Do not redesign the frontend workflow in this backend milestone.

## Hard Constraints

- Existing crypto REST API response shapes should remain compatible.
- `BTC` remains the only always-on default unless explicitly changed later.
- Provider, exchange, symbol, and database identity values must stay stable and unlocalized.
- Unsupported provider/symbol combinations must remain visible as unsupported instead of silently producing bad data.
- Crypto remains a market-data research layer, not an automated trading system.

## Context

- Repo: `C:\project\Open Market Intelligence`
- Related systems: backend crypto market contract/service/source-health, settings subscription defaults, SQLite cache, tests.
- Current known state: provider instruments and CoinGecko ids are hardcoded in `backend/app/crypto_market/contract.py`; default crypto subscription items are hardcoded in `backend/app/settings/market_data_subscription.py`; source-health default symbols are hardcoded in `backend/app/crypto_market/source_health.py`.

## Deliverables

- Backend registry module for crypto asset definitions.
- Contract/instrument generation from registry.
- Default market-data subscriptions generated from registry.
- Source-health default universe generated from registry-supported instruments.
- Focused backend tests for registry coverage and existing behavior.

## Done Criteria

- Adding a mainstream crypto asset requires editing the backend registry only for backend coverage.
- `provider_contract()` exposes generated instruments for BTC/ETH/USDT and additional major assets.
- Default subscription settings include major crypto assets while only BTC is always-on.
- Existing crypto backend tests pass.

## Open Questions / Assumptions

- Major assets in v1: `BTC`, `ETH`, `SOL`, `BNB`, `XRP`, `DOGE`, `TON`, `LINK`, plus `USDT` as local TWD reference.
- Binance and OKX spot/perpetual support will be represented as registry capability flags; BitoPro TWD pairs remain limited to known supported assets.
