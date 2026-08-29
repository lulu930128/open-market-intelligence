# Plan

## Program control documents

| Document | Role |
| --- | --- |
| `Prompt.md` | charter、scope、hard constraints與done criteria |
| `ArchitectureMap.md` | current/target graph、ownership與gap map |
| `WorkBreakdown.md` | executable work packages、dependencies與file ownership |
| `CoreHandoffChecklist.md` | 台股Core完成後的G0交付與驗證契約 |
| `AcceptanceMatrix.md` | 每一required gate的truthful status |
| `RiskRegister.md` | trigger、mitigation、contingency與blocker |
| `CutoverRunbook.md` | rollout evidence、promotion與rollback程序 |
| `Progress.md` | 當下狀態、驗證證據、決策、blocker與next step |

## Program governance

- 本`Plan.md`保留milestone視角；實際執行以`WorkBreakdown.md`的work package為最小單位。
- 一次只允許一個work package進入同一組高衝突檔案；`app.market_data`、registry/jobs/scheduler、US router/AI/frontend不得未協調平行修改。
- Package開始時固定source SHA、dirty status、owned files與validation budget；完成source只能標`implemented_unverified`，通過驗證後才標`passed`。
- 每個package完成後同步更新`Progress.md`與`AcceptanceMatrix.md`；風險觸發時同步更新`RiskRegister.md`。
- External API、runtime restart/cutover、DB migration、付費quota、commit/push/release各自需要明確授權；長專案授權不自動擴張side-effect權限。
- 不設未經證據支持的日曆工期；專案進度以gate與artifact計量，不用日期把未驗收工作壓成完成。

## Milestone to work-package mapping

| Master milestone | Work packages | Exit gate |
| --- | --- | --- |
| M0 | A0 Baseline、A2 Legacy Quarantine | baseline可重現；scheduler未接Core前fail closed |
| M1 | A1 Boundary Guard | no-new-leakage guard passed |
| M2–M3 | A3 Package/Candidate Seam | Pre-Core readiness passed |
| G0 | Core handoff G0-01至G0-15 | TW production convergence + US compile-only probe |
| M4 | B1 US Binding/Ports | fake-port Core E2E passed |
| M5 | B2 Daily Read | daily resolved vertical slice passed |
| M6 | C1 Operation Binding、C2 Repair/Scheduler | registry-owned bounded lifecycle passed |
| M7 | D1 Quote/Intraday、D2 Lease/Session | dated realtime/session evidence passed |
| M8 | E1 API、E2 AI/MCP、E3 Frontend/Research | provider-neutral cross-surface parity passed |
| M9 | F1 Compare、F2 Canary/On、F3 Closure | rollback rehearsed + all matrix rows passed |

Current status（2026-08-25）：

| Milestone | Status | Evidence / blocker |
| --- | --- | --- |
| M0 | passed | A0 baseline artifact；priority lifecycle fail closed |
| M1 | passed | architecture guard + named legacy allowlist |
| M2–M3 | passed | production-unwired package、pure adapters、truthful candidate seam |
| G0 | blocked | 等待TW production-converged handoff與G0-01至G0-15 evidence |
| M4–M9 | blocked | 不得早於G0建立production binding或cutover |

## Stage gates

```text
L0 Planning ready
  -> L1 Pre-Core source ready (A0-A3)
  -> G0 Shared Core handoff passed
  -> L2 US integration ready (B1)
  -> L3 Durable data ready (B2+C1+C2)
  -> L4 Realtime ready (D1+D2)
  -> L5 Consumer ready (E1-E3)
  -> L6 Production converged (F1-F3)
```

Gate不能用下游成功倒推上游完成。例如Frontend顯示正常不代表Dataset Registry已擁有refresh；provider call成功不代表postcondition或resolved evidence可用。

## Execution model

本計畫分為兩條 track，中間有不可略過的 Integration Gate。

