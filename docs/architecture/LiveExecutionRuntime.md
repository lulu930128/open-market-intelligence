# 每單人工執行接線（2026-11-06 current source）

台股 Desk readback 對歷史 `BROKER_OBSERVATION` 採逐列解析；無法建立合法 broker identity 的資料保留原 Journal bytes，透過既有 `unparsed_reports` 回傳 `INVALID_JOURNAL_OBSERVATION` 與 Journal sequence，該來源標示 PARTIAL。它不產生委託／成交 identity，不改寫 ledger，也不隱藏其他有效紀錄；SDK 斷線仍在各來源顯示 UNAVAILABLE，歷史證據不冒充即時券商讀回。

`desk-submit` 在原 Runtime 一次操作內完成持久化選定版本、preview、confirm 與 submit；MCP 使用者點按是此筆明確交易意圖，不另加 gate。Broker IO、SDK session、單據與 fills 仍由原 owner 管理。TW／US 共用操作面，US 使用既有子 context 與相同 SDK lane。

正式 Native 啟動預設於同一登入綁定 TW／US，以恢復已保存的美股每單規則；保留明確 `KGI_SUPERPY_US_ENABLED=false` override，simulation 不綁定美股。US 帳戶或介面不可用時沿既有 binding reason 回報，不妨礙 TW 原連線。

`StrategyRules.enabled` 是使用者選定的每單出場規則；預設 false 保持既有策略不自動啟用。Research stage 明確攜帶 enabled=true 與各 TP price/fraction/limit、stop trigger/limit。使用者可在原 execution 修改規則，不重送進場；已派送子單不回溯改寫。每筆委託依自身成交與預留退出數量協調，整股／小股數不提前把 TP2 比例交給 TP1。

明確採用的每單規則按該單實際成交數派送，券商判定可賣／信用資格，不新增帳戶估算庫存門檻；舊 global 策略的現有 capacity path 保留。TW SHORT_SELLING 回補為 Buy/SHORT_SELLING；現先賣回補為 Buy/CASH（SDK 禁止 Buy/CASH_SELLING）。US Sell 仍是現股賣出，不能宣稱裸放空已支援。

US `US_ORDER_TOTAL_OBSERVED` 保存券商累計量與本機讀取時刻，精確聯結 durable original ID、order ID、帳號與原價量。它不是逐筆 fill，也沒有虛構時間戳或 fill ID；`fill_history_complete=false` 保留。US quote 的無時區原始字串採明示 LOCAL_CALLBACK_RECEIPT，不假設紐約時區；callback latency 與交易量進展分開驗證。斷線重接由原 owner 恢復訂閱，讀取／重播不重送 entry。

MCP 使用者可精確撤單與修改每單出場規則。未提供把 SDK US cancel-and-replace 偽裝成原子改價的 API。出場仍是 LOCAL_SYNTHETIC / LIMIT ROD，需本機 runtime 與行情在線，並非券商託管或成交保證。

以下保留先前階段證據；其中舊的 CASH-only／TW-only／尚未接 MCP 描述不代表上述 current source 的能力。實際 Loaded／Live 驗收另見 active exec plan Progress。

# Dedicated Execution Runtime（原生 headless 接線）

## 美股手動正式送單

`control us-order` 依使用者指定的商品、方向、股數、USD 限價、TWD/MUT 交割及 request ID，在現有 Native owner 上送出正式委託。它自動綁定同一登入的複委託帳戶，不要求先跑 probe 或設定 US enable flag。Native factory 維持帳戶選擇與重連 pin；所有 SDK IO 仍在 KgiSessionOwner 的共用 lane。`us-status` 查詢連線或指定 request；`us-cancel` 以該 request 保存的原始序號及委託書號精確撤單。

先前固定拒絕 Native US 的 `US_LIVE_EXECUTION_UNQUALIFIED` 已移除。明確的手動命令在 Runtime 內沿既有 Draft／Preview／Confirm／durable claim 完成單次派送，不增加外部審批步驟；同 request 重複呼叫只回傳原結果。相同 request 改參數回報衝突；逾時、None、claim 後中斷及重啟都不自動重送。資金、可賣量、受理時間及價格限制由券商裁決，不把缺少本機資料當作券商已核准。

正式 US command 的 `trade_date` 是 UTC 本機送單日，僅作 Journal／intent scope；公開輸出標明 `date_basis=CLIENT_SUBMISSION_UTC`、`broker_business_date=null`，不將本機日期偽裝成券商營業日。既有 OFFLINE fixtures 與 TW v1 payload 不變。原 schema-v1 Journal 實作仍以獨立 US 檔案及 market/environment metadata 保存紀錄。台北／UTC 換日更新各市場的本機日期，不 logout 共用 session、不改寫歷史委託。

