# Provider Contract

## Current Backend Boundary

- Current implementation is read-only market data plus bounded cache refresh.
- `GET /api/crypto-market/*/latest` and `GET /api/crypto-market/source-health` read local backend state only and do not write source-health snapshots.
- `POST /api/crypto-market/*/refresh` may call external public market-data APIs and update local SQLite cache.
- `POST /api/crypto-market/source-health/snapshot` explicitly syncs current computed crypto source health into `source_health_snapshot`.
- `GET /api/crypto-market/realtime/streams` returns the configured WebSocket stream contract.
- `GET /api/crypto-market/realtime/status` returns collector runtime status.
- `GET /api/crypto-market/realtime/latest` reads in-memory latest realtime state.
- No crypto order placement, exchange private API, API-key storage, AI execution, stock-market execution, MCP execution, or Kuro execution route exists in this milestone.
- Automatic trading is out of scope until complete backend data coverage and the full crypto frontend workflow are both implemented and verified.

## Implemented Providers

| Provider | Role | Implemented resources | Canonical symbols |
| --- | --- | --- | --- |
| BitoPro | Taiwan-dollar spot price, local `USDT/TWD` reference, Taiwan premium/discount input | ticker, order book, OHLCV, spread input | `BTC-TWD`, `ETH-TWD`, `USDT-TWD` |
| Binance | Global high-liquidity spot reference and USD-M perpetual metrics | ticker, order book, OHLCV, funding/mark/index/open interest, liquidation events, global account long/short ratio, spread input | `BTC-USDT`, `ETH-USDT` |
| OKX | Secondary global spot and swap reference | ticker, order book, OHLCV, funding/open interest, spread input | `BTC-USDT`, `ETH-USDT` |
| CoinGecko | Low-frequency ranking and market-cap context | market-cap snapshot | `bitcoin`, `ethereum`, `tether` |
| CoinGlass | Third-party processed liquidation heatmap source | liquidation heatmap adapter, API-key and plan gated | coin symbols such as `BTC` |
| OMI local | Local fallback generated from stored liquidation events | estimated liquidation heatmap buckets | OMI canonical symbols such as `BTC-USDT` |
| Bybit | Planned derivatives confirmation source for account ratio and future liquidation/CVD coverage | backend contract only; provider not connected | provider-specific |

## Implemented Backend Endpoints

- `GET /api/crypto-market/provider-contract`
- `GET /api/crypto-market/source-health`
- `POST /api/crypto-market/source-health/snapshot`
- `GET /api/crypto-market/realtime/streams`
- `GET /api/crypto-market/realtime/status`
- `GET /api/crypto-market/realtime/latest`
- `GET /api/crypto-market/quotes/latest`
- `POST /api/crypto-market/quotes/refresh`
- `GET /api/crypto-market/order-books/latest`
- `POST /api/crypto-market/order-books/refresh`
- `GET /api/crypto-market/ohlcv/latest`
- `POST /api/crypto-market/ohlcv/refresh`
- `GET /api/crypto-market/derivatives/latest`
- `POST /api/crypto-market/derivatives/refresh`
- `GET /api/crypto-market/liquidations/events`
- `GET /api/crypto-market/liquidations/heatmap`
- `POST /api/crypto-market/liquidations/refresh`
- `GET /api/crypto-market/cvd/history`
- `POST /api/crypto-market/cvd/refresh`
- `GET /api/crypto-market/long-short-ratios/history`
- `POST /api/crypto-market/long-short-ratios/refresh`
- `GET /api/crypto-market/market-caps/latest`
- `POST /api/crypto-market/market-caps/refresh`
- `GET /api/crypto-market/spreads`
- `POST /api/crypto-market/spreads/refresh`

## Storage Contract

