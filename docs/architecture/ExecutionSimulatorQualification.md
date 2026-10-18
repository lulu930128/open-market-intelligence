# Execution 模擬環境資格驗證邊界

`execution/` 繼續擁有 pure Draft admission 與 reducer。
`execution_simulation/SimulationApplication` 繼續擁有 factory-only synthetic SQLite
transaction、confirmation consumption、reservation、outbox 與 replay。
另有明確 opt-in retained LOCAL_MOCK lifecycle 與無 route 的 headless manual command seam；
來源、限制與未來 MCP App owner 見 [Execution backend](ExecutionBackendMilestone.md)。
Retained synthetic ledger 不解除 durable REAL_SIM qualification gate。
`execution_kgi_simulator/` 只擁有隔離 qualification 工具與本地 SDK-shaped fixture，
不新增 provider、account owner、正式下單服務或另一套 canonical model。正式 caller 不得 import。

新增 `rehearsal_*` commands 屬於 `SimulationApplication`，重用既有 schema 與 full replay。
claim 必須在 fixture 呼叫前 commit；result 與 correlated observation 分別以 command 保存。
已 claim 的 command 永不重送；明確 fencing 撤銷舊 generation，未決 claim 保持 UNKNOWN。
constructor、status、audit、replay 均不自動 dispatch、reconcile、排程或 recovery。
fake acceptance/cancel 使用既有 reducer；schema v1 繼續保留 reservation。

分離 call boundary 的 executable evidence 僅為 **LOCAL MOCK**。
wire 只接受確切的本地 `FakeSDK`／`FakeOrder` 類別；login 呼叫 literal `simulation=True`，
但 fixture 呼叫不能證明已安裝 SDK 的實際環境。
canonical contract 仍標記 SYNTHETIC、test_only、broker_connected=False；
真實 observation 不得塞入此 envelope 或重新標記成 synthetic。

PowerShell worker 有 Preflight、ContractTest、Probe、Send 模式，無網路、真 SDK import、
secret value ingress 或 production switch。Probe/Send 固定 fail closed；
補環境變數或等待平日不會解鎖。真實 simulator 實作需要 reviewed environment/account ingress、
native endpoint/output confinement、有效 session、真實 account facts、unit/correlation 證明及
durable simulator ledger lifecycle。這些是 source/evidence gates，不是使用者 bool flags。

SDK inspection 僅將 allowlist source 與 distribution metadata 當資料讀取，不執行 SDK。
不讀 broker log、CA 內容、SDK encrypted config，也不證明 native binary 的行為。

機械防護由 `execution_kgi_simulator/constraints.toml`、zero-debt manifest 與 injected negative tests
執行；既有 M1/M2A/M2B/M3/manual manifests 繼續有效。
本 package 沒有 frontend、HTTP route、MCP/AI/Kuro tool、scheduler、正式 migration、quote session 或 PAOS 整合。

## REAL_SIM source qualification seam

`real_sim.qualify` 與獨立 worker 的 `RealSimPreflight` / `RealSimProbe` 提供 source-only
qualification；`origin=SOURCE_INSPECTION`、`runtime_origin=NOT_CONNECTED`、target=REAL_SIM。
這不是 M1 Origin 的新值，不把真實回報標記 SYNTHETIC。沒有 SDK/session/proof/secret/callback
注入參數；qualification 不 dispatch login/send/cancel；所有 runtime gates 維持 BLOCKED。
M1/M2A public contract、transaction、reducer 與現有 LOCAL_MOCK path 不變。

固定 SDK source AST inspection 回傳 hash 與 concern 行號，不讀 CA、log 或 encrypted config。
Native Connect 由動態 host 決定、identity-derived log、stdout 與 data/quote 初始化都是
待審查表面，不構成端點、ABI 或安全隔離證明。canonical credential 存在也不證明 SIM entitlement。
Launcher 不讀取帳密或其 env presence，child environment 清空，不傳 credential 值；
qualification 不建立 temp directory，worker audit hook 拒絕寫檔/native/network/process。
這個 hook 是 source 防線，不能冒充可安全執行 native SDK 的 sandbox。

未來真實 read-only connector 也須先證明 native endpoint/output/filesystem confinement 與
session ownership，且在外部處理前由既有 transaction owner 持久化 probe intent。
目前未實作安全 credential ingress、intent 或 real-origin migration，故不執行 native probe。
單筆 send 另須明確使用者摘要、短效確認、shares/張轉換與各 readback surface、broker ID、
callback finality 及不重送 UNKNOWN 的 durable lifecycle；任何 caller bool/JSON 不算證據。

