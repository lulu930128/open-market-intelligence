# OMI runtime control v1 — source contract

## 2026-10-26：操作／generation 恢復與 Backend 離線控制（Source）

本節取代下方歷史 checkpoint 的「同 owner lifetime 只能一次 schema／failed-start recovery」限制。
歷史 receipt 保留；沒有 hot reload、正式 DB migration 或跨應用 E2E 驗收。

`SchemaMaintenanceAttempted`、`SchemaMaintenanceFailed`、`FailedStartRecoveryAttempted`
只保留診斷用途，不再是全域永久 admission veto。自動 startup 的
`OwnedBackendStartAttempted` 仍防止 factory 結果不明時自動再 spawn；明確 Start／Recovery
走原 retained session 的 `CanStartAfterStop`／`CanRecoverFailedStart` 與退役 gate。
同 UUID 不能重播，同 session 不能再次退役；新失敗 child 必須提供自己的原始收據與 exact exits。

Schema operation 使用 CreateNew JSONL、終態 hash 及原 owner 記憶中的 worker 結果。
純 preflight refusal 或 native STOP-not-sent／rearm 證據可重新檢查新 UUID。
backup 等前置工作失敗時，必須同時有 retained worker exact exit、nonce-bound
`FAILED / NOT_ATTEMPTED` reply、持久終態與未改寫 receipt，才能再進原 maintenance lane。
新操作重新驗 DB/head/source、owner/process generation；不是清除布林後重跑。
`COMMITTED` 必須有原 worker 成功 reply 才能繼續新 retained generation 的恢復。
未知 transaction、lost reply、遺失／改寫 receipt 或未知 factory 仍拒絕危險操作；Status、
ReadOperation 與 Plan 保持可用，要求 worker／DB／generation reconciliation，不自動 restore/stamp。

普通 Restart 在消耗一次性 intent 後擷取當時磁碟 application release 作為 successor pin，
不要求新版等於舊 session `ReleaseId`。舊 session 的 retained handles、PID／creation、
loaded release 與 STOP protocol identity 保持不變；Runner 的私有 `target_release_id`
只檢查新 target，不傳入舊 Backend 的 identity。Start-after-stop 仍使用原 session release。
Stop 前先驗 Launcher loaded lifecycle source／Controller／endpoint，再由固定唯讀
`CheckStart` 檢查 configured SQLite metadata/head 與原 loaded DB binding、owner UUID、PID。
不相容時保留舊程序，普通 Restart 不 migration。PREPARE 前後、exact stop 後、factory 與
readiness 均驗同一 target pin；source 中途變更不可重新取新 pin 或額外 start。
原 180 秒 cutoff、owned exit 與 forced-stop reconciliation 保留。
這是 hash-pinned restart，並未建立 immutable release store；不保證偵測檢查間改動後又還原的 source。
Launcher lifecycle source 改動需另走明確 Launcher update；Backend Restart 不 hot reload owner。
明確 SchemaUpgrade 在 Stop 前要求 configured target 與已知 behind revision；之後仍走
原 graceful stop → schema.lock／SQLiteWriterLease (`BEGIN IMMEDIATE`) → verified backup／
restore-copy → Alembic transaction → successor。普通 Restart 不 migration，maintenance 不強停。

### 2026-10-26：OMI Search direct pipe 遠端 intent（Source）

本節取代上一輪要求 `actor=launcher_local_operator` 及 Launcher 本機 Yes/No 的設計。
遠端 Restart／Start／Recover／Schema 沒有 MessageBox、OpenFileDialog 或 approval boolean。
唯一執行 owner 仍是原 Launcher；既有 Backend HTTP／pipe 路徑保留。

同一 pipe `omi-runtime-<sha256(lowercase absolute repo root) 前 24 字元>`，不增加 manager、
daemon、HTTP listener 或 generic shell。adapter 必須驗證並 retained 真 Launcher process handle，
比對 pipe server PID／creation；同名 pipe 不構成身分。server 使用 current-user SID ACL、拒絕
Network SID，驗證專用 token 的 SHA-256（constant-time compare），從 OS 取得 caller PID、
保留 process handle／creation，並在消耗時重新核對。caller 需存活到 owner 消耗 intent。
身分不依賴 caller 宣告的 actor、PID、argv、approval 或 writer report。

每個 request 是單行 UTF-8 JSON，結尾 LF、frame <16384 bytes，無額外欄位。
四個基本欄位固定為 `action,request_id,expected_owner_id,token`；值為字串。
mutation 的 request_id 是新 D-format UUID，expected_owner_id 必須等於 Status 的 owner UUID。

| action | confirmation／wire | 執行 gate |
| --- | --- | --- |
| Status | 四基本欄位；request_id、expected_owner_id、token 可為空字串 | SID pipe 唯讀；Backend offline 可用 |
| ReadOperation | 四基本欄位；request_id 為既有 UUID | 唯讀原 receipt；不重建執行權 |
| RestartBackend | 四欄相容格式，或加 `confirmation=restart_backend` | retained running Backend；Stop 前 source／schema／binding；原 PREPARE、writer fence、180s deadline、Stop／Start |
| StartBackend | 五欄，`confirmation=start_backend` | 原 stopped exact-exit generation；原 release pin／start gate |
| RecoverFailedStart | 五欄，`confirmation=recover_failed_start` | 原 failed-start receipt、retained handles、exact exits 與單次 retirement |
| SchemaUpgrade | 五欄，`confirmation=upgrade_schema` | configured target、原 schema admission、備份、writer lease、transaction／rollback 與 successor gates |

既有 OMI Search MCP `omi_restart_backend` 已在 tool 邊界要求 `confirmation=restart_backend`，
既有四欄 pipe 省略 confirmation 只對 Restart 相容；Controller 將固定 action 正規化為同一
confirmation 並寫入 receipt。它不是任意 action 的省略規則。若有提供 confirmation，必須完全
吻合。Backend legacy wire 可另加 `backend_preflight` JSON 字串（五欄），只接受 OS caller
恰為 retained Backend 的觀察；direct caller 不得冒報。不可同時傳 confirmation 與 preflight。

Controller 先 durable accepted 再排入 single-flight。Launcher TakePending 後核對 retained caller，
先消耗記憶體 authority，再 durable running，最後才進原 lifecycle；不彈本機確認。
重送 UUID 只讀回同 action／owner 的原 receipt，不重排執行；跨 action／owner 不授權。
歷史 local actor／approval 僅為 receipt 解碼相容，沒有 live intent，不能重建權限。
新 receipt 的 `actor=authenticated_pipe_client` 由 Controller 產生，`requester` 是 OS PID／creation，
`confirmation` 是固定值，`intent_consumed_at` 記錄一次性消耗。token 永不寫入 receipt／log。

