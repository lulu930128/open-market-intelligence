# Execution Runtime／原生 KGI headless 入口

獨立的 execution source package。原生操作入口見 [NativeOperations.md](NativeOperations.md)：使用 OMI 現有設定、`.venv-kgi` 與官方 `KGI_SUPERPY_SIMULATION`，單一 stdin 程序內共用 `ExecutionApplication → ExecutionRuntime → KgiSessionOwner`。Import／help 不登入；只有明確 `--connect` 才登入與查單，Entry 只在 exact Confirm 後送出。策略 effects 預設停用，修改規則仍可保存。

2026-10-30 已驗證正式 broker login、唯讀 account/order/deal query、正常 reconnect/stop 與獨立背景 Runtime；兩 Space 的 headless commands 共用既有 Application／Runtime。Order/Deal callback 只確認註冊，真事件及實單送出／撤單仍未驗收；原生行情接線已測試，但目前沒有 qualified trade 或已啟用的 SL/TP 保護。官方 simulation probe 為 `BLOCKED / KGI_LOGIN_INCOMPLETE`。最新部署 PID、Loaded Source 與分級證據見 [Progress](../docs/exec-plans/active/live-execution-plane-20261029/Progress.md)。以下 Phase 1–3 段落保留歷史設計與測試說明；其中 fake harness／當時沒有 native factory 的描述不是目前操作方式。唯一正式環境切換為官方 SDK simulation 設定，不提供 fake native runtime。

## Source of Truth

| 責任 | 唯一 owner |
|---|---|
| Pure order-state reduction | `execution/order_reducer.py:reduce_order` |
| 原 M1 synthetic admission／envelope | `execution/validation.py`、`execution/contracts.py`、`execution/state_machine.py` wrapper |
| 原 M2A synthetic transaction／settlement | `execution_simulation/application.py`，不接入本 package |
| Execution command／transaction／recovery | `execution_runtime/runtime.py:ExecutionRuntime` |
| 專用 schema、codec、OS lifetime lease | `execution_runtime/storage.py` |
| KGI session／mapping／callback normalization | `execution_runtime/kgi.py:KgiSessionOwner` |
| Intent／request／broker identity contract | `execution_runtime/contracts.py` |

`intents`、`journal`、`observations`、`fills` 是 immutable facts；`orders` 是同 transaction 更新且可經同一 reducer replay 驗證的 projection。這個獨立 SQLite 的 application ID 為 `0x4F4D4558`，schema v1；不是 OMI production DB，也不是 M2A ledger。新檔建立 schema，既有外來 DB 或未知版本直接拒絕，不自動覆蓋／migration。

## 執行語意

- Phase 1 內部 primitive `_submit_engine(Command)` 先 commit 唯一 `(account, request)`／`(account, intent)` claim，再離開 transaction 呼叫 adapter。重送同 payload 回原 receipt，變更 payload 或換 request 重用 intent 為 conflict。
- `submit_claims=1`／`broker_attempts_max=1` 是 at-most-once 上限。claim 後、SDK call 前 crash 時實際 broker attempt 可能是 0；不能宣稱 exactly-once broker execution。
- `execution_id` 由 account／intent 決定；broker key 為 account／trade date／order ID。ID 只接受 SDK 返回的對應 Trade 綁定，不靠同商品／價格猜配。無 ID 的 UNKNOWN 不自動重送，也不自動領養外部單。
- `Command` 的 space／strategy／revision 保留 opaque lineage；broker engine 不知道 TP／SL、策略或資源配置。Phase 2 workflow 由上層 `ExecutionApplication` 呼叫原 runtime owner，正常 `submit()` 拒絕 raw command。
- `status()` 是純本機 read；`query()`／`reconcile()` 明確讀 `Account.OrderReport()`、每次 `Order.get_trades(True)`、`Order.ExecReport()`，並保存 evidence。重複 query 真的重新取得這些來源，不以先前 response 代替。
- Callback 先固定欄位並 durable 入 journal，再按 broker key 關聯。SDK IO 外不持 application transaction lock，支援 SDK 在 submit 內同步／另一 thread 回呼。
- `Task.Deal` 的 `status=None` 合法；增量以 `(account,date,order,CNT)` 去重，跨 callback／ExecReport 使用同一 fill key。亂序成交仍累加；同 ID 異內容、overfill 不更新 fill projection，保留 unresolved observation。
- `cancel(execution_id, BrokerKey)` 沒有再次確認；只 dispatch 精確 ID，送出前核對該 session cache 的完整 order identity。`CancelOrder.Success` 只記 ACK，成功 D report 才表示剩餘委託已撤；partial／late fills 繼續套用共用 reducer。沒有 cancel-all。
- Startup 取得同一 canonical journal 的 OS lease、replay 驗證後才呼叫 session factory；abandoned claims 不重新送。Reconnect 先關閉舊 session，再建立新 session 並查單；logout exception 保留 lease，不建立第二個 session。
- 外部手機／CLI broker 單以 `external-<broker-key-digest>` 穩定識別，保留 USER_SPACE context；不製造策略、intent 或獨立持倉池。原 callback 在內部 bind 前暫列 external，bind 後保留歷史但不再呈現為外部單。

