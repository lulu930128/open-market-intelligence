# 進度紀錄

## 2026-08-26 — 架構確認 checkpoint

狀態：source audit 完成；production implementation 尚未開始。

### 已完成

- 讀取 current product truth：Product Vision、Operating Model、Quality Bar、Roadmap、Backend Architecture、OMI Decision Contract。
- 盤點 branch 與 dirty worktree；確認 `backend/app/market/intraday.py` 已有既存 MIS 偽 bar 移除變更，必須原樣保留。
- 追蹤 Shared Gateway、provider catalog、Resolver、candidate repository、raw receipt / transaction pattern。
- 追蹤 public MIS quote platform 與 KGI / quote-depth legacy path。
- 追蹤 intraday trend/history、current-session index/breadth、router 與 frontend polling call sites。
- 搜尋 `QualityRequirement` production consumers並確認中央 enforcement 缺口。
- 核對 TW dataset catalog counts、dataset health semantics 與 AI company profile direct ORM query。
- 建立 ArchitectureMap、AcceptanceMatrix 與 evidence artifact。

### 核心結論

1. 使用者文件的 P0 / P1 / P2 主架構判斷大致正確。
2. Shared Resolver 已有 depth / auction typed resolution，但 Gateway application layer 沒有對應 reader、acquisition、transaction 或 resolve methods。
3. public MIS quote 是已收束 vertical slice；KGI / quote-depth 仍是平行 legacy owner，並未成為 Shared Core candidate。
4. `QualityRequirement` 目前是 declarative contract；Resolver 的 temporal / policy checks 不能取代 required fields、authority、partial 與 lineage gate。
5. GET side-effect 缺口比原文件列得更廣：trend intraday、index intraday、quote-depth polling 也可能進入 provider IO 或 mutation。
6. 現有 `research_lease.py` 是 request-scoped cooperative acquisition primitive；KGI frontend viewer heartbeat 是另一種 lifecycle。可以共用 owner / cleanup / bounds primitives，但不能直接假設前者已經是完整 viewer lease platform。

### 與原規格的差異／補充

- `MarketIndexAcquisitionResult` 已有 type，但 `resolve_market_index()` 仍是 read-only；不能把 type 存在描述成 application wiring 已完成。
- `SourceLineage` contract 已能表示 fetched time、raw receipt ID 與 content hash；缺口在 KGI legacy persistence / repository adoption，不在 canonical type 本身。
- `/api/market/intraday/{stock_id}` 在 cache miss 時也能執行 NStock / Yahoo fetch + commit，不只 history route。
- `/api/market/indices/{index_id}/intraday` 預設 `prefer_live`，是另一個 GET provider-IO surface。
- quote-depth GET 預設 refresh，前端 polling 傳入 `refresh=true`，是另一個 GET mutation surface。
- `MarketIntradayBar` 只存 provider/source/source URL，沒有 SourceRegistry / RawFetchResult foreign key；且現有 upsert identity 需要另行驗證 NStock row 是否被固定 provider label 污染。
- 最低可執行 shared quality gate 應在 KGI production cutover 前完成，而非等所有 onboarding 後才補。

### Worktree 保護

- 本次只新增 `docs/agent-runs/tw-shared-data-core-convergence-20260826/`。
- 未修改 `backend/`、`frontend/`、DB、runtime 或既有 task artifacts。
- 未 stage、commit、push、stash、reset、rebase 或 clean。

### 本次驗證

- 6 個新檔均以 strict UTF-8 成功讀回，無 BOM、無 trailing whitespace，且以 newline 結尾。
- Markdown code fences 數量平衡。
- `architecture-audit-evidence.json` 已成功解析，Job ID 與 production-code-changed flag 正確。
- 新檔逐一執行 no-index whitespace check，沒有 whitespace error。
- repo `git diff --check` exit code 0；只有 dirty worktree 既存檔案的 LF / CRLF 提示。
- 依 docs-only Tier 0 驗證預算，未執行 backend tests、build、lint、typecheck、runtime smoke 或外部 provider IO。

### 尚未驗證

- KGI runtime entitlement、login、quote/depth/auction live payload 與 provider health。
- Regular / Closing Auction / symbol switch / duplicate trade / cumulative volume / L5 / cleanup 的 M5 live-session gate。
- 現行 runtime 是否已載入 dirty source。
- DB 內實際 KGI rows 的 lineage completeness、orphan lease 或 current provider sample。
- API / AI / MCP / frontend cross-surface resolved truth runtime parity。
- 後續 production code 的 targeted tests、backend profile、frontend lint/typecheck/build 與 UI proof。

