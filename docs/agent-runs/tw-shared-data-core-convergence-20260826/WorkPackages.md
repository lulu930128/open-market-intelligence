# Work Packages

## 使用方式

- 一次只開一個 primary work package；必要的 test / docs與該 package一起完成。
- 開始前重讀 touched files、nested instructions、dirty status與上一包 evidence。
- 完成後更新 `ExecutionBoard.md`、`Progress.md`、`DecisionLog.md`，並在 `artifacts/` 保存 bounded evidence摘要。
- 每包最多只跨必要邊界；若需求擴大，拆成新 package，不把 scope偷塞進現有 package。

## Package index

| ID | 目標 | 依賴 | 終點 gate | 初始狀態 |
|---|---|---|---|---|
| BASE-01 | Current architecture audit | 無 | G0 | SOURCE_COMPLETE |
| BASE-02 | Long-project baseline | BASE-01 | G0 | SOURCE_COMPLETE |
| CORE-01 | Pure central quality evaluator | BASE-02 | G1 | NOT_STARTED |
| CORE-02 | Gateway / Resolver eligibility integration | CORE-01 | G1 | NOT_STARTED |
| CORE-03 | Depth / auction typed Gateway wiring | CORE-02 | G1 | NOT_STARTED |
| KGI-01 | TW KGI/MIS descriptors與acquisition seam | CORE-03 | G1 | NOT_STARTED |
| KGI-02 | Multi-provider quote persistence / repository | KGI-01 | G2 | NOT_STARTED |
| KGI-03 | Depth / auction persistence / repository | KGI-01, KGI-02 | G2 | SOURCE_COMPLETE |
| KGI-04 | Provider-neutral viewer lease platform | KGI-03 | G2 | SOURCE_COMPLETE |
| KGI-05 | Router/frontend/quote-depth cutover | KGI-04 | G3 | SOURCE_COMPLETE |
| BAR-01 | NStock/Yahoo shared adapters與planner | CORE-02 | G1 | SOURCE_COMPLETE |
| BAR-02 | Intraday raw/derived lineage persistence | BAR-01 | G2 | SOURCE_COMPLETE |
| BAR-03 | Explicit refresh + GET cache-only | BAR-02 | G3 | SOURCE_COMPLETE |
| BAR-04 | Intraday legacy cleanup / projection convergence | BAR-03 | G3 | SOURCE_COMPLETE |
| IDX-01 | Current-session index Shared Core slice | CORE-02 | G2 | SOURCE_COMPLETE |
| BRD-01 | Current-session breadth Shared Core slice | CORE-02 | G2 | SOURCE_COMPLETE |
| IDX-02 | Index/breadth routes與legacy orchestration cutover | IDX-01, BRD-01 | G3 | SOURCE_COMPLETE |
| TAIL-01 | Company profile market-owned reader | CORE-02 | G3 | SOURCE_COMPLETE |
| TAIL-02 | Minute/intraday derived component lineage seam | BAR-02, IDX-01, BRD-01 | G2 | SOURCE_COMPLETE |
| TAIL-03 | 長尾 dataset migration guards/order | TAIL-01, TAIL-02 | G1 | SOURCE_COMPLETE |
| CROSS-01 | API/AI/MCP/frontend parity與architecture guards | KGI-05, BAR-04, IDX-02, TAIL-01, TAIL-02 | G3 | SOURCE_COMPLETE |
| ADOPT-01 | Named-runtime adoption | CROSS-01 | G4 | PENDING |
| LIVE-01 | M5 official-session acceptance | ADOPT-01 | G5 | PENDING |
| CLOSE-01 | Debt、catalog、docs與evidence closeout | LIVE-01 | G6 | IN_PROGRESS |

## Wave 0 — Baseline

### BASE-01 — Current architecture audit

- Owned boundary：read-only source、tests、product / architecture docs。
- Acceptance：P0 / P1 / P2主張分類為 verified / partial / added / pending。
- Evidence：`AcceptanceMatrix.md`、`ArchitectureMap.md`、`architecture-audit-evidence.json`。
- Rollback：不適用；沒有 production diff。

### BASE-02 — Long-project baseline

- Owned boundary：本 task folder。
- Acceptance：work packages、dependency、validation、risk、decisions、execution board完整且互相一致。
- Validation：Tier 0 strict UTF-8、JSON parse、Markdown structure、diff check。
- Rollback：只修改本 task folder。

## Wave 1 — Shared Safety

### CORE-01 — Pure central quality evaluator

- Planned boundary：`backend/app/market_data/integration_contracts.py`、新增 shared quality policy module、targeted tests。
- Scope：
  - 定義 `QualityEvaluation`、eligible flag、stable reason codes、missing fields與limitations。
  - `required_fields` enforcement使用 request與quality的明確合併規則，不由 reader各自猜。
  - `minimum_authority`使用明確 authority rank / admissibility policy，不依 Enum順序。
  - `allow_partial=False` 阻止 partial candidate成為 research-usable。
  - canonical lineage要求採 additive flag，預設維持向後相容；啟用時驗證 raw receipt ID、content hash與必要 timestamps。
