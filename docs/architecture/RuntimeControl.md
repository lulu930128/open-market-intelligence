# OMI runtime control v1 — source contract

## 2026-10-17 遠端無人值守 RestartBackend（最新 Source，待重啟採用／Live 驗收）

受專用 Token 保護的 MCP RestartBackend 在 Launcher 既有 Controller 內消耗一次性 authenticated intent，**不再跳出 Windows 本機 Yes/No 對話框**。Controller 只接受已驗證 Backend Pipe 身分、Launcher Owner、UUID 與 typed preflight 的請求；經 TakePending 後，於 30 秒意圖期限內持久保存 running，才進入原本的 Writer Drain → Safe Stop → Exact Exit → Start → Readiness → Receipt。原 blocked/unknown 收據不重播，舊 local_approval 欄位僅供歷史讀取。這是 Source 變更；現役 Launcher 不會熱載入，新版尚待隔離回歸與使用者重啟後的 MCP E2E。

## 2026-10-17 Job Service Quiescence 第四輪（Source，待離線／Live 驗收）

22:49:18（Asia/Taipei）的正式 MCP Restart Request
`2ec55d26-9599-4f76-a4b2-384657bcea19` 已通過
`SCHEDULER_QUIESCENCE`，但返回
`blocked/PREFLIGHT_REARMED`，`preflight_stage=JOB_QUIESCENCE`。
原 Backend PID 13432 被保留，`/readyz` 恢復 HTTP 200；
這不是新的 Scheduler 失敗，也不能僅從 EOD job outcome error
推定哪個 Job Service 條件造成阻擋。

正式 Job Service 只有單一 `pause_jobs_if_idle` Gate，檢查
`_pending_tasks`、`_active_enqueues` 與 `_enqueue_failures`；
其中 `_enqueue_failures` 是記錄入隊／Commit／Compensation 結果不明
的持續性計數。這個計數非零不等於工作仍在執行，但也**不能**
因暫時沒有 Future 就擅自歸零，否則可能繞過真正的 durable job
不確定性。

新增唯讀 `observe_job_quiescence()`：僅使用 JobService 既有
`_executor_lock` 讀取每 Lane 的 pending Future 個數、其中已完成與
取消的 Future 個數、活躍入隊數、`unresolved_enqueues`、
`task_failures` 及是否關閉／已暫停 Admission。輸出不包含 job ID、
參數、資料庫內容、Future 物件或憑證，不變更任何 gate 或狀態。
`RuntimeCoordinator.prepare_owned_restart` 在
`JOB_QUIESCENCE` 失敗時記錄
`OMI_RESTART_JOB_QUIESCENCE`、最終 snapshot 與最多每 250ms
採樣一次的最後拒絕狀態及剩餘期限；它們是不同時間點的
唯讀觀察，不會成為重啟許可。
如果 `_enqueue_failures` 已非零（它在本程序中不會自動減少），
立即 fail closed 並走原本 rearm，不再無效地等待完整 60 秒；
對真正尚在執行的 Future，仍等待至原定 deadline，不取消、
不丟棄、不重送、不假定已完成。

**本輪未證實 22:49 那次究竟是 pending Future 或 unresolved enqueue。
Source 已修改但 live 尚未採用，也沒有正式測試結果。**
回歸驗證應覆蓋 snapshot 的只讀性、不可解決入隊失敗時的快速拒絕、
活躍 Future 時的 timeout/rearm，以及原本正常 idle 和 SQLite 防護。
Cold Restart 採用新版後，只再送一次新的受認證重啟請求，
若仍拒絕則根據 `OMI_RESTART_JOB_QUIESCENCE` 直接定位原因。

## 2026-10-17 Scheduler Quiescence 第三輪（歷史 Source，已通過此 Gate）

上一輪正式 MCP Restart 的終態為 `blocked/PREFLIGHT_REARMED`，
`preflight_stage=SCHEDULER_QUIESCENCE`；失敗時的診斷觀察到
`active_instances=0`、`jobs=[]`，但**未記錄原始 `_instances` Key 數量**。
源碼確認：舊 `OwnedScheduler.restart_quiescent()` 以
`if executor._instances` 作為忙碌判斷，APScheduler 3.11.2 的 defaultdict
可能保留計數為 `0` 的 Key，導致明明無正數活躍實例卻仍持續返回 False。
這是已確認的判斷條件缺陷；該次 Live 是否真的存在零計數殘留仍待驗證。

新的正式 Gate 改為在原 Executor lock 內逐一檢查計數：
空字典與全為正確整數 `0` 的字典視為排空；任何正整數、負數、
bool、非整數等異常計數都阻擋。**不改動或清空 APScheduler 的
`_instances`**，保留 Pause Lease、Scheduler state、全部 Writer Admission、
Session／Engine／SQLite Fence 與 Stop/Exact Exit／No Replay。

失敗診斷另外標示 `raw_instance_keys`、`zero_instance_keys`、
`invalid_instance_keys`、`active_instances`、`scheduler_state`、
`lease_matches`、目前採樣的 `reason`，以及最後一次 False 探測與
截止時的剩餘毫秒。這些是**不同時間點的唯讀觀察**，
不能把期限後的 `0` 推定成期限前的狀態；Job ID 仍做白名單遮蔽，
最多保留 12 項，無任何寫入／取消工作的權限。

新增隔離測試涵蓋零計數 Key、正／負／異常型別計數、錯誤 Lease、
實際 PREPARE 經過後續 SQLite Fence，以及 Timeout／Rearm 原有行為。
前輪 7 項 targeted tests 曾由操作者執行通過；**本輪改動後的測試與
新版本 Live E2E 必須分別重新驗證**，不能沿用作封版證據。

## 2026-10-17 Scheduler Quiescence 第二輪（歷史 Source 修改與 Live 失敗紀錄）

