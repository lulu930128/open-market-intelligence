# Plan

## Delivery strategy

本任務採 gated rollout。每個 milestone 可獨立停止、rollback 或維持 shadow；不以「所有階段都上線」作為成功前提。若資料或驗證不支持正式分類，保留 truthful `insufficient_data`／no-go 即是正確結果。

## Milestones

### 0. Freeze contract and integration baseline

- Scope:
  - 確認 `Prompt.md`、`CapabilityContract.md` 與 current product/architecture truth 一致。
  - 確認目前 dirty worktree 的 owner、Alembic head、`20260822_0064` 狀態與相關 AI/Foundation changes。
  - 確認新 task 使用的 feature flags、job IDs、methodology version naming 與 outward capability IDs。
- Acceptance:
  - 不和既有 Market Data Foundation、portfolio、EOD coverage changes 產生 migration/revision collision。
  - `broker_branch.summary` current contract snapshot、API route、AI projection 與 scheduler owners 有 baseline inventory。
  - source/license gate 被記錄；沒有暗示已取得 nStock redistribution permission。
- Validation:
  - `git status --short --branch`
  - `rg -n "broker_branch.summary|broker_branch_trade_daily|20260822_0064" backend docs agents`
  - `..\.venv\Scripts\python.exe -m alembic heads`（從 `backend` 執行，僅在實作開始時）
- Stop condition:
  - 若 migration head 或 capability registry 正在被其他未整合工作修改，先隔離 worktree/branch 或等待 owner 收斂，不直接疊改。

### 1. V0 observation and snapshot-quality foundation

- Scope:
  - 抽出 provider-neutral `BrokerBranchObservationBatch` 與 pure conversion seam。
  - 新增 `broker_branch_snapshot_quality` model/migration。
  - 讓 successful empty、partial、invalid、provider-date mismatch 與 provider failure 可保存／查詢。
  - derived observation 正規化 zero-lot average price；保留 raw payload/rows。
  - market coverage 改以 snapshot-quality truth 判斷，不只看 trade-row existence。
- Acceptance:
  - nStock normal snapshot 永遠是 `coverage_mode=ranked_top_n`、`coverage_status=censored`、`absence_semantics=unknown_not_ranked`。
  - empty/malformed/failure 不互相混淆，且不 destructive replace 已有成功 rows。
  - force/retry/idempotent path 不產生 duplicate selected state；commit failure rollback。
  - `broker_branch.summary` response/projection regression 全部保持相容。
- Validation:
  - 從 `backend`：`..\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests\test_broker_branch_quality.py tests\test_broker_branch_market_refresh.py tests\test_database_migrations.py`
  - `..\.venv\Scripts\python.exe -m compileall app\market app\db`
  - Repo root：`.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs @('backend\tests\test_broker_branch_quality.py','backend\tests\test_broker_branch_market_refresh.py','backend\tests\test_database_migrations.py')`
- Rollback:
  - Disable quality-selected read seam；downgrade only the new table；retain raw rows and summary path。

### 2. Shadow behavior feature engine

- Scope:
  - 建立 pure event pairing、censoring、feature calculation、Wilson intervals 與 price-context join。
  - 新增 methodology registry 和 `broker_branch_behavior_feature_snapshot` migration/model。
  - 新增 bounded derived job：target=`trade_date + methodology_version`，max lookback 120 sessions。
  - 以 `ENABLE_BROKER_BRANCH_BEHAVIOR_SHADOW=false` 作預設 rollout gate。
- Acceptance:
  - `not_ranked` 不進 same/opposite denominator，也不變成 zero。
  - `reverse_given_reappearance`、`same_direction_given_reappearance`、`reappearance`、`censored` numerators/denominators 可審計重算。
  - `as_of=T` 不讀 `T+1` 以後資料；Taiwan session calendar 對齊。
  - price missing 只讓 price-context partial；flow-only 保留。
  - 同 input fingerprint + methodology 重跑 idempotent；coverage 改善或 methodology 改變會產生新的 selected snapshot。
  - Job 不呼叫 provider、不在 read path 計算、不掃全歷史。
