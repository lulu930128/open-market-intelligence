# Plan

## Milestones

1. Provider and product contract
   - Scope: Define supported symbols, instruments, provider roles, canonical source priority, naming, and precision rules.
   - Acceptance: `BTC/TWD`, `ETH/TWD`, `USDT/TWD`, `BTC/USDT`, spot vs perpetual, funding rate, OI, ranking, and spread resources are unambiguous.
   - Validation: Static review against current official provider docs before implementation.

2. Read-only crypto backend domain
   - Scope: Create a dedicated crypto backend module, schemas, service boundaries, provider adapters, and router. No AI, no stock-market coupling, no order placement.
   - Acceptance: Crypto code is isolated from `backend/app/market/`, `backend/app/us_market/`, `backend/app/jp_market/`, and `backend/app/ai/` except shared infrastructure such as config, DB session, HTTP client, jobs, and provider health.
   - Validation: `.\.venv\Scripts\python.exe -m compileall backend\app`

3. Database migrations and storage policy
   - Scope: Add explicit Alembic migrations for crypto tables and avoid silent schema drift.
   - Acceptance: Tables separate spot tickers, bars, depth summaries, derivatives metrics, market-cap snapshots, spread snapshots, paper orders, paper fills, and optional live audit records.
   - Validation: `.\.venv\Scripts\python.exe -m unittest backend.tests.test_database_migrations`

4. WebSocket-first collectors
   - Scope: Implement BitoPro, Binance, and OKX WebSocket collectors with REST bootstrap/fallback and bounded reconnect loops.
   - Acceptance: Collectors maintain latest in-memory state with monotonic freshness metadata and record provider events on connect, disconnect, reconnect, stale feed, sequence gap, parse failure, and rate limit.
   - Validation: Unit tests with recorded/synthetic WS messages plus reconnect and stale-feed simulations.

5. Source health and freshness SLO
   - Scope: Extend provider health/source health for crypto resources.
   - Acceptance: Every API response can show whether the provider data is live, stale, partial, missing, or degraded. Trading-capable paths reject stale data.
   - Validation: API spot checks for `/api/system/provider-events?market=crypto` and crypto source health snapshots.

6. Derived market evidence
   - Scope: Build spread, premium/discount, funding, OI, top-of-book, and ranking summaries.
   - Acceptance: BitoPro TWD prices can be compared to Binance/OKX global references; CoinGecko ranking/market-cap context is clearly marked as low-frequency context.
   - Validation: Parser/service tests for normal, missing, stale, and provider-divergent inputs.

7. Complete frontend data workflow
   - Scope: Build the full crypto frontend workflow after backend data contracts stabilize, including quotes, order books, OHLCV, funding/OI, market-cap/ranking context, source health, and Taiwan spread/premium views.
   - Acceptance: User can inspect all crypto data surfaces from the frontend, see stale/partial/provider-failure states, and complete the normal monitoring workflow without backend-only API probing.
   - Validation: Frontend lint/typecheck/build, browser verification, API-backed page checks, and manual workflow smoke checks.

8. Watch-only resource/commodity data domain
   - Scope: Add an isolated resource market backend domain, default commodity futures catalog, local quote/OHLCV cache tables, read-only APIs, and the pinned `商品` sidebar folder.
   - Acceptance: `虛擬貨幣` and `商品` are fixed default folders; commodity rows include gold, silver, copper, WTI crude, Brent crude, and natural gas; no commodity instrument is tradeable or user-watchlist-managed.
   - Validation: Backend compile, resource-market unit tests, migration tests, frontend lint/typecheck/build, and a browser check for both pinned folders.

9. Paper trading only
   - Scope: Implement deterministic `crypto_strategy` signal evaluation and paper execution ledger. No exchange credentials required.
   - Acceptance: Strategy emits intents; paper ledger records simulated orders/fills/positions/PnL with reproducible timestamps, fees, slippage assumptions, and audit trail.
   - Validation: Unit tests for signal generation, duplicate-intent prevention, fill simulation, PnL, and risk-limit rejection.

