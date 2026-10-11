# Manual Trading Execution v1

## 2026-10-11 backend milestone checkpoint

[Execution backend](ExecutionBackendMilestone.md) 新增同一 M1/M2A owner 下的 retained LOCAL_MOCK
ledger、receipt-time contract、headless manual commands 與 effect 前檢查。
未來 UI owner 為 MCP App；現有 frontend/AI trade actions 不接線。
完整 G1 real ingress 與 G2/G3/G4 仍未通過，不能由 source/local mock 推定已具備 real execution。

## 2026-10-11 additive isolated manual mock checkpoint

M1 preflight與reducer保持原owner。新增 [manual mock bridge](../../execution_manual_mock/README.md)：
PowerShell人工preview/confirm/submit與status/query/reconcile/cancel，M2A唯一transaction/outbox/audit，
封閉fake SDK直接消費canonical Draft，不使用M3 stub作production contract。
此checkpoint只解鎖isolated loopback mock測試；下文M1 runtime blockers描述其原範圍。
**正式OMI runtime、broker live與交易frontend仍BLOCKED**；精準界線見
[handoff](../exec-plans/completed/omi-manual-mock-20261011/Handoff.md)。

## 現有範圍與驗收邊界

M1 的 executable truth 是 root [`execution/`](../../execution/README.md)：獨立、純 Python、stdlib-only 的離線領域與 in-memory 測試 harness。所有證據必須明示 `SYNTHETIC`；所有預覽、事件與結果均標示 `simulated=true`。確認只建立 `SIMULATED_PENDING`，不代表已送券商、已被券商接受或真實成交。

本文件新增 M1 current architecture truth；不更動既有 Market Data／Research invariants。架構 index、OperatingModel、shared constraints 等檔案屬本輪開始前的 dirty work，保持不變。獨立 [constraints](../../architecture/execution-constraints.toml) 與 [debt](../../architecture/execution-debt.toml) 由既有 architecture 測試入口發現；M1 不接受 architecture debt 豁免。

| 驗收面 | M1 範圍 |
| --- | --- |
| Source | typed contracts、純 preflight/reducer、in-memory 冪等、synthetic 正常／拒絕／競態測試與 negative guards |
| Runtime | **BLOCKED**：無服務、route、entrypoint、worker、migration 或正式 lifecycle adoption |
| Live | **BLOCKED**：無真實證據 owner、SDK、login、送單、查單、對帳或撤單 |
| Product | **BLOCKED**：無 authenticated app 操作、正式前端或使用者實盤驗收 |

Source 通過不解除任何其他 gate。已授權的 [M2A 隔離 application](ExecutionSimulationM2A.md) 另有 source 文件；正式 runtime、M2B／M3 仍需另行授權，以下 future 設計要求不是已實作功能。

## Owner 與 dependency direction

```text
目前 M1
synthetic immutable fixtures + explicit time
    -> execution.validation.assess
    -> execution.service.OfflineExecution
    -> execution.state_machine.transition
    -> simulated receipt + traceable in-memory events

未來（全部 BLOCKED）
authenticated app-only manual action
    -> independent execution command owner / durable transaction
    -> single isolated execution worker / dedicated broker session
    -> broker order/query/reconcile/cancel adapter

market-rule / account-fact / permission owners
    -> explicit trusted snapshot handoff -> execution preflight
```

| Owner | 責任與禁止事項 |
| --- | --- |
| Market Data／Resolver | 市場 identity、交易狀態、session、價格單位、tick/lot rule 及時間證據的未來來源；M1 不 import、不呼叫、不刷新任何現有 provider |
| Account facts | 未來提供帳戶有效狀態、可用額度／可賣量與預留語意；不從 Portfolio valuation 推導可下單額度 |
| Permission owner | 未來提供經身分驗證的 principal/account 授權、交易限額與政策版本；M1 只有 synthetic fixture |
| Execution domain | 草稿 admission、綁定證據的 preview/confirmation、執行意圖、冪等、狀態／事件；不擁有市場資料選源或 freshness fallback |
| Research／AI／MCP／Kuro | 維持唯讀 consumer，沒有本套件 caller，也沒有任何交易 action tool；不得透過 `omi.ask` 或行情 GET 寫入 |
| PAOS broker bridge | 既有服務屬 PAOS-owned 唯讀隔離服務；不借用登入 session、連線、process 或 client |
| 現有 OMI KGI quote/account provider | 保留原 quote/account lifecycle；不是 execution worker，也不得偷偷兼任 |

