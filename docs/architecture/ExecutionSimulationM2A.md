# M2A Synthetic Execution Application

## 2026-10-11 isolated manual mock extension

M2A仍是唯一transaction owner。新增封閉FakeSDK typed conversion與callback/query observation，
append-only audit和mock_effect同transaction保存，完整replay驗證；不接受real SDK注入。
mock kill switch預設關閉且保存在audit；confirm及send claim/effect重新檢查。人工reconcile可fence
中斷claim但不重送。新 [loopback bridge](../../execution_manual_mock/README.md) 只供PowerShell人工／smoke。
正式runtime/live/frontend仍BLOCKED，M2A source資料不構成真broker證明。

本次regression另修正`settlement.order_lots`：依event ID排序，讓並行fill插入順序與JSON materialized
projection/replay產生一致的receipt digest；保留完整驗證、不修改M1 reducer或使用者DB。

本頁補充 [M1 current architecture](ManualTradingExecutionV1.md) 的 synthetic application source 能力；該文件所有真實 auth/broker/live gates 仍 BLOCKED。M2A.1 additive 擴充 M1 contract/preflight，保留既有 constructor／fixture／tests 與純 IO guard。

```text
明確 synthetic fixture / 人工 test command
    → execution_simulation.application.SimulationApplication
        → execution.validation.assess / digest_of
        → 隔離 SQLite BEGIN IMMEDIATE / append-only ledger
        → 固定 mock fixture receipt（無 adapter injection / network）
        → execution.state_machine.transition
        → orders materialized projection + append-only audit
    → Envelope: SYNTHETIC / simulated / no broker / test-only
```

`SimulationApplication` 是唯一命令與 transaction owner。M1 是唯一 preflight/cost/state reducer owner。SQLite storage 只提供 temporary sandbox 與 schema，mock module 只產生固定回報；沒有 production market/account owner 或第二份 validation/reducer。

`orders` 與 monotonic command clock 是 mutable projection；其他業務事實採 immutable rows。確認的 challenge consume、reservation、order intent、outbox、audit 同 transaction。dispatch 分為 durable claim、mock effect、receipt processing 三段；重啟不重播 claim，UNKNOWN 需明確 recover/reconcile。audit 重放驗證 projection，損壞 fail closed。

新 [M2 constraints](../../architecture/execution-simulation-constraints.toml) 禁止 provider/network/SDK/app dependency，並禁止 production/backend/MCP/scripts/M1 呼叫 M2；新 [M2 debt](../../architecture/execution-simulation-debt.toml) 不接受豁免。原 [M1 constraints](../../architecture/execution-constraints.toml) 的純 IO/clock 與 no-production-caller invariants 原封保留。M2 targeted tests 執行 M2 manifest 與注入違規測試；尚未修改正式 CI wiring。

| 驗收面 | 狀態 |
| --- | --- |
| M1 source | 保留純 domain、無 IO，回歸重新驗證 |
| M2A source / isolated test process | 實作 persisted preview/confirm/outbox/mock receipt/recovery/audit、跨單保守預留 |
| 正式 runtime | 未部署、未啟動 listener、未接 main FastAPI、正式 DB 未開啟 |
| M2B app auth/UI | BLOCKED，詳見 [handoff](../exec-plans/active/omi-m2a-synthetic-execution-20261010/M2B-Handoff.md) |
| M3 broker/live | BLOCKED；無 SDK/session/真單、無 live flag |

保存範圍限 factory temp sandbox 的生命週期。Schema v1 保留所有預留；M2A.2 的明確 factory clone schema v2 可在 verified synthetic settlement 後新增 release overlay，原 reservation 永不刪改。實際 command contract、重跑指令及限制以 [package README](../../execution_simulation/README.md) 為準。

## M2A.1：audit、取消與擴充資源