本輪正式 MCP `omi_restart_backend` 已通過專用遠端授權、由 accepted 進入 running，
但 21:26:49（Asia/Taipei）回報 `PREFLIGHT_REARMED`、
`preflight_stage=SCHEDULER_QUIESCENCE`。Backend 仍為原 PID，`/readyz` 恢復 HTTP 200；
這只能證明排空等待逾期，不能從 APScheduler 的 missed-run 訊息推定哪個 Job 阻塞。

`RuntimeCoordinator.prepare_owned_restart()` 現在僅在此階段失敗時，以原 Scheduler
持有的 executor `_instances` 及其既有 lock 讀取、限量輸出診斷至 Backend Log：
`OMI_RESTART_SCHEDULER_QUIESCENCE failure_type=... evidence=...`。
包含最多 12 筆符合白名單字元的 executor/job ID、instance count 與 omitted count，
不複製 job arguments 或資料，亦不授予 Stop 權限。診斷不保證所有工作皆被列出；
`active_instances` 為同一個 APScheduler executor accounting 視角的觀察，不是 OS
全域 Writer 數。真正停止 Gate 仍由 `OwnedScheduler.restart_quiescent()` 檢查全部實例歸零。

台股 `audit_completed_taiwan_intraday_coverage` 已有 5 秒 `AuditSlice`，
但原本在開始 audit 前的 `dispatch_due_materializations()` 沒有同步協作檢查。
現在這個既有 Scheduler 呼叫會在查詢前及每個 due-item 邊界檢查 pause／budget，
並於前置派送後確認是否應 partial yield。已提交的項目仍完整完成其交易，
剩餘 queue 留給下次 cadence；**已開始且正在等待 DB／IO 的單項操作仍不能強制取消**。
本輪不延長 PREPARE deadline、不更動遠端 MCP 工具、不放寬 SQLite／Engine／Session gate。

驗證區分：Source 已修改；Windows 定點 pytest（真實 APScheduler active-job、
Timeout/rearm、協作 dispatch 正負例）及使用者重啟後的 E2E 仍待實際執行紀錄。
若再次在同 stage 失敗，先讀 `OMI_RESTART_SCHEDULER_QUIESCENCE` 對應的具體 Job ID，
再只修該實際工作，不能直接重送不同 UUID 或推定另一個 Scheduler 修復成功。

## 2026-10-15 歷史背景（以下為當時狀態，非最新部署判斷）

2026-10-15：正式 source 已接入既有 Launcher／Runner 的兩階段 RestartBackend；尚未 runtime adopted。
23:46 Asia/Taipei live checkpoint 仍為 Launcher 51376／Backend 42568，舊程序保持服務，
`runtime_started=true`、`disk_matches_import=false`、unknown writers=3，未送 live restart POST。
現役 legacy child 缺少出生時建立的 inherited control channel 與可撤銷 preflight；不能 hot-adopt、
注入或終止它來假裝完成採用。新 source 的 cold start 與 live succeeded receipt 仍待實際驗收。
任何模型 boolean、HTTP 欄位或 fixture approval 都不能授予 STOP authority。

## 本機托盤 Backend Safe Stop（2026-10-16，Source）

`Safe Stop Backend`、`Stop Services` 與 `Exit Launcher` 的正式呼叫鏈共用原有 owner：

```text
Safe Stop Backend / Stop Services / Exit Launcher
  -> Stop-Services (-BackendOnly for Safe Stop Backend; serialized; pause lifecycle timers)
  -> Assert-FrontendSafeStopAvailable (all-service paths only; observation before Backend STOP)
  -> Stop-BackendService (mutex + retained ProductionSession / runner)
  -> ProductionSession.StopAsync -> Stop (same UUID receipt; terminal no replay)
  -> existing Runner.RunProduction -> inherited PREPARE
  -> RuntimeCoordinator.prepare_owned_restart (quiescence + final flush + SQLiteWriterLease)
  -> inherited STOP -> commit_owned_restart -> Uvicorn.should_exit
  -> ASGI lifespan -> RuntimeCoordinator.stop / _drain
  -> LIFESPAN_COMPLETE -> retained child exit 0 -> retained runner exit 0
  -> Stop-FrontendService -RequireSafeStop (unless -BackendOnly)
  -> only explicit Exit Launcher may exit and release resources
```

同一托盤的 `Safe Stop Backend` 呼叫 `Stop-Services -BackendOnly`，沿用相同重入、Timer、
事件合併與未知／重送管理；只有既有 `Stop-BackendService` 確認 ExactExit 成功才顯示
`Backend stopped`，並明示執行中的 Frontend/UI services 保持運行、Launcher 保留。
啟動失敗但雙 process 已證退出時，托盤改顯示 `OWNED_START_EXIT_CONFIRMED`，明示沒有執行
Safe Stop；Exit log 也保留此分類，`LastStop` 不建立成功 receipt。其他 failure 不顯示停止成功。
此入口不呼叫 Frontend stop、不退出 Launcher；Frontend 缺少合作式通道不阻擋它。
`Stop Services`／`Exit Launcher` 仍走完整安全檢查，未降低 Frontend safety policy。

正常停止關閉的是原本已載入、出生時持有 authenticated channel 的 Backend。它不要求
磁碟 `ApplicationRelease` 相同、不使用 READY 時的 `RestartBlocker` snapshot，也不檢查
下一個版本的 Start/readiness。真正的 writer eligibility 仍由當下 PREPARE 決定，沒有
跳過 HTTP／Session／Job／Publisher／Fugle／Crypto quiescence、final flush、native writer
lease、lifespan、雙 retained exact exit 或 no-respawn。Restart-only source/readiness/approval
檢查繼續留在 `Restart-Backend`；本機 tray 不會把停止成功當成完整 Restart 授權。

