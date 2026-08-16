# 執行計畫

## Execution model

- 本輪先完成 planning artifacts；不修改 production source。
- 使用者指示開始後，依 Milestone 0 → 7 連續執行。每個 milestone 都要先達 acceptance 才能前進，並同步更新 `Progress.md`。
- 優先修「真相與成功判定」，再開啟自癒行為：canonical index、budget、health lifecycle、quote scope、expected-date postcondition 都穩定後，才啟用 repair loop。
- 每個功能形成局部、可審查、可回退的 patch boundary；commit candidate 只記錄範圍，不等同獲得 commit/push 授權。
- 測試由最小 targeted regression 開始，穩定後再跑 safe backend profile、consumer checks 與經授權的 runtime adoption。

## Milestones

### 0. Integration baseline 與 outward contract inventory

- Scope：Git/worktree、產品文件、相關 route/service/job/schema/tests、DB 唯讀 evidence、launcher/runtime 現況。
- Work：
  - 保存 branch、HEAD、`git status --short` 與所有 target-file pre-existing diff；標示哪些 hunk 不屬於本專案。
  - 盤點 direct index、summary、AI `market.indices`、source-health、quote scheduler、daily refresh、decision envelope、Frontend/MCP consumers 的完整呼叫鏈。
  - 保存 backend public manifest 與 MCP offline snapshot digest/count baseline。
  - 以唯讀查詢保存代表性 index/date、source-health lifecycle、quote universe、job result/expected-date fixture；不 refresh、不寫 DB。
  - 確認 launcher-selected URL、listener 與 process owner；若 runtime 不存在，只記錄 unavailable，不在本 milestone 自動啟動。
- Acceptance：
  - 每個修改面都有 owner、existing tests、pre-existing diff 與 outward consumer inventory。
  - 六項根因均有可重現 fixture 或 source-level evidence。
  - 沒有把目前 dirty work 誤算成新專案變更。
- Validation：
  - `git status --short --branch`
  - `git diff --name-only` 與 target-file scoped diff
  - read-only SQLite queries
  - `/api/system/health`、`/api/ai/tools`（僅在已存在的正確 runtime 可用時）

### 1. Canonical Taiwan index truth

- Scope：`backend/app/market/indices.py`、AI Taiwan market context、index persistence/source-health projection、相關 schemas/tests。
- Work：
  - 把 provider/cache 候選取得整理為 bounded acquisition layer，把 candidate selection 寫成 pure resolver。
  - 定義 `cache_only`、`prefer_live`、`require_live` policy；公開 timeout、fallback、reason code 與 zero-IO cache-only invariant。
  - 定義 canonical resolution：market/index id、session、trade date、official close、current observation、series、selected source/provider、quality、limitations、`resolution_id`。
  - direct route、summary、AI `market.indices` 與 scheduler/persistence 全部消費同一 resolved output；禁止 consumer 二次選源。
  - Persist exact resolved snapshot，使用 monotonic/as-of guard 避免舊資料覆蓋新資料。
- Acceptance：
  - 同 fixture 下 direct/summary/AI 回傳同一 trade date、observation、provenance 與 resolution identity。
  - 昨日 close、TPEX post-close sample、stale cache 與 live candidate 的優先序由 session-aware pure test 證明。
  - `cache_only` provider mock call count 為 0；provider failure 保留 truthful fallback/limitation。
  - 現有 public routes/fields 保持相容，新增欄位為 additive。
- Validation：
  - `backend/tests/test_taiwan_index_provider_adapters.py`
  - `backend/tests/test_tpex_index_intraday.py`
  - `backend/tests/test_taiwan_index_contract_snapshot.py`
  - `backend/tests/test_market_index_daily_stats.py`
  - 新增 resolver purity、cross-route parity、persistence monotonic tests

### 2. Response budget provenance 與 adaptive ceiling

- Scope：`backend/app/ai/capability_contract.py`、`backend/app/ai/decision_envelope_v4.py`、AI schemas/public contract/MCP snapshot、相關 tests。
- Work：
  - 在 normalized selection 保存 requested/default/effective limit 與來源：caller explicit hard limit 或 payload default adaptive。
  - 為 summary/compact/standard/full 設定 bounded adaptive ceilings；不得直接提升至全域 1 MiB max。
  - 以 final serialized envelope byte size 作為判定面，包含 required core、status、limitations 與 metadata。
  - 對 default request 先使用既有 slim projection/optional section trimming；必要時提供 visible continuation，而非刪除 required evidence。
  - Explicit caller limit 永遠是 hard limit；超限時回 predictable、可機器判讀的 outcome。