SDK 原始序號及委託書號延遲回報時，查單會從同一回傳 Trade 物件補齊；重啟後僅以已保存的原始序號復原，不能靠同商品、價格或數量猜配。`submission_status=RETURNED` 表示 SDK 已返回；`broker` 個別顯示券商狀態、操作與錯誤碼。缺少可信成交 ID／回報時區的資料仍保留未對帳，`filled_shares=null`；這些資料限制不再阻擋手動送單。自動策略未啟用，美股 UI/MCP 的完整操作介面另屬後續工作。

實作、隔離測試與正式 source 採用狀態見 [手動正式送單紀錄](../exec-plans/active/kgi-us-execution-20261105/ManualProduction.md)。前一次 2026-11-05 23:55 的 TSM 唯讀查詢證據保留於 [ReadonlyAcceptance.md](../exec-plans/active/kgi-us-execution-20261105/ReadonlyAcceptance.md)，不代表真實送單曾經驗收。

## 正式採用 checkpoint（2026-11-05 21:49，Asia/Taipei）

在使用者明確採用授權下，既有 Launcher 啟用 production Native、Backend 正常 restart、MCP 載入相符 build。21:39:11–21:49:52 的完整採樣維持同一 Native PID／creation、startup identity 與 session generation，首尾唯讀報表成功，沒有再出現 503；`keep_online=true`、strategy effects 關閉。這是該版本在該時窗的正式證據，非即時健康承諾；報表仍 PARTIAL，實際交易時段／台北跨日／真實送撤單尚未驗收。版本、收據、操作與剩餘界線見 [正式採用驗收](../exec-plans/active/execution-always-online-20261105/PersistentRuntimeLiveAcceptance.md)。

## Windows 收據發布（2026-11-05，Source／隔離）

Launcher 正常重開的真 Windows 子程序測試重現 Native 在發布 READY 收據時因 `ReplaceFileW / WinError 1175` 退出；這會讓原本已連線的 runtime 消失。本輪只修正原 `service.replace_receipt`：sharing violation（32）與原／新檔名皆保留的 1175 最多重試 0.5 秒；權限拒絕、1176／1177 等部分移動錯誤立即回報，持續衝突仍失敗。沒有刪除舊 receipt、忽略 ACL、另建 owner 或重送交易命令。

此錯誤來自本輪 synthetic fixture 的例外證據，尚不能認定為過去正式程序消失的唯一原因。[Windows ReplaceFileW 文件](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-replacefilew) 說明 1175 保留兩個原檔名，與部分移動錯誤的復原條件不同。原子發布與 owner identity 檢查維持；完整修正及採用界線見 [本輪驗收](../exec-plans/active/execution-always-online-20261105/PersistentRuntimeAcceptance.md)。

## Controller 失聯語意（2026-11-05，Source）

短命令 controller 在送出 Native command 後逾時，不能證明 SDK 未執行。`control.py` 將等待回應逾時分類為 `TimeoutError`；本機失敗回固定 `EXECUTOR_RESPONSE_UNKNOWN`，缺少 pipe 回 `EXECUTOR_UNAVAILABLE`，不輸出例外自由文字。Backend 只有收到附具體 Native code 的 `ExecutionRejected` 才當成已知拒絕；舊 controller 的無 code `ExecutionRejected` 也保守視為結果未知。

已 claim 的 staged 操作沿用 `SUBMISSION_UNKNOWN`／`CHECK_STATUS_DO_NOT_RESEND`，不因 client 退出、逾時或 Native 後來完成而自動重送、退回 STAGED 或建立替代 intent。readiness 階段的 exact-pin `NOT_ATTEMPTED` 規則不變。這是既有 controller／Backend 的局部分類修正，不新增 session owner、交易 store 或 lifecycle API；正式 loaded-source 採用與常駐驗收另記。

## Launcher 部署增量（2026-11-05，Source／隔離）

常駐部署的正式 owner 改為既有 mutex-owning OMI desktop Launcher：其 `Omi.RuntimeControl.Controller` 內 execution component 只建立／持有固定 `execution_runtime.launch --connect --supervise`，不重啟 supervisor、不管理 SDK。原 launch supervisor 繼續獨占 Native crash 恢復，`ExecutionRuntime/KgiSessionOwner/Journal` 不變。

既有同使用者 authenticated local pipe 提供固定 ExecutionStart／ExecutionStop／ExecutionStatus；短 client `scripts/omi-execution-control.ps1` 不啟動 Launcher 或程序樹，不取得遠端 HTTP/MCP authority。Start 冪等，保留原 SDK config bootstrap，策略 effects 關閉。Launcher 保留 spawn handle，另核對 `.venv` supervisor 及 `.venv-kgi` Native redirector 的 parent／birth／固定 interpreter image；READY 檔案、舊 PID 或過期 heartbeat 均不能宣稱服務在線。Launcher 的 RUNNING 只表示本代程序鏈，券商 connection 必須另讀原 Native status。