SchemaUpgrade 由 `Invoke-OmiConfiguredSchemaUpgrade` 呼叫固定私有 readonly
`CheckStart --upgrade`。inspector 讀 Launcher checkout 的 configured database_url 與
runtime_lock_dir/schema.lock，回傳經 canonical path／reparse／schema／binding 驗證的
configured_target；不猜測路徑。原 owner 再驗 paths，呼叫 `Invoke-OwnedSchemaUpgrade` 一次，
由現有 worker 重新驗 target、schema lock、SQLiteWriterLease、備份與 migration。
若 selector 缺失、target 不安全、DB revision／binding 不相容，收到
`blocked / SCHEMA_CONFIGURED_TARGET_UNAVAILABLE`，migration／successor 仍為 NOT_ATTEMPTED。
ReadOperation 提供 `next_action=Status_then_CheckStart_configured_target_diagnostics`；Status／
ReadOperation 可遠端讀取，CheckStart 是 Launcher 私有診斷，不是 generic remote command，
不以新 UUID 盲目重送 migration。未知 worker／transaction／receipt 保留原 reconciliation fence。

本 repo `Invoke-OmiLauncherCommand` 接受固定 Action、已驗證 retained Owner handle、
ExpectedOwnerId、RequestId、Token，產生固定 confirmation；不讀／配置 credential，也不自行
發現或接管 Launcher。只有同使用者、持有專用 runtime-control capability 的 adapter／既有
Backend caller 能 mutation。僅知 pipe 名稱或 owner UUID 不足以授權。

跨 repo 新 MCP tools 另任務接線，見 [精確 adapter 交接契約](../exec-plans/completed/remote-intent-20261026/WireContract.md)。
`ApplyRelease` 不曝光。Source／isolated fixture 與 loaded Runtime／ChatGPT E2E 分開驗收；
本輪未部署、restart 或操作正式 DB。Controller receipt 分列 stop／migration／successor，
accepted／running 不代表完成。詳見 [本輪證據](../exec-plans/completed/remote-intent-20261026/Progress.md)。

## DB Schema 單次升版（Source／fixture；Runtime／Live 未採用）

`scripts/omi-schema-maintenance.py Plan` 是 OMI 自有唯讀診斷入口，使用原 Alembic graph，
不載入 dotenv、不猜 DB 路徑。可選擇比對既有 loopback runtime 的 loaded configuration，
但不把 fingerprint／readyz 當作 exact DB handle 或全 writer exclusion。
`Gate` 保留舊 refusal 收據；`Status` 可唯讀檢視 Gate、worker 與外層 operation。
普通 owned Restart 不執行 migration；schema mismatch 指向此診斷並保留 failed-start receipt。

已載入新 source 的原 Launcher tray 提供 **Upgrade DB Schema**；點選即為本地 intent，
與遠端 action 共用 configured target，沒有檔案挑選。原 owner 的 single-flight、timer／event fence 包住全程；
不停止 Frontend，不使用 Apply Update。若載入 Launcher 新 source 需完整退出而影響 Frontend，
必須另行允許 downtime，不能以這個 Backend-only action 暗中代辦 adoption。

正常分支使用原 ProductionSession 的 graceful STOP protocol，不進 hard cutoff；必須有當次
request 的 retained child／runner exact exit、原 graceful receipt 與 `CanStartAfterStop`。
failed-start 分支使用 `CanRecoverFailedStart`／原私有 START_FAILED receipt、retained handles、
creation／exit code 的獨立 admission，沒有偽造 StopEvidence。migration 成功後才
`RetireFailedStart`，接原 `Start-OmiBackendSuccessor`，最多呼叫 factory 一次。
普通 stop／forced-stop／舊 failed-start receipt 不能當新的升版授權。

私有 `ApplyStopped` worker 不是公開 operator command：以 OS QueryFullProcessImageName、
NtQueryInformationProcess／固定 PowerShell `-File` grammar，以及 NtQueryMutant 的實際
Launcher mutex owner PID 驗證 parent，再與原 ProductionSession 的一次性 admission 做
challenge handshake。PID／creation／caller JSON flags 本身不授權。worker 驗 configured
DB／lock target，只輸出白名單結果；source pin 包含 application、Alembic 與 backup／worker。

Backend exit 會釋放舊 lease，**不宣稱連續持有**。離線 worker 取得既有 ProcessFileLock
`schema.lock`，並用 SQLiteWriterLease 在已初始化的 SQLAlchemy Connection 上取得
`BEGIN IMMEDIATE`；取得前已完成的外部寫入會進入後續 backup。原 backup utility 以獨立
readonly reader 複製／full integrity／schema snapshot／SHA-256，再驗獨立 restore-copy。
restore-copy 永不覆蓋原 DB。Alembic `config.attributes["connection"]` 使用該 maintenance
Connection，migration／head／integrity 檢查完成後才由 maintenance commit；SQL authorizer
拒絕 migration 提早 COMMIT／ROLLBACK。其他 SQLite writers 在 reservation 持有期間被排除。

外部 readers 可以存在；rollback journal reader 阻擋 commit 時明確失敗，不 retry。commit
釋放 reservation 後到 successor ready 之間，外部 writer 可以再次寫入；不宣稱保護任意檔案
寫入或 privileged interference。上述限制寫入 worker receipt，沒有不可達的 all-readers gate。

operation 與 worker 分開 durable JSONL，exclusive create、sequence、request UUID、flush／fsync；
同 request／同 owner 的升版 attempt 不重播。worker 只證明 migration，外層的
`migration_outcome`／`successor_outcome` 分開：

- `BLOCKED_NO_DB_CHANGE`：未進 migration；stop 結果仍另列，不把 DB 無變更當 runtime 健康。
- `UNKNOWN_RECONCILIATION_REQUIRED`：worker／transaction outcome 未知，保留原檔與 receipt。
- `MIGRATED_START_UNVERIFIED`：commit 已知，但未實際呼叫 successor factory，例如 IPC reply lost。
- `MIGRATED_START_FAILED`：commit 已知，已呼叫 successor factory，但 identity／release／readyz 未全部通過。
- `SUCCEEDED`／`COMPLETE`：migration committed 且原 successor 的 PID／creation／release／readyz 全部驗證。

receipt 的唯讀觀察不授權 replay／start。stop／worker 可能已發生後失敗，保留 reconcile fence；
純 preflight refusal 只消耗 schema request，恢復原日常 Restart admission。失敗不自動 restore、
downgrade 或重試，不改原 failed-start 收據，不刪 DB／WAL／SHM／backup。SQLite 的正常
transaction rollback 不等同於 restore／downgrade；實際殘留狀態仍需人工檢視。

0092 對 baseline 已建立的同名 index 僅在 canonical SQL 定義相同時跳過；異質定義拒絕，
沒有 drop/recreate／stamp。Source fixtures 的 empty→head 與 0092→0093 不代表正式 DB 驗收。
詳見 [工程交接與離線證據](../exec-plans/active/schema-maintenance-20261025/Progress.md)。

## 2026-10-25 明確人工 Failed-start Recovery（Source；Live 尚未採用）

