# 原生 KGI headless 操作

2026-11-06 MCP 接線：使用者可在 AI 提名建立待送單，再從 MCP 前端送出；盤後自動須先轉 AI 提名。`desk-submit` 沿原 Native session 一次派送，`desk-cancel` 精確撤單，`desk-protection` 修改該單出場規則。每單停損、多段停利與比例可調；出場依實際成交量、本機行情與限價 ROD 執行，並非券商原生託管。正式啟動預設綁定 TW／US 同一登入以恢復規則，明確 US=false override 與 simulation 保留。完整採用證據見 [MCP 接線進度](../docs/exec-plans/active/mcp-research-execution-20261106/Progress.md)。

## 美股手動正式送單（2026-11-06）

`us-order` 會透過現有 production session 直接送單，自動選取複委託帳戶；不必先跑 `us-probe` 或修改 `.env`。使用者的明確命令沿原 Runtime review／claim 寫入後只送一次，沒有額外審批步驟。以下命令僅由使用者自行執行；更換 request ID 代表新的一筆委託。

```powershell
Set-Location -LiteralPath 'C:\project\Open Market Intelligence'
$requestId = 'tsm-manual-20261106-001'
.\.venv-kgi\Scripts\python.exe -B -m execution_runtime.control us-order --request-id $requestId --symbol TSM --action Buy --quantity 1 --price 1 --settlement TWD
.\.venv-kgi\Scripts\python.exe -B -m execution_runtime.control us-status --request-id $requestId
```

以上為 TSM 1 股、USD 1 限價、台幣交割。外幣交割使用 MUT。`us-status` 不加 request ID 只綁定／查詢同一帳戶狀態，不送單；`us-cancel --request-id <原 request ID>` 對該筆執行精確撤單。

回應的 `submission_status=RETURNED` 是 SDK 返回，是否委託成功看 `broker.operations`／`broker.broker_status`／`status_code`，不是成交保證。逾時或 UNKNOWN 保留原 request ID 查詢；相同 request ID 重複呼叫不會重送。成交明細的未驗證部分保留未知，不影響手動委託交給券商受理。完整採用與測試紀錄見 [ManualProduction.md](../docs/exec-plans/active/kgi-us-execution-20261105/ManualProduction.md)。

## 歷史唯讀 checkpoint（2026-11-05，送單限制已由上節取代）

新 `us-probe` 是明確操作，透過既有 Native owner 在同一登入綁定複委託帳戶，讀取單一商品與委託／成交報表的成功狀態及列數。只輸出帳戶 alias 與白名單商品欄位，不輸出帳號、姓名或交易明細。

```powershell
.\.venv-kgi\Scripts\python.exe -B -m execution_runtime.control us-probe --symbol TSM
```

此入口不接受價格、數量、方向或 command payload，不呼叫 create_order／cancel_order，不保存草稿或修改 Journal，也不開第二個登入。probe-only binding 不啟用 US operational context，因此不改變原 TW 換日恢復政策；既有正式美股 effect gate 仍封鎖。未載入此版本的 Native 須先經原 Launcher 正常 stop/start 採用，不繞過 session lease。

2026-11-05 23:55（Asia/Taipei）已在 production 完成一次 TSM 唯讀驗證：商品 USD／board lot 1、兩份報表均 AVAILABLE，後續 TW 查詢與同一 session 保持正常。未建立委託。Native status 中 US operational `account_bound=false / US_DISABLED` 與獨立 probe 成功不矛盾：probe 沒有啟用正式 US execution context。完整紀錄見 [美股唯讀驗收](../docs/exec-plans/active/kgi-us-execution-20261105/ReadonlyAcceptance.md)。

## MCP 503 與控制命令逾時

先分別讀 Launcher 的 `ExecutionStatus` 和 Native 的 `control status`。`STOPPED / keep_online=false` 表示交易服務未啟用；Native 的 `FileNotFoundError / EXECUTOR_UNAVAILABLE` 只表示本機 pipe 不可達，不能單靠它判定券商網路原因。舊 startup JSON 的 READY 不代表程序仍存在。已載入 execution component 的 Launcher 可沿既有啟用入口操作；只有 loaded-source 不符時才安排正常採用，不預設重啟全部服務。