- Acceptance：
  - 代表性 market-overview default compact request 可完成且保留 required core/status/limitations。
  - 同一 payload 在 caller explicit 小 limit 下仍按 hard limit 拒絕或縮減，不被 adaptive logic 放大。
  - `requested_max_response_bytes`、`effective_max_response_bytes`、limit source/trim/continuation reason 可追溯（實際命名依既有 contract pattern）。
  - Backend manifest、MCP offline snapshot 與 online schema parity。
- Validation：
  - `backend/tests/test_ai_capability_contract.py`
  - `backend/tests/test_ai_decision_envelope.py`
  - `backend/tests/test_ai_outward_contract.py`
  - `backend/tests/test_mcp_schema_contract.py`
  - 新增 default-vs-explicit 與 final-serialized-size boundary tests

### 3. Operational/historical source-health lifecycle

- Scope：`backend/app/observability/provider_health.py`、`backend/app/ai/market_context/source_health_context.py`、source-health route/schema、active provider/scope registry、相關 tests。
- Work：
  - 定義 logical scope key 與 provider generation；由既有 active registry/config 決定目前 required providers/targets，不建立平行設定真相。
  - 將 current operational canonical records 與 historical target/provider generations 分流。
  - 修正 lifecycle 優先序：canonical `target=all` 過期時仍是 operational stale；退出 active scope/generation 才是 historical。
  - 保留 legacy `problem_count` 語意或明示 deprecation；additive 提供 operational/historical entry/problem counts 與 active/expired target-specific counts。
  - `include_historical` 與 scope filter 使用 additive/versioned query contract；不讓預設 view 被 zombie records 污染。
- Acceptance：
  - 測試同時覆蓋 active stale `target=all`、old target-specific、old provider generation、current provider fallback 與 missing registry 情境。
  - 預設 AI/source-health projection 只以 operational problems 判斷目前狀態，歷史問題仍可查詢及稽核。
  - Legacy callers 不因 count 欄位被偷偷重新定義而行為改變。
- Validation：
  - `backend/tests/test_source_health_contract.py`
  - `backend/tests/test_market_source_health.py`
  - `backend/tests/test_ai_freshness_guard.py`
  - `backend/tests/test_ai_market_context_projection.py`
  - read-only fixture query 對帳 operational/historical counts

### 4. Quote freshness 三軸契約

- Scope：market source-health quote projection、quote contract scheduler、provider events/circuit status、Frontend 更新狀態 projection、相關 tests。
- Work：
  - 拆分 `request_live`、`scheduler_contract`、`provider_availability`，各自有 status、as-of、scope 與 reason。
  - Scheduler contract 固定記錄 universe/source、symbol-set digest、requested/captured/failed count、coverage ratio、latest required/observed slot、missing symbols/slots。
  - 無 stock id 的 health 不再從整張 quote table 任取一列冒充 `target=all`；若 universe 只是 watchlist/bounded symbols，target 必須 truthful。
  - Provider availability 由 ProviderEvent/circuit/adapter evidence 建立，不從單一 quote row 反推。
  - Frontend 若需呈現，只接入既有「更新狀態」流程，不新增重複 inline error banner。
- Acceptance：
  - 一個 09:05 成功 row 不足以讓 20-symbol contract 全綠；coverage 與 missing detail 會正確反映。
  - Request-live 成功、scheduler partial、provider degraded 等混合情境可同時表達，不互相覆蓋。
  - `target=all` 僅在已定義且完成驗證的全域 universe contract 下出現。
- Validation：
  - `backend/tests/test_tw_quote_components.py`
  - `backend/tests/test_intraday_contract_remediation.py`
  - `backend/tests/test_market_source_health.py`
  - `backend/tests/test_taiwan_stock_detail_scheduler.py`
  - 新增 universe digest、coverage、slot/missing、three-axis mapping tests

### 5. Expected-date outcome truth 與 bounded self-healing