## 獨立 interpreter readiness

`scripts/test-kgi-native-runtime.ps1` 是唯讀、離線的 `INTERPRETER_BASE_ONLY` 工具，
不屬於 REAL_SIM connector。它固定檢查 `.venv-kgi`，不接受 caller proof、帳密、
SDK object 或替代 executable。PE/CPython 3.12 x64、base identity、`-I -S -B` flags
與 stdlib path 匹配後才可回 PASS；patch drift 可見，但不構成 native ABI acceptance。
公開 payload 只含安全摘要，原始 interpreter/base/sys.path 不流出。
存取受限與查無檔案分開回報；未知不能宣稱已修復或已卸載。
此 profile 不寫入設定、不 import SDK、不 login、沒有 network/credential ingress，
不影響 source qualification；JSON 報告不能作為可啟用 REAL_SIM 的 attestation。
M1/M2A owner、reducer、transaction、ledger 與所有 REAL_SIM gates 均不變。

## Login-only typed preparation boundary

`login_probe.CredentialOwnerReference` 固定指向既有 `app.config.Settings` 的
`kgi_superpy_person_id/password`；沒有新增永久 `KGI_SIM_*` source，沒有讀取 `.env`。
Legacy presence 欄位只供相容診斷，不參與資格判定；SIM entitlement、官方 native endpoints、
egress/redirect/CA/log/filesystem confinement 仍是獨立 gate。source SDK status 使用 INSPECTED。

同模組提供 ephemeral credentials codec 與 test-only login/readback/logout lifecycle。
`exercise_fixture` 的 injected `LoginOnlyPort` 不由正式 worker dispatch；機械 constraint
禁止正式 qualification 呼叫 fixture、private frame ingress 或 Settings reader。
唯一實作 port 位於 tests，精確接受本地 FakeSDK；不持有正式 quote bridge `_API`。
此 lifecycle 不是 execution reducer／transaction owner；不寫 schema、DB、outbox 或 account。

Typed result 只投影固定 enum/reason、generation、phase 與 opaque receipt identity；
LOCAL_MOCK origin 與 NOT_CONNECTED 永遠不可由 SDK response 覆寫。只對同 generation、SIM、
已接受且 identity 一致的 login/readback 產生 fixture receipt，logout 未確認即移除 receipt。
不註冊 callback、不輸出任何 SDK API／order 方法；其他 response 欄位丟棄。

tests 的獨立 child 用 invented inputs 驗證私密 pipe、OS FD output suppression、deadline、
cancel 與 owned PID teardown。這不認證 native DLL 子程序、Job Object containment、秘密 memory
zeroization 或 identity-derived logfile confinement。真實 credential reader/native adapter 尚未啟用；
後續必須在 Settings 讀值之前完成受信任 attestation、M2A intent/audit 與 process confinement。
不能用 caller bool/JSON、runtime readiness report 或 mock receipt 解鎖。

## 官方 SDK login-only source 與 native activation 邊界

`native/readiness.py` 固定讀取五個已檢視的 SDK source／CPython 3.12 binary，核對 local SHA256、
PE32+ AMD64 與已知 marker。這只證明本地 bytes 對齊，不證明 vendor authenticity、compiled
AutoRefresh 的行為、官方 TEST identity 或 redirect/fallback 安全性。官方 TEST destination
尚無可驗證清單；空 allowlist 不接受 caller endpoint、JSON proof、env 或 simulation flag 補足。
`RealSimPreflight`／`RealSimProbe` 回傳此 typed readiness，PowerShell 另驗證 G1/G2/G3 均 BLOCKED。

`require_verified_host()` 目前不簽發任何 authority，固定拋出封鎖例外，不讀 readiness dict
作為許可。沒有部署 Windows enforcer，所以即使 report 被改成 ALL VERIFIED 也不能登入。
未來 issuer 必須從 OS 獨立核對 suspended child／creation identity、Job kill-on-close、禁止
breakaway、token、private inherited handles、完整 image/dependency identity、期限與單次消耗，
在讀 secret 前和 child import SDK 前再次驗證。現在的 hash recheck 不能解決 TOCTOU 或替代 OS
鎖定。所有網路 family／protocol、DNS、redirect、reconnect、fallback 及 native descendants
都須 default deny，只允許經 vendor attested 的 TEST 流量；允許 IP 仍不單獨證明服務端 TEST 身分。

