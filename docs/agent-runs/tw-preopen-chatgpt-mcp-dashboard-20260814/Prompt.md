# OMI 台股盤前 ChatGPT MCP App 長專案任務規格

## 文件資訊

- 任務代號：`tw-preopen-chatgpt-mcp-dashboard-20260814`
- 建立日期：2026-08-14
- 狀態：Backend implementation 進行中；MCP/widget 尚未完成
- 主要規格來源：`C:\Users\thoma\Downloads\OMI_TW_Preopen_Backend_ChatGPT_MCP_App_Engineering_Spec_v2_20260814.txt`
- 主要程式庫：`C:\project\Open Market Intelligence`
- MCP adapter 程式庫：`C:\GPT_MCPtool\OMI_search`
- 預定 ChatGPT widget 位置：`C:\GPT_MCPtool\OMI_search\ui\tw-market-dashboard\`

## 任務背景

OMI 已具備台股盤中狀態、正式市場廣度、指數、族群、watchlist、技術分析與 AI decision contract，但現有能力尚未形成一個專為 08:30 至 09:00 盤前集合競價設計、可由 ChatGPT MCP App 穩定讀取與互動呈現的完整產品面。

本任務要建立一條可長期維護的產品化路徑：由 OMI backend 擁有盤前市場語意、資料品質、freshness、估算方法與限制；`OMI_search` 維持 thin adapter；ChatGPT 端以 MCP Apps widget 呈現 backend 已定義的市場事實，而不在 widget 或 adapter 重做市場邏輯。

這不是自動交易功能，也不是單純把現有 OMI web frontend 搬進 ChatGPT。成果應是一個以台股為核心、可被驗證、限制透明、能在真實盤前時段穩定使用的研究工作台。

## 預期成果

完成後，使用者可在 ChatGPT 中開啟 OMI 台股市場儀表板，取得：

- 盤前 session、交易日、資料時間與 freshness。
- 上市、上櫃盤前漲跌家數、未覆蓋數與 coverage。
- 盤前熱門族群與其樣本數、漲跌分布、coverage 與限制。
- 指定 watchlist 群組的盤前狀態，並可切換個股詳情。
- TAIEX、TPEx 指數的盤前 provisional estimate、coverage 與估算限制。
- 個股搜尋、backend 提供的 K 線與均線資料。
- 明確可見的 `partial`、`stale`、`missing`、provider failure、估算狀態與尚未觀察情形。

## 已確認的現況基線

### OMI backend

- 現有 `tw.market.breadth.v2` 與 intraday state 已保留盤前 indicative facts，但 regular decision state 仍正確要求 actual trade。
- 現有盤前或 live breadth provider cache 約為 30 秒；部分 live refresh gate 仍從 08:55 才開始，與本任務 08:30 的盤前需求不一致。
- 現有 full-market provider 讀取可能發生在 read path；本任務要把盤前全市場收集責任移到 scheduler-owned collector，使 dashboard GET/read 維持 cache-only。
- 現有族群、watchlist、股票搜尋、技術指標與指數貢獻 helper 可作為基礎，但不能直接假設其盤前語意或 coverage 已符合本契約。
- `StockProfile.issued_shares` 可作為已發行股數候選來源；仍須驗證資料日期、成分股、除權息與 divisor adjustment。
- 目前不存在 `omi.tw_market_dashboard.v1` canonical contract。

### OMI_search MCP adapter

- 現有 Python MCP server 是 thin adapter，主要呼叫 OMI backend，不直接擁有市場邏輯。
- 現有 server 只宣告 `tools` capability，尚未實作 MCP Apps 所需的 resource capability、UI resource 與 widget bridge contract。
- 現有公開工具以 `omi.ask`、refresh status 與個股 context 為主，尚未有台股 dashboard 的 focused data/render tools。
- 現有 streamable HTTP transport 已具備 session preservation；後續應擴充而非改寫成另一套 runtime。

### 前置專案成果

- 台股市場廣度 canonicalization 已建立 `advance + decline + unchanged = coverage` 與 `coverage + unknown = universe` 的基本方向。
- 盤前 intraday contract 與 opening handoff 已完成正式 rollout，但真實盤前各關鍵時間點仍需以 live evidence 驗收，不能用非交易時段模擬取代。
- 選股 quote depth 與技術分析能力可支援個股 drill-down，但本任務仍需建立 focused dashboard projection。

## 目標

### G1：建立 scheduler-owned 盤前資料收集

從交易日 08:30 起，以 bounded、single-flight、可觀察的背景工作收集上市與上櫃盤前 indicative observations；API read path 不得為了回應 dashboard 而臨時打外部 provider。

### G2：建立 backend-owned canonical dashboard contract

新增版本化 `omi.tw_market_dashboard.v1`，統一輸出 session、indices、breadth、hot groups、watchlist、freshness、warnings 與 limitations，並維持 null、unknown、partial 的真實語意。

### G3：建立 provisional index estimate

依官方指數方法、成分股、已發行股數與 divisor/corporate-action 規則，建立 TAIEX 與 TPEx 的盤前估算；缺少觀察時不得重新正規化已觀察權重，也不得把 estimate 冒充官方指數或 decision-usable fact。

### G4：擴充 thin MCP adapter 成 MCP App host

在 `OMI_search` 中新增 focused data tool、render tool、UI resource、精確 schema、正確 annotations 與 session-preserving protocol 行為；市場計算仍全部留在 OMI backend。

### G5：建立 ChatGPT 端互動 widget

以 React/TypeScript 建立窄版、資訊密度高、可輪詢、可搜尋、可切換個股、可呈現 K 線與 backend 均線的 dashboard。widget 透過 MCP bridge 呼叫 tools，不直接連 OMI backend 或外部 provider。

### G6：完成真實 runtime 與交易時段驗收

除了 unit、contract、protocol 與 isolated runtime 測試外，必須在實際 08:00、08:30、08:55、09:00 時段取得 live evidence。未觀察到的時段只能標為 `not_observed`，不可宣稱完成。

## 非目標

- 不在本任務建立自動下單、交易執行或報酬保證。
- 不把 ChatGPT widget 升格為市場邏輯或 freshness truth owner。
- 不在 MCP adapter 直接讀寫 OMI SQLite、import backend internals 或複製 provider 邏輯。
- 不讓 GET/read path 觸發全市場 refresh、昂貴 backfill、LLM、report 或 memory write。
- 不以現有 OMI Next.js frontend iframe 取代 MCP Apps widget。
- 不重寫 `OMI_search` Python server 為 Node server。
- 不在本專案直接進行 ChatGPT App 公開商店提交；第一階段只支援私人 Developer Mode 與安全 tunnel。
- 不在沒有證據時修改正式 completed-session index、breadth 或 AI decision semantics。
- 不在未授權下執行 DB migration、component restart、commit、push 或公開發布。

## 架構與責任邊界

### Backend 擁有

- 交易日與 session 判定。
- provider access、timeout、retry、backoff、source health 與 cache。
- 盤前 observation、breadth、族群、watchlist 與 index estimate 計算。
- coverage、unknown、freshness、warnings、limitations 與 decision usability。
- dashboard、symbol search 與 stock detail 的 canonical response contract。

### MCP adapter 擁有

- MCP tools、resources、schema、annotations 與 transport lifecycle。
- 把 backend response 投影成 MCP Apps 可消費的 `structuredContent`。
- UI bundle 的 resource 註冊、CSP 與版本化 URI。
- backend/network error 到 truthful tool error 的薄層轉換。

### ChatGPT widget 擁有

- 版面、互動、載入狀態、輪詢節奏與可及性。
- 對 tool result 做 schema validation 與 monotonic state adoption。
- 顯示 backend 已提供的數值、標籤、warnings 與限制。
- 不自行重算 breadth、族群排序、均線、index estimate 或 session。

## 功能需求

### FR1：盤前 collector

- 只在台灣交易日與允許時段執行；非交易日不得建立假盤前狀態。
- 預設從 08:30 開始，09:00 opening handoff 後切換 regular session contract。
- 具備 single-flight、`max_instances=1`、bounded request count、timeout、backoff、circuit/state reporting。
- 明確記錄 `trade_date`、`as_of`、provider、success/failure、row counts、coverage 與 duration。
- 若 API runtime 與 scheduler runtime 分離，snapshot 必須有可跨 process 讀取的 canonical storage；不得把 process-local memory 當唯一真相。
- 是否需要 DB migration 必須在 M0 用 runtime topology 證據決定；若不需要，不得為方便任意加表。

### FR2：盤前 breadth

- 分別輸出 TWSE、TPEx 與可選的 combined view。
- 每個 market 至少包含 `universe`、`coverage`、`advance`、`decline`、`unchanged`、`unknown`、`coverage_ratio`、`as_of` 與 status。
- 必須滿足：`advance + decline + unchanged = coverage`。
- 必須滿足：`coverage + unknown = universe`。
- 缺 quote、無法解析、基準價缺失與 provider omission 不得被歸類成 unchanged。
- null 不得為了 UI 好看被轉成 0。
- indicative observation 可作為盤前 fact，但一律 `decision_usable=false`。

### FR3：盤前族群

- 由 backend 依 canonical stock/group membership 與盤前 observation 建立。
- 每個族群至少輸出 coverage、unknown、advance ratio、median change、mean change、dispersion、sample size 與 status。
- 排序規則必須版本化並可測試；建議先依 median change、advance ratio、coverage 形成穩定排序。
- 樣本過少、coverage 過低或 membership 不完整時應降級為 partial 或不進排行榜。
- regular-session hot group 語意不得因盤前 projection 而被靜默改寫。

### FR4：watchlist

- 必須凍結來源群組：明確的 `group_id` 或 active-group policy，不可用模糊的「目前 watchlist」。
- 必須凍結 `include_children`、enabled-only、排序方式與最大筆數。
- 每檔輸出 symbol、name、market、indicative price/change、status、as_of、coverage/limitation 所需欄位。
- 使用者切換個股時，個股詳情走 focused backend tool，不把整份 dashboard 全量重取當作唯一方案。

### FR5：盤前指數估算

- 分別支援 TAIEX 與 TPEx，不得混用成分股或權重來源。
- 方法須以官方 index methodology 為基準，並記錄 `methodology_version`。
- 必須記錄 `constituent_as_of`、`shares_as_of`、`divisor_adjustment_status`。
- 未觀察成分股的 price delta 可在估算中視為 0，但其權重必須計入 uncovered weight；不得對已觀察權重重新正規化。
- 輸出至少包含 estimate、change、change_pct、observed_weight、uncovered_weight、constituent coverage、quote coverage、status、warnings 與 limitations。
- corporate action、除權息、成分變更或 divisor 狀態不確定時，必須降級或拒絕輸出數值。
- 所有盤前 estimate 必須標示 `provisional=true`、`official=false`、`decision_usable=false`。

### FR6：backend dashboard projection

`omi.tw_market_dashboard.v1` 至少包含：

- `kind`
- `version`
- `snapshot_id`
- `state_version`
- `trade_date`
- `session`
- `as_of`
- `indices`
- `breadth`
- `hot_groups`
- `watchlist`
- `freshness`
- `warnings`
- `limitations`

read endpoint 必須 cache-only、bounded、可預測，不得在 request lifecycle 內隱性執行 provider refresh。

### FR7：MCP Apps tool surface

預定工具面：

1. `omi.read_tw_market_dashboard`
   - data-only、model 與 app 可見。
   - cache-only；只有在此條件成立時才可標 `readOnlyHint=true`。
   - `outputSchema` 必須精確描述 `structuredContent`。
2. `omi.open_tw_market_dashboard`
   - render-only、model 可見。
   - 接收已準備的 `snapshot_id` 或等價 reference。
   - 唯一綁定 `_meta.ui.resourceUri` 的主要工具。
3. `omi.search_tw_symbols`
   - bounded、app-visible 的股票搜尋。
   - 不得因搜尋觸發外部 refresh。
4. focused stock detail tool
   - M0 先評估現有 `omi.read_stock_context` 是否足夠 focused。
   - 若 response 過重或語意不符，再新增 app-only backend-owned projection。

UI resource 使用版本化 URI，預設候選為 `ui://omi/tw-market-dashboard/v1.html`，MIME 為 `text/html;profile=mcp-app`。新實作以 `_meta.ui.resourceUri` 為主，`openai/outputTemplate` 只作相容 alias。

