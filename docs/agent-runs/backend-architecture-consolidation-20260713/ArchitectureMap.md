# OMI Backend Architecture Map

## Purpose

本文件以 M0 inventory 為起點，並更新到 M9 完成後的 current architecture、target architecture、依賴方向與主要責任 owner。它不取代長期規則 `docs/architecture/BackendArchitecture.md`。

## Baseline

- Baseline commit: `910a1caf3c88e6aeee217a03067dc3efddb8b827`
- Fresh M0 backend validation: `547 passed, 1 warning`
- Validation logs: `.tmp/validation/20260713-075524`
- Public FastAPI route decorators: 325
- HTTP methods: GET 186, POST 102, PATCH 18, DELETE 15, PUT 4
- SQLAlchemy model classes in `db/models.py`: 78
- Alembic revisions: 33, latest `20260709_0033_portfolio_holdings.py`
- Final backend validation: `580 passed, 1 warning`
- Final validation logs: `.tmp/validation/20260713-100213`
- Follow-up hardening validation: `586 passed`, no warning summary
- Follow-up validation logs: `.tmp/validation/20260713-130020`

## Current dependency map

```text
main.py
  -> runtime.py
  -> routers/*

routers/*
  -> market services
  -> jobs/service.py
  -> schemas

market services
  -> db/models.py
  -> providers/* or sources.py
  -> observability/provider_health.py
  -> source-health projections

providers/*
  -> observability/provider_http.py
  -> http_client.py

AI ask pipeline
  -> tools.py / agentic_tools.py
  -> market services
  -> answer_composer.py
  -> decision_contract.py / ask_finalizer.py

frontend / MCP / Kuro
  -> backend HTTP API
```

## Stable foundations

| Boundary | Current owner | Status |
| --- | --- | --- |
| Runtime lifecycle | `backend/app/runtime.py` | stable façade introduced |
| Provider HTTP context/error | `backend/app/observability/provider_http.py` | canonical shared contract |
| Source-health primitives | `backend/app/observability/source_health_contract.py` | canonical shared primitives |
| AI payload/slot primitives | `backend/app/ai/market_payload_contract.py` | canonical shared contract |
| US provider IO | `backend/app/us_market/providers/` | explicit adapters, compatibility wrappers retained |
| JP provider IO | `backend/app/jp_market/providers/` | explicit adapters, compatibility wrappers retained |
| KR provider IO | `backend/app/kr_market/providers/` | explicit adapters, compatibility wrappers retained |
| Taiwan read-path provider IO | `backend/app/market/providers/` | explicit context adapters; legacy `http_get` patch seam retained |
| Crypto REST provider IO | `backend/app/crypto_market/providers/` | explicit adapter; realtime lifecycle unchanged |
| Resource REST provider IO | `backend/app/resource_market/providers/` | explicit Yahoo adapter; compatibility wrapper retained |
| US/JP/KR chart projections | market-local `chart_projection.py` | pure aggregation/projection; service façade retained |
| AI answer leaf projections | `answer_localization.py`, `answer_data_limits.py`, `answer_scenarios.py` | pure helpers; high-level façade retained |
| AI market-context projection | `backend/app/ai/market_context/common.py` | shared source/freshness/compact projection |
| Taiwan index route family | `backend/app/routers/tw_market_indices.py` | subrouter with handler re-exports from `market.py` |
| Taiwan futures route family | `backend/app/routers/tw_market_futures.py` | subrouter with handler re-exports from `market.py` |
| Taiwan futures fallback jobs | `backend/app/market/tw_futures_jobs.py` | domain orchestration through `jobs.service`; no router transaction |
| ORM model registry | `backend/app/db/models.py` | intentional single-registry Option A |
| Market-family router errors/jobs | `backend/app/routers/market_family_helpers.py` | first shared slice complete |

## Current hotspots

| Module | Lines | Current responsibility groups | Target direction |
| --- | ---: | --- | --- |
| `ai/answer_composer.py` | 2936 | high-level evidence, question-aware answer, watchlist/digest orchestration | pure leaf modules extracted; façade retained |
| `us_market/service.py` | 3262 | stock, watchlist, prices, fundamentals, resources, intraday, refresh | pure chart projection extracted; future responsibility slices remain optional |
| `ai/tools.py` | 3373 | registry, Taiwan reads, execution, market payload assembly | shared context projection extracted; execution façade retained |
| `db/models.py` | 3158 | 78 ORM models | keep one registry; do not split without new evidence |
| `ai/agentic_tools.py` | 2911 | planner, budget, execution, progress, market-specific assembly | shared context projection extracted; execution core retained |
| `market/indices.py` | 2662 | cache, DB coverage, breadth, calculation, projection | provider/parser boundary complete; orchestration façade retained |
| `jp_market/service.py` | 2711 | stock, watchlist, refresh, resources, intraday | pure chart projection extracted; façade retained |
| `crypto_market/service.py` | 2709 | refresh, realtime persistence, resources, source events | REST/realtime/persistence audit |
| `kr_market/service.py` | 2607 | stock, watchlist, indices, resources, intraday | pure chart projection extracted; façade retained |
| `routers/market.py` | 1557 | 50 Taiwan routes + index/futures subrouters | two route-family splits complete |

## Router surface

