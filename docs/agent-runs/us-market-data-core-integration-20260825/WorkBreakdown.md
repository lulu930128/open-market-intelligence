# US Market Data Long Project Work Breakdown

## 1. Program model

本專案以work package作為最小可交付單位。每個package都必須具備：

- 明確owner boundary與檔案範圍。
- 可重現baseline。
- acceptance criteria。
- targeted validation與evidence location。
- rollback／stop condition。
- `Progress.md`與`AcceptanceMatrix.md`狀態更新。

不以日期或「程式已寫」判定完成。狀態只使用：

- `planned`
- `in_progress`
- `blocked`
- `implemented_unverified`
- `passed`
- `rolled_back`

## 2. Dependency graph

```text
A0 Baseline
 ├─> A1 Boundary Guard
 ├─> A2 Legacy Quarantine
 └─> A3 US Package / Candidate Seam
             |
             v
     G0 Shared Core Handoff
             |
             v
     B1 US Core Binding / Ports
       ├─> B2 Daily Read Cutover
       │      └─> C1 Refresh Operation Binding
       │              └─> C2 Repair / Scheduler Cutover
       └─> D1 Quote / Intraday Cutover
              └─> D2 Lease / Session Acceptance

B2 + C2 + D2
       |
       v
E1 API  -> E2 AI/MCP -> E3 Frontend/Research
       |
       v
F1 Shadow/Compare -> F2 Canary/On -> F3 Legacy Removal/Closure
```

A0–A3可在台股Core完成前執行。G0未通過時，B1–F3全部維持`blocked`。

## 3. Workstreams

| Stream | Scope | Primary modules | Exit evidence |
| --- | --- | --- | --- |
| WS-A Governance/Boundary | baseline、AST/import guard、legacy quarantine | tests、router/AI/frontend inventories、config | no new provider leakage |
| WS-B Provider/Core | descriptors、adapters、ports、bindings、candidate store | `app.us_market`、`app.market_data` public seam | fake-port E2E + coherent candidates |
| WS-C Dataset Lifecycle | daily/repair/coverage/scheduler | registry、jobs、EOD coverage、US continuity | bounded refresh + postcondition |
| WS-D Realtime | quote/intraday/session/lease | US provider ports、calendar、resolved projections | session-aware live/fallback evidence |
| WS-E Consumers/Research | API、AI/MCP、Frontend、technical authority | routers、AI、research、frontend | provider-neutral parity |
| WS-F Rollout/Closure | telemetry、runtime adoption、rollback、legacy removal | rollout modes、launcher/runtime、docs | production graph + rollback proof |

## 4. Track A — Shared Core完成前

### A0 — Baseline與變更隔離

- Status：`passed`；evidence=`artifacts/A0Baseline.md`。
- Dependencies：none。
- Scope：branch／HEAD／dirty status、相關call graph、public contract snapshot、runtime adoption status；建立exact-scope檔案清單。
- Deliverables：
  - baseline artifact，記錄tracked/untracked ownership與交疊檔案。
  - product consumer、diagnostic、legacy seam、provider adapter分類清單。
  - 現行daily/intraday/repair/API/AI/frontend fixtures或contract snapshot。
- Acceptance：
  - 能區分台股Core、美股OHLCV、M5與本任務變更，不revert他人工作。
  - 所有後續package都有可比較的legacy output與source inventory。
- Validation：`git status --short`、`git diff --name-only`、`rg` caller inventory、targeted fixture tests。
- Stop：無法判定檔案ownership或同檔同區塊被其他任務持續修改時，先協調，不進source edit。

### A1 — Consumer Boundary Guard

- Status：`passed`；evidence=`test_us_market_data_architecture_boundaries.py`。
- Dependencies：A0。
- Scope：新增`test_us_market_data_architecture_boundaries.py`或等價AST/import guard；建立具名legacy allowlist。
- Deliverables：
  - 阻止Frontend、AI、public product router、scheduler、research新增provider control。
  - 允許adapter、fixture、diagnostic/admin與具名legacy seam。
  - allowlist debt能隨cutover逐項縮小。