原 Launcher tray 的 **Recover Failed Backend Start** 是獨立人工入口，與 Start Backend
共用 single-flight、timer／event fence 及 bounded successor startup。沒有 CLI／MCP
recovery action、背景重試或 legacy fallback；Backend-only，不碰 Frontend。

`ProductionSession.CanRecoverFailedStart` 不使用 StopEvidence，也不修改
`CanStartAfterStop`。它要求原 owner PID／creation、child／runner retained handles、terminal、
原始 START_FAILED memory receipt 與 private journal 一致、child 非零 exact exit、runner
exit 79，且沒有 Stop／cutoff／readiness／退役歷史。遺失 handle／收據、事後僅靠
RefreshStartupExit 觀察、IO／ACL／identity unknown 均拒絕；不補造成功 Stop 或更改
StartupFailure。原 receipt 不會被 recovery intent 覆寫。

Launcher 驗 Controller reference／owner UUID、mutex、loaded lifecycle digest、原固定
endpoint、listener／bindability 及唯讀 process inventory。相關 process command line
缺失或 CIM 失敗即拒絕；其他 Backend 或 runner 存在亦拒絕。此觀察不取代後續 DB
maintenance 的全 writer exclusion／schema lock。

新 request UUID 不得重用原 restart UUID 或 startup instance；每個 owner lifetime 最多
消耗一次 failed-start recovery。C# 在同一 stopGate 內再核對證據與 successor release，
先 latch，再以 CreateNew／write-through／Flush(true) 保存獨立 recovery intent，最後退役。
IO／Dispose／factory 失敗仍消耗 attempt。新 session 使用原 factory 的新 instance／nonce；
readyz、owned identity、release 與 publication 全部成功才顯示 recovery verified。

這不是既有 Launcher 的 hot reload／handover。磁碟改好不代表原 loaded owner 可使用，
舊 session 不能跨 owner 採用。若現有正式換版能力會退出 Frontend 或強切，而任務禁止
這些動作，結果保持 SOURCE_READY／ADOPTION_BLOCKED，DB backup／migration／Start
均不得越過 gate。單次證據見
[執行紀錄](../exec-plans/active/launcher-failed-start-recovery-20261025/Progress.md)。

## 2026-10-22 已授權的 graceful → 180 秒 hard cutoff（Source／隔離測試）

使用者已明確授權 OMI 自有程序的有界強制終止。本節取代本文較早 checkpoint 的
「drain 失敗永久 blocked／不 force」處置；原 graceful、Job checkpoint、writer 與資料
完成語意仍保留。以下能力尚未採用至現役 Launcher，本輪沒有 Live stop/restart。

| 操作 | 停止範圍 | 停止後行為 |
| --- | --- | --- |
| Exit Launcher | owned Backend／Runner、owned Frontend 應用樹、Launcher cleanup | 關閉，不重開 |
| Stop Services | owned Backend／Runner、owned Frontend 應用樹 | Launcher 留存，服務保持停止 |
| Restart Backend／MCP | retained Backend／Runner | 原 ProductionSession／Backend Gateway 啟動一次並驗證 generation／HTTP |
| Restart Backend + Frontend | 同一 Launcher 的 Backend、Frontend | 原雙服務入口重啟並驗證兩者；不換 Launcher |
| Apply Update | exact Launcher、正式 Backend／Frontend runner 與固定應用鏈 | 原 VBS 啟動一次；驗證新 Launcher、Backend，Frontend readiness 另列 UNVERIFIED |

`LifecycleDeadline` 在 owner 接受操作時建立，production 固定 180000ms，採 Stopwatch。
Exit → Stop Services → Backend、雙服務 restart → Backend restart 均傳同一物件。
遠端 Controller 自 authenticated acceptance 開始計時，TakePending／Begin 不重設，
不因舊 30 秒 intent age 再變成 writer refusal。已耗盡的 deadline 直接進強切。
正式 Apply Update CLI `TimeoutSeconds` 僅接受 180；縮短只供 internal／隔離 fixture。

內層既有 wire protocol 仍最多 120 秒，使用 `min(120s, outer remaining)`，沒有第二次
PREPARE／STOP。rearmed、Job／Writer unknown 或 pipe send/read 卡住後等待原截止時間。
ProductionSession 的獨立 Task 不持 stopGate 等待 IO，到期先終止 retained runner，
再終止 retained child；不依賴 UI DoEvents。Launcher 有額外 5 秒收據返回上限；
kill 後最多 3 秒 exact handle exit 觀察不是新的 graceful window。

身份始終要求 PID、creation、原 retained handles／Launcher generation；不能靠埠、HTTP、
模糊名稱或 ancestry alone 授予 kill。Frontend preflight 不再擋住 Backend 先停；
Frontend 必須驗證 birth runner。未知或 foreign Frontend 保留並回報 identity failure，
不宣稱完整 Exit。Backend-only 不碰 Frontend、Launcher 或其他 MCP。

Controller 的 `restart.available=false`、typed preflight 缺失／UNKNOWN／runtime_started=false
不再否決 token＋OS pipe client＋exact Backend owner 已認證的顯式 intent。保留 owner
mismatch、單一 pending／active request、UUID 與 no replay。Router 只轉送，不以 writer
availability 自行回 409。原 consumer/API 不取得 process ownership。

強切收據是 `forced_stopped / HARD_CUTOFF_EXACT_OWNED_EXIT`、`ForcedExitConfirmed=true`、
`ExactExit=false`；不產生 `LIFESPAN_AND_EXACT_EXIT`、writers drained 或 Job completed。
保存 accepted/cutoff timestamp、elapsed、request、PID／creation／process generation、
graceful reason／stage 與 `RECONCILIATION_REQUIRED`。Runner session journal 與 Controller
receipt 保留 evidence；Controller 以 plain dictionary 讀回，不將 serialized data 變成
StopEvidence authority。receipt IO 不阻止已授權的 exact termination；無法落盤時明示
persistence unconfirmed，保留 memory evidence／Launcher log。

不改 DB、JobRun、checkpoint、quota 或歷史 unknown。下次正式 startup 由原 interrupted
cleanup／validated continuation owner 處理；HTTP ready 不代表對帳完成。啟動失敗保留
「舊程序已停止／新程序不可用」的區別，不宣稱重啟成功。

## 舊載入 Launcher 的一次性 Apply Update 入口

```powershell
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File '.\scripts\apply-omi-update.ps1' -TimeoutSeconds 180
```

這是 reviewer 決定 adoption 後的入口；本輪沒有執行。短命 helper 確認原 Launcher
mutex 被持有，捕獲唯一 exact `-File <repo>\scripts\omi-launcher.ps1` 的 PID／creation／
完整 commandline／retained handle。只納入同 repo、同 LauncherPid、正確 ServiceName／
WorkingDirectory 的正式 runners，並沿 Backend owned Python entry／Frontend npm／Next
固定應用鏈擴展。瀏覽器、Explorer、其他工具及其子樹保留，不阻擋 OMI owner 停止。
不使用 `taskkill /T` 或 port cleanup；切斷前重查 generation，僅對 retained handles 操作。