### FR8：ChatGPT widget

- 第一屏直接顯示 session、indices、breadth、freshness 與 warnings。
- 窄版單欄為主，watchlist 使用固定高度可捲動區，避免卡片無限增高。
- 支援 08:00 waiting、08:30 preopen、08:55 near-open、09:00 regular handoff 等 backend-defined 狀態。
- 支援股票搜尋、選取與個股 K 線/均線詳情；均線由 backend 提供。
- 使用 MCP Apps bridge 的 initialize、tool-result notification 與 `tools/call`；`window.openai` 僅作 additive compatibility。
- 不直接呼叫 localhost backend、tunnel endpoint 或外部 provider。
- 對 host/tool data 做 runtime schema validation，不信任任意 payload。

### FR9：輪詢與狀態一致性

- 預設 polling interval 不得低於 backend live cache TTL；初始建議為 30 秒以上。
- 只允許單一 in-flight request；使用 `AbortController`，unmount 時取消。
- document hidden 時暫停或顯著降頻。
- network/tool failure 使用 bounded exponential backoff 與 jitter。
- 只採用較新的 `state_version` 或 `as_of`；stale/out-of-order response 不得覆蓋新狀態。
- polling failure 保留最後成功 snapshot，但要明確顯示 stale/error，不得靜默假裝正常。