unknown／timeout 保留原 request UUID、StopEvidence、session 與 process handle，不重送。
只有同一活著 child 的 authenticated `PREFLIGHT_REARMED` 才允許下一次明確本機點擊使用
新 UUID。Stop 期間的重入／Windows event 合併，結束後恢復原先 enabled 的 timers；失敗
保留托盤、mutex、controller 與 owner，顯示固定錯誤碼。開始過 Safe Stop 後不自動 recovery、
Start 或處理 queued Restart；原 ActivationTimer 仍每五秒發布狀態，僅封鎖 TakePending／
Restart dispatch。仍可讀狀態、開 logs、明確再次 Stop／Exit。`Start Services` 仍回
`SAFE_STOP_NO_START_OR_RECOVERY`；已載入下節 source 的同一 Launcher，只有獨立
`Start Backend` 可在完整 retained exact-stop proof 後重建 session，永不 replay queued requests。
Terminal 的 unknown 與 retained exact exit
分開發布，stopped 只描述原 owned instance，不推論現在的 port owner。
`ApplicationExit` cleanup 只接受已完成兩個服務停止檢查的 `LauncherExitReady`。
這是正常 Launcher 流程的 guard，不是抵抗 OS 強制終止或系統關機的保證。

沒有 Owned channel 的 legacy Backend 回 `BACKEND_SAFE_STOP_OWNED_CHANNEL_REQUIRED`。
`Stop-LegacyBackendService`、taskkill、port cleanup 與舊 recovery 保留在 source，正式 Safe Stop
不呼叫它們，也不 bootstrap／接管現役程序。`Restart Services` 對 Owned session 明確回
`OWNED_RESTART_NOT_AVAILABLE_FROM_TRAY`，不先停止一半服務再嘗試未完成的版本切換。

Frontend 的既有 runner 沒有合作式停機通道。全服務 Stop／Exit 在 Backend STOP 前先要求
tracked runner（若有）已正常退出且 endpoint 可用；仍在執行時回
`FRONTEND_SAFE_STOP_UNAVAILABLE`，其餘證據不足回 `FRONTEND_STOP_UNCONFIRMED`，兩個服務都保留。
Backend STOP 後再用相同 owner 檢查一次；若 Frontend 在其間出現，保留已取得的 Backend
停止證據、拒絕整組成功與 Launcher Exit，不強殺或假稱能原子停止。BackendOnly 不執行此
Frontend 檢查；本輪不建立另一套 Frontend stop owner。故 **Backend Safe Stop 的
Source 接線完成，不表示執行中的 Frontend 可正常合作式關閉，也不表示整組 Exit 已 live PASS**。

驗證分開呈現：Launcher AST 隔離測試只證明順序／拒絕／timer／重入；真實 Runtime + Uvicorn
使用暫存 DB 與無 socket 的 ASGI server 驗證 production PREPARE/STOP 分支；既有 disposable
Runner 測試驗證獨立 retained exit 與負例。尚未操作真實 Launcher／Backend／Frontend，
現役 legacy channel 缺口、正式 cold-start adoption 與托盤 Live acceptance 仍待另行放行。

### 2026-10-16 失敗收斂 source 增量

- PREPARE 的五秒 lease 到期後，transport 保留原 UUID／deadline。晚到的 authenticated
  STOP 必須經 Runtime 的成功 undo 證據才能回 `PREFLIGHT_REARMED`、`rearmed=true`；Runner
  與 Session 共用嚴格 identity／UUID／deadline／proof 檢查，對外為 blocked refusal。
  缺 proof、過期 request、錯 identity 或撤銷失敗皆不能解除 terminal unknown。原
  terminal-intent 與 refusal 留存；同 UUID 不再送，下一次明確操作才取得新 guard。
- READY 前 Runner 發布 authenticated STARTING child identity；失敗時只有 retained child
  真實退出才發布 START_FAILED／child exit code。Session 另驗 Runner exit 79，得到
  `OWNED_START_EXIT_CONFIRMED`，可以收尾但不建立 Safe Stop success。尚未取得 child 的
  pre-spawn failure 需要 Runner 的 `child_started=false` receipt；缺少它仍 unknown。
  timeout 後僅可從原 retained child／runner identity 與 exit 證據唯讀收斂；保留未知 handle。
  Backend startup failure 直接停止 Start-Services，也拒絕把仍活著的失敗 Runner 視為成功。
- Owned health 使用 Session 出生時的 FixedPython，並核對 repo、retained owner、selected
  listener identity，health 若有 PID／creation 也須符合；Legacy／reload 保留原檢查。
- STOP 共用 120 秒 request budget（含至多 60 秒 PREPARE），Session receipt 等待 125 秒；
  lifespan 等待使用剩餘單調／wall-clock budget，移除獨立 30 秒截斷。逾時保持原 UUID unknown。
  Runner log 名稱加入同 session instance UUID；owner loss 關閉 child stdin，只撤銷 reversible
  PREPARE，不授予 STOP，不強殺、不重建 parent，也不進 legacy respawn。
- HTTP caller cancellation 不再取消已接件 ASGI scope。Middleware 保留其 task 與原 admission，
  streaming／BackgroundTasks 實際完成才離場；scope 自身取消仍保留 ownership unknown。
  不清除既有未知旗標，不更改 transaction owner 或 Writer Drain。

非阻擋 debt：Frontend cooperative lifecycle 尚未實作；無 receipt 且未保留 child identity 的
startup failure 不能靠 Runner／port 消失
推定成功。這些限制不得用自動 restart、force kill 或 port adoption 繞過。

### 同 Launcher 明確 Start Backend（2026-10-16，Source）

```text
Start Backend tray click
  -> Invoke-BackendStartRequest (existing service-operation guard; pause timers)
  -> Assert-OmiManualBackendStartOwner (retained mutex/controller/source/endpoint)
  -> old ProductionSession.CanStartAfterStop (receipt + original retained exits)
  -> retain old session/LastStop -> DisposeAfterConfirmedStop
  -> New-OmiProductionOwnedBackend (sole production spawn core; source/port recheck)
  -> ProductionSession -> existing Owned Runner -> owned_backend_entry -> Runtime
  -> authenticated READY -> bounded HTTP readiness -> final retained listener identity
  -> Backend started; Frontend unchanged
```

