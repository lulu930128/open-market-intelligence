# 人工委託 isolated mock

**SYNTHETIC ONLY。沒有真券商連線、登入、憑證或 live 開關；不得掛入 OMI 主 FastAPI。**

從 repo root 啟動可執行的 PowerShell smoke：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\test-manual-execution-mock.ps1 -Smoke
```

人工操作範例（所有價格、額度、規則、身份均為虛構）：

```powershell
.\scripts\test-manual-execution-mock.ps1 -Symbol 2330 -Side BUY -Shares 1000 -Lot BOARD -OrderKind LIMIT -LimitPrice 25.50 -Funding CASH -PositionAction OPEN
.\scripts\test-manual-execution-mock.ps1 -Symbol 6543 -Side SELL -Shares 1000 -Lot BOARD -OrderKind MARKET -Funding CASH -PositionAction CLOSE
```

先顯示完整 draft、eligibility、expense reserve、tick/lot/price constraints、有效期限及限制，再要求輸入精確 `CONFIRM`。未確認沒有 confirmation/outbox/send。確認成功後送出同一筆 fake order；其後可手動 `status`、`query`、`reconcile`、`CANCEL`、`exit`。取消另需精確輸入 `CANCEL`。任何失敗不自動重試。超過 preview/evidence/session TTL 必須重啟測試並重新預覽。

Symbol schema 為 4–6 位 ASCII 數字及可選大寫字尾；真正 admission 依 server catalog 的完整 Instrument/Evidence。無 fixture identity 為 `INSTRUMENT_UNVERIFIED`，沒有 lot evidence 為 `LOT_UNVERIFIED`。**命令列把指定 symbol 加入明確的虛構 catalog，不證明該代號存在或實際可交易。**正規股票主檔、session、tradability、可動用額度與 permissions 的可信 ingress 全部 UNVERIFIED。零股與信用在這個 runner 沒有完整資料，會阻擋；不 fallback 現股。

## 所有權

```text
PowerShell 人工操作／明確 smoke fixture
 -> 127.0.0.1 隨機 port 的 dedicated test process
 -> M2B transport + SyntheticAuth + ManualMockApp projection
 -> canonical execution Draft/Confirmation
 -> M2A SimulationApplication（唯一 transaction、challenge、reservation、outbox、audit owner）
 -> 封閉 FakeSDK create_order/set_event/get_trades(full=True)/cancel_order
 -> typed observation conversion -> 原 M1 transition