一次明確啟用保存 `runtime-control/<repo-hash>/settings/execution-preference.json` 的非秘密 keep_online 設定；它不是 UUID operation receipt／交易 store。下次正常 Launcher 啟動只採用一次。人工 Stop 先保存 false，再對原 startup id 提出 OFFLINE；正常 Launcher Exit 則暫停本代、保留下一次啟動意圖，且須原 supervisor 退出、所觀察 Native/shim handle 退出及兩個 OS lease 釋放。無法確認就不宣稱停止，不 force-kill。Launcher 意外消失由 supervisor 保留的 PID/creation handle 偵測並沿原流程停止，沒有第二 watchdog。

一般 Backend／Frontend Stop/Restart 和 MCP 生命週期不擁有 execution。Launcher 整體換版必須先人工 Stop，確認 STOPPED／keep_online=false；同 owner 的 PrepareUpdate fence 拒絕其後 Start，updater 不把 execution 納入 hard-cutoff tree。舊 owner 首次換版只能在原 Native/supervisor leases 都空閒且沒有新 preference 時交接。

正式舊 Launcher 不會熱載入新 component。首次採用須由 Reviewer 核對後經本機原桌面 Exit／重開載入，不能從 NORMAL 短命令建立 successor。本輪未操作正式 Launcher/Backend/Native、未登入或送撤單；隔離真程序與剩餘限制見 [部署驗收](../exec-plans/active/execution-always-online-20261105/DeploymentAcceptance.md)。OS 開機／正式長時連線仍待 Reviewer 驗收。Supervisor 自身 crash／SDK hang 不自動建立替代 owner，維持 UNKNOWN／人工核對。

## 常駐恢復 Source checkpoint（2026-11-05）

本節是新增 Source/Fake 能力；正式 Native／Backend／MCP 未部署，不能用歷史登入驗收替本版背書。完整分層證據與 task-only patch 見 [本輪驗收](../exec-plans/active/execution-always-online-20261105/Acceptance.md)。

- `launch --connect --background` 保留一個同 checkout OS lease 保護的 supervisor。只在已觀察 child 非預期退出、取得該 child 的有效啟動 receipt、再次證明 Native lease 已釋放時恢復。stop／fatal／未知 owner 不重啟；不新增 Windows service、排程或交易 store。
- `launch --stop` 可在 child 的 pipe 尚未出現或 crash backoff 期間保存 exact supervisor 的 OFFLINE 意圖；只有該 owner 的 exact request ACK 才算接受，STOPPED 另需 child exit 與 lease 證據。無 ACK 是 UNKNOWN。
- `ExecutionRuntime` 是唯一 session 恢復迴圈；`KgiSessionOwner` 仍序列化所有 SDK IO。disconnect callback 只標記事件；TW 跨日關閉舊 session／重綁新日期，沿同 Journal replay/reconcile，歷史 intent 不改、不重送 UNKNOWN／部分成交。每 60 秒有界 health read；空報表／無行情不是斷線。
- transport failure 與 report/schema failure 分開。退避為 5–300 秒並帶 jitter；已取得 handle 且 cleanup 成功的 transient 可恢復。SDK constructor 未回傳 handle 的失敗是 `KGI_LOGIN_OUTCOME_UNKNOWN`，不假定無 session。fatal/config/auth/close unknown 留人工介入。
- status 純讀 connection 投影，含 desired/actual/binding/date/busy/last broker read。pipe 保留 status/stop 容量；正常命令會等待同一 SDK lane，不讓 heartbeat 競態產生額外 staged rejection。GET readback 保留原 session 即時唯讀查詢及來源品質，不改為無刷新快照。
- Backend 前置狀態檢查已結束且 exact Candidate id/revision/digest 仍未 claim 時，才在實際 ASGI `error.detail.submission_attempt` 回 `NOT_ATTEMPTED`；latch 後沿用原 UNKNOWN／不重送。見 [InterfaceContract](../exec-plans/active/execution-always-online-20261105/InterfaceContract.md)。

本 checkpoint 的正式市場為 TW／Asia/Taipei；新增 US Source slice 的限制見本頁上方，尚未正式啟用美股下單。Supervisor 自己的 crash／OS reboot 不自動恢復，SDK 不可中止時只呈現 busy/unknown，沒有 force-kill 或第二個 watchdog。

## Current native owner boundary（2026-10-30）

原生接線使用同一 `ExecutionApplication → ExecutionRuntime → KgiSessionOwner` 與 schema-v1 Journal。USER_SPACE／AGENT_SPACE 是同一交易路徑的 provenance，不是兩個 broker 或持倉帳本。Entry 只有持久化 exact Preview／Confirm 後才能 claim／submit；UNKNOWN 不重送，精確 cancel 與可修改策略仍委派原 Runtime。