送出命令後的 timeout／EOF／無法解析回應維持 `EXECUTOR_RESPONSE_UNKNOWN`；client 退出不取消 Native 正在執行的命令。Backend 對已 claim 的 staged 操作保留 `SUBMISSION_UNKNOWN` 與原身份，不自動重送。只有明確收到 Native rejection code 才當已知拒絕；舊 controller 僅回 `error_type=ExecutionRejected` 而沒有 code 時，同樣按未知結果處理。這些分類是 Source 修正，正式 Backend／MCP 採用須另核對。

Native 發布收據遇到 `ReplaceFileW` 的 32／1175 時，原發布點會有界重試最多 0.5 秒；這是收據 IO 重試，不是交易重送。持續失敗、ACL 拒絕或部分移動仍回報錯誤，不手動刪除 receipt／lease 來繞過。隔離測試已重現 1175 導致 Native 退出，正式歷史故障仍沒有同一例外的證據。

2026-11-05 本輪唯讀 Status 已確認現有 Launcher 載入 execution component，當時為 `STOPPED / keep_online=false`；MCP HTTP 的 loaded build 與磁碟版本不同。因此後續採用先核對各 component 的 source，不直接照下方舊 checkpoint 一律重開 Launcher。實作、測試與後續正式啟用條件見 [本輪驗收](../docs/exec-plans/active/execution-always-online-20261105/PersistentRuntimeAcceptance.md)。

## 常駐部署的新入口（Source／隔離，尚未正式採用）

先由 Reviewer 核對 [部署驗收](../docs/exec-plans/active/execution-always-online-20261105/DeploymentAcceptance.md)，在本機原桌面 tray 正常 Exit，再經原桌面捷徑重開 Launcher，載入新的 execution component。舊 Launcher 不會熱載入；不可用 NORMAL 短命令重建 Launcher／Native 樹。以下是後續 Reviewer 核准的操作入口，本 job 未執行：

```powershell
.\scripts\omi-execution-control.ps1 -Action Status
.\scripts\omi-execution-control.ps1 -Action Start -RequestId <新的UUID>
.\scripts\omi-execution-control.ps1 -Action Status
.\scripts\omi-execution-control.ps1 -Action Stop -RequestId <新的UUID>
```

也可用原 tray 的「交易服務（維持連線）」選單。Start 是明確連線意圖，只由持續存在的 Launcher 建立唯一 supervisor；短 client 結束不結束服務。持續意圖保存在原 Launcher per-repo control directory 的 `settings/execution-preference.json`（非秘密、非交易 store）。未明確啟用時預設不登入；啟用後，下次正常 Launcher startup 自動採用一次。Stop 先保存 OFFLINE，重開也不會復活。不要把 STARTING／STOPPING 當完成，不自動重送 Start；用同 owner／startup id 的新 Status 追蹤。

Launcher Status 的 RUNNING 是 fresh heartbeat 與 retained OS lineage，不是券商 ONLINE。仍用原 `execution_runtime.control status` 驗 broker connection、loaded_source、trade_date、ready／busy 等獨立 axes。正常 Launcher Exit 必須先確認 Native/supervisor 退出，會保留 keep_online 供下次正常啟動；明確停用才清除它。換版前先 Stop 並確認 STOPPED／keep_online=false；未知狀態不 force-kill、不刪 lease、不自行改 receipt。

以下舊 `launch --background` 是歷史直接啟動入口，不能用作受短命令 Job 管理環境中的正式常駐部署；本節的 Launcher-owned 入口取代該部署方式。原 foreground/probe、Native 控制與 Journal 語意保留。首次正式採用、登入、OS cold-login 與長時間觀察皆仍待 Reviewer；本輪只用 Fake SDK／臨時 state 與隔離 OS 程序驗證。

## 2026-11-05 Source 交接入口

本版只完成 Source/Fake；下列正式命令**本 job 未執行**。Reviewer 應先核對 [Acceptance](../docs/exec-plans/active/execution-always-online-20261105/Acceptance.md)、task-only patch/hash 與已授權的部署範圍。以下舊 checkpoint 的正式登入結果不代表本版 loaded source 已驗收。

