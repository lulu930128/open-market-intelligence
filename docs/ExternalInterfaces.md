# OMI 對外接口與能力限制說明書

> 契約更新：AI 決策入口的 canonical contract 已收斂為
> `omi.decision.v4`，完整定義見
> [`architecture/OmiDecisionContract.md`](architecture/OmiDecisionContract.md)。
> HTTP、SSE、MCP 與 OpenAPI 只接受並回傳 v4；v2/v3 只存在於 backend
> 私有實作與回歸 seam，不是 consumer 可選版本。Consumer 應使用 v4 capability
> selection 與 `evidence.quality`，不應依賴 legacy `analysis.human_answer`
> 或 adapter 自製摘要。

> 文件基準：2026-07-24（Asia/Taipei）
>
> Backend OpenAPI：`0.1.0`
>
> AI 問答 contract：`omi.decision.v4`

本文件說明 Open Market Intelligence（OMI）目前可供 Frontend、Kuro、MCP、ChatGPT 或其他本機程式使用的接口，以及各接口可以做到、不能做到與必須保留的限制。它不是自動交易 API 規格，也不代表每一條 FastAPI route 都是承諾長期穩定的 public API。

## 1. 一頁結論

### 建議外部整合使用

| 使用情境 | 建議入口 | 原因 |
| --- | --- | --- |
| 一般市場問答、個股證據、跨市場 context | `POST /api/ai/ask` | 統一 target resolution、freshness、bounded refresh、evidence 與回答契約 |
| UI 或 Kuro 顯示處理進度 | `POST /api/ai/ask/stream` | SSE 提供 `status`、`evidence`、`tool_run`、`delta`、`final`、`done` |
| 本機支援完整 OMI contract 的 MCP client | repo 內 MCP：`omi.ask`、`omi.ask_stream` | thin adapter，能力最接近 Backend AI contract |
| ChatGPT 網頁或只需要安全讀取的外部 MCP | `OMI_search`：`omi.search` | 固定不呼叫 LLM、不寫 report，回傳 bounded compact payload |
| 特定圖表、資料表或維運工具 | `/api/market/*` 等專用 HTTP routes | 適合明確知道 schema 的 OMI 自家 UI，不建議當成單一跨市場 public contract |

### 目前可以做到

- 以同一個 AI contract 查詢台股市場、台股個股、自選群組、指數、期貨，以及美股、日股、韓股、Crypto、資源商品、FRED macro、portfolio、source health 與 capability status。
- 回傳 deterministic `data_only` evidence、可讀的 `brief`、完整 evidence `full`，以及在受信任條件下的部分 LLM `analysis` / persisted `report`。
- 先讀本機資料與 freshness，再由受信任的 backend 在預算內做 stale-first 外部刷新；失敗時保留 cached、stale、partial、missing 與 provider warning。
- 透過 `evidence.quality`、manifest、slots、source refs 與 readiness 告訴
  consumer 每個 capability 的資料能信到什麼程度。
- 使用 Frontend `/omi-data` proxy、stdio MCP，或本機 `OMI_search` HTTP MCP 將外部 consumer 保持在 Backend contract 之外。

### 目前不能做到

- 不能下單、改單、刪單、操作券商帳戶或執行自動交易。
- 沒有券商或授權行情 API 時，不能保證每一市場、每一檔股票都有逐筆、完整五檔或交易所等級即時資料。
- 尚未連接一般新聞事件、美股 options flow / earnings provider、JP TDnet、KR OpenDART 與港股市場 contract。
- 不是所有 target 都有 dedicated LLM decision/report path；目前 dedicated path 主要是台股個股、台股自選群組與美股個股。
- `OMI_search` 不是任意資料庫查詢 DSL，不能自由指定所有 dataset、欄位、日期區間、join、排序或分頁。
- Backend 目前是 local-first service，沒有全域 Internet-facing authentication；不能直接把 FastAPI port 暴露到公網。

## 2. 架構與責任邊界

```text
Frontend / Kuro / MCP / ChatGPT / local scripts
                         |
                         v
        Backend HTTP API / AI contract
                         |
                         v
 evidence + freshness + tool policy + bounded refresh
                         |
                         v
        local DB/cache + configured providers
```

硬性邊界：

- Backend 是市場資料語意、freshness、provider fallback、tool orchestration、AI reasoning 與回答 contract 的真相來源。
- Frontend、Kuro 與 MCP adapter 只能傳送需求、呈現結果，不應直接讀 OMI SQLite，也不應自行重做市場判斷。
- MCP adapter 不持有 provider secret，不把 OpenAI API key 傳給 consumer。
- `caller_profile` 只是 log/response label，不是授權憑證。
- 任何 `stale`、`partial`、`missing`、`blocked` 或 provider failure 都必須對 consumer 可見，不能轉成 0 或假裝 current/live。

