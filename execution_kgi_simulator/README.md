# KGI simulator qualification only

## G1-B/C host sandbox（預設停用）

一般 PowerShell 可執行 `scripts/test-kgi-g1bc.ps1`（預設 Preflight）、`-Mode Stage`、
`-Mode Probe`。全部維持 exit 2／G1/G2/G3 BLOCKED；Stage 的 `SOURCE_COPY_PASS` 只代表
五檔 source/copy SHA 核對與 cleanup，不是 OS filesystem acceptance。PE dependency audit
包含尚未 staging/pin 的 `PushClient_Win.dll` 等依賴，SDK execution／dependency closure 拒絕。

Probe 僅接受 source-enrolled、經 OS 核對的 approved preexisting AppContainer profile；
本輪沒有批准 profile，預期 `APPROVED_PREEXISTING_PROFILE_NOT_ENROLLED`、無 child。
Launcher 的唯一 resume site 只允許 pinned native canary，且先驗證 AppContainer SID、零
capabilities、restricted token、atomic Job 與 image/creation identity。原 G1-A 永不 resume。
不建立 profile、不安裝 WFP、不改既有 ACL，不透過未隔離程序執行 canary。

完整命令、rollback、profile 另次批准設計與本輪 evidence 見
[G1-B/C checkpoint](../docs/exec-plans/active/kgi-real-sim-20261012/g1bc-20261012/Handoff.md)。
Kernel network/filesystem 無 running confined child 結果時一律 UNVERIFIED。

2026-10-12 新增 source-only REAL_SIM seam：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test-kgi-official-simulator.ps1 -Mode RealSimPreflight
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test-kgi-official-simulator.ps1 -Mode RealSimProbe
.\.venv\Scripts\python.exe -B -m unittest execution_kgi_simulator.tests.test_real_sim -v
.\.venv\Scripts\python.exe -B -m unittest execution_kgi_simulator.tests.validate_real_sim_launcher -v
```

兩個 REAL_SIM 模式使用 `.venv`、`-I -S -B`，只讀 `.venv-kgi` installed source，exit 2/BLOCKED。
source worker 不證明 `.venv-kgi` interpreter 或 native ABI 可用。
launcher integration profile 必須在 ContractTest 結束後單獨執行，避免和它共用 mutex。
不載入 SDK/native、不登入或查帳。`SOURCE_INSPECTION` 不代表 broker origin，
`runtime_origin=NOT_CONNECTED`，不存在可用 bool/proof JSON 解鎖的 connector。
credential owner 固定為 `app.config.Settings` 的既有 `kgi_superpy_person_id/password`。
本輪 qualification 不讀 Settings、不查帳密 env 存在性、不傳任何 credential 值。
`dedicated_secret_presence` 是舊 pipe 的相容診斷欄位，不是必要條件或 entitlement 證明。
詳細本輪證據見 [任務紀錄](../docs/exec-plans/active/kgi-real-sim-20261012/Progress.md)。

## 離線 interpreter readiness 與基底修復

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test-kgi-native-runtime.ps1
exit $LASTEXITCODE
```

此獨立 profile 預設唯讀，只檢查 project `.venv-kgi` 的 pyvenv metadata、PE 架構與
CPython 3.12 x64 executable。固定 child 使用 `-I -S -B`，清空環境且不繼承 PATH、
PYTHON 或 KGI 設定；不 import SDK、不操作憑證、不連網、不寫套件或設定。
不接受 caller 指定 interpreter、proof JSON、credential 或 repair switch。

輸出 schema `omi.kgi-native-runtime-readiness.v1`、scope `INTERPRETER_BASE_ONLY`。
`PASS/exit 0` 僅表示 interpreter/base identity、位元、隔離 flags 與 stdlib path 匹配；
同主次版 3.12 的 patch 差異會顯示 `patch_drift=true` 與 `PYTHON_PATCH_DRIFT`。
絕對路徑只供內部比對，公開 report 僅輸出版本、位元與匹配摘要。
`BLOCKED/exit 2` 需一起查看 stage/reasonCodes；`BASE_PATH_ACCESS_DENIED` 表示基底
位置在目前執行權限下無法存取，不能解讀成未安裝；`PATH_NOT_FOUND` 才表示該檢查
位置查無檔案。任何結果的 `native_abi_verified`、endpoint/credential proof 都是 false，
REAL_SIM 仍 BLOCKED、正式環境與 session reuse 仍 FORBIDDEN。
靜態 RealSimPreflight 不會自行執行此 profile，也不採信存檔 readiness JSON 解除 gate。

