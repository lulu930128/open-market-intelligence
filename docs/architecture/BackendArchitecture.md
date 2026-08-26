# OMI Backend Architecture

本文件描述 Open Market Intelligence backend 的長期穩定責任邊界。

它是 current architecture truth，不取代 repo `AGENTS.md` 的產品規則，也不取代單次 `docs/agent-runs/*` 任務紀錄。

## 1. 高階依賴方向

OMI backend 的長期依賴方向：

```text
FastAPI / Runtime / Jobs
        |
        v
Public Routers / AI Entry
        |
        v
Market / Research Services
        |
        v
Resolution / Control Plane
        |
        v
Canonical Observation Layer
        |
        v
Provider / Integration Adapters
        |
        v
External Providers / Broker SDK
```

資料 outward：

```text
Provider
  ↓
Canonical Observation
  ↓
Resolver
  ↓
Market / Research
  ↓
AI / API
  ↓
Frontend / MCP / Kuro
```

Account 另外獨立：

```text
Broker Account Provider
        ↓
Account Plane
        ↓
Position / Cost / Cash
        ↓
Portfolio Valuation
        ↑
Market Data Resolver / FX
```

依賴只沿箭頭方向前進。

## 2. 架構不變量

- Provider 不得偽裝成其他 provider。
- Consumer 不得自行選 provider。
- Cross-provider fallback 只由 Resolution / Control Plane 擁有。
- Unknown 不默認成 0。
- No Quote != No Trade。
- No Trade != Suspended。
- Market Session != Instrument Trading Status。
- Freshness 要考慮 instrument eligibility。
- Selected evidence 保留完整 lineage。
- Provider Health / Dataset Health / Resolved Evidence Health 分開。
- Account failure 與 Market Data failure 分開。
- Advertised capability 必須真的有 projection。

## 3. Runtime / FastAPI

- `backend/app/main.py` 只建立 FastAPI app、middleware、exception handlers 與 route registry。
- `backend/app/runtime.py` 擁有 startup/shutdown lifecycle。
- migration / schema ownership 延續 Alembic-only 原則；正常啟動不以 `Base.metadata.create_all()` 取代 migration。
- background leader lock、scheduler、collector ownership 由 runtime/job boundary 管理。
- follower process 不應重複執行 background collector。
- shutdown 只停止本 process 實際持有的 runtime resource。

## 4. Router

`backend/app/routers/`：

負責：

- HTTP schema。
- query/body validation。
- status code。
- service dispatch。
- outward response projection。

不得：

- 直接 import provider SDK/requests。
- 自己做 provider fallback。
- 自己重算 freshness/trading status。
- 擁有 market/business transaction logic。
- 直接 commit/rollback/flush。

Public route / method / response shape 預設向後相容。

## 5. Provider / Integration Layer

Provider adapter 負責：

- HTTP / SDK / WebSocket / subprocess。
- login / reconnect。
- subscribe / unsubscribe。
- bounded timeout。
- provider raw payload parsing。
- provider-specific error / entitlement normalization。
- 安全 source metadata。
- 轉成 Canonical Observation。

Provider adapter 不負責：

- 跨 provider priority。
- fallback。
- AI readiness。
- market decision。
- DB transaction。
- 偽裝另一 provider schema。

### KGI

KGI 可以有一個 shared isolated runtime，但能力分成：

```text
KGI Quote Port
KGI Data Port
KGI Account Port
```

它們可共用登入/runtime，不共用單一 capability health。

例如：

```text
KGI TW Quote = live
KGI Historical KBar = plan_restricted
KGI Account = unavailable/503
```

這是合法狀態。

## 6. Canonical Observation Layer

Shared boundary：`backend/app/market_data/`。Foundation v1 已建立typed contracts、pure resolution與Dataset Registry；Taiwan Data Core v2另以additive Gateway、typed requirement/result、candidate repository、bounded acquisition port與transaction owner完成第一批production source cutover。2026-08-25 production DB/runtime已由migration、launcher PID/port lineage、API/data、visible UI、MCP與cold restart evidence證明採用；active-session public quote acceptance仍是獨立gate。