## 3. 連線位置與 runtime 發現

### Backend

- 偏好位置：`http://127.0.0.1:8400`
- Health：`GET /api/system/health`
- Readiness：`GET /api/system/readyz`
- Swagger UI：`GET /docs`
- 完整 OpenAPI：`GET /openapi.json`

`8400` 是 launcher 的偏好 port，不是保證值。若 port 被占用、落在 Windows excluded range 或不是目前 checkout 的 runtime，launcher 會選擇其他 port。實際 URL 以以下資訊為準：

- `logs/launcher/<date>/launcher.log` 的 `selected=` 記錄。
- Tray menu 的 **Open API Health**。
- `GET /api/system/health` 回傳的 `runtime.project_root`、Python executable 與 app name。

### Frontend

- 偏好位置：`http://127.0.0.1:3000`
- Browser-side API 應使用 `/omi-data/...` proxy。
- Proxy 會把 `/omi-data/...` 轉到實際 Backend 的 `/api/...`。
- 不要在 component 內硬編碼 `8400`，也不要在 UI 重做 freshness 或 provider fallback。

### 目前實測的本機 MCP HTTP adapter

- Health：`http://127.0.0.1:8797/health`
- MCP：`http://127.0.0.1:8797/mcp`
- Server：`omi-search-mcp` `0.1.0`
- Public tool：`omi.search`

`127.0.0.1:8797` 只供本機或受控 tunnel 的 target 使用。ChatGPT 網頁不能直接連 localhost；需要 Secure MCP Tunnel 或等價的受控連線層。

## 4. 接口分級

2026-07-22 的正式 OpenAPI 有 348 個 operations：199 GET、112 POST、18 PATCH、15 DELETE、4 PUT。這只是 route inventory，不代表 348 條都是同等穩定或安全的 public contract。

### A. 建議 public integration surface

| Method | Path | 用途 | 副作用 |
| --- | --- | --- | --- |
| `GET` | `/api/system/health` | Process 與 checkout identity | 無 |
| `GET` | `/api/system/readyz` | Runtime / database readiness | 無 |
| `GET` | `/api/ai/tools` | 查詢目前 public AI tool schema | 無 |
| `GET` | `/api/ai/strategy-profiles` | 查詢策略 profile | 無 |
| `POST` | `/api/ai/ask` | 統一問答與 evidence contract | 預設無；受信任且明確允許時可 refresh/LLM/write |
| `POST` | `/api/ai/ask/stream` | 同一 contract 的 SSE 版本 | 同 `/api/ai/ask` |
| `GET` | `/api/ai/data-freshness` | 直接讀取 freshness | 無 |
| `GET` | `/api/ai/market-overview` | 直接讀取台股市場 overview | 無 |

外部 consumer 應優先把 `/api/ai/ask` 當成 OMI 的單一能力入口。Canonical
contract 是 `omi.decision.v4`；FastAPI app 的 `0.1.0` 不等同 AI contract
version。

### B. 專用市場 read APIs

| Route family | 目前用途 | 外部使用建議 |
| --- | --- | --- |
| `/api/market/*`、`/api/stocks/*` | 台股 quote、intraday、OHLC、技術、籌碼、指數、期貨等 | 適合 OMI UI/明確資料表；跨 consumer 問答仍優先走 `omi.ask` |
| `/api/us-market/*` | 美股 symbol、quote、daily/intraday、fundamentals、source health | Provider/cache coverage 不一，必須讀 freshness |
| `/api/jp-market/*` | 日股/指數、daily/intraday、基本面與 source health | 交易日與 disclosure 能力尚不完整 |
| `/api/kr-market/*` | 韓股/指數、daily/intraday、投資人/基本面與 source health | Provider 與 calendar 限制必須保留 |
| `/api/crypto-market/*` | quote、OHLC、market/derivatives metrics、collector status | 只做研究資料，不含私有帳戶或下單 |
| `/api/resource-market/*` | 黃金、能源等資源資產 quote/OHLC context | Yahoo chart best-effort，可能延遲 |
| `/api/reports/*` | premarket / aftermarket deterministic report | 讀取型；內容仍受底層 coverage 影響 |

專用 route 的 request/response schema 以當下 `/openapi.json` 為準。它們保留既有相容性，但不是跨市場統一語意層。

