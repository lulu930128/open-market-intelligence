# Plan

## 執行原則

- 這是 actual-data-first umbrella plan；共同 contract 必須在第一條正式垂直切片中承載真實 TWSE／TPEx 資料，不能停在 dark/shadow。
- 前一 CP acceptance 未通過，不進入有依賴的下一個 CP；可獨立的文件、guard 或 fixture 工作不受影響。
- 每次只讓一個 capability/dataset family 進 production cutover，並在 `Progress.md`、`AcceptanceMatrix.md` 記錄 persisted/readback/runtime evidence。
- 先建立 compatibility adapter與rollback，再搬 ownership；不得先刪 legacy fallback 再補共同 Core。
- 既有 realtime M5 與 KGI 不在 CP0-CP8 的依賴鏈或完成判定內；平台完成後另開 KGI onboarding 計畫。

## Target component map

| Component | Target responsibility | Initial implementation seam |
| --- | --- | --- |
| `DataRequirementV2` | typed read requirement：target/capability/range/freshness/quality/bounds | `backend/app/market_data/contracts_v2.py` 或等價 additive module |
| `RefreshRequirementV1` | typed explicit mutation intent與postcondition | shared lifecycle/application contract |
| `ProviderCapabilityDescriptorV2` | provider + market + capability + resource的authority/bounds/limitations | TW catalog注入shared planner |
| `MarketDataGateway` | cache-first pre-resolve、bounded acquire、persist、reread、final resolve | `backend/app/market_data/gateway.py` |
| Candidate repositories | 將既有DB rows轉成canonical candidates；不選provider | repository interfaces + SQLAlchemy implementations |
| Acquisition ports | bounded provider IO + canonical conversion；不commit、不fallback | market-owned `backend/app/market/providers/` adapters |
| Transaction owner | raw receipt + canonical candidate idempotent write/rollback | application service / unit-of-work |
| Dataset Lifecycle | registry、expected date、eligibility、operation、postcondition、health | 連接既有registry、EOD coverage、scheduler/jobs |
| `MarketDataResultV1` | typed resolved payload + provider/dataset/resolved health + lineage | shared outward internal envelope |
| TW projection | session/official close/breadth/volume等market semantics | `backend/app/market/` |

實際檔名可在 CP0 根據現有 package 邊界微調，但 ownership 不可漂移。

## Common execution flow

```text
read(requirement)
  -> repository.load_candidates()
  -> Resolver.precheck()
  -> satisfied? return MarketDataResultV1
  -> policy permits acquisition?
       no  -> truthful missing/stale/policy_unsatisfied
       yes -> Planner(descriptors, provider health, bounds)
              -> AcquisitionPort.fetch()
              -> Canonical observations
              -> TransactionOwner.persist_idempotently()
              -> repository.load_candidates() again
              -> Resolver.resolve()
              -> DatasetLifecycle.evaluate_postcondition()
              -> MarketDataResultV1
```

`cache_only` 與一般 GET 在 `policy permits acquisition?` 必須永遠為 no。Completed-session repair 只能透過 `RefreshRequirementV1` 或 job執行。

## Milestones

### CP0 — Persistence inventory and boundary guards

- Scope：建立 current DB/data-flow inventory、legacy behavior fixtures、AST/import guard、migration decision record；不改 production behavior。
- Read model：
  - `market_daily_price`：source-scoped OHLCV，unique `(source_id, stock_id, trade_date)`。
  - `raw_fetch_result`：fetched_at、URL/method/status/content hash、raw receipt。
  - `source_registry`：source identity、priority與last success/error。
  - `market_dataset_coverage_checkpoint`：expected/latest date、coverage partition、repair state、postcondition evidence。
  - `market_intraday_bar`、`taiwan_stock_quote_snapshot`：後續 request-time candidate stores。
- Acceptance：
  - 每一 storage table有owner、writer、reader、unique/idempotency key、lineage欄位與transaction boundary map。
  - 產出「沿用現有schema」或「additive migration」的明確決策；不得憑偏好新增generic blob table。
  - 禁止router/AI/frontend新增provider-specific production control。
  - 禁止TW service新增cross-provider try/fallback/source-chain owner。
  - 現有violations有allowlisted debt；新增violation fail CI。
- Validation：targeted model/repository fixtures、AST/import tests、API contract inventory、`run-safe-validation.ps1 -Profile backend`。
- Stop：若現有row無法保留必要event/fetched/source/raw lineage，先設計migration與backfill/rollback，不進CP1 production write。

### CP1 — Additive common contracts and gateway

