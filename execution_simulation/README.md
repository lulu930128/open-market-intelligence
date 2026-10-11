# M2A SYNTHETIC-ONLY Execution Application

M2A.2 新增 factory clone schema v2 結算；原 public methods 與預設 schema v1 保持相容。下方原 M2A.1 的永久預留說明適用 v1；v2 的 release 規則以本節為準。

新增 Python commands（均回帶 SYNTHETIC／simulated／no broker／test-only 的 Envelope）：

| 方法 | 行為 |
| --- | --- |
| `record_fill(FillLot, *, now)` | unique ID、delta shares、Decimal executed price；同 transaction 經 M1 reducer 並記 exact lot |
| `settle(id, SettlementReceipt, *, fees, interest, now)` | explicit matched finality、fees/interest policy；terminal order 才可 atomic settlement/release |
| `accrue(AccrualTick, *, now)` | contiguous bounded explicit period、已綁定 interest policy；重複不重扣 |
| `restrict(id, RestrictionEvidence, *, now)` | synthetic maintenance/call/recall blocked evidence；停止 admission/SEND，沒有自動平倉或解除 |
| `snapshot(id)` | readonly lifecycle、lots、account settlement deltas、release／restriction 狀態；尚無成本證據時 `UNVERIFIED` |

`snapshot` 是明確的本機 synthetic ledger view，可含 synthetic account/fill identifiers；它不暴露 challenge token，也不接入 Gateway／HTTP。原 `status/audit` redaction 邊界維持不變。
`settlement_sandbox_clone` 從 `execution_simulation.storage` 匯入，僅接受 factory v1 sandbox，不接受 path。
新 tests 示範四種 funding、limit/market、zero-baseline open/close、不同 partial fill 價格、finality、explicit accrual 與 child-process crash。

```powershell
.\.venv\Scripts\python.exe -B -m unittest execution_simulation.tests.test_settlement -v
.\.venv\Scripts\python.exe -B -m execution_simulation.tests.benchmark_settlement
```

所有 rates/prices/session 均為虛構。信用 CLOSE 沒有本 sandbox opening loan 或 lender ack 時 UNVERIFIED；短賣所得維持 restricted proceeds 到 verified cover。仍有全量 replay 成本，60 previews／2048 audit rows／16MiB／每單64 lots 是測試配額，Scale Gate BLOCKED；不是正式帳務引擎。
完整 ownership、計費與分攤語意、版本與 integrity 邊界見 [architecture](../docs/architecture/ExecutionSimulationM2A.md)。

這是隔離測試 application，沒有 listener、HTTP route、正式 DB 路徑、broker interface、SDK、live flag 或 production caller。所有 public application response 都是 `Envelope(value, simulated=True, broker_connected=False, test_only=True, origin='SYNTHETIC')`。失敗使用 M1 `ExecutionRejected.code`，不把未知轉成拒絕或重送。

從 repo root 執行（Python 3.11+；Windows 因 private temp ACL 要求 3.13+，stdlib-only）：

```powershell
$env:TEMP = Join-Path (Get-Location) '.tmp'
$env:TMP = $env:TEMP
.\.venv\Scripts\python.exe -B -X utf8 -m execution_simulation.demo
.\.venv\Scripts\python.exe -B -m unittest discover -s execution_simulation/tests -t . -v
.\.venv\Scripts\python.exe -B -m unittest discover -s execution/tests -t . -v
.\.venv\Scripts\python.exe -B scripts/check-architecture.py --constraints architecture/execution-simulation-constraints.toml --debt architecture/execution-simulation-debt.toml
.\.venv\Scripts\python.exe -B scripts/check-architecture.py --constraints architecture/execution-constraints.toml --debt architecture/execution-debt.toml
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider backend/tests/architecture/test_manual_execution_boundaries.py execution/tests/test_boundaries.py
```

`.tmp` 應為既有可寫測試目錄；環境變數只影響目前 PowerShell process。每例 SQLite 皆由 `temporary_sandbox()` 建立，結束後清理自己建立的資料夾。無任意 DB filename/open/migrate API。`SandboxTicket` 只讓另一測試 process 重新開啟該 temp sandbox；需相同 TEMP、factory marker/token、固定檔名、SQLite application ID/schema version。它不是登入或 2FA，不能用於正式帳戶。

## 互動 contract

```python
from execution.tests.fixtures import NOW, confirmation
from execution_simulation import SimulationApplication, temporary_sandbox
from execution_simulation.fixtures import symbol_fixture

with temporary_sandbox() as sandbox:
    app = SimulationApplication(sandbox)
    draft, evidence = symbol_fixture('2330')  # 價格/額度/session 全部虛構
    preview = app.preview(draft, evidence, now=NOW).value
    # 明確人工操作在測試中的表示；這不是身分驗證或人類存在證明。
    result = app.confirm(confirmation(preview), now=NOW)
    result = app.dispatch(preview.preview_id, now=NOW)
    reopened = SimulationApplication(sandbox)
    assert reopened.verify().value['verified']
```

預設仍沿用 M1 TESTSTOCK fixture；`2330/0050` 等符合 M1 Instrument 的代碼可用。代碼看似真實不賦予 evidence 可信度，這裡沒有 quote/account 取得能力。