### C. 本機應用狀態 APIs

| Route family | 能力 | 注意事項 |
| --- | --- | --- |
| `/api/watchlists/*` | 自選群組/item CRUD、Radar、ranking、signals | POST/PATCH/DELETE 會修改本機狀態；backfill/refresh/snapshot 可能產生 job 或資料寫入 |
| `/api/portfolio/*` | 持倉 CRUD 與 summary | 屬於私人資料；AI `portfolio` target 只對 server-trusted caller 開放 |
| `/api/settings/*` | 本機設定 | 不應公開給不受信任 client |
| `/api/ai/memories/*` | AI research memory 的 list/create/update/archive | 寫入需 server trust；archive 保留稽核歷史 |
| `/api/ai/reports/*` | 查詢已保存 AI reports | 生成與保存需要 LLM/write policy |

### D. 維運與外部副作用 APIs

下列 routes 不應讓一般外部 consumer 隨意呼叫：

- `/api/sources/*/refresh`、`/run`：會抓外部資料並更新 cache/DB。
- 各市場的 `POST .../refresh`、backfill、sync、snapshot routes：可能耗用 provider quota、建立 job 或寫 DB。
- `/api/jobs/*/retry`：會重新執行工作。
- `/api/dispatch/send`、schedule run：可能發送 mail 或產生外部副作用。
- AI generate/save、memory create/update/archive：可能呼叫 LLM 或寫入持久資料。

即使某條 route 目前沒有全域 auth，也不代表它是安全的 public endpoint。

### E. 內部診斷 APIs

- `/api/system/provider-events`
- `/api/system/source-health-snapshots`
- `/api/raw-results/*`
- `/api/sources/*`
- `GET /api/ai/tools?include_internal=true`

這些接口適合維運、資料來源稽核或 trusted debug。不要讓 consumer 依賴 raw provider payload 來取代正式 evidence contract。

## 5. `POST /api/ai/ask`

### Request 核心欄位

| 欄位 | 目前規則 |
| --- | --- |
| `contract_version` | 唯一合法 public 值是 `omi.decision.v4`；v2/v3 會被拒絕 |
| `question` | 必填，1–4000 字元 |
| `target` | 建議 `{ "type": "auto" }` 或明確 `{ "type", "id" }`；不能再傳 legacy `scope_type/scope_id` |
| `mode` | `auto`、`data_only`、`brief`、`full`、`analysis`、`report` |
| `selection` | 選擇 required/optional/excluded capability、欄位、筆數與總 bytes |
| `output` | `evidence_only`、`decision` 或 `decision_with_evidence`；診斷 target 強制 evidence-only |
| `realtime_policy` | `cache_only`、`prefer_live`、`require_live` |
| `payload_level` | 舊 caller 的 evidence density 別名；v4 會正規化為 selection limits |
| `diagnostics_level` | `none`、`basic`、`debug`；只控制診斷資訊，不會提升回答 mode |
| `strategy_profile` | `balanced`、`technical_swing`、`short_term_momentum`、`chip_flow`、`fundamentals_growth`、`dividend_value` |
| `analysis_horizon` | `auto`、`intraday`、`short`、`swing`、`long`；`auto` 預設偏 swing |
| `allow_llm` | client 意圖；仍需 server trust 才能真的呼叫 LLM |
| `allow_write` | client 意圖；report/memory 類持久寫入仍需 server trust |
| `allow_external_fetch` | client 意圖；只允許 Backend 在預算內刷新，不授權 consumer 自己打 provider |
| `tool_budget` | bounded tool calls / external fetches / seconds |
| `refresh_policy` | 預設 `stale_first`、`before_answer=true`、`fallback_to_cached=true` |
| `market_data_params` | 市場特定且有上限的資料形狀參數 |
| `conversation_context` | 追問 context；優先使用 `last_target` |

### Mode 語意

| Mode | 回傳內容 | LLM | 寫入 |
| --- | --- | --- | --- |
| `data_only` | deterministic structured evidence | 否 | 否 |
| `brief` | human-readable 摘要與必要 evidence | 否 | 否 |
| `full` | 完整 evidence pack | 否 | 否 |
| `analysis` | non-persistent LLM analysis | 需要 trusted + `allow_llm=true` | 否 |
| `report` | LLM analysis 並保存 report | 需要 trusted + `allow_llm=true` | 需要 trusted + `allow_write=true` |
| `auto` | Backend 依 target、問題意圖與 policy 選擇 | 視 policy | 視 policy |

目前 dedicated LLM analysis/report path 主要支援：

