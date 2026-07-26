# Progress

## Status

- Current phase：已由 `omi-v4-only-convergence-20260724` 完成 public v4-only
  收斂與 external `OMI_search` migration
- Last updated：2026-07-24 Asia/Taipei

## Completed

### 1. Baseline 與邊界

- 讀取並套用 `productized-project-workflow`、
  `omi-evolve-ai-decision-contract` 與 `omi-trace-market-freshness`。
- 對齊 product docs、backend architecture、v3 contract、HTTP/SSE、repo MCP、
  Frontend、外部 `OMI_search` 與 Kuro consume path。
- 固定 consumer-neutral 邊界：Kuro 模型和其他模型一樣選取 OMI 資料；
  可朗讀稿、persona、語氣、斷句與 TTS 由 Kuro 端負責。

### 2. `omi.decision.v4`

- 新增 backend-owned capability registry、selection normalization、field
  allowlist、row/item limits、response byte budget、data manifest 與 fill plan。
- 支援 `evidence_only`、`decision`、`decision_with_evidence`。
- 支援 `cache_only`、`prefer_live`、`require_live`。
- v4 移除 outward `evidence.result` 大包，只輸出選定的 `evidence.data`。
- 本階段當時仍保留 v3/v2 public compatibility；後續收斂已將它們降為 backend
  私有 seam，public consumer 只接受 v4。

### 3. P0 semantic fixes

- Freshness intent 不再覆蓋已解析的 stock target；multi-intent 可同時保留
  analysis 與 data freshness。
- MCP structured business rejection 改為 `isError=false`；transport/internal
  failure 才是 MCP execution error。
- Bearish/neutral stance wording 與 headline/scenario 對齊。
- Continuation action ID 依 target、selection 與 registry 重新驗證。
- Fill continuation 同時驗證 `plan_id`、完整 `plan_action_ids` 與 selected subset；
  產出的 `invoke.arguments` 本身是合法 `omi.ask` request。
- Rejected/clarification response 保留原始 v4 selection，且不會為不存在 target
  建立 refresh action。

### 4. Granular fill

- Taiwan refresh 可依選定 dataset/capability 執行，不再只有整包 stock evidence。
- US 依 capability 規劃 intraday、daily price 或 SEC company facts。
- Crypto 依 capability 規劃 ticker、單一 interval OHLCV、order book 或
  derivatives；單一 request 維持單 asset、單 provider、bounded limit。
- `BTCUSDT`、`BTC-USDT`、`BTC/USDT` 與 provider-prefixed symbol 可正規化到
  registry asset；被選取的 order book、intraday/daily OHLCV 與 derivatives
  會進入 bounded compact projection。
- Fill action 帶 deterministic ID、target、operation、fields、limit、calls、
  timeout、cache write 與 external fetch metadata。

### 5. Realtime semantics

- 新增共用 realtime classifier。
- 區分 `live`、`delayed`、`stale`、`latest_completed_session`、
  `final_snapshot` 與 `unavailable`。
- Regulated market 使用 session/quote semantics；crypto continuous 同時驗證
  event time 與 received/fetched time。
- `require_live` 未滿足會進入 manifest、limitations 與 warning；休市最新完成
  session 不會冒充 live，也不會產生無意義刷新。

### 6. In-repo consumers

- Repo MCP 預設 v4，並 forward output、realtime policy、selection、
  continuation 與 position context。
- MCP `tools/list` 從 backend `/api/ai/tools` 取得 public schema/capability
  catalog，adapter 只保留 `include_raw`；離線時使用 fallback schema。
- OMI Dock 明確請求 v4；有 intraday 時使用 `require_live`，其他情境
  `prefer_live`。
- Frontend decision evidence parser 優先讀 v4
  `evidence.data["technical.structure"]`，仍保留 v3 fallback。
- Durable architecture 與 MCP 文件已更新為 v4、consumer-neutral contract。
- 修正指數資料 fixture 缺 `breadth_status` 時的 optional-chaining crash，
  讓實際 OMI Dock browser contract test 可穩定執行。

## Validation evidence

最終驗證：

- Safe backend profile：
  - backend `compileall` 通過。
  - backend full suite：`948 passed in 72.46s`。
  - `git diff --check` 通過。
  - log：`.tmp/validation/20260724-014400`。
- Safe frontend profile：
  - ESLint 通過。
  - TypeScript `--noEmit` 通過。
  - `git diff --check` 通過。
  - log：`.tmp/validation/20260724-014531`。