M1 使用合約自帶 instrument identity，刻意不 import `app.market.providers`、`app.ai`、Portfolio、PAOS、`kgisuperpy` 或其他 app 模組。此處只有 immutable value objects，沒有第二個 provider/resolver。未來 snapshot ingress adapter 必須在明確授權的 owner boundary 定義，不能直接把 stale watchlist、行情畫面或 Portfolio 數字轉成 execution truth。

## 合約與證據

Typed contract 位於 [`contracts.py`](../../execution/contracts.py)；沒有新增 OMI HTTP/Pydantic schema。

| 合約 | 必要語意 |
| --- | --- |
| `Instrument` / `Draft` | TW、現股或 ETF、TWSE/TPEX、BUY/SELL、以「股」為單位的 integer quantity、BOARD/ODD、TWD/PER_SHARE、account ID、client request ID；v1 保留 CASH/LIMIT/DAY，v2 擴充見下節 |
| `EvidenceRef` | snapshot ID、明確 owner、synthetic origin、aware `observed_at`、`valid_from`、`valid_until`；`valid_from <= observed_at <= now < valid_until` |
| `MarketFacts` | 完全相同的 instrument/venue/lot/currency/price unit、session ID、order-entry-open 與 tradable 的獨立明示值、價格上下限、完整 tick bands、lot rule |
| `AccountFacts` | 同帳戶／標的／幣別、active、available cash、sellable shares；缺值不補零 |
| `PermissionFacts` | principal/account/instrument、allowed sides/lots、can-trade、quantity/notional ceiling、買進費用預留 fixture 金額 |
| `Assessment` / `Preview` | 確切 draft 與完整 evidence、notional／required cash、期限、digest、challenge；保留可核對的所有計算輸入 |
| `Confirmation` | preview ID、token、digest、principal、嚴格 boolean `user_confirmed=True`；一次明確 `CONFIRM_SYNTHETIC_DRY_RUN` 動作 |
| `SimulationEvent` | event ID、preview identity、事件時間、fixture report sequence、事件種類、cumulative filled shares；control 不得偽裝 report |
| `DryRunResult` / `AuditEvent` | simulated、non-durable、目前狀態、成交股數、simulation attempts、取消意圖；audit 有時間、順序、操作、digest、狀態、reason 及已接收的原始 simulation event，不記錄 token |

所有 snapshots、preview、result 和 event 使用 frozen dataclasses，集合使用 tuple/frozenset。呼叫時仍驗證型別；拒絕 boolean/float/string quantity、float price、NaN／Infinity、缺失證據或原始字串代替 enum。不做隱含 coercion。

M1 的 policy bounds：單一證據有效窗最多 300 秒；preview TTL 最多 60 秒，且不得超過任一 evidence 的有效期限。時間由 caller 明確傳入且不得倒退，不存取系統時鐘。這些是離線 gate 上限，不是已驗證的券商／交易所 freshness policy。

Tick bands 必須有序、連續、無重疊且覆蓋允許的價格區間；下界 inclusive、上界 exclusive，價格必須是所屬 band tick 的整數倍（origin=0）。本套件不硬編碼交易所 tick 表。BOARD 以可信 board size 的倍數檢查；ODD 小於該 size 且 step=1。整股／零股皆只模擬所提供 session/lot 的 rule，不推定盤後、預約或特殊交易方式已支援。

v1 BUY 檢查 `quantity * limit_price + supplied buy_fee_reserve <= available_cash`；v1 SELL 檢查可賣股數。v2 融券／借券另需資源與政策證據。Decimal 計算使用獨立 precision context，防止 caller 的低精度設定改變金額或 tick 判斷。費用預留是 synthetic 輸入，不是正式費率／稅費計算。