### 下一步

若使用者核准開始實作，先做 Phase 1 的最小 vertical slice：central eligibility seam + Gateway depth/auction typed wiring與 targeted tests；該段通過後再接 KGI persistence，不直接跨到 router cutover。

## 2026-08-26 — 長專案規劃 checkpoint

狀態：program plan已建立；production implementation尚未開始。

### 已完成

- 將architecture audit擴成24個可追蹤work packages，其中BASE-01/02完成、TAIL-03 deferred、其餘未開始。
- 建立G0-G6累進gates、dependency map、stop-and-fix與rollback model。
- 為Shared Quality、KGI、Intraday Bars、Current Index/Breadth、P2 seams與cross-surface分別定義acceptance。
- 建立ValidationStrategy、RiskRegister、DecisionLog與ExecutionBoard。
- 鎖定第一個可執行slice為CORE-01；Gateway / Resolver production integration留到CORE-02。

### 關鍵決策

- 最低shared quality gate先於KGI production cutover。
- authority比較必須有明確policy；canonical lineage採additive explicit requirement。
- viewer heartbeat與research lease共用primitives但不混為同一lifecycle。
- explicit refresh surface先於GET cache-only cutover。
- P2本輪只封seam與anti-debt guard，不做長尾Big Bang。

### 尚未開始／驗證

- 所有production work packages CORE-01到CLOSE-01。
- backend/frontend tests、migration rehearsal、runtime adoption與live-session acceptance。

### Planning validation evidence

- 24個package在index、詳細章節、ExecutionBoard與JSON baseline的ID集合一致，無重複。
- `project-plan-baseline.json`的package count與文件一致。
- ValidationStrategy引用的25個targeted backend test files全部存在。
- 12個task files以strict UTF-8成功讀回；JSON、Markdown fences、newline與trailing whitespace檢查通過。
- 新檔no-index whitespace check與repo `git diff --check`均無whitespace error；32則輸出皆為既有dirty worktree的LF/CRLF warning。
- 依docs-only Tier 0，本輪沒有執行backend/frontend tests、build、runtime smoke、migration或provider IO。

### 下一步

開始CORE-01：pure central quality evaluator與targeted contract tests，不修改Gateway、Resolver、KGI或TW production path。

## 2026-08-26 — CORE-01 source complete

### 變更

- 新增pure `quality_policy.py`，沒有provider、DB、network、transaction或TW-specific imports。
- `QualityRequirement`新增向後相容的`require_canonical_lineage`，required field paths具normalized/unique validation。
- evaluator輸出stable eligibility、reason codes、missing fields、missing lineage、facts/research usability與limitations。
- authority採explicit rank；request與quality required fields採ordered union。

### 驗證

- 初層contract + quality：21 passed。
- 完整V1 shared regression：70 passed。
- 兩次均通過backend compileall與`git diff --check`。
- evidence logs：`.tmp/validation/20260826-115044`、`.tmp/validation/20260826-115102`。

### 狀態

- CORE-01：`SOURCE_COMPLETE`。
- Runtime adoption / live：不適用，evaluator尚未production-wired。
- 下一步：CORE-02 Gateway / Resolver eligibility integration。

## 2026-08-26 — CORE-02 source complete

### 變更

- Gateway把bars、quote、market breadth與market index requirements傳入shared Resolver quality seam。
- Resolver在既有ranking前執行pure quality evaluation，將stable rejection reason、missing fields與limitations投影到resolved health與candidate summaries。
- bar series會逐bar評估required fields與canonical lineage，再合併成series-level eligibility；非最新bar不重複套freshness age。
- completed official breadth明示`allow_partial=True`，保留unknown / missing truthful partial facts，同時維持`research_usable=False`。
- SQLite raw receipt fixtures改用UTC wall-clock，避免測試offset被SQLite移除後形成假future timestamp。

### 驗證

- CORE-02 first targeted：41 passed。
- V1 + TW platform regression：119 passed。
- backend compileall與`git diff --check`通過。
- evidence logs：`.tmp/validation/20260826-120246`；前兩次失敗證據保留於`.tmp/validation/20260826-120108`、`120206`、`120226`。

