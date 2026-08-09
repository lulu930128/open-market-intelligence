# Plan

## 執行策略

本任務採 backend-first、contract-first、test-first 的分段實作。先固定 state machine、migration 與 transaction boundary，再處理 readiness，最後才接 API/UI 與真實 SMTP。每個 milestone 必須完成自己的 acceptance 與 validation，失敗時先停下修正，不把已知錯誤帶到下一階段。

## Milestone 0：基線、範圍隔離與資料保護

### Scope

- 重新確認 branch、dirty worktree、現有 dispatch 相關 diff 與未提交 migration。
- 讀取實際 Alembic heads、現有 live schema revision、SQLite journal/foreign-key 狀態與 dispatch row counts。
- 盤點現有 API operation、Pydantic schema、frontend consumer、scheduler registration、runtime leader 與 JobRun lifecycle。
- 盤點 dispatch templates 實際回傳的 structured fields，以及台股 calendar/session/breadth/Radar canonical owner。
- 建立本任務 touched-file allowlist，避免混入 breadth/AI contract 的既有修改。
- 若後續要對 live DB migration，先用 `scripts/backup-omi-sqlite.py` 建立離線備份並記錄來源 DB hash、size、revision、quick check 與 rollback 路徑。

### Acceptance

- 明確記錄當時 Alembic head，且 v2 migration 的 `down_revision` 不會指向未完成或錯誤 branch。
- 列出現有 dispatch API shape 與 consumer，特別是 `/schedules/{id}/run` 的 job + delivery response。
- 確認 runtime 只有 background leader 擁有 scheduler，並知道實際 launcher backend/frontend port。
- 確認不會修改或覆寫既有 breadth、market state、AI contract 未提交內容。
- Live DB migration 尚未執行前已有可恢復備份與 integrity evidence。

### Validation

```powershell
git status --short --branch
rg -n "revision:|down_revision:" backend/alembic/versions
rg -n "DispatchSchedule|DispatchDelivery|enqueue_due_dispatch_schedules|run_schedule_now" backend frontend
.\.venv\Scripts\python.exe -m alembic -c alembic.ini heads
.\.venv\Scripts\python.exe scripts\backup-omi-sqlite.py --help
```

### Stop condition

- `0050` 或其他 head 尚未穩定、live DB integrity 非 `ok`、找不到可恢復備份、或工作範圍與既有 dirty files 無法隔離時，停止 migration 實作。

## Milestone 1：固定 v2 state machine 與 public contract

### Scope

- 在實作前以 tests／schemas 固定 run status、error code、trigger type、summary semantics 與合法 transition。
- 基準 status：`claimed`、`waiting_data`、`queued`、`sending`、`success`、`retry_wait`、`skipped`、`error`、`cancelled`。
- `DELIVERY_RESULT_UNKNOWN_AFTER_RESTART` 是 error code，不是另一個模糊 status。
- Trigger type 至少區分 `scheduled`、`manual`、`manual_retry`；recovery 是處理來源，不偽裝成新正式 slot。
- 分開 `readiness_check_count` 與 `delivery_attempt_count`，並明確定義 max/deadline。
- 定義 schedule summary：
  - `last_queued_at`：最近一次正式 scheduled run 成功建立 job 的時間。
  - `last_sent_at`：最近一次正式 scheduled run SMTP 成功時間。
  - `last_status`：最近一次正式 scheduled run 的狀態。
  - manual/manual_retry 只進 history，不覆蓋正式 schedule health。
- 定義 API compatibility：保留既有 route，新增 additive run endpoint／response；舊欄位保留 alias/deprecation，不直接移除。
- 定義 delete/archive、pause/resume、retryability、manual retry lineage 與 retention semantics。

### Acceptance

- 有一份可由 tests 表達的 transition matrix；任何非法 transition 都被拒絕並留下 stable error code。
- Queue success 與 SMTP success 的欄位／狀態不再共用語意。
- Manual run、manual retry、scheduled run 的 summary side effect 明確且互不污染。
- `skipped` 不代表一律可 retry；API 依 `retryable` 與 error code 決定 action。
- 現有 API consumer 能忽略新增欄位，舊 response 不因 waiting_data/skipped 變成無法解析。