Start eligibility 不是 port free 推論：原 session 必須是 terminal、沒有 StartupFailure，
LastStop 為 `stopped / LIFESPAN_AND_EXACT_EXIT / ExactExit`、非 rearmed，且原 UUID 的
authenticated receipt 有 `no_respawn=true`。重新核對原 launcher／runner／child PID＋creation，
兩個原 retained handles 都已退出且 exit 0；不使用 `GetProcessById` 重取舊 handle。
UNKNOWN／TIMEOUT／REARMED／startup failure／owner lost／creation mismatch 一律不建立新 Backend。

固定 endpoint 取自 **舊 ProductionSession 出生時的 SelectedHost／SelectedPort**，與目前
Launcher config 比對；合法非預設 port 同樣支援。Controller init 早於 service config，不能把
其當時的 port 當 authority。占用檢查使用該 selected port；觀察工具失敗回 unknown／拒絕。
退休前另以既有 `Test-TcpPortBindable` 短暫測試該 host／port，finally 釋放 socket；不可 bind
回 `FIXED_PORT_NOT_BINDABLE`，不退休、不消耗手動 attempt。啟動核心再查占用，不換 port／接管 PID。
probe 不是永久 reservation，其後的 bind race 仍按 startup unknown 保留 owner、禁止自動重試。
loaded Controller reference／OwnerId、有效 mutex handle、OwnsMutex 與初始 lifecycle source digest
必須一致。Backend app snapshot 仍由現有 ProductionSession／READY contract 驗證。

舊 session 在 `RetiredBackendSessions` 保留其 LastStop／receipt／identity。只有重驗 exact stop
後可 Dispose；retirement／spawn attempt 對該舊 session 僅一次。Dispose 或 factory 失敗仍保留
原 owner，不能重試。新 session 一取得就設為 current，之後 readiness 失敗也不丟棄、不 Stop／retry。
`ManualBackendStartAttemptedSession` 指向消耗過的舊 session；新 session 成功 Safe Stop 後可進入
下一輪，舊 receipt 不被新 receipt 覆蓋。

readiness 只做 observation：上限 30 秒輪詢，HTTP response 有總 timeout／size limit，先後以
相同 instance／child PID＋creation／release／host／port 的 runtime-control status 夾住真實
`/api/system/readyz` 的 HTTP 200、`status=ready`、runtime/database checks=ok。最後再查原
retained session／唯一 listener identity 和 loaded lifecycle source。未證實時 UI 顯示 unconfirmed，
保留新 owner；發布 unknown 而非舊 session stopped／新 Backend started。Source hashing 的本機
檔案 IO 不受 HTTP timeout 取消；這不是對不可回應磁碟的強制中止機制。

`SafeStopAttempted` 保持 sticky，沒有解除自動 recovery／舊 Controller pending Restart fence；
timer 繼續 Publish，但不 TakePending。新的 Safe Stop 仍走原 Stop-Services -BackendOnly，
使用新 owner 的新 UUID；成功 stop 清除該次 start-unconfirmed 顯示。操作中的 UI／named events
在原 guard 內合併；依原 enabled state 恢復 timers。`Restart Services` 對 Owned 仍拒絕。

磁碟更新不能熱載入現役 Launcher。換版與正式 cold-start／Live 驗收見
[操作者換版程序](../exec-plans/active/backend-manual-start-20261016/Adoption.md)；
這些步驟尚未執行，尤其 Frontend active 時，舊全服務 Exit gate 不因本功能而解除。

## 固定 HTTP contract

Base URL 仍由 standalone `OMI_search` 的既有動態 Backend discovery 決定。
不可固定假設 port 8400；不得 fallback 到自己 kill PID 或啟動 Backend。

| MCP tool | HTTP method / path | input |
|---|---|---|
| `omi_read_runtime_status` | `GET /api/system/runtime-control/status` | 無 body |
| `omi_restart_backend` | `POST /api/system/runtime-control/restart-backend` | 下列 JSON |
| `omi_read_runtime_operation` | `GET /api/system/runtime-control/operations/{request_id}` | UUID |

```json
{
  "request_id": "b4f9fb4b-0033-4db8-85af-0653ec0b7533",
  "expected_owner_id": "22c6f5dd-d658-47e6-9892-bb4c0fa76b53",
  "confirmation": "restart_backend"
}
```

拒絕 extra fields。`expected_owner_id` 必須來自 status；UUID 是 request idempotency key，
timeout 之後應讀原 UUID receipt，不建立新的 UUID 自動重試。
所有 response 都帶 `Cache-Control: no-store`；schema 為 `omi.runtime-control.v1`。

## 授權

三條路徑僅允許 socket peer `127.0.0.1` 或 `::1`；拒絕 Origin、Forwarded、
X-Forwarded-For、X-Forwarded-Host、X-Forwarded-Proto、X-Real-IP。即使 uvicorn 改寫
scope.client，保留的 forwarding headers 仍使新路徑拒絕請求；既有其他 API 的 proxy/trust 設定不變。