- Validation:
  - 從 `backend`：`..\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests\test_broker_branch_behavior.py tests\test_broker_branch_behavior_job.py tests\test_database_migrations.py`
  - Bounded benchmark：25-session 現有資料、synthetic 120-session fixture、affected-stock incremental case。
  - `EXPLAIN QUERY PLAN` 驗證後才決定是否增加 composite index。
- Stop condition:
  - 若結果仍需依賴把 absent 當 0，或日常 compute 只能靠無界全表掃描，停止並重做 contract/query design。

### 3. Data-readiness and calibration gate

- Scope:
  - 建立 read-only calibration/report script，不修改 raw/derived DB。
  - 定義 frozen training window、validation window、minimum sessions/stocks/reobserved denominator、concentration 與 stability metrics。
  - 比較 deterministic candidate weights，而不是預先採用 v1 文件示例權重。
- Acceptance:
  - `<60` high-coverage sessions 只能 exploratory；`<120` 不得 production classify。
  - Candidate class 在不同月份、market regimes、stock liquidity buckets 與 branch concentration buckets 有可解釋穩定性。
  - 報告同時呈現 censoring、coverage、interval、class drift、unclassified rate 與失敗樣本。
  - 如果無法建立穩定 class，明確決定只保留 feature evidence，不用 primary class。
- Validation:
  - Reproducible calibration command（實作時寫入精確 script/arguments）。
  - Walk-forward、no-look-ahead、threshold freeze tests。
  - 第二次獨立 rerun 產生相同 input fingerprint/result。
- Stop condition:
  - 若結果只在 in-sample 好看、對 censoring/流動性敏感或 class drift 過大，behavior classification 保持 disabled。
- 2026-08-22 outcome:
  - 已完成 `broker_branch.behavior.readiness_report.v0`、frozen `calibration_policy.v0`、profile denominator/concentration gates、purged/embargo walk-forward split planner、aggregate-only Markdown/JSON renderer 與唯讀 CLI。
  - Live rerun 對 25 個 high-coverage sessions 判定 `exploratory_only`／`shadow_only`，可規劃 split 為 0，`validation_results_present=false`；Milestone 3 以可重現 no-go 結論完成，未比較 candidate weights 或建立 primary class。
  - Evidence fingerprint `41e55b2fd78cded32c1c3dd531d22321182f34d2bf0aad4aab0d90bbb4defbdd`；第二次 rerun 相同，且 operational `computed_at` 不參與 evidence identity。

### 4. `broker_branch.behavior` outward capability

- Dependency: Milestone 3 production-candidate gate 通過，或使用者明確接受只 outward `insufficient_data`/feature-only preview。
- Current gate: **not entered**。25-session evidence 未達 60-session calibration 與 120-session production-candidate 門檻，且使用者未要求 feature-only outward preview；保持未 advertised。
- Scope:
  - 更新 capability contract、domain mapping、resolution derived dependencies、dataset lifecycle、freshness projection、field allowlist、payload budget 與 public contract snapshots。
  - 增加 backend context reader；只讀 derived snapshots，不在 AI layer 算 features。
  - 更新 query plan、answer composer、HTTP/SSE/MCP parity；summary path 保持原樣。
  - Feature flag `ENABLE_BROKER_BRANCH_BEHAVIOR_CAPABILITY=false` 預設關閉，先 canary。
- Acceptance:
  - `advertised => projection exists` 通過。
  - Manifest、quality、freshness、limitations、source refs、methodology 與 payload status 一致。
  - Pure broker behavior 問題不載入 fundamentals；multi-domain selection 不丟 capability。
  - `insufficient_data` 不產生 fabricated class；Chinese answer 不使用「確認隔日沖」。
  - cache-only API/MCP 不觸發 raw refresh/derived job。