- 台股個股 `tw_stock`
- 台股自選群組 `tw_watchlist`
- 美股個股 `us_stock`

其他 target 若要求 `analysis` / `report`，可能降級成 `brief` 或 `data_only`，並在 `mode.effective` 與 `warnings` 明確說明。Consumer 不應只看 request 的 `mode`。

### Tool budget 與 payload bounds

Backend public tool schema 的預設/上限：

| 控制 | 預設 | 上限 |
| --- | ---: | ---: |
| `max_calls` | 5 | 12 |
| `max_external_fetches` | 3 | 8 |
| `max_total_seconds` | 25 | 90 |
| `intraday_limit` | 依 payload level | 500 |
| `observations` | reader 決定 | 240 |
| `holding_limit` | reader 決定 | 500 |
| `health_limit` | reader 決定 | 500 |
| `radar_limit` | reader 決定 | 100 |
| `option_strike_limit` | 11 | 25，最少 3 |

建議使用：

- Kuro、一般 MCP、Frontend 與外部模型都使用同一份 v4；呈現或可朗讀稿由
  consumer 自行處理，不建立 Kuro 專用資料 contract。
- 優先用 `selection.include`、`selection.fields`、`selection.limits` 與
  `selection.max_response_bytes` 控制資料量。
- `payload_level` 只供舊 consumer 過渡，不應再作為唯一邊界。

### Request 範例

```powershell
$body = @{
  contract_version = "omi.decision.v4"
  question = "2330 現在的技術位階、回測區與失效條件"
  target = @{ type = "tw_stock"; id = "2330" }
  mode = "brief"
  output = "decision_with_evidence"
  realtime_policy = "prefer_live"
  selection = @{
    include = @("quote.snapshot", "technical.structure")
    max_response_bytes = 32768
  }
  diagnostics_level = "none"
  allow_llm = $false
  allow_write = $false
  allow_external_fetch = $false
  tool_budget = @{
    max_calls = 3
    max_external_fetches = 0
    max_total_seconds = 20
  }
  refresh_policy = @{
    mode = "stale_first"
    before_answer = $true
    fallback_to_cached = $true
  }
} | ConvertTo-Json -Depth 8

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8400/api/ai/ask" `
  -ContentType "application/json" `
  -Body $body
```

若要允許 stale-first refresh，應由 trusted caller 明確設定 `allow_external_fetch=true`，同時保持小型 `tool_budget`。這可能更新 market cache，但不等於允許寫入 AI memory/report。

## 6. Response contract 與判讀規則

### 主要欄位

| 欄位 | Consumer 應如何使用 |
| --- | --- |
| `ok` | 業務 request 是否成功；不能只靠 HTTP 200 |
| `target`、`resolution` | Backend 最終辨識的市場/標的 |
| `next_context.last_target` | 後續追問應帶回的 canonical target context |
| `mode.requested/effective/response` | 確認是否發生 policy downgrade |
| `answer_ready` | request 所需回答是否完成 |
| `facts_ready` | requested evidence facts 是否足夠 |
| `analysis_ready` | 是否已有 Human Answer |
| `decision_ready` | 可執行 decision sections 是否通過本地安全 invariant |
| `blocked_sections` | 哪些段落因資料或安全規則被阻擋 |
| `request_status` | `completed`、clarification、timeout/background 等實際狀態 |
| `fallback_used`、`cached_data_returned` | 是否用了 fallback/cached data |
| `analysis.human_answer` | 最安全的直接可讀答案 |
| `analysis.decision_contract` | 結構化 headline、action plan、scenarios、counter evidence、risks、data limits |
| `result` | 完整或 compact evidence pack |
| `freshness`、`evidence_passport` | 資料日期、來源品質、domain trust、decision readiness |
| `missing`、`warnings`、`source_refs` | 必須保留的資料缺口、警告與來源 |
| `tool_plan`、`tool_runs` | Backend 規劃/執行了哪些 bounded tools |
| `error` | Business error，例如 target not found |

`ok=true` 不代表資料是即時，也不代表 `decision_ready=true`。反過來，某個 decision section 被 block，也不應抹掉仍然有效的 facts。

### Slot status

`result.data.slots` 或 `result.data.compact.slots` 可能包含：

| Status | 意義 |
| --- | --- |
| `ready` | 本次有足夠資料可用 |
| `partial` | 有資料，但 freshness、coverage 或欄位不完整 |
| `missing` | 理應有資料但目前沒有 payload |
| `not_requested` | 能力存在，本次沒有要求或 policy 未允許 |
| `planned` | Contract 預留，adapter 尚未完成 |
| `not_applicable` | 對此市場/資產不適用 |
| `blocked` | 被 trust、quota、provider failure 或其他 policy 阻擋 |