| Router file | Route count | Main domain |
| --- | ---: | --- |
| `market.py` | 50 | Taiwan market, chips, charts and metrics; includes index/futures subrouters |
| `tw_market_indices.py` | 5 | Taiwan index summary/list/intraday/contribution/OHLC |
| `tw_market_futures.py` | 5 | Taiwan futures products/quotes/daily/intraday |
| `crypto_market.py` | 43 | crypto REST/realtime/resources |
| `us_market.py` | 39 | US stock/watchlist/resources |
| `kr_market.py` | 39 | KR stock/index/watchlist/resources |
| `jp_market.py` | 29 | JP stock/watchlist/resources |
| `ai.py` | 24 | AI ask, reports, memory, contexts |
| `watchlists.py` | 24 | Taiwan watchlists/radar |
| `sources.py` | 13 | source registry/fetch |
| `dispatch.py` | 12 | recipient/schedule/delivery |
| `resource_market.py` | 8 | commodity/resource context |
| `stocks.py` | 8 | Taiwan stock master |
| `portfolio.py` | 6 | holdings |
| `settings.py` | 6 | local settings |
| `raw_results.py` | 4 | raw data inspection/retention |
| `jobs.py` | 3 | jobs |
| `system.py` | 3 | health/observability |
| `indicators.py` | 2 | indicators |
| `reports.py` | 2 | reports |

Total: 325 routes.

## External IO ownership map

### Explicit provider adapters

| Market | Modules | Transport |
| --- | --- | --- |
| TW | TWSE OpenAPI/RWD/MIS, TPEX, Yahoo, nStock, TAIFEX | `provider_http` via market providers and shared `_http.py` |
| US | Alpha Vantage, FINRA, FRED, NASDAQ, SEC, Yahoo | `provider_http` via market `_http.py` |
| JP | J-Quants, JPX, Yahoo | `provider_http` via market `_http.py` |
| KR | KRX, Naver, OpenDART, Yahoo | `provider_http` via market `_http.py` |
| Crypto REST | CoinGecko, Alternative.me and bounded source URLs | `provider_http` via crypto `_http.py` |
| Resource | Yahoo chart | `provider_http` via resource `_http.py` |

### Taiwan stateless read paths after M1

| Module | Transport owner | Responsibility |
| --- | --- | --- |
| `market/indices.py` | `market/providers` + compatibility façade | TWSE/TPEX/MIS/Yahoo index and breadth |
| `market/intraday.py` | `market/providers.http_get` | Yahoo, nStock and MIS intraday |
| `market/market_chips.py` | `market/providers.http_get` | TWSE/TPEX/TAIFEX market-chip sources |
| `market/quote_depth.py` | `market/providers.http_get` | TWSE MIS quote depth |
| `market/institutional_holding_ratios.py` | `market/providers.http_get` | nStock institutional holding source |
| `market/broker_branch.py` | `market/providers.http_get` | nStock broker branch source |

M1 also moved pure date/number normalization and TWSE/TPEX daily-stat parsing to `market/index_parsers.py`. Stateful/cache/DB/fallback orchestration remains in its original service owner.

### Stateful or transaction-coupled transport

| Module | Current transport | Decision |
| --- | --- | --- |
| `market/backfill.py` | raw GET/POST | document and isolate; do not force stateless adapter |
| `market/*_history_backfill.py` | `new_session()` | stateful workflow boundary |
| `market/tw_futures.py` | `new_session()` | provider session/cookie flow boundary |
| `ai/llm.py` | raw `http_post` | LLM transport, not market provider; keep separate policy |

## Target dependency map

```text
routers
  -> stable service facades

service facades
  -> query services
  -> transaction-owning refresh services
  -> pure projections
  -> provider adapters

provider adapters
  -> provider_http
  -> http_client

AI execution
  -> market read services
  -> pure market-context projections
  -> answer-composer facade

answer-composer facade
  -> localization primitives
  -> data-limit/confidence projection
  -> evidence/scenario projection
  -> watchlist/digest formatting

DB
  -> one Base/metadata registry
  -> consolidated models.py by M8 Option A decision
```

## Allowed import direction

- Router may import schema, service façade and router helper.
- Service façade may import internal service modules and re-export compatibility names.
- Internal service may import models, parsers, providers and pure projections.
- Provider may import provider HTTP, market error/symbol contract and standard libraries.
- Parser/projection may not import service, router, DB session, provider transport or LLM.
- AI projection may import payload contracts and pure types, but not start refresh or write DB.
- `db.models` compatibility imports remain stable until M8 decision.

## Forbidden dependency patterns

- Provider -> service or DB.
- Parser -> provider HTTP.
- Frontend/MCP/Kuro -> DB or market implementation module.
- Router -> raw provider.
- Pure projection -> SQLAlchemy commit/refresh.
- Service split implemented through mutual imports or widespread lazy imports.
- DB model split that creates multiple `Base` registries or changes table metadata.

## Milestone ownership

| Architecture area | Milestone |
| --- | --- |
| Current maps/contracts | M0 |
| Taiwan provider paths | M1 |
| Transaction ownership | M2 |
| US/JP/KR services | M3 |
| Crypto/resource transport/services | M4 |
| AI answer composition | M5 |
| AI tool projections | M6 |
| Routers/API | M7 |
| DB models | M8 |
| Final convergence | M9 |