## Hard constraints

- 台股維持核心市場；不在此任務擴大成多市場 dashboard。
- backend 是 market semantics、AI evidence 與 freshness 的唯一真相來源。
- MCP adapter 與 widget 必須維持 thin。
- `partial`、`missing`、`stale`、`unknown`、`provider_failure`、`not_observed` 不得被隱藏。
- 盤前 indicative/estimate 不得標為 actual trade、official 或 decision-usable。
- read path 不得產生外部 provider IO、DB rebuild、LLM、report 或 memory write。
- 不得刪除、重建或覆蓋 `data/open_market_intelligence.db`。
- 如需 migration，必須有 backup、transaction、integrity、replay 與 rollback 說明。
- 不得 broad-kill process；runtime adoption 只可透過 owned component lifecycle。
- 未經使用者明確授權，不做正式 restart、commit、push、公開 tunnel 或 App submission。

## 交付物

### OMI backend

- scheduler-owned 盤前 collector 與 source-health/status evidence。
- 盤前 observation、breadth、group、watchlist 與 index-estimate canonical models。
- `omi.tw_market_dashboard.v1` focused API contract。
- bounded symbol search 與 focused stock detail projection。
- unit、contract、integration 與 session-boundary tests。

### OMI_search

- resources capability 與 `resources/list`、`resources/read`。
- dashboard data/render/search/detail tool descriptors、schemas 與 annotations。
- 版本化 UI resource、CSP 與 bundle serving。
- MCP session-preserving protocol tests。
- README、Developer Mode 與 private tunnel 設定文件。

