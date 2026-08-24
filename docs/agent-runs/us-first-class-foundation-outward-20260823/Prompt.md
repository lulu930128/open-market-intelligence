# OMI 美股 First-Class Market：Foundation 與 Outward Truth

## Authorization state

- 規劃與 task docs：已完成。
- A0-A6 source implementation：使用者於 2026-08-23 授權；已完成 source、fixture、shadow wiring 與 targeted validation。
- 使用者於 2026-08-23 授權 OMI 程式重啟並繼續；正式 launcher restart、AAPL bounded Yahoo canary、HTTP／SSE／MCP／frontend proxy 與 rollback drill 已完成。
- KGI login／subscription、Account／Order、DB migration、commit、push 與 release 仍未取得授權；KGI live entitlement smoke 是獨立 gate。

## Goal

- 讓 Yahoo、Alpha Vantage、KGI US 與未來美股來源以 provider-neutral Canonical Observation 進入共用 Resolution／Control Plane，不再由 app.us_market.service 自行擁有 cross-provider fallback。
- 建立美股 quote、intraday bars、daily OHLCV 的可信 outward contract，使 API、omi.decision.v4、MCP 與 frontend 能取得一致的 provider、event／received／fetched time、session、freshness、fallback 與 limitations。
- 在不做 Big Bang rewrite 的前提下，保留現有美股 data plane 與 UI 可用性，透過 off → shadow → compare → canary → on 漸進切換。
- 先修正 market.breadth 對 US market 的錯誤 advertised／resolution 漏洞，確保尚未實作的美股能力 truthful unsupported。
- 建立中性的 quote／intraday schema successor 與 compatibility path，停止讓新美股 outward capability 繼續擴張 tw.* schema 命名債。

## Non-goals

- 不在本工作流實作 technical.indicators、technical.structure、server-side 多週期聚合、sector rotation、hot groups 或 frontend 技術分析收斂；它們屬於第二塊 Research／Consumer 工作流。
- 不把 portfolio、position、cost、cash 或 KGI Account health 放進 Market Data Foundation。
- 不讓 AI 自主下單，不建立 broker execution，不把研究結論連到交易副作用。
- 不因 first-class market 目標而宣稱 full-market EOD、breadth、fundamentals 或 corporate actions 已完整。
- 不在 cache_only GET、projection 或 consumer render path 隱性啟動 provider fetch、subscription、repair 或 DB write。
- 不刪除 legacy Yahoo／Alpha Vantage service、既有 API response 或 frontend route，直到 canary、compatibility 與 rollback acceptance 全部通過。
- 不執行無界全市場 provider refresh、付費 quota smoke、無界 retry 或未批准的 schema migration。
- 不順手整理目前 110 筆既有 modified／untracked worktree 項目。

## Hard constraints

### Ownership and dependency

- Provider adapter 只做 IO、provider-specific normalization、payload parsing 與 canonical conversion；不得決定跨 provider fallback、research readiness 或 AI decision。
- Shared backend/app/market_data 不得反向依賴 app.us_market、provider SDK、SQLAlchemy Session、router、frontend 或 MCP。
- Resolver 必須 deterministic、bounded、可解釋，且不執行 IO。
- app.us_market 保留 US calendar、symbol／venue、premarket／regular／after-hours、corporate-action 與 provider integration 細節；共用 Foundation 保留 provider-neutral contract 與 selection policy。
- Frontend、MCP、Kuro 不得選 provider priority、重算 freshness 或建立替代 fallback。

### Truthfulness

- Unknown 不得轉成 0；No Quote 不得推導 No Trade 或 Suspended。
- Provider Health、Dataset Health 與 Resolved Evidence Health 必須分開。
- selected evidence 必須保留 source lineage、candidate／fallback summary、selection reason 與 event／received／fetched time。
- US market.breadth、market.sectors、market.hot_groups 與 technical capabilities 在真實 projection 完成前必須明確 unsupported／planned，不得指向 TW provider contract。
- Current、live、delayed、stale、latest_completed_session、final_snapshot 與 unavailable 不得互相冒充。

