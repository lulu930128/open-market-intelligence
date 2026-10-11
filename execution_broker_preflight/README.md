# KGI Execution Preflight M3

**SYNTHETIC / simulated / no broker。Source-only，所有 runtime/live gate 均 BLOCKED。**

此套件只把官方文件欄位與假造的核准委託轉成可檢查標籤，並對假造事件做純轉換。
它不是 adapter、session manager、下單路由，也不是可直接傳給 SDK 的參數字典。
不依賴 `execution`、`execution_simulation` 或任何 OMI provider；不提供 live enable 開關。

## 使用與驗證

從 repo root 執行，使用一般 OMI Python，**不要使用 `.venv-kgi`**：

```powershell
.\.venv\Scripts\python.exe -B -S -m execution_broker_preflight.tests.run_offline
.\.venv\Scripts\python.exe -B -S scripts/check-architecture.py --constraints execution_broker_preflight/constraints.toml --debt execution_broker_preflight/debt.toml
```

`-S` 不載入 site packages，`-B` 不產生 bytecode。專用 runner 在測試前裝入 process-local
audit guard，阻擋 SDK／PAOS／production imports、網路、SQLite、subprocess 與寫檔。
測試只讀自有 source 及指定 repo source 做 AST 邊界檢查，不讀 credentials、帳戶或資料庫。
此 guard 是 regression 防線，不是一般不可信 Python 的安全沙箱。

```python
from execution_broker_preflight.mapping import POLICY_20261010, preview
from execution_broker_preflight.tests.fixtures import ORDER, RISK, UNITS, NOW

result = preview(ORDER, RISK, UNITS, POLICY_20261010, NOW)
assert result.status == "SYNTHETIC_PREVIEW_ONLY"
assert result.runtime_gate == "BLOCKED_UNVERIFIED"
assert result.labels.sdk_qty == 4  # 假造 12 股 / 每單位 3 股，不是真實台股換算。
```

## 純契約與 owner

| 契約 | 責任與限制 |
| --- | --- |
| `ApprovedOrderFixture` v1 | 最小 M1 handoff stub，caller 明確提供 approval；不證明 M1 實際核准或身份 |
| `OfficialPolicySnapshot` | 必須等於已支援的版本內容；新版本／欄位改動拒絕；網址是 evidence 引用，不由程式抓取 |
| `RiskFixture` | 同 entity/account/subaccount/currency/venue/symbol、時效與獨立 gate；所有 proof 預設 UNKNOWN |
| `UnitConversionFixture` | caller 提供股／SDK qty 與 board size、lot、scope、假 SDK version 和 evidence ID；缺失或不可整除就拒絕 |
| `BrokerCapabilityMatrix` | [mapping.py](mapping.py) 是此隔離 preflight 的唯一可執行能力表；未列組合拒絕 |
| `KgiOrderMappingPreview` | 只有 synthetic labels 或 BLOCKED reasons；即使 fixture 全通過，runtime 仍封鎖 |
| `KgiEventNormalizerFixture` | 不可變單筆假委託 event reducer；不提供持久化、重查、重送或 session lifecycle |

`Proof.SYNTHETIC_VERIFIED` 僅表示 fixture 的假前提，不能提供權限、簽章或 broker verification。
本機 SDK 版本、CA、API 簽署、帳戶能力和 session 共存都沒有驗證。
300 秒 evidence window 是此離線契約的保守上限，不是券商公布的 SLA。

## 交易語意

下表是官方 enum 名稱與本輪保守語意的對照；OPEN/CLOSE 是本地 position intent，**不是 SDK 欄位**。
允許列也只代表可測試的 synthetic 標籤，仍需所有 risk/unit fixture gate。

| 資金／部位 | action / intent | condition 候選 | 本輪判定 |
| --- | --- | --- | --- |
| 現股買進 | BUY / OPEN | CASH | synthetic preview |
| 已持有現股賣出 | SELL / CLOSE | CASH | synthetic preview，需可賣持股證據；不使用 CASH_SELLING |
| 融資買進 | BUY / OPEN | MARGIN | synthetic preview，需信用與擔保／交割 gate |
| 融資賣出償還 | SELL / CLOSE | MARGIN | INFERRED，文件未充分證明 repayment routing；BLOCKED |
| 融券賣出 | SELL / OPEN | SHORT_SELLING | synthetic preview；不可當作借券額度 |
| 融券買回 | BUY / CLOSE | SHORT_SELLING | INFERRED，精確 cover routing 未確認；BLOCKED |
| 借券賣出 | SELL / OPEN | Lend_SELLING | synthetic preview，需獨立 borrow allocation |
| 借券買回／還券 | BUY / CLOSE | 無安全 mapping | BLOCKED；買股與還券不可混為單一步驟，也不 fallback CASH |
| 現股先賣 | SELL / OPEN | CASH_SELLING | 文件名稱不一致，BLOCKED |
| 其他方向／intent | 任意 | 無 | NO_MAPPING；不自動修正方向或資金種類 |