- `execution_runtime/launch.py` 是 OMI-local config bootstrap：沿用 OMI `.venv` 已安裝的 dotenv parser，以 `.env`、`.env.runtime`、process env 的既有優先序挑選 KGI 設定，只透過 child environment 交固定 `.venv-kgi`。不 import research Backend，不讀其他專案設定，沒有新 secrets store。
- `execution_runtime/__main__.py` 是唯一 native composition root：明確 `native --connect` 才登入，先持有固定 `data/execution-runtime/native-session.owner` OS lease，再 discovery account。factory 要求 held lease；prepared binding 交既有 KgiSessionOwner，不再次登入。啟動器不用 force-kill，等待 child 自行 close／logout。
- `execution_runtime/native.py` 只負責官方 SDK import／login、與既有 OMI quote bridge 相同的證券 account selection、能力檢查及 `SessionBinding`。SDK order IO／callback 全由 `kgi.py`，transaction／reducer 全由 `runtime.py`；factory 不送單、不查交易、不建立 ledger。
- `execution_runtime/headless.py` 是有界 stdin JSON-lines transport，使用原 `cli.py` typed routes；沒有 HTTP／MCP／UI。回應保留 review、revision、digest、request、intent、execution 與 Space；account 用 SELECTED alias，私有 journal rows 不輸出。
- `service.py/control.py/ipc.py` 為同一 Runtime 的薄 Windows local pipe transport。雙向驗證同 OS user，拒絕 remote／未知 caller，bytes JSON 不反序列化 pickle。控制程序離開後 detached runtime 繼續運作；stop/reconnect 委派原 owner，不加 manager、broker 或 ledger。source pin 是資訊性驗收證據，磁碟 source 修改不封鎖已載入程序的任何既有命令。
- 唯一環境切換為官方 `KGI_SUPERPY_SIMULATION` bool，無 fake native 模式。固定 simulation／production journal 分開保存於 OMI `data/execution-runtime/`；無任意 journal／root CLI override，不碰 OMI production DB。原 M1／M2A manifests 與 synthetic contract 不變。
- Native 入口預設不啟動 strategy effect pump。明確 `--enable-strategy-effects` 才允許已同意的 CASH long 策略恢復；規則仍可修改。已有策略才透過同 session 的 Quote `subscribe_all/set_cb_all` 訂閱對應 lot；14 位台北事件時間、5 秒 freshness、formal trade 與成交量前進為 price admission。正常 tick 只更新 Runtime 價格投影，只有首次 SL/TP 觸發才保存 evidence/target；同一 pure `price_trigger` 服務 replay 與 admission。不接受 caller 任意 price 代替 native event，不新增市場 cache owner 或 AI 自動確認。
- 安裝版 2.1.0 `set_Account` 只公開 `Account.ExecReport`，adapter 保留實際來源名稱；有 `Order.ExecReport` 時用原介面。Account report／full trades／ExecReport 始終經同一 session owner。history completeness 仍不能由 SDK cache 推定。
- Native binding 以台北日期限制使用；本節原 10/30 checkpoint 需人工換日，11/05 managed Source 已在原 owner 加入上述自動換日。舊日 command 仍受日期檢查，不重送。

Source／隔離 tests／Native Import 分開驗證。2026-10-30 正式 Session、account selection、readonly query、logout/reconnect、detached process 與 controlled stop 已有實機 evidence；callback registration 已驗證，Order/Deal 真事件仍未觀察。官方 simulation 為 `BLOCKED / KGI_LOGIN_INCOMPLETE`。沒有實際買賣／撤單，沒有指定新實單參數，Live Order 仍 NOT_SENT；native SL/TP source 尚未收到合格事件，不宣稱保護生效。固定 lease 不是跨 checkout／跨機帳戶鎖；SDK native file logs、call hang、新 session history completeness 仍是限制。

操作與停止／回退：[NativeOperations](../../execution_runtime/NativeOperations.md)。本輪命令、scoped diff、基線與限制：[Progress](../exec-plans/active/live-execution-plane-20261029/Progress.md)。機械限制只為 native import/login/config launch 新增精確 owner；不放寬其他 plane 或取消既有 safety rules，無新增 debt。

## 以下為 Phase 0–4 歷史 checkpoint

2026-10-29：Phase 0 owner reconciliation 與 Phase 1 fake/offline substrate 已實作。Source／fake acceptance 與正式 Runtime、Broker Session、Live Order、Native Callback、Product acceptance 分開；後五者本輪沒有執行。

## Owner／reuse 決策

