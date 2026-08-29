# 美股 Backend Shared Core 收斂計畫

## 執行狀態

- Current status：`M9_3A_HISTORY_COVERAGE_ACCEPTED`
- 2026-08-29 已取得 M0–M8 Source implementation 授權。
- 正式migration/runtime已採用M9.0 rollout revision與unknown identity 404 hardening；M9.0 Runtime gate已accepted。使用者已授權precommit source closeout、正式OMI restart、三檔bounded provider I/O／production DB writes、後續bounded priority／full-market、MCP reload與publication；仍必須按milestone gate執行，US full-market scheduler在其正式milestone前保持paused。
- Milestone狀態只使用：`pending_approval`、`pending`、`in_progress`、`source_passed`、`blocked`、`runtime_pending`、`live_pending`、`product_pending`、`accepted`。

## 執行原則

1. 先固定 current source、owner、contract、debt 與 failing fixtures，再修改。
2. 只做 additive Shared Core extension；不建立 US-only resolver、freshness、registry、dispatcher 或 rollout framework。
3. 每一 milestone 保持最小、可回退 diff；不得同時大改 acquisition、storage、consumer 與 frontend。
4. 每個修復先有 negative/failing test，完成後才轉綠；無法建立可驗證 fixture 時先停下釐清。
5. `off -> shadow -> compare -> canary -> on` 逐capability推進；Source、Runtime、Live、Product gate分開。
6. Runtime、provider、migration、DB、scheduler、commit、push與release權限不由Source實作授權推定。

## Target ownership map

| Responsibility | Canonical owner to extend | Forbidden owner |
| --- | --- | --- |
| US instrument identity | US market-owned typed identity port | company/SEC existence、Frontend symbol heuristic |
| Expected completed session/release | US expected-state/calendar port | Shared Core direct US calendar import、AI local date |
| Provider capability declaration | US `ProviderCapabilityDescriptorV2` registration | consumer/provider query parameter |
| Acquisition planning | Shared provider catalog/control plane | US adapter/service private fallback |
| Provider I/O | US acquisition port/adapters | Gateway DB owner、router、AI、consumer |
| Canonical observation | Shared typed contracts + US conversion | raw provider payload in consumer |
| Raw receipt/canonical persistence | US repository/transaction owner | adapter commit、query helper commit、Shared Core ORM |
| Candidate read | US cache-only repository | service refresh、provider selection |
| Final selection/fallback | Shared Resolver | acquisition port、service、valuation、technical |
| Dataset/freshness quality | Shared quality using US expected-state input | five-day heuristic、payload existence |
| Stable outward projection | US market projection + `omi.decision.v4` | Frontend/MCP recomputation |
| Priority/full-market lifecycle | Shared lifecycle contract + US operation binding | duplicate scheduler/provider path |
| Rollout/rollback | Shared per-capability registry | unrelated global flag、data deletion |

## Issue traceability

| ID | Current issue | Required disposition | Primary milestone |
| --- | --- | --- | --- |
| P1-01 | Manifest remains G0 / production disabled | Keep fail closed until Shared contract gate passes | M1 |
| P1-02 | Refresh requirement lacks reason/coverage/cursor | Add provider-neutral typed semantics and tests | M1 |
| P1-03 | Dataset lifecycle has names/bounds but no executable dispatcher/result | Add executable binding and postcondition evaluator | M1 |
| P1-04 | Bar series can mix declared provider/source lineage | Add fail-closed coherence validation | M1 |
| P1-05 | Plan summary diagram places Gateway after acquisition/persistence | Enforce actual Gateway-first orchestration | M4 |
| P1-06 | Existing US descriptors use legacy V1 vocabulary | Replace new binding with V2 descriptors; quarantine compatibility | M2 |
| P1-07 | `USDailyPrice` lacks complete canonical lineage | Mandatory receipt relation/sidecar/migration decision | M3 |
| P1-08 | Legacy service owns fallback and daily commit | Move to Shared plan + US transaction owner | M2/M3 |
| P1-09 | `^SOX` identity can depend on `USStockMaster.exchange` | Add market-owned index identity path | M4/M5 |
| P1-10 | Index volume null cannot distinguish missing/not applicable | Add applicability-aware quality/projection | M4/M5 |
| P1-11 | GET exposes acquisition/provider controls | Remove/deprecate controls and prove zero side effect | M4/M7 |
| P1-12 | AI uses five-day stale and payload-exists=current | Project canonical expected/latest/quality facts | M7 |
| P1-13 | Previous close can query alternate raw references | Use resolved daily exact expected date only | M7 |
| P1-14 | Financial valuation prefers Yahoo raw row | Use resolved daily close | M7 |
| P1-15 | Priority audit has no repair; EOD has shared reverse dependency/transaction debt | Bind same platform and remove exact debt | M6 |

### Precommit v4 issue traceability