| Python method | 輸入與效果 |
| --- | --- |
| `preview(draft, evidence, *, now)` | M1 typed 值；回 `Envelope[Preview]`；持久化最多 60 秒 challenge。相同 account/request/digest 重用 preview，異 payload/evidence conflict |
| `confirm(Confirmation, *, now)` | 明確 `user_confirmed=True`、token/digest/principal 綁定；同 transaction consume、reserve、初始 order、SEND outbox/audit；exact replay 回目前狀態 |
| `dispatch(id, *, now, fixture=Fixture.ACCEPT, kind='SEND')` | 顯式 mock worker action，`kind` 僅 SEND/CANCEL；durable claim 後最多一筆 mock effect，沒有自動重試 |
| `callback(SimulationEvent, *, now)` | 固定 mock effect 存在後接受 synthetic report，唯一 reducer 為 M1 `transition` |
| `cancel(id, *, now, user_confirmed)` | 未確認 preview 原子取消且不建立 outbox；UNKNOWN 僅記意圖；已有 mock send 且 CANCEL_PENDING 才建立唯一 CANCEL outbox |
| `timeout(id, *, now)` | M1 TIMEOUT；不釋放預留、不重送 |
| `recover(id, *, now)` | 顯式封閉 abandoned CLAIMED 為 UNKNOWN，fence 延遲 worker；不 dispatch READY，不自動 query |
| `query(id, *, now)` | 顯式 mock command 並 append audit；回 AVAILABLE/UNAVAILABLE/ERROR 與 synthetic receipt，不改 order |
| `reconcile(id, *, now, user_confirmed)` | UNKNOWN→RECONCILING 後 query；缺資料或錯誤仍 unresolved，已有事件經 M1 reducer 處理 |
| `status(id)` | readonly URI/query_only；回不含 raw events 的 order、simulation_attempts、commands(stage/mock_effects)、preview/draft/evidence digest |
| `audit()` | readonly 安全投影，只有 seq/occurred_at/operation/digest；private event-store payload 不 outward 暴露 |
| `simulate_fill(id, *, cumulative_filled, now)` | v2 明確 fixture fill；BUY ceiling／SELL floor、preflight range/tick guard、部分或完整累計成交，不做結算 |
| `verify()` | readonly chain/reducer replay，比對 preview、confirmation、orders、reservation、budget、positions、outbox/stage/mock effects、clock |

`crash_at` 是 test fault injection，只有固定程式碼位置拋出 `SimulatedCrash`；不存在替換為真 adapter 的參數。

## 持久化與安全語意

- `BEGIN IMMEDIATE` 串行化命令；unique `(account_id, request_id)`、confirmation PK、outbox `(preview_id,kind)`、mock effect PK 防雙擊／多 owner 重送。
- Audit、preview、confirmation、budget/position baseline、reservation、outbox、outbox stage、mock receipt 全部 append-only（SQLite UPDATE/DELETE triggers）。`orders` 與 `metadata` 是由唯一 transaction owner 更新的可重建 projection，不設 append-only trigger。
- `_event` 只呼叫原 M1 `transition`；相同 transaction 更新 orders 並 append audit。verify 獨立重放 M1 events；constructor、status、命令在採用 projection 前驗證。
- Claim commit 後 crash，即使 mock effect 尚不存在，也不再 send；recover→UNKNOWN→manual reconcile。這是保守 at-most-once mock dispatch，不是 exactly-once broker execution。
- `mock_effects` 另 transaction 表示 send 已發生而回報尚未入帳的 crash window。recover 與 delayed worker 共用 SQLite fencing；所有 `status()` 都在 command transaction 結束後才呼叫。
- Version/schema、未知 codec tag、unexpected fields、duplicate JSON keys、NaN、projection/hash mismatch 皆 fail closed。不使用 pickle/dynamic import。
- SHA-256 chain 可偵測本輪測試的損壞與 projection 改動；不是對抗可改整個 SQLite／程式碼的 OS 使用者之簽章或防竄改儲存。
- 跨委託 BUY 聚合已預留 cash（含 M1 fee reserve），SELL 按完整 instrument identity 聚合股數。聚合用固定 Decimal precision；成本及 admission 仍只呼叫 M1 assess。
- 所有 confirmed reservation 即使拒絕、取消、成交、UNKNOWN 仍保留。baseline 改變 fail closed；無資金釋放、成交入帳、賣出款加回、買入股數加回或 session reset。這項保守限制使晚到 fill 不會侵蝕下一單額度。

## 驗收限制與後續

實跑結果見 [Smoke](../docs/exec-plans/active/omi-m2a-synthetic-execution-20261010/Smoke.md)；[current architecture](../docs/architecture/ExecutionSimulationM2A.md) 定義 owner 與 guard。[M2B 交接](../docs/exec-plans/active/omi-m2a-synthetic-execution-20261010/M2B-Handoff.md) 只描述未来 app-only 契約。

目前能在 sandbox lifetime 內跨 process 重啟。結束 factory context 後 DB 會清理；沒有 production retention/backup/migration、OS service lifecycle、硬體斷電／磁碟毀損復原或高吞吐驗證。verify 全 journal 重放適用 bounded test fixture，不是大量委託 runtime。

未部署、無 KGI 真單、未修改正式 Backend/MCP/Next.js。M2B 真 authentication/UI、M3 broker/live 仍 BLOCKED；沒有 live enable 安裝。