- Acceptance：新增`provider="yahoo_chart"`、`provider="alphavantage"`、service-local`try provider A then B`會fail test。
- Validation：boundary test、API inventory、AI tool boundary tests、frontend source scan。
- Rollback：只移除本package新增guard；不改production behavior。

### A2 — Legacy expansion quarantine

- Status：`passed`；priority workflow external calls=0，source default off。
- Dependencies：A0、A1。
- Scope：OHLC continuity／priority repair與scheduler；只隔離新provider-specific acquisition，不重寫既有production service。
- Deliverables：
  - pure expected-date、coverage、missing-session、postcondition維持market-owned。
  - priority scheduler未接Core前default off／fail closed。
  - product refresh intent不帶provider；legacy provider execution集中到具名compatibility seam。
- Acceptance：startup不會因source default自動擴張Yahoo refresh；continuity tests仍通過；無新consumer leakage。
- Validation：US OHLC continuity/contract/priority + EOD scheduler targeted tests；config/source scan。
- Stop：若修改會改變現有local data或啟動external calls，先取得授權並拆成獨立package。

### A3 — US package與candidate seam

- Status：`passed`；production binding仍明確disabled並等待G0。
- Dependencies：A0、A1。
- Scope：整理market-owned descriptors、pure adapters、candidate repository interface、stable projection與legacy compatibility；不建立猜測版Core binding。
- Planned modules：
  - `app.us_market.market_data.descriptors`
  - `app.us_market.market_data.adapters.*`
  - `app.us_market.market_data.candidate_store`
  - `app.us_market.market_data.projection`
  - `app.us_market.market_data.integration_manifest`
  - `app.us_market.market_data.legacy_compat`
- Deliverables：Yahoo／AlphaVantage fixture adapters、provider-coherent legacy persistence inventory與read seam、compatibility quarantine；final canonical write contract等待G0。
- Acceptance：
  - Adapter無fallback、DB transaction與outward projection。
  - Candidate store不做selection；保留legacy store已有provider/fetched/source/hash facts；legacy未存event/finalization/price-basis時以explicit limitations揭露，不推測或補零。
  - Production imports與behavior不因package整理改變。
- Validation：compile/import、canonical fixture、transaction、DB contention、projection snapshot tests。
- Stop：若final Core storage contract尚未定義的欄位會迫使migration，先記錄gap，不預先改schema。

## 5. G0 — Shared Core handoff

- Dependencies：A0；建議A1–A3已passed。
- Owner：Shared Market Data Core／台股umbrella task交付，US task驗收。
- Input：`CoreHandoffChecklist.md`要求的code、tests、AcceptanceMatrix、runtime與actual-data packet。
- Acceptance：
  - 台股task正式標記`TW_MARKET_DATA_PLATFORM_PRODUCTION_CONVERGED`。
  - 台股`AcceptanceMatrix.md` B–G required rows全部`passed`且無`blocked`。
  - Core public seam、version與compatibility policy已定版。
  - US使用fake port完成compile-only contract proof，且無`app.market`依賴。
- Output：G0 evidence artifact與`Progress.md`明確`passed`／`blocked`。
- Stop：任何critical item缺失、僅source-complete、僅dark/shadow或runtime identity不明，一律不解鎖B1。

## 6. Track B — Core integration與daily vertical slice

### B1 — US bindings與provider ports

- Dependencies：G0 passed、A3 passed。
- Scope：依final Core interface註冊US descriptors、ports、candidate repository、calendar/session policy與projection callback。
- Deliverables：US binding module、Yahoo/AlphaVantage ports、fake-port integration fixtures、registration tests。
- Acceptance：
  - `DataRequirementV2 -> Gateway -> AcquisitionPlan -> US port -> candidates -> Resolver -> MarketDataResultV1 -> US projection`完整通過。
  - Core擁有fallback；US binding/adapter沒有Yahoo→AlphaVantage chain。
  - timeout、rate-limit、auth、plan restriction、no port、both unavailable皆truthful。