### 狀態

- CORE-02：`SOURCE_COMPLETE`。
- Runtime adoption / live：`PENDING`，未重啟或採樣現行runtime。
- 下一步：CORE-03 depth / auction typed Gateway wiring。

## 2026-08-26 — CORE-03 source complete

### 變更

- Shared Gateway新增Depth/Auction CandidateBatch、Reader、AcquisitionResult、AcquisitionPort與TransactionPort。
- 新增`resolve_depth()`與`resolve_auction()` application wiring；兩者共用shared planner、bounds validation、explicit transaction與mandatory repository reread。
- depth / auction分別回傳typed `ResolvedDepth` / `ResolvedAuction`，trial/indicative observation不會轉成quote。
- Shared Planner修正subscription-only budget：只有external call與subscription bounds都為0才回報`ACQUISITION_BUDGET_ZERO`。
- raw receipt budget同時受external work與subscription bounds約束。

### 驗證

- CORE-03 targeted：66 passed；depth/auction補充subset：30 passed。
- V1 + TW platform regression：126 passed。
- backend compileall與`git diff --check`通過。
- evidence logs：`.tmp/validation/20260826-121011`。

### 狀態

- CORE-03：`SOURCE_COMPLETE`，G1完成。
- Runtime adoption / live：`PENDING`。
- 下一步：KGI-01 market-owned KGI/MIS descriptors與acquisition seam。

## 2026-08-26 — KGI-01 source complete

### 變更

- 建立market-owned TW realtime descriptor catalog，分開quote snapshot、order book與auction resource/session/authority/bounds/limitations。
- KGI resources宣告為broker authority、single-symbol bounded subscription；MIS depth/auction宣告為exchange authority、single-symbol bounded fetch。
- 新增KGI realtime acquisition adapter：透過injected provider snapshot reader取得已bounded snapshot，沿用`kgi_canonical.py`，產typed quote/depth/auction與SHA-256 raw receipt。
- canonical lineage補`received_at`、`fetched_at`、raw contract version與content hash；adapter沒有DB、transaction或lease ownership。
- shared generic core維持無KGI/MIS名稱。

### 驗證

- adapter / descriptor / canonical targeted：50 passed。
- V2 KGI + lease + boundary regression：154 passed。
- backend compileall與`git diff --check`通過。
- evidence logs：`.tmp/validation/20260826-121529`。

### 狀態

- KGI-01：`SOURCE_COMPLETE`，production-unwired。
- Runtime entitlement / live session：`PENDING`。
- 下一步：KGI-02 multi-provider quote persistence / repository。

## 2026-08-26 — KGI-02 source complete

### 變更

- public quote transaction改由market-owned realtime source bindings驗證provider/source/resource/parser；MIS與KGI皆可合法持久化，forged identity fail closed。
- SourceRegistry defaults由descriptor authority/priority與binding metadata產生；provider adapter仍不commit。
- repository bounded讀取每個合法provider的latest candidate，不再hard-filter MIS；authority與priority直接取descriptor。
- public quote requirement啟用canonical lineage quality gate，candidate reader支援multi-provider health/candidates。
- platform acquisition支援injected descriptor catalog與對應bounded fetch/subscription budget；production default仍維持MIS-only。

### 驗證

- KGI raw receipt→transaction→repository reread、KGI/MIS deterministic、minimum exchange authority與forged identity tests：23 passed（含既有platform regression）。
- V2 quote/KGI/boundary regression：128 passed。
- backend compileall與`git diff --check`通過。
- evidence logs：`.tmp/validation/20260826-122232`。

### 狀態

- KGI-02：`SOURCE_COMPLETE`，KGI quote為opt-in injected path，尚未default cutover。
- Runtime / live：`PENDING`。
- 下一步：KGI-03 depth / auction typed persistence / repository。

## 2026-08-26 — KGI-03 source complete

### 變更

- 新增depth snapshot、normalized depth level與auction snapshot三張typed tables及additive 0069 migration；未重用legacy quote depth JSON。
- depth / auction transaction owner原子持久化SourceRegistry、RawFetchResult與canonical observation；任何lineage mismatch會rollback。
- repository依provider/source/parser/raw ID/content hash fail closed重建canonical lineage，且persist成功後由Gateway mandatory reread再resolve。
- market-owned Taiwan realtime platform提供cache-only read與injected bounded acquisition，runtime provider health以typed input交給shared planner。
- trial auction維持indicative/provisional，與quote/depth各自獨立storage與result kind。