| ID | Verified gap | Required disposition | Primary milestone |
| --- | --- | --- | --- |
| PC-01 | Technical payload `status=missing`仍可被generic quality提升為`available/ready` | 建立provider-neutral payload semantic-quality reader與negative matrix | M9.0.5 |
| PC-02 | Daily missing payload的upstream `refresh_recommended=true`可被generic builder清成false | 分離recommendation、allowed、requested與possible | M9.0.5 |
| PC-03 | Public diagnostics repair仍經legacy `repair_us_ohlc_history()`／`refresh_us_daily_prices()` | 改由canonical dataset operation／Platform refresh單一owner執行 | M9.0.5 |
| PC-04 | `candidate_store.py` production caller為0，但tests仍維持第二repository contract | 遷移tests後移除或quarantine，並加caller/import negative guard | M9.0.5 |
| PC-05 | Chart仍重算freshness、current與refresh recommendation | 分離request-specific coverage與canonical dataset truth | M9.0.5 |
| PC-06 | REST／decision v4／MCP／Frontend尚未完整保留`selected_event_at`等Daily truth | 補stable projection與consumer parity | M9.0.5／M9.3 |
| PC-07 | AAPL／TSM／`^SOX` canonical lineage均為0 | 逐檔bounded live seed與mandatory reread | M9.1 |
| PC-08 | Source closeout與live seed後仍需正式runtime adoption證據 | 正式launcher restart與cache-only readback | M9.0.6／M9.2 |
| PC-09 | Mixed worktree尚未形成可驗證的exact staged dependency closure | isolated staged-tree acceptance | M9.4 |
| PC-10 | Current branch ahead 6，publication target／upstream／version尚未證明 | target proof後才commit／push／release | M9.5 |

## Milestones

### M0 — Approval、baseline與scope freeze

- 狀態：`source_passed`
- Scope：
  - 取得使用者明確Source實作授權。
  - 重取branch、HEAD、dirty files、relevant file hashes、contract versions、registry/debt inventory。
  - 建立只讀owner/caller/transaction/side-effect map與consumer inventory。
  - 建立P1-01～P1-15 failing fixtures或精確source assertions。
- Acceptance：
  - Baseline artifact能重現所有current gaps，並列出哪些檔案已有使用者變更。
  - 沒有provider I/O、DB mutation、runtime restart或source修改混入baseline。
  - 後續milestone的exact touched paths與non-overlap strategy已確認。
- Validation：
  - `git status --short --branch`
  - `git rev-parse HEAD`
  - `..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` 執行fixture-only targeted collection（從`backend`）。
  - `.\.venv\Scripts\python.exe scripts\check-architecture.py`
- Stop：若current dirty diff已在修改同一核心contract但owner/intent無法判定，停下請使用者確認，不覆寫。

### M1 — Shared Contract Gate（US-B0.5）

- 狀態：`source_passed`
- Scope：
  - Additive擴充`RefreshRequirementV1`或下一相容版本，表達reason、coverage/cursor/checkpoint與postcondition。
  - 對`PersistedBarSeries`、`BarSeriesCandidate`與candidate read加入provider/source coherence negative validation。
  - 建立registry operation binding、typed execution result、cursor/checkpoint與postcondition evaluator。
  - 建立或收斂per-capability rollout/rollback registry。
  - 釐清synchronous daily HTTP acquisition與既有timeout/cancel/cleanup lifecycle的正式接點。
- Acceptance：
  - Mixed Yahoo/Alpha Vantage bars不能進同一provider-coherent series。
  - Registry宣稱refreshable時，operation一定可call、bounded、有typed result；不存在只寫字串但不能執行的truth。
  - `cache_only`／`completed_session` requirement無法攜帶external-call budget。
  - Contract serialization與compatibility seam有測試；TW相關caller回歸通過。
  - 不新增market-specific import到`app.market_data`。
- Validation：
  - `test_market_data_integration_contracts.py`
  - `test_market_data_provider_catalog_v2.py`
  - `test_market_data_gateway.py`
  - `test_market_data_resolution.py`
  - `test_market_data_registry.py`
  - `test_dataset_lifecycle.py`
  - `test_market_data_v2_dark_boundary.py`
  - architecture checker/tests與相關TW Shared Core regressions。
- Stop：若需要breaking contract或現有TW production caller無法additive相容，先提出version/migration window，不在本milestone硬切。

### M2 — US V2 Descriptors與Canonical Acquisition

- 狀態：`source_passed`
- Scope：
  - 盤點現有`app.us_market.market_data`草稿，逐檔標記keep/evolve/retire。
  - US descriptors對齊`ProviderCapabilityDescriptorV2`、Data/Refresh requirement與Shared acquisition plan。
  - 正式化Yahoo Chart與Alpha Vantage daily acquisition port；沿用pure canonical adapters。
  - Acquisition只執行plan routes，保留raw receipt、provider health與canonical observations。
  - `legacy_compat.py`維持單向quarantine；新production code不得import。
- Acceptance：
  - Yahoo stock/index daily、Alpha Vantage daily canonical fixtures通過。
  - Provider empty、malformed OHLC、rate limit、API error、future/current-session partial與adjusted/raw語意fail-visible。
  - Adapter/acquisition無DB transaction、無final selection、無private fallback。
  - Acquisition attempted resources是Shared plan routes的子集合，budget超限fail closed。
- Validation：
  - 新增`test_us_daily_ohlcv_acquisition.py`。
  - 既有`test_us_market_data_foundation_seam.py`、provider canonical/policy tests。
  - Gateway acquisition budget與architecture boundary tests。
- Stop：若provider payload無法證明finalization或price basis，保留unknown/partial並阻擋production，不自行推定。

### M3 — US Repository、Raw Receipt與Transaction Ownership

