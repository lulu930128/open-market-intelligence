# OMI Backend Transaction Ownership

## Purpose

本文件記錄 M0 掃描到的 SQLAlchemy transaction ownership。它用於 M2/M3 拆 service 時防止 double commit、partial commit、漏 rollback 與 observability write 污染主要 transaction。

## Baseline policy

- Query/read helper 預設不 commit。
- `create_*`、`update_*`、`delete_*`、`upsert_*`、`sync_*`、`refresh_*` 可以是 transaction owner，但必須一致且可測。
- 只 mutate 的 internal helper 不得隱性 commit。
- Provider adapter、parser、pure projection 不持有 `Session`。
- Composite operation 的單一 child/provider failure 不得提交半套主要資料。
- Provider event/source-health snapshot 的 commit 行為必須透過參數或 outer owner 明確選擇。

## Static scan summary

AST scan identified functions containing `commit`、`rollback`、`flush` or SQLAlchemy `refresh` calls.

| Module | Functions with transaction/session operations | Main ownership type |
| --- | ---: | --- |
| `us_market/service.py` | 17 | watchlist CRUD, upserts, sync, repair, nested resource rollback |
| `kr_market/service.py` | 15 | watchlist CRUD, upserts, index refresh, nested rollback |
| `jp_market/service.py` | 14 | watchlist CRUD, upserts, symbol sync, fundamental/resource rollback |
| `crypto_market/service.py` | 11 | refresh bundle, realtime persistence, event/fallback rollback |
| `dispatch/service.py` | 11 | delivery/schedule/recipient lifecycle |
| `pipelines/parse_pipeline.py` | 11 | parsed-data persistence |
| `watchlists/service.py` | 8 | Taiwan watchlist CRUD/tree moves |
| `jobs/service.py` | 7 | job lifecycle |
| `stocks/service.py` | 5 | stock sync/update and lazy creation |
| `market/indices.py` | 4 | stat persistence and fallback rollback |
| `resource_market/service.py` | 4 | retry writes, refresh rollback |
| `sources/service.py` | 4 | source CRUD |

Additional modules with smaller ownership include portfolio, AI memory/report store, market backfill, broker branch, futures, provider health, chart drawings, radar outcome and settings store.

## US market ownership

### Commit-owning functions

- `upsert_us_symbol_records`
- `sync_us_sec_company_data`
- `_ensure_us_stock_cik` when it fills missing CIK
- `upsert_us_daily_price_records`
- `repair_us_daily_price_quality`
- `upsert_us_company_profile_records`
- `upsert_us_sec_fact_records`
- `upsert_us_corporate_action_records`
- `upsert_us_short_volume_records`
- `upsert_macro_series_observation_records`
- watchlist create/update/delete functions

### Rollback/partial-failure locations

- `repair_us_daily_price_quality`
- nested `run_resource` in watchlist/resource refresh
- watchlist item create/update integrity failure

### M2 questions

- `upsert_*` currently commits internally; M3 extraction must not wrap them in another implicit transaction owner without a clear mutate variant.
- Resource bundle operations should document whether successful children remain committed when another child fails.
- Lazy CIK discovery combines query, provider result application and commit; its owner should remain explicit.

## JP market ownership

### Commit-owning functions

- `upsert_jp_stock_records`
- `sync_jp_symbol_master`
- `upsert_jp_daily_price_records`
- `upsert_jp_company_fundamental_records`
- `upsert_jp_margin_interest_records`
- `upsert_jp_investor_type_records`
- watchlist create/update/delete functions

### Rollback/partial-failure locations

- `refresh_jp_company_fundamental`
- nested `run_resource` in watchlist resource refresh
- watchlist item integrity failures

### M2 questions

- Yahoo/J-Quants multi-provider fundamental refresh must preserve provider fallback without unintended rollback of a prior valid provider result.
- J-Quants resource failures that are represented as partial/skipped results must not be converted into transaction-wide failure.

## KR market ownership

### Commit-owning functions

- `upsert_kr_stock_records`
- `sync_kr_symbol_master`
- `upsert_kr_index_records`
- `upsert_kr_index_daily_price_records`
- `upsert_kr_daily_price_records`
- `upsert_kr_company_fundamental_records`
- `upsert_kr_investor_trade_records`
- watchlist create/update/delete functions

### Rollback/partial-failure locations

- `refresh_kr_market_indices`
- nested `capture_resource_error`
- watchlist item integrity failures

### M2 questions

- Batch index refresh must state whether each index is its own transaction or one batch transaction.
- KRX daily/investor and OpenDART resource bundle should preserve per-resource failure isolation.

## Crypto market ownership

### Commit-owning functions

- `_run_refresh_items`
- `persist_crypto_realtime_updates`
- `persist_heatmap_records`
- `refresh_crypto_liquidation_heatmap`
- `refresh_crypto_long_short_ratios`
- `refresh_crypto_market_caps`
- `refresh_crypto_ohlcv`
- `refresh_crypto_spreads`
- provider event error recording paths

### Rollback/partial-failure locations

