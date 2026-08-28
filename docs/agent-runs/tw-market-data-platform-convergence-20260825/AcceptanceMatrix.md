# Common Platform Acceptance Matrix

## Status legend

- `passed`：本task有目前checkout可重現證據。
- `partial`：部分能力存在，但尚未成為完整production owner。
- `pending`：尚未實作或尚無required evidence。
- `blocked`：已執行且有阻塞；需stop-and-fix。
- `deferred`：明確移出本次common-platform done criteria，另案處理。

## A. Architecture and persistence baseline

| ID | Requirement | Status | Evidence / planned proof |
| --- | --- | --- | --- |
| A-01 | 附件只作提案，已對照current truth | passed | `Prompt.md`、`ArchitectureAudit.md` |
| A-02 | 現有02A Resolver/Control/Registry不被重做成第二套 | passed | architecture decision |
| A-03 | 12項TW gap逐項核對current code | passed | `ArchitectureAudit.md` |
| A-04 | Actual-data-first vertical slices取代Big Bang與dark-only closure | passed | `Plan.md` |
| A-05 | Branch/HEAD/dirty worktree baseline已記錄 | passed | `Progress.md` |
| A-06 | Daily/EOD實際storage與ingress已盤點 | passed | SourceRegistry、RawFetchResult、MarketDailyPrice、coverage checkpoint evidence |
| A-07 | CP0 daily candidate store的owner/writer/reader/unique/lineage/transaction map | passed | `StorageAndBoundaryDecision.md` |
| A-08 | 現有schema沿用或additive migration決策有contract evidence | passed | CP0 read schema reuse decision；migration triggers明列 |
| A-09 | 新consumer/provider coupling與shared transaction owner由CI guard阻擋 | passed | `test_tw_data_core_boundaries.py` + debt baseline |

## B. Common Core contract

| ID | Requirement | Status | Planned proof |
| --- | --- | --- | --- |
| B-01 | `DataRequirementV2`可表達quote/bar/index/dataset需求 | passed | typed target/capability serialization與invalid-shape tests |
| B-02 | `RefreshRequirementV1`分離read與explicit mutation | passed | zero-I/O read policy與bounded refresh contract tests |
| B-03 | capability-resource `ProviderDescriptorV2` | passed | descriptor/pure catalog planning/health/bounds tests |
| B-04 | cache-first Gateway與candidate repository ports | passed | pure repository + TW read adapter + Gateway pre/post read tests |
| B-05 | `prefer_live`只在pre-resolution未滿足時acquire | passed | cache satisfied zero-call、stale acquire、require-live truthful tests |
| B-06 | Transaction owner執行idempotent persist/rollback，成功後repository reread | passed | SQLAlchemy integration驗證atomic commit/rollback、idempotent upsert與mandatory reread |
| B-07 | existing Resolver仍是唯一final selection owner | passed | Gateway只呼叫shared `resolve_bar_series`，executor/transaction不選source |
| B-08 | stable typed `MarketDataResultV1` | passed | result-kind、raw receipt、acquisition/persistence serialization tests |
| B-09 | Provider/Dataset/Resolved health完整分離 | passed | result envelope與Gateway merge tests；production adoption另由CP2-CP7追蹤 |

## C. Actual vertical slice 1 — official daily OHLCV

