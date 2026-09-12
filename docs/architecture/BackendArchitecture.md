# OMI Backend Architecture

## 盤後分批與個股優先需求

Daily EOD 沿用既有 full-market coverage／checkpoint 與 market-owned acquisition。
美股 bounded shard 若 canonical current count 已增加、沒有 provider error 且仍有
未處理候選，可回傳 `continuation_required=true`：該批正常結束，但
`postcondition_met=false` 與 partial coverage 必須保留。無進展、錯誤或來源未提供
當期資料不得藉此報成成功。

`jobs/market_refresh_priority.py` 擁有明示 foreground demand 的持久化 transaction；
Shared EOD 只接受注入的 bounded priority-reader callback，不反向依賴 jobs。
需求依正式 instrument master identity 去重並到期失效，不保存或重算市場 evidence。
美股於每個 symbol boundary 重新讀取 priority，跨 shard 的 attempted counter 每五次
保留一次給原背景候選；台股提升所屬 venue bulk，避免逐股重複 acquisition。
Priority 不繞過 release／provider backoff／bounds，也不強殺執行中的 provider request。

此入口目前僅對接 Daily EOD；完整跨 dataset queue、全市場分鐘線、全域共享配額與
多程序 worker lease 的收斂仍屬 active exec plan，不因本需求表存在而宣稱已完成。

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

Public canonical contract 不得隨意破壞；breaking change 必須有明確 consumer impact、版本或 migration window、cutover 與 removal gate。Private、diagnostic、migration-only surface 不因曾有 caller 就自動永久相容。任何暫留 compatibility seam 都必須登錄 owner、reason、consumer、scope、sunset condition、removal gate、negative test 與必要的 architecture debt。

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

能力狀態可以彼此不同，例如：

```text
Capability A = available
Capability B = plan_restricted
Capability C = unavailable
```

這只是抽象語意範例，不代表 current runtime state；實際狀態由 runtime capability schema 與 live evidence 判定。

## 6. Canonical Observation Layer

Shared boundary：`backend/app/market_data/`。此 boundary 保存 provider-neutral typed contracts、pure resolution、Dataset Registry、Gateway ports 與 quality／health primitives；market-specific acquisition、persistence owner 與 consumer projection 留在各自明確 owner。實際 source、runtime、live 與 product adoption 狀態另見 [`CurrentImplementationState.md`](CurrentImplementationState.md)。

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

`BarFinalization` 只描述該 bar／time bucket 的成熟程度，不代表 official daily 已發布。Market Session、item finalization、authority、release、reconciliation 與 freshness 的正交規則見 [`MarketTemporalContract.md`](MarketTemporalContract.md)；不得建立混合這些維度的 universal temporal enum。

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

Provider resource health 保留獨立維度：enablement、connection、entitlement、operational request health、evidence freshness；不得用單一 status 壓平原因。同一 provider 的不同 endpoint／feed／capability 以 additive `resource_id` 分開識別；缺少 `resource_id` 的舊 producer 只作相容 fallback，不得覆蓋更精確的 resource-level evidence。

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

Internal data requirement 不自動成為 public request enum。Outward request policy 由 [`OmiDecisionContract.md`](OmiDecisionContract.md) 管理，consumer 不得依賴 internal requirement 名稱。

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

#### United States completed-session consumer boundary

美股completed daily的正式read／refresh owner固定為`USDailyOhlcvPlatform`。US market boundary負責instrument identity、calendar／release、provider acquisition與receipt + canonical bar transaction；Shared Gateway負責plan與mandatory reread，Shared Resolver／Quality負責final selection、fallback與decision usability。

