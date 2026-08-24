# Plan

## Milestones

1. C0 — Contract correctness
   - Scope：interval propagation、Yahoo extended-hours volume、US early-close calendar與Canonical projection。
   - Acceptance：HTTP／MCP requested interval等於effective interval；unknown volume不再是0；early-close finalization正確。
   - Validation：`cd backend; ..\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider tests\test_intraday_contract_remediation.py tests\test_us_intraday_aggregation.py tests\test_us_market_data_canonical_adapters.py tests\test_us_close_session_contract.py tests\test_trading_calendar.py -q`

2. C1 — Resolver與provider ownership
   - Scope：provider session eligibility、selected session、US daily priority single owner、stable resolved daily read seam。
   - Acceptance：policy使用requirement session；resolved outward保留session；Research／Watchlist不自行決定provider或adjusted basis。
   - Validation：`cd backend; ..\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider tests\test_market_data_provider_policy_v2.py tests\test_market_data_resolution.py tests\test_us_market_data_provider_policy.py tests\test_us_market_data_canary.py tests\test_us_market_research_service.py tests\test_us_market_data_outward_contract.py -q`

3. C2 — Selection-bounded Research／AI consumer
   - Scope：selected capability dependency map、US reader gating、supplemental warning隔離、MCP thin forwarding。
   - Acceptance：explicit intraday selection只執行identity／intraday／freshness所需readers；無關SEC／profile／ownership／coverage缺口不進selected warnings。
   - Validation：`cd backend; ..\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider tests\test_ai_tool_boundaries.py tests\test_ai_capability_contract.py tests\test_us_market_data_outward_contract.py tests\test_omi_mcp_server.py -q`

4. C3 — Rollout與runtime adoption
   - Scope：`canary`／`on` modes、symbol allowlist、fail-closed mode identity、launcher persistence與rollback。
   - Acceptance：mode／allowlist可由official launcher重啟後重現；canary不合格不回canonical selected result；off rollback可驗證。
   - Validation：targeted config／shadow／runtime tests、`scripts\run-safe-validation.ps1 -Profile backend`、launcher restart與health／HTTP／MCP smoke。

5. C4 — Docs與closure evidence
   - Scope：Progress、current architecture、remaining external gates與驗證證據。
   - Acceptance：source-complete、runtime-adopted、provider-live與full-market-ready分開陳述；沒有把blocked gate寫成完成。
   - Validation：UTF-8 readback、`git diff --check`。

## Stop-and-fix rules

- 任一targeted regression失敗，先修正再進下一milestone。
- 若interval修復需要cache-only path啟動provider fetch，停止並改為cache aggregation／明確unavailable。
- 若extended-hours volume無法證明available，保持`null/provider_unavailable`，不以0補值。
- 若early-close規則和official calendar不一致，使用versioned explicit override並保持unknown，不猜測。
- 若provider/session schema變更破壞TW／JP／KR既有descriptor，採additive default與compatibility test，不做Big Bang rewrite。
- 若canary／on無法證明effective runtime identity或bounded symbol，fail closed回`off`，不得默默啟用。
- 若需要external quota、KGI login、DB migration、commit、push或release，先停下取得額外授權。

## Decisions

- 2026-08-23：把附件當issue hypotheses與acceptance inputs，不把文件內建議視為執行指令。
- 2026-08-23：code closure與external data readiness分開；corporate-action、full-market universe及KGI entitlement不靠placeholder關閉。
- 2026-08-23：先修outward correctness，再做ownership與rollout，避免在錯誤contract上切換production mode。