### Validation

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider backend\tests\test_dispatch.py -q
```

### Stop condition

- 如果既有 `/run` 無法在不 breaking 的前提下承載 v2，停止修改原 route，改採新 endpoint 並更新 Prompt 決策。

## Milestone 2：Additive migration 與 ORM contract

### Scope

- 新增 `dispatch_schedule_run`，建議欄位：
  - identity：`id`、`run_token`、`schedule_id`、`trigger_type`、`retry_of_run_id`。
  - slot：`scheduled_for`、nullable `scheduled_slot_key`。
  - immutable intent：`schedule_snapshot_json`、必要 contract/version。
  - state：`status`、`error_code`、`error_message`、`retryable`。
  - counters：`readiness_check_count`、`delivery_attempt_count`、各自上限。
  - orchestration：`next_action_at`、`readiness_json`、單一 canonical `delivery_id`／`job_run_id` 關聯。
  - timestamps：claimed、queued、sending、sent、skipped、created、updated。
- 對 scheduled run 建立 DB-level unique guarantee；manual runs 以 run token 區分，不依賴同微秒時間。
- `dispatch_schedule` additive 欄位：`next_run_at`、calendar/catch-up/misfire/readiness/delivery retry policies、`last_queued_at`、`last_sent_at`、`last_skipped_at`、`last_status`、`archived_at` 或等價 soft-delete state。
- 不建立雙向 circular FK。以單一 FK + ORM reverse relationship 查詢反向關係。
- Migration 只改 schema，不 import application calendar logic；現有 schedule 的 `next_run_at` 由 migration 完成後的受控初始化 function 計算。
- 對 legacy fields 保留相容，API/UI 改讀新欄位；穩定一版後才評估 deprecation。

### Acceptance

- 空白 DB 可升到 head。
- 代表性 legacy DB 可升到 head並保留 recipient、delivery、schedule、job rows。
- Unique constraint/index、FK、nullable semantics 與 soft delete 行為有 migration test。
- Schedule deletion/archive 不會刪除 run、delivery、job history。
- Model registry 與 migration schema 一致。

### Validation

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider backend\tests\test_database_migrations.py backend\tests\test_database_model_contract.py -q
.\.venv\Scripts\python.exe -m compileall backend\app\db backend\alembic\versions
```

### Stop condition

- Migration 需要刪欄、重建 live SQLite table 或會 cascade 歷史資料時停止，改採更保守 additive revision。

## Milestone 3：時間計算、calendar policy 與 bounded slot claim

### Scope

- 新增純函式 module，例如 `backend/app/dispatch/schedule_time.py`。
- 建立明確 UTC normalization helper：SQLite 讀回 naive datetime 時只在 DB-domain boundary 按 UTC 解讀，不在一般 market datetime 上任意補 timezone。
- 實作 `compute_next_run_at()`、calendar validity、IANA timezone conversion、weekday mask、`tw_trading_days`、DST nonexistent／ambiguous time round-trip validation。
- `calendar_mode` 是主要規則；legacy `day_of_week` 經 compatibility mapping 轉成 normalized weekday mask，禁止互相矛盾。
- 實作 misfire 與 bounded catch-up：
  - default `latest_only`。
  - grace 依 schedule policy。
  - 可選 `all_slots` 必須有低 `max_catchup_slots`。
  - 超出範圍以 skipped/coalesced summary 記錄，不大量寄信。
- 實作 `claim_due_schedule_runs()`：排序、limit、insert run、advance next_run、update summary 同一 transaction。
- 以 file-backed SQLite 與兩個獨立 session 做 concurrent claim test；不只用同一 in-memory session。
- 捕捉 unique conflict 與 SQLite lock timeout，rollback 後 session 必須可再使用；不能留下 next_run 永遠卡在過期 slot 的 poison row。