```text
Track A — Data Core 完成前
  M0 現況封存與 legacy expansion quarantine
  M1 Consumer boundary guard
  M2 US market-data package skeleton
  M3 Provider adapters + candidate persistence/read
                    ↓
        G0 Shared Core Readiness Gate
                    ↓
Track B — Data Core 定版後
  M4 US bindings / provider ports
  M5 Daily OHLCV production cutover
  M6 Refresh / repair / scheduler lifecycle cutover
  M7 Intraday / quote / lease cutover
  M8 API / AI / Frontend consumer cutover
  M9 Canary / legacy removal / closure
```

G0 未通過時，M4–M9 必須保持 blocked。不得用臨時 second resolver、consumer fallback 或 provider-specific shim 假裝已接上 Shared Core。

## Milestones

### M0 — 現況封存與 legacy expansion quarantine

- Scope：
  - 再確認 branch、dirty worktree、HEAD baseline 與 US/TW 交疊檔案。
  - 將目前未提交 OHLC continuity、repair、priority scheduler 拆成「可保留的 pure coverage/postcondition」與「不得擴張的 provider acquisition」。
  - 未接 Shared Core 前，priority repair scheduler 必須 fail closed／default off；Frontend 不得自動發出 provider-specific repair。
  - 不 revert 使用者變更；必要時以小型 compatibility wrapper 或 feature flag 隔離。
- Acceptance：
  - Continuity、expected date、missing sessions、previous-close postcondition 保留且仍可測。
  - Source/runtime 未明確啟用時，不會在 startup 自動執行 Yahoo priority repair。
  - 新 repair product request 不含 `provider=yahoo_chart|alphavantage`。
  - `git diff` 可清楚區分既有 dirty work與本 milestone 修改。
- Validation：
  - `git status --short`
  - `rg -n "provider.*(yahoo_chart|alphavantage)|ENABLE_US_PRIORITY_OHLC" backend/app frontend/src`
  - `cd backend; ..\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider tests\test_us_ohlc_continuity.py tests\test_us_ohlc_contract.py tests\test_us_ohlc_priority.py tests\test_eod_coverage_scheduler.py -q`

### M1 — Consumer boundary guard

- Scope：
  - 新增 US market-data architecture boundary test，分類 product consumer、diagnostic/admin、provider adapter、legacy compatibility。
  - Guard product Frontend、AI planner/executor、public product router、scheduler、Research 與 Watchlist，不得新增 provider selection/fallback。
  - 初期 legacy allowlist 必須是具名 symbol/module，不用脆弱行號；每次 cutover 後縮小 allowlist。
  - Diagnostic/raw-source history 可以保留 provider filter，但路徑、名稱與測試必須明示非 product truth path。
- Acceptance：
  - 新 consumer-side `provider="yahoo_chart"`、`provider="alphavantage"` 或 `if auto -> fallback` 會使測試失敗。
  - Lineage 顯示欄位不被誤判為 provider selector。
  - Allowed exceptions 只限 adapter、fixture、diagnostic/admin 與暫時具名 legacy seam。
- Validation：
  - Planned targeted test：`backend/tests/test_us_market_data_architecture_boundaries.py`
  - `cd backend; ..\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider tests\test_us_market_service_boundaries.py tests\test_api_contract_inventory.py tests\test_ai_tool_boundaries.py -q`

### M2 — US market-data package skeleton

- Scope：
  - 以穩定責任整理 `backend/app/us_market/market_data/`，預計包含：
    - `descriptors.py`：US provider catalog/capability/session/priority metadata。
    - `adapters/`：Yahoo、AlphaVantage，未來 KGI US；每個 adapter 保持 provider-specific。
    - `candidate_store.py`：provider-coherent candidate persistence/read boundary。
    - `projection.py`：US resolved evidence → stable US outward projection。
    - `integration_manifest.py`：宣告 US 可提供的 descriptors、adapter factories、persistence callbacks、US policy callbacks 與 dataset specs；不執行 planning/fallback。
    - `legacy_compat.py`：暫時集中舊 service contract，不作新功能入口。
  - 既有 `market_data_policy.py`、`market_data_projection.py`、`providers/canonical.py`、`resolved_reads.py` 先以 compatibility re-export 或局部搬移維持 import stability。
  - 不先建立猜測版 Shared Core binding；真正 `bindings.py` 等 G0 通過後再加入。