Consumer 不得把 `missing` / `planned` 當作 0，也不得把 daily fallback 說成 live quote。

### Unknown target 與 ambiguity

- `target.type=auto` 若無法安全辨識，OMI 會回傳 clarification，而不是猜標的。
- 未存在的台股 stock master target 應回 `ok=false`、`answer_ready=false`、`error.code=TARGET_NOT_FOUND`，且不應啟動 refresh/analysis。
- Client 應同時處理 HTTP error、`ok=false`、`request_status`、`answer_ready=false` 與 SSE `error` event。

## 7. 支援的 `target.type`

| Target | 是否需要 `id` | 目前可做到 | 主要限制 |
| --- | --- | --- | --- |
| `auto` | 否 | 由問題解析市場與標的，支援 follow-up context | 模糊時會要求 clarification，不保證猜中簡稱 |
| `market` | 否 | 台股市場 breadth、量能、指數、籌碼與 movers context | 台股是核心；全市場不同資料集 coverage 可能不同 |
| `data_freshness` | 否 | TW/US/JP/KR/CRYPTO/ALL freshness | 只提供 data context，沒有 dedicated analysis/report |
| `tw_stock` | 是，如 `2330` | quote、daily/intraday、技術、籌碼、基本面、分點等 evidence 與 decision brief | 即時/五檔/分點取決於 provider、session 與 cache coverage |
| `tw_watchlist` | 是，numeric group id | 自選群組 context、ranking、Radar、signals、brief | snapshot/coverage 需由 scheduler 或明確 maintenance job 累積 |
| `tw_index` | 是，`TAIEX` / `TPEX` | 指數 quote/intraday/daily 與技術 context | 分項資料 cadence 不一；盤中 provisional 與收盤 finalized 必須區分 |
| `tw_futures` | 是，`TXF` / `MXF` / `TMF` | 最新 session quote（含 session 累計成交口數）、1 分 K interval 成交口數、法人 OI、PCR、TXO chain、large traders、basis/term structure | Quote 成交量是 session cumulative contracts；`intraday.bars` 是每分鐘 interval contracts。法人、選擇權與大額交易人主要是官方盤後資料，不是夜盤即時流 |
| `us_stock` | 是，如 `MU` | local-cache evidence、bounded quote/intraday/daily/fundamental context，並有 dedicated LLM path | 即時與 fundamentals 視 provider/key/quota；US options flow/earnings 未接 |
| `jp_stock` | 是，如 `7203.T` | 日股 local-cache daily/resource context、bounded intraday、brief/full | 無 dedicated LLM path；TDnet 未接，calendar/freshness 仍有限制 |
| `jp_index` | 是，`^N225` / `1306.T` | 日經/指數 OHLC 與 bounded intraday context | 同日股限制 |
| `kr_stock` | 是，如 `005930.KS` | 韓股 local-cache evidence、Yahoo/Naver bounded intraday、brief/full | 無 dedicated LLM path；OpenDART 未接，provider/calendar coverage 不齊 |
| `kr_index` | 是，`KOSPI` / `KOSDAQ` / `KOSPI200` | 指數 OHLC/intraday context | 同韓股限制 |
| `crypto_market` | 否 | Crypto 市場、quote/OHLC、derivatives/collector context | 依 collector/provider cache；沒有私有帳戶、交易或保證不中斷的 realtime feed |
| `crypto_asset` | 是，如 `BTC` | 單一資產 bounded evidence 與 brief/full | 無 dedicated LLM path；不同 provider symbol/coverage 不完全一致 |
| `resource_asset` | 是，如 OMI instrument symbol | 資源商品 quote/OHLC context | Yahoo chart best-effort、可能延遲、只能 watch/research |
| `portfolio` | 否 | 本機持倉、valuation context | 私人資料，只允許 server-trusted caller；不同幣別不會靜默相加 |
| `us_macro` | 是，如 FRED series id | FRED local-cache observations | Refresh 需 `FRED_API_KEY`；依 release cadence，不是即時行情 |
| `us_watchlist` | 是，numeric group id | 美股自選群組 context/Radar | data-only；coverage 依各 symbol cache/provider |
| `jp_watchlist` | 是，numeric group id | 日股自選群組 context/Radar | data-only；同 JP provider/disclosure 限制 |
| `kr_watchlist` | 是，numeric group id | 韓股自選群組 context/Radar | data-only；同 KR provider/disclosure 限制 |
| `source_health` | 否；可用 id/filter | 跨市場 provider freshness、missing 與 incident context | 反映 runtime 狀態，不等同 capability 是否已實作 |
| `capability_status` | 否；可指定 capability id | 查詢已接、derived、private、需 key、未接 provider 的 contract | 反映 implementation readiness，不等同資料此刻 current |