- GET、AI、research、valuation、technical、watchlist、overnight／ADR與cross-market consumer只讀resolved bars或US stable projection，不得import `USDailyPrice`來選provider、判current或找previous close。
- Historical／point-in-time read以typed requirement的`requested_at`傳入raw receipt `available_at` cutoff；晚到backfill不會倒灌當時的research context。
- Public chart與daily history的legacy response shape只是canonical selected bars的compatibility projection；deprecated provider參數不控制selection，也不觸發acquisition。
- Explicit refresh固定走`read -> resolve -> plan -> acquire -> persist -> reread -> resolve -> postcondition`；provider fetch成功但persist／reread／expected-session postcondition失敗時不得回success。
- Daily provider inventory由V2 executable descriptors投影：Yahoo Chart是P1；Alpaca SIP historical bars是P2；Alpha Vantage Daily不在production inventory。Quote／Intraday使用獨立capability inventory：Yahoo P1明確標示`can_produce_live=False`，Twelve Data P2保留`PARTIAL_US_MARKET_VOLUME`，兩者只經`USIntradayMarketPlatform`、Shared Gateway與Shared Resolver。Twelve Data不進Daily production plan，source integration也不等於runtime／live acceptance。
- US Quote與Intraday Bars是分離的dataset lifecycle，但共用同一個application boundary。Read path只讀`us_quote_snapshot`或帶完整`market_intraday_bar_lineage`的persisted candidates；legacy無lineage row不得進Resolver。Refresh path才可執行bounded provider I/O，且必須在transaction commit後由Gateway reread再resolve。Previous Close與Volume Pace只能使用resolved Daily evidence，不得直接對`USDailyPrice`另做provider selection或同日`max(volume)`。
- Quote refresh完成canonical reread後必須invalidate相關Intraday read model；Intraday snapshot revision涵蓋points、current observation與comparison reference，因此headline/truth變更不可被舊`since_revision`誤判為unchanged。US Daily／Weekly／Monthly與Intraday技術series由Backend Shared Technical Engine投影，帶algorithm／parameter contract；Frontend只能以backend authority顯示，缺失時維持unavailable。Backend calendar缺失時本機時間估算只供顯示，consumer acquisition／polling policy必須fail closed。
- Persisted reread必須重建evidence-owned session並保留selected provider descriptor limitations；current request session只表示caller需求，不得改寫舊evidence。Intraday raw candidate read與provider acquisition range分離：raw reader在總row bound內查35 calendar days；`recurring_current` acquisition只查1 calendar day／最多600 bars，`bootstrap_latest_available`才可查最多5 calendar days／1000 bars。Acquisition executor在交給Gateway前同時強制`max_bars`與operation `max_rows`，provider多回的資料不能靠Gateway最後才拒絕。Volume Pace的5／20-session historical baseline另由repository對Resolver-selected provider／source執行最多35 calendar days、20 sessions的canonical lineage aggregate query，不載入無界1m rows，也不另做provider selection。
- `us_quote_snapshot`定位為recent canonical quote cache，retention horizon定為30 calendar days；清理責任屬於US market maintenance/job boundary，不得放在GET、repository read或refresh transaction。Feature-off materializer將equity Quote／Intraday與US INDEX Quote／Intraday分成typed lanes；success postcondition由typed `USIntradayPlatformResult`依operation profile判定，Shared `MarketDataResultV1`不承擔US lifecycle語意。Requirement的typed `EvidenceTarget`明確分開`CURRENT`與`LATEST_AVAILABLE`：Recurring只在fresh且required fields完整時停止fallback；explicit `us.bootstrap_current_market_cache` tracked Job可在第一個usable latest-available candidate停止，但freshness仍維持stale／not-live，cache已滿足時零provider call no-op。Default bootstrap budget固定為16個normal-path calls加2個bounded fallback headroom，總額18；normal path涵蓋6個Index與2個Equity各自的Quote／Intraday lane。Operation ledger只計實際acquisition summary，persist／reread失敗則由typed post-acquisition error保留已知calls，不再於provider I/O前永久預扣整個symbol budget。Runtime summary除last result外，依lane + capability累積run／success／partial／failed／skipped、lock contention、duration、provider calls與refreshed symbols。三條scheduler仍共用non-blocking global lock；連續兩個interval因`materializer_run_in_flight`跳過同一lane是Runtime starvation blocker，Source階段不先重構scheduler owner。Retention registration獨立於materializer enable flag。這不授權full-market polling；runtime adoption、live cadence與擴大universe仍是獨立gate。
- US cash index volume的canonical invariant固定為`volume=null`與`volume_status=not_applicable`；Canonical producer、transaction與repository共同鎖住此規則。既有錯誤persisted rows只能經bounded、audited、reversible maintenance job修復，GET與consumer不得改寫或以`0`代替。Market-level六指數視圖由`app.us_market.market_indices`以同一caller-owned clock組合既有US Market Truth，固定順序為`^GSPC`、`^DJI`、`^IXIC`、`^NDX`、`^SOX`、`^VIX`；該aggregate不擁有provider selection、fetch、refresh或persistence，並由cache-only REST與`omi.decision.v4` `market.indices`共用。
- Completed-session executor只判斷expected session是否已有完整final OHLCV；Yahoo提供舊bar但缺expected session時必須標為stale／partial並繼續P2。Priority operation另外執行operation-wide symbol、external-call、provider-attempt與runtime budgets，單一symbol rollback／failure不得中止其他target。Daily persisted reader的`max_rows`是跨provider與unregistered rejection lane共用的總額，不能依provider數量放大。Provider winner、fallback與series coherence仍只由Shared Resolver決定。
- Full-market EOD的`current`／`partial`分類只接受與Daily repository相同的canonical eligibility：registered provider、row／raw receipt／Source Registry identity一致、parser contract相容、content hash一致、final／corrected OHLC、合法price relationships，以及依instrument區分的volume語意。Raw row存在但不合格只能形成partial diagnostic，不得被升級為current。
- Provider diagnostics與舊parser／storage helper可留在US-owned quarantine供遷移／診斷，但production consumer不得import；runtime rollout在source binding可用後仍獨立維持off，直到migration與launcher adoption另行驗證。