- Browser：Playwright
  `OMI context payload follows Taiwan and Korea index selection`：
  `1 passed`；實際確認 Dock 送出 v4、output 與 market target。
- Targeted semantic regression 最後一輪：`120 passed, 4 subtests passed`。

初始 runtime baseline（修改前）：

- Backend：`http://127.0.0.1:8400`。
- TW 2330 cache-only：56 ms、26,460 bytes、`as_of=2026-07-23`；quote 被標
  current 但缺 quote time/semantics，intraday `not_requested`。
- US NVDA bounded live read：1,454 ms、77,635 bytes；live quote age 約
  0.64 秒，另有 stale daily-provider fallback warning。
- Crypto BTC local-cache：2,696 ms、23,956 bytes；freshness `current` 但
  `is_realtime=false`，slot freshness `unknown/planned`。

修改後使用 scheduler-disabled isolated backend
`http://127.0.0.1:18400` 驗證：

- `/api/ai/tools`：default `omi.decision.v4`、selection schema、
  `omi.capability.registry.v1`、17 capabilities。
- TW 2330：`omi.decision.v4`、43,135 bytes；休市 quote 正確為
  `latest_completed_session`，technical current，無 quote refresh action。
- US NVDA：35,435 bytes；Yahoo observation 誠實判為 `delayed`，
  `require_live` 未滿足並進入 limitations，未冒充 live。
- Crypto `BINANCE:BTCUSDT`：正規化成 `BTC`；ticker 與 order book各只呼叫
  一個 Binance bounded tool，quote=`live`、order book payload included，
  22,897 bytes。
- TW selective fill：先只規劃一個 `tw.refresh_revenue`，再帶回
  plan/action 執行；tool run 只有該 operation，189 ms。Provider success 後
  現有測試日期仍缺新月份，OMI 保留 stale/missing 與 continuation。
- 32,768-byte request 實際 HTTP payload 32,765 bytes，
  projection `budget_met=true`。
- MCP stdio：
  - initialize 宣告 v4。
  - tools/list 使用 backend schema，包含 capability catalog 與
    `plan_action_ids`。
  - 不存在代碼回 `TARGET_NOT_FOUND`、`request_status=rejected`、
    `fill_action_count=0`、`isError=false`。

## Remaining

- 目前 launcher-managed `8400` 仍是 2026-07-23 23:21 啟動的舊 process；
  系統自動審核拒絕本輪 controlled restart，所以沒有終止它。使用者從 tray
  執行 `Restart Services` 後，才會讓正式 Dashboard runtime 載入本次 source。
- 外部 `OMI_search` 與 Kuro 仍待各 repo write scope。
- 未呼叫付費 LLM：使用者允許付費 API 是架構授權，但實際 paid smoke 仍需要
  明確一次性 cost budget；本次 market provider probe 已足以驗證 v4 orchestration。

## External consumer status

- `C:\GPT_MCPtool\OMI_search` 目前仍固定 v3；compact parser 只辨識 v3。
- `C:\project\kuro\Open-LLM-VTuber` 目前仍固定 v3；contract allowlist 與
  `evidence.result` parser 需要加入 v4。
- 兩個 repo 都是 thin consumer，沒有發現它們需要或應該擁有市場/freshness
  邏輯。
- 這兩個路徑不在本次 writable root。OMI backend truth source先完成；外部
  consumer 必須在取得各 repo write scope 後分別更新與執行其 tests，不能宣稱
  已完成 migration。

## Decisions

- 一個總出口是單一業務 contract，不是單一巨大 implementation。
- 模型選 capability、fields、limits 與 output；backend 選 provider/tool，
  並擁有 freshness、realtime、trust、budget、fill policy。
- 不建立 Kuro、桌寵、語音或 consumer-name-specific response profile。
- 此處原為 additive rollout 決策；已由後續 v4-only 任務取代。v2/v3 已從
  public surface 移除，只保留 backend 私有 seam。

## Risks

- Runtime 可能仍是修改前的舊 process；health/HTTP 200 不足以證明 v4 code
  已載入。
- 個別 provider 即時能力仍取決於 credential、session、rate limit 與來源健康；
  contract 只保證誠實表達，不保證 provider 永遠有 live data。
- 使用者原則上允許付費 API，不代表可跳過 trust、quota、timeout 或 cost bound。