- Validation：Core gateway/control/resolver tests + US provider policy/canonical/projection tests。
- Rollback：binding保持unregistered／mode off，legacy production path不變。

### B2 — Daily OHLCV resolved read cutover

- Dependencies：B1。
- Scope：single-symbol daily read、chart、research、watchlist ranking、Radar使用同一resolved bar series與US stable projection。
- Deliverables：provider-neutral daily read service、compatibility projection、compare telemetry、query batching。
- Acceptance：
  - `cache_only` external port call count = 0。
  - requested bars/date、completed-only、raw price basis、early close、stale/partial/missing/provider conflict語意一致。
  - Chart/Research/Ranking/Radar selected lineage一致；500-symbol上限與bounded query不退化。
- Validation：resolved read/research/watchlist/API tests + bounded 376/500-symbol performance smoke。
- Rollback：per-capability mode回off；不刪candidate rows、不回滾DB。

## 7. Track C — Dataset lifecycle與repair

### C1 — Dataset operation bindings

- Dependencies：B1、B2。
- Scope：註冊`us.daily.ohlcv`、priority research、full-market lifecycle；連接expected state、eligibility、bounds、cursor、postcondition與transaction owner。
- Deliverables：RefreshRequirement mapping、operation handlers、result summaries、post-write reread。
- Acceptance：operation name一定有可執行binding；success必須通過coverage postcondition；provider success但coverage不足回partial。
- Validation：registry consistency、continuity、transaction、coverage checkpoint tests。
- Stop：operation dispatcher若要求scheduler選provider，回Core contract處理，不在US job補fallback。

### C2 — Repair／scheduler cutover

- Dependencies：C1。
- Scope：single-symbol repair、priority universe、full-market shards、job dedupe/retry/cursor、Frontend refresh intent。
- Deliverables：provider-neutral jobs/scheduler/API、bounded budgets、resume/catch-up semantics。
- Acceptance：
  - Scheduler只知道dataset ID、target、budget、cursor、postcondition。
  - 無界refresh、重複job、quota overrun fail closed/dedupe。
  - Shared `eod_coverage`不再direct import US service或hardcodeYahoo。
- Validation：registry、job retry/dedupe、EOD coverage、DB contention、安全bounded smoke。
- Rollback：disable operation binding/schedule；保留coverage checkpoint與已持久化candidate。

## 8. Track D — Quote、intraday與lease

### D1 — Quote／intraday resolved path

- Dependencies：B1；Daily不必完全on，但Core/result semantics須穩定。
- Scope：Yahoo quote/intraday port、Canonical quote/bars、resolved projection；KGI US僅在另行readiness通過後加入。
- Deliverables：provider-neutral quote/intraday data path與last-good candidate policy。
- Acceptance：1m/5m/15m/30m/1h/4h、premarket/regular/after-hours、partial bar、unknown volume、previous close與source lineage一致。
- Validation：intraday aggregation、canonical、realtime contract、API/AI fixtures。
- Rollback：quote/intraday各自回off，不影響daily path。

### D2 — Lease／session／live acceptance

- Dependencies：D1。
- Scope：viewer/research/collector lease、timeout/cancel/release、closed/completed-session behavior、early close。
- Deliverables：bounded lease policies與dated runtime evidence。
- Acceptance：
  - `require_live`未滿足明確policy_unsatisfied。
  - Closed/completed-session不啟動無意義subscription。
  - lease cleanup、ownership、symbol/subscription bound可證明。
- Validation：fault injection、research lease、runtime selected PID/port/mode、US session-window smoke。
- Stop：非可重現session或provider entitlement未知時，不升production on。

## 9. Track E — Consumer與research convergence

### E1 — Stable API cutover

- Dependencies：B2、C2、D1按capability逐項通過。
- Scope：product routes使用requirement semantics；provider-specific audit移到diagnostic/admin surface。
- Acceptance：product request schema不再接受provider control；outward compatibility有deprecation與contract test。
- Validation：OpenAPI/API inventory、normal/partial/fallback/error snapshots。