- Scope：`backend/app/jobs/scheduler.py`、`backend/app/market/daily_metrics_backfill.py`、job result/status、repair orchestration/source-health metadata、相關 tests。
- Work：
  - 將 release-aware `expected_trade_date` 明確傳入 worker；worker 不再以 stale `MarketDailyPrice` latest date 作為目標真相。
  - 為 required datasets/providers 定義 postcondition：observed max trade date、fetched/skipped counts、provider result、coverage 與 failure reason。
  - Job status 由 postcondition 決定；task 沒例外但未達 expected date時只能是 partial/failed，不得 success。
  - 在 outcome truth 穩定後新增 repair controller：bounded target/date/dataset、dedupe key、lease/idempotency、backoff、max attempts、circuit awareness 與 startup reconciliation。
  - 寫入 repair ledger/metadata，包含 detected_at、attempt、next_retry_at、last_error、resolved_at、source/provider；投影到 source health。
- Acceptance：
  - 2026-08-13 expected、DB 只到 2026-08-12、provider 回空資料的 fixture 會得到 failed/partial，而不是 success。
  - 休市日、官方尚未發布、provider 短暫失敗、provider circuit open、重啟後未完成 job、重複 scheduler tick 均有 deterministic tests。
  - 同一 repair key 不會併發重複執行；達 max attempts 後停止並保持可見，不形成 retry storm。
  - GET/read path 只讀 repair 狀態，不直接執行 repair。
- Validation：
  - `backend/tests/test_taiwan_stock_detail_scheduler.py`
  - `backend/tests/test_calendar_status_integration.py`
  - 新增 daily-metrics expected-date/postcondition、repair dedupe/backoff/startup reconciliation tests
  - read-only job/result query 對帳 expected vs observed date

### 6. Additive status taxonomy 與 consumer sync

- Scope：backend outward schemas/mapping、AI v4 evidence/answer、source-health/status projection、必要 Frontend types/rendering、MCP snapshot。
- Work：
  - 定義 `service_status`、`data_quality`、`decision_readiness`、`provider_status` 的 enum、優先序、reason codes 與 evidence inputs。
  - 建立 backend-owned mapping table；同一 evidence 在 direct API、AI、Frontend proxy 與 MCP 使用相同結果。
  - 保留既有 `status`、`problem_count`、`evidence.capability_status`；新增欄位只做 additive projection。
  - Frontend/MCP/Kuro consumer 不重算 freshness/readiness；缺新欄位時保有 legacy fallback。
- Acceptance：
  - `service_status=available` 可與 `data_quality=stale`、`decision_readiness=blocked/limited` 同時存在。
  - Provider failure、partial coverage、stale data、missing required dataset 的 mapping 有 table-driven tests。
  - Public snapshot digest parity，舊 consumer fixture 不 break。
- Validation：
  - `backend/tests/test_source_health_contract.py`
  - `backend/tests/test_ai_outward_contract.py`
  - `backend/tests/test_ai_freshness_guard.py`
  - `backend/tests/test_omi_mcp_server.py`
  - `backend/tests/test_mcp_schema_contract.py`
  - 若修改 Frontend：`npm run lint` 與 `npm exec tsc -- --noEmit --incremental false`

### 7. Integrated regression、runtime adoption 與交付

- Scope：所有 touched modules、public contract snapshot、launcher-selected backend/frontend、MCP runtime、代表性 outward behavior、任務文件。
- Work：
  - 先跑所有 milestone targeted tests，再跑 safe backend profile；只在實際 frontend code 有變動時跑相應 checks/build。
  - 重建由 backend generator 擁有的 MCP snapshot，驗證 digest/count/schema parity；不得手工維護第二份 contract。
  - 若使用者明確授權 runtime adoption，透過 official launcher/Control Center 做 component-scoped restart；先驗證 exact owner/path/listener，不 broad-kill process。
  - 驗證 direct API、AI default/explicit budget、index parity、source-health lifecycle、quote scope、repair outcome 與 MCP session-preserving protocol。
  - 更新 `Progress.md` 的 final evidence、remaining risks、patch/commit candidates；不自動 commit/push。