### Acceptance

- Asia/Taipei、UTC 與至少一個有 DST 的 timezone 邊界測試通過。
- daily、weekdays、自訂星期、台股交易日、休市、補班／特殊日與 disabled/archive schedule 行為可測。
- 同一正式 slot 在兩 session concurrent claim 下只有一筆 run。
- Backend 關閉數分鐘後可在 grace 內補一次；超出 grace 只記 skipped。
- Backend 關閉多日不會一次寄出大量過期報告。
- Manual run 不改 `next_run_at` 或 scheduled slot key。

### Validation

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider backend\tests\test_dispatch_schedule_time.py backend\tests\test_dispatch_schedule_runs.py -q
```

### Stop condition

- 若 timezone/DST helper 無法以 round-trip 證明結果、或 concurrency test 仍可能重複 claim，禁止接入 scheduler tick。

## Milestone 4：Queue handoff、delivery lifecycle 與 SMTP 不確定窗口

### Scope

- 在不大改所有 JobRun consumer 的前提下，為 schedule run 建立明確 enqueue handoff：
  1. transaction 中建立／更新 run、delivery snapshot、JobRun record 與關聯。
  2. commit 後 submit ThreadPool task。
  3. submit failure 回寫 retry_wait/error，不顯示 queued success。
- 若需調整 `job_service`，拆成命名清楚的 `create_job_record()` 與 `submit_job_task()`，保留既有 `enqueue_job()` façade 與 consumer compatibility。
- `queue_delivery()` 繼續服務 manual `/send`；新增 schedule-specific orchestration，不把所有 state machine 塞入一般 manual send path。
- Delivery snapshot 固定收件者、subject、body、request、structured preview/evidence、contract version 與 Message-ID。
- Worker 在 SMTP 前持久化 `sending`；成功後依同一 domain owner 回寫 delivery success、run success、sent time 與 schedule last sent。
- 失敗依 stable category 分為 retryable/non-retryable；SMTP auth、invalid recipient、missing config 預設不可自動重試。
- 若程序在 `sending` 後崩潰，重啟只標 unknown result，不自動再 submit。

### Acceptance

- 可注入 crash/failure 的每個窗口都有可觀測狀態：delivery 建立前、job record 前、commit 後 submit 前、submit failure、worker start、SMTP exception、SMTP success 後 DB commit failure。
- Queue 成功時 `last_sent_at` 仍為 null；SMTP 成功後才填入。
- 同一 run 只產生一個 canonical delivery；retry 不會在未知結果下自動建立第二封。
- JobRun error、DispatchDelivery error、DispatchScheduleRun error 能互相追溯但不靠重複 FK 欄位維持一致。
- 既有 manual send／preview tests 保持通過。

### Validation

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider backend\tests\test_dispatch.py backend\tests\test_job_retry.py backend\tests\test_job_dedupe.py -q
```

### Stop condition

- 如果 submit failure 或 SMTP unknown 仍能被 UI/API 當 success，或 recovery 會無條件重寄，停止後續工作。

## Milestone 5：Startup recovery 與 periodic reconciliation

### Scope

- Recovery 只在取得 `background.lock` 的 leader 中執行。
- 明確定義啟動順序：database migration → background leader → mark interrupted jobs → reconcile dispatch runs → initialize next runs → start scheduler。
- 恢復規則：
  - stale claimed：安全重新處理。
  - waiting_data：到 `next_action_at` 後重檢 readiness。
  - retry_wait：依 retry type 與 deadline 重試。
  - queued + job interrupted/error + delivery 未 sending：安全重建或重新 submit job，保留 lineage。
  - sending：標 unknown error，不重寄。
  - success/skipped/cancelled/final error：不自動處理。
- Periodic reconciliation 只修復狀態或安全 handoff，不盲目執行 SMTP。
- Reconciliation 檢查 orphan run/delivery/job、summary cache 與 terminal-state mismatch，並留下 structured log/count。
- Recovery/reconciliation 必須 idempotent，多次執行不改變 terminal result或新增 duplicate delivery。