`SYNTHETIC` 與 owner 字串是離線型別 admission，不構成可信身份或簽章證明。真正的 owner provenance、snapshot authentic handoff、permission revocation、即時額度預留／跨委託消耗仍未實作。M1 對不同 request 的獨立模擬不宣稱會保留現金或持倉。

## Preview → 確認 → 模擬

下列確認與 reducer 流程由 v1/v2 共用；v2 的額外 admission 見本頁末節。

1. `assess` 是純 preflight；`preview` 驗證草稿與全部 snapshots，建立最短有效期限。
2. canonical digest 綁定 preview identity、完整草稿、全部 evidence、assessment 與建立時間。token 是由 caller 提供的 synthetic fixture key 對 digest 計算 HMAC；不讀取環境 secrets，也不產生真實 2FA。
3. caller 必須提交原 preview、相符 token/digest/principal，以及明確 confirmation boolean。篡改 account、標的、price、quantity、evidence、費用、期限或 payload 型別均拒絕。
4. 首次確認在期限內再次 preflight；僅建立一次 `SIMULATED_PENDING`。資料過期不得沿用 challenge，需新 request ID 與重新人工確認。
5. `apply` 只接收 synthetic event；沒有 adapter callback、網路或自動排程。`result` 是純讀取，不延長 TTL、修補 state、刷新或寫 audit。

In-memory idempotency key 是 `(account_id, client_request_id)`。同 key 同草稿／證據的 preview 重試回傳同一份 preview；草稿不同回 `IDEMPOTENCY_CONFLICT`，證據不同回 `EVIDENCE_CONFLICT`。已消耗的 key 不建立新 preview。

相同確認 command 重播只回傳目前 receipt（包括期限已過、UNKNOWN 或 terminal），audit 標示 `IDEMPOTENT_RECEIPT`，不再消耗 challenge、增加 attempt 或變更 order state。這與「用舊 token 授權另一筆操作」不同：後者拒絕。先取消未確認 preview 會消耗該意圖，attempts=0；token 不可再確認，後到回報也不可形成成交。

## 狀態、未知與競態

`transition(order, event, now)` 是 pure reducer。`OfflineExecution` 只提供單一 object 內的 repository/audit；caller 必須序列呼叫，沒有 thread/process 安全保證。

| 事件／情境 | 結果 |
| --- | --- |
| 首次有效人工確認 | `SIMULATED_PENDING`，attempts=1 |
| fixture accepted / partial / full / rejected | 對應 `SIMULATED_*` 狀態；成交量使用單調 cumulative shares |
| 未確認草稿取消 | `SIMULATED_CANCELLED`，attempts=0 |
| 已確認後取消 | `CANCEL_PENDING` 只是意圖；需要明確 cancelled report 才代表模擬取消 |
| 活躍操作或取消逾時 | `UNKNOWN`；不推定未送出，也不自動重試 |
| UNKNOWN 明確啟動 reconciliation | `RECONCILING`；只能由後續查單 fixture report 解決 |
| UNKNOWN／RECONCILING 中取消 | 記錄取消意圖，保持未知／對帳狀態；不虛構取消成功 |
| 取消期間 partial fill | 保留 `CANCEL_PENDING` 與成交數，不能抹除取消意圖 |
| 已取消後晚到 partial/full fill | 更新成交數；partial 保留取消剩餘量，full 收斂成 `SIMULATED_FILLED` |
| full fill 後晚到 cancel acknowledgement | 保持 full fill；不能回退成交量 |
| terminal rejected/cancelled 與新回報矛盾 | 保留新成交 evidence 並進 `RECONCILING`，不能靜默當作重新接受 |
| 同 event ID 同內容／不同內容 | 前者回目前狀態，後者 `EVENT_ID_CONFLICT` |
| 同 report sequence 不同內容 | `REPORT_SEQUENCE_CONFLICT` |
| 舊 sequence 晚到 | 記入事件與 `OUT_OF_ORDER_IGNORED`，不回退 state/filled；synthetic sequence 是本輪唯一排序依據 |

