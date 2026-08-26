# 台股 Shared Data Core Pre-Commit Remediation Plan

## 狀態與目的

- 狀態：`SOURCE_COMPLETE_RUNTIME_PENDING`
- 基線日期：2026-08-26
- 分支：`codex/tw-etf-provider-normalization`
- 目的：修正已由current source重現的breadth production bug，封住stream/capability/scope contract漂移，完成current provider與quote-depth physical closure，再重新建立source checkpoint證據。
- 本計畫不授權commit、migration、runtime restart、external provider refresh或live acceptance。

## Current evidence baseline

- Git staged files：0；dirty worktree約136 entries，混有US、scheduler、DB contention、frontend US/i18n與既有TW修改。
- Source Alembic head：`20260826_0072`；user DB read-only revision：`20260825_0068`。
- 既有targeted source regression：474 tests + 21 subtests passed；本次pre-commit audit subset：56 passed。
- Legacy breadth fixture `universe=1000, classified=900, unknown=100, missing=50`可重現acquisition failed、canonical observation missing。
- ADOPT-01、LIVE-01維持`PENDING`；CLOSE-01維持`IN_PROGRESS`。

## Goal

完成一個可選擇性stage的TW source remediation checkpoint，使下列陳述同時成立：

1. Current breadth partition恰好等於universe，legacy與new payload shape都不重複計數。
2. TW intraday provider descriptor、DataRequirement、registry、catalog、health與AI使用同一canonical capability ID。
3. Realtime stream只能作presentation telemetry，無法被AI/MCP/decision誤認為canonical truth。
4. Current index/breadth production acquisition不再依賴`indices.py` legacy provider helpers。
5. `quote_depth.py`不再含provider IO、legacy quote persistence或shadow owner；capture/replay另有明確owner。
6. Debt artifact、source guards、catalog scope與frontend provider文案符合current source。

## Non-goals

- 不重寫Shared Gateway、Resolver、central quality、typed repositories或0069～0072 migrations。
- 不改completed-session official index/breadth與daily OHLCV paths。
- 不把每250～500ms stream event全部落DB。
- 不讓frontend stream資料進入研究計算、AI或MCP。
- 不整理US market、scheduler/DB contention或其他長尾dataset。
- 不執行user DB migration、launcher restart、KGI login/subscription或M5 gate。

## Proposed decisions for approval

### PD-01 — Breadth canonical partition

- Canonical `unknown_count`維持「已收到但無法分類」。
- Canonical `missing_count`維持「universe中未收到」。
- Legacy compatibility轉換：`received_unclassified=max(legacy_unknown-legacy_missing, 0)`；`not_received=legacy_missing`。
- Producer直接輸出`received_unclassified_count`與`not_received_count`，並保留legacy aggregate fields作短期compatibility。

### PD-02 — Breadth scope

- outward canonical scope改為`full_market_registered_stock_universe`，明示這是完整registered stock universe，而非viewer/subscription subset。
- catalog改為`TWSE_or_TPEX_full_market_registered_stock_universe`，同時不得宣稱exchange official full market。
- `universe_definition`明示authority、inclusion rule、instrument policy、missing policy與`official_full_market=false`。

### PD-03 — Intraday capability

- canonical capability ID統一為`intraday.bars`。
- 因user DB尚未adopt 0070且沒有正式production canonical intraday rows，本輪直接修正source，不新增永久alias debt。
- 若實作前發現已存在`market.intraday.bars` durable identity，停止並改成有退場日期的formal alias migration。

### PD-04 — Realtime stream

- stream保留sub-second depth/recent trades/auction telemetry，不要求每次callback落DB。
- backend contract強制：`projection_scope="presentation_only"`、`canonical_truth=false`、`decision_usable=false`、`research_usable=false`、`provider_specific=true`。
- headline quote、AI、MCP與decision只使用Shared Core resolved truth；frontend depth可顯示stream telemetry，但必須有清楚scope/provider標示且不得回寫或研究計算。