| Surface | 精確 Source 路徑／owner | 決策與界線 |
|---|---|---|
| Pure domain／共用 order reducer | `execution/order_reducer.py:reduce_order` | 從原 `state_machine.transition` 抽出相同狀態規則，pure stdlib、無 IO／implicit clock；M1 和 execution runtime 共用，沒有第二份 live business reducer |
| M1 synthetic contract／admission | `execution/contracts.py`、`execution/validation.py`、`execution/state_machine.py:transition` | contracts／admission 未改；wrapper 保留 `SimulationEvent`／`SIMULATED_*` 與原 caller 行為，不把真事件偽裝 synthetic |
| M2A transaction／outbox／audit／settlement | `execution_simulation/application.py:SimulationApplication`、`storage.py` | 只保留 synthetic owner；不開放真 SDK 注入、不使用它的 SQLite 保存 broker facts。借用 durable claim → effect outside transaction → receipt 的工作方式，不搬 factory token／synthetic resource accounting |
| Gateway／headless／qualification | `execution_simulation_gateway/`、`execution_broker_preflight/`、`execution_kgi_simulator/`、`execution_manual_mock/` | 原限制保留；fixture normalizer、policy snapshot、native containment 不是 live application owner，也不能變成一般 execution transport |
| Persistent execution intent／order／fill／event | `execution_runtime/runtime.py:ExecutionRuntime`、`storage.py:Journal` | Runtime 唯一命令和 transaction owner；Journal 只有 schema／codec／connection／lease。獨立 execution SQLite，不寫 OMI DB、不共享 M2A ledger |
| Broker session／submit／query／exact cancel | `execution_runtime/kgi.py:KgiSessionOwner` | 唯一 injected session；operator 明確 start，SDK calls 串行，callback 不持 SDK transaction；不 import SDK、不 login、不讀環境／CA |
| Callback normalization | `execution_runtime/kgi.py:callback_observation/report_observation` | vendor labels、日期／單位／來源歸一；不選策略、不操作 DB、不執行 reducer |
| Correlation／reconciliation | `execution_runtime/runtime.py:_bind/_ingest/_apply/_reconcile_snapshots/verify` | account/date/order ID 綁定、durable fill IDs、共用 reducer、journal replay。無法精確綁定就保留 UNKNOWN／external；不靠交易外觀猜配 |

不採 `execution/live/`：原 `architecture/execution-constraints.toml` 與 M1 AST test 會遞迴要求整個 `execution/` 無 IO，且 `SimulationEvent` 有不可變 synthetic 標記。為放 IO 加 manifest exception 會模糊既有 package promise。使用最小 adjacent `execution_runtime/`，原 M1/M2A constraint／debt manifests 完全不變；新 [runtime constraints](../../architecture/execution-runtime-constraints.toml) 與 [空 debt](../../architecture/execution-runtime-debt.toml) 保護新 owner 與未接線邊界。

## v2.7 的可繼承與不可搬入範圍

唯讀 reference：`C:\work\KGI\manual-order-test-v2\kgi_manual_orders_v2.py`，SHA-256 `a8f8e8ec78abe379534cfca2d314e78971eec6a3ab1b22d561b8fd5ff8923f21`。實盤驗收是使用者提供的歷史 evidence，本輪沒有重新執行或讀取私有成交／真 journal。

繼承 `create_order` 的 Action／OrderCond／OddLot／ROD／qty／price call shape，CASH Odd、MARGIN Common、CASH_SELLING Common、SHORT_SELLING Common。shares 為 application 單位；Common 的 unit 必須由 command 明確給定，沒有把 preset 的 1000 當所有商品預設。LIMIT Decimal → native price 檢查不得失真；不順手擴充 MARKET、IOC、FOK、借券或信用反向 mapping。

繼承 durable claim-before-send、exceptions／timeout 不重送、`Trade.operations.NewOrder.Failed` 拒單、每次 full cache query、invalid bucket 分離、Account report 與 SDK cache 分開、精確 order ID cancel、ACK 不當 cancellation final、撤後再查。歷史已撤單不以「同商品同價格」阻擋新 intent；原 intent 的 UNKNOWN 仍不可重送。這裡以 durable intent identity 替代測試 preset 的經濟欄位 duplicate scan，不新增第二份 preflight。

不搬硬編碼商品／價位／cutoff、preview CLI、`.env`／CA/login、單次測試 Journal、preset ownership、process launcher／live execute switch。Phase 1 不含價格區間、交易時段、額度或 review／confirmation。Phase 2 只新增 typed command 與 exact snapshot workflow；市場／信用／額度 risk admission 仍未驗證，不假裝已具備實盤前置條件。

SDK 2.1.0 source 只做文字讀取：`trading/Order.py` 的 `set_event`、`_OnOrderReport`、`_OnExecReport`、`OrderReport`、`ExecReport`，及 `_trade_base.py`。`Task.Deal` 可沒有 status，quantity 是本次 deal 增量，`seqno` 對應 CNT；Trade 的 deals 不保留可靠成交 ID，因此不能只 sum cache 就創造 journal fill。

## Durability 與 reconciliation

```text
Explicit operator / injected session factory
  -> ExecutionRuntime (one canonical journal lease)
      -> durable command claim (commit)
      -> KgiSessionOwner SDK call (outside transaction)
      -> normalized observation / stable broker identity
      -> immutable observation + fills + journal
      -> execution.order_reducer.reduce_order
      -> orders projection (same transaction)
```

Journal 是獨立 application ID／schema v1 的 SQLite（WAL／FULL synchronous）。intent、journal、observations、fills、applied facts append-only；mutable orders projection 在 startup 先用 journal facts 經共用 reducer replay 驗證。未知 schema／foreign DB 不自動 migration。這不是硬體斷電、備份還原、惡意 OS 管理者防竄改或高吞吐驗收。