外部工具詢問「TXF 夜盤目前成交量」時，`omi.ask` 會依 `tw_futures`
scope 選取 `quote.snapshot`、`intraday.bars` 與 `data.freshness`。Consumer
應分別顯示 `total_volume_contracts`（目前 session 累計）與
`volume_contracts`（`volume_event_time` 所指最近一個有成交量的 1 分 K
interval），不得把兩者相加或混稱成同一個量。

`source_health` 的 `market_data_params` 支援 `market`、`resource`、`target`、`provider`、`status_filter`、`problems_only`、`include_healthy` 與 bounded `health_limit`。`total_*` 是套用 market/resource/target/provider 後的基礎集合，`matched_*` 是再套用 status/problem filter 的命中集合，`returned_*` 則是 limit 後實際回傳集合。

## 8. 目前 capability readiness

以下是 Backend `capability_status` contract 在 2026-07-22 的分類；它與即時 source health 是兩件事。

### 已連接或有條件連接

| Capability | 狀態 | Provider / cadence | 限制 |
| --- | --- | --- | --- |
| 台股全市場 breadth | `connected` | TWSE/TPEX，intraday 或 daily 依來源 | 全市場 official breadth 與 OMI sample movers 不可混用 |
| 台股市場籌碼/rankings | `connected` | TWSE/TPEX local cache，盤後日更 | Aggregate 與 per-stock DB coverage 分開揭露 |
| 台指期法人 OI / PCR | `connected` | TAIFEX official daily | 不是夜盤即時法人部位 |
| 韓股 intraday | `connected` | Yahoo chart / Naver cache，bounded | External refresh 仍需 server trust |
| 資源商品 quote/OHLCV | `connected` | Yahoo chart best-effort | 延遲、watch-only、無 execution |
| Portfolio context | `connected_private` | OMI local portfolio | 只給 trusted caller，幣別不靜默合併 |
| FRED macro | `connected_key_required_for_refresh` | FRED release schedule | Cache 可讀，refresh 需 key |
| 台灣選擇權 chain / IV / Greeks | `connected_derived` | TAIFEX 盤後 | Chain/Delta 為官方；IV/Gamma/Vega/Theta 是 OMI 衍生且有零利率/零股息假設 |
| 台灣大額交易人部位 | `connected` | TAIFEX 盤後 | Top 5/10 concentration 不等於外資方向 |
| 台指期 basis / term structure | `connected_derived` | TAIFEX + TAIEX 盤後 | Basis、annualized basis、curve shape 為同日收盤衍生值 |

### 尚未連接

| Capability | 目前狀態 | 缺少什麼 |
| --- | --- | --- |
| 一般新聞/事件 | `provider_not_connected` | Attribution、license、去重、entity mapping、retention、quota policy |
| 美股 options flow / earnings | `provider_not_connected` | 授權 provider 與獨立的 options/earnings quota contract |
| 日本 TDnet disclosure | `provider_not_connected` | Issuer mapping、document identity/storage、語言與 bounded polling policy |
| 韓國 OpenDART disclosure | `provider_not_connected` | API key policy、corp-code mapping、report normalization、bounded backfill |
| 港股市場 | `provider_not_connected` | Symbol master、calendar、quote/daily provider、freshness、watchlist contract |

`provider_not_connected` 是明確 blocked contract，不是「查到 0 筆」。未來加入券商或授權 API 時，應先在 Backend 補 provider、freshness、source health 與 bounded refresh，再由既有 outward target 暴露；不應直接在 Frontend/Kuro/MCP 接 provider。

## 9. SSE streaming contract

`POST /api/ai/ask/stream` 使用 `text/event-stream`，request body 與 `/api/ai/ask` 相同。

可能的 event：

- `status`：pipeline stage 與可顯示進度。
- `evidence`：evidence passport。
- `tool_run`：執行 tool 的狀態；只有實際有 tool run 才會出現。
- `delta`：Human Answer 的文字片段。
- `final`：完整 `AiAskResponse`。
- `error`：stream worker/validation/LLM error。
- `done`：最後一個 event，`{ "ok": true|false }`。

Consumer 規則：

