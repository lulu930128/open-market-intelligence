# OMI 台股 Architecture Freeze Gate 長專案

## 任務識別

- 日期：2026-08-26
- Repo：`C:\project\Open Market Intelligence`
- 分支：`codex/tw-etf-provider-normalization`
- 前置專案：`docs/agent-runs/tw-shared-data-core-convergence-20260826/`
- 本輪性質：架構封版前的第二階段收束；不是 Shared Core foundation rewrite。

## Goal

把主要台股 outward market-truth 管線整理成單一、可執行、可驗證的 ownership model，使封版後的新功能不能再從 AI、Portfolio、GET router、sidecar 或 legacy freshness path 繞過 Shared Data Core。

最終 production flow：

```text
Provider / external source
  -> provider adapter
  -> canonical observation + raw receipt
  -> explicit transaction owner
  -> repository reread
  -> market-owned lifecycle / DatasetHealth
  -> shared quality evaluation
  -> existing Resolver
  -> market-owned evidence / valuation projection
  -> API / AI / MCP / Portfolio / Frontend
```

## Current verified baseline

- Shared QualityRequirement、Gateway typed quote/bars/depth/auction/current index/current breadth、canonical persistence、mandatory reread 與 Resolver 已成立。
- KGI/MIS quote/depth/auction、NStock/Yahoo intraday、current index/breadth 與 company profile source convergence 已有前一專案證據。
- Core GET intraday history、quote-depth、TW OHLC 與 index summary 已是 cache-only 或把 legacy refresh flag 降為無效。
- Realtime stream 已明示 `presentation_only`、`canonical_truth=false`、`decision_usable=false`、`research_usable=false`。
- CP0 consumer/provider import debt 已清空；台股 production source 未直接 import V1 `provider_policy` / `control_plane`。
- Prior task 曾完成 0069～0072 runtime adoption checkpoint；本輪任何 source 修改後必須重新驗證，不可沿用該 pass 宣稱新版本已 adopted。
- G5 official-session live acceptance 仍為 pending。

## Verified freeze blockers

1. Depth / Auction 已有 canonical path，但未進 Shared Dataset Registry、TW Dataset Catalog 與 dataset health probe。
2. Intraday、depth、auction、current index、current breadth candidate batches可回傳 `dataset_health=None`。
3. Auction capability vocabulary 內部使用 `auction`，AI/MCP outward 使用 `quote.auction`。
4. AI capability projection存在，但 production dependency只注入 public last-trade quote，沒有真實 depth/auction vertical evidence。
5. AI daily context仍使用 legacy `get_latest_stock_daily_price()` raw ORM reader。
6. Portfolio context直接 query TW quote/daily與regional daily models，自行持有 valuation fallback。
7. Shared Registry、TW Catalog、`TAIWAN_DATASET_SPECS`、source health、AI freshness與cache probe分別持有部分 lifecycle/freshness truth。
8. 多個 GET 仍可透過 `ensure_*` / `refresh` 進入 provider IO或DB mutation。
9. Institutional holding ratio GET直接呼叫nStock，未分類、無canonical persistence、RawFetchResult或dataset health。
10. Futures quote/intraday GET仍允許consumer指定provider並觸發refresh/commit。
11. Disposition雖為cache-only GET + explicit POST，但未進dataset catalog/health；其他sidecars的分類與guard不一致。
12. Shared `market_data/eod_coverage.py`仍持有已allowlist的commit/rollback debt。

## Non-goals

- 不重寫 MarketDataGateway、Resolver、central quality、daily OHLCV、technical engine或completed official index/breadth。
- 不建立第二套 Dataset Registry、freshness evaluator、Resolver或lease framework。
- 不把 provider-specific stream telemetry持久化成每250～500ms canonical DB events。
- 不把 quote、depth、auction、official close合併成偽單一 lineage或單一 health。
- 不把所有 compatibility / lineage-gap dataset一次big-bang migration。
- 不整理 US provider integration、scheduler、DB contention或其他並行工作。
- 本 planning checkpoint不修改production code、schema、runtime或user DB。
- 不commit、push、publish、stage、stash、reset、rebase或clean。

## Hard constraints

