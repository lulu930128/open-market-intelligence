# OMI Database Model Modularization Decision

## Decision

M8 選擇 **Option A：保留單一 `backend/app/db/models.py` 與唯一 `Base` registry**。

這不是暫時跳過，而是依目前 migration、metadata 與 import evidence 做出的 intentional architecture decision。未來若要重啟 model package 拆分，必須先有新的可量化收益與相同等級的 metadata/migration guard。

## Evidence

- ORM model/table classes: 78.
- `Base.metadata` tables: 78.
- Resolved foreign keys: 45.
- Metadata indexes: 677.
- Metadata constraints: 184.
- Direct `app.db.models` consumer files under backend/tests/agents/scripts: 103.
- Alembic `backend/alembic/env.py` directly imports `Base` and sets `target_metadata = Base.metadata`.
- `test_database_migrations.py` validates empty-database upgrade, legacy `create_all` preservation and partial historical schema repairs.
- Model families are interleaved by historical migration order; moving names would create a large compatibility re-export surface without changing schema ownership.

## Risk Comparison

### Split now

- Must preserve one registry and import every domain module before Alembic metadata discovery.
- Must retain 103 existing import consumers or add a broad re-export façade.
- Mapper ordering and string foreign-key resolution become sensitive to package import order.
- Large file movement would produce high review cost while leaving table/schema boundaries unchanged.

### Keep one registry

- Alembic and legacy imports remain stable.
- Schema ownership stays explicit through section map and tests.
- Service/provider/AI decomposition can proceed independently from ORM import mechanics.
- Main cost is file length, which is less risky than registry fragmentation for this local-first SQLite application.

## Domain Section Map

| Approximate section | Ownership |
| --- | --- |
| `AppSetting` through `DataQualityCheck` | settings, source registry, raw fetch, jobs, dispatch, AI stores |
| `ProviderEvent` through `SourceHealthSnapshot` | observability and source health |
| `MarketDailyPrice` through `TaiwanFuturesDailyBar` | Taiwan market and futures cache |
| `CryptoTickerSnapshot` through `CryptoLongShortRatioHistory` | crypto snapshot/history persistence |
| `ResourceMarketInstrument` through `ResourceOhlcvBar` | resource-market registry and OHLC |
| `ChartDrawingSnapshot` through `PortfolioHolding` | Taiwan research projections and portfolio |
| `StockMaster` through `JPWatchlistItem` | Taiwan master plus US/JP core |
| `KRStockMaster` through `KRWatchlistItem` | Korea core |
| `USSecCompanyFact` through `USWatchlistItem` | US fundamentals/resources/watchlists |
| `WatchlistGroup` through `WatchlistRadarOutcome` | Taiwan watchlists and radar lifecycle |

## Guardrails

- Continue importing models from `app.db.models`; do not create a second declarative base.
- DB schema changes still require Alembic migration.
- New models belong near their domain section and must be imported by the same registry.
- `backend/tests/test_database_model_contract.py` guards mapper/table/FK counts and resolution.
- `backend/tests/test_database_migrations.py` remains the runtime migration authority.
- A future split requires an exact before/after metadata fingerprint, Alembic upgrade smoke and unchanged public import set.