### Session and identity

- 共用 Canonical MarketSession 保留 PRE_OPEN／CONTINUOUS／POST_CLOSE 等跨市場 phase；US outward 可映射 pre_market／regular／after_hours，但不得直接重寫共用 enum 造成 TW regression。
- Instrument identity 必須明確區分 market、venue／listing、canonical symbol、provider symbol、instrument type、currency 與 timezone。
- Yahoo punctuation／share-class symbol mapping 必須是可測試、可追蹤的 provider mapping；mapping failure 不得改寫成 missing=0 或成功。

### Compatibility and rollout

- 新 schema 採 additive successor、compatibility adapter 或明確 deprecation；不 destructive rename tw.quote.snapshot.v2／tw.intraday.bars.v2。
- off／shadow／compare 不得改變 legacy selected result、public response、provider call count或 subscription lifecycle。
- canary 只允許 bounded symbol／session／capability sample，且必須有 fail-closed、rollback 與 mismatch budget。
- source-complete、runtime-adopted、provider-live-verified、consumer-cutover-complete 是四個不同 acceptance state。

### Data, runtime and change control

- data/open_market_intelligence.db 不得重建、清除或覆蓋。
- 若需要 persistence，先提出 migration、容量、backfill、rollback 與 read-compatibility 設計，再取得批准。
- Runtime port 以 launcher selected= 與實際 listener／PID 為準，不假設永久為 8400／3000。
- 目前 branch codex/tw-etf-provider-normalization、HEAD aa65e65、63 modified＋47 untracked 是既有基線；任何實作前先做 target-file ownership map，禁止 reset／restore／clean。

## Context