enum 拼字來自 [Order.create_order](https://superpy.kgieworld.com.tw/kgipythonapi/guide/tw/orderCreate)。
一般現股與融資／融券 OPEN 語意是依文件定義建立的本地解讀，未宣稱 vendor 明列 OPEN/CLOSE 矩陣。
`CASH_SELLING` 在建立委託頁寫現股賣出，在
[Event](https://superpy.kgieworld.com.tw/kgipythonapi/guide/tw/eventObject)／
[Trade](https://superpy.kgieworld.com.tw/kgipythonapi/guide/tw/tradeObject) 頁寫現股先賣；此差異保留為缺口。
DayTrade enum 雖出現在 Event／Trade 文件，本輪沒有 mapping。

| 價格／時間／lot | 文件標籤 | 本輪機械限制 |
| --- | --- | --- |
| LIMIT | 正數價格 | 只接受 finite Decimal；tick／上下限由 caller 的 risk owner fixture 核准，不硬編碼 tick 表 |
| MARKET | `kgi.PriceType.MKT` | 精確 sentinel 字串；禁止 0、LimitUp、Reference 替代，不估市場成交價 |
| 存續 | ROD / IOC / FOK | 逐筆交易且 clock window 合格；ROD 不代表隔日有效 |
| 整股 | Common | 需 caller 證明的 board size 和 SDK unit；不可假設 qty=5 是 5 股或 5 張 |
| 盤中零股 | Odd | 本輪限 TWSE CASH / LIMIT / ROD、獨立 ODD session；TPEX 零股政策未另核對，BLOCKED |
| 盤後零股 | Odd_AfterMarket | 名稱已見文件；交易時段／單位／能力尚未收斂，BLOCKED |
| 盤後定價 | Fixing | 名稱已見文件；本輪 BLOCKED |

一般盤 MARKET／IOC／FOK 需 caller 指定 `CONTINUOUS`，並核對台北時間 09:00 ≤ t < 13:25。
時間符合不會自行推定已開盤、交易日或標的可以逐筆交易。
開收盤集合競價只限 LIMIT/ROD；瞬間穩定／延長撮合資訊 unknown 不放行 MARKET/IOC/FOK。
無漲跌幅限制、延長撮合，以及禁止平盤下放空的融券／借券賣出，不放行 MARKET。
限制放空的限價單需明確 reference price 且不得低於它。
本輪對盤後、延後收盤及額外市場特例採保守 BLOCKED。
依據：[TWSE](https://www.twse.com.tw/zh/products/system/trading.html)、
[TPEX](https://www.tpex.org.tw/zh-tw/mainboard/trading/rules/continuous.html)。

## 事件與 lineage

`EventFixture` 是手工假資料 envelope，**不是 raw SDK Event 的通用 parser**。
`event_id`、`request_id`、`generation`、`arrival_at`、`source_at`、`cumulative_shares`、
`quantity_evidence` 均為 fixture 補充欄位，不宣稱券商會回傳。
`OrderStatus` task tag 是本地快照分類；`error_code` 可承載假報告的 ErrCode，並非文件保證的 Event 欄位。
`source_ts` 保留原始 ts/op_time/modified_time；缺交易日期／時區時不自行補成完整 timestamp。

| 文件 evidence | fixture 行為 |
| --- | --- |
| 本地 request | requested，沒有 broker ID 或 broker acceptance |
| NewOrder / Pending + seqno，無 order_id | pending；seqno 保留為 opaque string |
| NewOrder / Success + order_id | accepted；允許新的 seqno，但必須有 caller 明確的同 request correlation |
| Deal / Success | 文件 quantity 是當次成交量；需 trade ID、已轉股數與單位 evidence；完整假歷史才可加總 |
| Trade.deals[].reportseq | 可作假 trade ID 來源；Event 文件未列此欄，不從 seqno 猜測 |
| CancelOrder / Pending 或 Success | cancel_pending；ACK 不直接宣告最終取消 |
| OrderStatus Cancelled / PartFilled_Cancelled | 需明確 cumulative 與已知 fill ledger 一致，再表示 cancelled remainder |
| Filled / PartFilled | 狀態文字不填造成交數；不把 modified_quantity 當 cumulative |
| Failed / msg | 新單失敗可 rejected；取消失敗不是原單 rejected，保持 unknown；errors 原樣留在 events |
| 重播／衝突 | 同 event ID 同內容只記重播；不同內容、broker ID／trade ID／scope 衝突進 unknown |
| 晚到／取消競態 | 舊 Pending／ACK 不回退成交；晚到 fill 保留成交量，完全成交優先；unknown 不自行解除 |

`seqno` 不做數字排序，不當成全球 order key。官方 Pending/Success 範例序號不同；
`OrderStatus.nid` 是最新有效序號。缺乏可靠 request-to-order correlation 時必須交給未來 reconciliation owner。
`complete_fill_history=False` 預設保留 cumulative unknown；fixture 不能用一筆 Deal 推定完整歷史。
本套件只允許與本地假 ledger 一致的 OrderStatus 快照，尚未實作 broker snapshot reconciliation。
詳細來源與 gate 見 [Evidence](../docs/exec-plans/active/omi-m3-kgi-preflight-20261010/Evidence.md)
及 [GateVerdict](../docs/exec-plans/active/omi-m3-kgi-preflight-20261010/GateVerdict.md)。

## M2A.2／M2B 交接與移除條件

M1/M2A.1 現有型別完全不 import、不修改。未來 M2A.2 需在自己的 owner 邊界實作顯式 conversion，
逐欄保留 funding、OPEN/CLOSE、shares、price kind、scope、currency、session 與 evidence。
stub 不可成為第二份 production canonical contract；當 typed handoff 核准且 consumer parity／負面案例通過後，
刪除或凍結此 test-only stub，將穩定語意移入當時批准的 canonical owner。
M2B 的 durable journal、交易鍵、跨 process idempotency、reservation 與 fencing 本輪只列 gate，未實作。