| ID | Requirement | Status | Planned proof |
| --- | --- | --- | --- |
| C-01 | TWSE official payload/receipt -> CanonicalBarObservation | passed | production receipt excerpt parser + canonical field assertions |
| C-02 | TPEx official payload/receipt -> CanonicalBarObservation | passed | production receipt excerpt legacy-table parser + canonical field assertions |
| C-03 | Raw receipt + daily candidates由明確transaction owner寫入 | passed | `TaiwanOfficialDailyTransaction` integration與boundary guard |
| C-04 | Persist後DB reread再resolve，不相信provider success string | passed | platform postcondition、cache-hit lineage與Gateway reread integration |
| C-05 | source/raw/trade date/fetched time/content hash/selection lineage完整 | passed | canonical row ID、raw receipt ID/hash、fetched/event time、selected provider/source/reason assertions |
| C-06 | 同source/symbol/date重跑idempotent | passed | 2 raw receipts、1 canonical row、unchanged summary、latest receipt lineage |
| C-07 | empty/malformed/partial/duplicate無silent data loss | passed | zero-bar missing、durable parse/HTTP failure、partial warning、duplicate reason、rollback tests |
| C-08 | daily read external calls = 0；refresh有target/date/venue/timeout/call budget | passed | cache-only chart read、venue scope與expected-date fail-closed、1 call/1 symbol/1 day plan |
| C-09 | stable daily API/projection讀取resolved platform result | passed | existing `MarketOhlcChartRead` validation + exact provider-neutral refresh route inventory |
| C-10 | TWSE與TPEx各有actual persist/readback evidence | passed | `artifacts/cp2-official-daily-evidence.json`; recorded production receipt excerpts replayed into isolated SQLite |

## D. Full-market EOD lifecycle

| ID | Requirement | Status | Planned proof |
| --- | --- | --- | --- |
| D-01 | Registry是EOD runtime lifecycle truth | passed | shared lifecycle contract + EOD runtime fail-closed binding |
| D-02 | expected date/eligibility/release window由spec驅動 | passed | latest-completed policy/scope validation + TW release guard |
| D-03 | healthy coverage時provider calls = 0 | passed | healthy TW integration test asserts zero `refresh_source` calls |
| D-04 | explicit reconcile只刷新unresolved venue且bounded | passed | TPEX-only repair test + Registry call/symbol/runtime clamp |
| D-05 | refresh後reread並重算postcondition/checkpoint | passed | repaired row只在post-refresh coverage recompute後成healthy |
| D-06 | current+partial+stale+missing = universe；unknown不轉0 | passed | DB constraint與coverage tests |
| D-07 | scheduler startup catch-up與retry/backoff由lifecycle operation使用 | passed | immediate startup、recomputed scheduler decision、Registry-bounded enqueue tests |
| D-08 | cache-only EOD API不repair | passed | current API/tests標示cache_only |
| D-09 | actual full-market coverage artifact | passed | read-only production recomputation/checkpoint parity artifact；status truthful partial |
| D-10 | provider transport success與dataset advancement分離 | passed | previous-date duplicate payload regression：transport success但`dataset_status=stale_payload`、success count不增加、postcondition false |
| D-11 | TWSE／TPEx venue coverage可直接觀測 | passed | checkpoint detail輸出venue universe/current/partial/stale/missing與coverage ratio；partition regression通過 |

## E. Actual vertical slice 2 — official index and breadth

| ID | Requirement | Status | Planned proof |
| --- | --- | --- | --- |
| E-01 | Official TWSE/TPEx index/breadth ports | passed | pure TWSE/TPEx descriptors/adapters；breadth由official daily candidate repository導出 |
| E-02 | actual payload -> canonical -> persist/readback -> resolve | passed | TWSE/TPEx actual public payload fixtures、isolated SQLite transaction/readback、Gateway/Resolver與CP4 artifacts |
| E-03 | TW official/final/provisional policy留在market projection | passed | completed-session observation validation、official/final/provisional與partial partition tests |
| E-04 | index、breadth、session、instrument status不混用 | passed | distinct `MarketIndexObservation` / `MarketBreadthObservation` contracts與semantic assertions |
| E-05 | provider outage/conflict由Resolver/health處理 | passed | HTTP/connection failure durable receipt、official-vendor conflict與Resolver official-first tests |
| E-06 | stable dashboard/API只讀resolved projection | passed | completed official index/breadth只由Data Core result提供；missing時`data_core_missing` fail closed，不復活legacy completed row；current-session observation維持獨立capability |