- Acceptance：
  - Package dependency 只由 US layer 指向 shared canonical contracts；Shared Core 不 import US service。
  - Adapter、candidate store、projection、legacy compatibility 的依賴方向有測試或 import guard。
  - 無 public response、DB schema、runtime mode 或 provider priority 行為變更。
- Validation：
  - Python compile/import smoke。
  - `cd backend; ..\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider tests\test_us_market_service_boundaries.py tests\test_us_market_data_provider_policy.py tests\test_us_market_data_canonical_adapters.py tests\test_us_market_data_outward_contract.py -q`

### M3 — Provider adapters 與 candidate persistence/read

- Scope：
  - Yahoo／AlphaVantage adapter 統一完成：bounded IO、provider error normalization、raw parse、timestamp normalization、Canonical quote/bar conversion。
  - Adapter 不直接 commit/rollback；由 transaction-owning persistence service 接受同 provider canonical batch 後 upsert。
  - Candidate reader 依 provider 分組回傳 Canonical candidates，不做 selection/fallback；保留 source URL/hash/fetched time 與可用 raw reference。
  - Daily cache reader 只讀 finalized/corrected bars；intraday reader保留 session scope 與 provisional semantics。
  - KGI US 只建立 readiness/descriptor placeholder；未通過 entitlement/live sample 前不 advertising、不 wiring。
- Acceptance：
  - Yahoo、AlphaVantage fixture 分別產生 provider-coherent Canonical observations。
  - Malformed、duplicate、out-of-order、timezone、partial bar、unknown volume、adjusted/raw price basis 有明確結果。
  - Adapter failure 不寫 DB；commit failure rollback/rethrow；單一 provider failure不污染其他 provider candidates。
  - Candidate store 不回傳 resolved/selected provider 結論。
- Validation：
  - `cd backend; ..\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider tests\test_us_market_data_canonical_adapters.py tests\test_us_market_data.py tests\test_market_transaction_contracts.py tests\test_database_contention_boundaries.py -q`

## G0 — Shared Core Readiness Gate

台股側交付 Shared Market Data Core 後，先逐項驗證下列 contract；全部通過才解鎖 M4。

### Required contracts

- [ ] Final `DataRequirement` 能表達 instrument、capability、timeframe/interval、bars/limit、session、realtime policy、max age、completed-only、purpose 與 bounded request budget。
- [ ] Final `RefreshRequirement` 能表達 dataset ID、market、target、reason、required coverage、max calls、max runtime/range/symbols、cursor 與 postcondition。
- [ ] Provider descriptor registration 由 market domain 注入，Shared Core 不持有 Yahoo/KGI/AlphaVantage production catalog。
- [ ] Provider acquisition port/handle lifecycle 已定版，包含 timeout、cancellation、external-call/subscription count、cleanup 與 provider health。
- [ ] Core acquisition 回傳 provider-coherent Canonical candidates；不要求 adapter 先做 fallback 或 selection。
- [ ] Resolver 能對 quote、intraday bars、daily bars 與必要 trading status 產生 stable Resolved Evidence，保留 candidate summary、selected lineage、freshness、fallback 與 selection reason。
- [ ] `cache_only` 有可測的 zero external IO invariant；`prefer_live`／`require_live`／`completed_session` 行為明確。
- [ ] Dataset Registry 不只存 operation name；已有 operation binding/dispatcher、expected state、eligibility、bounds、cursor、postcondition 與 result contract。
- [ ] Persistence transaction ownership 已定義：Core、provider port與 market persistence callback 各自誰能 commit/rollback。
- [ ] Provider Health、Dataset Health、Resolved Evidence Health 的 input/output schema 與 persistence/effective semantics 已定版。
- [ ] Shadow/compare/canary/on、telemetry、mode identity 與 rollback entrypoint 可被各市場重用。
- [ ] Shared Core 有 TW reference integration tests，能證明非單元 prototype，而是可註冊 market bindings 的 production path。
- [ ] 台股umbrella task已標記`TW_MARKET_DATA_PLATFORM_PRODUCTION_CONVERGED`，其`AcceptanceMatrix.md` B–G required rows全為`passed`且沒有`blocked`。