POST 額外要求 **`X-OMI-Runtime-Control-Token`**：由 operator 另行 provision 的
32-byte 高熵 token，以 64 個小寫 hex 字元表示。Launcher 初始化只從**實際 Launcher
程序帳號**的 HKCU Environment（`EnvironmentVariableTarget.User`）讀取
`OMI_RUNTIME_CONTROL_TOKEN_SHA256`（對 token 的 ASCII 字串算 SHA-256，嚴格 64 個小寫 hex）。
不使用其他登入者的 SID／hive，也不 fallback 到 inherited Process、Machine 或 dotenv。
在 Controller 建立與 `Start-Services` 前，將有效值寫入 Launcher 的 Process 環境，
由既有 runner 傳給新 Backend；缺少、無效或讀取失敗時清除舊 Process 值，正常市場服務
仍可啟動，受保護授權維持 disabled。無法清除／設定 Process 環境時不繼續啟動服務。
不寫 registry、不提供預設值、不生成或保存 credential。Launcher log 僅記錄固定的
account scope、`source_user_valid/missing/invalid/unavailable`、`parent_stale/matches/absent`
與 `configured/disabled`，不記錄 SID、帳號、憑證或片段。Scope 不等於 owner attestation。
這是啟動時 snapshot；已執行的 Backend 或被既有 port adoption 找到的 Backend 不會被
更新。程式碼採用後仍須在另行授權的安全生命週期中重新啟動 Launcher 及 Backend；
不得以此修正繞過 restart gates，也不在 tick／GET 路徑熱更新憑證。
Adapter 從其既有安全設定取得原 token；不能讓模型填 token，不能放 URL、log、receipt、
tool result、普通 AI trust token 或 `allow_write`。Provision、rotation 與採用需另行授權。

Header 驗證與 launcher 的獨立驗證都通過，才可持久受理。Confirmation 字串只是意圖，
不授予權限。真正 STOP/START 尚須已驗證專用 Token／Owner／Backend Pipe 身分、完整 drain、
graceful/no-respawn 與 identity proof。正式 Source 的 `BeginAuthenticatedOwnedRestart` 不呼叫 Windows
本機 dialog；已執行的舊 Launcher 不會因磁碟更新取得這個能力。
不存在由 HTTP 輸入提供 approval/drain/identity booleans 的路徑。

## Status schema

`owner_id: UUID|null`；`launcher`、`backend`、`frontend` 各有 `status` 與 `identity`。
有證據才回 `pid`、`created_at`；unknown 不等於 stopped。Backend/Frontend 的
`selected_host`、`selected_port` 只由 launcher 提供；缺少 owner 時可缺省。
`readiness: UNATTESTED` 不因 listener 或 process 存在改為 ready。
`mcp_dependency` 固定保留 unknown／EXTERNAL_ADAPTER_NOT_ATTESTED；OMI 不管理 adapter。
`restart` 包含 availability 與 blockers；available 代表可以申請，不代表已核准或已排空。

Launcher snapshot 的 `backend.ownership_reason` 是固定、非敏感的 identity 階段碼。
成功為 `ATTESTED`；失敗保留 `status: unknown`、`identity: UNATTESTED`、空 PID／creation
與 `OWNER_NOT_ATTESTED` blocker。階段區分 mutex、reload、runner、listener、process evidence、
creation order、ancestry、interpreter path、venv config 與觀察期間 evidence change；不輸出
例外文字、command line、路徑或 credentials。這不是 readiness 或 restart approval。

Windows interpreter ownership 允許 runner → `[cmd.exe]` → expected Python，以及
非 packaged repo 的 runner → `[cmd.exe]` → `.venv\Scripts\python.exe` → base interpreter。
後者必須由同一 repo 的 `pyvenv.cfg` 唯一 `executable` entry 精確對上 listener image。
所有 executable／config 路徑必須為本機 canonical absolute path，任何 ancestor／leaf reparse
都拒絕；base Python 單獨出現不授權。Packaged Python 維持 own-path 判定，不採 venv 例外。
Tracked runner 必須是 Launcher 的直接 child，並與 retained process creation 相符；每個節點
都核對 CIM／OS creation、parent order，限制 ancestry，最後重查所有節點與 selected-port
唯一 listener。CIM 不可取得、PID 重用、額外 supervisor、reload／workers 均 fail closed。
Identity 成功僅移除 `OWNER_NOT_ATTESTED`；其餘 restart blockers、approval、drain、stop/start
與 `source` 語意不變。

獨立 audit 後另要求 Python argv 精確符合既有 `Start-Backend` 的固定 entry、host、port，
不能只有「沒有 reload/workers」。CIM 時間只容許 FILETIME 轉微秒的 0–9 ticks 截斷，
不再使用 1ms tolerance。所有 process retain handle；發布前重查 launcher authority、tracked
runner、paths 與原始 venv config。新增拒絕階段為 `BACKEND_COMMAND_MISMATCH`。

定點測試：`powershell.exe -NoProfile -File scripts/tests/test-owned-backend-identity.ps1`。
它建立有限時的 stdlib child，擷取自身 disposable ancestry 的 OS image／parent／creation
FILETIME，回放到正式 identity 函式；不查 live CIM、不綁 port、不載入 OMI Backend。
負例只替換 OS observation 邊界，執行相同 identity／path／config／status 函式。
這證明 source 與 redirector fixture 行為；正式 Launcher 尚須使用者授權 reload，之後重新
GET runtime status 才能判定 Runtime adoption。既有服務未在此修補中重啟。

`source` 包含 `build_id_scope: runtime_control_bundle_only`、`disk_build_id`、
`import_time_build_id`、`disk_matches_import`、`loaded_release_identity: UNATTESTED`。
這只是固定五個 control source 檔（包含 preflight owner `runtime.py`）的 disk/import-time hash，不是整個 Python release 的載入證明。
`serving_backend` 包含 `runtime_started`、`database_readiness: not_checked`、
`readiness: UNATTESTED`。GET 不連 DB、不呼叫 provider、不讀 health headers、不寫檔、不修復。
Launcher snapshot 超過 15 秒即不可作 owner proof；read 不刷新 snapshot。

