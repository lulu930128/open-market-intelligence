# Architecture Audit and Target Contract

## 1. 結論

兩份附件的核心方向正確，也與 current product truth 一致：台股不該再擁有一套平行資料平台，而應成為 OMI 唯一 Shared Market Data Platform 的 reference production market。

目前 checkout 確實尚未達成這個目標。Shared contracts、pure Resolver、dark Control Plane、Research Lease 與 Dataset Registry 已存在，但台股 production acquisition/fallback 仍主要由 legacy market service、router 與 AI context 持有。

本工程需要「完整重架構」，但執行形式必須是 production-safe vertical-slice migration，不是一次替換所有檔案。Big Bang 會同時改變 provider IO、session semantics、DB ownership、public API、AI 與 UI，無法隔離錯誤或回退，違反 `QualityBar.md` 與 `Roadmap.md`。

本次計畫已改為 actual-data-first。既有 realtime M5 與 KGI 不再是共同平台前置條件；第一條 production slice 改用可在 completed-session 穩定驗收的 TWSE／TPEx official daily OHLCV，先證明 acquisition、canonical、persistence、Resolver、Lifecycle 與 outward projection 是同一條真實管線。

## 2. 輸入文件與 current truth

- 附件：架構提案、gap list、contract canvas、acceptance ideas。
- Current truth：repo `AGENTS.md`、`docs/product/*`、`docs/architecture/BackendArchitecture.md`、`docs/architecture/OmiDecisionContract.md`。
- 現有程式、tests、branch/worktree：目前 checkout 的實際證據。
- `docs/agent-runs/*`：既有里程碑與歷史證據；不可覆蓋 current truth，也不可把 dark/source status 說成 production completion。

## 3. 現況證據

| ID | 附件判斷 | Current verification | 判定 |
| --- | --- | --- | --- |
| TW-01 | `quote_depth` 自行做 KGI -> MIS fallback | `quote_depth.py` 直接 import KGI/MIS adapter；`get_taiwan_stock_quote_depth()` 先讀 KGI、失敗再抓 MIS；`_with_kgi_primary_metadata()` 建立 source chain/fallback reason | confirmed P0 |
| TW-02 | `intraday` 自行做 NStock -> Yahoo -> MIS | `_load_intraday_trend_uncached()` 依序嘗試 NStock、Yahoo、MIS 並在 service 內記 fallback operation | confirmed P0 |
| TW-03 | Intraday 跨 provider 拼欄位 | `_apply_mis_volume_adjustment()` 會把 NStock/Yahoo bars 與 MIS price/volume 寫回同一 points/result，並標 `provider=composite` | confirmed P0 |
| TW-04 | 缺少 TW Provider Descriptor / Acquisition Policy | `backend/app/market/` 沒有 production `market_data_policy.py` 或 `TW_PROVIDER_DESCRIPTORS` | confirmed P0 |
| TW-05 | Shared Control Plane 仍 dark | `provider_policy.py` 明示 deliberately unwired；production app 沒有呼叫 `execute_acquisition()`；TW app 沒有呼叫 shared `resolve_*()` | confirmed P0 |
| TW-06 | `indices.py` 同時擁有 IO、fallback 與 TW semantics | 檔案直接 import TWSE/TPEx/MIS/Yahoo；`_get_market_index_intraday_prefer_live()` 自行 official -> Yahoo/MIS -> persisted fallback | confirmed P1 |
| TW-07 | Generic lease/router 直接綁 KGI | `routers/market.py` 直接 import/acquire/heartbeat/release KGI lease，realtime stream 直接讀 KGI runtime snapshot | confirmed P1 |
| TW-08 | Chart read 可啟動 official backfill | `list_stock_ohlc_chart_data(... ensure_history=True)` 仍可直接呼叫 TWSE/TPEx backfill | confirmed seam；預設與目前 frontend 已是 `false`，風險低於附件敘述 |
| TW-09 | Dataset Registry 未成為 runtime truth | Registry 已註冊核心 dataset，但 runtime app 主要只用它做 capability/projection consistency；`evaluate_dataset_health()` 無 production lifecycle caller | confirmed P1 |
| TW-10 | AI 仍吃 legacy TW services/provider controls | `ai/tools.py` 直接注入 intraday/quote/source-health services；`taiwan_stock.py` 仍處理 `provider`、`strict_provider`、fallback/refresh control | confirmed P1 |
| TW-11 | TW technical 尚未完全 shared | EMA/RSI/MACD/KD/PVO primitive 已委派到 `app.research.technical.series`；但 TW pipeline仍直接讀 DB、聚合與建立完整 TW projection | partially resolved；ownership/input仍未 converged |
| TW-12 | Frontend 指標數學可能與 backend 不一致 | `indicatorMath.ts` EMA first-value seed、RSI rolling average；另有 `IntradayTrendChart.tsx`、`stock-k-line/indicatorProjection.ts` 的 local implementations | confirmed P1，範圍大於附件單一檔案 |