## F. Actual vertical slice 3 — public request-time data, no KGI

| ID | Requirement | Status | Planned proof |
| --- | --- | --- | --- |
| F-01 | 選定public MIS/official quote或intraday capability | passed | `CP5CapabilityContract.md` + single-symbol TWSE MIS `quote.last_trade` descriptor |
| F-02 | actual event/received/fetched/session/freshness lineage | passed | TWSE 2330 actual trade與TPEx 6173 indicative production rows封存/replay；`cp5-public-last-trade-evidence.json` |
| F-03 | 納入能力不再由`intraday.py`持有provider chain | passed | production `_load_intraday_trend_uncached`只讀platform cache projection；AST/source scenario guard禁止direct MIS quote fetch/fallback |
| F-04 | bars/volume/current trade顯式分開resolve/reconcile | passed | NStock/Yahoo price bars、bar volume與resolved current trade三個component lineage；quote不再製造或修改bar |
| F-05 | bounded `prefer_live`與truthful `require_live` | passed | 1 call/1 symbol/10秒/0 subscription；cache-hit zero-call、timeout receipt、trial/stale/post-close policy tests |
| F-06 | stable API data smoke | passed | actual persisted 2330 row經provider-neutral route handler回`MarketDataResultV1`；OpenAPI exact method/path inventory |
| F-07 | active-session public source live acceptance | pending | Production runtime已採用；收盤後2330 explicit acquisition以0 external calls truthful回`SESSION_NOT_SUPPORTED_BY_RESOURCE`。下一個台股active session仍須完成actual public-source sample，不得以recorded replay或post-close結果代替 |
| F-08 | post-close finalization不新增第二套Data Core／Resolver／dataset／table | passed | same `tw.quote.snapshot`、Gateway、Resolver、repository、transaction與raw receipt；model/catalog inventory無新增session-close plane或schema |
| F-09 | 13:30～13:33 centralized close-resolution taxonomy | passed | calendar／MarketSession／quote-depth／MIS／AI與frontend calendar-authority parity tests |
| F-10 | existing single-symbol quote path可bounded post-close confirmation | passed | 1 symbol／1 call／10秒／0 retry／0 subscription，persist後mandatory reread與generic post-close zero-I/O guard |
| F-11 | session-final promotion要求legal final-match event與post-resolution confirmation | passed | 13:24 rejection、13:30 match、13:31 resolving、13:33 confirmation、trial／date mismatch／volume regression fixtures |
| F-12 | `quote.session_close`與`quote.official_close`雙owner outward contract | passed | 14:00 3711 605／previous official 592／current official pending golden test |
| F-13 | session close freshness不遮蔽source freshness或official release state | passed | stale intraday不升格、session-close unavailable、dual owner/pending-release projection tests |
| F-14 | technical provisional／completed與official reconciliation正確 | partial | source tests涵蓋provisional gate、matched/mismatched與official wins；runtime 15:15 rollover／restart probe待PCF7 |
| F-15 | arbitrary TWSE／TPEx target不依賴fixed capture universe | passed | 3711 + TPEx recorded canonical evidence；production path不讀configured capture universe |
| F-16 | HTTP／SSE／MCP／frontend只消費同一backend projection | partial | capability advertised=>projection與AI/decision shared-contract tests通過；runtime transport parity probe待PCF7 |

## G. Dataset, provider onboarding and consumers