- Scope：`DataRequirementV2`、`RefreshRequirementV1`、capability-resource descriptor v2、`MarketDataResultV1`、candidate repository/transaction/acquisition ports、Gateway pre/post resolution seam；重用02A Resolver/Control Plane。
- Acceptance：
  - `cache_only` / completed-session read external calls = 0。
  - `prefer_live`在cache已滿足時external calls = 0；未滿足時只執行bounded plan。
  - `require_live`未滿足回`policy_unsatisfied`，不冒充live。
  - Adapter不commit、不選provider；repository不做IO acquisition；transaction owner不做resolution。
  - Stable result明確分離provider health、dataset health、resolved evidence health。
  - v1 compatibility tests通過，production routes尚不切換。
- Validation：serialization、invalid requirement、zero-I/O、fake repository/port、resolver selection、transaction rollback、duplicate/idempotency tests。
- Rollback：additive modules可完全不被production import；existing routes維持原路徑。

### CP2 — Actual vertical slice 1: official TW daily OHLCV

- Scope：將現有TWSE `STOCK_DAY_ALL`與TPEx official daily quotes的fetch/parse/persist路徑接入共同contract；以completed-session official data為第一條production-wired slice。
- Target flow：

```text
RefreshRequirementV1(dataset=tw.daily_ohlcv.official, trade_date, venue bounds)
  -> TW official descriptors
  -> TWSE/TPEx acquisition ports
  -> CanonicalBarObservation batch + RawFetchReceipt
  -> transaction-owned RawFetchResult + MarketDailyPrice persistence
  -> DailyPriceCandidateRepository reread
  -> ResolvedBarSeries / DatasetEvidence
  -> MarketDataResultV1 + stable daily projection
```

- Acceptance：
  - 使用實際official payload或已保存raw receipt，不能只用手寫成功dict。
  - TWSE與TPEx至少各有一個symbol/日期可完成fetch/fixture replay、canonical conversion、persist、DB reread、resolve、API projection。
  - `source_id`、`raw_result_id`、trade/event date、fetched_at、content hash、provider/source、selection reason可追溯。
  - 同一source/symbol/date重跑idempotent；partial/empty/malformed/duplicate不造成silent data loss。
  - Read path不觸發fetch；refresh path受target/date/venue/timeout/call budget限制。
  - Existing daily API outward shape以adapter相容；新增共同envelope先internal或versioned exposure。
- Validation：TWSE/TPEx parser fixtures、repository integration DB、duplicate/restart readback、rollback、API contract、bounded real-data smoke（需明確授權與可用網路）。
- Rollback：daily route可退回legacy reader；新寫入沿用相容schema，不刪資料。

### CP3 — Full-market EOD lifecycle becomes platform-owned

- Scope：將既有`market_dataset_coverage_checkpoint`、`tw.reconcile_full_market_eod`、scheduler startup catch-up與official bulk repair連到Dataset Registry runtime service。
- Acceptance：
  - Registry spec實際決定owner、expected date、eligible window、refresh operation、bounds、postcondition與stale rule。
  - Lifecycle先compute persisted coverage；healthy時provider calls = 0。
  - stale/partial/missing只由explicit reconcile/job執行TWSE/TPEx venue-bounded refresh。
  - Refresh後由repository重讀並重新compute checkpoint，不相信provider回傳的`success`字串。
  - current/partial/stale/missing partition等於universe count，unknown不轉0。
  - powered-off後startup catch-up可修復completed-session EOD；不宣稱可修復未保存的intraday/depth gap。
- Validation：registry-operation consistency、coverage partition、release window、scheduler/job retry/backoff、cache-only endpoint、postcondition與real-data coverage artifact。
- Rollback：停用新lifecycle dispatcher即可回既有reconcile operation；checkpoint/data保留。

### CP4 — Actual vertical slice 2: official index and breadth

- Scope：拆出TWSE/TPEx official index/breadth provider ports，共用Gateway、candidate persistence/result envelope；TW official-close與breadth semantics留在TW policy。
- Acceptance：
  - `indices.py`納入的completed-session路徑不再直接做cross-provider acquisition/fallback。
  - official index與breadth各有actual payload -> canonical -> persist/readback -> resolve -> stable API證據。
  - index、breadth、market session與instrument trading status不混用。
  - TWSE/TPEx universe、official/final/provisional、data date、coverage與limitations如實outward。
  - Provider outage/conflict只影響對應candidate/health，不讓consumer改選來源。
- Validation：official fixtures、DB/repository integration、expected-date/final-status、provider outage/conflict、dashboard/API data smoke。
- Rollback：per-capability route adapter退回legacy projection；candidate rows不破壞既有reader。
- Gate split：CP4 source/platform gate由official ports、canonical/storage/readback/Resolver、health與provider-neutral stable API構成。既有dashboard/summary compatibility projection的最終cutover屬CP7 consumer convergence；在切換前`E-06`維持`partial`，不得用CP4 source gate宣稱consumer convergence完成。