核心 contracts：

### InstrumentKey

- market
- symbol
- instrument_type
- venue / listing；listed instrument 必填，避免同 market/symbol collision

### SourceLineage

- provider
- source
- event_time
- received_at / fetched_at
- capability-aware authority class
- cache_hit
- provider latency optional
- raw contract version optional

### QuoteObservation

- instrument
- lineage
- trade_date
- last_trade_price
- last_trade_volume
- cumulative_volume
- open/high/low/previous_close
- currency
- trade observation state：unknown / awaiting_first_trade / indicative_observed / trade_observed
- quote status

### DepthObservation

- depth_capability: none / level1 / level5
- bid levels
- ask levels
- best bid/ask
- spread

### AuctionObservation

- opening / closing
- indicative price
- indicative volume
- provisional semantics

### BarObservation

- interval
- start/end time
- OHLCV
- finalization：provisional / final / corrected / unknown

### TradingStatusObservation

Instrument tradability 只表示標的是否可交易：

- UNKNOWN
- TRADABLE
- HALTED
- SUSPENDED
- DELISTED
- NOT_APPLICABLE

以下維度不可塞回 tradability：

- Market Session：pre-open、opening auction、continuous、closing auction、post-close、closed。
- Trade Observation State：awaiting first trade、indicative observed、trade observed、unknown。
- Regulatory Flags：attention、disposition、abnormal、restricted。

### ProviderResourceHealth

Provider resource health 保留獨立維度：enablement、connection、entitlement、operational request health、evidence freshness；不得用單一 status 壓平原因。

## 7. Resolution / Control Plane

Resolution / Control Plane 是 market evidence selection 的唯一 owner。

負責：

- provider policy registry。
- candidate collection。
- provider selection。
- fallback。
- realtime policy。
- lease lifecycle。
- cache policy。
- freshness。
- trading-status resolution。
- dataset health。
- repair planning。
- source-health aggregation。
- selected evidence lineage。

Public policy 使用需求語意，不直接暴露 provider：

- cache_only
- prefer_live
- require_live

`completed_session` 在 Foundation v1 是 internal data requirement，尚未加入 public `omi.decision.v4` request enum。

## 8. Lease Lifecycle

### Viewer Lease

用途：Frontend selected symbol。

- persistent。
- heartbeat。
- user-view lifecycle。

### Research Lease

用途：AI / MCP `require_live`。

- request-scoped。
- bounded symbol count。
- bounded callback wait。
- request completion release。
- provider unavailable 時由 Resolver fallback。

### Collector Lease

用途：少量明確 bounded anchors。

禁止無界全市場 subscription。

## 9. Market-specific Services

### Taiwan

`backend/app/market/` 保留台股市場差異：

- TWSE/TPEX calendar。
- preopen/open/close microstructure。
- official close。
- regulation。
- futures/options。
- chips / broker branch。
- TW-specific dataset rules。

### United States

`backend/app/us_market/` 保留：

- US market calendar。
- premarket/regular/after-hours。
- corporate actions。
- SEC / FINRA / FRED integration。
- US-specific symbol / exchange / fundamentals semantics。

TW 與 US 都依賴共通 Canonical / Resolver，而不是互相複製 fallback architecture。

## 10. Shared Research

基於 Canonical OHLCV 的技術計算應優先共用：

- MA
- RSI
- MACD
- ATR
- KDJ
- Bollinger
- technical structure

市場差異只在真正會改變演算法語意的 policy。

## 11. Dataset Registry

Dataset Registry 是資料 lifecycle source of truth。

每個 production dataset 應能定義：

- dataset_id。
- market。
- owner service。
- frequency。
- expected-state policy。
- trading eligibility。
- refresh operation。
- refresh scope / budget。
- postcondition。
- health rule。
- stale rule。
- capability mapping。

用途：

- freshness。
- source health。
- repair。
- AI fill plan。
- scheduler ownership。

避免同一 dataset 的規則散在 freshness、scheduler、repair 與 capability registry。