```

`fake_sdk.convert(Draft, FakeUnits)` 是 canonical handoff，不引用 M3 `ApprovedOrderFixture` 或 M3 event reducer。FakeOrderArguments 是 private fake protocol DTO；不是另一份 production order contract。Fake qty 的 1000/1 僅為 fake protocol 明訂的虛構單位，絕不代表 KGI 單位。SDK metadata 即使存在也不解鎖 live。

M2A 在同一 transaction 儲存 fake observation 與 mock effect，重新 replay 完整比對。這只適用純記憶體 fake SDK；**不可把真網路 SDK 填進此 SQLite transaction**。真 adapter 需 durable claim/outbox 與 transaction 外 side effect、generation/fencing/correlation 協定及 crash acceptance，見 handoff。

M2B `_TestApp` 目前是 private test-only transport seam，由本 bridge 單一 caller 沿用 body bounds、Origin/CSRF、principal/account capability 與 thread offload；原 M2B app 沒有 submit route。正式 authenticated transport 接入並通過 parity/negative acceptance 後，應移除本 test bridge 或明確抽出 versioned shared transport，不把 private seam 升格 production API。

## HTTP / machine status

沿用 `/test-execution/v1` 前綴，所有路由都驗證 synthetic session 與 Origin，POST 加 CSRF；沒有公共 session 發行端點。新增 `POST /orders/{preview_id}/submit` 只接受 `{"user_confirmed":true}`，先前 atomic confirm 是必要條件。沒有 query-string/scenario/任意 DB path/live-switch 參數。

Response 為 `kind=omi.manual_mock_execution.response, version=v1`；保留 `simulated=true, broker_connected=false, test_only=true`、`status`、`reasonCodes`、`data`。這是 M2B transport 上的 mock projection，不能當成原 M2B closed JSON schema。

| 操作 | 結果 |
|---|---|
| preview | `PREVIEWED`、`data.status=READY`，完整 cost/constraints；blocked 為 stable reason codes |
| explicit confirm | `PENDING`、`phase=CONFIRMED`，已預留但未送出 |
| submit | `phase=SENT`；`PENDING`、`BROKER_ACCEPTED`、`BROKER_REJECTED` 或 `UNKNOWN` |
| acceptance | 只由相關 callback/query 的 verified fake `order_id`；立即 Trade Pending 不構成成功 |
| rejection | `errcode=FAKE_REJECT` / synthetic `msg`，保留預留 |
| timeout / disconnect fixture | `UNKNOWN` / `TRANSPORT_OUTCOME_UNKNOWN`，不重送 |
| GET status | SQLite 純讀，不 query、recover、refresh 或寫 audit |
| POST query | 明確 `get_trades(full=True)` fixture，保存 observation；不自動套用 reducer |
| POST reconcile | 明確 fencing interrupted claim、查單並套 M1；查無不代表沒送，維持 `RECONCILING` |
| POST cancel | 明確取消意圖及 fake SDK ACK，`CANCEL_PENDING`；reconcile 最終查单才 `CANCELLED` |
| POST kill-switch | synthetic control，`enabled=false` 阻擋新 preview/confirm/send；保留查單／撤單 |

存在 pending/UNKNOWN/partial/cancel race 時保留資源，broker accept 不是 fill，cancel ACK 不是最終撤單。跨指令／跨 process 的同 outbox key 不重發，confirm replay 不重複預留。Schema v1 永不 release；本 runtime 不呼叫 settlement。

## 測試資料與 lifecycle

Default fixture：2330 接受；2317 Pending 待明確 query/reconcile；2454 拒絕；2303 timeout 但 query 可見接受；2882 timeout 且 query 無資料；9998 停牌 fixture、9997 過期、9996 未授權、9995 關市。這些都不是現實市場判斷。

Runner 僅綁 `127.0.0.1:0`，無 host override、reload、多 worker 選項；Windows OS lock 保護同 factory sandbox 的 dedicated worker。M2A claim/stage 為 effect fencing，沒有租約到期自動接管／自動 resend。臨時 synthetic auth 經 parent pipe 交付 PowerShell，不寫憑證檔、不出現在 argv 或結果。啟動／停止限本次 child，stdin EOF 或最長 300 秒結束，revoke session、關 mock send、停止 listener，再清掉 factory 自有 temporary sandbox。

Restart/crash persistence 驗證使用 parent 保有的 factory capability；一般 CLI 結束即刪除自有 test sandbox。沒有 durable production recovery store，沒有正式使用者 auth、2FA 或 broker session generation/coexistence acceptance。每次新 runtime 的新 issuer 會使舊 capability 無效。

## Source 驗證

```powershell
.\.venv\Scripts\python.exe -B -m execution_manual_mock.tests.run_validation
.\.venv\Scripts\python.exe -B -S scripts/check-architecture.py --constraints execution_manual_mock/constraints.toml --debt execution_manual_mock/debt.toml
```

Runner使用child-local factory temp root，不改正式設定，逐suite輸出PASS/FAIL/SKIP JSON；任何失敗exit非零。
Replay只呼叫純 `validate_proof`，不呼叫fake SDK send/cancel/query；tripwire測試保護此界線。

測試與精準 live gate 見 [本次交接](../docs/exec-plans/completed/omi-manual-mock-20261011/Handoff.md)。**正式交易前端 BLOCKED；即使做模擬 UI 也必须醒目標示模擬，不能新增真交易按鈕。**
