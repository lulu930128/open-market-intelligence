# 台股 Architecture Freeze Gate Owner Map

## Current stable foundation（保留）

```text
DataRequirementV2
  -> MarketDataGateway
  -> ProviderCapabilityDescriptorV2 plan
  -> bounded acquisition
  -> canonical observation + RawFetchResult
  -> explicit transaction owner
  -> repository reread
  -> central quality
  -> existing Resolver
  -> MarketDataResultV1
```

已成立的主要vertical slices：public quote、daily OHLCV、intraday bars、depth、auction、current index、current breadth、completed official index/breadth與technical indicators。

## Breakpoint A — Lifecycle / DatasetHealth

```text
Canonical repository
  -> candidate batch
       |-- quote: DatasetHealth exists
       |-- completed official: DatasetHealth exists
       |-- intraday: market-owned DatasetHealth
       |-- depth: market-owned DatasetHealth
       |-- auction: market-owned DatasetHealth + TW applicability
       |-- current index: market-owned DatasetHealth
       `-- current breadth: market-owned DatasetHealth
  -> Gateway forwards batch health unchanged
```

Depth/auction同時缺Shared Registry、TW Catalog與probe identity。`tw_dataset_health.py`只做storage/lineage probe，不是完整freshness evaluator。

Target：

```text
Shared DatasetSpec
  -> TW market lifecycle inputs
       - expected date / eligibility
       - session / instrument policy
       - latest observation state
       - partial / stale / lineage completeness
  -> DatasetHealth
  -> CandidateBatch
  -> Gateway / Resolver
```

Shared core不理解TW auction session；TW market layer不重做Resolver selection。

## Breakpoint B — Capability vocabulary

```text
Descriptor / transaction / repository: "quote.auction"
AI / MCP outward:                      "quote.auction"
Order book everywhere:             "quote.order_book"
```

Target canonical IDs：

- capability：`quote.snapshot`
- capability：`quote.order_book`
- capability：`quote.auction`
- capability：`quote.official_close`
- proposed dataset：`tw.quote.snapshot`
- proposed dataset：`tw.quote.order_book.snapshot`
- proposed dataset：`tw.quote.auction.snapshot`

Durable old identity存在時必須使用formal alias/migration，不做implicit mapping。

## Closure C — AI quote evidence

Freeze前：

```text
AI request
  -> TaiwanStockDependencies.read_taiwan_public_quote
  -> public last-trade quote only
  -> compact quote projection
  -> component projector guesses order-book/auction unavailable/NA
```

Synthetic projection tests能塞完整quote-depth fixture，但production dependency沒有讀canonical depth/auction。

Target：

```text
AI capability intent
  -> TaiwanQuoteEvidenceReader (cache-only)
       |-- quote MarketDataResultV1
       |-- depth MarketDataResultV1
       |-- auction MarketDataResultV1
       `-- official close result
  -> componentized evidence projection
  -> AI / MCP outward selection

Explicit live intent
  -> TaiwanQuoteEvidenceAcquirer
  -> bounded platform operations
  -> reread same bundle
```

Bundle只做orchestration，不合併provider health、dataset health、resolved health或lineage。

Current source closure：`TaiwanQuoteEvidenceBundle`在同一`requested_at`下保存
quote、order book、auction與official daily close四個獨立
`MarketDataResultV1`。`quote_depth.py`不再直接查`MarketDailyPrice`或
`SourceRegistry`拼接daily evidence；realtime snapshot也不能自行升級為official
close。Portfolio valuation直接消費bundle內的actual trade或official close result。

## Breakpoint D — Daily research與Portfolio valuation

Current：

```text
AI Taiwan context
  -> market_service.get_latest_stock_daily_price
  -> db.query(MarketDailyPrice)

Portfolio context
  -> db.query(TaiwanStockQuoteSnapshot)
  -> fallback db.query(MarketDailyPrice)
  -> market switch to US/JP/KR daily ORM models
```

Target：

```text
AI
  -> TaiwanDailyEvidenceReader
  -> existing daily platform/repository/Resolver projection

Portfolio positions (Account Plane)
  + ValuationPriceReader results (Market Data Plane)
  -> portfolio projection
```

Portfolio不持有provider priority、quote→daily fallback、market model mapping或freshness semantics。

## Breakpoint E — GET / command boundary

已安全：

- TW OHLC GET：legacy ensure flag ignored。
- Intraday history GET：legacy refresh ignored。
- Quote-depth GET：legacy refresh ignored。
- Index summary GET：force refresh ignored。
- ETF GET：cache read；refresh為POST。
- Disposition GET：file cache read；refresh為POST。

Freeze-gate修正前仍有side effect：

