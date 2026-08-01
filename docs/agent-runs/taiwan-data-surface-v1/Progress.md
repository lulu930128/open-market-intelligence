# Taiwan Data Surface v1 進度

## 狀態

- 目前階段：依 Taiwan Reference Implementation v1.0 進行契約收斂；
  先處理 canonical status、release-aware freshness、required-first projection
  與台股資料 scope/reconciliation
- 最後更新：2026-07-29（Asia/Taipei）

## 本階段基線

- 契約來源：
  `C:\Users\thoma\Downloads\OMI_台股Reference_問題修正與強化規格_v1.0.txt`。
- 既有已確認完成：explicit selection lock、evidence-only mode lock、
  market.sectors sample-only disclosure、market.volume_state final estimate
  normalization、manifest requested limit projection。
- 本階段優先缺口：canonical status authority、release/applicability categories、
  quote volume reconciliation、TWSE/TPEX aggregate coverage、required-first
  response budget、screening complete-window policy、timestamp/unit/source refs。
- 並行 dirty worktree 的 Radar／US／frontend 變更不屬於本階段；修改與驗證
  維持 Taiwan backend/AI contract path-scoped。

## 已完成

- 在 checkpoint `abff4c2` 之上建立 `codex/taiwan-data-surface-v1`；使用者已核准
  將目前安全快照直接保存至 main。
- 建立 backend-owned public target/capability registry v2、typed
  `selection.parameters`、target+market applicability、manifest 與 deterministic
  digest。
- 保留 `omi.decision.v4` 與 `evidence.data[capability_id]` canonical projection；
  未新增 `tw_screener`、`tw_calendar`、第二套 response contract 或 MCP 市場邏輯。
- 新增 cache-only Taiwan screening ranking／coverage，第一批 metric 為外資買賣超、
  投信買賣超與融資餘額變化率；具 stable snapshot、交易日 window、deterministic
  ties/pagination 與 full-universe coverage。
- 將 quote order book、auction 與 official close 拆成獨立 capability/freshness，
  盤前 last trade unavailable 不會再連帶阻擋可用委買賣與試撮。
- 正規化 Taiwan market indices、local-sample sectors、index contributions、
  institutional flow、margin/short 與 corporate-event calendar；跨日期 TWSE/TPEx
  aggregate 不做錯誤相加。
- 正規化 stock upcoming/history events、disposition 與 trading restrictions；
  event-only query plan 不載入 OHLC、技術面、基本面、籌碼面、券商分點或 quote
  depth。
- 將 corporate-event plural filters 與 offset pagination 下推至共用 cache reader，
  避免先截 1000 筆再篩選造成後段假分頁。
- Repo MCP 與 standalone `C:\GPT_MCPtool\OMI_search` 都先讀 backend
  `/api/ai/tools`，離線才讀 backend 產生的 snapshot；兩份 adapter 不 import
  backend、不讀 DB、不計算 freshness/ranking。
- 新增 snapshot 產生器、adapter 文件、contract/screening/quote/aggregate/event
  regression tests。
- 修正 Taiwan market indices capability 遺漏 `_latest_timestamp` 所造成的
  `/api/ai/ask` 500；共用同模組 ISO date/time 正規化並保留 market event time。
- 新增高信心 `market/TW` screening 問句 routing。像「台股近五日外資買超排行
  前十名」會正規化成 `screening.ranking + screening.coverage`，並投影
  metric/window/sort_order/limit/offset typed parameters；explicit selection
  保持最高優先，不把一般個股法人問句誤轉成全市場 ranking。
- 以官方 tray `-ReplaceExisting` 流程替換舊 8797 MCP 與 tunnel runtime；
  常駐 schema 已重新載入 backend manifest，沒有在 adapter 複製 routing 或市場
  邏輯。

## 驗證證據

- Safe validation：
  `.tmp/validation/20260729-191421`；backend compileall、191 項 focused regression
  與 `git diff --check` 全部通過。
- Main pre-push regression：
  `.tmp/validation/20260729-195223` 的 117 項 failure-focused regression 通過；
  `.tmp/validation/20260729-195302` 的完整 backend suite `1174 passed`，
  compileall 與 `git diff --check` 通過。完整 suite 先揭露並已修正一般股票
  context 未建構 `event_context`、MCP literal fallback capability 漂移，以及
  payload budget compaction 將 diagnostics-only 空 answer/decision 變成 truthy
  空陣列結構的相容性問題。