`serving_backend.writer_preflight` 是 RuntimeCoordinator 的記憶體觀察：
`omi.restart-preflight.v1`、`runtime_started`、`registered_drain_state`、
`all_writers_drained`、`unknown_writer_count`。沒有 runtime owner 時為 null。
Registered drain state 區分 NOT_REQUESTED、IN_PROGRESS、REGISTERED_DRAINED、INCOMPLETE、UNKNOWN；
它不呼叫 stop、不關閉 admission，也不碰 DB/provider。Unknown writer inventory 仍由
RuntimeDrainResult 的 source default 擁有，不在 transport 複製。
`restart.blockers` 列出尚缺的 gate；`available` 仍為 false。

## Receipt schema 與 HTTP status

```json
{
  "schema": "omi.runtime-control.v1",
  "request_id": "b4f9fb4b-0033-4db8-85af-0653ec0b7533",
  "action": "RestartBackend",
  "state": "blocked",
  "reason": "ALL_WRITERS_DRAIN_UNAVAILABLE",
  "owner_id": "22c6f5dd-d658-47e6-9892-bb4c0fa76b53",
  "before": {"pid": 1234, "created_at": "2026-10-14T00:00:00.0000000Z", "attestation": "PROCESS_IDENTITY"},
  "after": null,
  "updated_at": "2026-10-14T00:01:00.0000000Z",
  "loaded_release_identity": "UNATTESTED"
}
```

`before/after` 可為 null。State：`accepted | running | succeeded | failed | blocked | unknown`。
`accepted` 是 receipt 已原子持久化，並非已批准停止。Launcher 核對 owner、source、readiness，
由經過 OS Pipe 驗證且已交付的同一 UUID intent 在期限內一次性持久轉為 `running`，才開始可撤銷 PREPARE。
`succeeded` 必須由 retained child/runner 正常 exit 0、新 PID **且** creation、同 owner 固定啟動、
實際 HTTP runtime readiness 與 application source snapshot digest 共同證明。
成功時 `loaded_release_identity=APPLICATION_SOURCE_SNAPSHOT`，`application_release_id` 為 digest；
此 scope 不宣稱涵蓋第三方依賴或整個 Python 安裝。正式 live 成功尚未取得。

新增 optional receipt fields：`backend_preflight`、`backend_preflight_identity`、`blockers`、`local_approval`。
新增 `preflight_stage`、`rearm_evidence` 保存真正恢復後的拒絕證據。
舊 receipt 缺欄位仍可讀取；原 UUID replay 返回持久化原值，不採用新報告、不重新 enqueue。
只有 OS pipe client 的 PID＋creation 與 launcher 已持有的 Backend identity 完全相同時，
才保存 typed preflight 報告。缺失、格式錯誤或 caller identity 不符時，報告為 null，
舊 preflight reducer 保留 `BACKEND_PREFLIGHT_NOT_ATTESTED` 語意，僅供相容 evidence 測試。
正式 owner 在 tick 前改變則 `blocked/OWNER_NOT_ATTESTED`；缺少 retained ProductionSession
則 `blocked/OWNED_BOOTSTRAP_REQUIRED`，不會進入 legacy stop。
`blocked/PREFLIGHT_REARMED` 必須由相同 child 的 inherited ACK 證明 lease 已撤銷，並再核對
原 process 仍活著。未知、未能 rearm、STOP delivery 不明均為 unknown，不可自動重送。

- POST `202`：accepted/running；`200`：原 succeeded receipt 的 idempotent replay。
- POST `409`：blocked/failed 或 owner UUID 衝突；不得當成已重啟。
- `403`：loopback/專用 token 授權拒絕，`error: RUNTIME_CONTROL_FORBIDDEN`。
- `422`：不合法 UUID、confirmation、額外欄位或超過 1024-byte body；POST 不回顯輸入。
- POST `503`：controller、store 或 terminal evidence unknown；不自動 replay。
- GET `200`：status 或 receipt（包括 unknown）；沒有 receipt 是 `unknown/NOT_FOUND`。
- Controller 不可達時，GET receipt 為 `unknown/CONTROLLER_UNAVAILABLE`，不是失敗或成功。
  Backend 暫停時 adapter 回 transport unavailable；待 Backend 回來後用原 UUID 查詢。

## Owner、持久化與 staged adoption

控制通道是 existing mutex-owning launcher 內的 Windows named pipe；不是新 daemon、
Control Center、stdio adapter 或一般 shell gateway。只有固定 Status/ReadOperation/RestartBackend。
Pipe ACL 只允許 current user，拒絕 network SID；Backend 以 launcher-inherited PID＋creation
驗證真正 pipe server。外部 HTTP 不能指定 pipe、路徑、PID、port、executable 或 command。

正式呼叫鏈：固定 adapter relay → Backend runtime-control router → `app.state.runtime.restart_preflight()`
的唯讀觀察 → `launcher_request(RestartBackend)` → 既有 launcher pipe/controller →
`Restart-Backend` → Consume authenticated intent（不跳本機視窗）→ retained `ProductionSession.Stop` → Runner →
Backend PREPARE／commit → exact exit → 同 Launcher 固定 start → readiness → durable receipt。
報告只透過內部 pipe 的 optional `backend_preflight` JSON 字串傳送；HTTP body 不接受此欄位、
drain/approval booleans 或 caller identity。新增接線不改 adapter，也不增設 process manager。
舊 Backend 不送報告時仍可讀取及提交原 contract，但新 controller 明示缺少 preflight，不能解鎖。
Backend 與 launcher source adoption 需協同完成；舊 controller 對新 internal field 可回 unknown，
不得將 mixed-version unknown 當作 retry/restart 授權。

Production 不接受 caller-supplied boolean approval／drain；舊 fixture reducer 已從 Controller 移除。
ProductionSession 的實際 process evidence
由 internal constructor/setter 建立；HTTP 不提供 gate values。