| ID | Requirement | Status | Planned proof |
| --- | --- | --- | --- |
| G-01 | 新增非KGI provider只改catalog + port + adapter | passed | TWSE/TPEx descriptors與ports共用相同Gateway/transaction/consumer；route無provider input |
| G-02 | 每個production TW dataset有完整lifecycle spec | passed | 28個typed dataset contracts；`CP6DatasetPlatformContract.md`與catalog tests |
| G-03 | advertised => projection；refreshable => bounded operation | passed | 28個read/projection/health callable與18個bounded operation皆實際resolve；registry/capability consistency tests |
| G-04 | chips/ETF/fundamentals/events/derivatives納入共同health/lineage | passed | Data Core health API讀actual storage/lineage；gap維持`lineage_incomplete`/`lineage_limited`，不假裝canonical/fresh |
| G-05 | AI不持有provider/fallback control | passed | Taiwan quote context只依賴Data Core projection；static boundary + v4 regressions |
| G-06 | HTTP/SSE/MCP `omi.decision.v4` parity維持 | passed | outward decision/MCP contract suite通過，provider/freshness/limitations由backend projection提供 |
| G-07 | Frontend/MCP/Kuro不重算market semantics | passed | backend-authoritative metadata優先；legacy local technical math僅`presentation_only`且不回流AI/MCP |
| G-08 | Backend authoritative technical series跨surface一致 | passed | vendor-conflict golden test證明API/AI共同resolve official bars並輸出相同RSI/MACD/KD；frontend authority contract guard |
| G-09 | OHLCV volume unit與latest finalized date outward明確 | passed | `volume_unit=shares`、volume semantics/status、`latest_finalized_data_date` schema/service/official daily platform tests |
| G-10 | finalized decision與provisional current technical state完全分流 | partial | source tests證明decision/current observation分流、post-close 605取代11:49 601、AI compact contract與frontend build通過；production launcher adoption／visible UI仍待執行 |

## H. Final common-platform closure

| ID | Requirement | Status | Planned proof |
| --- | --- | --- | --- |
| H-01 | 已遷移能力的legacy fallback/masquerading/provider controls移除 | passed | `CP8LegacyClosure.md` + boundary tests；未onboard current-session/depth/KGI明確不誤算為已遷移 |
| H-02 | 三條durable actual-data proofs + 一條non-KGI request-time proof | passed | CP2-CP5 artifacts + `test_tw_data_core_cold_read.py`於同一fresh file SQLite重現daily/index/breadth/public quote actual-data persistence |
| H-03 | restart後persisted data可由Gateway/API讀回 | passed | dispose/reopen engine後4個Gateway cache read external calls=0，chart/dashboard projection同源讀回 |
| H-04 | capability-level rollback rehearsal | passed | verified offline production backup clone完成0068 -> 0066 -> 0068，row counts、legacy unknown lineage、FK與quick check均保持；technical rollback test通過，production rollback policy明定先保留additive schema並回退application |
| H-05 | backend/frontend/full validation | passed | full safe validation `20260825-222211`：compileall、2280 backend tests、frontend lint/tsc/build與diff check全綠 |
| H-06 | runtime adoption/API/data/UI/MCP evidence | passed | launcher PID/port/ancestor lineage、health/ready、28 datasets/18 operations、TPEX actual cold read、visible browser、frontend proxy與MCP `omi.decision.v4`；`artifacts/cp8-production-adoption-20260825.json` |
| H-07 | current architecture docs同步 | passed | `BackendArchitecture.md`與`Roadmap.md`同步production-adopted／F-07-pending boundary |

## I. Explicitly deferred follow-up

| ID | Requirement | Status | Reason |
| --- | --- | --- | --- |
| I-01 | KGI quote/depth provider onboarding | deferred | 共同平台完成後另案，避免provider反向塑造Core |
| I-02 | Generic realtime lease切到KGI runtime | deferred | 同上；Quote與Account health仍須分離 |
| I-03 | 既有M5 Preopen/Opening/Regular/Closing/Post-close acceptance | deferred | 使用者明確要求本次先不管，後續重新處理KGI |

## Completion rule

只有A-H所有required rows為`passed`、無`blocked`，且current production flow不再繞過Shared Platform，才能標記`TW_DATA_CORE_COMMON_PLATFORM_OPERATIONAL`。

I區是明確deferred follow-up，不阻塞本target；但不得因I區deferred而把KGI quote/depth或realtime lease宣稱為已完成。
