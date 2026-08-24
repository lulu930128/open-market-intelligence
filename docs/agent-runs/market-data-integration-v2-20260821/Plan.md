# OMI Market Data Integration v2 — 02A 長專案計畫

## Execution model

```text
Plan review
  -> Gate S: user authorizes dark implementation
  -> A0 baseline and isolation lock
  -> A1 lifecycle and ownership contract freeze
  -> A2 pure provider policy
  -> A3 research lease runner
  -> A4 control plane orchestration
  -> A5 safe acquisition observability
  -> A6 dark wiring and checkpoint guards
  -> A7 source validation and handoff
  -> 02A_SOURCE_COMPLETE_DARK
  -> wait for independent Foundation 1.1 closure
  -> Gate B: separate 02B authorization
```

- Milestones 依序通過；後一階段不得掩蓋前一階段 failure。
- 02A 全程只做 source/tests/docs，不做真實 provider、runtime、DB、consumer 或 public wiring。
- 每完成一個 milestone 就更新 `Progress.md`，並將 machine-readable 摘要寫入本目錄 `artifacts/`。
- Foundation 1.1 是平行但獨立的 stop-and-fix track；02A 不修改、取代或偽造其 closure evidence。

## Track separation

### Track F — Foundation 1.1（不屬於本計畫的執行範圍）

1. 修正 closing-auction stream classifier 缺少 session context 的 defect。
2. 重算 30-target checkpoint 並以 component owner adopt runtime。
3. 在同一新 fingerprint 上重跑 Preopen、Opening、Regular、cleanup。
4. 完成 `compare -> off` rollback 與 final closure。

### Track 02A — 本計畫

1. 保持 production import graph 不變。
2. 只建立 provider-neutral dark modules、fake ports、contract tests與 guards。
3. 不依賴市場開盤時段，可在 Foundation 等待期間持續推進。
4. 最終只交付 `02A_SOURCE_COMPLETE_DARK`。

## Milestone A0 — Baseline and isolation lock

### Scope

- 保存 branch、HEAD、`git status --short`、原始附件 SHA-256 與 task-doc versions。
- 讀取 Foundation `source-checkpoint.json` 的 30 個 target hashes，建立 02A 自己的 reference baseline，不修改原 artifact。
- 記錄 known closing failure，明示 `99f95233...` 只可作 02A freeze reference，不再是 closure-eligible fingerprint。
- 確認四個 planned dark modules 與五個 planned tests 尚未被 production import。
- 建立 `artifacts/02a-source-baseline.json`。

### Acceptance

- Foundation 30 targets 與 production wiring files 有清楚 ownership map。
- 02A planned files、allowed imports、forbidden imports 與 validation commands 已固定。
- Baseline artifact 不含 raw payload、credential、account/person identity 或 environment dump。
- 如果 frozen hashes 已因獨立 Foundation 修正改變，先辨識 ownership並以新的已驗證 checkpoint 重建 baseline。

### Validation

```powershell
git status --short --branch
git rev-parse HEAD
Get-FileHash "$env:USERPROFILE\Downloads\02A_Market_Data_Control_Plane_Research_Lease_v1_20260821.txt" -Algorithm SHA256
```

### Stop condition

- 任一 frozen drift 無法歸屬時停止，不覆蓋、不 revert、不把它算成 02A 變更。

## Milestone A1 — Lifecycle and ownership contract freeze

### Scope

- 在 `Architecture.md` 的既定方向上完成可直接實作的型別與責任決策。
- 定義 injected provider descriptor、provider route、acquisition plan 與 capability scope。
- 定義 `ResearchAcquisitionPort`、attempt context、owned handle、cancellation、deadline、release 與 cleanup result。
- 將 acquisition outcome 與 cleanup status 分開。
- 定義 Control Plane result只包含 candidates、attempts、counts、limitations與cleanup evidence。
- 定義 Resolver 是 final selection owner，Control Plane 不輸出 `selected_provider`。

### Acceptance

- 所有 terminal path 都有明確 owner、deadline、cancel 與 cleanup postcondition。
- Blocking provider 若無法 cooperative cancel/release，contract 必須 fail closed，不能被包裝成 bounded lease。
- `cache_only`/`completed_session` 明確形成 zero-route acquisition plan。
- Unknown health 的處理不依賴單一 `healthy` 布林。
- 不需要修改 `policies.py`、`contracts.py`、`resolution.py` 或 `registry.py` 才能完成 dark contract；若需要則停止評估。