Receipt store：`%LOCALAPPDATA%/Open Market Intelligence/runtime-control/<repo-path-sha256-prefix>/`。
目錄只允許 current user；既有寬鬆 ACL 或 reparse point 不修復，直接拒絕。這不是抵抗相同
Windows user 的惡意程式的 sandbox。原子 write-through temp＋replace；最多 2048 receipts，
滿時拒絕新增、不自動刪除 idempotency evidence。保留與 operator archival 尚需後續設計。
Crash 後 accepted/running 轉 unknown/CONTROLLER_RECOVERED_NO_REPLAY，不重放或推定成功。
已 terminal receipt 跨 launcher instance 保留。同 UUID 不得綁定其他 owner。

新 RestartBackend 不呼叫 Stop-BackendService、port-owner cleanup 或 Start-Backend fallback。
正式 non-reload／non-packaged cold start 使用同一 Runner 的 owned branch；固定 port 被占用就拒絕。
Owned start attempt 一旦發出，舊 auto recovery（包括換 port、停止 Frontend）與舊強制停止入口
均不可用。啟動握手失敗保留 Runner／child handle，無重試、無 port adoption。
Frontend／MCP 不在 RestartBackend 控制範圍。Legacy menu 若企圖走 force stop 會被拒絕。

## Owned shutdown transport（2026-10-15）

`omi-runtime-control.ps1` 的 launcher extension 持有 `OmiOwnedShutdown.LauncherSession`；
disposable launcher 取得自己的 named mutex，直接啟動既有 `run-service-logged.ps1`
的 `-OwnedShutdownChannel` branch。該 branch 對所有結果都 terminal exit，不能落入
舊 cmd.exe／force／auto-respawn loop。C# 是兩個既有 owner 的內嵌 helper，不是新 daemon、
Control Center 或 generic command runner。

控制使用建立 child 時繼承的 stdin/stdout pipes，沒有可從 HTTP 連線的 stop endpoint。
Launcher 保有 runner handle，Runner 直接持有 base Python 的 OS process handle；
固定 repository、interpreter、child entry 與空 argv，控制 frame 不接受 executable、shell、
target PID、port 或 import path。Frame 綁 instance UUID、request UUID、隨機 256-bit nonce、
launcher／runner／child PID 與 Windows creation FILETIME、期限。Child 核對實際 parent PID；
Launcher 與 Runner 核對自己建立的 process object，child 再核對 owner creation。
Inherited capability 不對抗相同 Windows SID 的惡意程式或管理員。

Session 分為既有 `DISPOSABLE` 與固定 `PRODUCTION`。正式 Launcher 只建立 ProductionSession；
固定 `backend/owned_backend_entry.py` 以 `-I -S -B` 啟動，捕捉 app Python source bytes，
之後 app imports 只編譯 snapshot，拒絕新插入 module；Launcher 與 child 核對同一 digest。
Disposable approval／receipt 不能供正式路徑使用。

Disposable approval 與 child writer proof 分離：launcher fixture 對指定 UUID 提供合成核准，
child 的 private PREPARE 實際封閉 fixture admission、release/join 已接件 worker，核對完成數。
Active／unknown writer 不產生 drain proof；它只證明隔離 app，不是 production 全 writer inventory。
合法完整 proof 後 Runner 先 latch terminal no-respawn，CreateNew＋write-through＋Flush(true)
保存不可覆寫 intent，才送 STOP。Journal 只在新的 task-private protected DACL 目錄，拒絕
existing directory、reparse ancestor、不符 owner／ACL；不修復既有權限。

`backend/app/owned_uvicorn.py:serve_owned` 是實際 reusable ASGI 退出入口。收到合法 STOP 才
設定持有的 `uvicorn.Server.should_exit`，等待 Uvicorn 完成 lifespan 後再回完成訊息。
既有正式 app 的 lifespan 仍是 `finally: await runtime.stop()`；沒有搬動市場／交易／DB owner。
固定 production entry 已完成 source 接線；現役舊程序尚未採用。Production PREPARE 不呼叫
terminal stop。成功後僅有 5 秒 commit lease；owner/channel 消失或沒有 STOP 會自動 rearm。
控制 reader 消失不會拋出 BrokenPipeError 去取消 serving task／意外觸發 lifespan stop。

正式 entry 現在先讀取有界 boot frame、驗證實際 runner parent／owner creation、nonce 與
inherited launcher／host／port，再 import `app.main`。不使用 Uvicorn 預設 port、reload 或
workers。應用程式 stdout 與 inherited control output 分離。`READY` 若由正式 entry 發出，
還須實際 server.started 與 runtime.started；其中 loaded_entry_sha256 只 hash 執行中的
transport code；另外的 `APPLICATION_SOURCE_SNAPSHOT` digest 來自實際 import bytes。
Source parity 已驗證，但不是現役 runtime adoption 或完整依賴 release certificate。

## 可撤銷 writer quiescence 與 native authority

RuntimeCoordinator 沿用各 owner 的 admission／transaction boundary：HTTP ASGI scope 包含
streaming 與 BackgroundTasks；scheduler 在實際 dispatch lock 下暫停，等待 executor 工作；
AI detached threads 在 Thread.start 前註冊，等實際 thread exit，不能用 HTTP timeout 當完成。
之後暫停 Session scope、Fugle/Crypto 接收與 materialization／auto refresh，讓已接件工作自然結束。
Final flush 仍由原 owner 執行；Fugle unresolved materialization、Crypto pending/error 會拒絕。
最後原子暫停 idle Job、publisher 與 physical SQLite admission，檢查 canonical Engine unknown。
取消等待不取消 DB thread，失敗反向撤銷 exact private lease，恢復接件。

canonical Engine、maintenance raw sqlite3 與 independent migration Engine 共用 physical registry。
Driver close callback 綁唯一 physical token；SQLAlchemy record reuse 不會讓舊 close 消掉新 connection。
Pool checkin 不等於 physical close，未知 driver／constructor／close failure 保持拒絕。