`us_consumer_canonical_daily_access` architecture rule封住AI、market與watchlist consumer對raw US daily ORM的回流。Source gate不代表runtime、live或product accepted。

#### Taiwan completed-session consumer boundary

台股 completed daily 的 public／research read owner 固定為
`TaiwanOfficialDailyBarRepository` 與 `daily_ohlcv_platform`。Repository 同時持有
official source identity、raw receipt、15:15 release qualification、active instrument
identity與deterministic duplicate reconciliation；consumer 不得再以
`MAX(market_daily_price.trade_date)`、raw row存在或自己的provider priority決定
completed session truth。

衍生 consumer 只可從 canonical read port 取值：

- Chart、legacy daily routes、valuation、next-session、ADR、volume pace、technical、chips、derivatives、Radar outcome/automation/backtest、index contribution與stock market-cap使用resolved daily series／universe或market-owned freshness projection。
- Taiwan index headline由market-owned typed resolution統一選擇：active session可選current observation，post-close可選qualified completed-session evidence；REST summary、Dashboard與AI只投影同一resolution identity、selected lineage與change reference，不共用raw latest-row heuristic或自行重選provider。
- Taiwan index headline compatibility seam由`app.market.index_resolution.project_taiwan_index_headline`擁有，只服務尚未帶有效`tw.index.resolution.v4`的legacy cached summary，consumer scope限Dashboard與AI `market.indices`。Fallback必須使用`compatibility.current_data_core.v1`、保留`INDEX_HEADLINE_COMPATIBILITY_FALLBACK` limitation且不得確認official close；當production summary一律提供有效v4、runtime parity證明fallback為零，並由malformed／missing resolution negative tests鎖定fail-visible行為後移除。
- Official breadth從同一canonical daily universe聚合，並額外要求component receipt coherence；不另列TWSE/TPEX provider winner。
- Completed-session stock sector／ranking由同一次canonical snapshot同時取得selected rows、active-stock denominator與TWSE／TPEX coverage counts；AI層不得另查第二份universe或把ETF列入stock aggregate。
- Official index exact/series由`official_index_platform`經`MarketDataGateway`與Resolver讀取；series可以bounded preload，但每一session仍經相同resolution policy。
- Historical／future `trade_date`只可在Data Core boundary clamp；AI、MCP、Frontend不得自行重做release calendar。

`tw_consumer_canonical_storage_access` Architecture Guard v2以AST import-name規則封住
protected normalized models。正式repository／transaction owner仍可讀storage；outward與
research consumer重新引入protected model時必須直接失敗，不以broad allowlist或新增
consumer-side fallback吸收。

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

台股 surface 的 current request lifecycle 採 demand-driven owner：

- Chart 先讀 canonical Bars 並立即繪製；Technical series 以同一 `session_scope` 非同步補強。History pin response-local `series_revision`；Current Session pin limit-independent `current_session_coverage.snapshot_revision`。Technical 的 calculation window 必須完整，response `limit` 只能裁切回傳 points，不得縮短 MA／VWAP warmup 或重選 session/provider。
- Technical report 與 Chart loading/error state 分離；volume pace 是明示 opt-in 的延後成本，預設 detail technical request 不等待它。
- Ranking 與 Radar 各自擁有 request lifecycle。Watchlist 順序先讀輕量 canonical snapshot；Radar 先讀 persisted snapshot，只有 active surface 才做後續 cache-only enhancement。
- Ranking／Radar 的 current-session price overlay 只讀 `TaiwanBarService` Unified Bar；不得回接 legacy `get_intraday_trend`／`tw_intraday_platform`。Radar persisted snapshot 404 應結束初始 loading 且不顯示錯誤；cache-only current computation 只能由既有 60 秒 enhancement lifecycle 延後執行，避免與個股 Chart critical path 競爭，且不得 refresh、enqueue 或寫入。MA／volume-MA／threshold defaults 由 Backend settings owner 解析，Frontend 不固定覆寫。
- Secondary detail、data panel 與 overnight context 由 viewport／展開需求啟動；未 demanded 的 surface 不建立 request。
- GET/read path 只做 cache-only revalidation。stale、partial、release-ready 或 missing 只能揭露狀態，不得由 `useEffect` 自動轉成 refresh／backfill POST；provider command 必須是明示使用者動作或 Backend scheduler owner。