時間回退、未來事件、超額成交、累積成交減少、無確認回報、UNKNOWN 未先對帳的回報等均 fail closed。拒絕不更新 order；可合法接收的 out-of-order／duplicate 事件保留 audit reason。

## 隔離機械保護

- 專屬 TOML constraints 限制 provider/app/consumer/IO import、動態執行、隱含 clock、transaction 與 production caller；debt 為空。
- AST negative tests 對 domain 採明確 stdlib import allowlist，拒絕網路／DB／檔案／subprocess／SDK／FastAPI 與測試 fixture 的反向 import。
- 既有 backend、agents 與 frontend source 只做靜態掃描，禁止新增 execution import、動態 module 引用或 execution/order routes。既有 AI 的 `execution` schema 欄位不是本套件引用。
- Negative fixtures 證明 import/route guards 會拒絕違規程式；IO tripwire tests 在離線 workflow 中封鎖檔案、網路、SQLite 與 subprocess。
- 這些 guards 是 source regression 防線，並非可以執行任意不可信 Python 的 sandbox。

## 未來 M2／M3：完整交易流程的必要原則（全部 BLOCKED）

### Session 與 worker owner

KGI execution 必須有獨立、單一 lifecycle owner 的 dedicated session／worker，不得把下單偷偷放進 PAOS read-only bridge 或 OMI `kgi_superpy` quote/account session。若 SDK 或券商限制同帳戶多 session，需先以官方能力與隔離測試確認可行設計；不可假設另開 process 就沒有互踢／登入衝突。

必須定義 session generation、帳戶綁定、單 worker lease、fencing token、啟停 lifecycle、重連與 callback 去重。多 worker 同時啟動、lease 過期、新舊 session callback 交錯、query/cancel/send race 都必須有 acceptance evidence；沒有 gate 通過不得 live。

### 送單與 durable idempotency

server-side command owner 驗證身分／帳戶／permission、最新 market/account facts、kill switch 與風險政策。durable transaction 必須在任何 broker side effect 前原子保留 principal/account/request key、canonical payload hash、snapshot versions、confirmation 消耗、預留額度、order intent 與 append-only audit/outbox。

唯一鍵/CAS/fencing 防跨 worker 重送；重啟／crash window 不能因記憶體清空而再送。不同 payload 同 key 必須 conflict。若 broker 不提供等價 client ID 去重，需承認無法僅靠 application receipt 保證 exactly-once，不得宣稱 at-most-once transport 等於 exactly-once execution。

### 查單、對帳與 UNKNOWN

送單逾時、斷線或 callback 不明都屬 UNKNOWN，禁止自動當作失敗重送。query/reconcile 必須比對 broker order identity、account、symbol、side、quantity、price、session、累積成交與取消剩餘量，保留 source event time、received time、序號與來源。

查無資料不立即等於「沒送到」：需明確 broker consistency window、bounded query policy、人工處置與證據。未解除未知的意圖維持凍結；新送單需新確認，不由 read path 暗中觸發。trade/fill reconciliation 不由 Portfolio sync success 代替。

### 撤單與晚到成交

撤單是另一個明確、authenticated、冪等 command；只以 broker order identity 操作。撤單 request/ack/confirmed cancellation 分開，cancel timeout 仍 UNKNOWN，不能釋放已成交或仍未知的預留額度。晚到／部分成交、cancel reject、full fill、重複 callback、順序錯亂與 reconnect replay 必須以 durable ledger 收斂。

### App-only 身分、challenge 與 2FA

App-only 是呈現範圍，不能作為授權證明。未來任何 authenticated app action 仍需 server-side principal/account binding、session/auth expiry、origin/CSRF 防護、權限與金額限制、rate limit、審計與操作取消權限；不新增公開 MCP action 或讓模型代填 confirmation。

