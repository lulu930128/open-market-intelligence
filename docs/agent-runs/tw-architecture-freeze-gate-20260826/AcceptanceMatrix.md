# 台股 Architecture Freeze Gate 驗收矩陣

狀態：`PLANNED`、`IN_PROGRESS`、`SOURCE_PASS`、`RUNTIME_PASS`、`LIVE_PASS`、`BLOCKED`、`DEFERRED`。

| ID | Requirement | Source acceptance | Validation evidence | Initial status |
|---|---|---|---|---|
| LIFE-01 | Auction capability統一`quote.auction` | descriptor/requirement/receipt/repository/AI/MCP exact ID | capability inventory + tests | SOURCE_PASS |
| LIFE-02 | Depth dataset registered | Registry、TW Catalog、probe、owner、projection存在 | registry/catalog/health tests | SOURCE_PASS |
| LIFE-03 | Auction dataset registered | Registry、TW Catalog、probe、owner、projection存在 | registry/catalog/health tests | SOURCE_PASS |
| LIFE-04 | Intraday DatasetHealth | every result has deterministic non-null health | intraday platform tests | SOURCE_PASS |
| LIFE-05 | Depth DatasetHealth | missing/NA/current/stale/partial semantics | realtime platform tests | SOURCE_PASS |
| LIFE-06 | Auction DatasetHealth | session/disposition applicability不在shared core | auction policy tests | SOURCE_PASS |
| LIFE-07 | Current index DatasetHealth | current/provisional/missing/stale deterministic | current market tests | SOURCE_PASS |
| LIFE-08 | Current breadth DatasetHealth | coverage/partial/unknown保留 | breadth tests | SOURCE_PASS |
| LIFE-09 | Health layers分離 | Provider/Dataset/Resolved fields不互代 | contract tests | SOURCE_PASS |
| AIQ-01 | Typed quote evidence bundle | quote/depth/auction/official close retain four independent results | bundle unit/integration | SOURCE_PASS |
| AIQ-02 | Cache-only bundle read | read external calls=0 | acquisition sentinel | SOURCE_PASS |
| AIQ-03 | Explicit bundle acquisition | bounded command then repository reread | gateway/transaction tests | SOURCE_PASS |
| AIQ-04 | AI real depth evidence | canonical depth row reaches outward capability | vertical fixture | SOURCE_PASS |
| AIQ-05 | AI real auction evidence | indicative stays non-trade | vertical fixture | SOURCE_PASS |
| AIQ-06 | Official close authority | only completed official/daily owner selected | completed path regression | SOURCE_PASS |
| VAL-01 | AI daily no legacy ORM | no `get_latest_stock_daily_price` dependency | AST + context tests | SOURCE_PASS |
| VAL-02 | Portfolio no market price ORM | no TW/US/JP/KR price model imports/query | AST + portfolio tests | SOURCE_PASS |
| VAL-03 | Valuation contract truthful | unknown/stale/partial/market closed preserved | valuation tests | SOURCE_PASS; regional lineage compatibility |
| GET-01 | Core GET remains cache-only | OHLC/intraday/quote-depth/index zero IO | route sentinel | SOURCE_PASS baseline |
| GET-02 | Chips/fundamentals GET cache-only | `ensure_*` cannot mutate from GET | route tests | SOURCE_PASS |
| GET-03 | Overnight GET cache-only | default/request cannot refresh | route tests | SOURCE_PASS |
| GET-04 | Holding ratio GET cache-only | no direct nStock IO | provider sentinel | SOURCE_PASS; compatibility cache |
| GET-05 | Futures latest GET cache-only | no refresh/commit | futures route tests | SOURCE_PASS |
| GET-06 | Futures intraday GET cache-only | no refresh/commit | futures route tests | SOURCE_PASS |
| GET-07 | Consumer provider control removed | router/frontend/AI/MCP provider selection=0 | AST/source guard | SOURCE_PASS; deprecated params ignored |
| FRESH-01 | Single executable lifecycle owner | expected/eligibility/freshness from Registry/lifecycle | parity tests | SOURCE_PASS |
| FRESH-02 | TW Catalog role clear | inventory/projection only, no second evaluator | architecture test | SOURCE_PASS |
| FRESH-03 | Source health role clear | provider/source health only | source health tests | SOURCE_PASS |
| FRESH-04 | AI freshness thin | no raw price freshness SQL | AST + AI tests | SOURCE_PASS |
| SIDE-01 | Institutional holding classified | dataset/exemption owner/status/refresh/health documented | catalog guard | SOURCE_PASS; COMPATIBILITY_CACHE |
| SIDE-02 | Disposition classified | cache/noncanonical semantics explicit | catalog/route tests | SOURCE_PASS; COMPATIBILITY_CACHE |
| SIDE-03 | Corporate event classification retained | no false platform-owned claim | catalog tests | SOURCE_PASS; LINEAGE_GAP |
| SIDE-04 | ETF classification retained | no hidden lineage upgrade | catalog tests | SOURCE_PASS; LINEAGE_GAP |
| SIDE-05 | Futures/derivatives debt explicit | provider/transaction/lineage limits visible | catalog/health tests | SOURCE_PASS; LINEAGE_GAP |
| BND-01 | TW V1 import remains zero | no production import V1 planner/control | boundary test | SOURCE_PASS baseline |
| BND-02 | Stream presentation-only | five invariant fields enforced end-to-end | backend/frontend tests | SOURCE_PASS baseline |
| BND-03 | CP0 consumer debt exact empty | actual imports equal allowlist | boundary test | SOURCE_PASS baseline |
| BND-04 | New TW surface catalog guard | outward dataset/route cataloged or exempt | new architecture test | SOURCE_PASS |
| EOD-01 | EOD transaction debt not expanded | actual debt <= exact allowlist | boundary test | SOURCE_PASS baseline |
| EOD-02 | Optional EOD physical closure | shared module no commit/rollback | EOD regression | DEFERRED |
| CROSS-01 | API/AI/MCP parity | same resolved fixture, health, lineage, limitations | cross-surface tests | SOURCE_PASS |
| CROSS-02 | Frontend thin | no provider/freshness/research recomputation | lint/typecheck/source guard | SOURCE_PASS |
| CROSS-03 | Targeted backend green | task-owned suites pass | pytest logs | SOURCE_PASS; 500 + migration 13 |
| CROSS-04 | Docs/diff hygiene | UTF-8/JSON/Markdown/diff checks pass | validation artifact | SOURCE_PASS |
| ADOPT-01 | New source runtime adopted | launcher identity/migration/direct/proxy/MCP/UI | M5 2026-08-27 SourceOnly／restart／conflict artifacts | RUNTIME_PASS source adoption; current safe mode=off after repeated external-owner overwrite, compare must be re-established before Preopen |
| LIVE-01 | Official-session semantics | Preopen/Opening/Regular/Closing evidence | M5 dated live artifacts | BLOCKED; Opening/Regular/Closing pass, final-source Preopen pending, external runtime owner conflict |
| LIVE-02 | Symbol switch/L5 | no stale lease, correct depth | `m5-live-regular-current-source-retry-20260827-0908.json` | LIVE_PASS; 2330→2303→2330 L5=7186/2561/2556ms |
| LIVE-03 | Trade safety | duplicate=0、trial leak=0、cumulative decrease=0 | Regular + Closing live counters | LIVE_PASS projection integrity; Closing 204 callbacks、119 auction additions、24 strict advances/24 trade additions、177 same suppressed、0 decrease、0 trial leak |
| LIVE-04 | Cleanup | active handles after cleanup=0 | Regular + Closing artifacts + Opening cleanup extension | LIVE_PASS; external leases未被本任務release，Closing owner cleanup後global leases=0、bridge=false |
| CLOSE-01 | Architecture freeze | source closeout complete；runtime/live pending仍truthful | final matrix | SOURCE_PASS; runtime/live pending |
| FINAL-01 | Daily source-health single owner | `market_daily_price`只投影canonical daily DatasetHealth | source-health/daily freshness tests | SOURCE_PASS |
| FINAL-02 | Disposition fail closed | missing/stale/degraded/malformed cache不得推定continuous | trading policy + AI/intraday tests | SOURCE_PASS |
| FINAL-03 | Intraday auction typed path | active disposition -> `AuctionType.INTRADAY`；type-specific persist/reread | realtime capability/persistence tests | SOURCE_PASS |
| FINAL-04 | Platform evidence語意 | storage/lineage endpoint不冒充lifecycle freshness | dataset health + OpenAPI tests | SOURCE_PASS |
| FINAL-05 | Quote acquisition scope | requested/acquired/materialized outward可辨識；quote alias bounded | MIS acquisition + AI intent tests | SOURCE_PASS |
| FINAL-06 | Final closure gate | targeted regression、checkpoint hash、safe validation、docs hygiene | final artifacts | SOURCE_PASS; runtime/live pending |
