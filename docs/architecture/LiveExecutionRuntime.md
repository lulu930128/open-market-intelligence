# Dedicated Execution Runtime（原生 headless 接線）

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
- Native binding 以台北日期限制使用；跨日後拒絕新 draft/confirm、SDK IO 與 callback admission，不自動切日或重送。

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