### Gate procedure

1. 依`CoreHandoffChecklist.md`固定台股source SHA、Core versions、AcceptanceMatrix、actual-data/runtime/rollback artifacts，再讀取Core public types、registration code、operation dispatcher與tests。
2. 將實際 contract 對照 `integration_manifest.py`；若名稱或責任不同，更新本任務文件，不以 compatibility guess 硬接。
3. 建立最小 US compile-only binding 與 fake-port contract test。
4. 驗證 `cache_only` zero IO、candidate coherence、fallback lineage、cleanup 與 transaction boundary。
5. Gate evidence 寫入 `Progress.md`，明確標記 `passed` 或 `blocked`。

### Gate stop condition

任一 required contract 缺失、仍是 dark/unwired prototype、TW AcceptanceMatrix未closure、或TW reference path尚未production-adopted時，M4保持blocked。可以繼續改善M0–M3，但不得切US production consumer。

### M4 — US bindings 與 provider ports（G0 後）

- Scope：
  - 依 final Core interface 建立 `app.us_market.market_data.bindings`。
  - 註冊 Yahoo／AlphaVantage descriptors、provider ports、US session/trading calendar policy、candidate persistence callback、dataset specs 與 stable projection callback。
  - 建立 fake Yahoo／AlphaVantage port integration tests，不先切 public traffic。
- Acceptance：
  - `DataRequirement -> Acquisition Plan -> US provider port -> Canonical candidates -> Resolver -> US projection` 可在 fixture/fake port 完整通過。
  - Core 擁有 fallback；US adapter與binding沒有 `try Yahoo then AlphaVantage`。
  - No port、timeout、rate-limit、auth/plan restriction、both unavailable 均有 truthful resolved/health outcome。
- Validation：
  - Shared Core contract tests + US binding targeted tests。
  - `cd backend; ..\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider tests\test_market_data_control_plane_v2.py tests\test_market_data_resolution.py tests\test_us_market_data_provider_policy.py tests\test_us_market_data_canonical_adapters.py -q`

### M5 — Daily OHLCV production cutover

- Scope：
  - Product daily read 改由 Core cache-only requirement + Resolved Bar Series。
  - Chart、Research、Watchlist Ranking、Radar 使用同一 stable US daily projection；不得再從 `USDailyPrice` rows 自行挑 provider。
  - 保留 legacy output compatibility adapter與compare telemetry；不在同 milestone 改 DB schema或Frontend視覺。
- Acceptance：
  - Yahoo primary、AlphaVantage fallback、provider conflict、stale、partial、missing、requested historical date、early close 均由 Resolver/US policy得到一致結果。
  - Chart／Research／Ranking／Radar 的 selected provider/source/session/fallback/price basis 一致。
  - `cache_only` read 對 provider port invocation count 為 0。
  - Bounded multi-symbol read 無 N+1 regression；500 symbols上限保留。
- Validation：
  - US resolved read/research/watchlist/API contract targeted tests。
  - 376-symbol或等價bounded ranking performance smoke；記錄symbol count、query count與elapsed time。

### M6 — Refresh／repair／scheduler lifecycle cutover