### 驗證

- KGI-03 targeted與disposable migration：4 passed。
- V2 Gateway / quality / quote / KGI / lease / boundary regression：163 passed，69個既有Python 3.12 SQLite adapter deprecation warnings。
- backend compileall與`git diff --check`通過；evidence log：`.tmp/validation/20260826-123511`。
- migration只對disposable `.tmp` DB執行upgrade / downgrade / re-upgrade，未觸及user DB。

### 狀態

- KGI-03：`SOURCE_COMPLETE`；O-003 resolved為dedicated typed tables。
- Runtime adoption / KGI entitlement / live session：`PENDING`。
- 下一步：KGI-04 provider-neutral viewer lease platform。

## 2026-08-26 — KGI-04 source complete / KGI-05 in progress

### KGI-04變更

- 在既有`research_lease.py`擴充persistent viewer coordinator，沒有新增第三套provider-specific lease framework。
- public owner token與provider handle分離；heartbeat/release只透過coordinator binding尋址provider port。
- descriptor planner負責subscription route與health eligibility；disabled/unfillable不啟動port。
- identity mismatch、無效owner token與release cleanup都有fail-closed測試；summary保留既有public shape。
- router acquire / heartbeat / release / summary已改走market-owned lease platform。

### KGI-04驗證

- V2 Gateway / quote / lease / control plane / API inventory / boundary：179 passed，69個SQLite adapter deprecation warnings。
- backend compileall與`git diff --check`通過；evidence log：`.tmp/validation/20260826-124329`。

### KGI-05目前進度

- router已完全移除KGI provider import；realtime stream改走descriptor-selected cache-only market projection port。
- lease live heartbeat可在POST/PATCH lifecycle中嘗試KGI quote/depth/auction canonical sync；GET不啟動subscription。
- `get_taiwan_stock_quote_depth`已改為Shared Core quote/depth/auction cache-only compatibility projection；即使傳入legacy `refresh=true`也不IO、不commit。
- 新Shared projection / stream / lease regressions：88 passed + 60 subtests。
- 既有`test_taiwan_stock_quote_depth.py`仍有15個測試把GET provider IO、fallback與DB mutation視為正確行為；這些測試已確認與新invariant衝突，尚未改寫，故KGI-05不標complete。

### 狀態

- KGI-04：`SOURCE_COMPLETE`；runtime / live仍`PENDING`。
- KGI-05：`IN_PROGRESS`；下一步是用explicit acquisition fixtures取代15個legacy GET-mutation assertions，並移除quote_depth dead provider-owner helpers。

## 2026-08-26 — KGI-05 source complete / BAR-01 started

### KGI-05變更

- 新增pure TWSE MIS realtime adapter；一次bounded fetch產生quote、typed depth與auction candidates，各capability以獨立RawFetchResult持久化並mandatory reread。
- quote-depth GET固定為cache-only compatibility projection；legacy `refresh`輸入不再觸發provider IO、subscription或commit，refresh移至additive explicit POST。
- Shared Core depth/auction投影會在resolved typed components套用後重算preopen、regular與closing語意，並保留各component event time。
- current-session MIS/KGI snapshot不再於13:33後自動升格成completed official close；official completed-session仍由既有official platform擁有。
- legacy quote-depth tests改成explicit acquisition後再cache-only read，canonical source fields取代provider-specific field guessing。
- OpenAPI inventory加入`POST /api/market/quote-depth/{stock_id}/refresh`；router不再direct import KGI manager，stream與lease皆經market-owned provider-neutral platform。

### KGI-05驗證

- legacy compatibility suite：21 passed + 10 subtests。
- 首次V2整合：184 passed / 1 failed；失敗為新增POST後inventory count仍為407，證據保留`.tmp/validation/20260826-130258`。
- 修正inventory後同一V2組合：185 passed；backend compileall與`git diff --check`通過。
- final evidence log：`.tmp/validation/20260826-130337`。

### 狀態

