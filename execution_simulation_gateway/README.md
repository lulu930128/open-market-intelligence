# M2B synthetic command Gateway v1

這是獨立、factory-only 的 ASGI Test App。`build_test_app(sandbox, server_fake_auth,
synthetic_fixture_policy, clock=...)` 只接受 M2A factory temporary sandbox。
沒有全域 app、HTTP listener、CLI server、production router、MCP tool、provider 或 broker adapter。
`SyntheticAuth` 是程式直接注入的虛構測試 issuer，不是 OMI 登入、2FA 或真實 Auth Owner。

## 責任與資料流

```text
Test issuer → ephemeral synthetic session + CSRF
Test fixture policy → immutable, principal/account-bound fictional Evidence
ASGI HTTP → bounded JSON + auth/origin/CSRF + order capability
          → typed M1 Draft/Confirmation
          → M2A SimulationApplication → M1 assess/transition → temporary SQLite
          → allowlisted synthetic response
Direct test runner → M2A dispatch (closed mock Fixture vocabulary)
```

Gateway 不算 tick、價格、可用額度、borrow、資金預留、交易時段、成本或 settlement。
v2 MARKET 的 `limit_price=null`、Funding、PositionAction 與 admission 由中央 M1 執法。
`SHORT_SELLING` 為融券、`LEND_SELLING` 為借券；不新增 Gateway 專屬別名。
所有 fixture 數字均為虛構，2330 只是測試代碼。Server policy 不由 HTTP payload 指定。

## HTTP contract

前綴為 `/test-execution/v1`。所有路由都需要 `Authorization: Bearer <test-session>`
及精確 Origin allowlist；所有 POST 另外需要 `X-CSRF-Token`、`Content-Type: application/json`。
訂單操作需要 `X-Order-Access`，只有 preview 成功後回傳的本主體 capability 能使用。
不接受 query string、額外 body fields、重複 headers／JSON keys、NaN 或非 UTF-8 JSON。
Body/header 分別最多 8192 bytes；body timeout 2 秒；預設每 session 每分鐘 120 requests，
最多 32 sessions，TTL 最長 5 分鐘。401/403/429 與格式拒絕不寫 M2A。

| 方法／路徑 | 操作與成功狀態 | 拒絕／不確定狀態 |
| --- | --- | --- |
| POST `/preview` | 200 PREVIEWED；唯一路徑可交付 confirmation token、digest、期限與 order capability | 403 fixture allowlist；409 idempotency/expiry；422 M1 admission |
| POST `/confirm` | 200；同 M2A transaction consume/reserve/order/outbox；exact replay 回目前 receipt | 403 challenge/access；409 digest conflict、過期或 consumed；422 explicit confirmation |
| GET `/orders/{preview_id}` | 200，保留 M2A 原始 order state（含 UNKNOWN） | 401/403；409 unknown preview；不做 query/recovery |
| GET `/orders/{preview_id}/audit-summary` | 200，僅該單 digest/draft_digest/evidence_digest/commands | 不暴露全域 audit rows、count、head、時間或其他帳戶資料 |
| POST `/orders/{preview_id}/cancel` | 200 cancelled 或 202 CANCEL_PENDING | 409 UNKNOWN/RECONCILING；不自動 dispatch |
| POST `/orders/{preview_id}/query` | 200 AVAILABLE；明確 mock 查詢，會 append audit | 409 UNAVAILABLE/ERROR；不自動變更 order |
| POST `/orders/{preview_id}/reconcile` | 200 resolved 或 202 CANCEL_PENDING | 409 unresolved/invalid transition |

cancel/query/reconcile body 都必須是 `{"user_confirmed":true}`。沒有公開 dispatch、callback、
recover、session issuance、資料庫 path 或 scenario route。未知路由 404；超量 429；
內部錯誤固定 500 `INTERNAL_TEST_ERROR`，不回 exception/request detail。

所有 response 都有 `kind=omi.synthetic_execution.response`、`version=v1`、
`simulated=true`、`broker_connected=false`、`test_only=true`、`status/limits/errorCodes/data`。
[schema.py](schema.py) 的 `contract_schema()` 產生版本化 JSON Schema；enum 直接來自 M1。
Schema 描述 wire shape，M1 才決定交易合法性。Decimal 使用字串，MARKET price 使用 null。

## 所有權、重播與重建

M2A `status()` 已去識別，沒有 account/principal lookup。Gateway 在成功 preview 後以
issuer 隨機 key 簽發 HMAC，綁定 principal/account/preview_id；不建立 ownership DB 或第二份 order reducer。
client_request_id 也依 principal/account 做 HMAC namespace，避免同帳戶不同 principal 的 idempotent
preview 取得別人的 challenge。所有 mutation、授權和 revoke 在同 issuer lock 下串行化；
body receive 完成後，在 lock 內讀取 clock、驗證 session，並完成 M2A 呼叫，沒有跨 await 持鎖。
ASGI 透過 thread worker 執行 SQLite 工作，不阻塞 event loop。

同一 sandbox 和同一 issuer 的新 Gateway instance 可讀回相同 order/digests，不 send、recover 或寫 DB。
GET 的無副作用保證涵蓋 M2A ledger/SQLite；ephemeral rate counter 仍會計數。
新 issuer 會讓舊 credentials/capability 全部失效；不宣稱跨 process 真實 authentication persistence。
已 consumed 的 exact confirm 即使 challenge 後來過期仍可回 receipt，這是 M2A canonical 行為；
未 consumed 的過期 challenge 回 409，不能建立新 outbox。

UNKNOWN 撤單不代表已撤單。若 reconcile 得到 CANCEL_PENDING，需再次明確 cancel 才由 M2A
建立 cancel outbox；mock runner 另行 dispatch。保留預留、不釋放、不補算 settlement。

## 重跑

既有 `.venv` 有 FastAPI/Starlette，但本次探查缺少 httpx，不安裝 dependency。
測試直接送入標準 ASGI scope、http.request/response messages，走完整 app boundary 和真實 temporary SQLite，
沒有直接呼叫 route handler，沒有 TCP、uvicorn 或正式 API probe。

```powershell
$env:TEMP = Join-Path (Get-Location) '.tmp'
$env:TMP = $env:TEMP
.\.venv\Scripts\python.exe -B -m unittest discover -s execution_simulation_gateway/tests -t . -v
.\.venv\Scripts\python.exe -B -m execution_simulation_gateway.tests.demo
.\.venv\Scripts\python.exe -B scripts/check-architecture.py --constraints execution_simulation_gateway/constraints.toml --debt execution_simulation_gateway/debt.toml
```

`tests/demo.py` 是 DIL-safe、兩個 synthetic account 並行的完整 HTTP 示範；stdout 只輸出狀態與 mock effect 數，
不輸出 token、principal/account、challenge 或 raw ledger。Temporary sandbox 只在 context lifetime 內存在。

## 後續版本與風險 gate

此 v1 只能作本機隔離測試，不能被掛到正式 FastAPI。Real Auth Owner integration、真實 account
permission lookup、正式 key/session lifecycle、部署/host acceptance、UI、MCP writes、broker/M3 Live
均 BLOCKED，另需明確授權與獨立設計／review。即使交易模式測試通過，也不表示 broker 或 exchange
支援。M2A.2 settlement 尚未整合；若增加帳本視圖，只能由 M2A 提供 additive read API。

本套件 constraints 與負例測試禁止 production caller、直接 DB/network/provider/broker IO 與重算
assess/transition；原 M1/M2A manifests 未放寬。驗收見指定任務資料夾 Acceptance.md。