- Standalone OMI_search：`python -B -m unittest discover -s tests`，
  `Ran 31 tests ... OK`；path-scoped `git diff --check -- OMI_search` 通過。
- 兩份 generated snapshot：registry=`omi.capability.registry.v2`、
  selection=`omi.capability.selection.v2`、22 targets、53 capabilities，digest
  均為
  `6fd8eacb0f17e48d0c369a0f49da887949ad856bc19249f5a2b13a5577965eb2`。
- 隔離 runtime `127.0.0.1:18400` health 證明 project root、venv 與目前
  worktree 正確；live `/api/ai/tools` schema 含 screening、quote、events、
  regulation 與 typed parameter keys。
- Live screening ask：`omi.decision.v4`、cache-only、as-of `2026-07-28`；
  coverage `1892/1973`、status=`partial`，缺口與 window warnings 保留，沒有
  隱性 full-market refresh。
- Live event calendar ask：status=`ready`、available_count=`247`、limit=`5`、
  `has_more=true`，as-of `2026-07-29` 與 assembly time 分離。
- Live `2330` disposition/restrictions ask：reader_profile=`event_only`；
  required reader 只有 stock identity/disposition，重型 market-analysis readers
  明確列為 excluded。
- Live stdio MCP：`initialize` → `tools/list` → `tools/call` 成功；
  registry/digest 與 backend 相同，business call `isError=false`，回傳 canonical
  v4 calendar evidence。
- 暫時 runtime 僅使用 `18400`；驗證後已核對並停止精確父子 PID，
  `18400` 無 listener。既有 `3000`／`8400` 程序未被操作。
- 實測回報後 focused regression：
  `test_ai_capability_contract.py`、`test_ai_market_context_projection.py`、
  `test_tw_screening.py`、`test_technical_report.py`、
  `test_tw_events_surface.py`、`test_omi_mcp_server.py` 與
  `test_ai_public_v4_contract.py` 共 135 項通過，另有 20 個 subtests 通過。
- Safe validation：`.tmp/validation/20260729-201150`；backend compileall、
  上述 focused pytest 與全 worktree `git diff --check` 均通過。
- Isolated runtime `127.0.0.1:18401`：
  - 一般 2330 explicit stock context：HTTP 200、`quality=ready`、無 blocked
    required capability。
  - `market.indices`：HTTP 200、`quality=ready`、兩個 index、as-of
    `2026-07-29T13:30:00+08:00`。
  - 自然語言外資排行：`capability_selection_mode=inferred`、window=5、
    limit=10、sort_order=desc，回傳 10 筆；coverage 缺口維持
    `quality=partial`，未誤標 blocked。
  - 驗證後已停止精確 server process，`18401` 不留 listener。
- Standalone OMI_search 31 項 unittest 通過。官方 tray restart 後，
  `127.0.0.1:8797` listener 已換成新 PID；session-preserving
  `initialize → tools/list` 顯示 registry v2、selection v2、正確 digest、
  `screening.ranking` parameters 與 `quote.order_book`。Representative
  `tools/call` 回傳 `omi.decision.v4`、`isError=false`、10 筆 typed screening
  rows；新 tunnel process 已建立 8797 connection。

## 已做決策

- 不以操作名詞建立 screener/calendar target。
- 不在 reader compact payload 建立第二套 public contract。
- 以 backend manifest／digest 消除三份人工 enum 漂移。
- Snapshot 只是 backend 不可用時的 schema fallback；正常狀態以
  `/api/ai/tools` 為權威。
- Screening、event calendar 與 regulation read path 固定 cache-only；需要外部
  contribution fetch 的 capability 仍由 backend trust/budget gate 控制。
- 既有 derivatives capability 足以表達目前台股衍生品 surface，不新增同義
  capability。

## 已知風險

- 使用者目前 `8400` runtime 於 19:34 啟動，早於本次 source remediation；
  仍不是自然語言 routing 與 market-indices fix 的正式部署證據。20:18 時另一批
  Radar／US 未提交檔案仍持續新增，為避免載入半成品，本輪刻意不重啟 8400。