### ChatGPT widget

- React/TypeScript dashboard bundle。
- bridge initialization、tool calls、polling、backoff、state adoption 與 error UX。
- responsive/narrow layout、watchlist interaction、search、stock detail 與 K 線呈現。
- lint、typecheck、build 與至少一組互動測試。

### 驗收證據

- backend targeted tests 與 safe validation logs。
- MCP initialize/resources/tools/call 完整 protocol smoke。
- isolated local runtime health、contract version 與代表性 outward behavior。
- ChatGPT Developer Mode 中的 widget render、搜尋、切換與輪詢證據。
- 真實交易日 08:00、08:30、08:55、09:00 session evidence。

## 完成定義

只有同時符合下列條件，專案才可標記完成：

1. OMI backend contract 已版本化，且所有市場語意由 backend 定義。
2. dashboard read path 經測試證明不觸發 provider fetch 或其他昂貴 side effect。
3. breadth、group、watchlist 與 index estimate 的 coverage/unknown invariants 全部通過。
4. MCP resource、tool schema、annotations、CSP 與 session behavior 通過 protocol 測試。
5. widget 不直接連 backend/provider，且能處理 loading、partial、stale、error、out-of-order 與 unmount。
6. component-scoped runtime 已採用正確 build 與 contract version，並完成 outward smoke。
7. ChatGPT Developer Mode 可實際開啟、更新與互動。
8. 真實盤前與 opening handoff 時段已觀察；未觀察項目不得被豁免或偽裝成通過。
9. 文件、風險、known limitations 與操作方式已更新。
10. 未混入 unrelated dirty-worktree changes、秘密、local DB、logs 或 build artifacts。

