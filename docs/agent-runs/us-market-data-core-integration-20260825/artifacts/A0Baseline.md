# A0 Source Baseline

## Identity

- Captured：2026-08-25 Asia/Taipei。
- Branch：`codex/tw-etf-provider-normalization`。
- HEAD：`6d508c7021c1050680262ce4a83f5b33e9f5eda7`。
- Worktree：41 modified／untracked status entries；本artifact只固定US Core integration交疊面，不宣稱其他task ownership。
- Runtime adoption：not checked；A0未修改或restart runtime。
- External provider calls：0。
- DB mutations：0。

## Relevant source hashes before A1-A3 edits

| Path | Git state | SHA-256 |
| --- | --- | --- |
| `.env.example` | modified | `bd4464d457ea7aea58d197072aa35bb6615a7a510ede6643988bbf36a5b4aaea` |
| `backend/app/config.py` | modified | `9c47cff1f235e2ca114202ebacddc76426b974ab8cc1a338c4e9edfaf4d4b045` |
| `backend/app/jobs/backfill_tasks.py` | modified | `3b7b92da329c83a4bec89e8ce2e3035f20ff95beea3aa3ec26850dda359e842d` |
| `backend/app/jobs/job_types.py` | modified | `c6c46c8ecee528c262bb2fe2bc8ff7023547605a5d868084aa82d30bc5077ae0` |
| `backend/app/jobs/scheduler.py` | modified | `8408d852fe267a94b472af35be517c376e5951c647a7a49908090cdd2c492bb3` |
| `backend/app/market_data/eod_coverage.py` | clean | `f806d368f13520380cf7067706e2dfa12f82a5e70c3a95b8949115812ad74085` |
| `backend/app/market_data/registry.py` | modified | `1a289c2e1a909934f02fd4841ef9134d0069cbc2abc8c9b452a5fe1f1117603a` |
| `backend/app/routers/jobs.py` | modified | `8acdc4c4103c8ba5a367dbfaacf2b1c36d4538e9bfab57d5f6ddcb188f91c9b0` |
| `backend/app/routers/us_market.py` | modified | `bb44e212cb781e92a159f1db8fcca18afa1bb563471f6f53f9dee0883becea2f` |
| `backend/app/us_market/market_data_policy.py` | clean | `fa0bf6208cb07278fcc7865d6704d8e528ca83ab40a1742a481a2441808b7304` |
| `backend/app/us_market/providers/canonical.py` | clean | `a02f6d21e2496dc99790ad2837695397147a340ff7754891f7d95261740c8efa` |
| `backend/app/us_market/resolved_reads.py` | clean | `3bb638101a4908253a0cf41821e28748b09b3be8f256c27d0c8ef44a8eee68e4` |
| `backend/app/us_market/market_data_projection.py` | clean | `50575c582da2af66ef37154344a81eaddd5705540d8b4d4b71ac920dbeb6734c` |
| `backend/app/us_market/service.py` | modified | `4f5612e76c672239fb78dd7818062555b210e9aeec6bec37b83f77c9a9a3e964` |
| `backend/app/us_market/ohlc_continuity.py` | untracked | `43e70231736d4fb44e60f908783eb22aed0f5a8afab3f362678acd38fbbc895f` |
| `backend/app/us_market/ohlc_priority.py` | untracked | `22471a996dbd8d7e3d310b800aa3bce92483c68425c828ff45ef400435753f94` |
| `backend/tests/test_us_ohlc_continuity.py` | untracked | `dc2eb5ca40ffd4697820b137b407dc642be9e2c5cd707ada1d3092dcd1e1626a` |
| `backend/tests/test_us_ohlc_contract.py` | untracked | `cd197ed77627af38883fee79233ccdddc7c4b517ca749bd5dcd9147f829c63e9` |
| `backend/tests/test_us_ohlc_priority.py` | untracked | `d36e5e1c4e2644b6c4f3cf26543944a461fc4262ff0cff6144aa8f3e801a2b78` |
| `frontend/src/components/USStockDetailPanel.tsx` | modified | `2fbd17af90c30b8481aa2609bcdf4658c5b8d13371fd33f9d4214aca3e3c760e` |
| `frontend/src/types/market.ts` | modified | `5ff3a90f02286fa236e79f808bd17aeedf9e539aa7c6e0037e63f0c71c26a602` |

## Verified legacy/new ownership graph

| Surface | Current observation | Classification |
| --- | --- | --- |
| `service.refresh_us_daily_prices(provider="auto")` | service executes Yahoo then AlphaVantage fallback | legacy production debt |
| `GET /api/us-market/ohlc/{symbol}` | product read accepts provider and optional implicit history refresh | legacy compatibility debt |
| `POST /api/us-market/ohlc/{symbol}/repair` | new dirty product route accepts provider | new violation to quarantine |
| `USStockDetailPanel` | daily read and automatic repair send `yahoo_chart` | new/active consumer violation |
| priority OHLC scheduler | source default enabled, startup delay 0, repair hardcodes Yahoo | new high-risk violation |
| `app.market_data.eod_coverage` | Shared module imports/calls US legacy service with Yahoo | existing reverse dependency; G0/M6 blocker |
| `market_data_policy` | market-owned descriptors and pure planning exist | retain |
| `providers.canonical` | pure Yahoo/AlphaVantage canonical conversion exists | retain |
| `resolved_reads`/projection | cache-only resolved seam exists | retain |
| OHLC continuity/postcondition | pure market policy and tests exist | retain and decouple |

## Capability contract for A1-A3

| Item | A0 decision |
| --- | --- |
| Product scope | US first-class quote/intraday/daily evidence; no autonomous trading |
| Target | Bounded US symbol/index; normalization remains `normalize_us_symbol` |
| Providers | Yahoo and AlphaVantage known; KGI US planned/unadvertised until entitlement proof |
| Resource | Daily OHLCV first; quote/intraday later after G0 |
| Freshness | US calendar/session policy; completed daily rows and explicit expected date |
| Bounds | bars <= 5000 existing public limit; provider calls/runtime/symbol bounds explicit for repair |
| Persistence | Existing provider+symbol+trade_date rows retained; no schema change in A1-A3 |
| Failure | unknown/partial/missing/rate-limited/provider-unavailable remain truthful |
| Transaction | provider adapter no DB; existing transaction-owning refresh remains legacy compatibility only |
| Public API | no new product provider control; provider-specific behavior diagnostic/admin only |
| AI/consumer | no new provider choice; Frontend automatic provider repair removed |
| Validation | boundary AST/import, OHLC continuity/priority, canonical/projection, transaction and frontend checks |

## Baseline validation

- First pytest attempt：collection failed because `PYTHONPATH` was not set; 10 `ModuleNotFoundError: app` errors，0 tests executed。
- Corrected command used repo-equivalent `PYTHONPATH=backend` and ran 10 targeted files。
- Result：`74 passed in 4.12s`。
- No external API、runtime、DB file或browser action was used。