上述 lifecycle 是 consumer cutover contract，不改變 freshness、session、resolution、repair 與 provider routing 的 Backend ownership。

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

同一份 bounded provider input 同時產生 legacy 與 canonical shadow；shadow 不改 outward selection。

### Phase 3 — Resolver Shadow

比較 legacy selection 與新 Resolver selection，保留差異、lineage 與 fail-closed gate。

### Phase 4 — Controlled Acquisition

需要 live evidence 時只能透過 policy 允許的 bounded lease／acquisition port；read path 不建立無界 subscription。

### Phase 5 — Consumer Cutover

依 bounded consumer slice 切換 backend API、AI、MCP、Frontend 與其他 consumer，並驗證 outward parity。

### Phase 6 — Dataset Registry

把 dataset lifecycle、refresh bounds、health 與 projection 對齊 executable registry；不另建重複 business inventory。

### Phase 7 — Capability Validation

Architecture／contract tests 保護 advertised、refreshable、supported 與 decision-usable capability 的 truthful projection。

### Phase 8 — Legacy Removal

Migration 完成條件同時包含 new path works、production consumer 已切換、old production path unreachable、compatibility seam 有明確處置，以及相關 architecture debt 被移除。最後已記錄的 implementation checkpoint 不放在本文件，統一由 [`CurrentImplementationState.md`](CurrentImplementationState.md) 導航。

## 21. 驗證層級

至少建立以下 contract tests：

- Canonical serialization。
- KGI TW / MIS adapter。
- 適用 market/provider adapter 的 canonical conversion 與 failure contract。
- Resolver primary/fallback。
- require_live / prefer_live / cache_only。
- Viewer / Research Lease lifecycle 與 bounded ownership。
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

### Taiwan stock comparison reference

台股比較基準由 `quote_depth.project_taiwan_quote_evidence_bundle` 擁有，使用 additive typed `change_reference`。既有 quote evidence bundle 在同次 cache-only daily read 讀取最多兩筆 canonical daily bars，不新增 provider acquisition、cache 或寫入。Provider `previous_close` 保留原值。官方 close/change 或同 session 的 resolved quote 可建立基準數值；只有核對前一交易日的 canonical close 相符，才能確認 prior-close 日期與類型。缺少該證據時保留 partial 與未知日期；官方有效基準不同於前收時標記 exchange reference，不推論 corporate-action 原因。`lineage` 與 `prior_close_lineage` 分別保留數值來源與日期核對證據。

REST quote-depth、legacy Chart quote-side、Today、Depth/Auction、AI/MCP 共用此 projection。`applies_to_trade_date` 表示適用 session，與基準歷史 `trade_date` 分開；Depth/Auction 用途另核對 selected component 的 event date。Legacy Chart 的 `previous_close` 僅作 resolved reference 的 presentation alias，並附完整 `change_reference`，不回寫 provider evidence。Bar/Technical 契約維持原責任，Frontend 不以 daily close/change 重建缺值。ADR comparison 從同份有界 daily evidence 依 trade_date 選最新有效 row，不依賴兩日序列的排列位置。Reference research eligibility 與 price availability 分離；盤後價格確認使用 session/official close evidence，不以 actual-trade availability 替代。


### 台股 breadth 對帳、門檻與價格前態

`tw_breadth_projection.project_breadth_coverage` 擁有 additive 接收／可分類比例與獨立 partition 投影。Canonical unknown 不含 missing；Dashboard legacy unknown 包含 missing。Dashboard 的舊 coverage_reason_counts 只保留摘要相容投影，細項由 classification_reason_counts 承載；移除舊摘要的 gate 是 Dashboard/MCP consumer 採用新欄位並完成版本遷移，禁止再把細項加回舊摘要加總。