經獨立 review 與後續授權後，在 repo root 用既有設定啟動：

```powershell
.\.venv\Scripts\python.exe -B -m execution_runtime.launch --connect --background
.\.venv-kgi\Scripts\python.exe -B -m execution_runtime.control status
```

不要加入 `--enable-strategy-effects`。背景 launch 是唯一 supervisor；回 READY 需本次 identity 的 receipt。STARTING／RECOVERING 表示尚未就緒，不重複 launch。`loaded_source`、pid、interpreter、root、environment、connection axes 和正式唯讀結果必須分別核對；檔案快照與 source 測試不是 live health。

正常停用，含 Native pipe 不存在的 backoff：

```powershell
.\.venv\Scripts\python.exe -B -m execution_runtime.launch --stop
```

這個入口不讀帳密、不登入。只有 exact supervisor/request ACK 才是接受 OFFLINE；STOPPING 不是完成。檢查 `supervisor-status.json` 的同一 startup_id/stop_request_id，須 STOPPED、owner_released=true，並另核對 supervisor／Native process 已退出。無 ACK／owner 不符／SDK hang 維持 UNKNOWN/BLOCKED，不 force-kill、不刪 lease、不另啟第二個 owner。Native 活著時原 `execution_runtime.control stop` 仍可正常停用；durable OPERATOR_STOP 即使接著 child crash 也不會被 supervisor 復活。

Source 回退：先完成上述停用與退出證據，再僅反向套用本輪 task-only patch；不要 reset worktree、刪 DB/Journal、改舊 intent 或覆蓋其他 WIP。本版未改 schema；既有歷史版本對 `SUBMIT_NOT_SENT` 等事件的限制仍適用。若前置 hashes 不符，先人工比較增量，不強行套 patch。

無 Windows service／排程／登入自啟動；supervisor 自身 crash 或 OS reboot 仍需明確重新啟動。本版不保證網路不中斷、SDK call 可取消、回補所有券商歷史或限價成交。詳見本輪驗收中的未驗證項目。

本入口全部位於 OMI，不依賴其他專案。Python 3.12.3 x64／kgisuperpy 2.1.0 native import 已驗證。2026-10-30 已完成正式登入、account selection、唯讀 order/deal query、正常 logout/reconnect，以及獨立背景程序驗收；未送買賣委託、未撤任何真單。官方 simulation probe 回 `KGI_LOGIN_INCOMPLETE`，維持 BLOCKED。最新 PID／Loaded Source 與原始限制見任務 Progress／Continuation-Validation.json。

## 啟動與設定

在 repo root 操作。安全的 import 檢查不讀 `.env`、移除繼承的 KGI 設定，也不登入；檢查期間禁止 socket connect／bind 與子程序。

```powershell
.\.venv-kgi\Scripts\python.exe -B -m execution_runtime native-check
.\.venv\Scripts\python.exe -B -m execution_runtime.launch --help
```

正式操作入口使用既有 `.venv` 的 `python-dotenv` 讀 OMI `.env`、再讀 `.env.runtime`，最後由 process env 覆蓋；只挑選 `KGI_SUPERPY_PERSON_ID`、`KGI_SUPERPY_PASSWORD`、`KGI_SUPERPY_TW_ACCOUNT`、`KGI_SUPERPY_SIMULATION` 給 child。既有帳密不必重填、不進 argv 或輸出。實際 SDK 程序固定使用同 repo `.venv-kgi\Scripts\python.exe`。沒有讀其他專案設定、Backend import、SDK 安裝或全域 Python fallback。

```powershell
# 官方測試環境；其餘帳密與帳戶沿用 OMI 本機設定。
$env:KGI_SUPERPY_SIMULATION = 'true'
.\.venv\Scripts\python.exe -B -m execution_runtime.launch --connect

# 正式環境：先正常結束舊程序，再啟動。這會真正登入，不要作一般 smoke test。
$env:KGI_SUPERPY_SIMULATION = 'false'
.\.venv\Scripts\python.exe -B -m execution_runtime.launch --connect
```