### Acceptance

- Crash injection tests 覆蓋 claimed、waiting_data、queued-before-worker、sending、success-after-send。
- 連續兩次 recovery/reconciliation 結果一致，不新增第二封 delivery/job side effect。
- Follower API worker 不執行 recovery 或 scheduler。
- Runtime log 可看到 recovered、unknown、skipped、orphan-repaired 數量與 run id。

### Validation

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider backend\tests\test_dispatch_recovery.py backend\tests\test_runtime.py backend\tests\test_runtime_lock.py -q
```

### Stop condition

- 若 background ownership 無法唯一化、terminal run 被 recovery 改寫、或 sending unknown 會自動寄第二次，禁止啟用 v2 tick。

## Milestone 6：Backend-owned market readiness

### Scope

- 新增 `backend/app/dispatch/readiness.py` 或等價 bounded domain module。
- 定義 versioned `DispatchPreflightResult`：ready、status、retryable、reason code/message、checked_at、retry_at、deadline、required capability、optional capability、freshness、session、warnings、missing、provider failures、source refs、metadata。
- 新增 explicit `readiness_profile`，至少支援：
  - `generic`。
  - `tw_preopen`。
  - `tw_post_close`。
  - `watchlist_radar`。
- 不只從 send time 推測盤前／盤後需求；schedule/request 必須保存 profile。
- 建立 template requirement registry，scheduler 不硬編所有 market rules。
- 執行順序應避免 TOCTOU：收集一次 structured evidence snapshot → 評估 readiness → 依 policy 決定等待／略過／寄送 → 從同一 snapshot render delivery body。
- Readiness 使用現有 backend canonical calendar/session/breadth/Radar/AI data-quality projection，不解析 HTML/text，不在 frontend 重算。
- Policy：
  - `immediate`：只要可安全 render 就寄，完整保留 limitations。
  - `wait_until_ready`：只等待 required capabilities，直到 readiness deadline。
  - `skip_if_incomplete`：依明確 required severity 略過，不因任意 optional warning 阻塞。
- Bounded refresh 必須經既有 trust/budget/policy；不得在每次 tick 無限制打 provider。可排入明確 refresh job並等待，不把昂貴 side effect藏在 read helper。
- `readiness_check_count`、`next_action_at` 與 deadline 獨立於 SMTP delivery retry。

### Acceptance

- `tw_preopen` 接受上一個 completed session，並把尚未開盤視為正常，不錯稱當日 official close。
- `tw_post_close` 能區分 official/final、final_partial、provisional、auction-only、partial coverage 與 stale。
- Radar required 時會檢查 active snapshot、universe/readiness/limitations；optional Radar missing 不阻塞非 Radar 報告。
- Provider failure、missing、stale 與 partial 會出現在 run readiness snapshot與最終派報限制，不被 quality ready 隱藏。
- Readiness 多次輪詢不建立 delivery，直到同一 run 首次 ready；最終仍只有一封 delivery。
- Deadline 超時為可見 skipped/error policy result，不 silent drop。

### Validation

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider backend\tests\test_dispatch_readiness.py backend\tests\test_ai_market_context_projection.py backend\tests\test_ai_outward_contract.py backend\tests\test_watchlist_radar_automation.py backend\tests\test_calendar_status_integration.py -q
```

### Stop condition

- Breadth `0050` session semantics 尚未穩定、readiness 需要解析 UI/text、required/optional 無法分離、或 normal tick 會觸發無界 provider refresh 時停止。

## Milestone 7：Additive API、run history 與 safe actions

### Scope