### E2 — AI／MCP cutover

- Dependencies：E1。
- Scope：AI planner/executor只選capability、policy、bounds；MCP維持thin；Decision v4 projection使用resolved data。
- Acceptance：HTTP/SSE/MCP readiness/freshness/limitations/lineage一致；AI tool沒有provider selection。
- Validation：decision v4、AI tool boundaries、transport parity、MCP schema/tests。

### E3 — Frontend與technical authority convergence

- Dependencies：E1、E2、B2、D1。
- Scope：US detail/chart/ranking/Radar不帶provider；正式technical series由backend shared engine提供；Frontend只render。
- Acceptance：
  - Production source provider selector inventory = 0。
  - 同一canonical OHLCV的EMA/RSI/MACD/KD在API/AI/UI一致。
  - Data Status顯示backend health/freshness/limitations，不自行推理。
- Validation：frontend lint/typecheck/build、golden-series cross-surface tests、必要desktop/mobile browser smoke。
- Rollback：consumer per-capability flag回legacy projection；不得在Frontend新增fallback。

## 10. Track F — Production rollout與closure

### F1 — Shadow／compare

- Dependencies：受影響package targeted tests passed。
- Scope：每capability記錄legacy/new result、lineage、latency、quota、candidate/selection mismatch。
- Acceptance：無額外unbounded provider call；mismatch分類與threshold可解釋；runtime mode identity可驗證。
- Validation：`CutoverRunbook.md` evidence packet、comparison tests與bounded smoke。

### F2 — Canary／on與rollback rehearsal

- Dependencies：F1 passed、相關session/data gate passed。
- Scope：single symbol -> bounded symbol set -> priority universe；daily、repair、intraday分開切。
- Acceptance：canary thresholds內、rollback不需DB destructive change、official launcher/runtime與可見UI都驗證。
- Validation：backend/frontend safe validation、API/data/AI/MCP/UI smoke、rollback rehearsal。

### F3 — Legacy removal與closure

- Dependencies：所有capability on且穩定、rollback evidence存在。
- Scope：移除service fallback、provider selectors、reverse imports、過期allowlist/flags；同步current docs。
- Acceptance：
  - Product graph只有Shared Core truth path。
  - Architecture guard與caller inventory沒有未核准legacy owner。
  - `AcceptanceMatrix.md` required rows全部passed，無blocked。
  - Source-ready、runtime-adopted、provider-live、dataset-ready、consumer-cutover分開陳述。
- Validation：backend/frontend/full safe validation、runtime/API/AI/MCP/UI、docs UTF-8/diff check。

## 11. File ownership與並行規則

- Shared `app.market_data/*` final contract由台股Core task擁有；US task只透過public seam接入。需要修改Core時，先記錄cross-task change request，不在US package內偷偷改contract。
- `app.us_market/*`由US task擁有；authority datasets可與market-data integration分開工作，但不得共享同一批service區塊的未協調修改。
- `jobs/scheduler/registry/eod_coverage`是cross-market高衝突區；同時間只允許一個task寫入，先取得baseline與owner。
- `routers/us_market.py`、AI tool files、`USStockDetailPanel.tsx`依序由E1、E2、E3處理，不在B/C階段順手改consumer。
- DB migration如必要，必須是獨立work package、additive、可讀舊資料並有rollback/backup說明。

## 12. 專案更新節奏

- 開始package：在`Progress.md`記錄package ID、baseline SHA、owned files與預期validation。
- 完成source：標`implemented_unverified`，不可直接標passed。
- 完成validation：把command、exit result、artifact路徑寫入`Progress.md`與`AcceptanceMatrix.md`。
- 發現blocker：標`blocked`，記錄重現條件、owner與解除條件；不跨gate硬做。
- Runtime/cutover：每次只升一個capability與bounded target，保存mode、PID/port、provider calls、mismatch與rollback evidence。
- Closure：所有required rows passed後才更新current architecture docs；歷史任務文件保持task evidence角色。