## Dependency order

```text
REM-00 Baseline
  -> REM-01 Breadth partition + scope truth
  -> REM-02 Intraday capability vocabulary
  -> REM-03 Realtime presentation-only boundary
  -> REM-04 Boundary debt truth
  -> REM-05 Current provider IO extraction
  -> REM-06 Quote-depth physical cleanup
  -> REM-07 Final source gate
```

每包完成後先跑該包targeted tests並更新`Progress.md`；task-owned failure不得累積到下一包。

## REM-00 — Freeze remediation baseline

狀態：`SOURCE_COMPLETE`。

範圍：

- 重讀所有預計touched files的current diff，標記使用者／US／scheduler既有hunks。
- 保存P0 reproduction、actual imports/callers、capability ID inventory與DB revision的read-only artifact。
- 確認Git index仍為空，不stage任何檔案。

Acceptance：

- touched-file ownership清楚；無法安全區分的hunk先停止。
- reproduction穩定顯示legacy breadth candidate被拒絕。
- source head 0072與user DB 0068只作read-only紀錄。

Validation：source search、AST import/caller inventory、in-memory fixture；不跑external IO。

Rollback：無production diff。

## REM-01 — Breadth partition與scope truth

狀態：`SOURCE_COMPLETE`；優先級：`P0 / MUST FIX`。

Planned boundary：

- `backend/app/market/indices.py`
- `backend/app/market/providers/tw_current_market.py`
- `backend/app/market/tw_dataset_catalog.py`
- breadth projection/schema tests

實作：

1. Legacy producer明確產生`received_unclassified_count`與`not_received_count`。
2. Adapter分開new-shape與legacy-shape parsing；legacy unknown扣除missing且clamp為0。
3. 建立partition helper或同等單一規則，禁止多處各自推算。
4. partial evidence保留facts usable，但`decision_usable=false`。
5. catalog scope改成registered stock universe；保留universe source/definition/count/coverage與limitations。

Acceptance：

- `classified + received_unclassified + not_received == universe`。
- 文件範例得到900/50/50，不被adapter拒絕。
- missing不重複、unknown不轉0、trade value missing仍truthful partial。
- complete breadth與completed official regression不變。
- catalog不再宣稱current breadth為official full market。

Targeted validation：

- `test_tw_current_market_platform.py`
- `test_market_index_daily_stats.py`
- `test_tw_market_breadth_session_contract.py`
- `test_tw_dataset_catalog.py`
- `test_tw_dataset_health.py`
- `test_tw_market_dashboard.py`

Stop-and-fix：若partition只能靠放寬canonical validator或把missing歸零，立即停止。

Rollback：只回退producer/adapter compatibility mapping與catalog wording，不改typed table或migration。

## REM-02 — Intraday capability vocabulary

狀態：`SOURCE_COMPLETE`；優先級：`P1 / MUST FIX`。

Planned boundary：

- `tw_intraday_capabilities.py`
- intraday platform/acquisition/transaction/repository tests
- shared registry、TW dataset catalog、health與AI capability guards

實作：

- 將`TW_INTRADAY_BARS_CAPABILITY_ID`改為`intraday.bars`。
- inventory所有descriptor、requirement、receipt/resource attempt、source binding、registry與fixtures。
- 新增contract test：TW descriptor、platform requirement、registry spec與catalog capability集合完全一致。
- 禁止implicit string replacement或雙向猜測。

Acceptance：

- production descriptor plan仍依priority選NStock/Yahoo。
- transaction identity、raw receipt與repository reread不因ID改名失效。
- AI selection與dataset health能以同一ID尋址。
- codebase沒有production `market.intraday.bars`殘留；若保留fixture，必須明示legacy migration用途。

Targeted validation：