preview digest 必須綁定所有使用者將承擔的條件及政策版本；短效、一次性 nonce／challenge 在 server 原子消耗並防 replay。送單前資料或條件改變，必須重作 preview/confirmation。所需 broker/user 2FA、step-up auth 與撤權流程需另行驗收；M1 synthetic HMAC 與 boolean 不是登入、人類存在證明或 2FA。

### 安全 rollout 與 kill switch

未來順序：離線 source → adapter fixture/沙箱 → authenticated app dry-run → 獲授權的小範圍實盤 canary → 擴充。每一步獨立授權、可追蹤、可停止。live enable 預設 fail closed；kill switch 必須由 execution owner 在 admission 及 side effect 前再次檢查，阻擋新送單，但保留受控查單、對帳和人工撤單能力。

停止或 rollback 不刪除 durable ledger，不把 UNKNOWN 清成失敗，不在重啟時重播 send。允許帳戶／標的／時間窗／單筆及累積限額、監控、告警與事故復原演練均為 future acceptance。

## 尚待驗收的 gates

| Gate | 狀態／所需證據 |
| --- | --- |
| 真實市場／帳戶／permission snapshots | **BLOCKED**：owner、authentic handoff、時間與 rule version、額度預留、revocation |
| 正式 app-only action API 與前端 | **BLOCKED**：另行授權、server auth/account identity、人工操作與錯誤 UX |
| challenge／2FA | **BLOCKED**：安全 nonce、atomic consume、replay/expiry/revocation 與 step-up policy |
| KGI execution session／worker | **BLOCKED**：獨立 owner、與 quote/PAOS session 共存、fencing、跨 worker race |
| durable journal／idempotency | **BLOCKED**：唯一鍵、交易邊界、crash recovery、outbox 與重啟去重 |
| broker adapter | **BLOCKED**：send/query/reconcile/cancel mapping、identity、timeout、callback ordering 與錯誤證據 |
| 真實交易規則與成本 | **BLOCKED**：整股／零股 venue/session、tick/lot、限制、費稅與額度政策驗證 |
| kill switch／rollout／復原 | **BLOCKED**：實際阻擋新 send、保留查單撤單、bounded canary 與人工驗收 |

M1 v2 包含下述 synthetic 融資／融券／借券／市價 instruction，仍不包含真實交易、衍生品、期貨、選擇權、US 或其他市場、長效單、自動下單。程式不包含可以直接切成 live 的 flag。

## M2A.1 additive order contract v2

`Draft.contract_version=1` 保留原 frozen constructor 與 CASH/LIMIT/DAY 行為；新模式必須明確設定 `contract_version=2`、`PositionAction`，並提供完整新 evidence。side、funding、position action、order kind、lot、venue、phase、TIF 分開建模。`DAY` 在此階段表示當日有效（ROD 語意），沒有 vendor mapping；IOC/FOK、直接現金還款／現券償還不是本階段 order command，不能偷偷換成另一種委託。

| 操作意圖 | funding | side / position_action | 必要資源 |
| --- | --- | --- | --- |
| 現股買進 | CASH | BUY / OPEN | cash + fixture fee reserve |
| 現股平倉 | CASH | SELL / CLOSE | 現股 sellable shares |
| CREDIT / MARGIN_BUY | MARGIN | BUY / OPEN | 自備款、available credit、maintenance |
| 賣出融資持倉以待還款 | MARGIN | SELL / CLOSE | margin position shares；本階段不入帳還款 |
| SHORT_SELL_MARGIN | SHORT_SELLING | SELL / OPEN | 融券 borrow shares、獨立 collateral、maintenance |
| BORROWED_SHORT_SELL | LEND_SELLING | SELL / OPEN | 借券 borrow shares、獨立 collateral、maintenance |
| 人工 COVER | SHORT_SELLING / LEND_SELLING | BUY / CLOSE | 對應 short/lend position、全額買回 cash + fee |

`MarketTradePolicy` 隸屬既有 market-rules owner，綁 instrument（含 asset／venue）、lot、session ID、current market snapshot ID、version 與 EvidenceRef TTL。`CreditFacts` 隸屬 account-facts owner，綁 account／instrument／currency／current account snapshot ID、version 與 TTL。permission 明示 synthetic authenticated principal/account、funding entitlement、intraday ceiling／used risk。它们只表示 fixture assertions，並非真實 auth、owner 簽章或券商 entitlement。