- 必須持續讀到 `done`；收到 HTTP 200 不代表 business pipeline 已成功。
- 只有 `final` 是完整正式 response；`delta` 只用於漸進顯示。
- 使用 request id / abort guard，避免上一個 request 的晚到 event 覆蓋新問題。
- 失敗流程通常以 `error` + `done {ok:false}` 結束。

## 10. MCP 接口

### Repo 內 stdio MCP

檔案：`agents/omi_mcp_server/server.py`

預設 public tools：

- `omi.ask`：forward 到 `POST /api/ai/ask`。
- `omi.ask_stream`：呼叫 SSE endpoint，收集 event 後回給不能原生消費 SSE 的 MCP client。

特性：

- 支援完整 `omi.decision.v4` request controls，schema 由 backend
  `/api/ai/tools` 動態提供。
- `include_raw` 僅保留為 caller compatibility flag；v4 下不改寫 response。
  Payload 大小由 backend `selection.fields`、`selection.limits` 與
  `selection.max_response_bytes` 控制。
- `OMI_MCP_EXPOSE_INTERNAL_TOOLS=false` 是安全預設。只有 trusted local debug 才能設成 `true`。
- `OMI_API_BASE_URL` 應指向 launcher 實際選到的 Backend URL。
- `OMI_MCP_AI_TRUST_TOKEN` 只傳 OMI trust header，不保存 OpenAI key。

注意：Backend `GET /api/ai/tools` 目前只列出統一 callable tool `omi.ask`；`omi.ask_stream` 是 MCP transport 提供的 streaming convenience tool，不是另一套市場邏輯。

### `OMI_search` standalone adapter

位置：`C:\GPT_MCPtool\OMI_search`

Public tool：`omi.search`

安全預設：

- `allow_llm=false`
- `allow_write=false`
- `mode=data_only`
- `refresh_if_missing=false`
- `contract_version=omi.decision.v4`

允許的 mode 只有 `data_only`、`brief`、`full`。它不能產生 LLM
analysis/report，也不能寫 memory/report；但可轉送 `selection`、`output`、
`realtime_policy` 與 granular continuation，並原樣回傳 v4 envelope。

`refresh_if_missing=true` 只會要求 Backend 使用 `allow_external_fetch=true` 與
bounded budget，允許主規劃器嘗試 refresh；不保證所有 fill action 都會在同一
request 自動執行。實際 attempts、tool outcomes、payload 是否進入 evidence 與
remaining actions 讀 `execution.refresh_reconciliation`，是否能更新 market
cache 仍由 Backend trust/freshness policy 決定。

```json
{
  "query": "2330 最近量價、法人與分點資料",
  "target": { "type": "tw_stock", "id": "2330" },
  "mode": "data_only",
  "refresh_if_missing": false,
  "payload_level": "compact",
  "selection": {
    "include": ["quote.snapshot", "technical.structure"],
    "max_response_bytes": 32768
  }
}
```

HTTP MCP 使用 session：client 先 `initialize`，保存 response 的 `Mcp-Session-Id`，之後用相同 header 呼叫 `tools/list` / `tools/call`。

`TARGET_NOT_FOUND`、trust 拒絕與其他 structured business rejection 都是成功
傳輸的 canonical result，因此 MCP `isError=false`；只有 protocol、HTTP
transport、serialization 或 adapter internal failure 使用 `isError=true`。

`OMI_search` v1 不支援任意 dataset query DSL。若未來需要日期區間、欄位選擇、排序、分頁或跨 dataset query，應先在 OMI Backend 新增正式 contract，例如 `/api/ai/search`，再讓 adapter forward。

## 11. Trust、安全與副作用

### AI trust 判斷

Backend server policy 依以下資訊判斷 trust：

- `X-OMI-AI-Trust-Token` 是否與 server config 相符。
- Request client host 是否在 server-side local trusted allowlist，且 local trust 已啟用。

以下 client 欄位本身都不能提升權限：

- `caller_profile`
- `allow_llm`
- `allow_write`
- `allow_external_fetch`

有效權限是 client intent 與 server policy 的交集。

### Internet exposure

FastAPI app 目前沒有全域 authentication middleware；AI 敏感功能有自己的 trust gate，但許多市場 refresh、watchlist、portfolio、settings、dispatch routes 並沒有統一 Internet-facing auth。安全原則：

- Backend 只 listen loopback / trusted local network。
- 不直接把 `8400` 或實際 fallback port 轉送到公網。
- ChatGPT Web 只經過 `OMI_search` + authenticated/controlled tunnel。
- Tunnel 或 adapter 是 transport/security boundary；Backend 仍留在 localhost。
- Provider key、OpenAI key、券商 credential 都不能放在 request body、query string、repo 文件或 MCP tool result。