若安全啟動環境已注入所有 `KGI_SUPERPY_*`，可直接執行 `.\.venv-kgi\Scripts\python.exe -B -m execution_runtime native --connect`。直接入口只讀 process env；有 `.env` 設定時使用上面的 config bootstrap。缺失或無法解析的 simulation 設定會拒絕啟動，不靜默選正式環境。`true/1/yes/on` 與 `false/0/no/off` 分別傳原生 bool 給同一 `kgisuperpy.login(person, password, simulation)` 路徑。

前景模式是持續運作的 stdin／stdout 程序；stdin 保持開啟就保留同一 session，EOF 或 Ctrl+C 走正常 close。一次性的 shell pipeline 在 EOF 結束程序，不會持續保護策略。背景模式與一次性控制命令如下，控制程序退出不終止 runtime：

```powershell
.\.venv\Scripts\python.exe -B -m execution_runtime.launch --connect --background
.\.venv-kgi\Scripts\python.exe -B -m execution_runtime.control status
.\.venv-kgi\Scripts\python.exe -B -m execution_runtime.control query
.\.venv-kgi\Scripts\python.exe -B -m execution_runtime.control reconnect
.\.venv-kgi\Scripts\python.exe -B -m execution_runtime.control stop
```

背景程序使用 Windows detached process／hidden startup，不依賴研究 Backend／Frontend 或控制程序存活。`STARTING` 的 PID 是 venv redirector，不等於 native PID；以新 control status 的 `pid/interpreter/project_root/loaded_source` 和 Windows process identity 一起驗證。`STOPPING` 不是停止完成，必須再確認該 native PID 退出。沒有 Windows service 安裝、排程、登入自動啟動或跨 reboot 保證。11/05 Source 的背景入口新增單一 supervisor 與 managed reconnect；其正式採用仍待本輪交接驗收。