- Non-goals：不選 provider、不做 TW session解釋、不改 Resolver排序、不碰 KGI。
- Acceptance：pure unit tests涵蓋 field missing、authority不足、partial、lineage缺漏、missing/stale/future timestamps與stable reasons。
- Rollback：新 evaluator尚未接 production path，可直接停留為 unused tested seam。

### CORE-02 — Gateway / Resolver eligibility integration

- Planned boundary：`market_data/gateway.py`、`market_data/resolution.py`、candidate batch contracts與tests。
- Scope：在 Resolver selection前套用 quality evaluation，將 rejection投影到 candidate summaries / limitations；保留既有 ranking。
- Compatibility：先以 bars / quote現有 paths建立回歸，public MIS quote不得 regression。
- Acceptance：同一 requirement在bars / quote得到一致 eligibility；API/AI不能繞過；cache/live/completed policies維持既有結果。
- Rollback：保留 evaluator pure API，撤回 integration hunk即可；不得修改 provider adapters補救。

### CORE-03 — Depth / auction typed Gateway wiring

- Planned boundary：`market_data/gateway.py`、`integration_contracts.py`、candidate/transaction ports、Gateway tests。
- Scope：Depth/Auction CandidateBatch、Reader、AcquisitionResult、AcquisitionPort、TransactionPort與 `resolve_depth()` / `resolve_auction()`。
- Acceptance：cache hit zero IO、require-live truthful failure、bounds、attempt route subset、persist後mandatory reread、transaction failure、typed result_kind全通過。
- Non-goals：不在 shared core放KGI/MIS名字，不新增第二個 Resolver，不先決定 TW provider priority。

## Wave 2 — KGI Canonical

### KGI-01 — TW KGI/MIS descriptors與acquisition seam

- Planned boundary：`backend/app/market/providers/` 與 market-owned realtime platform modules。
- Scope：分開宣告 quote.snapshot、quote.order_book、auction；session、venue、authority、live能力、timeout、subscription與limitations顯式化。
- Acceptance：planner只選符合 target/session/capability/bounds的route；shared core source search沒有KGI/MIS字樣。
- Rollback：descriptors先不接public route；可保持production-unwired。

### KGI-02 — Multi-provider quote persistence / repository

- Planned boundary：public quote transaction/repository/platform與必要migration。
- Scope：generalize MIS-only source defaults與reader hard filter；KGI raw receipt + canonical quote可被repository reread。
- Acceptance：MIS既有tests不 regression；KGI/MIS同時存在時Resolver deterministic；legacy無lineage row fail closed；provider不得偽裝。
- Migration：若只需既有 nullable source/raw IDs，不新增schema；若需constraint/index，先做disposable DB upgrade/downgrade證據。
- Rollback：KGI candidate可保持shadow / ineligible，不立刻改public selected truth。

### KGI-03 — Depth / auction persistence / repository

- Planned boundary：market-owned depth/auction repository、transaction、migration與tests。
- Scope：raw receipt、SourceRegistry、RawFetchResult、canonical depth/auction rows或等價typed storage；component不可混表成quote。
- Acceptance：trial/indicative只進auction；depth levels / capability一致；quote/depth/auction lineage各自完整；reread後才resolve。
- Open design gate：先決定專用typed tables或既有normalized storage extension；禁止generic JSON blob platform。
- Rollback：migration需可在disposable DB downgrade；user DB不作破壞性rehearsal。

## Wave 3 — Realtime Cutover

### KGI-04 — Provider-neutral viewer lease platform

- Planned boundary：market realtime application layer、existing research lease/control primitives、provider port、router tests。
- Scope：provider-neutral intent、owner token、heartbeat、cancel、timeout、symbol switch、subscription bounds與redacted summary。
- Acceptance：quote/account health分離；cleanup active handles=0；stale symbol lease=0；unknown lease不被force release。
- Non-goals：不把persistent viewer lifecycle假裝成request-scoped research lease；不建立第三套provider-specific framework。

### KGI-05 — Router/frontend/quote-depth cutover

- Planned boundary：`routers/market.py`、`market/quote_depth.py`、TW quote-depth frontend hook、boundary tests。
- Scope：router不direct import KGI manager；GET quote-depth cache-only；frontend不再polling refresh GET；legacy service降級成thin projection/compatibility。
- Acceptance：cp0 KGI debt移除；GET zero IO/commit/subscription；POST/PATCH/DELETE仍保持public API compatibility或有明確additive transition。
- Rollback：provider-neutral platform先包住舊manager implementation；public interface不一次breaking rewrite。

## Wave 4 — Intraday Bars

### BAR-01 — NStock/Yahoo shared adapters與planner

- Planned boundary：market-owned descriptors/adapters、Gateway bar acquisition、intraday tests。
- Scope：純fetch/parse/canonical conversion；priority只在descriptors / shared plan。
- Acceptance：`intraday.py`不再包含cross-provider priority；provider attempt不超plan；MIS quote仍不會成bar。
- Dirty-worktree rule：`backend/app/market/intraday.py`已有使用者hunk，開始前必須逐段重讀並保留。