只送一次原 Exit event。正常退出要本次 terminal log、mutex release、原 owner 與 scope
內 handles exit；舊版 blocked／rearmed／modal 不會重設期限。到期 one-shot cutoff，
abandoned mutex 不冒充 graceful。snapshot/cut 間新增的 OMI child 導致 unconfirmed，
不啟動另一套 owner。scope 內與排除 scope 的 ancestry 不互相代替。

確認舊 owner 停止後釋放原 mutex、呼叫原 VBS 一次。唯一 read-only verifier 最多 110 秒，
驗證新 Launcher PID／creation、OS pipe server、loaded lifecycle digest、application release、
Backend PID／FILETIME／host／port、`/api/system/runtime-control/status`、
`/api/system/readyz`，最後重查同 generation。404 明確報 route error；其他暫不可觀察在
同一 observation budget 內重查，沒有第二次 spawn／kill。

成功為 `UPDATE_BACKEND_READY`／exit 0，`update_applied=LAUNCHER_AND_BACKEND_VERIFIED`，
`backend_readiness=VERIFIED`、`frontend_readiness=UNVERIFIED`，不是雙服務產品驗收。
新 generation 未確認時 `NEW_START_UNVERIFIED` 或 `UPDATE_START_UNAVAILABLE`／exit 2；
保留舊 owner stop 結果、VBS 次數與新服務不可用。收據位於
`logs/launcher/updates/<request-id>.json`。證據見
[本輪紀錄](../exec-plans/completed/lifecycle-hard-cutoff-20261022/Progress.md)。

## 舊 Apply Update checkpoint（已由上述 180 秒強切政策取代）

Lifecycle source 已改、舊 Launcher 回 `SOURCE_ADOPTION_NOT_ATTESTED` 時，在 repo root
由已授權 PowerShell／Codex Bridge 執行單一命令：

```powershell
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File '.\scripts\apply-omi-update.ps1' -TimeoutSeconds 180
```

短命 helper 向現有 `OpenMarketIntelligenceLauncherExit` event **只送一次**，沿用舊 owner
的 Exit → Safe Stop（Job 收尾、SQLite commit／rollback、Writer Drain、Backend exact exit）
→ Frontend retained runner 停止 → Launcher cleanup。等待期間不開 log；原 mutex 正常釋放後，
保留 400ms grace 給舊版 `Add-Content` 完成，再讀本次新增的 `Launcher stopped.` 一次。
兩項證據齊全才呼叫原 `start-omi-launcher-hidden.vbs` 一次。它不讀 source digest，
不熱更新舊 Launcher、不改 `RestartBackend` pin、不走 `RestartServices`，也不接管或終止程序。
短命 update mutex 只防止同時執行兩個 helper；不新增服務、Controller、token 或 health gate。

`EXIT_REQUESTED` 只是停止請求。exit 0／`OLD_OWNER_STOPPED_START_REQUESTED` 僅表示舊 owner
正常交接，原 VBS 已呼叫一次；換版採用與 Backend／Frontend readiness 均標 `UNVERIFIED`。
helper 不讀取新版啟動中的 log，不把啟動請求宣稱為整個版本已通過 Runtime／Live 驗收。
沒有 owner 回 exit 3、不啟動；停止被拒、abandoned mutex、缺新 terminal log、權限／IO 錯誤
或停止 deadline 到期回 exit 2、不重試。若 terminal log 未及在 grace 內完成，保守回
`UPDATE_STOP_UNCONFIRMED`，不啟動；不靠重複讀取干擾最後 logger。VBS 呼叫失敗也不重試；
逾時不撤銷已送出的 Exit，舊 owner 仍可能稍後完成停止。

使用相同 Windows 使用者／session，換版期間不要同時開 Startup shortcut、手動啟動或繼續改
lifecycle source。舊版 Exit 若無法安全收尾，helper 無法補救；舊 owner 原有的失敗訊息框也
不會由 helper 關閉。這是有正常 Exit 能力的 owner 的換版／恢復入口，並非 crash 後強制清理。
日常 Backend-only 重啟仍使用 `omi_restart_backend`／`RestartBackend`，不動 Frontend。

## 2026-10-20 重啟名稱與 Frontend 啟動競態修復（Source，Runtime 未採用）

日常「重啟 OMI」明確指 **Backend-only**：使用既有 `omi_restart_backend`、tray
`Restart Backend`，或既有 Launcher 新增的 secondary action `RestartBackend`。
這三個入口共用 `Invoke-OwnedBackendRestart`；不停止、探測或重啟 Frontend。
OMI_search adapter 名稱、Backend runtime-control API schema 與原 source pin 保持不變。

明確「重啟兩者」才使用 tray **Restart Backend + Frontend** 或原 CLI action
`RestartServices`。舊 `RestartServices` 名稱保持相容，仍是完整 Backend→Frontend；
不是 Backend-only alias。MCP runtime 不屬於這兩種操作的 scope。

以下是已採用新 Launcher 後的操作命令，本次 source 工作沒有執行：

```powershell
# 日常重啟 OMI：Backend-only
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File '.\scripts\omi-launcher.ps1' -LauncherAction RestartBackend
# 明確重啟 Backend + Frontend：保留既有完整操作
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File '.\scripts\omi-launcher.ps1' -LauncherAction RestartServices
```

`RestartBackend` 只向原 mutex owner 的 `OpenMarketIntelligenceLauncherRestartBackend`
auto-reset event 發送一次，不另建 owner、不提示額外確認。沒有 owner 回 exit 3；舊 owner
沒有該 event 或 signal 失敗回 exit 2，不能改送 `RestartServices`。exit 0 只證明 signal
送達，完成仍須原 owner 的 terminal restart evidence。事件與 tray click 使用既有 guard、
timer pause、finally event reset 合併操作期間重複事件；不重送、不重播。

使用者提供的 10/20 時序：09:35:25 新 Frontend runner 出生，09:35:26 立即的 stop-proof
觀察回 `FRONTEND_STOP_UNCONFIRMED`；Next 約 2.8 秒後 Ready，09:35:42 API/UI 健康。
本次修復 source 中「啟動後立即全面 stop preflight」的競態，不推定歷史 CIM 權限拒絕就是
當次根因。10/19 完整重啟成功的歷史驗收仍有效，但不代表此次修改已採用至 Runtime。

新啟動先驗 retained handle／PID／creation／Launcher identity，再等待 HTTP healthy；
只有 HTTP 與 listener 均可用時，才做一次 listener→root ancestry snapshot。HTTP 尚未
Ready 不查 CIM；輪詢間隔 500ms，snapshot 暫不可用只在原 30 秒 deadline 內有界重觀察。
已知 foreign listener、PID reuse／creation mismatch 或 generation 改變立即拒絕；deadline
後仍 unknown 回 `FRONTEND_START_READINESS_UNCONFIRMED`。不增加 spawn／kill retry。
最後保留正常 health 與已驗證 ownership；HTTP 200 本身不授予 ownership。