## 12. 不能保證與已知限制

### 資料限制

- Public/best-effort provider 可能 timeout、rate limit、改 schema、延遲或只提供部分市場。
- `generated_at` 是 OMI 組裝回答的時間，不等於 provider 資料時間；應讀 `as_of` 與 freshness。
- 不同市場、不同資源不保證在同一時間點更新，不能把跨市場值當成同步 snapshot。
- 盤中資料可能 provisional，日線/法人/選擇權/分點等資料可能到盤後才 finalized。
- Collector、scheduler 或歷史累積從啟用後才開始，舊資料不一定自動完整回補。
- Full-market breadth、OMI sample movers、自選清單與 ranking 的分母不同，不能混稱「全市場」。
- 衍生值必須保留 assumptions 與 source refs，不能描述成交易所直接發布的 live value。

### AI/決策限制

- OMI 是研究與決策輔助，不預測保證漲跌，也不保證獲利。
- 沒有足夠 entry/risk guardrails 時，`decision_ready` 應保持 false，相關 section 會被 block。
- LLM 未設定 key、request 不受信任、budget 不足或 target 無 dedicated path 時，analysis/report 會被拒絕或降級。
- Evidence 不足時只能回報缺口、做 bounded refresh 或使用明示 cached fallback；不得編造數字。
- Consumer 不得只取一句 headline 而丟棄 risks、counter evidence、data limits、missing 與 warnings。

### 交易與帳戶限制

- 沒有 order placement contract。
- 沒有 broker account/session/position synchronization contract。
- Portfolio 是本機研究資料，不是券商帳戶 truth source。
- 未來加入券商 API 時，行情讀取與交易執行必須分開設計；本文件目前只涵蓋研究/read evidence surface。

## 13. 錯誤處理建議

Consumer 應依序判斷：

1. Network/timeout/HTTP status。
2. JSON/SSE contract 是否可解析。
3. `contract_version` 是否支援。
4. `ok` 與 `request_status`。
5. `answer_ready` / `facts_ready` / `analysis_ready` / `decision_ready`。
6. `mode.effective` 是否與 requested mode 不同。
7. `fallback_used` / `cached_data_returned`。
8. `evidence_passport` / `freshness`。
9. `missing` / `warnings` / slot status。
10. 最後才呈現 `analysis.human_answer` 或 `result`。

建議保留 Backend 回傳的 `x-request-id` 供 log tracing。遇到 provider 問題時，用 `/api/system/provider-events` 與 `/api/system/source-health-snapshots` 查原因，不要在 consumer 端自行切換 provider。

## 14. 維護與驗證清單

當 OMI 新增券商 API、外部 provider、target 或 MCP tool 時，至少更新並驗證：

1. Backend provider/service 與 bounded timeout。
2. Cache/DB transaction owner 與 migration（若需要）。
3. Freshness、source health、provider events 與 missing/warning contract。
4. `/api/ai/ask` target、tool policy、budget、evidence passport 與 slot status。
5. `/api/ai/tools` schema、repo MCP schema、`OMI_search` schema 是否一致。
6. Frontend/Kuro/MCP 是否只消費 Backend contract。
7. OpenAPI inventory 與 representative business smoke，而不只 health check。

快速盤點命令：

```powershell
Invoke-RestMethod "http://127.0.0.1:8400/api/system/health"
Invoke-RestMethod "http://127.0.0.1:8400/api/system/readyz"
Invoke-RestMethod "http://127.0.0.1:8400/api/ai/tools"
Invoke-RestMethod "http://127.0.0.1:8400/openapi.json"
Invoke-RestMethod "http://127.0.0.1:8797/health"
```

能力 readiness 應透過 `target.type=capability_status` 查詢；runtime freshness/provider incident 應透過 `target.type=source_health` 或 source-health endpoints 查詢。兩者不能互相替代。

## 15. 相關文件與程式位置

- `README.md`
- `docs/architecture/BackendArchitecture.md`
- `docs/agent-runs/omi-ai-decision-core/ContractMap.md`
- `docs/agent-runs/productized-market-payload-contract/ContractDesign.md`
- `backend/app/ai/schemas.py`
- `backend/app/ai/scope_resolution.py`
- `backend/app/ai/ask_policy.py`
- `backend/app/ai/market_context/capability_context.py`
- `backend/app/routers/ai.py`
- `agents/omi_mcp_server/server.py`
- `agents/omi_mcp_server/README.md`
- `C:\GPT_MCPtool\OMI_search\README.md`