- KGI-05：`SOURCE_COMPLETE`；KGI P0 source cutover完成。
- provider entitlement、running backend adoption與Preopen/Opening/Regular/Closing live gates：`PENDING`，未用fixtures冒充live evidence。
- `quote_depth.py`仍保留fixed-slot capture/replay與不可達legacy helper，後續CLOSE-01只做有guard的debt清理；public GET owner已是thin cache-only projection。
- 下一步：BAR-01，先重讀`intraday.py`現有dirty hunk與owner map，再建立NStock/Yahoo pure adapter + descriptor vertical slice。

## 2026-08-26 — BAR-01～BAR-04 source complete / IDX-01 started

### Intraday Bars變更

- 新增market-owned NStock / Yahoo intraday descriptors、pure adapters與descriptor-route acquisition executor；`intraday.py`不再擁有provider URL、fallback或HTTP。
- 新增`MarketIntradayBarLineage` typed one-to-one lineage table與additive 0070 migration；transaction owner原子寫入SourceRegistry、RawFetchResult、bar與lineage，成功後Gateway mandatory reread。
- repository只接受合法provider/source/parser/content hash/authority identity；4h local aggregation保留1h source interval、calculation version與component raw IDs。
- history / trend GET固定cache-only，即使legacy query傳`refresh=true`也不IO、不commit；新增bounded explicit `POST /api/market/intraday/{stock_id}/history/refresh`。
- frontend professional history與quote-depth polling不再把GET當refresh command；outward schema補resolved health、candidate rejections、limitations與raw/derived lineage欄位。
- `tw.intraday.bars` lifecycle升為platform-owned derived-component-lineage dataset，refresh operation與bounds同步到market catalog / shared registry。

### Intraday Bars驗證

- focused catalog / platform / migration / API：46 passed + 60 subtests。
- V3 intraday / contract / quote / cold-read / registry組合首輪：154 passed / 1 failed；central quality正確拒絕測試fixture的future fetched timestamp。
- 修正fixture clock為同一pre-close時間線後，cold-read：1 passed；production future-timestamp gate未放寬。
- backend compileall與BAR-scoped `git diff --check`通過；evidence：`artifacts/wp-bar-01-04-source-20260826.json`。

### 狀態

- BAR-01～BAR-04：`SOURCE_COMPLETE`。
- provider live IO、running runtime adoption與user DB migration：`PENDING`。
- 下一步：IDX-01，先確認`indices.py` current-session index owner map並保護completed official path。

## 2026-08-26 — IDX-01／BRD-01／IDX-02 source complete

### Current index / breadth變更

- Shared Gateway新增current index/breadth acquisition與transaction wiring；market-owned descriptors分開`market.index.snapshot`、`market.breadth.current`及TAIEX/TPEX scope。
- 新增typed current index/breadth tables與0071 additive migration；raw receipt、source identity、event/received/fetched time、parser version與content hash完整持久化。
- candidate transaction成功後mandatory repository reread，再經central quality與existing Resolver；completed official datasets保持獨立。
- breadth canonical/projection保留universe、classified、unknown、not_received、received_unclassified、coverage、provisional、decision usability及limitations；missing不轉0。
- index summary與intraday GET固定cache-only；explicit POST refresh才執行descriptor-planned acquisition。
- public current summary不再執行`indices.py`的cross-provider fallback chain；legacy provider-specific fetch/parser helpers暫留給compatibility adapter與其他舊surface。

### 驗證

- 0071 migration upgrade / downgrade / re-upgrade與typed schema：pass。
- current platform、GET zero IO/commit、completed official regression、unknown/coverage與TAIEX/TPEX semantics：納入final targeted 474 tests。

## 2026-08-26 — TAIL-01～TAIL-03 source complete

### P2 seams變更

- 新增market-owned company profile cache reader/projection；AI Taiwan context改用injected reader port，不再direct query `StockProfile`。
- minute state與stock intraday state新增component raw IDs、sources、event times、time skew、calculation version與lineage completeness；0072 additive migration已在disposable DB驗證。
- current breadth raw receipt保存bounded component stock rows，derived stock rows才能truthfully引用相同receipt；legacy缺component lineage時fail closed且不可decision-ready。
- catalog改為9 platform-owned、7 compatibility、12 lineage-gap、2 compatibility-derived；derived兩項雖有lineage仍保留compatibility owner狀態。
- 新增`MigrationOrder.md`，依chips/fundamentals、profile/events、ETF、futures/derivatives排定後續owner與anti-debt gates。

## 2026-08-26 — CROSS-01 source complete / closeout recheck

### Boundary closeout