本輪驗證限 AST／mock Windows、Backend restart/source-pin contract 與 architecture checker；
不執行 native tree test、不連正式 endpoint、不讀寫 DB、不停止或重啟 OMI。
**Source PASS 與 Runtime Adopted 分開；本輪 Runtime／Live／Product 仍為 UNVERIFIED。**
操作換版與驗收步驟見 [操作者 runbook](../exec-plans/active/backend-manual-start-20261016/Adoption.md)。

## 2026-10-19 Cold admission／Run dispatch 修復（Source／offline，未採用至 Runtime）

`Start-Backend` 在 `OwnedBackendStartAttempted` 之前呼叫
`Assert-OmiProductionBackendStartPreflight`，只觀察 Controller、owner／模式、lifecycle source、
固定 port listener 與 bindability，不建立 session／store／Runner／child，也不 pump UI。
此階段拒絕保留 `SOURCE_ADOPTION_NOT_ATTESTED`、`Controller unavailable`、
`FIXED_PORT_NOT_FREE`／`FIXED_PORT_NOT_BINDABLE` 原因，Start Services 的提示也保留原因。
尚未消耗 attempt 時，修正外部條件後可由下一次明確 Start 重新檢查；不提供自動重播。
進入 factory 前仍先設不可逆 latch，factory 再做相同 preflight。包含第二次檢查的 race、
constructor 例外、null 回傳或已啟動 child 的 unknown，都不能因 session 缺失而清 latch。
本次未修改 ProductionSession／Runner 的生產握手、安全停止或 writer drain 契約。

無 session 的 Stop／Exit 只有非常窄的 cold no-op：必須明確為 no-attempt、non-reload／
non-packaged、持有原 mutex 且 handle 有效、沒有 Backend runner／retired session／manual
start history、沒有 Frontend runner history 或 unknown stop。再確認 Frontend port 無 listener
且可 bind、process snapshot 無本 Launcher 的直接 child（含未追蹤 Runner），以及 Backend
selected port 無 listener 且可 bind。觀察失敗或任何證據缺失即拒絕。先前純空狀態的 no-op
Frontend stop 可重查，因此 Stop Services 後仍可明確 Exit；不允許從有 runner 的歷史推定為空。
成功記錄 `OWNED_COLD_START_NOT_ATTEMPTED`，不補造 `LIFESPAN_AND_EXACT_EXIT` receipt。
Stop 的 sticky fence 仍保留；任何 factory-attempt／unknown 都不能走此例外。

Run／Start Services 的 degraded 判斷在原 request guard 內完成；先在原 finally 合併 Run
事件，再同步交給 `Restart-Services` 取得既有 lifecycle guard。交接中沒有 DoEvents、wait
或 callback；Backend 與 Frontend 的 UI pump、finally event reset 仍受 guard 保護。
直接 tray Restart Services 使用同一路徑。full-service UUID、Backend→Frontend 次序、
sticky SafeStop、generation／source pin、後段 `partial` 與 unknown 不重播均不改。
無 owner 的 Backend start 拒絕；legacy／reload cold start 也只接受空且可 bind 的固定 port，
不再由 `Start-Services` 落入歷史 port-owner force cleanup／endpoint adoption／換 port。
沒有 retained Owned channel 的 legacy Restart／Stop 仍拒絕。

控制 scope 必須分開：遠端 `RestartBackend` 仍只處理 Backend；本機 `Restart Services`
才協調 Backend 與 Frontend，MCP runtime 本身不在兩者的重啟範圍。
第一次換版依 [Cold Adoption Gates](../exec-plans/active/backend-manual-start-20261016/Adoption.md)
先結束舊 owner，再由原入口載入唯一新 Launcher；已有 Startup shortcut 時不可重複開啟。
離線 AST／mock OS 驗證只證明控制路徑，Controller private store、正式 DB readiness、真實
npm／Next subtree 與同 UUID Live receipt 仍待操作者驗收，不能宣稱 runtime adopted。

## 2026-10-19 Launcher Frontend Stop／Full-Service Restart（Source／offline）

Frontend 的 bounded termination 由原 Launcher 擁有（2026-10-20 簡化 source）。
`Start-LoggedService` 在出生時保留同一 Process object、native handle、PID、creation 與
Launcher PID／creation。停止前驗原 object reference、handle、PID／creation、Launcher
identity 與有效 mutex；不從 port、HTTP 或 caller-supplied PID 接管 ownership。
停止不做 CIM descendant inventory、不為 descendants 重新開 handles，也不做 pre/post
多次 tree snapshots。唯一 target 是原 retained runner：`taskkill /PID <owned-runner> /T /F`。
使用者已接受 force 結束該 Frontend 的 npm／cmd／Node 樹；Backend 永不走此路徑，仍須
原 Job Quiescence、Writer Drain、receipt 與 Exact Exit。

taskkill helper 最多等 5 秒；之後最多 5 秒確認 retained runner exit、selected Frontend port
（預設 3000）無 listener 且可 bind。這只證明 runner exit／port release，不宣稱觀察到
所有 detached descendants 的 exact exit。runner 未退出、listener 仍在、bind failure 或
證據不足維持 `FRONTEND_STOP_UNCONFIRMED`／unknown，保留 evidence，封鎖 recovery，
不重送 kill、不清 port。沒有 birth proof 或原 identity 不符不得終止。

`Stop Services`／`Exit Launcher` 先做 Frontend 唯讀 preflight，再走原 Backend
`Stop-BackendService` 的 Writer Drain／receipt／Exact Exit，成功後才實際停止 Frontend。
後段失敗保留已完成的 Backend stop evidence 與 Launcher；不宣稱 atomic stop 或整組成功。
`Safe Stop Backend` 維持 Frontend 不動。所有 Frontend stop 呼叫（含 legacy recovery）共用
此 ownership 路徑，`-RequireSafeStop` 不再切換到另一條較弱的 port cleanup 路徑。

Owned 模式本機 `Restart Services` 使用新 UUID 呼叫原 `Invoke-OwnedBackendRestart`，
不使用 remote intent。原 ApplicationRelease pin、`StopForRestartAsync`、StopNotSent／
ABORT_PREPARE／Rearm、失敗不重送及新 Backend readiness proof 均保留。
Backend 未通過時 Frontend 保持原樣。通過後以原 operation guard 和暫停中的 timers 執行
`Restart-Frontend` → confirmed stop → `Start-Frontend -AfterConfirmedStop` → owned listener
與 `/omi-ui-health`，最後再觀察兩個服務的 readiness。
這個一次性 start 僅接受同 port 的 confirmed stop，拒絕既有健康 endpoint adoption、換 port
及重播；不清除 `SafeStopAttempted` 或 `RestartReadyBackendSession`，不改 remote Backend 契約。
`LastFullServiceRestart` 與 log 留下 UUID、stage、Backend／Frontend 狀態、reason；只有兩者
ready 才是 `succeeded/BOTH_READY`，後段失敗是 `partial`，不自動 rollback／retry。