### Validation

- Contract review 對照：`backend/app/market_data/policies.py`、`contracts.py`、`resolution.py`。
- Import boundary review 對照：`docs/architecture/BackendArchitecture.md`。

### Stop condition

- 若 contract 只能靠更改 frozen Foundation type 或複製 Resolver selection 才能完成，停止並提出 versioned follow-up，不以私有 shortcut 繞過。

## Milestone A2 — Pure provider policy

### Planned files

- `backend/app/market_data/provider_policy.py`
- `backend/tests/test_market_data_provider_policy_v2.py`

### Scope

- 建立 provider-neutral、pure、deterministic 的 policy types與 `plan_acquisition(...)`。
- Provider descriptors由 caller/test注入；shared layer不寫死 KGI/MIS route catalog。
- 初版 capability只接受 TW `quote.snapshot`、`quote.order_book`。
- 根據 `RealtimePolicy`、provider capability與多維 health形成 attempts或truthful skip reasons。
- 施加 max routes、max attempts、route timeout與overall budget bounds。

### Required cases

1. `cache_only` -> routes=0。
2. `completed_session` -> routes=0。
3. `prefer_live` -> deterministic bounded routes，不承諾 final selection。
4. `require_live` -> 只允許可追求 LIVE 的 route；沒有 route 時 truthful unfillable。
5. unsupported capability -> fail closed。
6. disabled/auth_failed/plan_restricted/failed/rate_limited/unavailable -> default terminal skip。
7. degraded/disconnected/unknown -> 依 explicit rule 分類，不視為 healthy。
8. 同 priority 使用 stable provider key tie-break。
9. route/attempt/timeout bound不可被 caller overflow。

### Acceptance

- 無 network、DB、provider SDK、AI、router、frontend side effect。
- 同一 input 產生 canonical-equivalent output。
- Provider key只是資料，不造成 shared module 反向依賴 market-specific implementation。

### Validation

```powershell
cd "C:\project\Open Market Intelligence\backend"
..\.venv\Scripts\python.exe -m compileall app\market_data\provider_policy.py
..\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests\test_market_data_provider_policy_v2.py -q
```

## Milestone A3 — Research Lease lifecycle

### Planned files

- `backend/app/market_data/research_lease.py`
- `backend/tests/market_data_fakes.py`
- `backend/tests/test_market_data_research_lease_v2.py`

### Scope

- 實作 request-scoped Research Lease runner與 test-only cooperative fake ports。
- 使用 injected monotonic clock、absolute deadline與 cancellation token；測試不用真實長時間 sleep。
- 每個 attempt有 owner token與owned handle；release idempotent。
- `route_budget = min(route_timeout, overall_remaining)`。
- 保存 acquisition outcome與cleanup status，不以 `RELEASED` 覆蓋 `TIMED_OUT/FAILED/CANCELLED`。

### Required cases

1. success + released。
2. unavailable + no leak。
3. provider error + released。
4. timeout + cooperative cancel + released。
5. caller cancellation + no next attempt + released。
6. unexpected exception + released。
7. cleanup failure truthful，不能宣稱released。
8. duplicate release idempotent。
9. 100 sequential runs active handles回 baseline。
10. parallel leases彼此隔離。
11. lease A不能release lease B。
12. timeout/cancel後沒有late callback或reactivation。
13. provider worker/task已終止或明確進入不可再callback的terminal state。

### Acceptance

- Fake active handle、logical subscription與worker counts全部回到before baseline。
- Cancellation與timeout不是只停止外層等待。
- 不建立background task或process殘留。

### Validation

```powershell
cd "C:\project\Open Market Intelligence\backend"
..\.venv\Scripts\python.exe -m compileall app\market_data\research_lease.py
..\.venv\Scripts\python.exe -B -c "import ast, pathlib; ast.parse(pathlib.Path('tests/market_data_fakes.py').read_text(encoding='utf-8'))"
..\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests\test_market_data_research_lease_v2.py -q
```

## Milestone A4 — Control Plane orchestration

### Planned files

- `backend/app/market_data/control_plane.py`
- `backend/tests/test_market_data_control_plane_v2.py`

### Scope

