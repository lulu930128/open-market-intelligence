# Work Packages

每包只在前置acceptance通過後開始；實作期間同步更新`ExecutionBoard.md`與`Progress.md`。

## BASE-01 — Freeze baseline

- Priority：P0 prerequisite
- Owners：docs / architecture inventory / read-only DB inspection
- Scope：touched-file diff、registry/catalog/probe/candidate/consumer/GET/sidecar inventory、durable capability identity。
- Acceptance：exact baseline artifact；legacy`auction`durable rows有明確答案；staged files=0。
- Validation：source/AST inventory、read-only DB query、UTF-8/JSON checks。
- Rollback：docs/artifact only。

## LIFE-01 — Capability vocabulary

- Depends：BASE-01
- Scope：auction constant、descriptors、requirements、resource attempts、transactions、repositories、fixtures、AI/MCP outward。
- Acceptance：canonical`quote.auction`exact parity；不存在未註明production`auction` capability。
- Durable rule：若DB已有舊identity，先additive alias/migration並設定退場條件。
- Validation：realtime capability/persistence/Gateway/provider catalog/AI/MCP contract tests。
- Rollback：保留alias與舊read compatibility，先回consumer cutover，不刪資料。

## LIFE-02 — Depth / Auction dataset registration

- Depends：LIFE-01
- Scope：Shared Registry、TW Catalog、storage-lineage probes、dataset IDs、read/refresh operation metadata。
- Acceptance：`PLATFORM_OWNED => registered + probe + projection + lifecycle owner` guard通過。
- Validation：registry、catalog、dataset health、API inventory tests。
- Rollback：registration為additive；不改0069 typed tables。

## LIFE-03 — Executable DatasetHealth

- Depends：LIFE-02
- Scope：intraday、depth、auction、current index、current breadth candidate-reader/lifecycle seam。
- Acceptance：registered production results的`dataset_health`非空；missing/NA/partial/stale/current語意正確。
- Validation：各platform targeted、Gateway、quality、session/applicability tests。
- Stop：不得把TW session邏輯放入generic Gateway。
- Rollback：market reader注入點可局部回退；不改Resolver ranking。

## AIQ-01 — Taiwan quote evidence contract

- Depends：LIFE-03
- Scope：typed bundle/results、cache-only reader、explicit acquirer、component projection。
- Acceptance：quote/depth/auction/official close各有獨立health/lineage/limitations；read zero IO。
- Validation：bundle unit、quote/depth/auction persistence、official platform regression。
- Rollback：additive seam；舊public quote projection暫留compatibility。

## AIQ-02 — AI / MCP vertical cutover

- Depends：AIQ-01
- Scope：TaiwanStockDependencies、query plan reader contract、capability projection、MCP parity。
- Acceptance：canonical depth/auction rows可真實抵達AI/MCP；synthetic-only fixture不再是唯一證據。
- Validation：AI context、capability contract、outward contract、MCP server/schema、cross-surface fixture。
- Stop：AI不得importstream/provider或自己fallback。
- Rollback：切回舊bundle adapter，但不刪新market reader。

## VAL-01 — Market-owned daily evidence reader

- Depends：LIFE-03
- Scope：latest daily/official-close projection、AI Taiwan daily dependency。
- Acceptance：AI不呼叫legacy raw ORM reader；trade date/freshness/source/limitations來自market-owned result。
- Validation：daily platform、AI context、technical/official-close regression。
- Rollback：reader為additive；保留舊service給legacy non-AI callers直到後續migration。

## VAL-02 — Portfolio valuation reader

- Depends：VAL-01
- Scope：market-neutral valuation protocol、TW implementation、Portfolio context injection；regional adapters分段接入。
- Acceptance：Portfolio context無price model import/query、無自有market/provider fallback；unknown不轉0。
- Validation：portfolio context/service/API、account separation、valuation fixtures、AST guard。
- Stop：不得把Account健康與Quote健康合併。
- Rollback：compatibility adapter可包舊readers，但fallback owner必須在market layer。

## GET-01 — Route side-effect inventory與guard

- Depends：LIFE-03
- Scope：所有TW GET call graph、provider IO/commit/lease sentinels、explicit command inventory。
- Acceptance：產出actual violating routes；guard可抓直接與間接side effect，不只檢查函式名稱。
- Validation：AST/source inventory + monkeypatch runtime sentinels。
- Rollback：tests/docs only。

## GET-02 — Legacy metrics與overnight command split

- Depends：GET-01
- Scope：market chips、institutional、margin、shareholding、revenue、financials、overnight impact GET/POST。
- Acceptance：GET zero IO/mutation；explicit POST/job保留bounds與compatibility。
- Validation：route/API inventory、daily/fundamental backfill targeted、frontend call-site search。
- Rollback：先additive POST，再降級GET flags；public response shape保持。