- `_run_refresh_items`
- `persist_crypto_realtime_updates`
- provider `_record_event` and `record_error_event`
- liquidation/ratio/market-cap/OHLC refresh
- local fallback path

### M4 questions

- Realtime persistence and REST refresh must remain separate owners.
- Event recording failure must not commit or rollback unrelated market writes.
- Bundle refresh must document idempotency and partial-success response contract.

## Taiwan core ownership

| Function/module | Current behavior | Required decision |
| --- | --- | --- |
| `indices._persist_market_index_daily_stats` | commits persisted index stats | remain transaction owner or split mutate wrapper |
| `indices._ensure_market_index_daily_stat_coverage` | catches failure and rolls back | document coverage transaction scope |
| `indices.get_market_index_ohlc_chart_data` | may rollback after coverage failure | preserve read-path best effort without hidden partial commit |
| `indices.get_market_index_summary` | may rollback after coverage failure | preserve best-effort summary behavior |
| `intraday._upsert_market_intraday_bars` | commits cache rows | separate provider read from persistence owner |
| `market_chips.upsert_market_chip_daily` | commit + refresh | explicit upsert owner |
| `quote_depth._upsert_quote_snapshot` | commit + refresh | explicit snapshot owner |
| `tw_futures.refresh_*` | stateful provider session plus commit | keep dedicated workflow owner |
| `backfill.backfill_*` | commit/flush/rollback | keep pipeline transaction boundary |
| history backfills | create raw result then commit/rollback | keep workflow transaction boundary |

M1 only moves provider IO/parser. It must not silently change these transaction behaviors.

## Shared service ownership

### Watchlists

Taiwan/US/JP/KR watchlist CRUD currently owns commit and uses refresh after create/update. Item create/update handles integrity errors with rollback. Service decomposition must preserve this behavior unless a dedicated transaction migration is approved.

### Jobs

`jobs/service.py` owns job lifecycle commits. Router enqueue helpers must not commit job-owned business data.

### Provider health

`record_provider_event` and `sync_source_health_snapshots` support commit/flush/refresh behavior. Callers must choose whether observability shares or does not share the main transaction.

### Dispatch

Dispatch has its own transaction lifecycle and is outside the primary market-service split. Do not refactor it incidentally.

## Target transaction patterns

### Pattern A - Query only

```text
query_service(db, ...)
  -> SELECT/projection
  -> no commit/rollback
```

### Pattern B - Internal mutation plus owner

```text
mutate_records(db, records)
  -> add/update/flush as required
  -> no commit

upsert_records(db, records)
  -> mutate_records(...)
  -> commit
  -> return summary
```

Use only when it reduces real nested-transaction ambiguity; do not duplicate every existing upsert mechanically.

### Pattern C - Composite partial success

```text
for resource/target:
  isolate failure
  record result/event without corrupting main write
commit according to documented per-item or batch policy
return success/partial/skipped/error summary
```

### Pattern D - Observability write

```text
record_provider_event(..., commit=False)
outer owner decides final transaction
```

or use a clearly separate session when event durability must not affect market-data state.

## M2 test matrix

| Scenario | Expected evidence |
| --- | --- |
| Successful upsert | one owner commit, expected rows, summary counts |
| Integrity error | rollback, predictable domain error, no partial row |
| Provider failure before mutation | no commit, provider result/error visible |
| Provider failure after another child success | documented per-item/batch result, no accidental half state |
| Observability write failure | main transaction behavior unchanged according to policy |
| Query-only helper | no commit call |
| Retry path | previous failed transaction rolled back before retry |
| Repeated refresh | idempotent or documented replacement behavior |

## M2 verified policy

`backend/tests/test_market_transaction_contracts.py` now characterizes one representative owner for Taiwan, US, JP, KR and crypto:

- each representative upsert owns exactly one `commit()`;
- commit failure invokes exactly one `rollback()` and re-raises the original failure;
- Taiwan index coverage query does not commit or rollback;
- persistence correctness remains covered by the existing market-specific suites.

The representative owners are:

| Market | Owner | Commit-failure policy |
| --- | --- | --- |
| TW | `indices._persist_market_index_daily_stats` | rollback and re-raise |
| US | `upsert_us_daily_price_records` | rollback and re-raise |
| JP | `upsert_jp_daily_price_records` | rollback and re-raise |
| KR | `upsert_kr_daily_price_records` | rollback and re-raise |
| Crypto | `persist_crypto_realtime_updates` | existing rollback and re-raise |

Targeted M2 evidence: `175 passed` in `.tmp/validation/20260713-081914`.

This does not claim that every legacy mutation has been normalized. Remaining owners keep their current scope until moved by M3/M4; any moved owner must add the same success/failure contract before extraction.

## Stop conditions

- A moved function changes commit count or transaction scope without a dedicated test.
- An outer service begins committing an internal function that already commits.
- A rollback clears unrelated successful work in a composite operation.
- Event/source-health persistence changes primary market-data commit behavior.
- Query/read path gains a hidden write other than explicitly documented cache/snapshot behavior.

When any stop condition appears, pause M3/M4 and return to M2 contract design.