- 驗證 requirement與plan一致性後，依 route執行 bounded acquisition。
- 呼叫 Research Lease runner，合併 canonical candidates、provider health、attempt outcomes、counts與limitations。
- 不混合不同 provider snapshot欄位。
- 不產生 final `selected_provider`、selection reason或fallback_used。
- Acquisition completion判斷不得複製 Resolver selection；如果 frozen Resolver沒有可重用 seam，先以 bounded plan執行並把 selection留給 caller。

### Required scenarios

1. first fake provider produces candidate；後續 attempt是否停止由明確 acquisition completion policy決定。
2. unavailable -> next route。
3. timeout -> cleanup -> next route。
4. exception -> classified limitation -> bounded fallback。
5. cancellation -> cleanup且不執行下一 route。
6. `cache_only`/`completed_session` ports call count=0。
7. max provider attempts enforced。
8. external call/subscription counter overflow fail closed。
9. no cross-provider field merge。
10. all attempts fail -> truthful acquisition outcome；Resolver仍獨立處理 final policy result。
11. resolver在acquisition回傳後失敗時，不會造成lease leak，因Control Plane回傳前已完成cleanup。

### Acceptance

- Result只包含 candidates與acquisition metadata。
- 所有 ports都是fake；沒有real provider import或side effect。
- Deterministic order、bounded budget與cleanup invariant成立。

### Validation

```powershell
cd "C:\project\Open Market Intelligence\backend"
..\.venv\Scripts\python.exe -m compileall app\market_data\control_plane.py
..\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests\test_market_data_control_plane_v2.py -q
```

## Milestone A5 — Safe acquisition observability

### Planned files

- `backend/app/market_data/acquisition_observability.py`
- `backend/tests/test_market_data_acquisition_observability_v2.py`

### Scope

- 建立 allowlist-based structured diagnostics。
- 記錄 request、purpose、target、capability、policy、route attempts、safe detail code、logical/physical counts、elapsed、outcome、cleanup與limitations。
- Acquisition attempt provider與Resolver selected provider使用不同欄位/階段；02A只有前者。
- Exception只轉成bounded classification/detail code，不保存原文。

### Required cases

1. attempt order與skip/fallback reason可見。
2. cleanup status與cleanup failure可見。
3. logical attempts、external calls、subscriptions分開。
4. missing/unknown counts不偽造成0。
5. secret-like exception message不出現在serialization。
6. raw payload object不可進diagnostics。
7. oversized limitation/detail被bounded validation拒絕或安全截斷。
8. diagnostics自身serialization failure不造成resource leak。

### Acceptance

- Artifact可回答「嘗試了誰、為何繼續、結果如何、是否清理」，但不冒充「Resolver最後選了誰」。
- 沒有raw payload、credential、account/person identity、token、cookie或environment dump。

### Validation

```powershell
cd "C:\project\Open Market Intelligence\backend"
..\.venv\Scripts\python.exe -m compileall app\market_data\acquisition_observability.py
..\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests\test_market_data_acquisition_observability_v2.py -q
```

## Milestone A6 — Dark wiring and checkpoint guards

### Planned file

- `backend/tests/test_market_data_v2_dark_boundary.py`

### Scope

- 使用 AST/import graph檢查 production modules沒有import四個dark modules；掃描時排除這四個模組彼此的合法import與tests。
- 檢查新 shared modules沒有import forbidden boundaries。
- 檢查 `backend/app/market_data/__init__.py`、router、runtime、AI consumer、frontend與public snapshots未因02A改動。
- 將目前有效 Foundation checkpoint的30 targets與02A own manifest分開比較。
- 若發現 dynamic import pattern，加入明確guard或人工review evidence。

### Forbidden imports

- `app.ai`
- `app.db`
- `app.routers`
- `app.market.providers.kgi_superpy`
- `app.market.providers.twse_mis_canonical`
- `app.market.quote_depth`
- `agents`
- `requests`
- `httpx`
- `sqlalchemy`

### Acceptance

- Production import graph完全unwired。
- No router/config/runtime/public/frontend/MCP change。
- 02A造成的Foundation target hash mismatch=0。
- 如果hash drift來自獨立Foundation修正，已暫停並以新validated checkpoint重建baseline，而不是revert。

### Validation

```powershell
cd "C:\project\Open Market Intelligence\backend"
..\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests\test_market_data_v2_dark_boundary.py -q
```

## Milestone A7 — Source validation and dark handoff

### Scope