- Schedule create/update/read additive fields：calendar、catch-up、misfire、readiness、retry、next run、last queued/sent/skipped/status、archive。
- 新增 run read schema，所有 JSON 欄位經 typed projection，malformed legacy payload 安全降級。
- 新增：
  - `GET /api/dispatch/schedules/{id}/runs`。
  - `GET /api/dispatch/schedule-runs/{run_id}`。
  - additive `POST /api/dispatch/schedules/{id}/runs` 供完整 v2 manual execution，或經 inventory 確認後採等價兼容 route。
  - `POST /api/dispatch/schedule-runs/{run_id}/retry`，只接受 backend 判定 retryable 的 terminal state，並建立 `manual_retry` + `retry_of_run_id` lineage。
- Pause/resume 優先沿用 PATCH enabled；resume 重新計算 future next_run，不補消失期間 slot，除非使用者明確選擇 catch-up。
- GET routes 保持 read-only；maintenance recalculate 不預設暴露一般 UI。
- API 不回傳 SMTP secret；recipient/body 顯示遵循現有 local-only contract並評估是否需要 masking/limited detail。

### Acceptance

- OpenAPI path/method inventory 中既有 operation 不消失，既有 response model regression 通過。
- Older consumer 可忽略 v2 fields；v2 UI 能處理 fields absent、malformed JSON、partial history與 older version。
- Retry endpoint 無法對 non-retryable auth/config、non-trading-day skip 或 unknown SMTP result進行隱性重寄。
- Manual execution 不改正式 next run／scheduled summary。