Completed-session 全市場 EOD 使用獨立 durable coverage checkpoint：

- TW universe 是 active TWSE／TPEx ordinary stocks；repair 由兩個 official bulk source 擁有。
- US universe 是 active Nasdaq Trader non-ETF、non-test stocks；沒有 bulk daily provider 時，只允許 bounded、可續跑的 per-symbol shard，且不得宣稱單次全市場完成。
- checkpoint 保存 expected date、universe hash、current／partial／stale／missing、cursor、error budget 與 retry boundary；`JobRun` 只保存單次 execution evidence。
- cache-only GET 不得計算 provider freshness 或啟動 repair；scheduler-only full-market operation 不進 AI fill allowlist。

## 12. Freshness / Health

分三層：

### Provider Health

provider / capability 本身是否正常。

### Dataset Health

Canonical dataset 是否達到預期。

### Resolved Evidence Health

這次 request selected evidence 是否可用。

Persisted health 與 request-local health 可以分開保存，但 outward 必須有明確 effective semantics。

## 13. Trading Status

Trading Status 不屬於 Quote。

Quote unavailable 時，不得直接推斷停牌或 awaiting first trade。

Trading Status Resolver 可組合：

- official exchange / regulator evidence。
- broker provider hint。
- quote observation。
- market session。

官方 evidence 優先。

## 14. Provider HTTP Contract

`backend/app/http_client.py` 保持最低層 transport。

`backend/app/observability/provider_http.py` 負責：

- market/provider/resource/target identity。
- bounded timeout。
- timeout/rate_limited/blocked/failed/error classification。
- Retry-After。
- safe source URL。
- provider event metadata。

Provider HTTP 層不直接寫 DB。
Provider event persistence 由 service/job transaction owner 決定。

## 15. Source Health Persistence

Persisted source-health snapshot 與 request-local observation 不應互相取代。

建議 outward 可區分：

- request_health。
- persisted_health。
- effective_health。

GET read path 不應為了「讓 health 看起來新」隱性重跑全市場 provider refresh。

## 16. Transaction Ownership

- Query/read helper 不 commit。
- Provider adapter / canonical conversion / pure freshness helper 不持有 transaction。
- `upsert_*`、`refresh_*`、job worker、maintenance pipeline 是明確 transaction owner。
- transaction-owning service commit failure 必須 rollback 並 rethrow。
- provider telemetry persistence 不得污染 caller transaction。
- composite refresh 隔離單一 provider/symbol failure。
- 不提供「有時 commit、有時不 commit」的隱性 API；需要時拆 mutate / owning wrapper。

## 17. Account / Portfolio Plane

`backend/app/portfolio/` 不再被視為 Market Data provider branch。

Account Provider 提供：

- AccountStatus
- PositionObservation
- CostBasisObservation
- CashObservation

Sync rules：

- complete success 才 destructive replace provider-owned state。
- partial 保留未確認 state。
- 503/unavailable 保留既有 state。
- confirmed empty 才真正清空 provider-owned holdings。
- unknown cost 不轉 0。

Portfolio Valuation 永遠透過 Market Data Resolver 取得市場價。

## 18. AI / Capability Contract

`backend/app/ai/` 擁有：

- target resolution。
- capability selection。
- bounded query plan。
- evidence projection。
- decision core。
- answer contract。
- continuation/fill plan。

AI 不直接選 provider。

Capability Registry 必須有 contract test：

```text
advertised capability + scope
=> projection exists
```

Refreshable capability 另要求：

```text
=> refresh operation exists
```

`omi.decision.v4` 維持 public business contract；底層 provider/canonical migration 不應迫使 HTTP/SSE/MCP 分叉。

## 19. Frontend / MCP / Kuro

### Frontend

只呈現 backend contract 與發出 viewer intent。

### MCP

thin adapter，只轉送 public contract。

### Kuro

consumer，只負責 persona/workflow/presentation。

三者都不得：

- 直接讀 OMI DB。
- 自行 call market provider。
- 自行做 freshness/fallback/trading-status inference。