```text
GET market chips / institutional / margin / shareholding / revenue / financials
  -> ensure_* helpers
  -> provider IO + persistence

GET institutional holding ratios
  -> nStock HTTP

GET overnight impact (default refresh=true)
  -> US context refresh/mutation

GET futures latest / intraday
  -> consumer provider param
  -> refresh_taiwan_futures_*
  -> provider IO + db.commit/rollback
```

Target：所有GET只讀cache；所有refresh/repair/acquire由explicit command surface承擔。

Current source closure：

```text
GET legacy metrics / overnight / holding / futures / index list-contribution-OHLC
  -> cache or typed repository read only
  -> missing/partial stays visible

POST / job / lease
  -> bounded provider acquisition
  -> explicit mutation owner
  -> cache/repository reread
```

Compatibility flags仍可出現在舊API schema，但不得控制provider或觸發side effect。

## Breakpoint F — Lifecycle / freshness multiple owners

Current sources：

1. Shared Dataset Registry + `dataset_lifecycle.py`
2. TW Dataset Catalog
3. `TAIWAN_DATASET_SPECS`
4. `source_health.py`
5. `ai/freshness.py`
6. `ai/market_context/taiwan_freshness.py`
7. `tw_dataset_health.py` storage/lineage probe

Target ownership：

```text
Registry / lifecycle
  -> executable expected/eligibility/freshness policy

TW Catalog
  -> market inventory, owner, projection, refresh, lineage, limitation

Storage probe
  -> storage/lineage facts only

Source health
  -> provider/source operational facts only

AI freshness
  -> projection of DatasetHealth + ResolvedEvidenceHealth
```

Current source closure：platform-owned Taiwan daily price由
`app.market.tw_daily_freshness`查canonical official rows並呼叫Shared
`evaluate_dataset_health`；AI只投影其status/date/refresh operation。其他尚未
converge的chips/fundamentals仍保持legacy compatibility，不被誤標為platform-owned。

Final closure後，`source_health.market_daily_price`也只投影同一份canonical
`DatasetHealth`；generic dataset endpoint改以`platform-evidence`明示只讀
storage/lineage，舊`/health`不再是freshness authority。

## Final closure — disposition與intraday auction owner

```text
Disposition cache (cache-only)
  -> TW instrument trading policy
       current + typed active=true  -> disposition_batch_auction
       current + typed active=false -> continuous
       missing/stale/degraded/malformed -> unknown
  -> TW auction applicability
       opening / closing market auction
       intraday disposition auction
  -> explicit SnapshotCapabilityRequest.auction_type
  -> provider adapter canonical observation
  -> transaction type guard
  -> repository type-specific reread
  -> Shared Quality / Resolver
```

`AuctionType.INTRADAY`由TW market policy決定；Shared Gateway、Resolver與generic
core不import disposition或TW session規則。

## Final closure — quote acquisition diagnostics

```text
AI / API intent: quote.snapshot
  -> Taiwan quote bundle alias boundary
  -> internal quote.last_trade requirement
  -> exact provider resource attempts
  -> repository reread
  -> acquisition_scope
       requested_capabilities
       acquired_resources
       materialized_capabilities
       limitations
```

這個scope只描述bounded acquisition/materialization，不合併四個component的
provider、health或lineage。

## Sidecar inventory

| Surface | Current state | Freeze target |
|---|---|---|
| Corporate events | Cataloged `LINEAGE_GAP` | 保留truthful status或補typed lineage |
| ETF profile/NAV/PCF/iNAV | Cataloged `LINEAGE_GAP` | 不big-bang；守住GET/POST與owner |
| Futures/derivatives | Cataloged `LINEAGE_GAP` | 先修GET/provider/transaction boundary |
| Disposition | File cache + explicit POST、未catalog | 加classification/health contract |
| Institutional holding ratio | GET direct nStock、未catalog | 先cache-only + explicit refresh，再決定persistence |
| Chips/fundamentals | Cataloged `COMPATIBILITY` | 移除GET ensure；migration另排 |
| EOD coverage | Platform-owned但shared module直接transaction | 精確allowlist，條件式physical cleanup |

## Cross-surface target

```text
One resolved market truth
  |-- API projection
  |-- AI evidence bundle
  |-- MCP thin schema
  |-- Portfolio valuation reader
  `-- Frontend presentation

Presentation telemetry stream
  -> frontend-only, provider-specific, noncanonical
```

## Architecture guards

- Shared core不得importprovider或TW policy。
- Registered dataset必須有spec/catalog/probe/lifecycle parity。
- AI/Portfolio不得importmarket price ORM models。
- GET call graph不得到provider IO、commit/rollback或lease acquire。
- AI/MCP不得importrealtime stream platform/provider lease。
- Consumer不得傳production provider preference。
- 新outward TW dataset/route必須cataloged或有explicit exemption。
- CP0 debt must equal actual debt；過期allowlist也失敗。