- Shared generic core不得import或硬編KGI、MIS、Yahoo、NStock、TAIFEX或TW session規則。
- Provider adapter只做IO、parse、provider-specific error normalization與canonical conversion；不得commit/rollback。
- Registered production dataset的DatasetHealth必須由market-owned lifecycle evaluator提供；Gateway不得猜TW session/freshness。
- Provider Health、Dataset Health、Resolved Evidence Health保持分離。
- AI/MCP/Portfolio/Frontend只能提出intent或消費projection，不得自行選provider或重建fallback/freshness。
- GET不得provider IO、subscription、repair或DB mutation；命令使用POST/job/lease等explicit surface。
- Unknown、missing、partial、not applicable、indicative與actual trade不得互相替代。
- Capability rename若影響durable identity，必須先read-only inventory，再採formal alias或migration；不可blind string replace。
- 所有source package完成後才可進runtime adoption；source pass不能替代live-session acceptance。
- Dirty worktree現有160 entries視為使用者/並行工作，task-owned diff必須可辨識且不得覆蓋無關hunks。

## Trust boundaries

- Market Data Foundation：canonical observation、raw receipt、transaction、repository、health、quality、Resolver。
- TW market layer：TW session、instrument eligibility、auction applicability、registered universe與provisional/final interpretation。
- AI/Research：evidence orchestration與answer contract，不擁有市場資料fallback。
- Account/Portfolio：position/cost/cash來自Account Plane；valuation price來自Market Data Resolver。
- Frontend/MCP：thin consumer；presentation telemetry不可升格為research truth。

## Deliverables

- `ArchitectureMap.md`：current/target owner map與斷點。
- `Plan.md`：phase、gate、依賴、stop-and-fix與rollback。
- `WorkPackages.md`：每一包scope、acceptance與validation。
- `AcceptanceMatrix.md`：requirements到evidence的追蹤矩陣。
- `ValidationStrategy.md`：source、migration、runtime與live分層驗證。
- `RiskRegister.md`、`DecisionLog.md`、`ExecutionBoard.md`。
- 每包source/runtime/live evidence放入`artifacts/`，保留實際pass/fail/pending。

## Done criteria

- [ ] Depth / auction具有canonical capability ID、dataset spec、catalog contract、probe與executable DatasetHealth。
- [ ] Registered production results不再以`dataset_health=None`對外。
- [ ] AI quote/depth/auction/official-close由同一market-owned evidence bundle編排，但各component保留獨立result/health/lineage。
- [ ] AI daily與Portfolio valuation不再直接query market price ORM models。
- [ ] 所有台股GET都為cache-only；legacy refresh flags只能忽略或明確拒絕。
- [ ] Institutional holding ratio與所有sidecars都有明確catalog分類、owner、refresh與limitation。
- [ ] Futures consumer不再指定production provider，GET不再refresh/commit。
- [ ] Registry/lifecycle成為executable dataset authority；AI/source health不再重建freshness。
- [ ] V1 boundary、stream presentation-only、core GET與completed official paths無regression。
- [ ] Targeted backend、architecture、AI/MCP、frontend與migration tests通過。
- [ ] 新source由named launcher重新adopt並通過direct/proxy/MCP/UI smoke。
- [ ] M5在合法session完成Preopen/Opening/Regular/Closing/symbol-switch/L5/cleanup；未取得者維持pending。

## Open questions / implementation-time checks

- User DB是否已有`capability_id="auction"`的durable receipt/source identity；未inventory前不決定direct rename或alias migration。
- Depth/auction dataset ID暫定`tw.quote.order_book.snapshot`與`tw.quote.auction.snapshot`，實作前需和既有schema/projection命名做final contract review。
- Disposition與institutional holding ratio應升為canonical storage，或先列`COMPATIBILITY` / `NONCANONICAL_CACHE`；由decision impact與replay需求決定。
- EOD transaction debt是否納入本輪closure，取決於P0/P1完成後的risk budget；不得阻塞更高優先級修正。

## Final closure addendum — 2026-08-26

本段取代前述「verified freeze blockers」作為目前source closeout範圍；前述清單保留為當時baseline，不代表現在仍未修。

- Daily source health不得再與`tw_daily_freshness`競爭platform-owned price freshness authority。
- Disposition cache missing/stale/degraded/malformed時，不得把false-y `is_active`推定成continuous/time-bars semantics。
- `AuctionType.INTRADAY`必須走typed request、canonical converter、transaction type guard與repository type-specific reread；只有TW market policy能決定適用性。
- Generic dataset storage/lineage probe outward名稱必須明示`platform-evidence`，不得冒充完整lifecycle health。
- Quote bundle必須外顯requested/acquired/materialized scope；consumer vocabulary使用`quote.snapshot`，內部`quote.last_trade` alias只存在market-owned boundary。
- 完成source regression與exact checkpoint後才可恢復`SOURCE_FROZEN`；runtime adoption與official-session live acceptance仍是後續獨立gate。