## 4. Existing actual-data inventory

現有系統並非沒有真實台股資料，而是 production ingestion、storage、coverage 與 consumer semantics 尚未由同一 Data Core contract 擁有。這個差異決定了重構應先接管現有可靠資產，而不是再造一條平行 pipeline。

| Asset | Verified current behavior | Reuse decision |
| --- | --- | --- |
| `SourceRegistry` | 保存source identity、endpoint、priority、parser/auth、last success/error | 沿用為source identity/operational metadata；不升格成capability policy catalog |
| `RawFetchResult` | 保存source、fetch log、fetched_at、URL/method/status、content hash與raw payload/file | 沿用作raw receipt與fetched lineage；由transaction owner管理 |
| `MarketDailyPrice` | 以`(source_id, stock_id, trade_date)`唯一保存source-scoped TW OHLCV，連到raw result | 第一條Canonical Bar candidate store；repository負責row -> candidate，不讓model選源 |
| `MarketIntradayBar` | 以provider/stock/interval/bar_time唯一保存intraday bar與source | CP5 candidate store候選；先補event/received/quality contract audit |
| `TaiwanStockQuoteSnapshot` | 保存provider、session、quote time、OHLC、volume、level1/depth JSON、raw payload與fetched_at | CP5 quote candidate store候選；KGI rows可留legacy但不作本次gate |
| `MarketDatasetCoverageCheckpoint` | 保存expected/latest date、universe hash、current/partial/stale/missing partition、repair state/cursor/backoff | 直接升為EOD lifecycle persisted checkpoint，不另造第二份coverage truth |
| `refresh_source()` + parse pipeline | TWSE/TPEx official bulk fetch、raw persist、parse與`MarketDailyPrice` write已能production執行 | 拆成/包成acquisition、canonical conversion與transaction seam；不能繼續讓一個函式同時成為platform owner |
| EOD coverage scheduler/job | 先compute coverage、只修unresolved venue、post-refresh recompute、release window/backoff/startup catch-up | 連到Dataset Registry runtime service；保留bounded與postcondition設計 |

### Schema decision at CP0

`MarketDailyPrice JOIN RawFetchResult JOIN SourceRegistry` 初步已能提供source、raw receipt、trade/event date、fetched_at與content hash，且source-scoped unique key適合idempotent candidate persistence。因此第一選擇是建立repository與application transaction seam沿用現有schema。

只有在contract tests證明以下資訊無法如實保存時才新增additive migration：received time與event time區分、parser/schema version、observation quality/provisional status、component limitations或不可由raw receipt重建的lineage。不得先建立generic observation blob再找用途。

## 5. 附件未充分列出的 shared-core 缺口

### 5.1 DataRequirement v1 太窄

目前 `DataRequirement` 只有 instrument、單一 capability、realtime policy、purpose、session、tradability、age 與 candidate bound。它尚不能完整表達：

- timeframe / interval / bar count / time range。
- completed-only / provisional policy。
- authority / minimum quality / required fields。
- dataset ID、coverage/postcondition。
- caller budget 與 request cancellation context。

不能只把附件範例欄位直接塞進 optional dict；需要 additive、typed v2 contract 與 v1 adapter。

### 5.2 ProviderDescriptor v1 不是 capability-resource 級

目前一個 descriptor 可列多個 capabilities，但 priority、timeout、session、health policy 共用。TW 的 KGI quote、KGI depth、MIS auction、TWSE official close、NStock intraday 需要 capability/resource 級 authority、bounds、quota 與 limitation。

目標是 additive `ProviderCapabilityDescriptorV2`：一筆 descriptor 對應 provider + market + capability + resource/venue scope；market domain 注入 catalog，shared core 不硬編碼 provider 名稱。

### 5.3 Dark Control Plane 只能處理極小範圍

- TW supported capability 目前只有 `quote.snapshot`、`quote.order_book`。
- `plan_acquisition()` 目前只允許 `DataPurpose.RESEARCH`；Viewer、Collector、Repair 都會 fail closed。
- 沒有 production cache candidate reader、pre-resolution、port registry、transaction owner 或 projection gateway。
- `prefer_live` 目前等同需要 acquisition；尚未先判斷現有 candidate 是否已滿足 requirement。