- 狀態：`source_passed`
- Scope：
  - 唯讀schema/receipt relation spike，選定reuse、sidecar或additive migration。
  - 實作bounded all-provider candidate repository與provider-coherent canonical series。
  - 將`price_store.py`拆成zero-commit primitives與明確transaction owner。
  - Atomic persist raw receipts + canonical observations，commit failure rollback/rethrow。
  - Legacy upsert wrapper只能委派新transaction owner並有removal gate。
- Acceptance：
  - Fetch failure時DB不變；provider I/O不發生於transaction持有期間。
  - Commit failure rollback且不吞原始錯誤。
  - Retry idempotent；Yahoo/Alpha Vantage同symbol/date可各自保存candidate。
  - Storage alias不造成重複canonical symbol；每一接受/拒絕row守恆。
  - Persisted reread可完整重建lineage、finalization、price basis與raw receipt identity。
- Validation：
  - 新增`test_us_daily_candidate_repository.py`、`test_us_daily_transaction.py`。
  - Migration upgrade/compatibility/downgrade或sidecar integrity tests。
  - `test_database_contention_boundaries.py`、transaction failure regressions。
- Stop：若需migration，先完成isolated copy upgrade與rollback/compatibility證據；未另行授權不得套production DB。

### M4 — US Daily Platform、Expected State與GET Purity

- 狀態：`source_passed`
- Scope：
  - 建立`USDailyOhlcvPlatform` stable interface。
  - 建立US instrument identity、expected completed session/release/eligibility/applicability typed ports。
  - Read流程固定cache-only；refresh流程固定read -> resolve -> plan -> acquire -> persist -> reread -> resolve -> postcondition。
  - Stable projection輸出selected lineage、health、limitations、price basis、volume applicability與continuity。
  - GET移除/封閉acquisition controls，explicit POST/job承接bounded repair intent。
- Acceptance：
  - Read requirement為零external calls/subscriptions/write/queue。
  - Pre-resolution satisfied時acquisition不執行。
  - Fetch有資料但persist/reread/postcondition失敗時refresh不成功。
  - Historical/future date在US platform boundary clamp或fail-visible，consumer不自行重算。
  - Index不需company/SEC即可建立canonical target；volume not-applicable不被quality判missing。
- Validation：
  - 新增`test_us_daily_ohlcv_platform.py`、`test_us_daily_expected_state.py`、`test_us_daily_instrument_identity.py`。
  - `test_us_market_data_outward_contract.py`、`test_us_ohlc_contract.py`、GET zero-side-effect tests。
- Stop：若Shared quality無法表示applicability而需要additive contract，先回M1補contract，不在projection用字串硬補成第二truth。

### M5 — TSM + `^SOX` Source Vertical Slice

- 狀態：`source_passed`
- Scope：
  - 以fixtures/in-memory or isolated DB先完成TSM stock與`^SOX` index end-to-end source slice。
  - 驗證Yahoo fresh/AV stale、Yahoo stale/AV fresh、both fresh conflict、both stale/missing、partial/future candidate。
  - 接入previous close、technical與valuation的shadow/compare讀取，不先production on。
- Acceptance：
  - TSM latest等於expected completed session；volume shares；previous close exact expected date。
  - `^SOX` latest等於expected；index identity正確；volume null + not_applicable；沒有profile/SEC false blocker。
  - Technical/valuation shadow evidence與resolved daily選擇一致。
  - Selected provider、selection reason、fallback、expected/latest、lineage與quality可解釋。
  - Gate artifact標記`US_DAILY_SHARED_CORE_VERTICAL_SLICE_SOURCE_ACCEPTED`，Runtime/Live/Product仍pending。
- Validation：
  - 新增vertical-slice integration tests與TSM/`^SOX` fixtures。
  - `test_us_ohlc_continuity.py`、technical/valuation consumer shadow tests。
  - architecture checker與targeted safe backend validation。
- Stop：不得使用production provider call或DB來替代fixture source acceptance；需要live evidence時停在Live pending。

### M6 — Priority與Full-market Lifecycle收斂

- 狀態：`source_passed`
- Scope：
  - `us.daily.ohlcv.priority_research`由cache-only audit接到同一platform的explicit bounded repair operation。
  - `us.daily.ohlcv.full_market`使用同一US acquisition/persistence/expected-state owner。
  - Full-market保存universe hash、expected date、cursor/checkpoint、current/partial/stale/missing、budget與retry boundary。
  - 移除Shared EOD對US service/calendar/rollback的reverse dependency與transaction debt。
  - 明確區分priority quick reconcile與full-market resumable background reconcile，防止重複scheduler競跑。
- Acceptance：
  - Registry只有在operation真的可執行後才宣稱refreshable/repairable。
  - Priority job bounded、deduplicated、checkpoint可續跑；full-market不宣稱單次完成。
  - Shared lifecycle透過typed US port工作，不importUS implementation/ORM。
  - Scheduler restart從durable checkpoint續跑；provider error backoff且不無界retry。
- Validation：
  - 更新`test_us_ohlc_priority.py`、`test_eod_coverage_scheduler.py`、`test_job_retry.py`。
  - 新增operation dispatcher/checkpoint/concurrency tests。
  - architecture debt removal checks。
