# Plan

## Execution status（2026-08-23）

- B0：completed；保存dirty-worktree ownership、52 tests baseline與frontend local-owner inventory。
- B1：completed for the shared numerical primitives used by TW/US first-class indicators；TW compatibility wrapper沿用既有outward schema，advanced TW-only research algorithms尚未對US宣告。
- B2：completed；US/TW versioned profiles與US data-usability gate已建立。
- B3：completed；US daily `technical.indicators` neutral projection已接入Decision v4。
- B4：completed for US v1；current state、trend、support/resistance、breakout/failure、counter-evidence、invalidation與limitations由backend擁有；relative strength因benchmark未確認保持明確missing limitation。
- B5：completed；1m／5m／15m／30m／1h／4h由backend session-aware聚合並揭露partial finalization。
- B6：gate completed, outward activation held；versioned universe/classification coverage可見，但full-market與standard taxonomy gate未過，因此breadth/sectors/hot groups保持unsupported。
- B7：completed；frontend canonical technical與intraday aggregation owner已移除，US OHLC GET不再隱性補抓。
- B8：completed；HTTP／SSE／MCP皆回`omi.decision.v4`與相同US technical evidence keys，MCP保持thin adapter。
- B9：completed；safe validation、launcher adoption、frontend proxy與AAPL visible UI proof已完成，外部檢查留給後續獨立階段。

## Program relationship

- 本工作流是兩塊計畫的第二塊，擁有Canonical／Resolved data之上的research derivation與consumer convergence。
- Upstream：docs/agent-runs/us-first-class-foundation-outward-20260823/。
- B0／B1 pure extraction可與第一塊shadow work平行；B2之後的US production capability必須等待第一塊A2＋A6 readiness。

## Milestones

### B0 — Research baseline與cross-workstream gate

- Scope：
  - 保存technical_evidence、technical parameters、capability specs、USStockDetailPanel與相關tests的target-file status／diff。
  - 建立TW／US capability、data basis、provider independence與consumer ownership matrix。
  - 固定現有TW numerical golden baseline與frontend local calculation inventory。
- Acceptance：
  - 明確列出哪些函式pure、哪些綁DB／TW calendar／benchmark／projection。
  - 第一塊A2 session contract與A6 daily resolved projection尚未ready時，US activation保持blocked。
  - 所有既有dirty hunks都有ownership說明。
- Validation：
  - git status --short --branch
  - cd backend; ..\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider tests\test_technical_parameters.py tests\test_technical_capability_contract.py -q
  - cd frontend; npm run lint；僅在後續實作改到編譯檔時執行。

### B1 — Extract pure Shared Technical Engine

- Scope：
  - 將indicator、swing、Fibonacci、divergence、breakout、volume profile、anchored VWAP與relative-strength pure計算抽至shared research boundary。
  - 保留build_tw_stock_technical_evidence作compatibility wrapper。
  - 不改公式、rounding、period completeness或outward schema。
- Acceptance：
  - shared core不importSQLAlchemy、app.market.service、MarketIndexDailyStat或Taiwan trading calendar。
  - TW golden fixtures在抽離前後bit-for-bit或明確tolerance一致。
  - 沒有建立第二套指標算法。
- Validation：
  - cd backend; ..\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider tests\test_technical_parameters.py tests\test_technical_capability_contract.py tests\test_technical_evidence.py -q
- Stop condition：
  - 任一TW數值、period status、corporate-action guard或outward payload無意變動，先修正compatibility wrapper。

### B2 — MarketAnalysisProfile與US technical data usability

- Scope：
  - 定義versioned profile：windows、minimum bars、warm-up、calendar、session、benchmark、currency、price basis與provisional policy。
  - 建立US daily bars輸入validator與decision-usability gate。
  - 將corporate action coverage、stale／missing bars、duplicate dates與split discontinuity納入quality。
- Acceptance：
  - MA200等長window不足時回insufficient／partial，不產生看似完整值。
  - raw／adjusted basis明確；無法判定時不允許structure decision-ready。
  - profile default有version與tests，不靠consumer傳入任意參數。
- Validation：
  - cd backend; ..\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider tests\test_market_analysis_profiles.py tests\test_us_technical_data_usability.py -q
- Stop condition：
  - 若現有schema無法誠實表達price basis／corporate action coverage，先提出additive contract或migration設計。

### B3 — US daily technical.indicators capability

- Scope：
  - 從第一塊resolved daily.ohlcv建立US indicator evidence。
  - 第一批只納入產品需要且可驗證的MA／EMA、RSI、MACD、ATR與volume state。
  - 建立evidence.data[technical.indicators]與capability_status projection。
- Acceptance：
  - 每個indicator有method、parameters、as_of、bar count、warm-up與data basis。
  - stale／partial／missing會反映在quality與decision usability。
  - Consumer不需知道provider或自行補資料。
- Validation：
  - cd backend; ..\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider tests\test_us_technical_indicators.py tests\test_us_outward_capability_contract.py tests\test_ai_tool_boundaries.py -q

### B4 — US technical.structure與current_state

- Scope：
  - 建立trend、support／resistance、swings、breakout／failure、counter-evidence與canonical current_state。
  - benchmark-ready時加入relative strength；未ready時標示optional／missing，不阻塞基礎indicators。
  - 保持active_score_impact與決策語意顯式。
- Acceptance：
  - current_state是唯一backend-ownedpresent-state model，不建立平行frontend判斷。
  - Structure evidence引用已選定bars／indicators與quality，無provider IO。
  - 反證、失效條件、limitations與資料日期可驗證。
- Validation：
  - cd backend; ..\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider tests\test_us_technical_structure.py tests\test_technical_capability_contract.py tests\test_ai_decision_contract_v4.py -q