維修順序：

1. 先以 `py -0p`、`where.exe python` 與明確候選位置查找現有 CPython 3.12 x64。
   原位置若存取被拒，先由可存取該位置的正常使用者終端執行上述 checker，保留完整
   status/exit；不要改 ACL，也不要把拒絕存取當成刪除安裝。
2. 對已確認的可信本機候選，用 `-I -S -B` 檢查版本、位元與 base identity，不 import SDK。
   新版本支援範圍不代表舊環境可混用；目前 site-packages 有 cp312 extensions，
   不得只把 `pyvenv.cfg` 指向 3.13。缺少可用 3.12 時停止；本 checker 不安裝任何東西。
3. 若有相容基底且獲授權修 metadata，先在 repo ignored `.tmp/` 的新專屬目錄，以
   `[IO.FileMode]::CreateNew` 非覆寫方式保存 pyvenv.cfg 與其 SHA-256，保存套件檔案
   hash。只更新 `home`、`executable`、`command` 的定位；保留 version 供 patch drift
   比對，不建立 venv、不重裝或刪除 site-packages。原地重新執行 checker。
4. 修復後若非 PASS 或 package hash 改變，立即以剛才備份逐 byte 還原 cfg 並重驗 hash；
   不回退其他 WIP。成功亦只到 interpreter gate，仍不得 SDK login/send。

不要使用 `setup-kgi-superpy.ps1 -Recreate` 做上述有限修復；該安裝流程會重建環境／pip
且超出此維修範圍。原生 SDK 的 DLL/CA、所有 egress/output confinement、專用 SIM
身分、endpoint attestation、session coexistence 與 durable intent 仍需另行設計與驗收。

Launcher 在回傳 qualification 前驗證 schema/mode、status 與 child exit、zero side effects，
並將通過檢查的物件重新序列化，避免重複 key 的相反解讀。generic BLOCKED、mutex
阻塞或 launcher failure 不是完整 qualification。新增 Windows regression 獨立執行：

```powershell
.\.venv\Scripts\python.exe -B -m unittest execution_kgi_simulator.tests.validate_native_runtime -v
exit $LASTEXITCODE
```

測試中的 invented 3.12 observation／copied launcher 只驗 contract 與失敗處理；
實際可用 3.13 child 只驗 isolation，均不計為本機 3.12 或官方 SIM acceptance。

本 package 是隔離資格驗證工具。**真實 Probe/Send 尚未實作為可啟用能力**，
只回傳 BLOCKED；沒有正式環境開關，也不能把 fake adapter 替換成 real SDK。