- Stop：full-market external calls、scheduler enable或production checkpoint mutation需另行授權；Source只使用fixtures/in-memory/isolated storage。

### M7 — Consumer、API與Quality收斂

- 狀態：`source_passed`
- Scope：
  - 建立production consumer inventory，依序切換OHLC、previous close、technical、Radar、valuation、AI compact context、source health、data freshness、capability projection與MCP outward。
  - 移除五日stale canonical authority與payload-exists=current。
  - 移除valuation/provider preference與consumer raw `USDailyPrice` selection。
  - Legacy compatibility有owner、sunset、negative test與removal gate。
- Acceptance：
  - 同一target/date的expected/latest/selected provider/lineage/freshness reason一致。
  - 不把不同health axes壓成一個status；矛盾時fail-visible。
  - Previous close缺exact expected date時為missing，不退回更舊日期冒充。
  - Stale technical可保留historical facts但decision usability降級。
  - `omi.decision.v4`、API、MCP與Frontend不自行選provider、重算freshness或推volume applicability。
- Validation：
  - US market context、agentic freshness、financials、technical/Radar、decision envelope、capability、MCP schema與Frontend authority contract tests。
  - GET/API schema compatibility與negative tests。
- Stop：若consumer仍依賴provider-specific欄位且無版本/migration window，不用silent breaking change；先列compatibility seam。

### M8 — Source Closeout與Architecture Freeze

- 狀態：`source_passed`
- Scope：
  - 清除已取代的legacy daily selection/write/read paths與exact debt entries。
  - 更新current architecture truth、constraints/debt、consumer maps與source acceptance artifact。
  - 跑targeted matrix、backend safe validation與必要完整regression。
- Acceptance：
  - `production_binding_available`只在contract、caller、rollback與source gates齊備後改為true；effective mode仍可維持off。
  - Architecture checker無undeclared/stale debt。
  - US daily單一production owner，無永久雙寫／雙讀／雙freshness truth。
  - Source gate標`US_DAILY_BACKEND_V1_SOURCE_ACCEPTED`；Runtime/Live/Product未做時保持pending。
- Validation：
  - `.\scripts\run-safe-validation.ps1 -Profile backend`
  - `.\.venv\Scripts\python.exe scripts\check-architecture.py`
  - architecture tests、US/Shared/TW affected regression matrix、`git diff --check`。
- Stop：全套baseline中的無關失敗要精確隔離與記錄；與本任務相關失敗不得留到runtime階段。

### M9.0 — Rollout Stabilization與Live前契約補洞

- 狀態：`accepted`
- Scope：只做Source contract與local deterministic validation，不執行restart、provider I/O或production DB寫入。
  - 將名義canary與實際outward selection對齊：per-capability rollout必須真正約束Daily outward selection／acquisition，或明確將現況標為global canonical read而非canary。
  - REST chart/outward schema補齊selected provider/source、fallback、selection reason、limitations與usability欄位；統一expected/latest trade-date mapping。
  - Public refresh的provider參數標為deprecated並對非`auto` fail closed，或提供明確compatibility window；不得接受後靜默忽略。
  - 將US full-market scheduler隔離納入executable test與runtime checklist；本機目前維持`SCHEDULER_EOD_COVERAGE_MARKETS=TW`。
  - 更新`CurrentImplementationState.md`、Prompt／Progress與architecture constraints，使runtime、migration與scheduler狀態一致。
- Acceptance：
  - AAPL allowlist真的限制bounded cutover，TSM／`^SOX`在Stage 1不會被錯誤宣稱已canary accepted。
  - REST response model不再丟棄canonical selection／limitation facts。
  - Non-auto provider request不可誤導operator。
  - Restart後沒有新的US full-market job；TW scheduler不受影響。
  - Architecture guard無新增debt，targeted contract tests通過。
- Validation：architecture guard、US rollout/API contract/scheduler targeted tests、OpenAPI schema probe、read-only DB job inventory。
- Stop：若真正canary需要永久雙讀、consumer-owned fallback或public breaking change但沒有version window，先停下修正contract。

### M9.0.5 — Pre-live Semantic與Owner Closeout

- 狀態：`source_passed`
- Scope：先完成deterministic Source closeout；本milestone不做provider I/O、production DB write或restart。
  1. Generic typed payload quality reader統一解讀`payload.status`、`payload.quality.status`、`facts_usable`、`decision_usable`、`reason_codes`與`limitations`；technical不建立第二套truth engine。
  2. 將refresh的recommendation、allowed、requested與possible分離；cache-only只能限制動作，不能清除missing／stale的recommendation。
  3. Diagnostics／quality／history repair統一委派canonical dataset operation／`USDailyOhlcvPlatform.refresh()`；deprecated provider seam只能fail closed或單向相容，不再執行legacy private fallback。
  4. 將`candidate_store.py`的tests／exports遷移至`USDailyBarRepository`後移除或quarantine；production與test caller inventory都有negative guard。
  5. Chart只擁有request-specific timeframe／bar coverage與shape mapping；canonical freshness、usability、current、previous close與refresh recommendation由Platform projection擁有。
  6. Stable projection／REST schema／consumer map補齊`selected_event_at`及已存在但未完整保留的Daily truth fields。