### B5 — Session-aware backend multi-timeframe aggregation

- Scope：
  - 建立1m → 5m／15m／30m／1h／4h純聚合contract。
  - 處理regular／extended／all、America/New_York、DST、early close、missing minute與partial current bar。
  - 定義timeframe、session_scope、source_interval、aggregation_method與bar finalization outward metadata。
- Acceptance：
  - frontend不必取得完整1m後自行聚合。
  - regular與extended不會無意混桶；跨日／DST bucket deterministic。
  - completed bar與current partial bar明確分開。
- Validation：
  - cd backend; ..\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider tests\test_us_intraday_aggregation.py tests\test_us_close_session_contract.py -q

### B6 — US universe、sectors、breadth與hot groups

- Scope：
  - 定義WATCHLIST／INDEX_MEMBERS／PORTFOLIO／FULL_MARKET等universe contract。
  - 建立versioned membership、sector／industry taxonomy、effective date、coverage與unknown。
  - 先做index／bounded universe research，再依coverage gate開放full-market claim。
- Acceptance：
  - is_full_market、universe_complete與dataset coverage是不同欄位。
  - missing、unmapped與not-ranked不得轉成0。
  - breadth／sector／hot groups不依賴使用者開啟個股頁面；completed-session資料由scheduler-owned persistence供應。
  - provider rights／quota／coverage不明時保持shadow／partial。
- Validation：
  - cd backend; ..\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider tests\test_us_market_universe.py tests\test_us_market_breadth.py tests\test_us_market_groups.py tests\test_eod_coverage.py -q
- Stop condition：
  - 若universe來源、effective date或coverage無法驗證，不得宣稱full_market或用sample推導全市場。

### B7 — Frontend data contract convergence

- Scope：
  - USStockDetailPanel改讀backend technical／aggregation projection。
  - 移除或停用aggregateUsProfessionalIntradayBars、client-side MA／technicalTitle canonical ownership。
  - 將missing／partial／stale／provider failure導向shared更新狀態flow。
  - 保留既有layout、selection、extended-hours與detail功能。
- Acceptance：
  - 畫面數值、title與backend current_state一致。
  - backend unsupported時UI顯示unavailable／partial，不回退自算canonical結論。
  - Desktop／mobile無遮擋、控制重複或主要操作退化。
- Validation：
  - .\scripts\run-safe-validation.ps1 -Profile frontend
  - browser／DOM／screenshot驗證代表性US symbol的ready、partial與missing states。
- Stop condition：
  - typecheck/build成功但實際畫面未採用新payload，不得宣稱consumer cutover完成。

### B8 — MCP／Kuro parity與Decision v4 convergence

- Scope：
  - 透過既有omi.ask與read tools消費新增capabilities。
  - 驗證HTTP／SSE／MCP envelope、capability status、freshness、current_state與limitations一致。
  - Kuro只做persona／語音呈現，不建立US專用研究schema。
- Acceptance：
  - MCP server沒有importresearch engine、DB或provider。
  - 同一request的indicator values與readiness跨transport一致。
  - payload budget裁切不改變核心語意。
- Validation：
  - MCP initialize → retain Mcp-Session-Id → tools/list → representative omi.ask call。
  - HTTP與SSE final parity tests。

### B9 — Runtime acceptance、performance與docs convergence

- Scope：
  - 正式runtime adoption、UI visible proof、performance／payload budget、docs同步。
  - 對large history、many indicators、mobile payload與bounded universe做容量驗證。
- Acceptance：
  - selected port、PID、owner、health、contract version與frontend chunk adoption已確認。
  - 代表性US symbol在UI／omi.ask／MCP顯示一致technical evidence。
  - P95／payload budget或repo既有門檻通過；超出時以projection limit／continuation處理，不靜默裁切。
  - Product／architecture docs只記錄已完成與仍partial的truth。
- Validation：
  - .\scripts\run-safe-validation.ps1 -Profile backend
  - .\scripts\run-safe-validation.ps1 -Profile frontend
  - 依變更風險決定是否執行full profile與browser acceptance。

## Cross-workstream dependency gates

- B1可先執行，但必須保持TW compatibility。
- B2需要第一塊A2的US session／identity contract。
- B3／B4需要第一塊A6的resolved daily.ohlcv與outward quality contract。
- B5需要第一塊A3的canonical1m bar semantics。
- B6可做universe research，但full-market outward需要durable coverage達到明確門檻。
- B7／B8只能在相應backend capability與projection通過acceptance後cutover。

## Stop-and-fix rules

- 若pure engine出現provider、DB、router或consumer dependency，停止抽離並修正boundary。
- 若TW golden數值或既有outward contract無意改變，先修compatibility，不帶著regression做US。
- 若adjusted／raw、corporate action或warm-up不明，technical output不得decision-ready。
- 若frontend仍自行聚合或推導canonical technical state，不得宣稱consumer convergence。
- 若sample／index universe被標成full market，立即停止outward rollout。
- 若需要DB migration、external refresh、runtime restart、browser side effect、commit／push，先取得授權。
- 任一targeted test、typecheck、build或actual UI驗證失敗，先修正再進下一個milestone。

## Decisions

- 2026-08-23：第二塊包含Shared Technical、server-side aggregation、US market research aggregates與consumer convergence。
- 2026-08-23：先抽現有pure algorithms並保留TW wrapper，不建立第二套US technical engine。
- 2026-08-23：US daily technical.indicators先於technical.structure與多週期分析。
- 2026-08-23：Corporate action／price basis／warm-up是readiness gate，不只是warning。
- 2026-08-23：Frontend migration是contract adoption，不是視覺大改版；視覺改版另立專案。
- 2026-08-23：B0／B1可與第一塊平行，US production activation需等待A2／A6。