Frontend 自動 health recovery 與其正常 `Start-Frontend` 共用唯讀 admission guard。
`SafeStopAttempted` 保持 sticky；設置後僅當 `Test-OmiRemoteRestartGeneration` 認證
目前 Backend 是同一 retained live verified successor 才允許恢復。Backend start error、
Frontend stop unknown、未成功的 full restart、停止／重啟中的操作或 Launcher shutdown
仍拒絕；recovery 入口也拒絕進行中的 service start／Backend recovery。
Frontend stop 後的正常 start 再驗一次，不把先前 admission 當成持續許可。
此例外不解除 `Invoke-ServiceStartRequest`、Backend admission 或 legacy cleanup 的 fence。

驗證表面是 Launcher AST source tests、synthetic ownership／port／failure fixtures，以及
臨時目錄、隨機 port 的真實 legacy runner retry／整棵停止測試；不接觸正式 Backend、DB 或 provider。
**Source／offline 驗證不等於 Live adoption。** 使用者提供的 10/19 10:09 正式觀察是
`SOURCE_ADOPTION_NOT_ATTESTED`（disk/import hash mismatch），本次未重新探測或操作該 runtime。
舊 Launcher 不會熱載入此能力；不能用更新後的檔案冒充舊 session 有 birth proof，或另開 Launcher
接管現役 PID。正式換版仍需另行安排合法 cold adoption 與 tray Stop／Restart／Exit 驗收。
10/19 09:12 Backend Restart receipt ACL 問題保持獨立，未推定由 Frontend 引起，也未改 ACL。

## 2026-10-19 RestartBackend 的舊映像與新 Source（Source／offline）

`ProductionSession.VerifyReadiness` 驗證 retained PID／creation、出生時 instance／endpoint／release
與同程序的 serving status；磁碟上的新版 ApplicationRelease 不再否定舊程序的身分。
Restart 在舊 readiness 前固定 successor ApplicationRelease，經 Session 送出前、Runner PREPARE 前、
writer drain 後且 STOP 前重查。新 START 必須接受同一 pin，原 boot snapshot／loaded release、
readyz 前後 source 檢查與最後 Launcher adoption 檢查仍保留。這是分階段 hash 檢查，不是檔案系統鎖。

未送 PREPARE 的 source drift 產生 `blocked/RESTART_SOURCE_CHANGED`、`BEFORE_PREPARE`，
不設 terminal；已接受 UUID 仍不能重播。Runner 已 PREPARE 但尚未送 STOP 時，只能透過原 inherited
channel 發送同 identity／UUID／deadline 的 `ABORT_PREPARE`；Backend 呼叫既有
`RuntimeCoordinator.abort_owned_restart` 並觀察 `owned_restart_rearmed`。
只有同一存活 child 的 `PREFLIGHT_REARMED/rearmed=true` ack 才解除該次 terminal。
錯誤、逾時或缺 proof 保持 unknown；不靠時間經過或缺少 guard 推定 rearm。
原 PREPARE expiry 仍獨立撤銷可逆 admission，不授予 STOP。

Launcher 只在綁定原 generation 的 StopNotSent／Rearmed 證據下恢復操作前的 SafeStop fence 與
RestartReady session；真正送達未知仍 sticky。Controller 保留 before identity、固定 refusal reason、
durable receipt 與原 UUID。`target_release_id` 只存在 Launcher→Runner pin，傳往 Backend 前移除，
不取代舊 release、child identity 或 public request schema。

新 Backend 的出生 READY 宣告 `restart_abort_protocol=1`。缺此能力的舊 generation 在 PREPARE 前
回 `RESTART_ABORT_PROTOCOL_UNAVAILABLE`，不冒險進入無法確認撤銷的排空。
這個 private seam 由 Owned transport 擁有；待所有可採用 generation 都具該協議並完成 Runtime
驗收後才可考慮移除 compatibility refusal，不能用外部欄位偽造能力。

現役 Launcher 已載入的 C#／PowerShell 不會隨檔案修改而更新。
`Get-OmiLifecycleSourceId`、`Assert-OmiManualBackendStartOwner` 與 factory 的 source adoption gate
保留；單次 Backend Restart 無法更新 Launcher，必須先另行規劃合法的 Launcher／Backend cold adoption。
若舊 Launcher 的正常退出流程仍受 Frontend stop proof 或其他 gate 阻擋，應回報 blocker，不能強殺、
注入、接管舊 PID 或改 ACL。本次未做正式服務 IO、重啟或 durable store 寫入驗收。

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

以下為當時的歷史政策；2026-10-22 的 Source 修正見本文「歷史 durable outcome 與執行 quiescence」。歷史 BLOCKED receipt 不追溯改寫。

當時 Job Service 的 `pause_jobs_if_idle` Gate 檢查
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

沒有 Owned channel 的 legacy Backend 回 `BACKEND_SAFE_STOP_OWNED_CHANNEL_REQUIRED`；
只有上節定義的可證 no-attempt cold owner 可走無 receipt 的 no-op。
`Stop-LegacyBackendService`、taskkill、port cleanup 與舊 recovery 保留在 source，正式 Safe Stop
不呼叫它們，也不 bootstrap／接管現役程序。`Restart Services` 的 Owned 接線現已由本頁
2026-10-19 Frontend／Full-Service 增量取代舊 `OWNED_RESTART_NOT_AVAILABLE_FROM_TRAY` refusal。

Frontend 的既有 runner 仍沒有合作式停機通道；最新 source 以 retained ownership 驗證後的
bounded termination 取代 live Frontend 必然回 `FRONTEND_SAFE_STOP_UNAVAILABLE` 的舊 gate。
Backend STOP 前後仍重驗 Frontend；不確定時回 `FRONTEND_STOP_UNCONFIRMED`，保留 Launcher
及 Backend 已有證據。BackendOnly 不執行 Frontend 檢查。**整組 Exit 尚未 Live 驗收**。

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
在原 guard 內合併；依原 enabled state 恢復 timers。`Restart Services` 最新接線見本頁
2026-10-19 Frontend／Full-Service 增量。

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
`restart_preflight()` 與 POST 的 `backend_preflight` 嚴格保留上述五欄，
符合既有 C# parser 的 exact-field 與 1024 字元上限，不含擴充診斷。
以下診斷獨立放在 GET-only `serving_backend.writer_diagnostics`，
由 `restart_diagnostics()` 提供；POST 不讀取此方法。
`unknown_writer_count_basis=unattested_scope_categories` 與
`unknown_writer_categories` 明示此 legacy count 是未證明涵蓋的類別數，
不是實測程序／connection 數；保留原 count 與 all_writers_drained 的保守語意。
`owned_restart_capability` 另提供既有 owned bootstrap／admission capability 的記憶體觀察，
不代表 PREPARE 已執行。`owner_observations` 重用 Job owner 的 bounded quiescence
觀察，並列出 HTTP admission、Session／Engine fence 與 prepare／commit flags。
這些欄位是 process-local、非原子、非授權的診斷；空 Job／零 connection／retained lease
均不能取代 request-bound PREPARE、STOP、exact exit 與 terminal receipt。