### Validation

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider backend\tests\test_dispatch.py backend\tests\test_api_contract_inventory.py -q
```

### Stop condition

- 任何既有 route shape 被無版本 breaking change、GET 產生 side effect、或 retry 可繞過 backend policy 時停止。

## Milestone 8：Frontend 設定、狀態與可觀測性

### Scope

- 修改前依 `frontend/AGENTS.md` 讀取目前 Next.js bundled docs，不用舊框架知識猜 API。
- 擴充 `frontend/src/lib/dispatchMail.ts` types/client，維持 older backend fallback。
- 將 `DispatchSettingsDialog.tsx` 中 schedule form、schedule card、run history 視責任拆成局部元件，避免繼續擴大單一大型 component；不做無關 redesign。
- 設定 UI：calendar mode、weekday picker、timezone、misfire/catch-up、readiness profile/policy/deadline、delivery retry。
- Schedule card：next run、last scheduled status、last queued、last sent、last skipped、recent error、enabled/archive。
- Run history：scheduled/manual/manual_retry、scheduled for、status、readiness、attempt counters、delivery/job、error code、source limitations。
- Safe action：run now、pause/resume、只在 backend `retryable=true` 時顯示 retry；unknown SMTP result 顯示人工確認警告。
- i18n 同步 zh-TW/en-US/ja-JP；避免狀態只靠顏色，加入文字／icon／accessible label。
- Desktop/mobile 驗證文字不溢出、control 不重複、run history 展開不破壞研究工作台密度。

### Acceptance

- UI 不推論 due/readiness/retryability，只使用 backend fields。
- Existing manual preview/send/recipient UI 維持可用。
- next run、queued、sent、error、skipped、waiting data、unknown result 可明確區分。
- Small viewport 與 desktop 不遮擋、不溢出；loading/error 進入 shared data-status flow或既有 dispatch message pattern。
- 三語 i18n 無缺 key，TypeScript types 處理 absent/older payload。

### Validation

```powershell
.\scripts\run-safe-validation.ps1 -Profile frontend
```

只有實際 UI 風險需要時才增加：

```powershell
.\scripts\run-safe-validation.ps1 -Profile frontend -IncludeBuild
```

### Stop condition

- Frontend 開始重算交易日/readiness、需引入新 UI library、或為本功能大範圍重寫 Settings shell 時縮小範圍。

## Milestone 9：Feature flag、copied-DB migration 與 runtime cutover

### Scope

- 增加明確 v2 feature flag/mode；old/new tick 不可同時 active。
- V2 off 時不 claim run、不更動 next run、不影響現有 manual send。
- 啟用前初始化 missing `next_run_at`，只計算未來 slot；不因 migration 自動補寄過去排程。
- 在 live DB copy 上完整跑 migration、initialization、claim/recovery simulation、integrity與 rollback rehearsal。
- Runtime 啟用時確認 background owner、scheduler job ID、interval、feature mode、actual port與 build/source identity。
- Rollback 只關閉 v2 execution、保留 run/delivery/job歷史與 additive schema；不刪資料、不直接 downgrade live DB。

### Acceptance

- Feature flag off/on 行為有 regression。
- 切換 active mode 時只有一個 dispatch tick job。
- Copied DB migration 前後 row counts合理、`quick_check=ok`、foreign key violation=0。
- 啟用 v2 不會立即補寄大量 legacy schedule。
- 關閉 v2 後不再 claim 新 run，既有 history仍可讀。

### Validation

```powershell
.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs backend\tests\test_dispatch.py
```

另以 copied DB 執行 migration/integrity script，命令與結果記入 `Progress.md`，不得對唯一 live DB直接試錯。

### Stop condition

- 無法證明 old/new tick 互斥、copied DB migration integrity失敗、或啟用會補寄未知數量歷史 slot 時禁止 live cutover。

## Milestone 10：完整驗證與受控真實 SMTP smoke

### Scope

先完成無外部 side effect 驗證：

1. Compile、targeted dispatch/migration/recovery/readiness/API tests。
2. Backend safe profile。
3. Frontend lint/typecheck，必要時 build/browser。
4. Copied live DB migration與 integrity。
5. Runtime restart：核對 owner path、old/new PID、listener、launcher selected ports、health、scheduler mode。
6. API/manual run dry checks，確認將建立 exactly one run/delivery/job。

真實 SMTP smoke 限制：

- 使用者已明確授權本任務寄到其指定的單一地址；地址只存在本機 recipient group/runtime，不寫入 repo。
- 驗證 run 必須是 manual v2 run，不消耗正式 scheduled slot或改 next run。
- 收件者數固定為 1；一次 verification 最多 submit 一封。
- 主旨格式：`[OMI TEST] Dispatch Scheduler v2 <run-id>` 或等價明確測試標記。
- 內容使用 bounded preview，保留資料日期與限制，但不得包含 SMTP secret、token、完整環境資訊或不必要的私人 watchlist內容。
- 發送前記錄預期 schedule/run/delivery/job id；發送後核對 SMTP accepted result、Message-ID、delivery success、run success、job success、sent_at。
- 若 SMTP timeout/connection error，可依明確 retry policy決定一次新測試；若狀態為 sending/unknown，禁止自動或人工直接再寄，先由使用者確認收件匣。
- SMTP server accepted 只是 transport evidence；若使用者方便，再由使用者確認實際收件與內容渲染。未確認時不得宣稱 inbox delivery已證實。
- Smoke 完成後停用專用測試 schedule／recipient group，避免日後意外觸發；不刪除 audit history。

### Acceptance

- Targeted 與 safe validation 全部通過，或任何 unrelated failure已清楚隔離且不影響本功能。
- Runtime 證明載入新 source、background leader唯一、v2 tick唯一。
- 真實 smoke 只建立一個 manual run、一個 delivery、一個 active job handoff與一個 Message-ID。
- SMTP success 後 run/delivery/job均為 success，`last_sent_at`只在適用 summary policy下更新；正式 next run不變。
- 未出現 duplicate email；unknown result不自動 retry。
- 實際地址、secret、local DB與log未進 git diff。

### Validation

```powershell
.\scripts\run-safe-validation.ps1 -Profile backend
.\scripts\run-safe-validation.ps1 -Profile frontend
git diff --check
rg -n "DISPATCH_SMTP_PASSWORD|@gmail\.com" docs backend frontend .env.example
```

Live API probes 必須使用 launcher log/tray顯示的實際 backend URL，不預設固定 8400。

### Stop condition

- 收件者不是唯一授權地址、recipient_count 不等於 1、subject 未標示測試、runtime identity不明、或任何 path可能重複 submit 時取消 live send。

## Milestone 11：文件、release hygiene 與交付

### Scope

- 更新 README：v2 execution model、feature flag、next run、misfire/readiness/recovery、known SMTP uncertainty。
- 更新 `.env.example`：只放安全 placeholder與 bounded defaults，不放真實地址/secret。
- 若 public contract 變更，更新相應 architecture/API docs與 contract tests。
- 更新本任務 `Progress.md`：每個 milestone、命令、測試數、migration evidence、runtime PID/port/build、SMTP run/delivery/job id與剩餘風險。
- Audit diff、untracked files、secret/private data、DB/log/cache/build outputs與 unrelated changes。
- 未獲使用者要求不 stage/commit/push；若之後要求，依範圍 audit後使用清楚的 Conventional Commit。

### Acceptance

- 文件描述與實際 feature flag、API、state machine、readiness、recovery相符。
- Task progress有可接手的決策與驗證證據，不把未完成項目標成 done。
- Git diff不含 private recipient、SMTP credentials、SQLite、logs、temporary artifacts或無關 churn。
- 所有 Done criteria逐項有 evidence或明確 remaining risk。

### Validation

```powershell
Get-Content docs\agent-runs\dispatch-scheduler-v2-reliability-20260804\Prompt.md -Encoding UTF8
Get-Content docs\agent-runs\dispatch-scheduler-v2-reliability-20260804\Plan.md -Encoding UTF8
Get-Content docs\agent-runs\dispatch-scheduler-v2-reliability-20260804\Progress.md -Encoding UTF8
git diff --check
git status --short
```

## Stop-and-fix rules

- 若 migration、FK、unique constraint、timezone、calendar或 concurrent claim test失敗，修正後才能接 scheduler。
- 若 queue success仍可能顯示為 SMTP success，停止 UI/API rollout。
- 若任何 recovery/reconciliation路徑可能在 `sending` unknown後自動重寄，立即停用 v2 execution。
- 若 readiness 需要 frontend推論、解析自然語言，或隱藏 partial/missing/stale/provider failure，回到 backend contract設計。
- 若 normal tick/readiness會無界觸發 provider refresh、全市場 backfill、付費 quota或 LLM，停止並建立 bounded policy。
- 若既有 `/preview`、`/send`、schedule CRUD、manual run或 delivery history發生 breaking regression，先提供 additive相容方案。
- 若 dirty worktree與 breadth `0050` 無法安全隔離，不建立下一個 migration revision。
- 若 live DB backup/integrity、runtime owner/port/build identity任一不明，禁止 migration/cutover/restart assertion。
- 若 live SMTP 的 recipient、次數、subject、run identity或 duplicate guard不符合限制，禁止發送。
- 若測試失敗與本次修改相關，先修復；不得以「後續再處理」進入下一 milestone。

## Decisions

- 2026-08-04：沿用現有 mail dispatch與APScheduler heartbeat，不推倒重寫，也不導入外部 broker。
- 2026-08-04：正式排程保證 slot exactly-once claim；SMTP end-to-end exactly-once不是可承諾目標。
- 2026-08-04：readiness與SMTP retry分開計數、deadline與retry interval。
- 2026-08-04：claim時保存 immutable schedule intent，避免排程後續編輯改變既有 run。
- 2026-08-04：使用單一 canonical FK，不採 run/delivery互相指向的 circular schema。
- 2026-08-04：預設 catch-up `latest_only`且有上限，避免長時間關機後大量補寄。
- 2026-08-04：manual/manual_retry不覆蓋正式 schedule health summary。
- 2026-08-04：existing `/schedules/{id}/run`優先維持相容，完整 v2 manual run採additive endpoint。
- 2026-08-04：readiness使用explicit profile與backend structured evidence，不從寄送時間或email文字猜測。
- 2026-08-04：使用者已授權最終單一真實 SMTP smoke；實際地址不寫入 repo，且每次驗證最多一封。
- 2026-08-04：在 breadth `0050`與Alembic head穩定前，不開始派報v2 migration。
