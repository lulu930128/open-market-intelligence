# 台股 ETF Provider 正規化

## 目標

- 將 ETF 的 PCF、成分曝險與盤中 iNAV 從元大專屬判斷，改為發行商中立、可逐步擴充的 backend provider contract。
- 建立穩定的 ETF 身分解析與 provider capability registry，讓所有 ETF 都能得到正確的 `supported`、`provider_not_connected`、`missing`、`stale` 或 `current` 狀態。
- 建立欄位級 canonical composition，讓市價、盤後 NAV、盤中 iNAV、折溢價、績效基準、基金持股與 PCF 可由不同官方來源組成，而不是因單一 provider 缺資料就整張卡片失效。
- 明確區分「尚未接來源」、「尚未發布」、「不適用」、「來源失敗」與真正缺值，並讓 backend 成為這些語意的唯一判定者。
- 在不破壞既有公開 API consumer 的前提下，逐步擴大 TWSE／TPEx ETF 發行商覆蓋。

## 非目標

- 第一個 milestone 不宣稱所有發行商的 PCF／iNAV 已接通。
- 不讓 frontend、MCP 或 Kuro 自行辨識發行商、解析 PCF 或計算 freshness。
- 不把成分曝險等同基金公司宣告的完整持股，也不把缺值轉成 `0`。
- 不要求所有 ETF 都有相同資源；主動式／被動式、現金／實物申贖與境內／跨境 ETF 必須允許不同的 `applicable` 狀態。
- 不把指數成分、基金實際持股與 PCF 申購買回籃子合併成同一份「成分股」。
- 不加入自動交易、下單或無邊界的全市場 refresh。

## 硬性限制

- 維持 `router -> service -> provider/parser` 依賴方向；provider 不讀寫 DB。
- GET overview 維持 cache-only；外部請求只允許由明確 refresh path 觸發。
- 保留 `/api/market/etfs/{stock_id}/overview`、`/api/market/etfs/{stock_id}/refresh` 與既有 response fields，避免影響 frontend、AI／MCP 對外介面。
- 新增 canonical valuation／resource-state 欄位時採 additive compatibility；既有欄位與 consumer fallback 在遷移期保留。
- 保留 freshness、partial、missing、provider failure 與 request count 可見性。
- 折溢價只能使用日期、session 與估值基礎相容的市價和 NAV／iNAV 計算；不得跨日湊值。
- DB schema 若需變更必須使用 migration；不得刪除或重建本機 SQLite。
- 單次 refresh 維持最多 8 次 provider HTTP request 的既有公開上限。

## 背景

- Repo: `C:\project\Open Market Intelligence`
- 相關系統：backend market service、provider adapters、SQLite cache、provider events、frontend ETF 資料頁。
- 已知現況：provider registry 與七家大型投信 adapter 已建立，但不同發行商只提供部分資源；MOPS 盤後 NAV 也是 shared-but-partial，不能作為唯一完整來源。
- 已知資料組合缺口：ETF 上方收盤價目前依附 `daily_nav` record；當 NAV 缺少時，即使一般行情已有收盤價，UI 仍顯示空白。
- 已知語意缺口：主動式 ETF 的績效參考基準、基金持股、指數成分與 PCF 申贖籃子尚未完整分離；現金申贖沒有實物籃子時也缺少 `not_applicable` 表達。
- 產品邊界：台股是 OMI 核心市場；backend 是資料、freshness 與 provider capability 的真相來源。

## Capability contract