- 本階段未改 frontend；UI 仍可使用既有 specialized routes，新的 canonical
  capability surface 先供 AI/MCP/Kuro consumer 使用。
- `market.sectors` 明確是 OMI local sample，不宣稱官方全市場 sector breadth。
- 使用者要求保存整個目前專案快照，因此
  `docs/台股Radar現行計算與判斷基準_v1.0.txt` 會原樣納入 main checkpoint。
  文件證實現行 Radar bucket、批次相對 grade、盤中 overlay 與 T+1 hit/miss
  是不同語意，不能直接包成一般 ranking。
- 下一階段仍可擴充 `screening.radar`、更多 ranking metrics、technical
  indicators/signals/levels split、持股/融資歷史與 ownership concentration；
  這些不應回頭破壞本次 registry kernel。
- Standalone OMI_search 所在 monorepo 有其他專案既有 dirty changes；本輪只改
  `OMI_search/`，後續 commit/push 仍須 path-scoped audit。

## 下一步

- 等並行 Radar／US 工作樹完成並通過其驗證後，使用 launcher 安全重啟主要
  backend，再對實際 selected port 重跑一般 2330、market indices、自然語言
  screening 與外部 MCP smoke；完成後勾選 Plan milestone 8。
- 以 `docs/台股Radar現行計算與判斷基準_v1.0.txt` 為下一階段輸入，先把
  universe-independent read-only Radar 與 outcome contract 分離；外部 read
  不建立 snapshot、不 evaluate/write outcome。
- Main repo 依使用者指示直接保存至 main；`C:\GPT_MCPtool\OMI_search` 仍是另一個
  repo 的 path-scoped publish，未納入本次 main push。

## Taiwan Reference Contract v1.0 收斂結果

- 建立 consumer-facing canonical status authority，將 applicability、
  availability、freshness、release、coverage 與 usability 分離；正常的
  post-close、pending release、not applicable 與 valid empty 不再被誤送進
  missing／fill loop。selected capability 的錯誤與 background provider
  history 也不再混為同一層級。
- Explicit selection 採 locked policy；推論能力只進 optional，不會擴大
  required。outward trace 現在揭露 capability origins、inference policy、
  requested/effective output、override reason，以及 requested/effective limit、
  returned count、truncated。
- Required-first response projection 已覆蓋 4096／8192／16384／65536 budget；
  evidence-only 維持空 decision，必要 root semantics
  `transport_ok`、`request_valid`、`execution_completed`、`data_available` 與
  `quality_status` 也已納入 FastAPI response model／OpenAPI。
- 台股 quote 與 intraday outward contract 明確揭露 provider path、fallback、
  cache、TWD 價格／成交值單位，以及 canonical shares 對 provider lots 的
  轉換。intraday closing auction、synthetic 與 indicator eligibility 保留在
  bar metadata；技術分數帶出固定 scale、range、model version 與 normalization。
- 台股 market aggregate 揭露 TWSE／TPEX coverage 與 reconciliation；index
  contribution 外部讀取受 tool budget 約束並產生 per-index tool run。screening
  預設要求完整觀測窗口，event filters、company profile、corporate actions、
  margin missing semantics 與 quote volume reconciliation 均已補齊。
- Backend registry、repo MCP 與 standalone `C:\GPT_MCPtool\OMI_search`
  fallback snapshot 已重生：
  registry=`omi.capability.registry.v2`、
  selection=`omi.capability.selection.v2`、22 targets、53 capabilities，
  digest=`8ad8f0189671bae1ab8da2d85c1a44842763e698b501b2b66a0c898ec00cc87d`。

### 最終驗證

- Backend safe validation：
  `.tmp/validation/20260729-231815`；compileall、完整 suite
  `1253 passed in 126.30s` 與 `git diff --check` 全部通過。
- 最後一輪 focused contract regression：
  capability／projection／decision envelope／public v4 共 122 tests 與
  33 subtests 通過；intraday remediation／technical regression 所在組共
  141 tests 與 15 subtests 通過；MCP boundary 組 30 tests 與 2 subtests
  通過。