`owner_observations.detached_workers.retained_worker_count` 是尚未取得完成證明的
worker reservation 數，包含 Thread.start 結果不明，不能直接解讀為活躍 thread 數。
`OwnedWorkThread` 在 native start 前保留 reservation，只有 `run()` 的 finally 能釋放；
start 拋例外或 `is_alive()==False` 都不是未啟動／已完成的證明。已完成的 worker 不會
因 start 晚到的例外被重新保留或重複釋放。MIS 同 venue IO slot 遵守相同限制：
只有明確發生於 native start 前的 admission 拒絕可立即清除 slot；其他 start 例外
保留原 Future，直到原 worker 實際完成。沒有完成證據時 PREPARE 保守停在
DETACHED_WORKER_QUIESCENCE，回復可逆 admission，不取得 native SQLite lease，
也不進入 terminal drain。此保守狀態可能需要人工查明，不能用清計數器恢復重啟資格。

`restart.blockers`／`available` 由 Launcher 當下回覆決定。`available=true` 只表示正式
控制入口可以接收經驗證的 intent，不代表 writers 已排空或已授權停止。
`serving_backend.readiness=UNATTESTED` 是這個純記憶體 GET 的觀察範圍，
不能當成 readyz 失敗，也不能改成 ready 以繞過獨立 readiness／source gate。

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
Frontend 不在遠端／Backend-only `RestartBackend` 控制範圍；本機 full-service restart
由 Launcher 協調，見本頁最新章節。MCP runtime 不由這些操作重啟。Legacy menu 若企圖走
force stop 會被拒絕，legacy cold start 也不走 port-owner cleanup。

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
沿 accepted 的同一 monotonic deadline 重查 retained process／Owner、
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

## JobService 協作式 quiescence（Source contract）

正式 Stop／Restart request 本身即為停止授權；本契約不新增 modal、確認視窗或二次詢問。
`RuntimeCoordinator` 仍是既有 orchestration owner：PREPARE 先關 HTTP／Scheduler admission，
透過 `JobService.request_job_pause()` 關閉所有 managed lane 的新任務 admission，對已登記
Future 發出同一套 cooperative stop signal。這是共同 admission／pause／ack 契約，
**不代表所有 worker 都已支援 prompt stop**。

`jobs_paused(lease)` 必須等到真正 Future、done callback、已接納的 enqueue 都退出。
歷史 unresolved durable outcome 另保留為 reconciliation 診斷，不能宣稱工作已完成。
queued wrapper 不呼叫 task／provider，先 commit `JobRun.status=paused`
與 versioned `result_json.job_service_resume_v1` obligation，再關閉 Session；running worker
只能在其 transaction owner 已完成 commit／rollback 的安全點退出。不能以 progress、token、
Future.cancel、Python thread kill 或程序強制結束代替完成證據。uncaught task exception、
pause commit failure 或無法編碼的 continuation 保留原 JobRun 與 unknown 診斷，不授權自動重放；
未證實完成的 Session close、transaction、physical writer 或 provider ownership 仍阻擋。

PREPARE 在 managed jobs 退出後才關閉 Session scope admission，接著仍必須通過 publisher、
physical SQLite、Engine unknown check 與 native writer lease。collectors／HTTP／Frontend
不是 JobService 所有；crypto／Fugle 的 admission 與 final flush 仍由原 owner 執行。
Graceful ExactExit、UUID、source pin、STOP delivery 與不可逆 commit gate 不變。內層 deadline
可回 blocked／rearm；明確 lifecycle operation 的外層 180 秒到期仍執行 exact-owner cutoff，
不重送 STOP，也不宣稱工作完成。

### 已驗證的安全點與未支援範圍

`run_taiwan_broker_branch_market_refresh_job` 在當前 stock transaction 完成及
progress transaction 結束後檢查 signal，保存精確
current／total，再由 JobService 保存 `restart_paused` partial。重啟後根據 persisted
stock／trade_date 與同來源、同 contract、同日期的 success／partial／empty quality 跳過
已收集項目；provider failure、invalid、date mismatch 不當作完成。empty acquisition
仍不等於完整 market coverage；缺資料保持 partial。2330 release probe 的對象與 provider
參數沿用原契約；去重是逐股 acquisition 去重，並不省略原有 release probe。

Period owner 的新增接點由 `jobs/resumption.py::PERIOD_TASK_OWNERS` 明列。TWSE／TPEx price
按月、revenue 按月、financial 按季、shareholding 按週、market daily／margin 按 source/date、
Radar snapshot 按完整 group/mode，在原 domain owner commit／rollback 完成後通知。
`BackfillProgress` 只保存記憶體 cursor，不擁有 Session 或業務交易；descriptor 綁定 task、
typed args、job id，並比對完整 canonical items 的內容與順序、identity 與 ledger totals。
Price parsed 與 inserted 分別記錄，不從部分已有日價推定整月完成。Context 漂移保留 paused
obligation 並 fail closed。Radar outcome 則使用原 pending path ledger，在原 evaluation owner
的 commit=True commit／rollback 後通知；commit=False 不提供安全點。

可執行盤點入口是 `scripts/job-support-inventory.py`，coverage test 對照 production submissions
與 retry routing；本文件不維護另一份完整 task 表。來源掃描不能證明 hard wall-clock bound，
Radar 單一 scope、provider request 與 DB commit 仍須等待原 owner 返回；drain deadline 到期
回報 graceful blocked，不能中斷持有交易的 Python 執行緒；180 秒外層可終止 exact owned
OS process，保留未確認對帳。

EOD 的 US symbol、US priority OHLC 的 symbol scope、Taiwan intraday bootstrap 的 child
admission，由 `jobs/resumption.py::OWNER_TASKS` 與原 owner 的明確接點授權。沿用 JobRun
JSON 保存原 universe、release/date/contract、精確 work order、逐項結果與累計 quota/runtime；
`OwnerWork` 是純資料 ledger，沒有 executor、provider selector 或 DB ownership。
Job composition adapter 在 IO 前持久化保守 calls reservation，只有原 owner 完成後才結算。
US EOD 的結果 ledger 與 coverage cursor 在 `_update_repair_state` 的同一 commit 寫入；
優先序與每第五次 background rotation 在原 Job 凍結，續跑不依最後 cursor 推測完成集合。
Provider exception 保留 reserved quota，原 retry/backoff 不重設。US priority 的 Shared
read/ensure 必須返回，chart Session 必須 close，之後才保存 counters 與發布 checkpoint；
unknown consumption 保留 reservation、實際 calls=null，terminal partial 不重放該 symbol。
未知 commit/rollback/Session close 不能發布 pause。Future 的 escaping outcome 保留 reconciliation
診斷；是否可停止仍取決於真正 execution exit 與後續完整 writer gates，不等同 durable completion。

