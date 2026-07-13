# OMI Backend Compatibility Matrix

## Purpose

本文件列出架構整頓期間必須保護的 route、service import、test patch seam、provider wrapper、AI consumer contract 與 DB compatibility。每個 milestone 搬移名稱前先更新此矩陣。

## Baseline

- Baseline commit: `910a1ca`
- FastAPI route decorators: 325
- Methods: GET 186, POST 102, PATCH 18, DELETE 15, PUT 4
- Backend regression after M1: `556 passed, 1 warning`
- Final backend regression after M9: `580 passed, 1 warning`
- Follow-up hardening regression: `586 passed`, no warning summary
- Final OpenAPI inventory: 326 total operations, 325 under `/api/*`

## Router prefix matrix

| Router | Prefix | Routes | Compatibility owner |
| --- | --- | ---: | --- |
| `system.py` | `/api/system` | 3 | system/observability |
| `sources.py` | `/api/sources` | 13 | source registry |
| `raw_results.py` | `/api/raw-results` | 4 | raw result inspection |
| `jobs.py` | `/api/jobs` | 3 | jobs |
| `settings.py` | `/api/settings` | 6 | local settings |
| `ai.py` | `/api/ai` | 24 | AI contract |
| `crypto_market.py` | `/api/crypto-market` | 43 | crypto context |
| `resource_market.py` | `/api/resource-market` | 8 | resource context |
| `dispatch.py` | `/api/dispatch` | 12 | dispatch |
| `market.py` + Taiwan subrouters | `/api/market` | 50 + 5 + 5 | Taiwan market core; index and futures subrouters |
| `indicators.py` | `/api/market/indicators` | 2 | indicators |
| `stocks.py` | `/api/stocks` | 8 | Taiwan stock master |
| `us_market.py` | `/api/us-market` | 39 | US context |
| `jp_market.py` | `/api/jp-market` | 29 | JP context |
| `kr_market.py` | `/api/kr-market` | 39 | KR context |
| `watchlists.py` | `/api/watchlists` | 24 | Taiwan watchlists/radar |
| `portfolio.py` | `/api/portfolio` | 6 | holdings |
| `reports.py` | `/api/reports` | 2 | report access |

Route count is a compatibility signal, not the only contract. Method, full path, query/body schema, response model and status behavior must also remain stable.

## M1 Taiwan index API surface

| Method | Full path | Router function | Service function | Response contract |
| --- | --- | --- | --- | --- |
| GET | `/api/market/indices/summary` | `get_indices_summary` | `get_market_index_summary` | `MarketIndexSummaryRead` |
| GET | `/api/market/indices/list` | `get_indices_list` | `get_market_index_list` | `MarketIndexListRead` |
| GET | `/api/market/indices/{index_id}/intraday` | `get_index_intraday_trend` | `get_market_index_intraday` | `IntradayTrendRead` |
| GET | `/api/market/indices/{index_id}/contributions` | `get_index_contributions` | `get_market_index_contributions` | `MarketIndexContributionRead` |
| GET | `/api/market/indices/{index_id}/ohlc` | `get_index_ohlc_chart_data` | `get_market_index_ohlc_chart_data` | `MarketOhlcChartRead` |

M1/M7 compatibility result：

- 不改 route/method/response model。
- 不改 index id normalization、market selection、fallback order、cache behavior 或 freshness metadata。
- M7 將 handlers 移到 `tw_market_indices.py`，`market.py` include subrouter 並 re-export 同一 handler identity。
- 五條 route 的 OpenAPI operation ID 與 response model ref 均保持不變。

## Taiwan futures API surface

| Method | Full path | Router function | Response item contract |
| --- | --- | --- | --- |
| GET | `/api/market/tw-futures/products` | `list_taiwan_futures_products_api` | `TaiwanFuturesProductRead` |
| POST | `/api/market/tw-futures/refresh` | `refresh_taiwan_futures_quotes_api` | `TaiwanFuturesQuoteRead` |
| GET | `/api/market/tw-futures/latest` | `get_latest_taiwan_futures_quotes_api` | `TaiwanFuturesQuoteRead` |
| GET | `/api/market/tw-futures/{symbol}/daily` | `list_taiwan_futures_daily_bars_api` | `TaiwanFuturesDailyBarRead` |
| GET | `/api/market/tw-futures/{symbol}/intraday` | `list_taiwan_futures_intraday_bars_api` | `TaiwanFuturesIntradayBarRead` |