## Reconciliation 的限度

`reconcile_required=false` 只代表該次 dated account report、SDK snapshot 與具成交 ID 的 journal fills 相互吻合；receipt 的 `fill_history_complete` 仍為 `false`。它不代表 broker history completeness 或 live acceptance。Account report／cache 缺列不推定沒有單；SDK total 大於 journal fills 時不憑空補成交。

`Order.ExecReport()` 是 SDK 收到的回報集合。原生新 session 能否回補所有歷史成交、`CNT` 在各種 session／日期的唯一性、Deal quantity unit、callback 在 reconnect／跨日的時間語意，仍需 native qualification。Fake fixtures 提供明確 fabricated history，因此可測 crash recovery，不能替代券商證明。

Canonical journal 路徑由獨立 operator 固定；lease 只保護相同 resolved path，不是跨機／跨不同 journal 的帳戶鎖。此階段不提供 account journal 遷移、跨日自動換 session、原生 timeout supervision 或 service 安裝。不得同帳戶另開不同 journal 當繞路。

## 可執行的 offline 驗證

Repo root，使用現有 `.venv`，不需新 dependency：

```powershell
.\.venv\Scripts\python.exe -B -m execution_runtime.tests.offline_demo
.\.venv\Scripts\python.exe -B -m unittest discover -s execution_runtime/tests -t . -q
```

Demo 在 `execution_runtime/tests/` 下建立／清理專用 temporary fixture directory：同命令重送 → 一次 fake submit → 漏 callback → 重開 journal → 恢復 partial fill → 精確 cancel → 再查單。`test_process.py` 另以真 child process 和 `os._exit(73)` 測 crash 邊界。沒有 native SDK／broker effects。

完整驗收、命令、未完成項目與 rollback 見 [Phase 1 驗收](../docs/exec-plans/active/live-execution-plane-20261029/Phase1-Acceptance.md)；owner 決策見 [current architecture](../docs/architecture/LiveExecutionRuntime.md)。


## Phase 2 正常 client 路徑

`ExecutionApplication` 只提供 `draft/preview/revise/reject/confirm/list/status/query/cancel`。`Draft(Command, owner_id, source)` 是 typed input；USER_SPACE 接受 MANUAL／MOBILE／LOCAL_STRATEGY，AGENT_SPACE 接受 AGENT_PROPOSAL。兩個 space 共用同一 broker pool；space 是意圖／來源 lineage，沒有分割真實持倉。

Preview 由原 Runtime transaction owner 寫入既有 schema-v1 immutable journal，record 為 `review_version=1` 的 `REVIEW_*` events，沒有新 schema／store／migration。完整 command、owner/source、review revision、timestamp、LIMIT／ROD／quantity unit 都在 SHA-256 snapshot 中。Confirm 必須傳 stable review_id、expected digest、expected review revision；Revise 成功後舊 Preview 失效，Reject 不可再確認。

`ExecutionRuntime.submit()` 一律回 `CONFIRMED_REVIEW_REQUIRED`；原 `_submit_engine` 是 private Phase1 engine primitive，保留給 engine fixtures 和唯一 confirm path，且不能繞過既有 review identity。正常 client 不拿 engine/session，沒有 raw submit route。這是 workflow／owner boundary，不是 auth、2FA 或 approval server。

確認與 claim 分別 commit。CONFIRMED 但尚無 claim 的 crash 重開不自動送單，只有相同 exact confirm 的明確重試可繼續；claim commit 後永不再次 submit，UNKNOWN／無 ID 只保留 evidence／reconcile，不猜配或 resend。`EXECUTION` workflow state 表示 claim 已存在，broker order state 另外呈現。`status/list` 不做 broker IO 或 journal write；`query` 明確取得並保存 broker evidence；`cancel` 直接用完整 exact broker identity，不重新確認。

固定的是已確認的 command snapshot。`review_revision` 與 strategy `Command.revision` 分開；沒有把已確認 strategy frozen。Phase 3 的可修改策略與本輪暫定 exposure policy 見下節。

Headless parser：`execution_runtime.cli.run(application, argv)`。可執行的 fake-only harness：

```powershell
.\.venv\Scripts\python.exe -B -m execution_runtime.tests.review_cli --directory <專用fake目錄> list
.\.venv\Scripts\python.exe -B -m unittest execution_runtime.tests.test_review execution_runtime.tests.test_review_process -q
```