- Acceptance：
  - Technical missing／stale／current與Daily missing／stale／current negative matrix全部truthful；Unknown不變0。
  - `refresh_recommended=true`不因`cache_only`變false；但`refresh_allowed/requested/possible`仍可各自為false。
  - Daily repair只有一個production transaction/fallback owner；legacy refresh/upsert production caller歸零。
  - Chart不覆寫canonical dataset truth；request-specific coverage明確以不同欄位表達。
  - Architecture guard維持exact debt，沒有broad allowlist。
- Validation：AI quality、US Daily contract/platform/architecture、repair/caller negative tests、compileall與architecture checker。
- Stop：若修正需要public breaking change、第二個quality engine或無法證明repair transaction owner唯一，先停下補compatibility plan。

### M9.0.6 — Source Closeout Runtime Adoption

- 狀態：`accepted`
- Scope：以已授權的正式OMI launcher lifecycle重啟，只採用M9.0.5 source；不做provider refresh或production DB mutation。
- Acceptance：project root、`.venv` interpreter、selected ports、migration、OpenAPI與loaded behavior一致；direct／proxy ready；US full-market仍paused。
- Validation：launcher identity、direct/proxy health與readyz、OpenAPI、negative quality/read purity smoke、read-only DB／scheduler inventory。
- Stop：任何runtime identity mismatch、read path side effect或US full-market job重新啟動時，不進live seed。

### M9.1 — AAPL／TSM／`^SOX` Bounded Canonical Live Seed

- 狀態：`blocked_at_aapl`
- Scope：使用者已授權bounded provider I/O與三檔production DB write；依AAPL -> TSM -> `^SOX`逐檔explicit refresh，每次只允許一個target，禁止priority/full-market並行。AAPL先沿用現有canary；成功後才將allowlist明確擴為三檔並正式restart驗證。
- Budget：每檔最多2次provider attempt/call，三檔合計最多6次；不以retry繞過quota或entitlement failure。
- Acceptance：
  - 每檔都有provider attempt、RawFetchReceipt、SourceRegistry lineage、canonical rows、atomic commit、mandatory reread、Resolver selection與postcondition證據。
  - `latest_trade_date == expected_trade_date`，無future/unreleased bar。
  - AAPL／TSM為stock shares；`^SOX`為index、volume null／not_applicable，不用fake zero，也不依賴company／SEC facts。
  - 每檔refresh後做read-only DB probe，三檔以外無本次operation造成的非預期寫入。
- Validation：explicit POST／Dataset Operation result、receipt/lineage DB query、cache-only reread、resolved projection與consumer targeted smoke。
- Stop：provider payload drift、quota／entitlement不明、persist/reread不一致、identity錯誤、fallback不可解釋或postcondition失敗時立即停止後續symbols。

### M9.1A — Free Provider Contract與Inventory收斂

- 狀態：`source_passed`
- Scope：以V2 descriptors／Shared Provider Catalog為唯一Daily provider inventory；對`ProviderResourceHealth`做additive `resource_id`擴充；補provider-specific auth／entitlement／rate-limit／eligibility taxonomy與安全source metadata。Legacy policy只保留相容投影，不再手動維護第二份Daily priority。
- Acceptance：Yahoo／Alpaca Daily priority只由一份executable descriptor truth產生；SIP／IEX或quote／intraday resource health不互相覆蓋；舊health producer保持相容；receipt／log／exception不含credential。
- Validation：Shared contract/catalog/Gateway、US policy/source health/canary、architecture negative tests與TW affected regression。
- Stop：需要breaking outward contract、第二份provider inventory、broad debt allowlist或secret可進receipt/log時先修正，不進M9.1B。

### M9.1B — Alpaca SIP Daily P2 Source與Deterministic Fallback

- 狀態：`source_passed`
- Scope：新增bounded Alpaca historical bars client、pure canonical adapter、STOCK／ETF descriptor、Daily acquisition integration與transaction metadata；Yahoo仍P1，Twelve不加入Daily。
- Acquisition semantics：依Shared plan順序執行；Yahoo已提供`expected_trade_date`完整final raw OHLCV時停止，否則才呼叫Alpaca。Executor只判需求是否已滿足，不選winner；persist後mandatory reread與Shared Resolver仍是唯一selection owner。
- Acceptance：AAPL fixture重現Yahoo 2026-08-28 `close=null`並由Alpaca final bar補足；`selected_provider=alpaca`、`fallback_used=true`、latest=expected；Yahoo成功時Alpaca零call；TSM同語意；`^SOX`永不規劃或呼叫Alpaca stock endpoint。
- Validation：provider/client、canonical、eligibility、acquisition、transaction、repository、Platform vertical slice、secret redaction與architecture tests。
- Stop：最近15分鐘SIP、pagination超界、index誤送、provider timestamp誤當session close、缺volume被補0、或Yahoo成功仍消耗P2 quota時先修正。

### M9.1C — Alpaca Bounded Live AAPL修復

- 狀態：`accepted`
- Scope：只在credential存在且entitlement probe合法時，透過正式canonical explicit refresh對AAPL執行最多2次external calls（Yahoo P1、必要時Alpaca P2）及既有production transaction；不啟用US full-market scheduler。
- Acceptance：Alpaca 2026-08-28完整final raw bar產生redacted receipt、canonical row、atomic persist、mandatory reread、Shared Resolver fallback與postcondition；若credential／entitlement／provider evidence不成立，truthfully blocked而不移除Alpha Daily。
- Validation：exact call budget、receipt/lineage read-only DB probe、direct/proxy cache-only reread、before/after side-effect inventory。
- Stop：credential缺失、401／403、429、T-15 eligibility、schema drift、persist/reread不一致或postcondition failure時停止；不以重試storm或其他symbol繞過AAPL gate。