- `crypto_ticker_snapshot`: latest spot ticker by provider, symbol, and instrument type.
- `crypto_order_book_snapshot`: latest bounded depth snapshot by provider, symbol, instrument type, and depth limit.
- `crypto_ohlcv_bar`: bounded historical bars by provider, symbol, instrument type, interval, and bar time.
- `crypto_derivatives_metric`: latest perpetual mark/index/funding/open-interest metrics.
- `crypto_market_cap_snapshot`: latest CoinGecko market-cap context by coin and quote currency.
- `crypto_spread_snapshot`: derived Taiwan premium/discount inputs, using BitoPro local price plus BitoPro `USDT-TWD` and Binance/OKX global `USDT` price.
- `crypto_liquidation_event`: normalized liquidation events from exchange force-order streams or third-party event feeds.
- `crypto_liquidation_heatmap_cell`: processed liquidation heatmap buckets from third-party sources or bounded local estimates.
- `crypto_cvd_history`: spot/perpetual cumulative volume delta buckets derived from persisted trade streams.
- `crypto_long_short_ratio_history`: account/position long-short ratio samples from derivatives providers.

## Provider Source Notes

- BitoPro public REST base is `https://api.bitopro.com/v3`; official docs also expose `wss://stream.bitopro.com:443/ws`. Current backend uses REST endpoints for ticker, order book, and trading history only.
- Binance spot market data uses public REST endpoints for depth, klines, and 24h ticker. Binance USD-M futures endpoints are used for premium/mark/index funding and open interest. Binance USD-M public WebSocket `<symbol>@forceOrder` streams can persist liquidation events into `crypto_liquidation_event` for the `omi_local` heatmap fallback.
- CoinGecko market-cap/ranking context uses `/coins/markets`; it is not a tradeable price source.
- OKX official docs page did not load in the browser tool during implementation, so the current OKX REST adapter is limited to well-known public v5 endpoints and should be re-verified against OKX official docs before WebSocket collectors or execution-adjacent logic are added.
- Liquidation heatmap refresh first calls CoinGlass `/api/futures/liquidation/aggregated-heatmap/model1` with `CG-API-KEY`. The endpoint is plan gated by CoinGlass; without `COINGLASS_API_KEY` or a supported plan, refresh returns skipped/error details instead of fabricating rows.
- If the CoinGlass heatmap path is unavailable and `ENABLE_CRYPTO_MARKET_LIQUIDATION_LOCAL_FALLBACK=true`, OMI can aggregate stored `crypto_liquidation_event` rows into `omi_local` estimated heatmap cells. This fallback only uses liquidation events from Binance force-order streams or third-party event feeds, not order-book depth guesses.
- CVD refresh endpoints currently return explicit `skipped` results with `provider_not_connected`. They do not fabricate data, call third-party quota, or write placeholder rows.
- Binance long/short ratio refresh uses `/futures/data/globalLongShortAccountRatio` and stores `ratio_scope=global_account` samples in `crypto_long_short_ratio_history`. Bybit remains planned and returns explicit skipped results until its provider adapter is connected.
- Bybit is represented in the backend contract as a planned source only. It is not an enabled collector.

## Freshness And Safety

- Crypto freshness is 24/7 and does not reuse Taiwan stock trading-day/session rules.
- Current stale threshold is controlled by `crypto_market_ticker_stale_seconds`.
- Realtime message freshness is controlled by `crypto_market_ws_message_stale_seconds`.
- REST refresh is intentionally bounded:
  - order book depth is capped by endpoint query limits.
  - OHLCV refresh defaults BitoPro to a 6-hour window when no explicit window is passed.
  - Binance/OKX OHLCV refresh uses a bounded `limit`.
- Source health entries include ticker, order book, OHLCV, derivatives, market-cap, spread, liquidation event, liquidation heatmap, CVD, and long/short ratio state. Advanced indicator entries are optional and do not mark core crypto data unhealthy while providers are pending.
- WebSocket stream specs, message parsers, in-memory latest-state storage, and realtime source-health entries are implemented for backend milestone 4-5.
- Live WebSocket collector startup is enabled by default through `enable_crypto_market_ws_collector=true`, but remains bounded to `always_on` subscription items and verified default providers BitoPro and Binance. Binance liquidation-event streams use the futures WebSocket base URL, separate from the spot WebSocket base URL.
- OKX realtime stream support remains parser/scaffold only and is not enabled by default until official docs are re-verified.
- Full frontend operation is a required gate before automatic-trading design or implementation.