Follow-up hardening restrictions:

- `market.py` include `tw_market_futures.py` and re-export the same five handler identities.
- Operation IDs, response item refs, query defaults and fallback behavior remain unchanged.
- Futures refresh/job persistence is owned by `tw_futures.py` and `tw_futures_jobs.py`; router modules contain no direct transaction calls.

## Service façade consumers

| Façade | Current direct consumers | Compatibility strategy |
| --- | --- | --- |
| `app.us_market.service` | `routers/us_market.py`, AI/tools, tests, OHLC overlay tests | re-export moved names; router import unchanged |
| `app.jp_market.service` | `routers/jp_market.py`, AI/tools, tests | re-export provider/parser/service names used by tests |
| `app.kr_market.service` | `routers/kr_market.py`, AI/tools, tests | re-export stock/index/watchlist/resource names |
| `app.crypto_market.service` | `routers/crypto_market.py`, `auto_refresh.py`, `realtime_persistence.py`, tests | preserve realtime persistence and refresh entrypoints |
| `app.market.indices` | `routers/market.py`, `market_chips.py`, `ai/tools.py`, tests | preserve public and patched private wrappers through M1/M7 |

## M1 index patch seams

`backend/tests/test_market_index_daily_stats.py` currently patches or calls these `indices` names directly. M1 must retain wrappers or update tests only after an explicit compatibility decision:

- `http_get`
- `_fetch_json`
- `_fetch_recent_market_index_daily_stats`
- `_fetch_twse_market_daily_stats_for_month`
- `_fetch_yahoo_index_points`
- `_fetch_yahoo_index`
- `_fetch_twse_index_5s_ohlc`
- `_fetch_twse_index_5s_intraday`
- `_fetch_market_quote_breadth`
- `_fetch_twse_mis_stock_messages`
- `_fetch_twse_mis_live_market_breadth`
- `_fetch_yahoo_index_intraday`
- `_fetch_mis_index_message`
- `_latest_market_breadth`
- `_ensure_market_index_daily_stat_coverage`
- `_fetch_recent_index_trade_values`

`http_get` is a test seam rather than a desired target architecture. During M1.1, keep a compatibility alias until provider-adapter tests replace direct transport patching.

## US provider/service patch seams

Representative tests patch the following names under `app.us_market.service`:

- `fetch_yahoo_chart_payload`
- `fetch_sec_companyfacts_payload`
- `fetch_sec_company_tickers_exchange_payload`
- `refresh_us_daily_prices`
- `refresh_us_daily_prices_from_alphavantage`
- `refresh_us_daily_prices_from_yahoo_chart`
- `refresh_us_company_profile_from_alphavantage`
- `refresh_us_sec_companyfacts`
- `expected_us_daily_price_date`
- `_get_us_intraday_overlay`
- market configuration under `settings`

M3.1 must keep these names bound at the façade even if implementation moves.

## JP provider/service patch seams

Representative tests patch the following names under `app.jp_market.service`:

- `fetch_jpx_listed_issues_workbook`
- `parse_jpx_listed_issues_workbook`
- `fetch_yahoo_chart_payload`
- `fetch_yahoo_quote_summary_payload`
- `fetch_jquants_id_token`
- `fetch_jquants_statements_payload`
- `fetch_jquants_summary_payload`
- `fetch_jquants_margin_interest_payload`
- `refresh_jp_daily_prices`
- J-Quants settings and `_jquants_id_token_cache`

J-Quants HTTP 403/429 fallback wording and plan/rate-limit behavior are compatibility surfaces.

## KR provider/service patch seams

Representative tests patch the following names under `app.kr_market.service`:

- `fetch_naver_index_intraday_page_payload`
- `fetch_naver_index_realtime_payload`
- `_kr_index_intraday_thistime`
- `refresh_kr_daily_prices`
- `refresh_kr_investor_trades_from_krx`
- OpenDART settings

KR index and stock paths share one façade; M3.3 must preserve both groups until consumer imports are migrated intentionally.

