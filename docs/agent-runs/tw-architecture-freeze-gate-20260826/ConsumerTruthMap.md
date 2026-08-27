# 台股 Consumer Truth Map

## Canonical truth

```text
Provider adapter
  -> canonical observation + RawFetchResult
  -> explicit transaction owner
  -> repository reread
  -> Shared Quality + Resolver
  -> MarketDataResultV1
       |-- API stable projection
       |-- AI evidence / decision contract
       |-- MCP thin projection
       |-- Portfolio ValuationPriceReader
       `-- Frontend research view
```

| Consumer | Allowed input | Forbidden ownership | Current source state |
|---|---|---|---|
| API GET | cache-only market projection | provider IO、commit、lease、fallback | source guard通過 |
| API POST/job/lease | bounded intent與target | provider priority hardcode | explicit command surface |
| AI | capability/freshness/quality intent與resolved evidence | raw ORM market-price fallback、stream payload | quote四元bundle + daily reader |
| MCP | OMI outward contract | provider、freshness、market semantics重算 | thin consumer guard |
| Portfolio | Account Plane position/cost + `ValuationPriceEvidence` | price ORM、quote→daily fallback | market-owned valuation readers |
| Frontend | backend projection與presentation state | provider selection、research math | GET/POST與shared status boundary |

## Quote component contract

同一個`requested_at`下，market-owned bundle保留四個獨立result：

- `quote.snapshot`
- `quote.order_book`
- `quote.auction`
- `quote.official_close`（canonical official daily bar result）

各component各自保留provider health、dataset health、resolved health、lineage、
candidate rejection與limitations。Realtime snapshot即使看似最後一筆成交，也不能
自行升級為official close；只有completed official daily owner可以確認。

## Presentation telemetry

`tw_realtime_stream_platform`只提供sub-second UI telemetry。其contract固定：

- `projection_scope=presentation_only`
- `canonical_truth=false`
- `decision_usable=false`
- `research_usable=false`
- `provider_specific=true`

AI、MCP、Portfolio與decision layer不得import或consume stream/lease provider port。
Stream可顯示recent trades、live depth與auction telemetry，但不能取代canonical
research evidence。

## Unknown and partial rules

- Unknown不轉0。
- No quote不等於no trade；no trade不等於suspended。
- Auction indicative不等於actual trade。
- Missing/partial/stale/fallback與lineage limitation必須沿所有consumer表面可見。
- Compatibility cache只能做presentation/reference，不可偽稱decision-ready。