| 項目 | 契約 |
|---|---|
| Product scope | 台股 ETF 研究資料；不含自動交易。 |
| Target | `instrument_type=etf`；第一階段 TWSE，後續納入 TPEx；symbol 使用現有 `StockMaster.stock_id` normalization。 |
| Provider | profile=`twse_openapi`；market price 使用既有台股 quote／daily bar；daily NAV 採 MOPS、投信官方 NAV 或語意相容的 PCF unit NAV 欄位級優先序；PCF／iNAV／holdings 由 issuer provider registry 選擇。 |
| Resource | market price、daily NAV、iNAV、derived valuation、benchmark、fund holdings、index constituents 與 PCF 是獨立 resource；不得互相冒充。 |
| Freshness | `Asia/Taipei`、交易日與 session-aware；盤後 NAV 預期 21:00 後發布；holdings、PCF 與 benchmark 各自保留 `as_of`／effective／reference 日期。 |
| Request bounds | profile 1、NAV 1；各 issuer resource 宣告自身 request count；整次 refresh 上限 8。 |
| Persistence | 沿用 ETF profile、NAV、PCF snapshot/components、iNAV snapshot；canonical valuation 優先以 projection 組成，不覆寫原始 observation；新增 holdings 時使用獨立 snapshot／row schema 與 migration。 |
| Failure | 明確區分 `current`、`closed`、`delayed`、`stale`、`partial`、`missing`、`not_published`、`not_applicable`、`provider_not_connected` 與 `provider_failed`。 |
| Transaction | service 擁有 market-data commit/rollback；provider event 使用既有隔離流程。 |
| Public API | 保留既有 method、path、query 與欄位；以 additive `valuation`／resource state 投影提供正規化結果，consumer 遷移完成前保留 legacy fallback。 |
| AI contract | 本階段不擴增 AI payload；既有 backend API 仍是後續唯一來源。 |
| Consumer | frontend 依 backend canonical valuation 與 resource state 呈現；核心估值狀態不被 PCF／holdings 等次要資料拖累。 |
| Validation | provider/registry pure tests、composition/date-alignment tests、service regression、migration tests（若有）、API contract inventory、frontend typecheck/e2e 與 representative runtime screenshot。 |

## 交付物

- 通用 ETF domain records、provider resource contract、registry 與 resolver。
- 元大 PCF／iNAV adapter 遷移到 registry，現有行為與 request budget 保持相容。
- 發行商與 resource 支援狀態的測試，以及未接入 provider 的安全降級測試。
- Canonical ETF valuation projection、欄位來源優先序與日期相容規則。
- Benchmark／holdings／index constituents／PCF 的獨立資料與適用性 contract。
- 以 00981A 與 00878 為代表案例的 backend、frontend 與 runtime 驗收證據。
- 後續發行商接入與 TPEx 擴充的 milestone 與驗證紀錄。

## 完成條件

- Service 不再含元大專屬分支或來源 hardcode。
- 每檔 ETF 可由 backend 得到 resource-level capability 與正確來源；未接入者不會被誤標為已支援。
- 新增發行商只需新增 adapter、registry binding 與 conformance tests，不需修改 public consumer contract。
- 相關 backend regression、API contract 與 transaction tests 通過。
- 盤後 NAV 缺少時，一般市場收盤價仍可獨立呈現；折溢價只有在輸入時點相容時才產生。
- 主動式 ETF 不再被標為缺少「追蹤指數」；現金申購買回沒有實物籃子時不再被標為 provider 缺口。
- 00878 缺 PCF／holdings 時仍可正確顯示核心估值有效，00981A 則能精確指出是哪個估值資源不足。
- 長期完成時，TWSE／TPEx ETF universe 有可稽核的 issuer/provider coverage matrix。

## 未決問題／假設

- 發行商的官方 NAV／PCF／iNAV／holdings 介面、授權與穩定性不同，因此「通用」代表共同 contract 與安全降級，不保證所有 issuer 能使用相同 endpoint。
- PCF `unit_nav` 只有在官方欄位定義與 `reference_date` 明確符合盤後單位淨值語意時，才能成為 canonical daily NAV fallback。
- 主動式 ETF 的績效基準與投資組合來源需逐家驗證；不能僅依名稱或前端文案推論。
- Holdings 的揭露頻率與完整度可能因投信、產品及法規而異，必須保留 `as_of`、coverage 與 source limits。