### M9.1D — Twelve Data Quote／Intraday Source-ready

- 狀態：`source_ready_live_quote_accepted`
- Scope：新增REST client、auth redaction、typed errors、quote/time_series pure canonical adapters與fixtures；保留`PARTIAL_US_MARKET_VOLUME`與personal/internal usage limitation。本階段不加入Daily、不advertise production、不啟動polling／WebSocket。
- Acceptance：source parser、timezone、duplicate/out-of-order、null、rate-limit、invalid symbol與secret tests通過；沒有Frontend／MCP provider selection或production binding。
- Validation：pure provider/canonical/architecture tests；無live call與DB write。

### M9.1E — Alpha Daily Cutover Gate

- 狀態：`accepted_for_stock_etf`
- Scope：只有M9.1B／M9.1C與後續M9.2／M9.3通過後，才從Daily descriptors、manifest、legacy projected priority與production repair seams移除Alpha Daily；Fundamentals／Corporate Actions保留。
- Acceptance：Alpha Daily production caller為0且negative guard防止重返；既有非Daily Alpha tests無regression；fallback rollback evidence仍可追溯。
- Stop：Alpaca只達Source或Live blocked時不得執行本milestone。
- Limitation：Alpaca Daily只宣告STOCK／ETF；`^SOX`仍是Yahoo-only。Twelve Data `^SOX` 1day live probe為HTTP 404，不能當index fallback或把三檔gate標成完整通過。

### M9.2 — Restart Cache-only Readback與Canary Gate

- 狀態：`partial_index_fallback_missing`
- Scope：正式launcher restart後，不執行provider refresh，以cache-only讀回AAPL、TSM與`^SOX`。
- Acceptance：rows／receipts／lineage survive restart；Resolver重建相同selection；zero provider call／repair／enqueue／write；direct/proxy一致。
- Gate：`US_DAILY_CANARY_RUNTIME_LIVE_ACCEPTED`。
- Validation：launcher root/interpreter/port/migration/source identity、direct/proxy readiness、read-only DB before/after diff與三檔canonical readback。
- Stop：restart後需要再次fetch才能讀回、runtime source/config不一致或任何read path寫入時不建立gate。

### M9.3 — Daily Product Parity

- 狀態：`accepted_for_aapl_tsm_partial_for_sox`
- Scope：Backend REST、`omi.decision.v4`、MCP與Frontend；不做UI redesign。已授權正式MCP lifecycle，但必須證明實際host載入本repo contract。
- Acceptance：同一symbol的expected/latest/selected event date、selected provider/source、fallback、selection reason、freshness、coverage、usability、facts/decision usable、volume與previous close truth一致；presentation可不同，market truth不可分叉。
- Gate：`US_DAILY_CANARY_RUNTIME_LIVE_PRODUCT_ACCEPTED`。
- Validation：direct REST、frontend proxy、MCP initialize/tools/list/tools/call、實際MCP host identity、可見Frontend DOM／screenshot與contract inventory。
- Stop：任何consumer自行補provider、freshness、previous close、volume語意，或只驗repo offline schema未驗running MCP host時，不建立Product gate。

### M9.3A — Multi-provider Candidate History Coverage Convergence

- 狀態：`in_progress`
- Scope：在既有Shared Gateway／Resolver／US Daily Platform上新增provider-neutral bar coverage intent、temporal／coverage雙postcondition與explicit `us.ensure_daily_history_coverage` operation；修正Index completed-session volume applicability，封住legacy compatibility synthetic lineage，並只對AAPL／TSM執行bounded 260-bar provider-coherent history repair。
- Non-goals：不採用`COMPOSE_BY_TIMESTAMP`、不拼接Yahoo／Alpaca timestamp、不啟動priority或full-market history backfill、不由GET／AI／Frontend隱性fetch、不把Technical readiness壓回Daily freshness。
- Acceptance：
  - `BarCapabilityRequest.max_bars`維持輸出bound；coverage使用獨立typed minimum-bar intent。
  - Shared Gateway在temporal current但coverage不足時，只對explicit acquisition policy繼續plan；普通read／latest refresh語意不變。
  - Platform同時回報`temporal_postcondition_satisfied`與`coverage_postcondition_satisfied`；Daily `decision_usable`仍由temporal evidence決定，Technical使用自己的history／corporate-action／benchmark gate。
  - AAPL／TSM 以Alpaca-first history planning各取得至少260根單一provider canonical bars；persist、mandatory reread、Resolver與restart cache-only readback通過。
  - Alpaca若回pagination token，在本輪兩-call budget內fail closed／fallback，不宣稱coverage complete或provider-confirmed best available。
  - INDEX完整OHLC且`volume_status=not_applicable`可滿足expected session；STOCK／ETF仍要求observed shares。
  - `SourceRegistry.source_type=compatibility_adapter`或legacy compat marker永遠被canonical repository拒絕，既有DB rows不刪除、不偽造lineage。
  - `^SOX`保持Yahoo-only truthful stale／missing；不得送Alpaca stock endpoint。