- router的realtime lease/stream已是provider-neutral，並移除對legacy`app.market.kgi_market_data`的direct import；explicit KGI maintenance route經market-owned operation seam。
- quote-depth public owner固定cache-only Shared Core projection；同檔仍有fixed-slot capture/replay與不可達legacy provider helpers，列為physical cleanup debt。
- intraday public service不再持有NStock/Yahoo URL、fallback或transaction；current summary public path不再持有cross-provider selection。
- shared core source guard確認沒有KGI/MIS/Yahoo/NStock provider import；AI/MCP/frontend不重建central quality或provider priority。

### 最終比例驗證

- task-owned backend integration：474 passed、21 subtests passed、276個既有Python 3.12 SQLite adapter deprecation warnings；耗時50.34秒。
- KGI router/boundary focused：57 passed。
- frontend safe validation：lint passed、tsc passed；sandbox build在compile後遇`spawn EPERM`，以既有核准的`npm run build`於sandbox外重跑後完整通過6 pages。log：`.tmp/validation/20260826-140933`。
- `git diff --check` exit 0；只有LF/CRLF warnings，沒有whitespace error。
- full backend safe profile已完成compileall與Taiwan suites，但整體不是green：2個`test_us_ohlc_contract.py` failures來自並行US OHLC dirty work；`test_runtime_launcher_recovery.py`有pytest temp directory PermissionError。log：`.tmp/validation/20260826-141045`。
- 額外手動全backend（排除上述兩檔）在240秒、83%時timeout，期間5個failure未能在summary展開；此命令不列為pass，source acceptance以明確task-owned 474-test集合為準。

### 目前狀態

- G0-G3：`SOURCE_COMPLETE`。
- ADOPT-01 / G4：`PENDING`。未重啟named OMI runtime、未確認launcher-selected endpoint/interpreter、未對user DB執行0069-0072。
- LIVE-01 / G5：`PENDING`。KGI entitlement與Preopen/Opening/Regular/Closing Auction、symbol switch、L5、duplicate/trial/cumulative/cleanup皆沒有official-session evidence。
- CLOSE-01 / G6：`IN_PROGRESS`。runtime/live與legacy helper physical cleanup未完成，不能宣稱整個program fully closed。

### Worktree保護

- 未commit、push、publish、stage、stash、reset、rebase或clean。
- 未改動secret、未執行provider refresh、未重啟runtime、未寫入user DB。
- US/scheduler/frontend既有並行hunks保留；未為修正US full-suite failures擴大本輪scope。

## 2026-08-26 — Pre-commit remediation planning checkpoint

### Read-only audit evidence

- Legacy current breadth production shape可重現partition double-count：acquisition failed、canonical observation missing、resolved status missing。
- Stream response直接來自KGI manager記憶體snapshot，沒有raw receipt/transaction/reread/central quality/Resolver；目前AI/MCP無caller，但frontend live depth會優先顯示stream。
- Current index/breadth production refresh仍經`tw_current_market_legacy_bridge.py`呼叫`indices.py` provider helpers。
- TW intraday descriptor/requirement使用`market.intraday.bars`，registry/catalog/AI使用`intraday.bars`，無formal alias。
- `quote_depth.py`的legacy acquisition/shadow/quote upsert functions為test-only/dead；capture/replay仍有scheduler/router production caller。
- cp0 allowlist仍含已消失router imports；另有specific guard但generic baseline不等於current actual。
- current breadth universe為active StockMaster stock registry且`official_full_market=false`，catalog full-market宣告不精確。
- read-only user DB revision為0068；source head為0072；Git index為空。

### Plan output

- 新增`PreCommitRemediationPlan.md`，定義REM-00～REM-07、依賴、acceptance、targeted validation、stop/rollback與runtime boundary。
- 新增`precommit-remediation-baseline-20260826.json`。
- program狀態調整為`PRECOMMIT_REMEDIATION_PLANNED_AWAITING_APPROVAL`；尚未開始production修改。

### Validation evidence

- pre-commit audit targeted subset：56 passed。
- 本planning checkpoint依Tier 0只執行文件UTF-8/JSON/Markdown與diff checks；不跑backend/frontend build或runtime smoke。

### Next step

等待使用者確認plan；獲准後從REM-00/REM-01開始，不先處理runtime、migration或commit。

## 2026-08-26 — Pre-commit remediation source complete