- Acceptance：
  - Targeted tests 與 `run-safe-validation.ps1 -Profile backend` 通過，或任何 pre-existing unrelated failure 有明確隔離證據。
  - Runtime adoption（若授權）同時證明 source/build identity、process lineage、listener、health、contract digest 與代表性 outward behavior；HTTP 200 或 PID replacement 單獨不算通過。
  - MCP 完成 `initialize -> notifications/initialized -> tools/list -> tools/call`，retained `Mcp-Session-Id`，schema digest 與 backend 一致。
  - 沒有未授權 external bulk refresh、DB destructive action、runtime restart、commit 或 push。
- Validation：
  - `.\scripts\run-safe-validation.ps1 -Profile backend`
  - 必要時 `.\scripts\run-safe-validation.ps1 -Profile frontend`
  - `/api/system/health`、`/api/system/provider-events?limit=20`、`/api/system/source-health-snapshots?market=tw`、`/api/ai/tools`
  - 代表性 direct index API 與 `omi.decision.v4` default/explicit budget probes
  - Session-preserving MCP smoke

## Stop-and-fix rules

- 任一 targeted test、contract snapshot parity、compile/typecheck 或 outward invariant 失敗，先修正再進下一個 milestone。
- 若 direct API、AI、Frontend proxy 或 MCP 對同一 index/date/freshness 給出不同 backend semantics，停止 consumer rollout，回到 canonical resolver/mapping 修正。
- 若 required dataset 未達 expected trade date但 job 仍 success，禁止啟用 repair loop。
- 若自癒行為可能造成 retry storm、重複 job、無界 provider IO、付費 quota 或 DB 污染，立即停用/不啟用並修正 bounded policy。
- 若 additive contract 會無聲改變既有 `status`、`problem_count`、route 或 MCP shape，先補 compatibility layer 與 regression，不直接 breaking cutover。
- 若現有 dirty hunk 與本專案重疊，先讀懂並記錄 owner/意圖；不得 revert、覆寫或用大範圍 rewrite 消除衝突。
- 若需要 schema migration、跨 repo Kuro 修改、正式 runtime restart、commit/push 或大量 external refresh，而未取得對應授權，暫停並請求使用者確認。
- 若 runtime health 200 但 build/contract/version/代表性 outward behavior 未採用新邏輯，狀態維持「source complete, runtime not adopted」。
- 若新證據推翻 Prompt.md 的根因或安全假設，先更新 Prompt/Plan/Progress 與理由，再繼續實作。

## Validation matrix

| Surface | 必要證據 |
|---|---|
| Index truth | Pure resolver、policy zero-IO、provider fallback、direct/summary/AI parity、persistence monotonic |
| Time/session | Trading calendar、expected/released date、盤中/盤後/休市、official close vs current observation |
| Budget | Caller explicit provenance、payload adaptive ceiling、final serialized bytes、required core preservation |
| Source health | Active scope/generation、operational/historical counts、canonical stale all-target、legacy compatibility |
| Quote freshness | Request/scheduler/provider axes、universe/digest、coverage、slot/missing detail |
| Jobs/repair | Expected-date postcondition、strict success、dedupe/backoff/max attempts/circuit/startup reconciliation |
| Status | Service/data/decision/provider mapping、reason codes、consumer parity |
| Public contract | Backend manifest、MCP offline/online schema、digest/count、legacy consumer fixtures |
| Runtime | Official owner/path、PID/listener/start time、health、contract、代表性 API/MCP outward behavior |

## Decisions

- 2026-08-14：先建立長專案文件，production implementation 等待使用者下一步指示。
- 2026-08-14：scheduler 根因定義為 expected-date/outcome false-success；既有 startup catch-up 保留並修正，不另造平行 scheduler。
- 2026-08-14：canonical index 採 acquisition/resolution 分離；pure resolver 是 direct/summary/AI/persistence 的共同真相。
- 2026-08-14：response budget 保留 explicit hard limit；default adaptive 只能在 payload-level ceiling 內調整。
- 2026-08-14：source health 以 logical scope + active generation 分 operational/historical；過期不等於 historical。
- 2026-08-14：quote freshness 分 request-live、scheduler-contract、provider-availability，不再以單列 quote 代表全域。
- 2026-08-14：先修 job outcome truth，再啟用 bounded self-healing。
- 2026-08-14：status taxonomy additive/versioned，consumer 不重算 backend semantics。
- 2026-08-14：目前只建立 patch boundaries，不 commit、不 push、不正式 restart。