- Validation：Shared contract／Gateway、US repository／acquisition／transaction／Platform／dataset operation／repair、continuity、research/AI、TW affected regression、architecture checker、runtime direct/proxy與read-only DB evidence。
- Stop：任何跨provider composition、legacy row被Resolver採用、coverage intent影響普通GET purity、pagination無界、DB transaction持有provider I/O、AAPL失敗仍進TSM、或三檔以外寫入時立即停止。

### M9.4 — Precommit Staged-tree Acceptance

- 狀態：`pending`
- Scope：在高度混合的worktree只stage本任務exact files／hunks及其dependency closure；建立isolated staged tree驗證，不納入local DB、`.env`、logs、cache、runtime artifacts、TW無關變更或私人資料。
- Acceptance：staged diff沒有secrets／generated junk／unrelated hunks；migration、contracts、constraints/debt、docs與tests同步；Source／Runtime／Live／Product evidence可追溯。
- Gate：`US_DAILY_PRECOMMIT_CLEAN`。
- Validation：staged file/hunk inventory、secret/sensitive-path scan、isolated staged-tree backend targeted matrix、必要Frontend／MCP contract checks、architecture checker、compileall與`git diff --cached --check`。
- Stop：dependency closure不明、staged tree不能獨立驗證、混入其他market hunk或任何required test failure時不得commit。

### M9.5 — Commit／Push／Release Checkpoint

- 狀態：`pending`
- Scope：使用者已授權commit、push與release，但仍需先證明exact target branch/upstream、remote ancestry、version/tag機制與release scope。Current branch ahead 6，禁止把既有未審計commits隱性帶入。
- Acceptance：只commit已驗收的exact staged tree；push target與remote SHA明確；若repo沒有本次適用的versioned release機制，只做commit/push並將release標為not_applicable，不自行創tag或發版。
- Validation：`git status --short --branch`、staged diff、sensitive scan、`git log`／upstream ancestry、targeted validation、commit SHA、push後remote SHA。
- Stop：target branch／upstream不明、remote ancestry不安全、ahead 6內容未審計或release contract不明時停在`US_DAILY_PRECOMMIT_CLEAN`，不推定授權等於目標已確定。

### M9.6 — Closeout與下一條主線交接

- 狀態：`pending`
- Scope：更新current architecture、constraints/debt、acceptance evidence與Progress；完成後將整個task folder移到`docs/exec-plans/completed/`。
- Acceptance：Source／Runtime／Live／Product truth一致；未驗證區域明示；下一份工程只建立`US_INTRADAY_QUOTE_SHARED_CORE_CONVERGENCE`前置條件，不在本任務偷跑實作。
- Validation：UTF-8/link/structure、final acceptance matrix、remote/source identity與working-tree scope audit。

### Deferred follow-up — Priority／Full-market與Daily rollback seam retirement

- 使用者已授權後續bounded priority/full-market rollout，但它們不是`US_DAILY_PRECOMMIT_CLEAN`的必要條件，必須另立bounded rollout milestone執行。
- Priority先使用明確symbol inventory、quota/runtime budget、cursor/checkpoint、dedupe/retry/backoff與failure isolation；US full-market scheduler在此之前維持paused。
- Full-market從小shard開始，驗證coverage、lineage、resume、rate-limit與rollback後才逐步放大；不直接canary -> 250/full market。
- Daily canary/shadow與compatibility-only `resolved_reads.py`待priority/full-market rollback evidence完成後再退役；Intraday compare不在本任務範圍。

## Stop-and-fix rules

- 新增Shared Core對US implementation/ORM reverse dependency時立即停止，不以debt allowlist吸收。
- 新production code import `legacy_compat.py`、自行選provider或private fallback時立即停止。
- Candidate series出現mixed provider/source lineage但未fail closed時不得進M2之後。
- Provider I/O發生於DB transaction持有期間時先修正，不進下一milestone。
- Fetch成功但persist/reread/postcondition未滿足時不得回報refresh success。
- Missing、unknown、not_applicable、stale、partial或provider failure被轉成0/current/ready時立即停止。
- GET觸發fetch、repair、enqueue、write或provider selection時不得進consumer cutover。
- Registry宣稱refreshable/repairable但operation不可執行時立即回退宣告。
- Schema/migration需要production DB或existing-row backfill semantics未定時，停下要求授權與決策。
- Architecture checker新增undeclared violation、stale debt或broad allowlist時先修正。
- External refresh、production DB write、正式OMI／MCP lifecycle與publication雖已取得原則授權，仍只能依M9.0.6～M9.5的target、budget、順序與stop condition執行；授權不取代gate evidence。
- US full-market scheduler在本task closeout前若重新出現queued/running job，先停止live acceptance；不得把移動中的DB baseline拿來驗三檔gate。
- 三檔vertical slice不得直接觸發Daily canary/shadow removal；priority/full-market的deferred rollout evidence未完成時必須保留rollback seam。
- Public response model丟棄canonical selection／limitation欄位時不得宣稱REST／MCP／Frontend parity。
- Current branch ahead 6；未證明target/upstream/ancestry與exact staged dependency closure時，不得把commit/push授權解讀為可以直接發布整個worktree。