- Validation:
  - 從 `backend`：`..\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests\test_broker_branch_behavior_contract.py tests\test_ai_capability_contract.py tests\test_ai_capability_resolution_registry.py tests\test_ai_outward_contract.py tests\test_ai_decision_envelope.py tests\test_ai_answer_composer.py`
  - API contract inventory 與 MCP snapshot tests。
  - Fresh runtime canary：selected PID/port、`/api/ai/tools`、cache-only behavior ask、MCP representative call。
- Rollback:
  - Disable capability flag；保留 shadow snapshots；summary path不變。

### 5. Dimensionless flow-risk capability

- Dependency: Behavior capability calibration validated，且另有 prospective validation design。
- Current gate: **not entered**。沒有 validated behavior classification 或 prospective OOS window，不建立 risk score/table/API。
- Scope:
  - 建立 `broker_branch.flow_risk` methodology，輸出 risk index、visible lots、observed opposite flow、components 與 limitations。
  - 不新增 estimated lots，不使用 confirmed unwind/inventory。
  - 需要保存 snapshot 時才新增獨立 migration/table；先用 pure projection prototype 驗證需求。
- Acceptance:
  - Risk score 0–100 是無量綱 ranking/index，documentation/AI/UI 全部一致。
  - 每個 contributor 可追到 versioned branch feature snapshot 與 raw source refs。
  - `not_ranked` 不算 unwind；opposite flow 不叫 confirmed close。
  - Coverage/history/calibration 不足時 `decision_usable=false`。
- Validation:
  - `tests\test_broker_branch_flow_risk.py`
  - Capability projection、freshness、payload budget 與 answer contract tests。
  - Prospective shadow result 至少跨一個事先凍結的 validation window。
- Stop condition:
  - 若 score 被誤解為張數/機率，或無法在不同 liquidity bucket 穩定，保持 internal shadow。

### 6. Radar and frontend integration

- Dependency: Milestone 5 out-of-sample gate 通過。
- Current gate: **not entered**。沒有 flow-risk OOS evidence，不修改 Radar、frontend、MCP 或 Kuro。
- Scope:
  - Radar 只消費 backend flow-risk/behavior contract，作可見 counter-evidence。
  - 個股分點區新增行為與短期 flow-risk panel，清楚顯示 Top15 截尾與資料門檻。
  - Error/partial/stale 走共享更新狀態，不新增互相競爭的 inline error owner。
- Acceptance:
  - Radar 相對既有 technical/volume baseline 有事先定義、可重現的 incremental lift；沒有 lift 就不改 Radar decision weight。
  - Low-quality/partial/insufficient behavior 不升降 Breakout/Support Quality。
  - Desktop/mobile 可讀，沒有文字溢出、重複控制或 consumer-side formula。
  - UI 顯示 index、observed lots、history/calibration/coverage，且不寫成必然賣壓。
- Validation:
  - Backend Radar regression 與 prospective evaluation。
  - Repo root：`.\scripts\run-safe-validation.ps1 -Profile frontend`
  - Browser screenshot/DOM、console errors、representative partial/stale/insufficient cases。
- Rollback:
  - 關閉 UI/Radar feature flag；backend capabilities 可獨立保留。

### 7. Runtime acceptance and documentation closure

- Scope:
  - 執行 migration、shadow/canary job、API/MCP/UI 分層驗收。
  - 更新 current architecture/product docs only if long-term truth actually changed。
  - 記錄 source/license limitation、runtime config、rollback、operator diagnostics。
- Acceptance:
  - Migration head、runtime code identity、selected port/PID、job result 與 outward behavior 均為同一 build。
  - Raw source current／partial、derived current／lagged、methodology mismatch 與 cache-only cases都有 runtime evidence。
  - Public artifacts 不含本機 DB、raw payload、third-party production data 或 secrets。