新 snapshots 仍限單一有效窗 300 秒、preview 最長 60 秒；preview 到期不超過所有 evidence 最短期限。不得以行情畫面的最近價格補 evidence。信用額度、collateral、borrow、position、maintenance ratio／門檻缺值皆拒絕，不補零、不內建真實融資比例、利率或資格。

保守 admission 矩陣由 `execution.validation` 擁有，表格只說明 gate，不是第二份 provider inventory：

| 範圍 | LIMIT / DAY | MARKET / DAY |
| --- | --- | --- |
| TWSE/TPEX、stock/ETF、CASH、BOARD | 明示普通證券、同標的 policy 與 opening/continuous/closing phase | 只允許 `market_continuous`，同標的 market_orders=ALLOWED |
| TWSE/TPEX、stock/ETF、CASH、ODD | 只允許明示 `odd_lot_auction` policy | UNVERIFIED／拒絕 |
| TWSE/TPEX、stock/ETF、credit/short/lend、BOARD | 僅 continuous，加對應 capability=ALLOWED、權限與資源 | 同左，再加 market_orders=ALLOWED；受平盤下放空限制者拒絕 short MARKET |
| credit/short/lend ODD、未知 phase、特殊／未驗證證券、其他 TIF | UNVERIFIED 或 DENIED；不模擬有效委託 | 同左 |

每筆 instrument 的 capability 須獨立供應；stock、ETF 或 venue enum 本身不代表可融資／券／借券／市價。`ExecutionRejected` 保留穩定 code，並新增 typed `Capability.DENIED/UNVERIFIED` outcome。原始字串 enum、錯誤 side/action、snapshot owner/identity 不符、unknown/stale evidence 均 fail closed。

MARKET 的 outward `limit_price` 必須是 `None`，LIMIT 則必須是有效 Decimal。MARKET BUY 以可信 range ceiling 計算 cash／margin credit；SELL 以 floor 計算最小估值，風險／short collateral 以上界計算，賣出款不抵預留或變可用現金。LIMIT SELL 的 collateral/risk 亦以市場上界保守估算；不同資源與可賣現股、融資持倉、融券／借券持倉分開。價格上下界均須有限、正值、符合 tick，無漲跌幅或缺上界則拒絕 MARKET。所有數量仍為 shares，所有金額／比例用 Decimal。

`SimulationEvent.fill_price` additive 欄位不改舊無價格回報；v2 fill 必須通過 M1 `validate_fill` 的 range／limit direction／tick guard，sequence conflict 同時比較價格。唯一 state reducer 仍是 `transition`，沒有第二套成交或結算 reducer。

規則核對（2026-10-10）：[TWSE 交易制度](https://www.twse.com.tw/zh/products/system/trading.html) 說明市價限盤中逐筆，開收盤集合競價不接受，無升降幅度／延長撮合／平盤下禁止放空亦有限制；[TPEX 交易系統](https://www.tpex.org.tw/zh-tw/mainboard/trading/rules/system.html) 與 [逐筆交易](https://www.tpex.org.tw/zh-tw/mainboard/trading/rules/continuous.html) 官方索引內容支持第一次撮合後至 13:25 及 short MARKET 限制（本輪頁面直讀失敗，PDF 回 403，未將無法取得的完整細節當作已驗證）。[KGI orderCreate](https://superpy.kgieworld.com.tw/kgipythonapi/guide/tw/orderCreate) 僅核對 CASH/MARGIN/SHORT_SELLING/Lend_SELLING 與 MKT/ROD 名稱；沒有 SDK、帳戶、資格或交易測試。

本階段不從 wall clock 推交易所 phase；synthetic market owner 必須給正確 session/phase/snapshot/expiry，例外或未核對模式拒絕。所有數值在 fixtures，2330 只是虛構代碼外形；未取得行情，也不宣稱上述模擬是某真實證券或帳戶可用交易方式。
