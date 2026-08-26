# CP0 Storage and Boundary Decision

## Status

- Decision：`CP0_READ_SCHEMA_REUSE_APPROVED`
- Production write cutover：`not_approved`
- Migration：`not_required_for_CP0_read_seam`
- Scope：TWSE／TPEx official daily OHLCV candidate read path。

## 1. Why this decision exists

共同平台不能先建立一張generic observation table再把既有資料複製進去。CP0先回答四個問題：

1. 現有storage能否保存第一條official daily candidate所需lineage？
2. 哪些函式目前擁有fetch、parse、write與postcondition transaction？
3. Read repository能否在零provider I/O、零commit下產生Canonical Bar？
4. 哪些缺口必須在production write cutover前修正？

## 2. Current storage map

| Storage | Current writer | Current reader/consumer | Identity / idempotency | Lineage retained | CP0 decision |
| --- | --- | --- | --- | --- | --- |
| `source_registry` | source seed/admin service | fetch pipeline、source health、candidate repository | unique `source_name` | source name/type/category/endpoint/priority/parser/reliability/last status | 沿用source identity與operational metadata；不取代capability catalog |
| `fetch_log` | `run_source_fetch()` | jobs/source health | fetch attempt ID | job/status/start/end/duration/error | 沿用operation evidence |
| `raw_fetch_result` | `run_source_fetch()` | parsers、candidate lineage | row ID + content hash | source/fetch log/fetched_at/URL/method/status/hash/raw/parser version | 沿用raw receipt；official bulk目前parser_version多為null，repository以source parser_type作bounded fallback |
| `data_quality_check` | `run_source_fetch()` | fetch result/source diagnostics | quality row linked toraw/fetch | status/check/message/row count/duplicate/detail | CP2 production result必須投影quality；不可只看HTTP success |
| `market_daily_price` | TWSE/TPEx parse pipeline、per-symbol backfill | daily/chart/coverage/research | unique `(source_id, stock_id, trade_date)` | source_id/raw_result_id/date/OHLCV/name | 沿用第一條daily candidate store；不新增duplicate canonical table |
| `market_dataset_coverage_checkpoint` | EOD coverage service | cache-only EOD API、scheduler/jobs | unique dataset/scope/expected date/universe hash | expected/latest date、universe/coverage partition、repair cursor/backoff/job/detail | 沿用EOD lifecycle truth；Registry尚未成runtime owner |
| `market_intraday_bar` | intraday persistence | intraday services | unique provider/stock/interval/bar_time | provider/source/time/OHLCV | 留到CP5另作request-time audit，不用daily決策推論足夠 |
| `taiwan_stock_quote_snapshot` | quote-depth persistence | quote/depth services | unique provider/stock/quote_time | provider/session/event/fetched/raw/level data | 留到CP5；既有KGI rows不作本次gate |

## 3. Current transaction map

### Fetch receipt transaction

`run_source_fetch()`目前在同一transaction寫入：

- `FetchLog`
- `RawFetchResult`
- `DataQualityCheck`
- `SourceRegistry.last_success/error`

Provider HTTP不直接寫DB；fetch pipeline是明確owner。Raw receipt即使後續parse失敗也應保留，因此不要求raw receipt與canonical rows形成一個跨階段atomic transaction。

### Canonical daily row transaction

`parse_twse_daily_raw_result()`與`parse_tpex_daily_quotes_raw_result()`目前：

1. 讀raw result。
2. parse rows。
3. 執行same-date destructive regression guard。
4. 刪除同raw與同source/trade-date舊rows。
5. insert新`MarketDailyPrice` rows。
6. `db.commit()`。

這個writer具source/date unique key與80% retained-count guard，但commit failure目前沒有owning wrapper負責rollback/rethrow。CP2 production cutover前必須補齊；CP0 read seam不修改這個dirty-sensitive legacy pipeline。

### Coverage transaction

EOD service目前分開persist checkpoint與repair state，並在provider refresh後重新query `MarketDailyPrice`計算coverage。這個「不相信provider success、必須reread postcondition」方向保留；CP3再把operation/eligibility/expected date ownership接到Dataset Registry runtime service。

## 4. Canonical read mapping

新增的`TaiwanOfficialDailyBarRepository`只做以下mapping：

```text
venue TWSE
  -> source TWSE OpenAPI Daily Trading
  -> provider twse_openapi

venue TPEX
  -> source TPEx Mainboard Daily Quotes
  -> provider tpex_openapi
```

- Instrument identity：`Market.TW + symbol + STOCK/ETF + venue`。
- Bar interval：`1d`。
- Start/end：Taiwan local 09:00–13:30。
- Event time：official session close 13:30。
- Fetched time：`RawFetchResult.fetched_at`；SQLite讀回naive時依既有`utc_now`storage contract還原UTC。
- Authority：`exchange`。
- Cache semantics：persisted row一律`cache_hit=true`。
- Observation ID：`market_daily_price:<row id>`。
- Volume：official traded shares，unit=`share`；`None`保持unknown，0不自動改成missing。
- Finalization：official daily persisted row為`final`；尚未完成session的payload不得進這個repository path。

## 5. Fail-closed behavior

- Query range上限3660天、row上限5000。
- 查到`max_rows + 1`時raise `CandidateReadLimitExceeded`，不得silent truncate。
- 缺任一OHLC欄位時產生`MISSING_REQUIRED_OHLC` rejection。
- 非正值或OHLC關係不一致時產生`INVALID_CANONICAL_BAR` rejection。
- `rows_accepted + rejections == rows_examined`由contract validator保護。
- Venue只接受TWSE/TPEX，並用venue-specific official source filter避免symbol碰撞或跨市場污染。
- Repository沒有provider import、HTTP、refresh、selection、commit或rollback。

## 6. Boundary debt baseline

Machine-enforced baseline：`artifacts/cp0-boundary-debt.json`。

目前只allow既有debt，不授權新增：

- Router/AI direct provider imports：`backend/app/routers/market.py`的KGI legacy imports。
- Shared `backend/app/market_data/` transaction calls：`eod_coverage.py`既有checkpoint/repair commits與rollbacks。

Tests採`actual <= allowlist`，所以移除debt會通過；新增consumer/provider coupling或shared transaction owner會fail。

## 7. Migration decision

CP0/CP1不新增DB migration，原因：

- Daily candidate已保有source/raw/date/OHLCV identity。
- Raw receipt已保有fetched time、URL/status/hash/raw payload。
- Data quality已有linked table。
- Event time可由official trade date + verified TW session close deterministic重建。
- Source/date unique key可支援idempotent replacement。

以下任一證據出現時，才重新開migration decision：

- 同一source/symbol/date需要並存多個correction revision且現有identity無法表示。
- Parser/schema version無法由raw/source contract如實恢復。
- Per-observation quality/provisional/correction status不能由現有raw/quality資料重建。
- Received time與fetched time的差異會影響request-time evidence；這屬CP5，不反向污染daily slice。
- Component limitations需要持久保存且不能由raw/quality/checkpoint重建。

## 8. CP0 exit gate

- Read repository contract與TW SQL adapter tests通過。
- Consumer/provider與transaction debt guards通過。
- Existing Foundation、Resolver、EOD與backfill regression通過。
- Production route、provider call、DB write、scheduler與runtime皆未改動。
- `Progress.md`與`AcceptanceMatrix.md`記錄證據後，才可進CP1。