Harness 只注入 Fake SDK，拒絕非空未標記 fixture directory，沒有 live/native factory。Phase 2 route 與歷史驗證見 [Phase 2 驗收](../docs/exec-plans/active/live-execution-plane-20261029/Phase2-Acceptance.md)。Native／Live／正式 runtime adoption／MCP／UI 均 UNVERIFIED；Phase 4–5 NOT_STARTED。

## Phase 3 可修改策略與保護數量

`ExecutionApplication` 新增 `create_strategy/strategy_status/revise_strategy/exit_strategy/observe_strategy_price`，仍只委派 `ExecutionRuntime`。沒有新增 CLI route、MCP、UI、session 或 DB owner。`strategy.py` 只有 typed contracts、pure replay 與由 canonical order facts 計算的 projection；不保存另一份 broker position／fill ledger。

1. 用既有 Draft → Preview → exact Confirm 建立有 `strategy_id/revision` 的 CASH Buy Entry。
2. `create_strategy(review_id, StrategyRules, SourceSnapshot, expected_digest=...)` 將該已確認 Entry 綁定一個 strategy instance，保存既有策略 consent；這是明確 application command，沒有新增身分／approval 流程。
3. `revise_strategy` 帶 stable request ID 與 expected strategy revision，修改 SL／TP／退出限價及 source snapshot。已送 command 保持原 revision／價量；新 child exit 使用 claim 當時的 revision。
4. `observe_strategy_price` 接收帶來源及時間的明確 price observation，評估 LOCAL_SYNTHETIC SL／TP；沒有市場資料訂閱／polling 或 native stop。`exit_strategy(..., target_position=0)` 為原策略退出；大於零且低於實際可減碼數量的 target 為減碼。

本輪暫定 `MUTABLE_REDUCE_EXIT_V1_PROVISIONAL`：既有 consent 允許修改保護、減碼與原策略退出；新增 Entry／曝險另經 Preview／Confirm，目前以新 strategy instance 表達。此規則可演進，沒有永久凍結策略。信用單反向 mapping／short strategy／broker-native protection 尚未 qualified，不從既有 CASH long 模型推定支援。

所有 `STRATEGY_*` 版本化 records 存在原 schema-v1 Journal。原 Runtime 先以 transaction 取得 target ownership；effect pump 再於另一個 transaction 原子寫入退出 reservation、`STRATEGY_EXIT_CLAIMED` 與既有 `SUBMIT_CLAIMED`。replay 在寫入及啟動驗證 revision、來源 digest、review／engine lineage 與 claim 時已存在的 entry fills。只有原 runtime 的一個 effect pump 可以派送自己剛提交的 claim，KgiSessionOwner 不讀策略。

```text
effective_position = entry broker fills - exit broker fills
reserved_exit_quantity = committed exit quantities - exit broker fills
new exit quantity = max(0, effective_position - reserved_exit_quantity - target)
```

Stop／TP／Manual 同時到達時，以同一 transaction 取得首次 target ownership；target 只能降低。Entry 未成交部分精確 cancel；ACK 不終結剩餘量。Callback 只 durable ingest 並喚醒 Runtime，SDK effect 不在 callback thread／SQLite transaction 內；每個新 callback wave 有界查證，缺事件時等待明確 query／reconnect，不做無界背景查詢。純 `strategy_status` 不寫入或取得 broker evidence。

60/100 fill → stop → cancel remaining 40＋exit 60 → late fill 15 → exit 15。只有 entry remaining=0、effective=0、reserved=0 且現有 evidence 相符才 CLOSED；後來若有新 broker fill 仍會重新進入 reconciliation。`fill_history_complete=false` 持續揭露，不把 CLOSED 當 native history completeness 證明。

UNKNOWN／已取消／拒絕的 child exit 不會自動回收 reservation 或換 ID 重送；`unresolved_exit_claims` 明示未達 target 的原因。限價未成交、缺 broker ID／history、跨交易日 session mismatch 都不能保證平倉；`session_date_matches` 明示日期限制。只計算該策略 Entry／Exit 的 broker fill lineage，不將 USER／AGENT 或手機單當獨立實體持倉池。

```powershell
.\.venv\Scripts\python.exe -B -m execution_runtime.tests.strategy_demo
.\.venv\Scripts\python.exe -B -m unittest execution_runtime.tests.test_strategy execution_runtime.tests.test_strategy_process -q
```

完整 [Phase 3 驗收](../docs/exec-plans/active/live-execution-plane-20261029/Phase3-Acceptance.md) 含 source/fake scope、crash matrix、diff/hash 與只回退本輪檔案的 rollback。