Claim 後 crash 有 0 或 1 次外部 effect 的不確定窗口，沒有 exactly-once 宣稱。無 ID claim 永不因 query empty 重新送；已返回且 durable 綁定的 ID 才能跨 process 沿原 identity 恢復。外部單保留 USER_SPACE context 和 source channel evidence，不建立第三個策略空間，也不分割真持倉。

撤單不重新確認；用已綁定的 account/date/order ID，送前僅檢查 SDK exact cache entry，無 cancel-all 或 account-wide round trip。Cancel ACK 保持 pending；D report 的剩餘量為零可套用取消，後到成交仍留在原單。Reconciliation 另比 dated Account report、SDK totals 和 journal fill identities；缺 callback／缺 cache／不一致保留 `reconcile_required`。

`reconcile_required=false` 是該次可取得證據相符，非歷史完整性宣告；`fill_history_complete=false` 保持明示。原生新 session 是否回補所有 ExecReport、CNT 唯一性、成交 qty unit、跨日／重連 callback、native timeout 與 session closure，都仍需獨立驗收。

Account／ExecReport 的逐列 normalization 失敗由 `QueryBatch.diagnostics` 分離；query 回 `PARTIAL`、`invalid_report_count` 與診斷，仍 ingestion 同批有效 order／deal。診斷含 source、零起算 row index、reason、可解析日期／account match 狀態及 allowlist 原值字串（保留空白／null／錯誤碼），由原 Runtime transaction owner 寫入 immutable journal 的 `REPORT_ROW_QUARANTINED`，不進 observations／fills／external orders。帳戶／個資欄位及自由文字 ErrMsg 不複製；沒有新 store 或 schema migration。

`OrderNo=0000`、缺 ID／symbol／fill ID、缺失或不合法時間，以及 `ErrCode` 缺失／非 `0` 均不能成為成功 order fact。不針對 MAT0095 特判；完整失敗回報也只代表一次失敗動作，隔離保留原值，不用它宣告目前委託已拒絕／已撤或零成交。既有直接 `Trade.operations.NewOrder.Failed`／callback 拒單路徑不變。SDK 的 `C=UpdateQty`／`M=UpdatePrice` 語意已靜態核對，但 Phase 1 未支援改單 reduction，因此與未知 OrderFunc 一起明確隔離。

診斷若可能涉及同 broker order number／account／date，該筆保留 `reconcile_required`，不以較舊有效報表和 cache 抵銷疑義；日期或帳戶 cell 讀不出來也保留疑義。已知不同 account／date 的列不污染目前委託，無 ID 的拒單不靠經濟欄位猜配。未涉及的有效委託仍可正常 corroborate。API／session／table schema／cache 失敗及未預期的 parser exception 維持 `UNAVAILABLE`；`PARTIAL` 不是成功空帳戶。證據仍只涵蓋本次可取得內容，沒有提升 Native／Live acceptance。

## Runtime／產品邊界

原 Backend／Frontend／launcher 沒有 import、啟動或管理本 runtime；沒有 MCP／HTTP／AI trade entry。canonical journal 路徑由 operator 固定，OS lease 防止同路徑同時兩個 owner；不宣稱防止不同 journal／不同機器對同帳戶另開 session。這項 deployment invariant 尚未 runtime/adoption 驗證。

Phase 2 預審／確認與 Phase 3 mutable strategy 已實作 source/fake 路徑，見下節；Phase 4–5（Order Desk UI、MCP）未開始。`Command` 上的 USER_SPACE／AGENT_SPACE／strategy／revision 是 lineage；confirmation 由 workflow record 選取 exact snapshot，不是身分驗證。策略不進入 broker adapter。

實際測試結果、執行命令與 rollback 見 [Phase 1 驗收](../exec-plans/active/live-execution-plane-20261029/Phase1-Acceptance.md)；進度見 [Progress](../exec-plans/active/live-execution-plane-20261029/Progress.md)。


## Phase 2：同一 owner 下的預審／確認

| Surface | Owner 與限制 |
|---|---|
| Typed proposal／snapshot／workflow replay | `execution_runtime/review.py:Draft/snapshot/replay`；pure、無 IO／clock acquisition／order reducer；兩個 space 及 owner/source provenance |
| 正常 client application | `execution_runtime/application.py:ExecutionApplication`；無 raw submit、無 DB／SDK ownership，所有 workflow command 委派原 runtime |
| Workflow transaction／recovery | `ExecutionRuntime:create_review/preview_review/revise_review/reject_review/confirm_review`；原 `_transaction`＋Journal；同一 pure replay 驗證 append 與 startup |
| Headless parser | `execution_runtime/cli.py:run`；只轉 typed args 至 canonical application；無 session factory／live default |
| 可執行 local harness | `execution_runtime/tests/review_cli.py`；只在明確 fixture directory 注入 Fake SDK，不是 production service path |

所有 review records 使用既有 schema-v1 journal 的 `REVIEW_*` kinds，payload 明確 `review_version=1`；不新增 table、DB owner 或 migration。未知 record version／event 與 corrupt snapshot 在 session factory 前拒絕。`review_id` 穩定綁定 account／intent，`review_revision` 在成功 Revise 時遞增；command strategy revision 仍是另一個 lineage 欄位。

