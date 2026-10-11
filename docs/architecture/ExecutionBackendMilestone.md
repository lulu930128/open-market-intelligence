# Execution headless backend 與保留型 LOCAL_MOCK ledger

未來 manual execution UI owner 為 **MCP App**。Research MCP/AI/Kuro 保持唯讀，
沒有新增 production route 或 trade tool，現有 frontend 不接線。

## 單一 owner

M1 `assess` / `transition` 擁有 admission/reducer；M2A `SimulationApplication`
擁有 confirmation、reservation、outbox、audit、SQLite transaction 與 full replay。
`HeadlessCommands` 只做 server auth、strict payload conversion、手動 action binding 與 delegation。
`execution_kgi_simulator` 不持有 DB transaction、不呼叫 reducer、不成為第二套 domain。

## 來源與時間

Canonical `Origin.SYNTHETIC` 未放寬。`EvidenceRef.received_at` 是 additive optional field，
舊 absent payload/hash 不變；若有值，要求 `observed_at <= received_at <= now`。
原 valid_from/valid_until/maximum evidence window 保留，receipt 不替代 source time。
新 headless ingress 要求 server fixture 的 market/account/permission 三者都有 received_at。
consumer 不能傳 account/principal/evidence/origin，也不能自行宣稱已驗證。

這是 server-owned LOCAL_MOCK trust boundary，不是 authenticated real market/account ingress。
真 SIM evidence 的來源／身份／撤權／session verification 尚未實作，不得改標 synthetic 來進入本路徑。

## Retained lifecycle

`temporary_sandbox()` 維持既有清理行為。`retained_mock_sandbox()` 明確建立 private factory
directory，使用同一 schema/SQLite application ID/append-only tables/FULL sync。
normal exit/exception 不刪除，creator abrupt exit 後可用 issued `SandboxTicket` 重開；
不接受任意 DB path、不 touch 主 DB、不自動 migration/recovery/dispatch。
ticket token 不進 repr，透過 private pipe 傳送；重開仍驗證 factory root/marker/link/schema。

這條 selected working path 在設定的 test TEMP root 保存至人工處理，可能受外部 temp cleanup 影響，
尚不是 REAL_SIM durable operational lifecycle。備份／restore／長期 retention 與 real origin migration 必須另驗。
full replay 與原 bounded quotas 保留，沒有 scale/throughput/production acceptance。

## Headless command contract

入口為 `HeadlessCommands.execute(Command, JSON_bytes, headers=...)`，沒有 listener/route/global app。
JSON 上限 8192 bytes，duplicate/extra fields 拒絕。Headers 為 lowercase server transport keys；
既有 `SyntheticAuth` 要求 bearer session、allowlisted origin，mutation 再要求 CSRF。
失敗以 `CommandStatus.DENIED` 與原 reason code 回覆；real readiness 一律 typed BLOCKED。

| Command | Payload / 行為 |
|---|---|
| PREVIEW | 與既有 gateway Draft wire fields 相同；server evidence policy 按 principal/account/symbol/lot 選取；不 dispatch |
| CONFIRM | preview_id、order_access、token、digest、manual_action=`CONFIRM_LOCAL_MOCK:<digest>`；原子 consume/reserve/outbox |
| STATUS | preview_id、order_access；不寫 ledger、不呼叫 SDK、不 reconcile |
| QUERY / RECONCILE / CANCEL | preview_id、order_access、manual_action=`<COMMAND>_LOCAL_MOCK:<preview_id>`；轉交 M2A 明確命令 |

所有 reply 標示 `omi.execution.manual-command.v1`、SYNTHETIC、LOCAL_MOCK、
REAL_SIM BLOCKED、LIVE_SESSION BLOCKED、MCP_APP_CONSUMER NOT_CONNECTED。
只有 authenticated preview 回傳 challenge；status/audit 不回 token/session/CSRF/order_access。
exact action string 在 LOCAL_MOCK 中可測試人工步驟，不能單獨證明真實人類確認；G4 需真 UI/auth 事件。
headless 沒有 SEND、worker claim/result/report 或 enable-send 入口。

`SimulationApplication.manual_request_id` 把 server principal/account/client_request_id 放入穩定 namespace，
auth issuer 重建不造成新的 request identity；這個 digest 不授予 access。
新的 auth issuer 使舊 session/access 失效，同 principal 重新驗證後可重新 preview 取得 access。
過期 preview 不延長，已確認命令可依既有 confirmation capability idempotent readback；跨重啟的
正式 order discovery/re-auth access recovery 還不是已發布的 production API。

## Broker fixture 與封鎖

Fixture quantity metadata 分開 order/query/modified_quantity/deal，無預設推定與 bool coercion。
這些數字是 invented fixture，不能充作 2.1.0 sanctioned qty proof。
Send claim 先 commit，再進 `rehearsal_check_effect` 驗 generation/kill/expiry/resource restriction，
離開 read transaction 後才呼叫 FakeSDK。QUERY/CANCEL 不被 SEND kill 全面封鎖。
最後檢查與 native call 之間仍存在不可由 SQLite 消除的 race，不能宣稱 fence 能撤回已執行外部 effect。
真 SDK 必須先有 worker native confinement、controlled ownership 與外部 reconciliation 證明。

UNKNOWN 不重送、Pending 不當 accepted、accepted 不當 filled、cancel ACK_ONLY 不當 final；
沿用 M1/M2A 既有語意與 LOCAL_MOCK correlation。費用／settlement 缺少證據不釋放 reservation。
Claim 後 crash 的辨識由明確 fence/recover command 處理；單純 reopen/status 不猜測 worker 存活。
Power-loss、disk-full、operational backup/restore 與 native hard fencing 尚未驗證。

最新測試、source manifest 與 G0-G4 狀態見
[milestone Acceptance](../exec-plans/active/execution-backend-milestone-20261011/Acceptance.md)。