### CP5 — Actual vertical slice 3: public request-time quote/intraday, no KGI

- Scope：選一條目前可合法使用且不依賴KGI的public MIS/official request-time資料路徑，接入quote或intraday capability；bars、session volume、actual trade分開resolve與reconcile。
- Acceptance：
  - 至少一條request-time capability走Gateway production path，具actual event time、received/fetched time、session/freshness、provider health與resolved health。
  - `intraday.py`對納入能力不再持有NStock -> Yahoo -> MIS fallback chain。
  - 不把MIS volume/price偽裝成NStock/Yahoo bar；跨component組合保留lineage、time skew、unallocated volume與reason。
  - `prefer_live` bounded；`require_live`未達成truthful fail；lease/cancel cleanup可驗證（若該port需要lease）。
  - 非交易時段只驗證cache/completed semantics；需live語意的能力在對應market session另留acceptance artifact，但不使用既有M5/KGI作gate。
- Validation：recorded actual payload、session/freshness fixtures、timeout/error/stale/conflict、bounded API/data smoke；必要時安排新public-source session acceptance。
- Rollback：per-capability rollout mode退回legacy；不 broad-kill unknown runtime/lease。
- Gate split：recorded actual payload、isolated persistence/readback、provider-neutral API與legacy consumer source cutover構成CP5 source/platform gate；active-session public-source live acceptance留到CP8 runtime adoption window，未執行前不得宣稱live operational。

### CP6 — Provider onboarding seam and durable TW dataset convergence

- Scope：完成market-owned TW catalog/port registry與dataset-family application adapters；依風險納入chips、ETF、fundamentals/events、derivatives。
- Acceptance：
  - 新增一個非KGI provider capability的contract test只改catalog + adapter/port，不修改consumer/Gateway/Resolver。
  - 每個production dataset有typed payload、storage reference、expected-date/eligibility、refresh operation、bounds、postcondition與health projection。
  - 不可refresh的dataset如實`unavailable`/`not_repairable`；advertised => projection exists，refreshable => executable bounded operation。
  - Dataset-specific schema保留，不硬塞成generic quote/bar/blob。
- Validation：catalog planning、provider port contract、registry inventory/consistency、dataset family regression、source health/data smoke。

### CP7 — AI, API, MCP, Kuro and technical convergence

- Scope：AI query plan/TW contexts、stable APIs、MCP/Kuro projection、resolved OHLCV -> shared technical engine -> versioned series -> frontend render。
- Acceptance：
  - AI不再注入/call已納入平台的legacy provider-orchestrating services。
  - Public production request不接受provider/strict_provider控制acquisition；legacy fields只可diagnostic/deprecated/rejected。
  - HTTP/SSE/MCP `omi.decision.v4` parity不變，provider/freshness/limitations只來自backend resolved contract。
  - 正式EMA/RSI/MACD/KD等只有一個backend algorithm/basis/version truth；local presentation-only overlay明確標scope。
- Validation：decision v4 contract、capability inventory、transport parity、golden series cross-surface、frontend lint/typecheck/build與必要browser smoke。

### CP8 — Legacy removal and common-platform closure

- Scope：移除已遷移能力的service-local fallback、masquerading、provider controls、過期flags與compatibility debt；更新current architecture docs。
- Acceptance：
  - `AcceptanceMatrix.md`所有common-platform required rows為`passed`，無`blocked`。
  - 三條durable actual-data proofs與一條non-KGI request-time proof可從fresh test DB重現。
  - Production consumer不繞過Gateway/Resolver/Lifecycle；新增provider不改consumer。
  - Runtime selected PID/port、API/data/UI/MCP採用新path；rollback rehearsal完成。
  - KGI/M5仍可維持deferred，不影響`TW_DATA_CORE_COMMON_PLATFORM_OPERATIONAL`。
- Validation：safe backend/frontend/full profiles、migration upgrade/rollback（若有）、API/MCP inventory、runtime adoption、browser-visible workflow、restart durability、rollback rehearsal。

### Deferred follow-up — KGI onboarding and realtime M5

- CP8完成後另開獨立任務，將KGI quote/depth/realtime lease/account-separated health接到既有catalog/ports/Gateway。
- 該任務再執行Preopen/Opening/Regular/Closing/Post-close與M5 live acceptance。
- KGI adapter不得改動共同Core來容納provider-specific payload，也不得把Account health混入Quote health。

## Stop-and-fix rules