Preview 固定完整委託、owner/source、revision、timestamp、digest。正常 `submit()` 拒絕 raw command；唯一 application confirm 驗證 persisted Preview 的 expected digest／revision，先持久化 CONFIRMED，再呼叫原 private engine `_submit_engine`。SUBMIT_CLAIMED 與 REVIEW_EXECUTION_CLAIMED 同 transaction，只一個 broker attempt 上限；adapter 的 mapping／query/cancel／callback 和原 order reducer 不變。正常 clients 不可自行建立另一個 DB/session 或呼叫 private engine。

CONFIRMED／未 claim 的 crash 後不自動送；相同 exact confirm 明確重試才能繼續。Claim 後 crash／UNKNOWN 不重送，無 ID 不以經濟欄位猜配。status/list 純本機 read；query 明確保存 evidence；exact cancel 不需再次確認並保留完整 broker key。Workflow `EXECUTION` 不等同 broker ACCEPTED。

已確認 command snapshot 固定，strategy 不 frozen；可修改 runtime、SL/TP 及暫定 edit policy 由下節 Phase 3 負責。Source／Fake 驗證不提升 Native／Live／MCP／UI acceptance。Phase 2 歷史測試與 rollback 見 [Phase 2 驗收](../exec-plans/active/live-execution-plane-20261029/Phase2-Acceptance.md)。

## Phase 3：原 Runtime 內的 mutable strategy

| 責任 | 唯一 owner 與界線 |
|---|---|
| StrategyRules／SourceSnapshot／revision／target replay | `execution_runtime/strategy.py`；pure、無 IO／clock／DB／SDK，策略狀態來自原 Journal records |
| Strategy application commands | `ExecutionApplication`；create、revise、exit/reduce、explicit price observation 與純 status；沒有新 transport |
| Target ownership／quantity reservation／child claim | `ExecutionRuntime` 原 `_transaction`；target latch 與 `SUBMIT_CLAIMED` 皆在相同 Journal，child claim 與 `STRATEGY_EXIT_CLAIMED` 同 commit |
| Broker effects／callback coordination | `ExecutionRuntime` 擁有一個 effect pump；callback ingest 後只喚醒，所有 SDK call 仍經原 `KgiSessionOwner` |
| Order／fill truth | 原 orders／observations／fills／shared order reducer；沒有第二個 broker ledger 或策略持股 allocation store |

`STRATEGY_*` records 使用 `strategy_version=1`，沒有新增 table／schema migration。每次 append 與 startup 使用同一 pure replay；startup 在 session factory 前驗證 source digest、revision、已確認 review lineage、child engine claims 及 claim 當時的實際 entry fills。策略 status 在同一 read snapshot 讀取 Journal 與 order/fill projections。

`create_strategy` 對已確認有 lineage 的 Entry 保存 mutable policy 和既有策略 consent。Phase 3 暫定 `MUTABLE_REDUCE_EXIT_V1_PROVISIONAL` 允許 SL／TP／退出限價修改、減碼與退出；增加曝險或新 Entry 仍需新的 Preview／Confirm，當前一個 instance 綁一個 Entry。修改 strategy 不重寫已送 command 或 review snapshot。

保護量由 entry fills 減 exit fills 得出。所有已 claim exit 的未成交量均持續 reservation；target0 時新 child 只補 `effective - reserved` 的正差。多個 Stop／TP／Manual trigger 以原 transaction 取得第一次 target ownership，後續 target 只能降低。取消未成交 Entry 不需新確認；Cancel ACK 不作 remaining=0。Late fill 繼續驅動新 child，CLOSED 必須 entry remaining=0、effective=0、reserved=0 且現有 evidence 相符；後到實際 fills 仍可重開 reconciliation。

Crash 後，已持久化的 target 可根據新的 broker evidence 產生尚未 claim 的減碼；已 claim／UNKNOWN 的 child 永不 replay。`UNKNOWN`、cancelled 或 rejected child 保留 reservation 並顯示 `unresolved_exit_claims`，不藉換 intent ID 回收容量或造成無界 retry。這保證對已接受 fill lineage 的派送量上限，並不保證限價會成交或失聯期間可平倉。

目前 executable strategy capability 為 CASH long＋LOCAL_SYNTHETIC SL／TP，Native price input 只收同 Session 的 qualified quote callback；沒有 broker-native stop 或信用反向 order mapping。明確新日 Session 採用原 Journal 時，舊策略可繼續訂閱／修訂／退出；immutable Entry 與 review 不改，child trade_date 使用當日，replay 依 claim 的台北日期重建驗證。舊日 ROD 餘量／UNKNOWN 不當成今日可撤單，也不因新 Session 自動重送。