## 需要在 M0 凍結的決策

- dashboard 使用 dedicated backend endpoint，或透過 `omi.ask` focused capability 投影。預設建議 dedicated read projection，避免 MCP adapter 解讀完整 AI decision envelope。
- scheduler 與 API reader 是否同 process；若否，canonical snapshot 的跨 process storage 方案。
- watchlist 的確切 `group_id`、active-group policy、`include_children` 與筆數上限。
- focused stock detail 是否沿用 `omi.read_stock_context`，或新增更小的 app-only projection。
- TAIEX/TPEx 成分股、issued shares、divisor/corporate-action 的 authoritative source 與更新節奏。
- widget bundle 採 inline single-file 或 hashed static assets，以及對應的 exact CSP。

## Stop-and-fix 條件

出現以下任一情況，必須停止擴大實作，先修正根因：

- dashboard read 觸發外部 provider fetch 或 expensive refresh。
- adapter/widget 開始計算 breadth、group、MA、session 或 index estimate。
- `unknown` 被歸為 unchanged 或 0。
- 舊 response 覆蓋較新的 dashboard state。
- 指數成分、股數、除權息或 divisor evidence 不足卻仍輸出看似精確的估算。
- tool annotations 與實際 side effect 不一致。
- resource URI、MIME、bridge initialization 或 CSP 導致 widget 無法載入。
- runtime 只證明 health/PID，沒有證明 build、contract 與 outward behavior 已採用。
- 實作 hunk 與既有 dirty worktree 衝突。
- 未經授權需要 migration、restart、commit、push 或公開發布。

## 2026-08-15 M9：Dashboard 互動與視覺改版增補

### Goal

- 將既有 terminal prototype 收斂成安靜、可長時間掃描的台股研究工作台。
- 讓熱門族群、使用者自選群組、個股選擇與資料限制具備清楚且互不混淆的資訊層級。
- 修正 watchlist scope、polling、out-of-order response、個股 selection 與錯誤狀態耦合，使視覺改版建立在正確互動模型上。
- 維持 backend-owned market truth 與 thin MCP widget 邊界，不把市場語意移到前端。

### Non-goals

- 不新增下單、券商連線、模擬撮合或任何寫入工具。
- 不重寫 React、MCP bridge、backend dashboard route 或既有 K 線計算。
- 不把熱門族群點擊擴張成產業成分股瀏覽器；本階段只正確呈現其市場雷達語意。
- 不修改正式盤前 index estimate 方法或 M4 尚未完成的官方 constituent/divisor 工作。
- 不在本 milestone 執行 component restart、remote registration、commit 或 push。

### Hard constraints

- `partial`、`stale`、`missing`、`unknown`、warnings 與 limitations 必須保持可見，但可用摘要加漸進揭露降低長期視覺噪音。
- Watchlist group metadata 必須由 backend contract 提供；widget 不得直接讀 DB 或自行推導 group tree。
- Dashboard initial load、manual/group refresh 與 30 秒 polling 必須使用同一個明確 scope。
- 群組快速切換與個股快速切換時，舊 response 不得覆蓋目前使用者 selection。
- 行動版不得只把桌機所有面板無限向下堆疊；市場、自選與個股研究需有清楚的單一主工作視圖。
- 所有變更需與目前 dirty worktree 共存，不得回復或覆蓋無關 hunk。

### Deliverables

- Backend dashboard watchlist group metadata 與 hot-group raw/display identity。
- Widget scope-aware snapshot adoption、獨立 selected stock state、分離錯誤狀態與 retry UX。
- 新版桌機與行動版資訊架構、字體／色彩 token、互動／focus／loading／empty／error states。
- 移除主畫面 disabled 委託草稿空殼；保留研究用途與不可自動交易聲明。
- Backend targeted tests、widget typecheck/test/build、isolated browser smoke 與使用者驗收清單。

### Done criteria

