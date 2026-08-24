# Plan

## Implementation status

- A0-A7：source、neutral outward、AAPL compare/canary與rollback complete。
- A8：KGI US source readiness與fixture gate complete；live login／entitlement／subscription smoke未授權、未執行，KGI保持unadvertised／unwired。
- A9：正式launcher adoption、HTTP／SSE／MCP／frontend proxy runtime acceptance complete；第二塊可依capability gate開始實作。

## Program relationship

- 本工作流是兩塊計畫的第一塊，擁有 US provider → Canonical → Resolution／Control → truthful outward 的責任。
- 第二塊 docs/agent-runs/us-first-class-research-consumer-20260823/ 只能在本工作流對應 capability達到 acceptance gate 後啟用 US production projection。
- 第二塊的純技術演算法抽離可平行進行，但不得用 legacy provider結果宣稱 canonical US research cutover。

## Milestones

### A0 — Baseline、ownership 與 stop-ship truth gate

- Scope：
  - 保存 branch／HEAD、target-file status、dirty hunks、Foundation mode、DB schema head與 runtime presence。
  - 建立 US capability × target × market × dataset × projector × provider contract matrix。
  - 把 market.breadth 的 US scope leak 固定成 regression test。
- Acceptance：
  - 所有預定修改檔都有 ownership與既有 dirty hunk說明。
  - 明確列出 source-complete、runtime-adopted、provider-live與consumer-cutover四種狀態。
  - US market.breadth 在修正前測試能重現，修正後回 truthful unsupported。
- Validation：
  - git status --short --branch
  - cd backend; ..\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider tests\test_ai_capability_contract.py tests\test_ai_capability_resolution_registry.py -q
  - 使用唯讀 selection probe 檢查 market.breadth、market.sectors、market.hot_groups、technical.indicators、technical.structure 的 US compatibility。
- Stop condition：
  - 若 Foundation target files與既有 dirty hunks無法安全分離，停止實作並確認 integration base。

### A1 — Outward capability與 schema migration design

- Scope：
  - 定義 neutral quote／intraday successor schema。
  - 定義 legacy TW-named schema compatibility、deprecation與consumer migration matrix。
  - 補強 advertised ⇒ dataset／projector／fixture／operation 的 market-aware validation。
- Acceptance：
  - 新 schema 不複製 provider policy、freshness owner或 Decision v4 readiness。
  - 舊 API／MCP snapshot仍可通過 compatibility tests。
  - US unsupported能力不會因 scope wildcard或缺少 markets restriction而被誤宣告。
- Validation：
  - cd backend; ..\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider tests\test_ai_capability_contract.py tests\test_ai_capability_resolution_registry.py tests\test_api_contract_inventory.py -q
  - 重新產生但不自動接受 public／MCP snapshot diff；人工確認 breaking surface。

### A2 — US canonical session、identity與 bar semantics

- Scope：
  - 定義 US phase alias與 Canonical MarketSession mapping。
  - 定義 venue、listing、canonical symbol、provider symbol、currency與 America/New_York timestamp normalization。
  - 定義 1m bar partial／final、zero volume、missing OHLC、duplicate timestamp、DST與early close處理。
- Acceptance：
  - pre_market／regular／after_hours可映射，但不修改共用 enum語意。
  - 所有 canonical timestamp timezone-aware；event／received／fetched time分離。
  - Unknown、no trade、empty bar與provider omission不互相冒充。
- Validation：
  - cd backend; ..\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider tests\test_market_data_contracts.py tests\test_us_close_session_contract.py tests\test_us_market_data_session_contract.py -q
- Stop condition：
  - 若共用 enum變更會改變 TW fixture serialization，先採 additive market-specific metadata，不直接 breaking change。

### A3 — Yahoo canonical adapter

- Scope：
  - 在 app.us_market provider owner內新增 Yahoo payload → QuoteObservation／BarObservation converter。
  - 建立 sanitized fixtures，涵蓋 regular、extended、closed、no-data、delayed、punctuation symbol與provider error。
  - Adapter不執行 fallback或DB write。
- Acceptance：
  - 同一 payload可產生 deterministic observations與bounded lineage。
  - Quote與bar的session、currency、timezone、volume unit與partial state一致。
  - Adapter failure可被分類，不污染legacy selected result。
- Validation：
  - cd backend; ..\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider tests\test_us_market_data_canonical_adapters.py tests\test_market_data_contracts.py -q

### A4 — Alpha Vantage daily canonical adapter

- Scope：
  - 轉換 daily raw／adjusted OHLCV、dividend與split metadata。
  - 明確區分provider data basis、quota／plan limitation與source event date。
- Acceptance：
  - adjusted與raw不會在無 metadata時混用。
  - rate limit、missing API key、compact／full差異保留 truthful limitation。
  - 不由adapter決定Yahoo fallback。
- Validation：
  - cd backend; ..\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider tests\test_us_market_data_canonical_adapters.py tests\test_us_market_daily_price.py -q

### A5 — US provider policy、bounded acquisition與resolver shadow

- Scope：
  - 擴充 US provider descriptors、capability／session-aware candidate policy與call budget。
  - 串接 off／shadow／compare，legacy仍為production owner。
  - 建立selected／candidate summary、fallback chain、selection reason與mismatch taxonomy。
- Acceptance：
  - cache_only永遠不建立provider call或lease。
  - prefer_live／require_live只建立bounded plan，未達live時明確policy unmet。
  - shadow／compare不改outward result、不增加無界call、不保存raw credentials／payload。
