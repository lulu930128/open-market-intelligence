# Freeze Gate Source Manifest

本清單只記錄`tw-architecture-freeze-gate-20260826`相對於前一輪
`tw-shared-data-core-convergence-20260826` checkpoint的task-owned source delta。
既有US、scheduler/DB contention、runtime remediation與i18n hunks不屬本清單。

## Production source

- `backend/app/ai/agentic_tools.py`
- `backend/app/ai/freshness.py`
- `backend/app/ai/market_context/portfolio_context.py`
- `backend/app/ai/market_context/taiwan_freshness.py`
- `backend/app/ai/market_context/taiwan_projection.py`
- `backend/app/ai/market_context/taiwan_stock.py`
- `backend/app/ai/query_plan.py`
- `backend/app/config.py`
- `backend/app/jp_market/valuation.py`
- `backend/app/kr_market/valuation.py`
- `backend/app/market/daily_ohlcv_platform.py`
- `backend/app/market/indices.py`
- `backend/app/market/institutional_holding_ratio_cache.py`
- `backend/app/market/institutional_holding_ratios.py`
- `backend/app/market/portfolio_valuation.py`
- `backend/app/market/quote_depth.py`
- `backend/app/market/schemas.py`
- `backend/app/market/taiwan_quote_evidence.py`
- `backend/app/market/tw_daily_freshness.py`
- `backend/app/market/tw_dataset_catalog.py`
- `backend/app/market/tw_dataset_health.py`
- `backend/app/market/tw_dataset_lifecycle.py`
- `backend/app/market/tw_sidecar_classification.py`
- `backend/app/market_data/registry.py`
- `backend/app/market_data/valuation.py`
- `backend/app/portfolio/valuation.py`
- `backend/app/routers/market.py`
- `backend/app/routers/tw_data_core.py`
- `backend/app/routers/tw_market_futures.py`
- `backend/app/routers/tw_market_indices.py`
- `backend/app/us_market/valuation.py`
- `frontend/src/components/SidebarWatchlistExplorer.tsx`
- `frontend/src/components/TaiwanFuturesDetailPanel.tsx`
- `frontend/src/components/stock-detail/useTaiwanDataPanel.ts`
- `frontend/src/types/market.ts`

## Tests

- `backend/tests/test_ai_freshness_guard.py`
- `backend/tests/test_ai_supplemental_contexts.py`
- `backend/tests/test_api_contract_inventory.py`
- `backend/tests/test_market_index_daily_stats.py`
- `backend/tests/test_market_data_registry.py`
- `backend/tests/test_market_data_v2_dark_boundary.py`
- `backend/tests/test_tw_daily_freshness.py`
- `backend/tests/test_tw_data_core_boundaries.py`
- `backend/tests/test_tw_institutional_holding_ratio_cache.py`
- `backend/tests/test_tw_official_daily_platform.py`
- `backend/tests/test_tw_quote_depth_shared_projection.py`
- `backend/tests/test_tw_sidecar_classification.py`

## Task evidence

- `docs/agent-runs/tw-architecture-freeze-gate-20260826/`

## Explicit exclusions

- `backend/app/us_market/market_data/`與US OHLC continuity/source work。
- scheduler、DB session/contention與launcher recovery hunks。
- `docs/agent-runs/tw-realtime-market-state-remediation-20260824/`及其live artifacts。
- frontend US、regional tape與不相關i18n hunks。
- `.tmp/` validation logs、local DB、cache、build output與runtime state。

Git index保持空；本清單不是staging授權，也不代表runtime已adopt。