## GET-03 — Holding ratio與futures closure

- Depends：GET-01、SIDE-01
- Scope：nStock holding ratio cache/command seam、futures latest/intraday provider-neutral reads與explicit refresh。
- Acceptance：GET不IO/commit；consumer provider parameter不影響production selection；provider adapter不transaction。
- Validation：holding parser/cache、futures quote/intraday/route/catalog/architecture tests。
- Rollback：保留deprecated query參數但忽略/拒絕；不刪既有rows。

## FRESH-01 — Canonical lifecycle authority

- Depends：LIFE-03
- Scope：Registry/lifecycle authority、TW Catalog parity、legacy specs adapter。
- Acceptance：每dataset只有一個executable expected/eligibility/freshness rule owner。
- Validation：dataset lifecycle、registry/catalog parity、calendar/freshness tests。
- Rollback：compatibility projection保留；禁止雙寫兩套規則。

## FRESH-02 — Source health / AI freshness cutover

- Depends：FRESH-01、VAL-01
- Scope：source health、AI freshness、Taiwan context freshness、storage probe naming/contract。
- Acceptance：AI不raw SQL重算platform-owned price freshness；source health不冒充DatasetHealth。
- Validation：source health、AI freshness/context、dataset health/API contract tests。
- Rollback：保留outward fields，用adapter轉新health，避免breaking response。

## SIDE-01 — Sidecar classification inventory

- Depends：BASE-01
- Scope：disposition、holding ratio、corporate events、ETF、futures/derivatives、chips/fundamentals。
- Acceptance：每項具有dataset/exemption ID、owner、read/refresh、IO、storage、lineage、health、decision usability與limitations。
- Validation：catalog/probe/API inventory/route search。
- Rollback：docs/catalog metadata only。

## SIDE-02 — Sidecar anti-debt enforcement

- Depends：SIDE-01、GET-03
- Scope：catalog/exemption guard、truthful convergence status、必要的typed storage/migration seam。
- Acceptance：新TW outward surface未分類時CI fail；不得把lineage gap標platform-owned。
- Validation：architecture guard、catalog/health tests、disposable migration（若有）。
- Rollback：classification changes additive；不刪歷史sidecar data。

## EOD-01 — Optional transaction debt closure

- Depends：CROSS-01 prerequisite source green
- Priority：P2 conditional
- Scope：EOD coverage/repair transaction port、cp0 allowlist縮減。
- Acceptance：shared lifecycle module無commit/rollback；TW/US coverage與repair state不regression。
- Validation：EOD coverage、repair/scheduler focused、boundary tests。
- Stop：若擴及US redesign/scheduler rewrite/schema migration則DEFERRED。
- Rollback：operation factory切回legacy transaction adapter；不清資料。

## CROSS-01 — Source freeze gate

- Depends：AIQ-02、VAL-02、GET-03、FRESH-02、SIDE-02
- Scope：cross-surface、architecture、frontend、migration、docs/diff/exact manifest。
- Acceptance：FG1～FG6全pass；task-owned failure=0；staged files=0。
- Validation：見`ValidationStrategy.md`。
- Rollback：逐package回退task-owned hunks，不用destructive git。

## ADOPT-01 — Named runtime adoption

- Depends：CROSS-01、使用者明確runtime授權
- Scope：launcher-selected backend/frontend/MCP、migration、health/ready、direct/proxy/UI。
- Acceptance：新source identity與DB revision可證明；zero lease baseline。
- Validation：launcher log、process lineage、API/proxy/MCP/UI smoke。
- Rollback：既有launcher component lifecycle；不broad-kill。

## LIVE-01 — Official-session acceptance

- Depends：ADOPT-01、合法market session
- Scope：Preopen、Opening、Regular、Closing Auction、symbol switch、L5、trade safety、cleanup。
- Acceptance：duplicate=0、trial leak=0、cumulative decrease=0、stale lease=0、active handles=0。
- Validation：time-stamped live artifacts；不得用其他時段補造。
- Rollback：release task-owned lease、compare/off復原；不force-release外部owner lease。

## CLOSE-01 — Architecture freeze closeout

- Depends：CROSS-01、ADOPT-01；LIVE-01未完成時只能partial/pending。
- Scope：final matrix、debt/allowlist、exact manifest、docs/status、剩餘migration order。
- Acceptance：所有claim有source/runtime/live evidence；未驗證項目保持可見。
- Validation：final readback、git status/diff、artifact schema checks。