- Validation：
  - cd backend; ..\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider tests\test_market_data_provider_policy_v2.py tests\test_market_data_control_plane_v2.py tests\test_market_data_shadow_comparison.py tests\test_us_market_data_provider_policy.py -q
- Stop condition：
  - 任一price、currency、unit、session、timestamp或symbol identity mismatch先停下修正，不以平均一致率掩蓋語意錯誤。

### A6 — US quote／intraday／daily outward projection

- Scope：
  - 將resolved US evidence接到capability projection與omi.decision.v4 evidence.data。
  - 保留provider lineage、freshness_by_capability、realtime、quality與limitations。
  - 維持HTTP／SSE／MCP語意一致。
- Acceptance：
  - quote.snapshot、intraday.bars、daily.ohlcv均使用backend-ownedselected evidence。
  - Consumer無須指定provider；legacy provider參數只保留compatibility，不能成為新contract owner。
  - response budget、fields／limits與partial／missing投影truthful。
- Validation：
  - cd backend; ..\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider tests\test_us_outward_capability_contract.py tests\test_ai_tool_boundaries.py tests\test_api_contract_inventory.py -q
  - repo MCP initialize → tools/list → omi.ask representative US call protocol smoke。

### A7 — Canary、legacy ownership cutover與rollback

- Scope：
  - 為single-symbol／bounded-universe建立canary。
  - 比較legacy與resolved outward payload；定義rollback trigger。
  - 將provider selection從app.us_market.service逐步移到Control Plane。
- Acceptance：
  - canary僅影響明確sample；fallback、quota、timeout與provider failure可觀測。
  - rollback不需migration reversal或資料破壞。
  - legacy path移除前，所有active consumer與snapshot inventory完成盤點。
- Validation：
  - run-safe-validation backend profile。
  - bounded API smoke對比off／compare／canary輸出。
- Stop condition：
  - 若runtime identity、effective mode、selected provider或sample不符合預期，fail closed，不進on。

### A8 — KGI US readiness與可選整合

- Scope：
  - 先做SDK capability／entitlement／symbol／session／field mapping審查。
  - 只有明確授權後才做single-symbol、single-login、bounded timeout的live smoke。
  - Account／Order API完全排除。
- Acceptance：
  - KGI US Quote與KGI Account health分離。
  - entitlement不足、plan restriction、not connected與no quote均有不同狀態。
  - lease／subscription cleanup可驗證。
- Validation：
  - fixture tests是source gate。
  - live smoke需另行批准，並記錄runtime identity、symbol、session、call／time budget與cleanup evidence。

### A9 — Production runtime acceptance與handoff

- Scope：
  - 正式launcher採用、API／MCP／frontend資料面驗證、文件同步。
  - 產出給第二塊的capability readiness matrix。
- Acceptance：
  - source、runtime、provider與consumer adoption證據分開。
  - selected port、PID、owner、health、contract version與代表性outward call全部確認。
  - BackendArchitecture／Roadmap只在code與runtime truth已證明後更新。
- Validation：
  - .\scripts\run-safe-validation.ps1 -Profile backend
  - 正式runtime /api/ai/tools、HTTP／SSE omi.ask與MCP protocol smoke。
  - frontend只做資料contract adoption smoke；視覺改版留給第二塊。

## Cross-workstream gate

第二塊可在以下條件前做pure extraction與fixture work，但不得啟用US outward research：

- A0 capability truth gate已完成。
- A2 US session／identity contract已固定。
- A3或A4至少一條canonical daily OHLCV fixture path可用。
- A6 daily.ohlcv resolved projection與freshness／quality contract可供Research Engine消費。

## Stop-and-fix rules

- 若US能力錯誤使用TW provider contract、schema owner或market data，立即停止後續milestone。
- 若cache_only產生external IO、subscription、repair或DB write，視為blocking regression。
- 若provider adapter開始決定fallback、readiness或AI semantics，退回owner boundary修正。
- 若任何missing／unknown／plan_restricted被投影成0、ready或live，停止cutover。
- 若需要DB migration、external quota、runtime restart、KGI live login、commit／push，先取得對應授權。
- 若targeted regression失敗，先修正或證明與本工作流無關，不帶著失敗進下一階段。

## Decisions

- 2026-08-23：把長專案拆成Foundation／Outward與Research／Consumer兩塊，避免同一批同時改provider、public contract、technical與frontend。
- 2026-08-23：第一塊先修US market.breadth truth leak，再做Yahoo canonical shadow。
- 2026-08-23：Canonical MarketSession保留跨市場enum，US premarket／regular／after-hours採mapping，不先做breaking enum rewrite。
- 2026-08-23：neutral schema採additive successor與compatibility，不destructive rename既有tw.* schema。
- 2026-08-23：KGI US live整合是後段獨立授權gate，不作為Yahoo canonical source-complete的必要條件。
- 2026-08-23：US provider descriptor留在app.us_market；shared provider_policy只保留market／capability allowlist與pure planning。
- 2026-08-23：Yahoo intraday shadow wiring重用同一個已取得payload，不增加provider call；off不執行canonical conversion，shadow／compare不改legacy outward result。
- 2026-08-23：AAPL canary只在compare exact match時投影neutral evidence；任一mismatch均fail closed回legacy。
- 2026-08-23：Yahoo 16:00 closing print映射為closing auction；regular/all包含，extended排除。
- 2026-08-23：finalized daily cache按provider形成候選再進shared Resolver；cache-only read不呼叫provider、不commit或flush。
- 2026-08-23：KGI SuperPy 2.1.0雖有`api.USQuote`，但現有bridge是`api.Quote`且payload shape不相容；在六項live gate完成前不加provider descriptor、不宣稱supported。