- Validation:
  - `.\scripts\run-safe-validation.ps1 -Profile backend`
  - 若 frontend 已改：`.\scripts\run-safe-validation.ps1 -Profile frontend`
  - Fresh runtime API/MCP/UI smoke；不以 health endpoint alone 代替 outward proof。
- 2026-08-22 closure scope:
  - V0 migration、shadow job 與 runtime adoption 已在 Milestone 0–2 驗收；本輪新增 surface 只有離線唯讀 report module/CLI，沒有 runtime API/UI contract 變更，因此不重啟 production runtime。
  - Status／boundary closure 記錄於 `BoundaryReport.md`；M4–M6 保留 gated，而不是描述成已完成。

## Cross-cutting validation matrix

| Boundary | Required evidence |
| --- | --- |
| Provider/parser | fixture normal/empty/malformed/timeout/rank drift |
| Quality | censored/partial/invalid/failure/ready-empty guard |
| DB | Alembic upgrade/downgrade、idempotency、rollback、raw preservation |
| Features | denominators、intervals、session alignment、no look-ahead |
| Scheduler/job | bounded scope、fingerprint、partial recompute、retry |
| Freshness | raw vs derived vs methodology dates |
| Capability | derived dependencies、projection、manifest、field/limit budget |
| AI/transport | query intent、answer wording、HTTP/SSE/MCP parity |
| Consumer | no recompute、truthful warning、responsive UI |
| Runtime | exact process/build、migration、job、API/MCP/UI outward proof |

## Stop-and-fix rules

- 若任何路徑把 `not_ranked` 轉成 0／no-trade／no-reversal，先修正再繼續。
- 若 opposite flow 被描述成 inventory close／confirmed unwind，停止 outward/UI integration。
- 若 deterministic score 被當成 probability 或 estimated lots，停止 flow-risk milestone。
- 若 source permission、cost、quota 或 endpoint stability 不符合目前假設，維持 local/shadow/disabled，先更新 contract。
- 若 migration 需要重建或刪除既有 raw table，拒絕該方案並改成 additive migration。
- 若 test、migration、runtime smoke 或 public contract snapshot 失敗，先修正，不帶著失敗進下一 milestone。
- 若 worktree owner/migration head 無法安全隔離，停止 implementation，不覆蓋既有變更。
- 若 prospective evidence 不顯示 Radar incremental lift，不整合 decision weight；保留研究顯示或 no-go 結論。

## Decisions

- 2026-08-22：採 V0 observation/quality + shadow feature，再經 calibration gate，取代直接上 `overnight_likely`。
- 2026-08-22：Top15 metrics 使用 `reverse_given_reappearance` 等條件式名稱；confidence cap 不能修復 selection bias。
- 2026-08-22：V0 不持久化 flow episodes；先用 deterministic event derivation 證明需求，減少 schema 與 migration 成本。
- 2026-08-22：不輸出 `weighted_short_term_lots` 或 `confirmed_unwind`；後續能力暫名 `broker_branch.flow_risk`。
- 2026-08-22：正式 classification 至少需要 120 個高覆蓋 session 並通過 walk-forward；資料量門檻達成不等於自動開放。
- 2026-08-22：現有 nStock collector、summary、retry、startup catch-up 保留；derived compute 解耦為獨立 job。
- 2026-08-22（規劃階段）：worktree 有大量既有修改與未追蹤 migration `0064`，先建立 task docs 並完成 baseline，未在該階段修改 code/schema。
- 2026-08-22（實作階段）：確認 source/live head 均為 `0064` 後，以 additive `0065`／`0066` 延伸 revision chain，不改寫其他任務 migration。
- 2026-08-22：shadow scheduler 預設關閉；只有 raw coverage 至少 95% 才能排獨立 derived job，且 job 永不觸發 external fetch。
- 2026-08-22：25-session、1,253,114-row 唯讀 benchmark 為 2.73 秒；暫不在 24 GB DB 增加 composite index，待 runtime materialization evidence 再決定。