- 隔離 backend `127.0.0.1:18402` health 證明 project root 與
  `.venv` interpreter 正確；live `/api/ai/tools` 回傳上述 registry、
  selection、digest 與 `tw.intraday.bars.v2`，且預設欄位含 currency、
  price unit 與 canonical volume unit。
- Live 2330 explicit evidence-only ask：HTTP 200、root semantics 全為成功、
  `quality_status=ready`、`inference_policy=explicit_selection_locked`、
  decision 維持空物件；20 根 intraday bars 回傳
  `currency=TWD`、`price_unit=TWD`、`volume_unit=shares`、
  `canonical_volume_unit=shares`、`provider_volume_unit=lots`，
  event time 為 `2026-07-29T13:30:00+08:00`，最新 bar 為
  `closing_auction`、非 synthetic 且可用於 indicator。
- 同一 live response 的 technical selected composite 為 `-4.2`，
  range `-7..7`、scale=`technical_factor_composite_v1`；分數語意由 backend
  contract 提供，不需 consumer 反推。
- Live company profile／corporate actions ask：
  兩個 capability 都 usable；actions requested/effective limit 均為 20，
  manifest returned count=3、truncated=false。非法 event date range 則回
  HTTP 400、`INVALID_PARAMETER`，field 精確指向
  `selection.parameters.events.calendar.date_to`。
- Live stdio MCP：
  `initialize` → `tools/list` → `tools/call(omi.ask)` 成功；protocol
  `2025-06-18`、public digest 與 backend 一致、business call
  `isError=false`，並保留 evidence-only、canonical shares／provider lots、
  event time 與所有 root semantics。
- Standalone `OMI_search` fallback 也已同步新 digest，intraday default fields
  含 currency、price unit 與 canonical volume unit；`python -B -m unittest
  discover -s tests` 為 `Ran 31 tests ... OK`，monorepo
  `git diff --check -- OMI_search` 通過。
- 驗證後已精確停止隔離 uvicorn，`18402` listener count=0。既有
  `3000`／`8400` PID 未被停止、重啟或替換。

### 剩餘 deployment 邊界

- 本 milestone 已完成 source、regression 與隔離 outward proof；正式 8400
  仍早於這批 source，且同一 worktree 另有 Radar／US 並行修改。依既定安全
  決策不在此時載入混合狀態；待並行變更穩定後由 milestone 8 進行 launcher
  restart，再交由使用者以最新版做實際 UI／Kuro 使用情境驗收。

## 2026-07-31 MCP 缺資料補抓與 outward refresh outcome 收斂

### 已完成

- 修正 tool execution 將「函式正常回傳」誤當成「provider operation 成功」
  的根因。`tool_runs` 保留 legacy `status`，並新增：
  - `transport_status`：呼叫、deadline 與背景工作 transport 結果。
  - `operation_status`：provider／dataset 工作的 succeeded、partial、failed、
    timeout、pending、blocked 或 skipped。
  - `evidence_status`：本次 tool result 是否提供 available、partial、
    unavailable、pending 或尚待 reconciliation 的 evidence。
  - `result_status`：保留 provider 回傳的原始 business status。
- Background job 現在會檢查 inner result；例如 transport success 但
  `status=error` 的 TDCC 回應會完成為 public `failed`，不再是 completed。
- `refresh_selected_stock_data()` 會把 nested provider failure 彙整為 bounded
  `failed_steps`，保留 dataset、label、provider、target、refresh outcome、
  error message 與 retryable；shareholding telemetry 也會帶出錯誤原因。
- Reconciliation、fill-plan successfully-attempted 與
  `current_request_failures` 改以 `operation_status` 判斷。transport success /
  operation failed 會保留 remaining fill action，並提供
  `remaining_fill_action_detail`。
- Capability manifest 新增 refresh ownership metadata：
  `refresh_strategy`、`fill_operation`、`refresh_possible_now`、
  `refresh_requires_market_open`、`writes_market_cache`、
  `estimated_calls` 與 `expected_timeout_seconds`。
- 台股 quote snapshot、五檔、auction、official close 與 intraday bars 改為
  `reader_fetch`；移除不存在的 `tw.refresh_quote`／`tw.refresh_intraday`
  executable fill 宣告。缺口會以 `reader_fetch_on_primary_request` 說明，
  不再生成無法執行的 continuation。