Bootstrap parent 保存原 target plan、admitted child ids 與剩餘 symbols；parent admission
progress 不代表 children coverage。每個 child 的 deadline、CAS claim、quota、retry 與
terminal postcondition 仍由 `taiwan_intraday_demand` 擁有。Admission 與 parent checkpoint
之間若 persistence outcome 不明，保留 inflight ledger 並阻擋自動重放。

其餘已開始的 worker，包括 TW EOD venue bulk、index repair、其他未接線 bootstrap、
Dispatch 與 intraday-demand，尚無本契約驗證的中途 safe point；執行中顯示
`UNCOOPERATIVE/UNKNOWN`，只能等實際自然完成。不能保證 prompt stop，deadline 到期必須
拒絕成功。現有 AuditSlice 的 scheduler yield 不是 JobService checkpoint 的替代證據。

queued continuation 的 executable allowlist 與 typed argument codec 由 `jobs/resumption.py`
擁有，文件不複製另一份完整 task inventory。僅 source-owned top-level task、可驗證的
argument shape／signature／lane／checkpoint 可重放；不用 pickle、不從 request_json
決定 import、不允許任意 module。Dispatch／intraday-demand 有自己的 durable state machine，
明確禁止通用 queue replay。Intraday demand 的 unstarted callable 由原 owner 以 CAS 將
已 claim 的 running attempt 交回 queued，保留原 request、deadline、已耗 quota 與 backoff，
並保存 original-owner handoff marker。原 `dispatch_due_materializations` 接回同一 episode；
GET 不派送，沒有重新 enqueue 或重設 quota。已開始的 acquisition 使用原最多 40 秒的
cooperative deadline／late callback rejection，但不保證 HTTP／Thread 在 40 秒內退出；
仍須等真正 callable、Session、Future 與 done callback 完成。Dispatch send／SMTP 的
irreversible state machine 沒有新 replay authority；unsupported callable／closure 不執行，
保留 unknown durable 記錄。真正 execution 與 writer 都退出後可停止，下一次正式 startup
依原 interrupted cleanup 明確標註未完成，不偽造 paused／success 或通用重送。

### Durable recovery 與 rearm

沒有 schema 變更：沿用 JobRun 既有字串 status 與 JSON 欄位。paused 納入共同 dedupe，
不被 `mark_interrupted_jobs()` 改成意外 error；真正 crash 留下的 queued／running 仍沿用
既有 interrupted error 語意；唯一 queued 例外是經原 intraday-demand owner 驗證的 unstarted
handoff，保留給原 dispatcher。不存在 marker 或 quota 不明時不推測可恢復。
不對未證實完成邊界做自動 replay。status=paused 本身不授權
重放，必須通過完整 versioned descriptor 驗證；API projection 不輸出 private task descriptor。

啟動時 background leader 先只讀取並驗證 obligation，關閉該 read Session；所有必要
scheduler／collector components 啟動、runtime 設為 started 後，才從同一 JobService 提交
continuation。啟動中途失敗時不得啟動 recovery worker，obligation 保持原 bytes。若正式
提交後失敗，沿用實際 Runtime drain／unknown 結果，不能假稱安全退出。GET／status／read
不啟動 recovery，也不寫 DB。

無 STOP 的 rearm 先恢復其他被關閉 owner，再重新開啟 Job admission。已完成 pause 的工作
可續跑；仍在寫 pause commit 的 worker 必須先完成並退出，由 done callback 才接續。
reservation 在 `_executor_lock` 內，codec validation／submit dispatch 在鎖外，DB IO 不進入
executor fence。Future 完成與 callback 續跑本身均納入 drain 計數，避免零 Future 空窗假成功。

隔離測試使用實際 JobService、ThreadPoolExecutor、temporary SQLite 與 mocked provider，
包含第二個 disposable Python process 的 durable recovery；這些都是 Source／offline 證據。
本輪未操作正式 Backend／Frontend、DB、provider 或 Launcher；Live adoption 仍為 UNVERIFIED。

### 2026-10-22 歷史 durable outcome 與執行 quiescence（Source contract）

使用者明確核准解除「只有歷史不確定計數也永久禁止 Safe Stop／Exit／換版」的政策。
`_enqueue_failures` 記錄 INSERT／commit／continuation 的結果不確定，並非 executing writer 數；
數值、原 JobRun、result/request JSON 與既有 error 診斷均保留，不清零。JobService 的 drained
只代表 admission 已關、實際 Future（含 callback）與 active enqueue（含 rollback）均退出。
`execution_quiescent` 與 `reconciliation_required` 是不同 memory-only 診斷；GET 不加 DB query。

RuntimeCoordinator 在 Job 執行靜止後記錄 `OMI_RESTART_JOB_RECONCILIATION_PENDING`，繼續原
Session、publisher、physical SQLite、Engine unknown 與 native `BEGIN IMMEDIATE` 排他流程。
HTTP、scheduler、detached provider worker、collector final flush 亦須通過原 gate。任何未完成
或無法證明已退出的 writer／transport 仍拒絕；歷史計數非零不會授權 cancel、kill、清 owner、
忽略 close failure 或跳過 SQLite exclusion。`all_writers_drained` 不宣稱所有 Job 業務成功。

Durable obligation 的處置仍由既有 owner 負責：下一次正式 background-leader startup 的
`mark_interrupted_jobs` 將一般 queued/running 原記錄標註 interrupted error，保留 ID、request、
result、created/started 時鐘，填入 ended/updated；沒有新 job、沒有 provider replay。cleanup
commit 失敗向外傳播並停止 startup；不宣稱已完成 reconciliation。合法 paused descriptor
由既有 validated resume 接回；intraday-demand handoff 保留原 CAS、deadline、quota、backoff。
這不是新的 recovery manager，也不增加 startup retry、status repair 或全市場掃描。

離線驗收使用 temporary SQLite、真 Future／rollback／Session、第二個 disposable Python
process，分別驗證失敗後仍存 queued/running、下一次啟動 interrupted 且冪等、合法 paused／
original-owner resume、cleanup commit 失敗保留、未知 Session close／Provider start 不可放行。
子程序受 offline guard 與外層 timeout 限制；不宣稱正式大 DB 的 startup wall-clock 上界。
既有 architecture no-forced-cancellation 與 transport-no-owner constraints／debt 邊界不變。
2026-10-22 12:51 的 JOB_QUIESCENCE/PREFLIGHT_REARMED 是當時載入政策下正確的安全拒絕；
此 Source 修正不能倒寫該 receipt，也不代表現役程序已採用或現在已獲重啟許可。
