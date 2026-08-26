# CP7 Consumer and Technical Convergence

## Gate result

CP7 source gate已通過：AI quote consumer、backend-authoritative technical series與index dashboard completed-session adapter都已接到Data Core。Dashboard的completed official index/breadth只接受resolved projection；production DB尚未採用0067或缺canonical lineage時回`data_core_missing`，不復活legacy completed row。這仍不等於production runtime已完成採用。

## Taiwan quote flow

```text
AI query/context
  -> read_taiwan_public_quote_projection
  -> MarketDataGateway
  -> Taiwan public quote candidate repository
  -> Resolver
  -> compatibility projection
  -> omi.decision.v4 / HTTP / SSE / MCP
```

- AI不再import或call `quote_depth`來取得台股current quote。
- `provider`與`strict_provider`只保留legacy diagnostic input compatibility，不再影響production acquisition；Data Core一律收到provider-neutral intent。
- AI不再自己組裝fake provider attempt或fallback reason；lineage、fallback、freshness、dataset health與resolved health都從platform result投影。
- Intraday bars一律cache-only讀persisted bars，不因AI問答偷偷refresh。

## Technical truth flow

```text
resolved official tw.daily.ohlcv
  -> backend canonical technical engine
  -> algorithm/version/price-basis/parameter contract
  -> indicator API + AI technical evidence
  -> frontend backend-authoritative series projection
```

- Indicator API與AI technical evidence都經`read_taiwan_official_daily`，不直接讀raw `market_daily_price`；同日多provider row由Resolver決定official selected evidence。
- `tw.technical.indicators.v3`攜帶`algorithm_version`、`price_basis=raw_unadjusted`、`calculation_role=backend_authoritative`與完整parameter contract。
- Frontend在metadata與requested parameters相符時直接採用backend MA/EMA/RSI/MACD/KD/ATR/ADX/MFI/ROC/Donchian/Bollinger/support-resistance值。
- 舊market或缺少authority metadata時保留local calculation作presentation compatibility，並由`data-indicator-projection-scope=presentation_only`明確標記；它不是backend research evidence，也不得回寫或餵給AI/MCP。
- Golden regression刻意加入close=10,000的vendor duplicate row，API與AI仍共同選TWSE official close=179，且RSI/MACD/KD完全一致。

## Contract evidence

- Decision v4與MCP parity suite維持既有outward shape。
- Capability registry把`technical.indicators`與`technical.structure`映射到`tw.technical.daily`，`advertised => projection exists`仍成立。
- Indicator contract endpoint公開目前active engine、algorithm version與rollback flag，不讓frontend猜測。
- Completed-session cache read預設使用最近已發布交易日，max 5,000 rows且calendar range上限36,600日；external calls固定為0。
- `/indices/summary`新增`data_core_contract_version`，每個index item分開暴露`completed_official_index`、`completed_official_breadth`、component health/lineage與`data_core_projection_scope`。
- Current-session index observation與latest-completed official component保留各自trade date；Resolver不會把前一交易日official close錯套成今日盤中official close。
- Index與breadth Data Core read各自隔離；其中一個schema/read failure不會抹掉另一個已resolved component。

## CP8 handoff

- Existing `/indices/summary`的current-session acquisition仍含legacy provider orchestration；它不是本次completed official capability，後續需獨立onboard，不能與completed evidence混用。
- Frontend production build與最終browser-visible evidence列入CP8 final validation；目前targeted lint與TypeScript檢查已通過。