## 20. Migration Strategy

Market Data Foundation 採 Strangler Pattern。

### Phase 1 — Contract

新增 canonical contract，不改 runtime behavior。

### Phase 2 — Provider Shadow

KGI TW / MIS 同時產 legacy + canonical shadow。

### Phase 3 — Resolver Shadow

比較 legacy selection 與 new resolver selection。

### Phase 4 — Research Lease

AI/MCP require_live 可取得 bounded KGI research lease。

### Phase 5 — Consumer Cutover

依序切 AI/MCP、backend API、frontend。

### Phase 6 — Dataset Registry

先納入 TW/US quote、intraday、daily price，再擴大。

### Phase 7 — Capability Validation

CI 保護 truthful capability。

### Phase 8 — Legacy Removal

全部驗收後才刪 provider masquerading / legacy fallback。

### Foundation v1 source status（2026-08-19）

- Phase 1 typed contract：source-complete。
- Phase 2 KGI TW / MIS direct canonical adapter 與同 payload shadow/compare seam：source-complete，預設 mode `off`。
- Pure resolver、internal `completed_session` 與 acquisition port contract：source-complete；尚未接 production Research Lease。
- Dataset Registry v1：保留 TW quote/intraday/daily 與 US intraday/daily 五個 per-target 核心 dataset，另註冊 TW/US 兩個 full-market EOD coverage lifecycle dataset。
- Capability projection validation：TW/US core fixture registrations 已建立；`technical.indicators` 與 `technical.structure` 已有 US resolved daily research projection，US full-market aggregates仍受 coverage gate 阻擋。
- Runtime adoption、KGI live smoke、canary/on、consumer cutover、DB persistence：尚未驗收，也不屬於本次 source-complete。

### Taiwan Data Core v2 source status（2026-08-25）

- `DataRequirementV2`／`RefreshRequirementV1`、`MarketDataGateway`、provider capability-resource descriptor、candidate repository ports、typed acquisition/persistence summary與`MarketDataResultV1`已建立；Gateway只做pre-read／plan／acquire／persist／mandatory reread／Resolver，不擁有provider或DB transaction。
- TWSE／TPEx official daily OHLCV已完成actual payload -> canonical -> source/raw + typed row transaction -> cold reread -> Resolver -> chart/API projection；cache-only daily read不接受`ensure_history`隱性backfill。
- Full-market EOD expected date、eligibility、venue-bounded repair、postcondition/checkpoint、startup catch-up與retry由Dataset Lifecycle contract約束；powered-off後可修completed-session EOD，不宣稱修復未保存intraday/depth。
- Official index與official breadth是不同canonical payload；breadth只由同venue/date/raw receipt official daily rows與registered universe導出，unknown與missing保持分離。
- Public request-time第一個capability是single-symbol TWSE MIS `quote.last_trade`，定位為personal-research best effort/no-SLA；quote不製造minute bar，未取得授權前不推定raw/value-added資料可向外轉播。
- Taiwan market-owned catalog現有28個production dataset contracts與18個bounded operations；Data Core health surface讀actual storage/lineage，lineage gap不冒充canonical或fresh。
- Taiwan AI quote context只讀Data Core projection；daily technical API與AI evidence共用Resolver-selected official OHLCV及`tw.technical.indicators.v3` algorithm/price-basis/parameter contract。Frontend只在authority metadata匹配時使用backend authoritative values，local math僅是presentation compatibility。
- `/indices/summary`分離current-session observation與completed official index/breadth；completed components只接受Data Core evidence，missing時fail closed，不回復legacy completed row。
- 已移除direct MIS snapshot-to-bar、台股OHLC GET隱性backfill與completed dashboard legacy fallback。Current-session index/intraday、depth/auction與KGI是尚未onboard的獨立capabilities，不得誤稱已完成。
- Production DB已由0066採用0067 index lineage與0068 public quote lineage；offline backup與clone downgrade/upgrade rehearsal通過。Named launcher runtime、Data Core API、TPEX actual official index persistence/cold read、visible browser與MCP `omi.decision.v4`均已驗收。
- TAIEX 2026-08-25 official source response缺target date、current public quote legacy row lineage incomplete、official breadth不完整與active-session F-07都保持truthful outward。F-07完成前label維持`TW_DATA_CORE_PRODUCTION_ADOPTED_F07_PENDING`，不得標記common platform operational。