`MarketBreadthObservation.limits` 是 actual-trade 對交易所門檻的觀測計數及各側可判定範圍。只有非空 universe 全部可判定，outward limit_up_count/limit_down_count 才有精確值；缺門檻不轉成 false/0。方向、limit、資料接收與 decision usability 分開。分類子原因只細分 mapping_error，不由無成交推論停牌。

逐股價格前態存於既有 current breadth snapshot 的 typed companion JSON，與原 observation/receipt 由同一 transaction owner 保存。Public quote repository 的 shared current-stock reader 合併同日、同 venue 的 MIS quote actual observations 與 breadth companion，逐筆核對原 receipt/hash/source；acquisition 與 cache-only quote consumer 共用此讀取結果。Provider 接受明確前態，不持有程序全域價格 cache、不讀寫 DB。缺少本次成交價不清除最後真實成交；carry-forward 保留原價格時間與 receipt，不以本次接收時間更新原價格 freshness。最新 observation lineage 與價格 lineage 分開投影。沒有可信歷史前態時保持缺值直到取得新 actual evidence。

Minute-state derived v3 依成交額所屬 component 的 event minute 檢查 bucket coherence；舊 breadth 金額不得隨 index refresh 變成新分鐘觀測。分鐘差額要求相鄰 bucket、兩市場資料齊全、來源／scope／semantics 可比較且各自累計不倒退。Read path 對既有 rows 同樣檢查 lineage/coherence，不重寫歷史 DB。

盤中 current index 與 completed official close 分開；official close 缺失保持 null。TAIEX canonical daily source 可由既有 official index repository 讀取，仍驗證 receipt、發布時間與日期。盤前估算使用獨立 indicative lane，TPEX 股數由 dated issued-shares owner 提供。技術報告須有明確 complete-prefix/session coverage 才使用開盤區間與量速；未知 coverage 不等同完整。AI 保留 current-session coverage、materialization policy 與按 capability 區分的 acquisition diagnostics，cache-only 不觸發補洞。前日收盤缺少足夠公司行動確認時，不替代當日比較基準。

Migration 20260908_0082 為 additive nullable companion 欄位。Current repository 的舊 schema read seam 僅為部署遷移窗口：缺 companion columns 時 defer 欄位並返回未知，不能在 read path 自動升級；所有支援 DB 採用此 revision 後移除 seam。Persistence 需要完成 migration。

官方日線 breadth 沿用 official_breadth_platform/repository，`read_taiwan_breadth_lanes` 在 completed-session 需求下提供 shadow 比較；active_ordinary_stock_universe 不替換 current registered universe。Legacy completed breadth entry 改走此 cache-only owner，逐股 ±9.5% heuristic 不再輸出 exact limit count。TWSE MI_INDEX 股票合計沿用既有 RWD official-daily descriptor/acquisition，日線 transaction 同時保存 typed published breadth companion 至獨立 snapshot，與 raw receipt 原子提交。讀取只載入小型 canonical payload 與 receipt metadata，不載入 raw_text、不解析大型原文、不寫入；需同日、發布時間合格、可信官方來源及 requested_at 可見。其 scope 為交易所股票欄所有已公布分類，不與 registered/active-stock 範圍混用。官方 lane 可提供此 aggregate，current_registered 主卡 selection 維持原範圍；aggregate 不可用時保留 daily-derived evidence 與限制。

`PublishedBreadthLimits` 表示交易所公布的合計，與逐股 `BreadthLimitObservation` 分開：不以 aggregate 填造 evaluated_count。精確漲跌停與整體 breadth 的 partial 狀態可並存，完整總數不等於所有研究證據可用，也不由 session close 單獨推導 finality。前端只做 exact/observed/unconfirmed 呈現；有可判定樣本的 observed zero 顯示 0，零可判定樣本維持尚未確認。Coverage、scope、來源與官方比較可展開，影響主卡解讀的狀態維持可見。

0083 正式採用前的 schema compatibility 僅允許略過尚無 published snapshot 的讀寫，回傳 persistence limitation；正式 DB 全數採用後移除此 seam。既有 receipt 不由 GET 自動回填，需受控重新處理或後續 acquisition。TPEX published aggregate 仍未接入，缺精確來源時保持 unknown。

整合驗證補充：TWSE published breadth 的純解析與 typed payload 位於 `app/parsers/twse_published_breadth.py`，read repository 不反向依賴 provider adapter。Completed Dashboard 保留 resolver 允許的 partial facts，並沿用 official breadth projection 的 aggregate scope／精確合計與 usability。新增 price-state reader 的 schema inspection 使用 session-owned connection，避免 Engine inspector 干擾尚未提交的 SQLite transaction。