現股上限仍由原 KgiSessionOwner 讀 `Account.InventorySum(B)` 與 account order report，Runtime 使用既有 Journal reservations 做 account／symbol 層級扣抵，跨 Space 不分池。`max(NETQTY0,NETQTY9,0)` 沿用 OMI holdings 正規化，margin／short 不混入；這不是已證實的 sellable quantity。現有 SDK 沒有清楚的 SALEQTY deduction／as-of／完整性契約，因此保留 `UNVERIFIED` 與 `report_complete=false`，只派送不超過已知保守上限的部分。庫存 query／SDK send 串行，child effect 前再次查核；相同 broker key 的 pending sell 與 reservation 取較大佔用量而非重複加總。無完整數量單位或同 Symbol 疑義資料保留未知；無關 invalid row 逐列 quarantine，不令全帳戶不可用。沒有新 Ledger／position table 或 external_orders 推定持股。

`SUBMIT_NOT_SENT` 是原 Journal 新增的 pre-effect 證據，只有 SDK owner 在呼叫 create_order 前回報才能記錄；local REJECTED／NOT_SENT、0 SDK attempts，釋放該 reservation，但 immutable intent 不能重送。新 revision／operator request 才可建立下一 child；SDK exception 後 UNKNOWN 仍永久保留原 claim／reservation。verify 檢查 claim 順序、跨日日期、未送出證據與後續 claim 的數量守恆。Schema v1 不變；舊 reader 不可覆寫新事件。

觸發與成交分開顯示，LOCAL_LIMIT_ROD 不保證成交；`protected_quantity` 的 basis 為 strategy fill lineage，`protection_guaranteed=false`。真 broker fill finality、手機同時操作競態、跨日實盤成交／callback 與完整可賣語意仍未驗收，來源／測試／實機唯讀與 Live Order 分開。

Constraint manifest 已對 pure strategy、client claim bypass 與 adapter→strategy import 加 guard；debt 仍空。原 M1/M2A manifests、shared reducer、KGI parser／session owner、schema 均未改。Source/Fake 測試及正式 Runtime／Native／Live／MCP 的分界見 [Phase 3 驗收](../exec-plans/active/live-execution-plane-20261029/Phase3-Acceptance.md)。

## Phase 4：Order Desk 的 Source／Fake projection

獨立 Next route `/order-desk` 使用 scoped components／CSS 與 `frontend/src/lib/order-desk/contract.ts`。前端只保存選定單、表單、pending/error 與讀取快照；確認 selectors、策略 revision、order/fill 狀態與 timeline 來自 canonical Application／Runtime。沒有 UI reducer、position allocation store、原市場首頁重構或普通 Backend execution route。

`/order-desk/transport` 是明確啟用的 fake preview seam：未設定 `OMI_ORDER_DESK_FAKE_PORT` 回 503；設定時只使用固定 loopback host，POST 先辨認 `omi.order-desk.fake.v1 / FAKE_ONLY / NOT_DEPLOYED`。`execution_runtime/tests/order_desk_server.py` 只注入既有 FakeSession、固定虛構帳戶／日期與每個 session 的臨時 Journal；所有 review、confirm、cancel、strategy commands 都委派原 `ExecutionApplication`。Fake scenario buttons 只注入 fabricated callback／query evidence，沒有平行策略規則或假造完成回覆。GET/read 不 query broker；query 為明確 POST command。

確認仍需 exact review_id/digest/revision；Revise 產生新 DRAFT 並要求新 Preview。取消不二次確認且必須 exact account/date/order_id/execution_id；ACK 不代表 final，UNKNOWN identity 不猜配、claim 不重送。LOCAL_SYNTHETIC 不是 broker-native stop，也沒有持續行情或成交保證。未部署 live transport、Native／Runtime Adoption／Live／MCP 均 UNVERIFIED。這個 tests-only seam 不改既有 runtime constraint／debt 或 ordinary startup 邊界。UI Source/Fake 驗收與回退見 [Phase 4 驗收](../exec-plans/active/live-execution-plane-20261029/Phase4-Acceptance.md)。


## AGENT_SPACE ???????2026-10-30 Source checkpoint?

Candidate/Pending ??? owner ?? Backend `app.research.candidate_service`??? additive 0095 Research revisions?? ExecutionRuntime Journal ?? broker intents/orders/fills/strategy reservation ??? owner?Backend ? import execution_runtime??? OMI control CLI ?????? local named pipe ? ExecutionApplication?

?? Backend scheduler ?? Candidate Monitor????? worker standalone ???canonical quote/technical ??? KGI session ????? TRUE ???? Pending???? Native Draft/Preview??????? approve ??? Confirm??? AI_PASS ???????? write txn ????????IPC??????durable preparation/selection ? invalidation receipt ??? Owner lineage?

Native immutable candidate backlink ??? Candidate store?Long ????? Entry claim ??????? Strategy???? fill ? Exit ?? effect pump ??????effects ??????????broker fill ?????Short Cover mapping ??????? Source/isolated tests??? migration?Monitor/Native loaded source ? Live ???????????? ConditionalCandidatePlan.md ?12?