- `test_tw_intraday_platform.py`
- `test_tw_intraday_migration.py`
- `test_intraday_history.py`
- `test_intraday_trend.py`
- `test_ohlc_intraday_overlay.py`
- `test_market_data_registry.py`
- `test_tw_dataset_catalog.py`
- `test_tw_dataset_health.py`
- AI capability contract subset

Stop-and-fix：若read-only user DB inventory發現durable old capability identity，不直接改名；先補formal alias/migration design。

Rollback：單一constant與相依tests可局部回退，不動0070 schema。

## REM-03 — Realtime presentation telemetry contract

狀態：`SOURCE_COMPLETE`；優先級：`P1 / MUST FIX`。

Planned boundary：

- `tw_realtime_stream_platform.py`
- realtime response schema與TypeScript type
- `useTaiwanQuoteDepth.ts`、`QuoteDepthPanel.tsx`
- AI/MCP/decision architecture guards

實作：

1. 在market-owned stream platform強制加入五個presentation-only欄位；provider port不能覆寫成true。
2. Pydantic與TypeScript使用literal/required fields，避免舊runtime靜默被當canonical。
3. Frontend headline/研究語意維持canonical quote-depth；stream只供depth/recent trades/auction telemetry。
4. UI改用payload provider動態label，並顯示「即時呈現串流／非研究證據」。
5. AST/source guard禁止`backend/app/ai/`、`agents/`與decision modules import stream platform、KGI lease port或provider stream payload。

Acceptance：

- stream payload永遠`canonical_truth=false`且兩種usability皆false。
- AI/MCP/decision source無stream依賴。
- stream depth優先只影響display rows，不改headline quote、freshness、selected provider或decision state。
- provider hardcode文案歸零；KGI仍可由payload如實顯示。
- SSE與snapshot route保持read-only，不建立subscription。

Targeted validation：

- `test_tw_realtime_stream_platform.py`
- `test_tw_realtime_viewer_lease.py`
- `test_tw_quote_depth_shared_projection.py`
- `test_taiwan_stock_quote_depth.py`
- `test_ai_outward_contract.py`
- `test_omi_mcp_server.py`
- `test_mcp_schema_contract.py`
- frontend ESLint、TypeScript、production build

Stop-and-fix：若frontend開始從stream推導research freshness/provider selection，停止並退回pure presentation contract。

Rollback：contract欄位與UI badge為additive；canonical API不需回退。

## REM-04 — Boundary debt truth

狀態：`SOURCE_COMPLETE`；優先級：`P2 / MUST FIX FOR CHECKPOINT`。

Planned boundary：cp0 debt artifact與`test_tw_data_core_boundaries.py`。

實作：

- `consumer_provider_imports`縮為current actual set，預期為空。
- generic debt test由subset改成actual與allowlist一致，讓過期allowlist也失敗。
- 保留router-specific禁止`kgi_market_data`與`kgi_superpy`測試。
- 不順便清理shared EOD transaction debt。

Acceptance：artifact與AST actual完全一致；重新引入舊router import會失敗。

Validation：`test_tw_data_core_boundaries.py`、`test_tw_quote_depth_shared_projection.py`、JSON parse。

Rollback：artifact/test單獨可回退；不影響runtime。

## REM-05 — Current provider IO physical extraction

狀態：`SOURCE_COMPLETE`；優先級：`P1 / REQUIRED FOR FULLY CONVERGED LABEL`。

Planned modules：

- `providers/twse_mis_current_index.py`
- `providers/yahoo_current_index.py`
- `providers/twse_mis_current_breadth.py`
- market-owned current provider factory/operation seam
- `tw_current_market_legacy_bridge.py`降級或移除
- `indices.py`移除current-session provider acquisition ownership

實作原則：

- provider modules只做bounded HTTP、raw parse、provider error/circuit/cache與`CurrentMarketProviderPayload`。
- StockMaster universe由market-owned universe reader提供；provider adapter不query/commit DB。
- descriptor plan仍是跨provider order/fallback唯一owner。
- application operation建立adapters後呼叫既有platform；不改Gateway、repository、transaction或Resolver。
- completed official與historical index helpers不搬、不重寫。