- 任一`cache_only`、GET或completed-session read產生provider IO、subscription或repair，立即停止。
- 任一adapter、router、AI、frontend開始決定cross-provider priority/fallback，立即停止。
- 任一provider field merge失去component lineage/coherence，立即停止。
- 任一unknown/missing/no-quote被轉成0/no-trade/suspended，立即停止。
- 任一persist成功但DB reread/postcondition未成立仍回success，立即停止。
- 任一duplicate rerun造成重複row、destructive replace或coverage錯算，立即停止。
- 任一lease timeout/cancel後仍可callback/reactivate，或可釋放其他owner資源，立即停止。
- 任一DB mutation缺少transaction owner、rollback或必要migration，立即停止。
- 任一outward compatibility drift無version/adapter/rollback，立即停止。
- 任一validation failure先修正；只有可證明與本CP無關的既有failure才可隔離紀錄。

## Decisions

- 2026-08-25：接受單一Market Data Platform方向；完整重架構採可回退的vertical-slice convergence，不採Big Bang。
- 2026-08-25：Data Core Integration Contract定義internal evidence acquisition/resolution contract；不建立public mega-endpoint。
- 2026-08-25：承接既有02A dark core，不重做第二套Control Plane/Resolver/Registry。
- 2026-08-25：計畫改為actual-data-first；第一條production slice是TWSE/TPEx official daily OHLCV，接著是EOD lifecycle與official index/breadth。
- 2026-08-25：既有realtime M5與KGI完全移出共同平台依賴鏈與done criteria；平台完成後再做KGI onboarding。
- 2026-08-25：正式資料分request-time evidence與durable dataset evidence兩族；共用lineage/health/lifecycle envelope，保留typed payload。
- 2026-08-25：現有`market_daily_price + raw_fetch_result + source_registry`先作daily candidate persistence seam；只有contract evidence證明不足才migration。
- 2026-08-25：正式technical P1是resolved input/projection/frontend authority convergence，不重做已有shared math primitives。
- 2026-08-25：official breadth只能由同一venue/date/raw receipt的official daily rows加上active registered universe導出；`missing`與`unknown`分開，receipt混用或partition不守恆時fail closed。
- 2026-08-25：legacy `market_index_daily_stat`缺少raw/source FK lineage，因此CP4採nullable additive migration；legacy rows保留但新platform reader在補齊lineage前拒絕把它們冒充可驗證official evidence。
- 2026-08-25：CP4 source/platform gate與CP7 consumer cutover分開記錄；新增provider-neutral index/breadth API可以先通過，既有dashboard仍須在CP7明確切到共同resolved projection後`E-06`才可passed。
- 2026-08-25：CP5選定TWSE MIS single-symbol public last-trade quote，不把snapshot製造成intraday bar；正式intraday trend只做common-platform cache-only quote projection，MIS legacy merge/fallback helper留到CP8刪除。
- 2026-08-25：TWSE MIS僅視為public best-effort、no-SLA來源；bounded個人研究可用不等於取得raw payload對外轉播授權。
- 2026-08-25：CP6以market-owned typed catalog + describe-only operation registry + cache-only storage/lineage health API收斂28個TW production dataset；登錄lineage gap不等於完成canonical migration，也不建立generic refresh-all endpoint。
- 2026-08-25：CP6 production evidence artifact保留取得當下的27-dataset point-in-time truth；CP7新增`tw.technical.daily`後不事後改寫artifact數字。
- 2026-08-25：`tw.technical.daily`由Resolver-selected official daily OHLCV即時計算並攜帶algorithm/version/parameter/component lineage，不建立第二份indicator value storage。
- 2026-08-25：Frontend在backend authority metadata與parameter contract吻合時採用backend technical series；legacy local math只作`presentation_only` compatibility，不能成為AI/MCP evidence。
- 2026-08-25：CP7 AI Taiwan quote context只讀Data Core projection；legacy `provider`/`strict_provider` input不再控制production acquisition。
- 2026-08-25：Index dashboard把current-session observation與latest-completed official index/breadth拆成獨立components；Data Core selected evidence優先，migration尚未adopt時保留明示`legacy_compatibility`的rollout fallback，CP8才移除。
- 2026-08-25：CP8移除completed dashboard rollout fallback；Data Core missing一律`data_core_missing` fail closed。Current-session index/MIS breadth是尚未onboard的獨立capability，不因completed source closure而誤刪或誤稱完成。
- 2026-08-25：台股OHLC GET即使收到legacy `ensure_history=true`也維持cache-only；只回ignored/not-attempted diagnostic，mutation必須走explicit bounded operation。
- 2026-08-25：Production rollback保留additive schema並回退application build；0067/0068 downgrade只作emergency compatibility proof，已有新canonical writes後不得把移除lineage columns當首選rollback。
- 2026-08-25：歷史Foundation/M5 checkpoint不重寫；共同平台以獨立successor extension checkpoint精確承接intentional source drift。US manifest只授權market-owned integration exact path。
- 2026-08-25：backend full suite已達2280 tests、正常teardown約310秒；safe-validation仍bounded，但預設timeout由300秒提高至420秒，避免測試全綠後被wrapper誤標timeout。