## Provider wrapper compatibility

| Market | Legacy import surface | Current implementation owner | Rule |
| --- | --- | --- | --- |
| US | `app.us_market.sources.fetch_*`, error, symbol normalize | `app.us_market.providers/*`, `errors.py`, `symbols.py` | keep forwarding/re-export |
| JP | `app.jp_market.sources.fetch_*`, error, symbol/local code | `app.jp_market.providers/*`, `errors.py`, `symbols.py` | keep forwarding/re-export |
| KR | `app.kr_market.sources.fetch_*`, error, symbol/local code | `app.kr_market.providers/*`, `errors.py`, `symbols.py` | keep forwarding/re-export |
| TW | module-local `http_get`, `indices._fetch_json`, private `_fetch_*` | `app.market.providers/*`, `index_parsers.py`, service façades | retain patch aliases; provider transport owns runtime request context |
| Crypto REST | `sources._request_json` | `app.crypto_market.providers/*` | keep wrapper; realtime/persistence ownership unchanged |
| Resource | `sources.fetch_yahoo_chart_payload` | `app.resource_market.providers/yahoo.py` | keep forwarding wrapper |

Removing a wrapper requires zero-consumer evidence from backend, tests, agents and known external adapters.

## AI consumer compatibility

### Required top-level behavior

- `analysis.human_answer` remains the preferred user-facing answer.
- `analysis.decision_contract` remains additive and versioned.
- `result.data.slots` remains available for full payload consumers.
- `result.data.compact.slots` remains available for compact consumers.
- Warnings, missing keys, freshness and source refs remain visible.

### `human_answer` semantic fields

Refactors must preserve applicable fields and their meaning:

- `headline`
- `text`
- `summary`
- `action_plan`
- `scenarios`
- `counter_evidence`
- `risks`
- `data_limits`
- `source`
- `style`
- `sections`
- `lines`

Exact wording is protected where characterization tests assert it; otherwise semantic field/value compatibility is primary.

### Decision contract

- Kind remains `omi_ai_decision_contract`.
- Version remains `decision_contract.v1` unless separately migrated.
- It continues to derive from the assembled human answer and evidence.
- Frontend/MCP/Kuro must not need backend-internal modules to interpret it.

## DB compatibility

- Current ORM registry: 78 model classes in `backend/app/db/models.py`.
- Current Alembic chain: 33 revisions through `20260709_0033_portfolio_holdings.py`.
- M0-M7 do not change table names, columns, constraints, indexes or schema revision.
- M8 selected Option A: keep `app.db.models` as the single implementation module and retain one shared `Base.metadata`.
- Contract coverage protects 78 tables/mappers and resolves all 45 foreign keys against the registry.
- DB migration is a separate compatibility event, not an incidental consequence of file movement.

## Compatibility verification by milestone

| Milestone | Required compatibility evidence |
| --- | --- |
| M1 | Taiwan index routes, patched `_fetch_*` seams, response models, provider fallback |
| M2 | commit/rollback owner and query-no-commit behavior |
| M3 | service imports, provider refresh order, watchlist/chart/resource contracts |
| M4 | crypto realtime/REST/resource capability and source-health |
| M5 | human answer semantics, locale, warnings/data limits, decision contract |
| M6 | tool names/schemas/budget/progress/slots/source refs |
| M7 | route count, methods, paths, response models and OpenAPI |
| M8 | model import set, table metadata, Alembic discovery |
| M9 | full backend, representative runtime/API smoke, final consumer checks |

Final M9 evidence:

- Full backend: `580 passed, 1 warning`.
- Taiwan index OpenAPI operation IDs and response models: unchanged.
- ORM registry/table and foreign-key resolution contracts: passed.
- Runtime read-only API probes: 9/9 returned HTTP 200.
- No frontend file changed and no public OpenAPI contract drift was detected, so frontend validation was intentionally not run.

## Breaking-change protocol

若任何 milestone 發現必須 breaking：

1. 立即停止原 slice。
2. 在本文件新增 affected consumers、old/new contract、migration/deprecation window。
3. 先取得使用者明確同意。
4. 以獨立 milestone/commit 實作，不混入純重構。
