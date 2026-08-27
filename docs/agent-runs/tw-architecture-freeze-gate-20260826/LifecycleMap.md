# 台股 Dataset Lifecycle Map

## Authority chain

```text
Shared DatasetSpec / Registry
  -> TW applicability and latest-observation inputs
  -> shared evaluate_dataset_health
  -> CandidateBatch.dataset_health
  -> MarketDataGateway
  -> Resolver / MarketDataResultV1
  -> API / AI / MCP / Portfolio projection
```

Shared Registry與`dataset_lifecycle.py`是expected date、eligibility、frequency及
freshness evaluation的executable authority。`tw_dataset_catalog.py`只持有台股
inventory、owner、read/refresh operation、projection、lineage與limitations；
`tw_dataset_health.py`只做storage/lineage probe，不自行推算完整freshness。

## Platform-owned lifecycle

| Dataset | Read owner | Refresh owner | Candidate / health owner | Notes |
|---|---|---|---|---|
| `tw.quote.snapshot` | `public_quote_platform` | explicit realtime operation | public quote repository + TW lifecycle | quote與account health分離 |
| `tw.quote.order_book.snapshot` | `taiwan_realtime_platform` | explicit realtime operation / lease | depth repository + TW lifecycle | session applicability由TW layer決定 |
| `tw.quote.auction.snapshot` | `taiwan_realtime_platform` | explicit realtime operation / lease | auction repository + TW lifecycle | indicative不得成actual trade |
| `tw.intraday.bars` | `tw_intraday_platform` | explicit intraday refresh | intraday repository + TW lifecycle | local aggregate保留derived lineage |
| `tw.daily.ohlcv` | `daily_ohlcv_platform` | official daily refresh | daily repository + Shared lifecycle | official close來源 |
| `tw.market_index.current` | `tw_current_market_platform` | explicit current-market refresh | current index repository + TW lifecycle | provisional與completed分離 |
| `tw.market_breadth.current` | `tw_current_market_platform` | explicit current-market refresh | breadth repository + TW lifecycle | unknown/not-received不轉0 |
| `tw.technical.daily` | `technical_indicator_gateway` | backend technical operation | backend-authoritative projection | frontend不得重算research truth |
| `tw.daily.ohlcv.full_market` | dataset lifecycle owner | bounded full-market EOD job | lifecycle coverage state | physical transaction cleanup deferred |
| `tw.market_index.daily` | `official_index_platform` | official completed job | official index repository | 不回退current-session provider |
| `tw.market_breadth.daily` | `official_breadth_platform` | official completed job | official breadth repository | completed universe semantics |

## Compatibility and lineage-gap lifecycle

Chips、fundamentals與company profile維持`COMPATIBILITY`；corporate events、ETF、
futures/derivatives維持`LINEAGE_GAP`；minute/stock intraday state維持
`COMPATIBILITY_DERIVED`。這些dataset仍由Catalog公開限制，不會因有cache或
storage probe就被提升為canonical decision-ready。

Disposition與institutional holding ratio使用
`tw_sidecar_classification.py`的`COMPATIBILITY_CACHE` exemption：GET只讀cache、
POST才refresh，`canonical_truth=false`、`decision_usable=false`，且缺raw receipt
必須出現在limitations。

## Health separation

- Provider health：來源連線、quota、entitlement、resource可用性。
- Dataset health：expected observation、coverage、freshness、lineage與applicability。
- Resolved health：Resolver選到的evidence是否facts/research usable。

三者不得互相覆寫，也不得把storage row存在解讀為fresh或decision-ready。