## Validation matrix

| Surface | Minimum proof |
| --- | --- |
| Shared contracts | serialization、invalid reason/coverage/cursor、bounds、compatibility |
| Candidate coherence | same provider/source、mixed provider/source fail closed、row rejection守恆 |
| Acquisition | plan-only routes、budget、timeout、empty/error/rate limit、no transaction |
| Persistence | receipt+bar atomicity、idempotent retry、commit rollback、post-write reread |
| Expected state | weekend、holiday、early close、pre-release、post-release、future date |
| Instrument identity | stock/index/ETF、unknown symbol、venue missing、company facts absent |
| Volume | stock shares、index not_applicable、provider missing、negative/malformed、never fake zero |
| Resolver | primary/fallback conflict、both stale/missing、future/partial、deterministic reason |
| Continuity | expected present/missing、internal gap、insufficient history、best available |
| GET purity | zero provider calls、zero writes、zero enqueue、acquisition controls rejected/deprecated |
| Lifecycle | priority/full-market scope、cursor/checkpoint、dedupe、retry/backoff、restart resume |
| Consumers | previous close、technical、Radar、valuation、AI freshness、source health、capability |
| Parity | `omi.decision.v4`、REST、MCP、Frontend selected facts與limitations |
| Architecture | no reverse dependency、no consumer fallback、exact debt shrink、no stale debt |
| Runtime | launcher root/interpreter/port/migration/SHA/mode、restart readback |
| Live | actual receipt/candidate/persist/reread/resolution/failure/fallback evidence |

## Review checkpoints

1. **R0 計畫核准**：使用者確認Prompt、milestones、non-goals與授權邊界；此前不改source。
2. **R1 Shared contract review**：M0–M1 diff、compatibility與TW regression通過後再進M2。
3. **R2 Storage decision review**：M2完成、M3 migration/sidecar方案與風險確認後再改schema。
4. **R3 Vertical slice review**：M3–M5 Source evidence通過後決定是否進priority/full-market。
5. **R4 Consumer/debt review**：M6–M8 source diff與acceptance完成後才討論runtime adoption。
6. **R5 Daily closeout replan**：M9.0–M11修正版經使用者核准後，先執行M9.0 Source closeout。
7. **R6 Pre-live source gate**：M9.0.5 negative matrix、single repair owner、candidate/Chart cleanup與architecture guard通過後，才進正式runtime adoption。
8. **R7 Three-symbol execution gate**：授權已取得；M9.0.6 runtime identity與side-effect isolation通過後，依AAPL -> TSM -> `^SOX` bounded執行。
9. **R8 Product／staged-tree gate**：M9.2 runtime/live readback與M9.3 product parity通過後，建立exact staged dependency closure並驗證isolated tree。
10. **R9 Commit/push/release gate**：授權已取得；仍須證明target/upstream/ancestry、remote SHA與version/release contract，不能隱性帶入ahead 6或無關dirty work。

## 決策紀錄

- 2026-08-29：附件視為提案，不是execution instruction；current executable source與typed contract優先。
- 2026-08-29：採單一Shared Core；US market-owned acquisition/persistence/expected state，不另建US Resolver/Quality/Registry。
- 2026-08-29：在US-B1前新增Shared Contract Gate，解決refresh reason/coverage/cursor、series coherence、dispatcher與rollout gaps。
- 2026-08-29：Gateway控制順序固定為read/resolve/plan/acquire/persist/reread/resolve；acquisition不得自行fallback。
- 2026-08-29：現有US daily lineage不足視為confirmed hard gate，不再當optional migration。
- 2026-08-29：TSM + `^SOX`作最小stock/index slice；index identity與volume applicability必須一般化，不hardcode。
- 2026-08-29：第一主線只做daily；fundamentals與intraday延後。
- 2026-08-29：初稿完成時等待使用者核准；該狀態已被後續M0–M8 Source implementation授權取代。
- 2026-08-29：M0–M8已完成並通過Source gate；此後production migration與runtime restart已由正式launcher採用，Live／Product與external side effects仍依新M9分段gate管理。
- 2026-08-29：使用者自行透過正式launcher重啟，migration `20260829_0073`與Runtime adoption已驗證；後續bounded provider refresh、canonical live seed、OMI／MCP lifecycle與publication現已取得使用者授權，但仍依budget與acceptance gate執行。
- 2026-08-29：read-only preflight確認名義AAPL canary未約束全域canonical read、REST response model缺parity欄位、public provider參數被忽略，以及legacy write caller inventory不完整；新增M9.0先修正，不直接進live seed。
- 2026-08-29：US full-market scheduler曾在三檔seed前執行；使用者授權將本機EOD markets限為TW並透過正式launcher restart。後續full-market雖已取得原則授權，仍保持paused直到closeout後另立bounded rollout milestone。
- 2026-08-29：Precommit v3提案經current source驗證後，新增M9.0.5；quality negative cases與repair single-owner必須在live seed前完成。
- 2026-08-29：三檔只建立canary-level Runtime/Live/Product gate；priority/full-market與Daily rollback seam retirement延為不阻擋precommit的後續rollout。
- 2026-08-29：使用者已授權commit/push/release，但current branch ahead 6；只有exact staged tree、target/upstream/ancestry與release contract證明後才能執行，不包含branch delete或無界publication。