`native/credentials.py` 只在 gate 後延遲 import 既有 `app.config.settings`，透過 bounded
private challenge/frame 傳交兩個既有欄位。沒有新的 Settings instance、durable SIM env 或 DB。
這個 parent bridge 要在 canonical backend import context 執行；repo cwd 不等於可解析
`app.config`，當前沒有以調整 sys.path 或 env fallback 假裝驗證 parent activation。
private pipe 對象本身不是 authority，host handle ownership、期限和 teardown 未驗收前不可用。

`native/worker.py` 是獨立 SIM child entry；activation gate 在 stdin、Settings、SDK/native 前。
未來 gate 可用時，worker 永久抑制 stdout/stderr FD（包含 shutdown noise），以私密 control
pipe 回報固定欄位。現在 CLI 固定 exit 2，不連線、不讀秘密。`native/adapter.py` 的真 SDK body
固定一次 `kgi.login(..., simulation=True)`，檢查 login state，以 native `GetAccounts()` 讀回，
finally 呼叫 `_logout()`；不接受 SDK injection、不用 `_API`、不啟用 Order 或 account binding。
SDK logout 為 void，正常返回也不等於券商確認，故 body 仍保留 UNKNOWN，不產生成功 receipt。
這些方法只用 invented inputs／unit double 驗證；不把 unit double 當 native evidence。

SDK `TradeComAPI.__init__` 會 `os.chdir(libdir)` 並以 identity 呼叫 native constructor；因此
單獨更改 CWD 不足以保護 identity-named log、native debug/bin、CA 或 SDK 其他 IO。需隔離的
SDK 副本、workspace、CA policy 與 Windows filesystem boundary，目前均未部署／驗收。
PowerShell `test-kgi-native-containment.ps1` 僅讀 OS service capability 和 fixed binary hash；
不建立 AppContainer profile、WFP/firewall rule、ACL 或 process，不作為 admission proof。
Python audit hook、低 integrity 或 Job Object 單獨都不能替代完整 native containment。

M1/M2A owner、正式 Settings simulation default、quote/portfolio provider 與 primary DB 不变。
Native auth/audit 與真正 origin 若需持久化仍須既有 owner 的 reviewed contract，不能在此另建。

## Windows suspended host building block

`native/windows_host.py` 擁有隔離工具的 Windows process/handle lifecycle；G1-A 只允許固定 repo
interpreter 的無秘密命令，以 `CreateRestrictedToken(DISABLE_MAX_PRIVILEGE)`、
`CreateProcessAsUserW(CREATE_SUSPENDED)` 建立，該 probe 永不 resume。使用
`STARTUPINFOEX` Job list 原子加入 unnamed Job：kill-on-close、active-process limit 1、
不設定 breakaway flags；handle list 只包含兩個 private pipe ends。parent environment
不繼承，pipe 不寫入 credential，結束時立即關閉。任何 Windows API 失敗都停止，不改用
一般 token／一般 CreateProcess，不修改全機 OS policy。

Image 與祖先目錄 top-down 持有 deny-write/delete handles，拒絕 reparse/hardlink；image
hash 從鎖定的 handle 讀取。Child PID、creation time、image path、Job membership、token
privileges／non-elevation 與 handle flags 分別核對。當次 hash 不是 vendor 簽章，也不證明
base interpreter／DLL dependency closure；SDK 永不載入。正常路徑必須觀察 Job close 後
process signaled；失敗／中斷先嘗試 owned process teardown，再釋放所有已取得 handles。
此 building block 不提供 caller PID kill、任意 executable 或 endpoint ingress。

`native/host_policy.py` 擁有 SOURCE_ONLY deny-all construction contract，要求 per-child
kernel identity、owned dynamic session，禁止 global policy。IPv4/IPv6 connect/receive
全拒、全部 protocol/destination（含 loopback）全拒；沒有 permit、DNS、proxy、redirect
或 fallback 例外。未實作 WFP installer／AppContainer profile；這份 plan 不表示已部署
filter，suspended child 也不是 Winsock denial proof。Vendor manifest 在沒有 trust root
與正式 TEST 清單時一律拒絕。Empty sdk/logs/ca layout validator 只做 metadata/path 檢查，
不讀內容、不複製 SDK，也不形成 filesystem isolation／TOCTOU-safe workspace lease。