10. Live execution readiness gate
   - Scope: Design, and only later implement after explicit approval, a crypto-only execution boundary.
   - Acceptance: Execution is disabled by default, remains the final milestone, and requires complete backend data, a fully working crypto frontend, explicit approval, env flags, exchange-specific API keys, order permission checks, kill switch, max notional, max position, idempotent client order IDs, cancel/reconcile loop, and durable audit logs.
   - Validation: Dry-run tests, mocked exchange tests, rejected-default-config tests, and manual checklist before any real API key is connected.

11. Runtime and API smoke checks
   - Scope: Verify backend runtime behavior after implementation.
   - Acceptance: Health, latest quote, derived spread, provider event, paper trading, and disabled execution paths behave predictably.
   - Validation:
     - `Invoke-RestMethod "http://127.0.0.1:8400/api/system/health"`
     - `Invoke-RestMethod "http://127.0.0.1:8400/api/system/provider-events?market=crypto&limit=20"`
     - `Invoke-RestMethod "http://127.0.0.1:8400/api/crypto-market/quotes/latest?symbols=BTC-TWD,BTC-USDT"`
     - `Invoke-RestMethod "http://127.0.0.1:8400/api/crypto-market/spreads?base=BTC"`

## Stop-and-Fix Rules

- If implementation would enable stock-market auto trading, stop and redesign the boundary.
- If automatic trading is requested before read-only crypto data and the full crypto frontend are complete and verified, stop and keep working on data/frontend readiness first.
- If live execution is requested before read-only feeds, freshness SLO, and paper trading are validated, stop and finish those milestones first.
- If any route lets AI, MCP, Kuro, or frontend call order placement directly, stop and move the action behind the crypto execution risk gate.
- If provider docs or API behavior differ from assumptions, update provider contracts before coding against them.
- If WebSocket data is stale, missing, sequence-gapped, or disconnected beyond the SLO, strategy and execution paths must reject new orders.
- If SQLite write pressure affects latest-state reads, move latest state fully out of SQLite and persist only bounded summaries/audit rows.
- If exchange API keys lack IP allowlist, correct permissions, or safe scopes, do not connect live execution.
- If order reconciliation disagrees with local state, block new orders until the mismatch is resolved or explicitly acknowledged.

## Decisions

- 2026-06-24: Crypto should be a separate backend market domain and should not share automatic trading behavior with stocks.
- 2026-06-24: Initial crypto scope is not AI-connected. Any later AI support must remain advisory and must not directly place orders.
- 2026-06-24: BitoPro is the Taiwan-dollar/local exchange source; Binance and OKX are global liquidity and derivatives sources; CoinGecko is ranking/market-cap context only.
- 2026-06-24: Scheduler polling is not sufficient for tradeable crypto realtime data. Crypto collectors should be WebSocket-first with in-memory latest state.
- 2026-06-24: Live execution is a later gated milestone, not part of the read-only market-data milestone.
- 2026-06-24: First backend implementation is REST-backed read-only cache refresh plus source health. WebSocket collectors, paper trading, and live execution gates remain future milestones.
- 2026-06-24: Automatic trading is the final milestone and must wait until complete crypto backend data and a fully working crypto frontend are both verified.
- 2026-06-24: Milestones 4-5 are backend-only. Strategy, paper trading, live execution, and automatic trading remain paused until backend completeness and frontend wiring are verified.
- 2026-06-24: Realtime collector startup is disabled by default; BitoPro/Binance stream contracts and parsers are implemented first, while OKX live WebSocket remains blocked on official-doc re-verification.
- 2026-06-25: BTC is the only current future trade candidate. ETH, USDT, and all commodity/resource instruments are watch-only.
- 2026-06-25: The crypto/resource page uses fixed default folders rather than user-managed watchlists: `虛擬貨幣` and `商品`.
- 2026-06-26: Realtime collector startup is enabled by default, but only for verified providers and `always_on` subscription items; OKX live WebSocket remains disabled until re-verified.
- 2026-06-27: WebSocket latest state must not stay memory-only. Add a bounded persistence bridge that coalesces realtime ticker/order-book/OHLCV updates before writing SQLite, keeping provider WebSocket handling non-blocking while making restart/cache continuity better.
- 2026-06-27: Non-OHLCV crypto market data needs a separate history layer. Keep current snapshot tables as fast latest-state reads, and add bounded sampled history tables for ticker, liquidity/order-book, derivatives, and spread research/backtesting.