全本機已知 writer quiescent 後，RuntimeCoordinator 對既有絕對 local SQLite target 取得
`BEGIN IMMEDIATE` native transaction；Windows 額外以禁止 delete sharing 的 handle 固定 main path，
拒絕 reparse、hardlink 與非本機磁碟。這會排除遵守 SQLite locking 的其他程序新寫入，含 WAL；
不宣稱能防止任意程式直接破壞檔案。失敗釋放 native authority 後 rearm，未知結果保留 unknown。
成功的 commit 保持 native transaction 到 process exit；不以短暫探測後釋鎖當 authority。
原始依據：[SQLite transaction](https://www.sqlite.org/lang_transaction.html)。

Owned startup 只以 read-only SQLite 讀既有 revision，必須已在 head；不建立 DB、不自動 migration。
只有 lifespan 的 registered owners 與 physical Engine drain 完成、native authority 仍持有，
才會將結果投影為 all_writers_drained；一般 terminal stop 與舊 live runtime 仍保留 unknown inventory。

## Canonical writer fence 與 authenticated remote intent

`get_db` 正式沿用原 `owned_session`／`get_draining_db`，constructor 之前保留 owner，
正常 scope 結束後關閉 Session；取消或 close failure 保留 unknown。production lifespan
啟用 API/startup scopes。`restart_preflight` 仍是純記憶體觀察，不呼叫 stop 或 close admission。

`EngineAdmission` 附掛於 `db/session.py` 建立的 canonical Engine。`do_connect` 在 driver
constructor 之前保留 lease，checkout／checkin 追蹤借用；包括直接 Session、Engine、
raw_connection 的正常路徑。detach／invalidate 保留 unknown，正常服務期間 reconnect
不會刪除舊 unknown，也不被 restart fence 提前阻止。registered jobs／collectors／publisher／
API scopes 完成後，RuntimeCoordinator 才 terminal-close 此 Engine 的新 admission，等待
既有 lease 歸還。這樣既有工作仍可 lazy-open connection 完成交易。逾期／unknown 不升格，
terminal commit 後沒有 same-process rearm；commit 前則可撤銷。Pool checkin 只證明 lease
歸還，不等於後續 driver close 完成；實際 close token 由 physical registry 擁有。

maintenance backup／VACUUM 改用 tracked physical connect，migration Engine／Alembic
附掛同一 registry 並在 finally dispose；交易內容不變。其他程序靠上述 native SQLite authority
排除新寫入；`schema.lock`／`background.lock` 本身不能授予這項能力。

遠端 MCP 的 **單次 RestartBackend Intent** 先由 Backend API 驗證專用 Token，
Launcher Controller 再驗證 OS Named Pipe 的 Backend PID／creation、typed preflight、
當前 Owner UUID 與唯一 pending request。只有通過檢查並先持久保存 accepted，
Controller 才在記憶體登記不可由 public Dispatch／GET 重新建立的 intent 證據。
Launcher tick 以 TakePending 取出同一 UUID 後，`BeginAuthenticatedOwnedRestart`
在 30 秒（UTC＋monotonic）內重查 retained process／Owner／source availability、
相同 request、backend preflight identity 及一次性消耗狀態，先持久保存 running，
再交給原 Owned Stop→Start 流程。**不要求 Windows 本機 Yes/No**，不以 caller 輸入
`approval`、`all_writers_drained`、`local_approval` 等欄位解鎖。
舊 `local_approval` 收據保留唯讀相容；舊 rejected／unknown／accepted 在新 Controller
不得重新取得執行權，也不重送原 UUID。授權與 Writer Drain 是兩個獨立 Gate。

成功條件是 identity-bound completion **及**原 child retained handle 在 UTC 與 monotonic
deadline 內 signalled、exit code 0、owner 仍存在。STOP_ACCEPTED、lifespan ACK、PID 消失
任一單獨都不算成功。取消於 delivery 前返回 cancelled；送出後不提供反向 rearm 或 force
cancel。Timeout、lifespan failure/cancellation、runner crash、owner loss 保留 unknown／blocked，
late fixture lease exit 不升格結果。相同 UUID 重讀 cache，不再發送；terminal session 拒絕新 UUID。
新 instance 不讀 journal 重放，也不能重用舊目錄。正式 approval／receipt 沿用 Controller store；
Runner journal 只記錄實際傳輸／退出證據，不是第二個 approval owner。

測試 fixed app 使用既有 B4 AST loader 載入 unchanged RuntimeCoordinator／session／publisher
source，實際執行 stop 與 Uvicorn lifespan。仍保留 `all_writers_drained=False`。無 listener、
production app startup、DB/provider IO；fixture-only 有限 lease 用 cooperative shutdown 收尾。
證據見 [本輪紀錄](../exec-plans/completed/owned-backend-shutdown/Progress.md)。

## 2026-10-15 歷史 adoption／live gates（當時紀錄，非最新現況）

G1–G5 的正式 source 已接線，定點測試包含恢復接件、跨程序 native lock、physical token、
真實 APScheduler pause/resume、固定 source digest parity 與 C#／PowerShell syntax。
這些證據不替代本輪新版 boot／受驗證遠端 intent／STOP／新 process readiness／durable succeeded receipt。
目前先阻擋於 `OWNED_BOOTSTRAP_REQUIRED`：現役舊 Backend 無 inherited channel 及可撤銷 preflight。
禁止先停它再嘗試把新能力補上，也禁止 inject/adopt/force/retry。需由 owner 在可證安全的維護
生命週期完成初次 Launcher／Backend source bootstrap；本輪限制內沒有能安全退出舊程序的路徑。
新版 Launcher 採用後，須以新的 UUID 經正式 MCP 遠端 Restart、無本機對話框、同 UUID durable receipt 驗收。

後續 standalone adapter 僅機械轉送以上三個 endpoints，不把 runtime tools 加入 `/api/ai/ask`。
舊 Backend 404 代表 source 尚未採用，不能自行啟動 owner。其他 MCP tools 不依賴此 feature。
