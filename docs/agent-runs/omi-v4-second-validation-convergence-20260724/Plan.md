# Plan

## Milestones

1. Baseline 與任務契約
   - Scope：固定第二輪 12 項問題、目前已修正項目、consumer boundary 與驗證矩陣。
   - Acceptance：`Prompt.md`、`Plan.md`、`Progress.md` 可讓後續工作無需依賴對話重建。
   - Validation：UTF-8 讀回、相關檔案與 tests inventory、`git diff --check`。

2. P0 narrative、payload semantics 與 selected freshness
   - Scope：multi-domain answer profile、ownership normalization、
     semantic-empty quality、selected/supplemental gap separation。
   - Acceptance：三個 P0 都有 producer-to-final regression。
   - Validation：
     `backend/tests/test_ai_answer_composer.py`,
     `backend/tests/test_ai_capability_contract.py`,
     `backend/tests/test_ai_public_v4_contract.py`。

3. US intraday contract
   - Scope：tool capability merge、open-session classification、stale facts
     usability、legacy intraday limit mapping。
   - Acceptance：planner、realtime、quality、projection 與 reconciliation 都以同一
     capability set 運作。
   - Validation：
     `backend/tests/test_ai_realtime_contract.py`,
     `backend/tests/test_ai_tool_boundaries.py`,
     `backend/tests/test_ai_public_v4_contract.py`。

4. Source Health contract
   - Scope：total/returned problem counts、snapshot age/TTL、progressive payload
     degradation。
   - Acceptance：bounded compact 與 oversized standard 都保留可判讀 summary，
     freshness 由 snapshot age 決定。
   - Validation：
     `backend/tests/test_ai_capability_contract.py`,
     `backend/tests/test_ai_public_v4_contract.py`,
     `backend/tests/test_provider_health.py`。

5. Passport consistency 與 response budget priority
   - Scope：consumer-facing passport 以 canonical quality/realtime 為準；
     contradiction debug routing；brief 先裁 diagnostics/execution，再摘要 evidence。
   - Acceptance：同 capability 不再 ready/blocked；32 KiB brief 保留核心摘要。
   - Validation：
     `backend/tests/test_ai_decision_envelope.py`,
     `backend/tests/test_ai_public_v4_contract.py`,
     `backend/tests/test_ai_outward_contract.py`。

6. Full validation 與 runtime handoff
   - Scope：compile、targeted/full backend、HTTP representative calls、payload bytes、
     freshness/realtime/business-error spot checks。
   - Acceptance：所有 done criteria 有 test 或 live evidence；任何未完成項目明確隔離。
   - Validation：
     `.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs <targeted tests>`
     與 launcher-selected `/api/ai/tools`、`/api/ai/ask`。

## Stop-and-fix rules

- 任一上一輪已通過的 tool result ingestion、capability projection、MCP business
  error 或 target rejection regression，先修正再繼續。
- 任一 stale／missing／supplemental gap 被轉成 ready、current 或 zero，停止該
  milestone。
- 任一 explicit `selection.limits` 被 legacy alias 覆蓋，停止 limit rollout。
- 任一 market-open observation 被分類成 completed session，不得宣稱 realtime
  milestone 完成。
- 任一 response 超過 `max_response_bytes` 或核心 evidence 被無聲省略，不得宣稱
  budget milestone 完成。
- 外部 provider probe 必須 bounded；不為驗證啟動全市場 refresh、付費 LLM 或
  DB destructive operation。
- 保留既有 dirty worktree，不 reset、不 checkout、不做無關格式化。

## Decisions

- 2026-07-24：延續現有 v4 task line，不建立 v5 或 consumer-specific envelope。
- 2026-07-24：multi-domain answer profile 由 selected capabilities／requested
  domains 決定；primary intent 只作排序與局部語氣提示。
- 2026-07-24：facts usability 與 decision usability 分離；stale、有 provenance、
  structurally complete 的歷史 observation 仍可作事實引用。
- 2026-07-24：legacy `market_data_params` 只作 request normalization，
  canonical selection 才是 outward execution contract。
- 2026-07-24：Source Health 與 brief 使用 capability-aware progressive
  degradation，不直接優先 omitted 整個 capability。