### REM-01～REM-04

- 修正legacy breadth aggregate unknown/missing轉換：`received_unclassified=max(unknown-missing, 0)`，partition不再double count；partial evidence維持`decision_usable=false`。
- current breadth scope明示`full_market_registered_stock_universe`與`official_full_market=false`，unknown與not-received皆保留。
- intraday capability ID統一為`intraday.bars`；descriptor、requirement、registry與catalog有exact contract guard。
- realtime stream強制`presentation_only`、非canonical、非decision/research usable；frontend只作telemetry display並動態顯示provider。
- AI/MCP/decision source guard禁止依賴stream platform、KGI realtime lease port與raw stream payload。
- cp0 consumer/provider import allowlist縮為current actual空集合，generic guard改成exact match。

### REM-05～REM-06

- 新增TWSE MIS current index、Yahoo current index、TWSE MIS current breadth provider modules；URL、HTTP、parsing與provider error/circuit ownership離開`indices.py`。
- StockMaster universe query留在market-owned operation layer；provider adapter不query DB、不commit。
- production current refresh不再經legacy bridge；shared descriptors/planner、typed transaction、mandatory reread與Resolver保持不變。
- `quote_depth.py`移除provider fetch、fallback、circuit、direct quote persistence、commit/rollback與shadow owner。
- fixed-slot capture/replay搬到`quote_contract_capture.py`；capture先走explicit Shared Core refresh，再cache-only projection與獨立transaction。

### 驗證

- current provider extraction與completed official regression：95 passed。
- Shared Core、quality、KGI、intraday、current market、boundary整合集合：234 passed、60 subtests；dark checkpoint guard的歷史假設已更新並全綠。
- AI/MCP/realtime/quote capture/boundary：174 passed、65 subtests。
- frontend targeted ESLint、`tsc --noEmit`與Next.js production build：全部通過。
- provider/current breadth compileall：通過。
- final architecture focus：39 passed；七項forbidden source inventory全部為0。
- task docs UTF-8與checkpoint/debt JSON讀回通過；`git diff --check`只有line-ending warnings、無whitespace error；Git index為空。
- pytest僅有Python 3.12 SQLite adapter deprecation與sandbox無法建立`.pytest_cache`警告；不是task-owned test failure。

### 狀態與未驗證

- REM-00～REM-07：`SOURCE_COMPLETE`。
- Git index維持空；未commit、push、publish、migration、restart、provider refresh或subscription。
- ADOPT-01 / G4：`PENDING`；user DB仍未由本輪套用0069～0072，running OMI未adopt新source。
- LIVE-01 / G5：`PENDING`；KGI entitlement、Preopen/Opening/Regular/Closing、symbol switch、L5、duplicate/trial/cumulative/cleanup仍需合法session證據。
- CLOSE-01 / G6：`IN_PROGRESS`；source physical closure已完成，但不得在G4/G5前宣稱production fully converged。

## 2026-08-26 — Production adoption checkpoint

- ADOPT-01 / G4：`PASSED`。M5 SourceOnly以base、M5、Data Core convergence與本任務`precommit-remediation-source-checkpoint.json`四層validated precedence驗證，19個本任務targets零mismatch；effective acceptance targets=35。
- 16:29只透過既有正式launcher owner執行component-scoped `RestartServices`；新backend listener 54792以repo venv／project root啟動，selected endpoint=`127.0.0.1:8400`，effective mode=`compare`，health／ready、frontend proxy、stdio MCP與zero-lease baseline通過。
- Startup migration log依序套用0069～0072；read-only Alembic query確認user DB revision=`20260826_0072`。Data Core runtime catalog回傳30 datasets／21 operations。
- 120秒stable soak後的KGI readiness在`post_close`由common planner fail closed為`VIEWER_LEASE_PLAN_UNFILLABLE`；沒有建立lease或bridge，global baseline仍為0。此結果只表示當下session不可建立subscription，不是G5 pass或credential failure。
- LIVE-01 / G5：`PENDING`。Automation實際在16:20 Asia/Taipei觸發，當日四個正式session gate已過；新source identity仍需2026-08-27 Preopen／Opening／Regular／Closing、symbol switch、L5、trial/cumulative與cleanup artifacts。
- CLOSE-01 / G6：`IN_PROGRESS`。在G5完成前保持`compare`，不得提前rollback或宣稱fully accepted。