- Scope：
  - Daily、single-symbol OHLC repair、priority universe、full-market EOD 全部送 `RefreshRequirement`。
  - Dataset Registry operation dispatcher 擁有 expected state、eligibility、bounds、cursor、postcondition與result summary。
  - Scheduler只知道 dataset ID、scope、budget、cursor與postcondition，不知道 Yahoo/AlphaVantage。
  - Frontend只能表達 refresh intent或執行 backend fill action，不直接選provider。
- Acceptance：
  - `us.daily.ohlcv`、`us.daily.ohlcv.priority_research`、`us.daily.ohlcv.full_market`各自有可執行operation binding與bounded policy。
  - Provider call、runtime、symbol、range、error與retry budgets皆由Core enforcement；無界或重複refresh會fail closed/dedupe。
  - Repair成功必須通過postcondition；provider call成功但coverage未達標回partial，不宣稱完成。
  - Shared Core不再import `app.us_market.service`，US full-market repair不再hardcode Yahoo。
- Validation：
  - Registry contract、job dedupe/retry、EOD coverage、OHLC continuity/priority、DB contention targeted tests。
  - Scheduler source inspection + bounded job smoke，不執行無界external refresh。

### M7 — Intraday／quote／lease cutover

- Scope：
  - Yahoo intraday IO透過provider port；未來KGI US以獨立port接入，不修改consumer contract。
  - Core取得Canonical quote/bars並resolve；US projection負責premarket/regular/closing/after-hours/early-close語意。
  - Viewer Lease、Research Lease、Collector Lease各自bounded；closed/completed-session不啟動無意義subscription。
  - Last-good cache只能作有lineage/freshness的candidate，不能在service內自行冒充current。
- Acceptance：
  - 1m/5m/15m/30m/1h/4h interval、session bucket、partial bar、extended-hours volume與previous-close semantics保持正確。
  - `require_live`未滿足時明確policy unmet；closed market最新completed session不冒充live。
  - Viewer/research lease cleanup、timeout、cancellation、max symbol/subscription有驗證。
- Validation：
  - Intraday aggregation、canonical adapter、realtime contract、research lease、API/AI targeted tests。

### M8 — API／AI／Frontend consumer cutover

- Scope：
  - Public product route改用requirement semantics；provider-specific操作移至明確diagnostics/admin/raw-source surface。
  - AI planner/executor只選capability、realtime policy與bounded parameters；US context只讀resolved market data/research。
  - Frontend移除`provider: "yahoo_chart"|"alphavantage"`與consumer-side repair owner；只renderbackend projection與Data Status。
  - MCP/Kuro維持thin，`omi.decision.v4`不因底層cutover分叉。
- Acceptance：
  - Repo product consumer provider selector inventory為0。
  - HTTP/SSE/MCP對同一selection的readiness、freshness、limitations與lineage一致。
  - Provider-specific history/audit route不被Frontend、AI、MCP product flow呼叫。
  - Frontend lint/typecheck/build與必要browser desktop/mobile smoke通過。
- Validation：
  - API inventory、AI outward/public v4、MCP schema、Frontend lint/typecheck/build。
  - 必要時Browser驗證US detail、chart、Data Status與repair workflow。

### M9 — Canary、legacy removal與closure

- Scope：
  - 依序執行`off -> shadow -> compare -> canary -> on`，每階段保存mismatch、health、latency、quota與rollback證據。
  - Canary先單symbol/daily，再intraday，再priority universe；不得一次切全市場。
  - 全部consumer驗收後，移除service cross-provider fallback、legacy provider selectors、reverse imports與過期allowlist。
  - 更新current architecture docs與task closure，不把KGI/full-market/corporate-action external gate誤寫成完成。
- Acceptance：
  - Production graph只剩唯一Shared Core truth path；legacy compatibility不再接product traffic。
  - `rg`/AST guard、contract tests與runtime evidence證明無第二套resolver/fallback/registry。
  - `off` rollback不需DB migration或資料回滾，並能由official launcher/runtime驗證。
  - Source-complete、runtime-adopted、provider-live、dataset-ready、consumer-cutover分開陳述。