- 台股 continuation gate 已補齊：使用者選定有效 granular action 時，即使
  aggregate freshness 已是 current，仍會進入 target/action/plan
  revalidation 後的 bounded tool session。
- Response budget compaction 只在 summary 實際縮小 payload 時才替換 capability
  data，避免對已依 selection 投影的精簡資料額外插入
  `projection_level=summary`。
- Repo MCP 與 standalone `C:\GPT_MCPtool\OMI_search` snapshot 已同步：
  registry=`omi.capability.registry.v2`、selection=`omi.capability.selection.v2`、
  22 targets、55 capabilities、
  digest=`ed1d6ef622bb56b12e68eaae9cb81c29cd825c25e4917c01c3783001200c1fe9`。

### 驗證

- 基線先確認兩個既有 failure：stale quote 測試仍期待已不存在的
  `tw.refresh_quote` invoke，以及 internal tool catalog hash 尚未重生。
  本次 contract 修正與 snapshot 重生後，兩者皆已更新為新契約。
- Safe validation `.tmp/validation/20260731-000725`：
  backend compileall、138 項 focused pytest 與 `git diff --check` 全部通過。
- 最終擴大 contract regression `.tmp/validation/20260731-002209`：
  252 項 pytest 通過，涵蓋 capability、ask stage、freshness guard、
  decision envelope、tool boundary、outward contract、selected refresh、
  repo MCP 與 public v4；backend compileall 與 `git diff --check` 亦通過。
- Standalone OMI_search：
  `python -B -m unittest discover -s tests` 為 `Ran 31 tests ... OK`；
  path-scoped `git diff --check -- OMI_search` 通過。
- Repo 與 standalone snapshot SHA-256 均為
  `95F0084D1320E5615A33F45B12D20392061B350332F40E98E4986F4188551303`，
  byte parity=true。

### Runtime 驗收

- 隔離 runtime `127.0.0.1:18403`：
  - 8299 ownership cache-only ask 先產生可執行的
    `tw.refresh_shareholding` action；以 `max_calls=1`、
    `max_external_fetches=1`、`max_total_seconds=12` 執行後，
    outward `transport_status=success`、`operation_status=succeeded`、
    `evidence_status=available`，reconciliation 已 satisfied。
  - 2330 quote 在 32KB response budget 下回傳
    `refresh_strategy=reader_fetch`、`fill_operation=null`，
    `budget_met=true`、`required_payload_preserved=true`。
  - stdio MCP 完成 `initialize → tools/list → tools/call(omi.ask)`，
    protocol=`2025-06-18`、`isError=false`、contract=`omi.decision.v4`。
- 隔離 runtime 啟動時依既有 Alembic lifecycle 套用 pending migration
  `20260730_0046 → 20260730_0047`；未重建或覆寫 SQLite。
- 8299 bounded TDCC 驗證有依既有 policy 寫入該標的 shareholding cache；
  無全市場 refresh。
- 2026-07-31 00:26 使用者由正式 tray launcher 重開服務：
  - launcher log 顯示 backend 使用 repo `.venv`，backend=`8400`；
    frontend 因 Windows TCP excluded range 自動由 `3000` 改選 `3179`，
    兩端 health 均為 OK。
  - 正式 HTTP `omi.ask` 回傳
    `public_contract_digest=ed1d6ef622bb56b12e68eaae9cb81c29cd825c25e4917c01c3783001200c1fe9`；
    quote manifest 為 `reader_fetch`、無 fake fill operation，
    32KB budget 實際約 7.8KB 且 required payload 保留。
  - 正式 stdio MCP 再次完成
    `initialize → tools/list → tools/call(omi.ask)`；
    暴露 `omi.ask`／`omi.ask_stream`、`isError=false`、quality=`ready`，
    digest 與 repo／standalone snapshot 一致。

### 明日使用者驗收保留項

- 盤中時段確認 quote depth／試搓 indicative match volume 的實際 provider
  availability 與語意；休市／盤前 cache-only 只能證明 fallback contract。
- 以真實「昨天」美股問句重驗交易日、session finalization 與 calendar
  semantics；本輪未擴大修改美股日期解析。