### BAR-02 — Intraday raw/derived lineage persistence

- Planned boundary：MarketIntradayBar model/migration、transaction/repository、5m aggregation metadata。
- Scope：SourceRegistry、RawFetchResult、provider identity、raw receipt；derived rows保留source interval、component raw IDs、calculation version。
- Acceptance：NStock row不被標成Yahoo；quote volume不混入bar volume；persist後reread；lineage gap health如實改善。

### BAR-03 — Explicit refresh + GET cache-only

- Planned boundary：market router、refresh operation/job、frontend chart hook與API tests。
- Scope：先建立bounded POST/job，再將trend/history GET固定cache-only並忽略/移除legacy refresh behavior的安全transition。
- Acceptance：所有TW intraday GET external calls=0、commit=0；explicit refresh有bounds、timeout、provider lineage與結果摘要。

### BAR-04 — Intraday legacy cleanup / projection convergence

- Scope：移除legacy direct URLs/fallback/upsert ownership；projection讀shared resolved bars + public quote component。
- Acceptance：source_components、lag、limitations保留；AI/MCP cache-only；frontend不重算research semantics。

## Wave 5 — Current Index / Breadth

### IDX-01 — Current-session index Shared Core slice

- Planned boundary：market-owned current index descriptors/adapters/repository/transaction與Gateway wiring。
- Scope：`market.index.snapshot`或經current code確認後的等價capability；TAIEX/TPEX venue/session分離。
- Acceptance：current observation不覆蓋completed official final evidence；Yahoo/MIS/official只產candidate；GET cache reader zero IO。

### BRD-01 — Current-session breadth Shared Core slice

- Planned boundary：market-owned breadth current descriptors/adapters/repository/transaction與TW policy。
- Scope：universe_count、classified、unknown、not_received、received_unclassified、coverage、provisional、decision_usable與limitations。
- Acceptance：unknown不轉0；coverage equation穩定；full_market與OMI sample不混；provider failure truthful partial/failed。

### IDX-02 — Routes與legacy orchestration cutover

- Planned boundary：`market/indices.py`、`routers/tw_market_indices.py`、frontend index chart / tape hooks、guards。
- Scope：`/indices/summary`維持cache-only；`/indices/{id}/intraday`改cache-only；refresh只由existing explicit POST/job進入shared path。
- Acceptance：indices.py不再direct import provider HTTP/fallback owner；completed official tests全過；current-session projection無語意回退。

## Wave 6 — P2 Seams

### TAIL-01 — Company profile market-owned reader

- Scope：dedicated reader/projection seam取代AI `db.query(StockProfile)`；保留outward payload compatibility。
- Acceptance：AI只依賴market-owned port；missing profile truthful；無provider/DB logic洩漏至MCP/frontend。

### TAIL-02 — Derived component lineage seam

- Scope：`tw.market.minute_state`、`tw.stock.intraday.state`持久化component source/raw-result IDs、time skew與calculation metadata。
- Acceptance：跨provider component不偽裝單一lineage；component缺失導致partial而非0或ready。

### TAIL-03 — 長尾 dataset migration guards/order

- Scope：7 compatibility與剩餘 lineage-gap datasets只建立owner、reader/transaction seam、migration order與anti-debt tests。
- Acceptance：沒有新direct AI SQL、consumer fallback或偽repairability；不要求本輪全部fully migrate。

## Wave 7 — Cross-surface / Runtime / Live

### CROSS-01 — Cross-surface parity與architecture guards

- Scope：API / AI / MCP / frontend contract snapshots、source guards、cp0 debt縮減。
- Acceptance：同一resolved truth、health、lineage、limitations跨surface一致；frontend無第二套provider/freshness/quality logic。

### ADOPT-01 — Named-runtime adoption

- 前置：需要使用者對named OMI runtime的明確restart/adoption授權。
- Scope：repo launcher-selected backend/frontend、direct/proxy readiness、runtime identity、DB migration、OpenAPI與可見UI。
- Acceptance：source fingerprint與runtime一致；backend healthy不被當作proxy/UI通過；沒有廣域process kill。

### LIVE-01 — M5 official-session acceptance

- Scope：SourceOnly、Preopen、Opening、Regular、Closing Auction、symbol switch、cleanup、compare/off rollback。
- Acceptance：duplicate trade=0、trial leak=0、cumulative decrease=0、L5正常、cleanup residual=0。
- Truth rule：錯過時段或沒有live entitlement即維持PENDING；offline fixture、replay、post-close readiness不能代替。

### CLOSE-01 — Program closeout

- Scope：legacy code/debt allowlist/catalog/docs/decision log/evidence matrix更新。
- Acceptance：P0/P1全部G6；P2 seams具owner與guard；所有remaining pending明確列出，沒有假裝Foundation全閉合。