`native/parent.py` 是唯一獨立 G2 parent CLI，固定 `-I -S -B` 與 backend source roots，
不 import `app.config` 來探測 context；cold context 拒絕既有 app session。原 Settings
reader 仍由 `native/credentials.py` 擁有。`login-only` 先經 `require_verified_host()`，
即使未來 gate 改動，仍由 `G2_ACTIVE_PRIVATE_CHANNEL_NOT_IMPLEMENTED` 第二次停止。
短效 credential pipe 的 active handshake／deadline／issuer 尚未完成，不能拿 probe 的
pipe 或 JSON receipt 代替。這輪沒有新增另一個 env reader、Settings instance 或 DB。

Source checker 與 qualification worker 禁止 import host launcher／parent。機械 guard 限定
ctypes 只出現在 Windows host，禁止 policy installation、SDK／secret dispatch。G1-A
no-resume invariant 由 scoped AST test 保護；G1-B/C 的唯一 resume site 另受下列限制。
G1/G2/G3 保持 BLOCKED；實際 OS acceptance 和逐次 exit 記錄於 dated exec plan。

## G1-B/C synthetic AppContainer 與 SDK quarantine

`parent.py sandbox-preflight` 只做 System32 API/export capability check；experimental
`processmodel.dll` export 即使存在也不呼叫。`sandbox-probe` 僅接受 source 中已審核登錄的
既有 AppContainer profile name/SID，沒有 CLI/env/JSON override。未登錄即停止，不建立
profile，不採無 profile fallback，不修改 firewall、registry 或既有 ACL。Profile metadata、
SID 與 loopback exemption query 必須通過，並以 named mutex 限制本 owner 的 concurrent use。
Profile 的實際 provision／rollback 必須另獲具體授權，不能從 probe 目的推定授權。

同一 Windows host owner 在新 workspace 放置 SHA-pinned native canary；它只依賴經 PE
核對的 Windows DLL names，不載入 Python 或 SDK。Restricted token、zero-capability
SECURITY_CAPABILITIES、原子 Job、child-process restriction 與 exact output handle list
在 suspended creation 時一併設定。Parent 再 query child token 的 AppContainer SID、
capability count、privilege/elevation、PID/creation/image 與 Job membership，通過才可在
唯一 resume site 啟動 canary。任何 API failure 沒有較弱 fallback，保留 stage/error；timeout、
cancellation 及 normal exit 都由同一 owner teardown。Receipt 永不成為 G1/G2/G3 authority。

Canary 固定測試 IPv4/IPv6 TCP/UDP、loopback、mapped loopback、explicit local proxy
transport 與 UDP port 53；無 hostname、system proxy discovery、broker endpoint 或秘密。
只把 WSAEACCES 視為該項 denial；refused/timeout/unreachable 不通過。Filesystem 只操作
parent 新建的 invented sentinel、empty CA directory、SDK cwd 與 logs，必須同時通過內部
read/write/chdir controls，不能拿不存在檔案或 sharing violation 當 access denial。這是有限
synthetic cases 的 OS evidence，並非所有檔案／DNS API／proxy redirect 行為的完整證明。

`sandbox-stage` 可獨立執行，不啟動 child，也不註冊 profile。只從既有 REVIEWED_SHA256
五檔讀取 code/binary bytes；`CA.py` 是已 pin 的程式碼，沒有讀取 CA certificate。來源與
每層 ancestor 均持有 deny-write/delete handle，拒絕 UNC/device/ADS/reparse/hardlink/escape，
copy 後另核對 SHA。新建物件在 creation 時使用 scoped DACL，不改既有路徑 ACL；SDK file
僅 grant read，logs 為可寫獨立目錄，CA 空且不 grant child access。清理只限 recorded paths，
不使用 broad recursive deletion，清理失敗必須撤銷 OS observation 並保留 UNVERIFIED。

五檔副本是 quarantine，不是可執行 SDK installation。PE imports（包含 native DLL 的
`PushClient_Win.dll`、Python runtime、VC runtime 等）逐項輸出，缺少 pinned dependency
一律拒絕 execution，不搜尋原始 SDK 或 PATH，也不自動補 copy。SDK `chdir(libdir)` 的
write risk 以 canary cwd probe 獨立測試；不承諾 native identity log 可改寫到 logs。完整
dependency closure、loader search confinement、真實 SDK 行為與 G2/G3 都仍待後續驗收。
`SOURCE_COPY_PASS` 與 `OS_OBSERVED_SYNTHETIC_DENIAL` 是不同 evidence，兩者都不等於
完整 G1-C acceptance。正式 `DenyAllPlan` 持續為 SOURCE_ONLY。
