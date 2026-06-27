# Crypto Market Realtime Backend And Trading Boundary

## Goal

- Add a future OMI backend plan for a crypto-only market domain that is separate from all stock markets.
- Support realtime crypto market data with provider-specific roles:
  - BitoPro for `BTC/TWD`, `ETH/TWD`, `USDT/TWD`, Taiwan-dollar market prices, and Taiwan exchange spread observation.
  - Binance and OKX for global `BTC/USDT` primary prices, high-liquidity order book data, perpetual funding rates, and open interest.
  - CoinGecko for coin ranking, global market cap context, and 24h gainers/losers.
- Keep crypto strategy and possible future live execution isolated from OMI stock-market research flows.
- Start with read-only realtime data, then deterministic paper trading, then evaluate a gated crypto-only execution service.
- Add a default, watch-only resource/commodity data folder beside crypto:
  - `虛擬貨幣` for crypto market data.
  - `商品` for resource futures context such as gold, silver, copper, WTI crude, Brent crude, and natural gas.
  - The commodity folder is not a watchlist and is not trade-enabled.

## Non-goals

- Do not enable automatic trading for Taiwan stocks, US stocks, Japan stocks, ETFs, indices, Taiwan futures, or any non-crypto market.
- Do not connect AI decision core to order placement. Crypto strategy should start deterministic and rule-based.
- Do not build high-frequency trading, market making, millisecond arbitrage, or exchange colocated infrastructure.
- Do not store exchange API keys in code, local database rows, frontend state, logs, or committed files.
- Do not let frontend, MCP, Kuro, or AI tools bypass backend crypto risk gates or call exchange trading APIs directly.
- Do not use CoinGecko as an execution-price source.
- Do not rely on scheduler polling as the primary realtime trading feed.
- Do not make commodity/resource futures tradeable in this milestone.
- Do not build a user-managed watchlist for the crypto/resource page; the first version uses default pinned folders only.

## Hard Constraints

- Repo: `C:\project\Open Market Intelligence`
- The existing OMI product rule says OMI is not an automatic trading system. Any live crypto execution must be treated as an explicit crypto-only exception and kept outside stock-market flows.
- Implementation should use a new backend domain, for example `backend/app/crypto_market/`, rather than extending `backend/app/market/`, `backend/app/us_market/`, `backend/app/jp_market/`, or `backend/app/ai/`.
- Crypto must be 24/7 aware. Do not reuse Taiwan trading-day/session assumptions for crypto freshness.
- Realtime market data should be WebSocket-first. REST should be used for bootstrap snapshots, backfill, fallback, and low-frequency metrics.
- Latest tradeable state should live in memory or a low-latency runtime cache. SQLite is for audit, bars, snapshots, market-cap/ranking context, and historical summaries, not every order book delta.
- Every feed and derived signal must carry freshness metadata: `event_time`, `received_at`, `feed_lag_ms`, `last_message_age_ms`, provider, symbol, instrument type, and stale/gap status.
- Strategy code must not place orders directly. It emits candidate signals or intents that pass through a separate crypto risk gate.
- Live execution, if ever implemented, must be disabled by default and require explicit environment configuration, API-key permission checks, kill switch, max notional/position limits, idempotent client order IDs, exchange reconciliation, and audit logs.
- Automatic trading is explicitly the final milestone. It must not be started until read-only crypto data coverage is complete, source health/freshness is visible, and the full frontend crypto workflow is implemented and operating normally.
- BTC is the only current future trade candidate. ETH, USDT, and all commodity/resource instruments are watch-only unless a later explicit approval changes that boundary.
- Resource/commodity market data must stay in an isolated backend domain, for example `backend/app/resource_market/`, and must not extend stock watchlists or crypto execution paths.
- API keys must be read from environment variables or a documented local secret mechanism only. No secrets in repo docs beyond placeholder names.
- Provider failure, stale data, sequence gaps, partial depth, and degraded source health must remain visible in API responses and logs.

## Context

- Current backend has no dedicated crypto module yet.
- Existing reusable backend patterns:
  - `backend/app/observability/provider_health.py` records provider events and source health snapshots.
  - `backend/app/db/models.py` already has `ProviderEvent`, `SourceHealthSnapshot`, `MarketIntradayBar`, and Taiwan futures quote/bar tables with provider-aware uniqueness.
  - `backend/app/jobs/scheduler.py` has Taiwan futures polling, but its interval model is not enough for crypto execution-grade realtime data.
- Existing Taiwan futures scheduler defaults are useful as a comparison point, not as a crypto execution design:
  - `scheduler_taiwan_futures_interval_seconds` defaults to 30 seconds.
  - Collector interval is clamped to at least 10 seconds.
  - This is acceptable for monitoring, not for trade execution based on fast crypto order books.
- Crypto market design should align with OMI source-health principles while remaining isolated from AI and stock-market decision flows.

## Deliverables

- Backend-only crypto market architecture plan.
- Provider contract for BitoPro, Binance, OKX, and CoinGecko.
- Data model plan for:
  - spot ticker / trade snapshots
  - OHLCV bars
  - order book top-of-book and depth summaries
  - perpetual funding rate and open interest
  - market-cap/ranking snapshots
  - cross-exchange spread and Taiwan premium/discount
  - paper trading orders/fills/positions
  - live execution audit records, only after explicit execution milestone approval
- API plan for read-only crypto data, health, derived spreads, and paper-trading state.
- Safety plan for any future crypto-only live execution.
- Validation plan covering unit tests, provider parser tests, WebSocket reconnect tests, API smoke checks, and degraded-feed behavior.

## Done Criteria

- A future implementation can answer these backend questions without guessing:
  - Which provider is canonical for each crypto resource?
  - Which data is realtime vs low-frequency context?
  - Which paths are read-only and which paths are execution-capable?
  - How is crypto separated from stocks, AI, MCP, Kuro, and frontend-only logic?
  - What freshness SLO blocks trading?
  - What risk gates must pass before any live order can be sent?
- Read-only crypto market APIs expose provider, symbol, instrument type, freshness, and source health.
- Crypto strategies can run in paper mode without exchange trading credentials.
- Default crypto/resource sidebar structure shows `虛擬貨幣` and `商品` folders without requiring user-created watchlists.
- Resource/commodity APIs expose a watch-only provider contract and local cache tables before any provider refresh is connected.
- Complete backend data and complete frontend operation are verified before any automatic-trading design or implementation begins.
- Live execution cannot be enabled accidentally by read paths, AI routes, frontend routes, or default config.
- Stale feed, provider disconnect, sequence gap, order rejection, reconciliation mismatch, and risk-limit breach are explicit states.

## Open Questions / Assumptions

- Assumption: first implementation should be backend-only. Frontend can be added after data and health contracts stabilize.
- Assumption: crypto starts without AI. Any future AI use is advisory only and cannot directly place orders.
- Assumption: BitoPro is needed for Taiwan-dollar pricing and local premium observation, but Binance/OKX should remain the global liquidity references.
- Open question: whether the live execution service should live inside this repo behind a hard-disabled boundary or as a separate local service that OMI calls through a narrow interface.
- Open question: whether to use only Python runtime for collectors or introduce a separate event-driven process if WebSocket throughput and reconnect behavior demand it.