### US first-class Foundation source status（2026-08-23）

- US capability truth gate已修正：market.breadth在真實US projection完成前只宣告TW，US target會truthful unsupported。
- Shared provider policy可接受market owner注入的US quote／intraday／daily descriptors；Yahoo／Alpha Vantage catalog仍由app.us_market擁有，shared Foundation不持有production provider catalog。
- Yahoo chart 1m／1d與Alpha Vantage daily已有pure canonical adapters，輸出provider-neutral quote／bars、US session mapping、timezone-aware lineage、bar finalization與raw price basis；adapter不做IO、DB write或fallback。
- US resolved quote／bars已有neutral schema projection seam；legacy TW-named schema只列compatibility，不再作新US canonical identity。
- Yahoo intraday在canonical mode shadow／compare時重用同一已取得payload做bounded comparison；off不執行canonical conversion，shadow／compare不改legacy selected outward result。
- Production AI／API已可在compare canary通過後消費resolved US quote／intraday／daily projection；KGI US live仍因source readiness未通過而fail closed。

### US first-class Shared Research 與 consumer convergence（2026-08-23）

- `app.research.technical` 是provider-neutral pure research boundary；TW compatibility wrapper與US engine共用SMA-seeded EMA、Wilder RSI、MACD、KD與PVO numerical primitives。
- Versioned `MarketAnalysisProfile` 分開US／TW的windows、minimum bars、currency、calendar、timezone、session、benchmark、price basis與corporate-action policy；US v1使用MA 5／10／20／50／60／200，completed daily raw-unadjusted bars。
- `app.us_market.research_service` 只讀resolved cache，不觸發provider IO或DB write；輸出 `omi.us_market.research.v1`、`omi.research.technical.indicators.v1`與`omi.research.technical.structure.v1`。
- US corporate-action completeness尚無checkpoint，因此AAPL等有足夠bars的technical facts可用，但 `decision_usable=false`，不得把raw-price structure描述成完整決策證據。
- `/api/us-market/intraday/{symbol}` 由backend依America/New_York session anchor聚合1m／5m／15m／30m／1h／4h，regular、pre-market與after-hours不混桶，並揭露source/effective interval、aggregation method與partial-bar status。
- Frontend不再用GET隱性補抓US OHLC，也不再自行產生canonical MA／technical title或professional intraday aggregation；read/refresh ownership已分開。
- Local universe與provider-reported sector/industry coverage已有versioned gate；因expected full universe、standard taxonomy與effective membership date尚未證明，US `market.breadth`、`market.sectors`與`market.hot_groups`繼續truthful unsupported。

## 21. 驗證層級

至少建立以下 contract tests：

- Canonical serialization。
- KGI TW / MIS adapter。
- KGI US / Yahoo / AlphaVantage adapter（後續 integration milestone）。
- Resolver primary/fallback。
- require_live / prefer_live / cache_only。
- Viewer / Research Lease lifecycle（後續 integration milestone）。
- Trading Status。
- Dataset expected / stale / not-applicable。
- Provider / Dataset / Resolved Health。
- Capability advertised/projection consistency。
- Account partial/503/unknown cost。
- API/MCP contract inventory。

跨 Market Data Foundation 修改後，使用 repo safe validation wrapper 與最接近 regression tests。

## 22. 後續拆分原則

大型檔案只按穩定責任拆，不按行數拆。

優先抽離：

- provider IO。
- canonical conversion。
- resolver。
- dataset lifecycle。
- pure research projection。
- outward schema conversion。

避免同一批同時：

- 重寫 provider。
- 改 public route。
- 改 DB。
- 改 frontend。
- 刪 legacy compatibility。

先建立可驗證 seam，再逐步 cutover。