公開 `audit()` 僅投影 `seq/occurred_at/operation/digest`；不回傳 internal payload、challenge、confirmation、account/principal、任意 caller identifier。`status()` 的 order 移除 raw events，另提供 `simulation_attempts`（未確認為 0）。private audit event store 保留完整 immutable preview 供 deterministic replay；只有 preview command 可以回傳該次確認 challenge。codec/replay 錯誤不連帶輸出原始 decode exception。

Windows sandbox factory 要求 Python 3.13+，以 tempfile 的 mode 0700 建立 private ACL；實測 OWNER RIGHTS（owner 為當前使用者）、SYSTEM、Administrators，沒有其他 Allow ACE。測試讀取 directory／SQLite／marker ACL，沒有修改主機或既有目錄 ACL。這不抵抗擁有該檔案的 OS 使用者或管理員自行竄改。

取消仍使用唯一 M1 `transition`：

- 未確認 preview：讀 preview 建立 `PREVIEWED/confirmed_at=None` 值物件，套用 `CANCEL_REQUESTED`，同 transaction 寫唯一 EVENT 與 cancelled order projection。沒有 confirmation、reservation 或任何 outbox。取消後原 challenge 永久不能 confirm；重複取消不新增取消 event。
- UNKNOWN／RECONCILING：只保存 `cancel_requested=True`，沒有新 CANCEL outbox／mock effect，不宣稱成功。query 回覆仍經原 reducer；回到 `CANCEL_PENDING` 後需另一個明確 cancel command 才 enqueue，另行 mock ack 才完成。無回覆就維持 unresolved。
- replay 允許未確認取消的 order，並嚴格要求 confirmations 集合等於 `confirmed_at != None` 的 orders；不插入假 confirmation。

v2 preview 綁定完整 ResourceRequirements。`_remaining_resources` 只聚合已確認 preview 的 immutable holds，帳戶層扣 credit／collateral／intraday risk，標的層扣 borrow／margin position／short position／lend position；cash／現股 sellable 沿用既有 reservations table。成本、side/action eligibility 與 admission 始終由 M1 assess 決定。新 SEND claim 前再次驗證 v2 證據 TTL；不 refresh、不變更證據或重新預留。

新 `simulate_fill` 是明確 fixture command：BUY 使用 preflight ceiling、SELL 使用 floor，保留 Decimal fill_price，接受部分／完整累計成交。callback 與 replay 共用 M1 `validate_fill` 的範圍／限價方向／tick guard，再走原 reducer。它不保證市場實際成交價格、速度或可成交性。

## M2A.1 相容性 checkpoint

SQLite `user_version=1` 與既有表結構不變。codec envelope 仍為 v1；新增欄位只有明確 `metadata={additive: True}` 可以缺省，且預設值不加入舊 canonical digest／packed JSON。`Draft.contract_version=2` 才接受新模式。舊 reader 遇新欄位會 fail closed；新 reader 可重放原 v1 bytes。測試保留修改前的 synthetic preview JSON，驗證逐 byte roundtrip、舊 digest、舊 journal reopen 不寫入與後續確認。

新資源尚無獨立 release ledger；credit／collateral／borrow／positions 由完整 confirmed preview 重算。拒絕、取消、成交都不釋放，不能以更新 snapshot／降回 v1 繞過已建立的 resource baseline。M2A.2 必須先定義 versioned settlement journal、重放／projection parity、ack／late fill／UNKNOWN 保留規則與 migration，才可加入釋放、還券、還款或餘額更新。

完整 audit replay 與聚合仍限 bounded tests；實測與 checkpoint gate 見 [M2A.1 交接](../exec-plans/active/omi-m2a1-expanded-order-contract-20261010/M2A2-Handoff.md)。未新增 Runtime／Live／Product 能力。

## M2A.2 synthetic settlement owner