1. 所有 active watchlist groups 都由 dashboard snapshot 提供，切換後 items 與 selection 一致。
2. 群組切換後經過至少兩次 polling 不會跳回預設群組；快速 A → B → C 只保留 C。
3. 個股 selection 在 loading/error/success 間保持穩定，poll success 不會清除 detail error。
4. 產業代碼顯示人類可讀名稱，stable identity 不因 label 正規化而改變。
5. 桌機保留市場摘要 → 自選 → 個股研究主路徑；行動版可在市場、自選與個股視圖間切換。
6. 中文 UI 不再全面使用 mono；狀態、互動、行情與 warning 色彩語意可區分。
7. Widget typecheck、state tests、production build 與 backend targeted tests 通過。
8. 使用者完成 ChatGPT host 內的主觀前端驗收；在此之前 M9 只能標為 `technical_validation_complete_user_ui_validation_pending`。

### Assumptions

- 本輪以現有 `omi.tw_market_dashboard.v1` 做 additive field 擴充，不升版且不移除舊欄位。
- 使用者會執行最終 ChatGPT host 視覺與操作驗收；Codex 仍負責 isolated preview 的基本實機 smoke。

## 2026-08-15 M10：使用者驗收修正——保留原始版面

### Goal

- 還原 M9 前 terminal dashboard 的完整資訊架構與區塊順序，包含市場雷達、個股工作台及底部委託草稿介面。
- 使用 OMI SQLite 現有的台股自選樹作為 widget 自選群組真相來源，不再使用「核心持股／動能觀察」等示意分類。
- 保留 M9 已完成的 watchlist scope、snapshot ordering、獨立 selection/error state 與 backend industry label 修正。
- 視覺變更限制在色票、中文字型、按鈕文案與按鈕狀態樣式，不刪除或重排既有功能區。

### Non-goals

- 不新增、啟用或暗示真實券商送單能力。
- 不重做 dashboard layout，不把 desktop 改成新的市場／自選／個股三頁式工作流。
- 不改寫現有 77 群組／349 項目的 SQLite 自選資料。
- 不執行 component restart、commit、push 或 remote connector 變更。

### Hard constraints

- 使用者提供的截圖與附件是驗收證據／修改參考；本段使用者明確修正的範圍優先。
- 改版前備份是 layout baseline；`OrderShell`、市場雷達、個股研究、K 線、technical evidence、warning 與 footer 都必須保留。
- 委託草稿介面可以恢復顯示，但在 broker trust policy、write contract 與審計完成前維持 disabled／disconnected。
- Watchlist groups 必須由 backend snapshot 的 `watchlist.groups` 提供；preview fixture 使用目前 SQLite 已驗證的真實根分類名稱。

### Done criteria

- Desktop 與 mobile 畫面皆保有 M9 前全部功能區，底部委託草稿可見。
- Preview 不再出現「核心持股／動能觀察／半導體追蹤」示意群組。
- 自選群組 selector 能呈現並切換 backend 回傳的 77 個 active groups；預設 group 為目前資料的 `ETF／市場指標`。
- 群組切換、polling、快速切換、選股、detail error 與 K 線仍通過既有 tests／browser smoke。
- CSS／文案 diff 維持局部，不新增 dependency、不刪除原始操作介面。

## 2026-08-15 M11：自選股 Tree Explorer 正式後端跟隨

### Goal

- 將 MCP Dashboard 的攤平式 `<select>` 改為唯讀、可遞迴展開／收合的自選群組 Tree Explorer。
- 群組 hierarchy、名稱、順序與 selection 全部跟隨 backend `watchlist.groups`／`watchlist.selection`，frontend 不讀 DB、不維護第二份分類。
- 選取群組時只取得該群組直接股票，不再把所有子孫群組股票混入同一份清單。
- Dashboard request 明訂 bounded `group_limit=10`、`watchlist_limit=40` 與 `include_watchlist_children=false`。

### Non-goals

- 本階段不新增 backend group count 欄位；frontend 只在 backend 回傳 `direct_item_count`／`subtree_item_count` 時顯示，不自行推算或捏造。
- 不搬入正式 OMI 前端的新增、刪除、改名、拖放、啟停或股票管理功能。
- 不改變熱門族群計算、市場語意、MCP tool surface、個股 detail、K 線或 disabled OrderShell。
- 不執行 component restart、commit、push 或 remote connector 變更。

### Hard constraints