- Validation：
  - `scripts\run-safe-validation.ps1 -Profile backend`
  - `scripts\run-safe-validation.ps1 -Profile frontend`
  - 相關API/data smoke、official launcher restart、HTTP/AI/MCP與可見UI驗收。

## Validation matrix

| Surface | Required cases |
| --- | --- |
| Boundary | Consumer no provider choice；adapter/diagnostic exceptions bounded |
| Canonical | malformed/null/timezone/duplicate/out-of-order/provisional/final/corrected |
| Resolver | primary/fallback/both unavailable/stale/partial/conflict/lineage |
| Policy | cache_only/prefer_live/require_live/completed_session |
| Daily | requested bars/date、raw price basis、corporate-action limitation、early close |
| Intraday | premarket/regular/closing/after-hours、interval aggregation、unknown volume |
| Repair | bounds、cursor、dedupe、retry、postcondition、partial outcome |
| Health | Provider/Dataset/Resolved分離；request/persisted/effective語意 |
| DB | provider-coherent upsert、rollback、no connection held across provider IO |
| Consumer | API/AI/MCP/Frontend同一resolved semantics |
| Runtime | selected PID/port/mode、canary bound、rollback、visible UI |

## Stop-and-fix rules

- 任一 milestone 的 targeted test 或 contract smoke 失敗，先修正再進下一 milestone。
- 若 G0 任一 required contract 缺失或仍是 dark/unwired prototype，停止 M4+ 接線並在 `Progress.md` 標記 blocked；不得補一套 US-only Core。
- 若 `cache_only` 觸發 provider IO、subscription、repair 或DB write，立即停止 cutover並修正 ownership。
- 若 selected evidence 缺 provider/source/event/fetched/fallback/selection reason，保持legacy/canary，不升on。
- 若 adapter需要自行fallback才能滿足caller，表示Core port/requirement不足；回到G0，不把fallback留在adapter。
- 若 repair只證明provider call成功但postcondition未滿足，結果必須partial/failed，不得記success。
- 若 transaction owner不清楚或provider IO期間持有DB connection/transaction，停止外部smoke並先修正。
- 若 API compatibility 影響repo外consumer無法確認，保留provider-neutral新route與deprecated diagnostic route，不直接刪舊route。
- 若 canary mismatch、latency、quota、health或runtime identity超過bound，rollback到off；不擴大symbol或market scope。
- 若需要KGI login、付費API、大量quota、migration、資料刪除、commit、push或release，先取得明確授權。

## Decisions

- 2026-08-25：兩份附件作為architecture proposal與acceptance input，不視為直接修改指令；以repo current truth與實際caller graph為準。
- 2026-08-25：採兩段式計畫；先完成US-owned preparation，再以G0等待台股Shared Core final contract。
- 2026-08-25：不依目前prototype自行猜`RefreshRequirement`或operation dispatcher；缺Core契約時fail closed。
- 2026-08-25：保留現有raw provider storage與Canonical/resolved資產，採compatibility re-export與Strangler cutover，不Big Bang搬移`service.py`。
- 2026-08-25：OHLC continuity/postcondition是可保留的US dataset policy；provider choice、repair planning與scheduler acquisition必須移交Core。
- 2026-08-25：升級為long-horizon umbrella program；用A0–F3 work packages、AcceptanceMatrix、RiskRegister與CutoverRunbook管理，避免只靠對話或單一milestone清單。
- 2026-08-25：G0不以Core type存在為完成；必須對齊台股umbrella task的production-converged closure、actual-data/runtime/rollback packet與US compile-only probe。
- 2026-08-25：完整scope採per-capability/per-dataset Strangler delivery；拒絕Big Bang rewrite與全域一次切換。