新增能力以 `execution_simulation/settlement_contracts.py`、`settlement.py`、`SimulationApplication` 為 source truth。
Settlement module 只有純財務投影，沒有 order reducer、IO 或 transaction；application 仍是唯一寫入 owner。
`record_fill(FillLot)` 的每筆 unique ID 帶 delta shares 與自身 executed price，同 transaction 轉成 M1 cumulative report；只有 reducer 實際增加的 quantity 才能成為 lot。
Legacy cumulative callbacks 仍相容，但缺逐筆價格／ID 時不得推算結算。

生命週期分開呈現：ORDER_CONFIRM、BROKER_MOCK_ACCEPT、TRADE_FILL、SETTLED。成交不是結算。
`settle` 要求 terminal canonical order、lot 合計一致、版本化 receipt 綁 account／instrument／currency／session／preview digest／order digest／fill digest、有效時間、eligibility 與無未決晚成交聲明。
UNKNOWN／RECONCILING／CANCEL_PENDING／仍在成交的部分委託不 release；部分成交後取消可以在完整 finality 證據下結算已成交量。
新事實寫入 append-only settlement_events／releases 與同一 SHA journal，materialized settlement_projection 必須完整 replay 相等。
結算後矛盾 report 會拒絕並持久化 account restriction，停止後續 admission／SEND，不發生自動平倉、重送或解除 restriction。

資源輸入统一為 immutable baseline 加 verified settlement delta 減尚未 release 的 holds。preview／confirm／dispatch／replay 使用相同 projection，再交 M1 assess；不刷新原 AccountFacts，不建立第二個 admission owner。
Cash buy 增加現股；融資增加獨立本金與 margin position；融券／借券增加 borrowed shares 與獨立 collateral，賣出所得保留為 restricted proceeds，直到 verified cover／return 才可轉入現金。
信用 CLOSE 必須指向本 sandbox 已結算 opening loan、對應 funding／account／instrument、未還股數，以及 unique synthetic lender ack。
只有原 CreditFacts 中的部位而沒有 loan lineage 時維持 UNVERIFIED。

FeeSchedule／InterestPolicy 必須明確提供 currency、immutable evidence ID/version、validity、有限 Decimal rates、money quantum 與 ROUND_HALF_EVEN；本機不含真實稅率／券商費率。
費用按委託所有 lots 的 exact notional 計算，再依明確 quantum 計費。利息只由 explicit contiguous AccrualTick 計算並扣現金，無自動排程或複利。
平倉前需 accrued_through 等於結算時間；部分本金／collateral／proceeds 分攤向下至 M1 最小金額單位 1e-8，最後一筆消耗 exact remainder，不以 fee quantum 四捨五入原始成交款。
Maintenance／margin call／recall 只接受明確 synthetic blocked evidence，不取得估值或執行 forced liquidation；無法證實費率、來源、償還或資源非負時 fail closed。

## 沙箱版本與成本上限

原 `temporary_sandbox()` 仍產生 schema v1。新 `settlement_sandbox_clone(source)` 只接受原 factory capability，在另一個 factory temp directory backup，再以 transaction 建立 v2 tables／prefix root／schema version。
舊 preview、private journal payload 與 hash 不 rewrite；v1 reader 相容，codec envelope 保持 v1，新增 allowlisted typed settlement payload。`connection` 只讀版本，永不自動 migration。
Root 綁 factory token digest、原 seq/head、codec/schema/policy version；每次 reopen、command、讀取完整驗證 prefix、M1 state、結算、release、outbox 與 clock。
這是 accidental corruption 模型，不能抵抗能重寫整個 sandbox／程式的 OS owner。

未實作 checkpoint 或 incremental replay。固定上限為60 previews、2048 audit rows、16 MiB audit payload、每單64 lots；超額 command 在寫入前拒絕，postcondition 超額則整筆 rollback。達上限需新隔離測試沙箱，沒有刪除歷史或轉移負債捷徑。
**Scale Gate BLOCKED**：full replay 成本隨 journal 增長，未達單筆100ms保證。所有Source／benchmark／review證據見 [M2A.2 Acceptance](../exec-plans/active/omi-m2a2-settlement-20261010/Acceptance.md)。