Acceptance：

- production current refresh call graph不import`indices as legacy`。
- `tw_current_market_legacy_bridge.py`不再是catalog operation owner。
- current MIS/Yahoo/breadth helpers不再定義於`indices.py`；current architecture guard鎖定此點。
- provider adapter無DB transaction；persist後仍mandatory reread。
- completed official、summary GET cache-only與TAIEX/TPEX semantics全過。

Targeted validation：current platform/architecture/migration、index resolution、dashboard、official index/breadth、scheduler/backfill focused tests。

Stop-and-fix：若需要改Shared Core或completed official path才能抽離IO，先停止並縮小seam，不做indices.py Big Bang。

Rollback：新provider modules先由factory切換；public routes與storage contract不變。

## REM-06 — quote-depth physical cleanup

狀態：`SOURCE_COMPLETE`；優先級：`P2 / REQUIRED FOR PHYSICAL CLOSURE`。

實作：

1. 以AST/reference inventory分類：production、capture/replay、test-only/dead。
2. 移除或把shadow comparison改成直接測canonical converters，不保留production dead owner只為測試。
3. 將contract capture/replay搬到`quote_contract_capture.py`或同等market-owned module，維持router/scheduler outward API compatibility。
4. `quote_depth.py`最後只保留Shared Core cache read與stable compatibility projection。

Acceptance：

- `quote_depth.py`無`http_get`、KGI manager import、provider fetch、legacy quote upsert、`commit/rollback`。
- scheduler capture與replay route仍正常，且GET quote-depth zero IO/commit/subscription。
- shadow/canonical comparison tests仍能從converter/platform contract驗證，不依dead production wrapper。

Targeted validation：quote-depth、MIS/KGI acquisition、shadow comparison、intraday remediation、scheduler capture、API inventory與boundary tests。

Stop-and-fix：若cleanup改變public response、capture slot identity或歷史replay可讀性，停止並先建立compatibility wrapper。

Rollback：先搬capture/replay並維持re-export，再刪dead helpers；每一步可獨立回退。

## REM-07 — Final source checkpoint gate

狀態：`SOURCE_COMPLETE`。

必要驗證：

1. REM-01～06各自targeted suites全綠。
2. Shared quality/Gateway/provider catalog regression。
3. KGI/realtime/intraday/current index-breadth/boundary/AI/MCP整合集合。
4. frontend ESLint、TypeScript、production build。
5. backend compileall、task-doc UTF-8/JSON/Markdown檢查、`git diff --check`。
6. source searches：無舊capability ID、無AI/MCP stream import、無router KGI direct import、無current legacy bridge、無quote-depth provider IO。
7. 產出exact TW checkpoint file manifest；排除US、scheduler/DB contention、其他舊文件與無關frontend hunks。

Program acceptance：

- REM packages可標`SOURCE_COMPLETE`。
- G3重新通過；CLOSE-01只升為`SOURCE_REMEDIATED_RUNTIME_PENDING`。
- Git index仍保持空，除非使用者另行明確要求selective staging/commit。
- ADOPT-01、LIVE-01仍`PENDING`。

Final stop conditions：

- 任一task-owned failure、scope/partition不實、provider/consumer boundary倒退、trial leak或GET side effect。
- full-suite無關failure可隔離記錄，但不能掩蓋targeted failure。
- 未取得明確授權不得migration user DB、restart runtime、commit或push。

## Execution handoff

本輪已依序完成REM-00～REM-07；source checkpoint完成後仍須維持下列handoff紀律：

- `ExecutionBoard.md`
- `Progress.md`
- `RiskRegister.md`
- `DecisionLog.md`（將對應PD轉為accepted/rejected）
- `artifacts/wp-rem-<id>-source-20260826.json`

不得一次修改全部檔案後才測試；REM-01失敗時不進REM-02。