因此不能直接把 production service 指向現有 `execute_acquisition()`；必須先建立 application-level gateway 與 resolver-owned acquisition-needed seam。

### 5.4 Resolved types 尚未形成統一 integration envelope

Shared core 有 typed `ResolvedQuote`、`ResolvedDepth`、`ResolvedBarSeries`、`ResolvedTradingStatus`，但：

- 尚無 `ResolvedAuction`。
- 尚無統一承載 requirement、typed resolved result、dataset health、acquisition summary 與 limitations 的 application result。
- 尚無 durable dataset evidence family，不能把 chips/ETF/fundamentals/derivatives 硬塞成 quote/bar。

目標不是改成 untyped dict，而是 stable envelope + discriminated typed payload。

## 6. 目標 ownership

| Layer | Owns | Must not own |
| --- | --- | --- |
| TW Provider Adapter | provider IO/SDK/HTTP、auth/session、raw parse、provider error normalization、Canonical conversion | cross-provider priority/fallback、TW decision、DB transaction |
| TW Provider Catalog | capability/resource descriptors、authority、session/venue support、bounds、market-specific eligibility hint | provider IO、final selection |
| Shared Candidate Store Ports | cache/persistence candidate reads、explicit mutation contract | market policy、implicit commit |
| Shared Market Data Gateway | requirement validation、cache-first flow、planning、bounded acquisition、final resolver call、result envelope | provider-specific semantics、TW projection |
| Shared Control/Resolution | provider plan、lease coordination、candidate selection、fallback、freshness、health、lineage | public/UI formatting、TW trial/closing interpretation |
| Dataset Lifecycle | registry、expected state/date、eligibility、refresh operation、bounds、postcondition、repair status | provider raw IO、consumer-side repair |
| TW Market Policy/Projection | session、auction、official close、disposition、TWSE/TPEx、volume reconciliation、typed outward projection | provider selection/acquisition |
| Research/AI | capability request、resolved evidence research、decision contract | provider control、freshness/fallback reconstruction |
| Router/Frontend/MCP/Kuro | validation/transport/presentation/viewer intent | provider selection、market semantics、repair policy |

## 7. 目標 internal flow

```text
Consumer intent
  -> DataRequirementV2 / RefreshRequirementV1 / LeaseIntentV1
  -> MarketDataGateway
       -> candidate repository reads
       -> existing Resolver pre-check
       -> if policy unmet and bounded acquisition allowed:
            market-owned ProviderCapabilityDescriptors
            -> AcquisitionPlan
            -> Platform Lease/Control Plane
            -> market-owned acquisition ports
            -> canonical observations + raw receipts
            -> explicit idempotent persistence transaction owner
            -> candidate repository reread
       -> existing Resolver final selection
       -> Dataset Lifecycle postcondition/health
       -> MarketDataResultV1
  -> TW Market Policy / Reconciliation / Projection
  -> stable Data API / omi.decision.v4 / operations projection
```

### Cache-first semantics

- `cache_only`：只讀 candidate store -> Resolver；port call、external call、subscription = 0。
- `completed_session`：只讀 latest completed dataset；需要 repair 時產生 separate `RefreshRequirement`，不在 read 中啟動 live acquisition。
- `prefer_live`：先 resolve current candidates；已滿足就不 fetch；未滿足才依 bounded plan acquisition，可 truthful fallback。
- `require_live`：先 resolve；未滿足才建立 bounded acquisition/lease；仍未滿足就回 `policy_unsatisfied`，不冒充 live。

## 8. Integration contracts

### 8.1 DataRequirementV2

必填核心：

- `instrument` / bounded target set。
- `capability_id`。
- `purpose`。
- `realtime_policy`。
- `session_policy`。
- `requested_at`。
- `freshness_requirement`。
- `quality_requirement`。
- `bounds`。

Capability-specific typed request：

- quote/depth/auction：depth level、required fields。
- bars：interval/timeframe、range/bars、completed_only、price basis。
- index/breadth：index ID/universe、official/final requirement。
- durable dataset：dataset ID、target/range、required coverage/postcondition。

不包含 provider、provider URL、SQL、internal function name 或任意 backfill scope。

### 8.2 ProviderCapabilityDescriptorV2