控制通道是固定 OMI-local Windows named pipe，使用有界 bytes JSON，不用 pickle、TCP、MCP 或另一個 manager/store。雙向以 Windows process token 驗證同使用者；server 只接受 `ERROR_PIPE_LOCAL=229` 證明的本機 caller，未知 identity 拒絕。依據為 Microsoft [pipe client PID](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getnamedpipeclientprocessid)、[token query](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-gettokeninformation) 與 [ERROR_PIPE_LOCAL](https://github.com/MicrosoftDocs/win32/blob/docs/desktop-src/Debug/system-error-codes--0-499-.md) 文件。這是本機同一 OS principal 的操作入口，不授權遠端／不同使用者。

`loaded_source` 是程序啟動時 execution source＋共用 kernel 的 SHA-256 pin；`source_matches` 只顯示目前磁碟是否一致。後續 source 修改不封鎖已載入程序的 query／cancel／手動退出；更新採用以正常 stop、確認退出、再 start 處理。`data/execution-runtime/process-status.json` 只保存去識別程序 receipt，不能代替新的 pipe response 或 OS process 驗證。

程序在登入前取得固定 `data/execution-runtime/native-session.owner` OS lease；同一 checkout 不能用不同 mode、帳戶或 journal 參數繞過。factory 本身要求仍被持有的 `OwnerLease`。取得此 lease 後才 discovery account，再將同一個 `SessionBinding` 交給原 `KgiSessionOwner`；不會第二次登入。

帳戶選擇沿用 quote bridge 語意：篩選「證券」、去重；設定 `KGI_SUPERPY_TW_ACCOUNT` 時必須精確匹配，未設定且僅一個候選時自動選取，多個候選則拒絕。reconnect 必須先成功 logout，且不能換帳戶。本入口不修改、重用或終止 quote／holdings bridge session。

## stdin 協定與雙 Space

每行一個 JSON object，格式 `{"id":"client-request-id","argv":["command","argument",...]}`。每行回一個 `id/ok/result` 或 `id/ok/error`。`id` 只負責傳輸關聯，durable idempotency 仍由 Draft 的 `request_id/intent_id` 與 review selector 擁有。格式錯誤不重播；超過 128 KiB 的行直接終止讀取，避免將後半段誤當下一個命令。

背景模式以 `.\.venv-kgi\Scripts\python.exe -B -m execution_runtime.control command --request-json '<同一個 id/argv JSON>'` 呼叫完全相同的 application routes；沒有第二份 submit/cancel engine。`status/query/reconnect/stop` 是程序控制命令；交易 review 的 status 仍放在 `command` 的 argv 中。

下例是輸入格式；`TEST`、日期、價量均須由操作者換成實際且已檢查的值，範例不會被啟動器自動執行。所有帳戶欄位都使用 `SELECTED`，實際帳戶只由目前 session 決定。

```json
{"id":"user-draft-1","argv":["draft","--draft-json","{\"command\":{\"account_id\":\"SELECTED\",\"trade_date\":\"2026-10-29\",\"request_id\":\"user-request-1\",\"intent_id\":\"user-intent-1\",\"symbol\":\"TEST\",\"action\":\"Buy\",\"quantity\":1,\"price\":\"50\",\"space_id\":\"USER_SPACE\"},\"owner_id\":\"local-user\",\"source\":\"MANUAL\"}"]}
{"id":"agent-draft-1","argv":["draft","--draft-json","{\"command\":{\"account_id\":\"SELECTED\",\"trade_date\":\"2026-10-29\",\"request_id\":\"agent-request-1\",\"intent_id\":\"agent-intent-1\",\"symbol\":\"TEST\",\"action\":\"Buy\",\"quantity\":1,\"price\":\"50\",\"space_id\":\"AGENT_SPACE\"},\"owner_id\":\"local-agent\",\"source\":\"AGENT_PROPOSAL\"}"]}
```

使用各次回傳的 `review_id`，逐步輸入：

```json
{"id":"preview-1","argv":["preview","<review_id>","--expected-revision","1"]}
{"id":"confirm-1","argv":["confirm","<review_id>","--expected-revision","1","--expected-digest","<snapshot.digest>"]}
{"id":"status-1","argv":["status","<review_id>"]}
{"id":"list-1","argv":["list"]}
{"id":"query-1","argv":["query"]}
```

Preview 是目前真實 session 下 canonical command 的純預審，無 SDK `create_order`，不宣稱券商已預核風控或接受。Confirm 會真的進入 engine，沒有新增另一個 execute flag。USER_SPACE 與 AGENT_SPACE 都使用同一流程，AGENT_SPACE 本身不會自動確認。Revise／Reject 沿用 `cli.py` 的 typed route；revision 改變後舊 Preview 無效。公開輸出遮蔽 account ID、移除 journal audit／原始 row diagnostics；digest 指向原始內部 snapshot，不能用遮蔽後的 JSON 重算。

每次 query 呼叫 SDK `Account.OrderReport()`、`Order.get_trades(full=True)`、成交報表。安裝版 2.1.0 的 public facade 將 `ExecReport` 放在 `Account`，所以使用 `Account.ExecReport` 並保留此 source 名稱；若 SDK 公開 `Order.ExecReport`，沿用該介面。這些 SDK 報表／cache 不保證新 session 的歷史完整性，`fill_history_complete=false` 不變。

精確撤單使用 confirm/status receipt 的 identity；不需重做 Preview／Confirm，沒有 cancel-all：

```json
{"id":"cancel-1","argv":["cancel","--execution-id","<execution_id>","--account-id","SELECTED","--trade-date","<trade_date>","--broker-order-id","<broker_order_id>"]}
```

Timeout／UNKNOWN 或任何傳輸中斷後，先以原 review 查 status／query，不換 request ID 重送。無 broker ID 不靠商品、價格、數量猜配。撤單 ACK 不是撤單 final；仍需 report 與 late fill reconciliation。

## 策略調整

初期策略只允許原有 CASH long 模型。Draft 的 command 加 `strategy_id`、`revision:1`，依原流程 Confirm 後建立策略。`StrategyRules`、`SourceSnapshot`、修改 request ID 與 expected revision 全部交原 Runtime；沒有第二份 position/order ledger。

CLI argv routes：

| 指令 | 參數 |
|---|---|
| `strategy-create <review_id>` | `--expected-digest <digest> --rules-json <JSON> --source-json <JSON>` |
| `strategy-status <strategy_id>` | 無額外參數 |
| `strategy-revise <strategy_id>` | `--request-id <stable-id> --expected-revision <n> --rules-json <JSON> --source-json <JSON>` |
| `strategy-exit <strategy_id>` | `--request-id <stable-id> --expected-revision <n> --source-json <JSON> [--target-position <shares>]` |
| `strategy-price <strategy_id>` | `--request-id <stable-id> --expected-revision <n> --source-json <JSON> --symbol <symbol> --price <price>` |

`rules-json` 範例：`{"stop_loss":"45","take_profit":"55","exit_limit_price":"45"}`；`source-json` 格式：`{"source_id":"operator-plan","observed_at":"<ISO timestamp with offset>","content":{"reason":"operator revision"}}`。JSON 作為 argv 的一個字串，與 draft 相同。

原生入口預設 `strategy_effects=false`：可建立／修改規則，不啟動 effect pump；`strategy-exit` 明確回 `STRATEGY_EFFECTS_DISABLED`，不儲存待日後偷偷派送的退出指令。若操作者刻意允許既有策略恢復派送，啟動時加入 `--enable-strategy-effects`。此選項會允許既有 target 在 startup query 後精確撤 entry／送 child exit，可能在第一個命令前產生券商 effect；本次實際部署保持停用。

Native Runtime 的 SL/TP 價格只收同一 KgiSessionOwner session 的 `Quote.set_cb_all`＋`subscribe_all(symbol, odd_lot=...)`，有已確認策略才訂閱；不新登入，不借 quote bridge lifecycle。一般股與盤中零股分開對應策略 lot。`strategy-price` 在 native mode 回 `NATIVE_PRICE_CALLBACK_REQUIRED`，caller 任意標記來源不能偽裝真實 callback。

來源 `datetime` 支援 SDK 的 14 位 `YYYYMMDDHHMMSS`，以台北時區解析後轉 UTC；不得用 receipt time 補值。trial／suspend／delay／無量、未來時間、超過 5 秒的來源時間皆拒絕。combined callback 也含 depth，因此先建立累計成交量 baseline，只有 `total_volume` 增加才視為新成交價格。初次 sample／沒有事件／過期事件分別顯示 WAITING_TRADE_PROGRESS／WAITING_NATIVE_TRADE／STALE；訂閱方法可呼叫或 callback 已註冊不代表 native price 已驗收。

正常 tick 只更新原 Runtime `_prices` 投影，不讀寫 journal。只有首次符合 SL/TP 時，透過相同 `price_trigger` 判斷，保存來源／received timestamp 及觸發 evidence，交原 Runtime target/reservation/engine。重複／倒序／只有 depth 更新不重複 claim；已觸發 target 的後續 tick 不擴大 immutable journal。可修改已送策略，原 confirmed command 不改寫。實際 deploy 的 price source 尚為 WAITING_NATIVE_TRADE，不能宣稱真實停損／停利保護已生效。

策略修改不改寫已確認 entry snapshot。新增曝險仍須新的 Preview／Confirm；UNKNOWN child claim 不釋放 reservation、不自動 resend。沒有 AI 自動確認。跨台北日界線後舊 native binding 的 SDK IO 與 callback admission 仍拒絕；11/05 managed 背景入口由原 owner 正常關閉／重綁新日期，前景入口仍需明確重開。兩者皆不重送舊 intent。

2026-10-30 跨日修正：以新交易日 Session 開啟原 journal 後，前日策略仍訂閱同 Symbol／lot、可修 SL/TP、可明確退出；child exit 使用目前 Session 的交易日。舊 Entry、review digest、成交與原 broker identity 不改寫。昨日 ROD 未證實餘量顯示未知，不當作當日可撤單；exact identity 先驗證，再於任何 claim 前拒絕舊日取消。跨日與重連都不重送既有 child intent。

Native factory 強制啟用同 Session 的現股查核：使用 `Account.InventorySum("B")` 股數、依 OMI 既有正規化取 `max(NETQTY0, NETQTY9, 0)`，不相加，也不混入融資／融券。這是現股總量上限，SDK 2.1.0 的 `SALEQTY` 名稱不能證明可賣／交割／委託扣抵語意。Runtime 從原 Journal 計算所有 Space／策略／人工賣單 reservation，和同 Session 的 account order report 以精確 key 去重；已知手機賣單佔用與新的庫存減少都會降低上限。缺少 Symbol、資料失敗／超過 5 秒、未知數量單位或同 Symbol 疑義單不當成全額可賣。報表逐列 quarantine，無關 Symbol／已知歷史拒單不封鎖全帳戶。

自動 SL/TP 與明確 `strategy-exit` 分別顯示 `exit_initiation=AUTOMATIC_PRICE_TRIGGER/OPERATOR`，在有效已知上限內可派送；每筆 child SDK effect 前由同一 session lock 再查核一次，超過上限則不送。`cash_inventory.status=UNVERIFIED`／`sellable_quantity=null`／`report_complete=false` 持續揭露來源限制，不是永久禁止所有退出。只有新鮮可計算的部分可用；一般明確 Draft→Preview→Confirm 人工賣單入口仍保留，沒有新的全面交易 Gate。

送單前證實未呼叫 `create_order` 時記錄 `SUBMIT_NOT_SENT`、`submit_stage=NOT_SENT`、`broker_attempts_max=0`，本地 REJECTED 不是券商拒單。原 intent 保留且永不重送，其 reservation 釋放；新的策略修訂或新 operator request 才可建立下一個 child，query／restart／reconnect 不自動重試。已進入 SDK 的 exception 仍是 UNKNOWN、保留 reservation。status 的 `trigger_state`、`exit_execution_state`、`effective_position` 分開；`LOCAL_LIMIT_ROD` 不保證成交，`protection_guaranteed=false`／`exit_fill_guaranteed=false`。`protected_quantity` 僅保留歷史 lineage 數值，不代表券商保護或可立即賣出量。

## 保存、部署限制與回退

- 固定 OMI-local journal：`data/execution-runtime/simulation.sqlite` 與 `production.sqlite`；沿用原 schema v1／application ID／transaction owner。不同 mode 不共用 broker facts；兩個 Space 在同 mode 共用一份 journal。account metadata 不符會拒絕開啟，不能刪檔解決。
- 不碰 `data/open_market_intelligence.db`。執行狀態受既有 `.gitignore` 的 `data/*` 排除。不要提交、複製到公開 artifact 或讀印 private journal。
- stdout 是本機操作者的交易 receipt，不應送到公共 log。SDK stdout/stderr（包含 fd 1/2）持續抑制到程序結束，只有 protocol writer 持有原 stdout 副本。2026-10-30 首次 probe 的 teardown 污染保留為已修正 incident；修正後同一正式 readonly probe 只有兩行合法 JSON，子程序測試另覆蓋 context exit／atexit／原生 fd 輸出。錯誤只輸出固定狀態、exception type 與受控 `ExecutionRejected.code`。SDK 自身 native file logs 的 retention／權限仍未驗收；stdout clean 不是 vendor 不落地資料的證明。
- OS lease 僅證明同一 OMI checkout 的入口互斥，不保證其他 checkout／其他軟體／其他機器沒有同帳戶 session。沒有自動清 lock、force-kill 或破壞 quote runtime。
- SDK 呼叫沒有額外 thread timeout／force-kill；native hang、CA、帳戶權限、服務退出、callback recovery、跨日行為、真 broker history 完整性都是尚未驗收的 deployment gate。SDK import PASS 不能提升為可實盤使用。
- 本輪部署為 detached native process，未安裝 Windows service，也未重啟研究系統。回退先 control stop 並確認 native PID／owner 結束，只撤回本輪 source diff；保留所有 journal／原有 WIP／歷史 acceptance。未確認 logout 時不得另啟第二個 session。
- 若 journal 已產生新的 `SUBMIT_NOT_SENT` 事件，舊版 reader 不理解該狀態，不能直接換回舊版後刪／改事件來通過 verify；須保留能讀取此事件的版本。此次實機只有唯讀驗收、無 child claim，未產生此類正式交易事件。