在 repo root 執行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test-kgi-official-simulator.ps1 -Mode Preflight
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test-kgi-official-simulator.ps1 -Mode ContractTest
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test-kgi-official-simulator.ps1 -Mode Probe
```

Exit 0：LOCAL MOCK tests PASS；1：測試失敗；2：BLOCKED。
Preflight/Probe 不會登入、連線或排程；Send 同樣封鎖，沒有真實 order payload 入口。
輸出為 JSON。SDK version/signatures/enums 為 AST inspection，不是 import/ABI 驗證。
PowerShell 送空的 presence map；既有 `KGI_SIM_*` 布林 pipe 仍可解析，僅供 legacy 診斷。
不要求第二套 SIM secret 設定、不載入 `.env`、不將 credential value 傳入 child。
SDK source status 是 `INSPECTED`，不是 native／broker PASS。

## Login-only 離線接線

`login_probe.py` 提供固定 `CredentialOwnerReference`、bounded typed private frame codec、
login/readback/logout lifecycle、generation fencing 與 sanitized fixture result。
`exercise_fixture` 只由 `tests/login_fixture_worker.py` 和離線 unit tests 使用；正式 worker
的 architecture constraint 禁止 dispatch 這個 seam。這個 fixture 沒有 native adapter 或真
Settings reader；`test_preflight=True` 不能啟用 REAL_SIM。獨立官方 SDK source 見下節。

正向 fixture 狀態是 `LOCAL_MOCK_ACCEPTED`，receipt origin 固定 `LOCAL_MOCK`，
runtime origin 固定 `NOT_CONNECTED`。每次 session 的身分 HMAC 使用隨機且不輸出的 key，
不回傳 person/account/SDK object。沒有 M1/M2A ledger 寫入，也不作為 broker evidence。
收尾包含 logout 與 CLOSED；timeout、late response、未知及 logout failure 不保留成功 receipt。

```powershell
.\.venv\Scripts\python.exe -B -m unittest execution_kgi_simulator.tests.validate_login_probe -v
exit $LASTEXITCODE
```

此獨立 profile 只傳 `INVENTED_*` inputs；驗證 FD stdout/stderr 丟棄、pipe、owned-process
timeout/cancel，不認證 native egress、CA、identity-derived logs 或 Windows filesystem confinement。
未來 Settings reader 必須在受控父程序通過所有驗收後才讀既有欄位，使用短命私密 pipe，
不使用 env/argv/temp/log。Python/SDK immutable strings 無法承諾 secure zeroization。
詳細限制與回退見本輪 [驗收](../docs/exec-plans/active/kgi-real-sim-20261012/login-plumbing-20261012/Acceptance.md)。

LOCAL MOCK 使用相同 M1 Draft/admission/reducer、M2A confirmation/reservation/outbox。
只有固定的 `FakeSDK` 可進入 wire rehearsal；1000 shares/unit 完全是 fixture 假設。
claim 先 commit，fake call 在 transaction 外，transport Pending 不 accept。
後續明確的本地 correlated observation 才能推進 reducer。
claim 後 crash 是 UNKNOWN，不重送；query/reconcile/cancel 只在明確 command 時執行。

2026-10-11 Source audit 修復：kill switch 只封鎖新 SEND claim；明確 QUERY/CANCEL
仍須通過既有 digest、generation、一次性 command 與取消 identity 檢查。
`CancelOrder.Success` 只保存 `ACK_ONLY` audit，不產生 reducer event；正常取消流程維持
`CANCEL_PENDING`，UNKNOWN 也不會被 ACK 解決。
只有另一筆 `OrderStatus.Cancelled`，附上完整且綁定 command／preview／generation／
`LOCAL-ORDER` 的 `finality_fixture`（`origin=SYNTHETIC`、`scope=LOCAL_MOCK`、
`status=Cancelled`、`complete=True`），才可交由原 M1 reducer 判斷終局。
這是 test-only fixture schema，不是 broker finality 證明或可替換的真實 ingress。
晚到 partial/full fill 保留原 reducer 語意；取消不抹除累計成交。

Replay 相容範圍：舊 audit 中未帶 `semantics` 的取消成功紀錄，仍依原本事件重放，
不改寫歷史 projection；新 command 一律寫 `ACK_ONLY`，不能產生該舊格式。
舊紀錄相容不代表其 ACK 已取得獨立終局證據。

本次修復重跑結果（前次 Acceptance／Evidence／SourceManifest 保留原樣）：

- KGI ContractTest：32 PASS、0 FAIL、0 ERROR、0 SKIP；包含原 25 tests 與新增 7 個回歸。
- 五組 legacy suites：240 tests，239 PASS、0 FAIL、0 ERROR、1 SKIP（Windows symlink 1314）。
- 六組 execution architecture manifests：全部 PASS、0 violations、0 debt。
- Repo architecture guard：PASS，15 violations 均屬既有 declared debt。
- Backend architecture integration：2 PASS。
- ACK、終局、晚到成交、kill switch 與歷史紀錄皆含獨立 child-process replay parity；
  child 只重開 factory sandbox、verify/status/audit，沒有呼叫 wire。

本輪直接執行隔離 ContractTest worker，避免 launcher 的 credential presence lookup：

```powershell
.\.venv\Scripts\python.exe -I -S -B execution_kgi_simulator/worker.py ContractTest
```

沒有執行 Preflight/Probe/Send；沒有真 SDK import、憑證／CA 讀取、券商登入／送單／取消、
排程或 production DB 寫入。上述結果只驗證 LOCAL MOCK source，真實 simulator 仍 BLOCKED。

真實測試前缺口與命令見
[Handoff](../docs/exec-plans/active/kgi-official-simulator-20261011/Handoff.md)。
架構邊界見 [Architecture](../docs/architecture/ExecutionSimulatorQualification.md)。

## G1→G3 官方 login-only source checkpoint

`native/` 現在有 fixed-path readiness、canonical Settings 延遲橋接、私密 challenge/frame
協定、distinct worker，以及真正呼叫官方 `kgi.login(..., simulation=True)`／native
`GetAccounts()`／`_logout()` 的 one-shot adapter body。沒有呼叫 `login_fixture` 替代。
**G1/G2/G3 皆 BLOCKED**；source unit tests 不能宣稱 native host／login acceptance。

`require_verified_host()` 固定拒絕，沒有 caller flag、endpoint 或 proof 入口。官方 TEST
目的地 attestation、Windows egress/filesystem/CA/child/handle enforcer、backend parent
activation 尚未齊備，故 native worker 不讀 stdin／Settings、不 import SDK。單純 cwd 隔離
無效：SDK constructor 會切換到 libdir 並初始化 identity-derived logs。

唯讀診斷（預期 exit 2；JSON 是 evidence，不能作為 unlock token）：

```powershell
powershell.exe -NoProfile -File scripts/test-kgi-official-simulator.ps1 -Mode RealSimPreflight
$LASTEXITCODE
powershell.exe -NoProfile -File scripts/test-kgi-native-containment.ps1
$LASTEXITCODE
.\.venv\Scripts\python.exe -I -S -B execution_kgi_simulator/native/worker.py
$LASTEXITCODE
```

離線 source／negative tests：

```powershell
.\.venv\Scripts\python.exe -B -m unittest execution_kgi_simulator.tests.validate_native_activation -v
```

Settings owner 仍是 `backend/app/config.py`；未來 parent 必須在 backend 的 import context
解析 `app.config.settings`。這次沒有真的 import Settings，也沒有新的 credential store。
SDK logout 沒有 native acknowledgement contract；return 不能當成功登出。Host activation、
hang／descendant teardown、redirect/fallback deny 均仍待驗證，不會以 fake test 解鎖。

## Windows host 無秘密 building block

`native/parent.py` 提供獨立 backend-context 入口；以下使用現有固定 interpreter，不依靠
PATH、不安裝 dependency，也不修改 firewall、AppContainer profile、ACL 或 registry。

```powershell
.\.venv\Scripts\python.exe -I -S -B execution_kgi_simulator/native/parent.py preflight
$LASTEXITCODE
.\.venv\Scripts\python.exe -I -S -B execution_kgi_simulator/native/parent.py suspended-probe
$LASTEXITCODE
.\.venv\Scripts\python.exe -B -m unittest execution_kgi_simulator.tests.validate_host_activation -v
$LASTEXITCODE
```

前兩條固定 exit 2：沒有啟用 authority。Probe 嘗試 restricted-token suspended child，
原子 Job assignment／kill-on-close／禁止 breakaway／兩個 inherited pipe ends，核對後
關閉 Job 並等待 owned child 終止。沒有 resume 路徑、不 import SDK、不讀 Settings。
若 API 被拒絕，輸出具體 stage/winerror，沒有較弱的 launch fallback。

Deny-all policy 是 SOURCE_ONLY schema，尚未安裝 per-child WFP 或 filesystem boundary；
即使 lifecycle 回 OS_VERIFIED，三個 gate 仍 BLOCKED。`login-only` 入口也固定拒絕。
本輪結果與精確依賴見
[Host handoff](../docs/exec-plans/active/kgi-real-sim-20261012/host-activation-20261012/Handoff.md)。