- `provider_key`、`market`、`capability_id`、`resource_key`。
- `authority_class`、`venue_scope`、`supported_sessions`。
- `acquisition_modes`、`can_produce_live`。
- `priority` 或 market-owned deterministic rank policy。
- `timeout`、call/subscription/symbol/range bounds、quota class。
- `limitations`、health eligibility policy。

Shared core 接受注入後規劃，不持有 KGI/MIS/Yahoo/NStock production catalog。

### 8.3 MarketDataResultV1

- `requirement`。
- `resolved`：typed discriminated union，例如 Quote/Depth/Auction/BarSeries/TradingStatus/DatasetEvidence。
- `resolved_health`：selected provider/source/event/received/fetched/freshness/fallback/selection reason/limitations。
- `candidate_summary`。
- `provider_health`。
- `dataset_health`（適用時）。
- `acquisition_summary`：attempt/outcome/bounds/cleanup；不取代 resolver selection。

### 8.4 TW stable projection

TW projection 只接 resolved evidence，不接 provider port。它可組合多個已 resolve 的 component：

```text
ResolvedIntradayBars
+ ResolvedSessionVolume
-> TwIntradayVolumeReconciliation
-> TwIntradayProjection
```

Outward 必須保留 bar 與 volume 各自 lineage、time skew、reconciliation status/reason、unallocated volume 與 limitations；不得改寫成偽單一來源。

## 9. 統一輸出平台的邊界

「統一」表示單一 evidence semantics 與 integration owner，不表示單一 endpoint：

| Plane | Stable outward surface | Shared truth |
| --- | --- | --- |
| Data | 現有 `/api/market/*` 與後續 stable market projection | `MarketDataResult` + TW projection |
| Decision | HTTP/SSE/MCP `omi.decision.v4` | capability projection 使用同一 resolved result |
| Operations | source/provider/dataset health、jobs、settings | provider/dataset/resolved health 與 lifecycle |

Public route 第一階段保持相容。Provider-specific legacy fields只能是 lineage/compatibility alias，不得再控制 acquisition。

## 10. Actual-data-first migration strategy

| Order | Production slice | Why first/next | Required proof |
| --- | --- | --- | --- |
| CP0 | Persistence inventory/guards | 先決定沿用schema或migration，防止重做第二份truth | owner/reader/writer/unique/lineage/transaction map |
| CP1 | Additive common contract/Gateway | 給所有後續slice同一application入口 | zero-I/O、bounded acquisition、transaction/Resolver separation |
| CP2 | TWSE/TPEx official daily OHLCV | completed-session、official、已有真實ingress/storage，最適合證明全管線 | payload/receipt -> canonical -> persist -> reread -> resolve -> API |
| CP3 | Full-market EOD lifecycle | 已有coverage/scheduler資產，可把Registry變成runtime owner | expected date、bounded repair、postcondition、catch-up |
| CP4 | Official index/breadth | 第二個不同payload family，驗證平台不是OHLCV專用 | official data、typed projection、health/coverage |
| CP5 | Public request-time quote/intraday | 證明共同平台也能處理session/freshness，不依賴KGI | actual timestamp/session、bounded request、resolved outward |
| CP6 | Provider onboarding + durable datasets | 證明catalog/port可擴展，逐dataset收斂 | consumer unchanged、registry completeness |
| CP7 | AI/API/frontend/MCP/technical | Consumer只在platform truth穩定後切換 | v4 parity、cross-surface series equality |
| CP8 | Legacy removal/closure | 只有實際production adoption後才能刪舊owner | source inventory、runtime/UI/MCP、rollback |

各CP的scope、驗收命令與rollback詳見`Plan.md`。

## 11. Gate model

- CP0-CP1可使用fake/fixture建立contract，但CP2開始必須有actual provider payload或保存的raw receipt、真實DB write/readback與stable projection證據。
- 共同平台完成至少需要三條durable production-wired proofs與一條non-KGI request-time proof；source-only、shadow compare或測試double不能代替。
- KGI與既有realtime M5不阻塞CP0-CP8，也不計入`TW_DATA_CORE_COMMON_PLATFORM_OPERATIONAL`；它們是平台完成後的provider onboarding gate。
- 需要live-session語意的public capability仍需自己的dated session artifact，但不能借用post-close資料冒充live acceptance。
- 任一persist後postcondition不成立、lineage缺失、unknown coercion、unbounded IO、consumer provider control或public contract drift都stop-and-fix。
- 每個capability/dataset可獨立rollback到上一個已驗證mode；不得用一個全域開關同時切daily、intraday、index與datasets。