- Tree 必須能處理任意深度、orphan／cycle 防護、穩定排序與 malformed group；錯誤資料不得讓整個 widget 崩潰。
- 快速切換群組時，舊 scope response 不得顯示在新 selection 下；30 秒 polling 必須維持目前群組。
- Host 注入或舊 response 若仍是 `include_children=true`，不得被當成正式 direct-group watchlist 採用。
- Loading 時不得在新群組名稱下短暫顯示上一群組股票。
- 保留原始 dashboard layout 與 M10 已恢復的所有功能區。

### Done criteria

1. 所有 root 都可見，child／grandchild 可遞迴展開與收合，selection 可被鍵盤與螢幕閱讀器辨識。
2. 不再存在群組 `<select>`；Tree 的 source 只來自 backend snapshot。
3. 選 child 後 request 使用該 `group_id`、`include_watchlist_children=false`、`watchlist_limit=40`、`group_limit=10`。
4. Aggregated descendant snapshot、舊 group response 與 malformed hierarchy 均有 regression tests。
5. 熱門族群區與 Tree 各自 bounded scroll，不讓 sidebar 高度隨資料無限增加。
6. Widget typecheck、state tests、production build、adapter regression 與 desktop/mobile browser smoke 通過。
7. 正式 runtime adoption 仍為獨立授權閘門；本階段完成後交由使用者驗證 preview。

## 2026-08-16 M12：ChatGPT Mobile V2 正式工作區

### Goal

- 在 ChatGPT 行動裝置 fullscreen 的實際窄 viewport 中，建立 compact 市場摘要、左側真實自選樹與右側真實 K 線的單一研究工作區。
- 直接沿用 M11.5 的任意深度 watchlist group recursion、lazy direct-stock leaves 與 focused stock detail read，不建立手機專用資料或示意行情。
- 行動版移除市場雷達的視覺與垂直占用；桌機版保留既有雷達、direct items、technical evidence 與 disabled `OrderShell`。
- 移除已完成任務的 fullscreen debug 面板；保留自動 fullscreen 與明確的手動全螢幕操作。

### Non-goals

- 不修改 backend、MCP tool schema、watchlist DB、K 線／MA 計算或市場 freshness 語意。
- 不把使用者 prototype 內的示意數值、示意折線或假股票帶入正式 widget。
- 不在手機版提供 Radar、Professional Mode、drawing tools 或前端重算技術指標。
- 不連接券商、啟用送單、模擬撮合或新增任何寫入 tool；「下單介面」只展開 disabled 委託草稿。

### Hard constraints

- 手機市場摘要只能顯示 backend 已回傳的 index estimate、change、coverage、breadth、session、freshness 與 limitations；缺少成交金額等欄位時不得自行補值。
- 股票只有 direct-group tool response 才是終端葉節點；群組不得因目前未載入 child 而被前端猜成 leaf。
- 右側 chart 必須由 `omi.read_tw_stock_dashboard_detail` 的 OHLC points 與 backend moving averages 繪製；空值、錯誤與 stale 狀態要可見。
- ChatGPT fullscreen composer 會保留在畫面底部，主要操作後方必須預留安全空間，不得讓 CTA 被覆蓋。
- 360／390／430／560／768px 均不得產生 horizontal overflow；桌機 breakpoint 不得被手機 CSS 回歸。

### Done criteria

1. 行動版 header、search、market summary、truth 與 closed warning 的首屏高度維持 compact，Radar 不 render／不占位。
2. 行動版 workbench 固定為左 watchlist Tree、右 K 線；Tree 具內部捲動，group／stock selection 與 ARIA state 保留。
3. 股票葉節點顯示 backend price／change，點擊後右側顯示同一 stock identity 的 actual OHLC candles 與 MA5／20／60。
4. 手機版只保留 K 線必要控制與 OHLC；stock-specific limitations 仍可漸進揭露。
5. 底部只有「全螢幕」與「下單介面」兩個主要操作；後者只能展開 disabled／disconnected `OrderShell`。
6. Widget typecheck、tests、production build、desktop regression 與 360／390／430／560／768 browser smoke 通過。
7. `omi_search` component-scoped runtime 採用與 ChatGPT mobile host 驗收完成後，M12 才可標記 user-visible complete。