- 跑四個模組compileall與完整02A targeted suite。
- 跑backend safe validation，確認shared market-data regression。
- 跑`git diff --check`與精確changed-file inventory。
- 生成 `artifacts/02a-source-manifest.json` 與 `artifacts/02a-validation.json`。
- 更新 `Progress.md`、`AcceptanceMatrix.md`。

### Validation

```powershell
cd "C:\project\Open Market Intelligence\backend"
..\.venv\Scripts\python.exe -m compileall app\market_data
..\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  tests\test_market_data_provider_policy_v2.py `
  tests\test_market_data_research_lease_v2.py `
  tests\test_market_data_control_plane_v2.py `
  tests\test_market_data_acquisition_observability_v2.py `
  tests\test_market_data_v2_dark_boundary.py -q

cd "C:\project\Open Market Intelligence"
.\scripts\run-safe-validation.ps1 -Profile backend
git diff --check
git status --short --branch
```

### Acceptance

- 02A targeted failure=0。
- Backend safe validation與diff check通過；任何無關既有failure有可重現、精確隔離證據。
- Source manifest只包含02A owned files，不修改Foundation source checkpoint。
- Acceptance Matrix沒有未處理的blocking gate。
- Final status=`02A_SOURCE_COMPLETE_DARK`。
- `production_wiring=false`、`real_provider_calls=0`、`db_writes=0`、`runtime_acceptance=false`。

### Stop condition

- 任何targeted failure、leak、boundary violation、secret/raw payload evidence或Foundation target drift未釐清前，不得宣告完成。

## Stop-and-fix rules

立即停止並更新 `Progress.md`：

1. 02A 必須修改 Foundation frozen file 才能繼續。
2. 任一 production module import 新 Control Plane/Research Lease。
3. 任一 fake test、import或fixture實際啟動 KGI/MIS/network/runtime。
4. `cache_only`產生port call/external call/subscription。
5. `completed_session`產生live acquisition route或subscription。
6. Timeout/cancellation後worker、handle、lease或callback未回terminal baseline。
7. 一個owner可以release其他owner的handle。
8. Fallback合併不同provider欄位。
9. Control Plane輸出final selected provider或重做Resolver selection。
10. Unknown health被壓成healthy/unhealthy或0。
11. Exception原文、raw payload、credential、token、account/person identity進入diagnostics/artifact。
12. Route、external call、subscription或deadline budget可overflow。
13. 為了02A修改public contract、router、runtime、DB、frontend、MCP或Kuro。
14. Foundation target hash drift無法歸屬。
15. 用unit/full backend tests冒充production或market-session acceptance。
16. 未經授權commit、push、release或啟用02B wiring。

## Decisions

- 2026-08-21：原提案方向通過，但修正為雙軌計畫；`99f95233...`保留為freeze reference，不再視為closure-eligible checkpoint。
- 2026-08-21：Research Lease不直接建立在只有`acquire()`的舊port上；02A新增dark lifecycle protocol，02B再做market-specific adapter。
- 2026-08-21：Control Plane負責acquisition candidates，Resolver繼續擁有final selection。
- 2026-08-21：Outcome與cleanup採正交狀態，timeout/cancel必須cooperative並證明沒有late callback。
- 2026-08-21：02A shared policy不硬編碼KGI/MIS production order；使用injected descriptors。
- 2026-08-21：舊Foundation artifact保持immutable，02A使用獨立manifest與validation artifact。
- 2026-08-21：Lifecycle protocol具體採non-blocking `poll/cancel/release` owned handle；`port.start()`失敗時activity counts為unknown，不壓成0。
- 2026-08-21：因existing Resolver沒有generic public eligibility seam，02A執行全部bounded routes並保留candidates，不為short-circuit建立第二套selection。

## 02B unlock conditions

以下全部成立且取得 Gate B 授權後，才可另立 02B 計畫：

1. Foundation 1.1 使用修正後新 fingerprint 完成正式 Preopen、Opening、Regular、cleanup與rollback。
2. Foundation closure 文件 truthful 標記 ready-for-02。
3. 02A=`02A_SOURCE_COMPLETE_DARK`且所有boundary/cleanup tests通過。
4. 真實 KGI/MIS port各自有market-specific owner、entitlement/health/error contract與bounded runtime plan。
5. Consumer cutover順序另行核准：internal AI/MCP shadow -> backend API -> frontend -> external consumers。