- Repo：C:\project\Open Market Intelligence
- Source proposal：`%USERPROFILE%\Downloads\OMI_US_First_Class_Market_Engineering_Plan_v1.txt`
- Task docs：docs/agent-runs/us-first-class-foundation-outward-20260823/
- Planning date：2026-08-23（Asia/Taipei）
- Related systems：backend Market Data Foundation、US provider integrations、AI capability registry、omi.decision.v4、MCP adapter、frontend data consumers、SQLite、scheduler／coverage、launcher runtime。
- Current truth：docs/product/*、docs/architecture/BackendArchitecture.md、docs/architecture/OmiDecisionContract.md。

### Confirmed current state

- Foundation typed contracts、pure resolver、Dataset Registry 與 TW adapters 已存在；本工作流已補上 US market-owned provider policy、canonical adapter、neutral projection、shadow compare 與 AAPL canary seam。
- US market.breadth scope leak 已修正為 truthful unsupported；US quote.snapshot、intraday.bars、daily.ohlcv 已能投影為 neutral `omi.market.quote.snapshot.v1`／`omi.market.bars.v1`。
- Yahoo quote／1m 與 daily、Alpha Vantage daily 均可產生 provider-neutral observation；AAPL compare 重用同一取得 payload，不額外發 provider call。
- US intraday session_scope 支援 regular／extended／all；Yahoo 16:00 closing print 已明確映射為 closing auction，不混入 extended。
- AAPL finalized daily cache 已由 provider-homogeneous candidates 進 shared Resolver；Alpha Vantage stale 時可 truthful 選 Yahoo fallback，且 read path 不做 provider IO 或 DB write。
- KGI SuperPy 2.1.0 source inspection 證明 SDK 有獨立 `api.USQuote`，但 OMI 現有 bridge、field extractor 與 canonical adapter 仍是 TW-only；KGI US 保持 unadvertised、unwired、live validation not attempted。
- 最新唯讀 DB checkpoint：US full-market universe 7,427；current 1,820、stale 342、missing 5,265，expected／latest date 2026-08-21。
- 正式 launcher runtime 已採用本工作流 source；目前 canary 以 process-scoped `CANONICAL_MARKET_DATA_MODE=compare` 與 `US_CANONICAL_SHADOW_SYMBOLS=AAPL` 啟動，完整 launcher exit／一般啟動會回復 off。
- MCP 維持 thin HTTP adapter；HTTP、SSE、repo MCP stdio 與 frontend proxy 已完成 `omi.decision.v4` neutral quote／intraday／daily parity 驗證。

## Deliverables

- US outward capability compatibility matrix，至少覆蓋 target scope、market、dataset、projector、refresh operation、provider policy、schema version 與 truthful unsupported。
- market.breadth US scope leak 的 regression fix 與 market-specific capability tests。
- Yahoo canonical QuoteObservation／BarObservation adapter，含 sanitized fixture corpus、timezone、session、currency、symbol mapping、partial／final bar 與 lineage tests。
- Alpha Vantage daily OHLCV canonical adapter，保留 adjusted／raw、dividend／split metadata 與 provider limitation。
- US provider descriptors、capability／session-aware policy、pure resolver inputs、bounded acquisition plan 與 shadow／compare observability。
- Neutral quote／intraday outward schema successor、compatibility projection 與 public contract inventory update。
- Legacy-vs-canonical mismatch taxonomy與 acceptance report，至少涵蓋 price、volume、timestamp、session、currency、symbol、bar finalization、fallback 與 missing／stale semantics。
- Feature-flag rollout、canary、rollback 與 runtime acceptance matrix。
- KGI US quote source-readiness contract與 sanitized fixture gate；保持 fail-closed、不進 provider policy，live entitlement／subscription smoke保留獨立授權。
- 持續更新的 Progress.md，記錄 source、tests、runtime、provider sample、blocked gate 與 remaining legacy ownership。

## Done criteria

### Source-complete

- US quote／intraday／daily provider fixtures可直接產生 canonical observations，無需偽裝成其他 provider payload。
- MarketSession、US session alias、InstrumentTradingStatus 與 observation state 保持正交。
- Resolver／policy 對 US capability與 session 產出 deterministic plan；cache_only 不產生 IO。
- market.breadth／sectors／hot groups／technical 等尚未實作能力在 US target 上 truthful unsupported。
- advertised US quote／intraday／daily capability 都有 dataset registration、projector與 fixture contract test。
- Neutral successor schema 可與 legacy TW-named schema compatibility 共存，舊 consumer test 不破壞。
- Shadow／compare 預設不改 production result、不增加無界 call、不寫 raw provider payload。
- Targeted tests 與 backend safe validation 通過。

### Runtime-accepted

- 正式 launcher 採用新 source，並確認 selected port、listener、PID、executable path、build／contract version 與 health。
- /api/ai/tools、HTTP／SSE omi.ask、repo MCP tools/list 與代表性 US quote／intraday／daily call 保持 v4 parity。
- bounded shadow／compare sample 可觀測且無重大 price、unit、session、timestamp、identity 或 fallback semantic mismatch。
- canary sample 在 mismatch budget 內，fail-closed 與 rollback 實際驗證。
- 若沒有 KGI US entitlement/live sample，不得宣稱 KGI US runtime accepted。
- Consumer cutover 前後的 provider lineage、freshness、limitations 與 payload compatibility都有 outward evidence。

## Open questions / assumptions

- 第一版 neutral schema 命名與 version 將在 Milestone A1 依現有 public snapshot、MCP schema與 compatibility cost 決定。
- Yahoo 與 Alpha Vantage 的 provider priority 不預先硬編碼；必須按 capability、session、data basis、quota與 operational health 決定。
- KGI SDK source已證明 `USQuote` facade、USStock quote／KBar與scalar best bid／ask欄位存在；premarket／after-hours session值、venue mapping、實際欄位payload、entitlement與subscription cleanup仍需另行批准的single-symbol live smoke驗證。
- US daily adjusted／raw canonical basis 是否需要新增 persisted欄位，必須先證明現有 us_daily_price 不足；否則保持 source-only projection。
- Provider compare telemetry預設使用 bounded structured evidence；若要 durable persistence，需另開 migration gate。
