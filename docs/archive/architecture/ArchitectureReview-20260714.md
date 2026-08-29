# Open Market Intelligence Architecture Review

> **HISTORICAL SNAPSHOT — 2026-07-14**
> 本文件不是 current architecture truth。請改讀
> [`docs/architecture/index.md`](../../architecture/index.md) 與
> [`BackendArchitecture.md`](../../architecture/BackendArchitecture.md)。

日期：2026-07-14

這份文件集中目前專案掃描後看到的不足與架構風險，供後續開發時對照。它不是一次性 TODO，而是後續拆 issue、排優先順序、驗證改善是否完成的基準。

## 總覽

目前最完整的是台股主線；AI 已經能回答實務問題，但架構仍偏向「規則引擎 + LLM 補強」；美股資料面可用，但判斷深度與資料健康度還沒有追上台股。

最大風險不是單一功能缺失，而是核心責任集中在少數超大型檔案：

- `backend/app/ai/ask.py`：原本約 3,900 行，Phase 1 已收斂到約 400 行；目前主要保留 OMI 問答 orchestration 與相容 alias，target resolve、policy、execution 與 response support 已拆到分檔模組。
- `backend/app/ai/tools.py`：3,373 行；主要保留 AI tool registry、資料 envelope 與跨 market readers，仍是大型後端 façade。
- `backend/app/us_market/service.py`：3,275 行，集中美股 master、報價、SEC、FINRA、FRED、watchlist 與 refresh。
- `frontend/src/components/LightweightKLineChart.tsx`：4,492 行，集中 chart engine、drawing、indicator、projection、interaction。
- `frontend/src/components/StockDetailPanel.tsx`：4,206 行，集中台股個股頁、資料 tab、refresh、專業模式、AI context。
- `frontend/src/components/MarketDashboardClient.tsx`：5,365 行，仍集中台股/美股/日股/韓股 dashboard selection、radar 與 refresh state；watchlist ranking row projection 與共用 panel 已完成第一批抽離。

2026-07-14 收斂已完成 frontend payload guard、嚴格 E2E fixtures、provider fallback telemetry、source-health snapshot age、Alembic-only startup、跨程序 background leader lock、direct dependency pins 與 CI Python/browser gates。後續大型檔案拆分採獨立批次進行；第一批已先從 dashboard ranking 的純資料與 presentation boundary 開始，避免把 runtime/contract 維護和高風險 UI 重構混在同一輪。

## P1：優先處理

### 1. OMI AI pipeline 太集中

現況：

- `backend/app/ai/ask.py` 的 `ask()` 已不再直接承擔大部分細節，但仍是整條 OMI 問答流程的 orchestration 入口：request validation、scope resolution、freshness/tool/mode stage、response assembly 與 evidence passport 會由它串接。
- 任何回答品質調整都容易牽動 refresh、mode、response schema 或 UI rendering。

風險：

- AI 回答品質問題很難定位是 intent、資料、價位、LLM、還是 answer composer。
- 後續台股、美股、期貨、指數若都繼續共用同一條流程，分支會越來越多。
- 測試會變成整包黑箱測試，難以針對單一推理階段建立 regression fixtures。

建議：

- 拆出 `ai/intent.py`：問題分類、部位語意、時間週期判斷。
- 拆出 `ai/evidence_builder.py`：市場 session、資料 freshness、技術/籌碼/基本面 evidence。
- 拆出 `ai/decision_engine.py`：進場、出場、風險、續抱、停損、停利、觀察條件。
- 拆出 `ai/answer_composer.py`：將 decision/evidence 組成穩定 human answer contract。
- `ask()` 保留為 orchestration wrapper，不再承擔細節。

### 2. 問題理解仍偏 keyword routing

現況：

- `backend/app/ai/ask.py` 的 `_infer_question_intent()` 主要靠 hint lists 判斷 `entry_decision`、`exit_decision`、`risk_check`、`trend_view`。
- 沒命中時容易回到 `general` 或 `brief`，回答就會偏模板。

風險：

- 使用者問法稍微改變，例如「要不要進一點」、「拉回怎麼看」、「這裡追會不會太晚」、「停損抓哪」，可能沒有進到專業 decision path。
- 後續一直補 keyword 會讓邏輯難維護，也不容易測試語意覆蓋率。

建議：

- 建立 table-driven intent fixtures，至少覆蓋 30-50 個中文自然問法。
- 用 deterministic classifier 先處理常見問法，再把 low-confidence 問題交給 LLM 做 intent classification。
- intent output 要包含 `intent`、`confidence`、`position_context`、`horizon`、`missing_slots`。

### 3. Signals 目前不是實際逐步推理

現況：

- 已從「完成後一次補 Signals」推進到 pipeline progress callback + queue-based streaming：`ask()` 執行中可發出問題理解、資料檢查、工具執行、推導與回答完成事件。
- `backend/app/ai/pipeline_progress.py` 已集中 Signals 的 stage message、`phase`、`dedupe_key`、elapsed timing 與 `run_stage()`，避免 progress 文字散落在 `ask.py`。
- `ask()` 的 freshness check、tool session、data/brief/analysis/report 讀取已改由 runner 包裝，具備 running/completed/failed 與 duration_ms。
- `backend/app/ai/streaming.py` 透過背景 worker 執行 `ai_ask.ask()`，SSE generator 從 queue 即時送出 progress status，再送出 evidence、tool runs、answer delta、final。
- Phase 1 已把穩定的 stage helper 拆到 `ask_question_stage.py`、`ask_tool_stage.py`、`ask_mode_stage.py`、`ask_response_stage.py` 與 `ask_finalizer.py`；尚未完成的是把所有 stage 都改成真正 generator-style pipeline，部分 dispatch 與相容 wrapper 仍由 `ask()` 串接。

風險：

- 若後續只繼續在 `ask()` 內增加流程分支，仍可能讓 orchestration 變厚。
- 真正長任務已能先送出部分狀態，且核心階段已有 `phase` / `dedupe_key` / elapsed timing / failed event；但尚未覆蓋所有細節 stage。
- 若中途失敗，已可回傳 SSE error，但還需要更細的 stage-level failure contract。

建議：

- 下一步將 AI pipeline 的 stage 業務邏輯拆成獨立 modules/generator。
- 每個 stage 實際執行前後都送出 SSE：resolve target、market session、freshness、refresh、read evidence、score、price levels、LLM synthesis、answer compose。
- Signals UI 顯示摘要，詳細內容可展開，不要佔據 answer 本體。

### 4. 前端核心元件過大

狀態：仍存在，但第一批已完成 dashboard ranking boundary 拆分；目前以 payload runtime guard、typecheck、production build 與 Playwright characterization 降低後續修改風險。

現況：

- `LightweightKLineChart.tsx` 同時處理 chart lifecycle、series、drawing、projection、indicator、keyboard/mouse interaction。
- `StockDetailPanel.tsx` 同時處理個股頁 UI、資料 tab、intraday polling、professional mode、refresh job、AI context。
- `MarketDashboardClient.tsx` 仍處理台股、美股、日股、韓股 active market、selection、radar 與 refresh states；group flatten、pending row build、ranking merge/progressive batch 已移到 `market-dashboard/watchlistRankingRows.ts`，共用 US/JP/KR ranking layout 已移到 `WatchlistRankingPanel.tsx`。

風險：

- 專業模式後續加工具會越來越容易破壞既有 chart behavior。
- OMI context 與資料 refresh 很難復用到美股或期貨。
- Playwright 已新增 loaded Taiwan parent/child watchlist ranking 與 US regional panel characterization；圖表互動與 JP/KR 狀態細節仍多數需要後續案例。

建議：

- Chart 拆成 `ChartCanvas`、`DrawingLayer`、`IndicatorLayer`、`ProjectionLayer`、`useChartInteraction`。
- 個股資料拆成 `useTaiwanStockData`、`useTaiwanIntradayRefresh`、`useTaiwanDataPanelRefresh`。
- Dashboard selection 拆成 `useMarketSelection`、`useWatchlistState`、`useRankingState`。
- 下一批優先抽 dashboard ranking load/state orchestration 或 market selection helper，不把 radar、refresh 與 routing 同時搬動。

### 5. 交易日/休市規則前後端不共用

現況：

- 台股前端 `frontend/src/lib/taiwanMarketTime.ts` 有 hardcoded holidays。
- 台股後端 `backend/app/market/trading_calendar.py` 也有 holidays。
- 美股前端 `frontend/src/lib/usMarketTime.ts` 目前主要判 weekday。
- 美股後端 `backend/app/us_market/trading_calendar.py` 才有 NYSE-like holidays。

風險：

- UI、排程、AI 對「今天是否交易日」可能不一致。
- 補班日、臨時休市、半日交易不容易同步。
- AI 明明後端知道休市，但前端 refresh/polling 仍可能用另一套規則。

建議：

- 後端作為唯一 market calendar source。
- 新增 `/api/market/calendar-status`，以 `market=tw|us|all` 回傳台股與美股 calendar status。
- 前端 market refresh state 改吃後端 calendar response，僅保留 client-side fallback。
- calendar response 包含 `is_trading_day`、`phase`、`reason`、`holiday_name`、`previous_trading_day`、`next_trading_day`、`release_windows`。

## P2：中期補強

### 6. 美股 provider 架構需要拆分

現況：

- `backend/app/us_market/service.py` 集中 Alpha Vantage、Yahoo chart、SEC companyfacts、FINRA short volume、FRED macro、watchlist refresh。
- `backend/app/us_market/sources.py` 也承擔多種 source client/parse 行為。

風險：

- provider rate limit、錯誤處理、cache、fallback 會互相混在 service 中。
- 美股要做到台股等級的資料信任與 AI 判斷時，缺少清楚 source health。

建議：

- 拆 `us_market/providers/alpha_vantage.py`、`yahoo.py`、`sec.py`、`finra.py`、`fred.py`。
- 建立 provider-level result contract：`ok`、`source`、`as_of`、`rate_limited`、`retry_after`、`data_quality`。
- 建立 source health dashboard/table，讓 UI 和 AI 都能引用。

### 7. Refresh / ensure side effect 太分散

現況：

- 多個 route 有 `ensure_daily`、`ensure_history`、`ensure_latest`、`refresh` 等參數。
- 前端個股頁與資料 tab 會依不同情境直接觸發 refresh/backfill。

風險：

- read API 與 network write/backfill side effect 耦合。
- AI 問答、UI refresh、scheduler 可能重複打外部來源。
- 很難統一控管 tool budget、sleep、rate limit、fallback_to_cached。

建議：

- 建立 `RefreshPolicy` 與 `RefreshOrchestrator`。
- read routes 預設只讀；需要 refresh 時走 job 或 explicit refresh service。
- AI refresh-before-answer 只呼叫 orchestrator，不直接碰各 source/backfill function。

### 8. OMI dock 是可用 workaround，但需要回到 React 架構

現況：

- `frontend/src/components/OmiAskDock.tsx` 透過 raw script、runtime globals、`dangerouslySetInnerHTML` 注入 dock。
- 這解決了入口消失與跨頁重掛問題，但型別與測試成本高。

風險：

- SSE event parsing、UI state、focus、abort、retry、signals popover 都難以單元測試。
- 後續若要多 panel 或 mobile layout，raw script 會變成維護負擔。

建議：

- 改成 React portal：`OmiAskDockProvider` + `useOmiAskDock`。
- SSE handling 拆成 `useOmiAskStream`。
- Signals rendering 拆成可測 component。

### 9. AI answer contract 需要版本化與 fixtures

現況：

- `analysis.human_answer`、`reasoning_steps`、`evidence_passport` 已開始穩定，但仍由大型 function 組裝。
- 前端主要靠 runtime parsing 顯示。

風險：

- 後端欄位調整可能讓前端退回 fallback text。
- 不同 target type 的 answer shape 容易漂移。

建議：

- 明確定義 `human_answer.version` 與 display schema。
- 加後端 fixture tests：台股個股、台指期、加權指數、美股個股、watchlist。
- 加前端 fixture rendering tests，確保回答 card、signals、data limits 都能顯示。

### 10. 測試保護不平均

現況：

- 後端有完整 pytest regression，CI 以 Python 3.11/3.13 matrix 執行 compile、`pip check` 與測試。
- 前端 CI 會執行 lint、TypeScript typecheck、production build 與 Playwright smoke。
- Playwright fixtures 對未知 API 直接失敗，且 SSR 預設隔離本機 live backend；目前覆蓋 OMI dock、專業圖表 shell 與 malformed portfolio payload 的局部錯誤隔離。

風險：

- 大型互動元件目前仍只有 smoke 級覆蓋；畫線拖曳、跨週期切換、休市日與 mobile layout 仍需後續案例。

建議：

- 補 Playwright smoke tests：
  - OMI dock 在個股/指數/期貨頁都看得到。
  - 問答 SSE 可以完成並顯示 answer。
  - 休市日顯示最新交易日，不觸發盤中誤判。
  - 專業模式圖表非空白，切換 timeframe 不爆。
- 保留 lint/build，並加入 `npm run test:e2e`。

## P3：後續整理

### 11. DB models registry 仍大，但暫不拆檔

現況：

- `backend/app/db/models.py` 目前 3,158 行，集中多個 domain 的 table model。

風險：

- 直接拆檔會增加 Alembic discovery、foreign-key resolution、import set 與第二個 `Base` 的風險。

建議：

- 目前保留 `models.py` 作為唯一 registry，並以 migration parity test 保護 78 張 model table 與 Alembic head 完全一致。
- 只有在先建立完整 import/constraint/index contract 後才重新評估 domain 拆檔，不以行數單獨驅動重構。

### 12. 台股資料源健康度需要更透明

現況：

- 台股資料主線成熟，但不同資料源的可用時間、失敗原因、延遲、缺資料狀態還沒有統一視覺化。
- 部分資料如分點、持股、月營收、財報具有不同 release window 與限制。

風險：

- AI 容易把「資料尚未發布」、「資料源失敗」、「資料真的缺」混在同一種資料不足敘述。

建議：

- 建立 data source health/readiness table。
- AI data limits 要引用具體原因：未到發布時間、來源失敗、資料表缺值、target 不適用。
- UI 顯示資料源狀態，不只顯示資料筆數。

### 13. 美股判斷模型不能直接複製台股籌碼模型

現況：

- 美股可取得日線、company profile、SEC facts、short volume、macro 等，但它和台股法人/分點/籌碼結構不同。

風險：

- 若硬套台股的籌碼權重，AI 會看起來有分數，但金融語意不可靠。

建議：

- 美股 adapter 應以 `price trend`、`volume/relative volume`、`sector/peer`、`fundamentals`、`macro/regime` 為核心。
- 台股 adapter 保留 `price trend`、`volume`、`institutional`、`broker branch`、`shareholding`、`revenue/financials`。
- 最終共用的是 answer contract，不是同一套 scoring weights。

## 建議執行順序

### Phase 1：穩住 OMI Decision Core

狀態：後端 AI 核心拆分第一輪已完成。

目標：

- 讓 AI 回答品質不再靠不斷補模板。
- 讓 intent、evidence、decision、answer 可以各自測試。

工作：

1. 抽 `intent` 與 fixtures。
2. 抽 `evidence_builder`。
3. 抽 `decision_engine`。
4. 抽 `answer_composer`。
5. 補 30-50 個問法 regression tests。

目前進度：

- 已新增 `backend/app/ai/decision_core.py`，集中 question intent、position context、analysis horizon、盤中判斷與常見中文問法 hints。
- `backend/app/ai/ask.py` 已改為透過 `QuestionUnderstanding` 取得 intent、horizon、position context，並把 `analysis.question_understanding` 放進 API 回應，方便 UI/Signals/除錯引用。
- `mode=auto` 且 trusted/allow_llm 成立時，進場、出場、持倉風險、風險檢查、走勢解讀會升級到 `analysis`，避免決策型問題只走快速 brief。
- 自動升級到 `analysis` 時，如果 LLM 設定或呼叫失敗，會退回 `brief` 並附 warning；使用者明確指定 `mode=analysis` 時仍保留錯誤回報。
- 已新增 `backend/app/ai/evidence_builder.py`，集中 `stock_decision_evidence_v1` 的 market session、近五日波動、MACD 品質、基本面摘要、資料品質與信心因子。
- `backend/app/ai/tools.py` 已保留 `_stock_decision_evidence()` wrapper，但實作改由 `evidence_builder.build_stock_decision_evidence()` 產生，讓資料查詢與 evidence 組裝分離。
- 已新增 `backend/app/ai/decision_engine.py`，集中技術價位解析、追價/回檔進場判斷、持倉成本距離與停損條件計算。
- `backend/app/ai/ask.py` 已保留 decision 相關 helper wrapper，但實作改委派到 `decision_engine`，讓 orchestration 與純決策規則先分離。
- 已新增 `backend/app/ai/answer_composer.py`，集中 `consumer_market_answer`、LLM report、watchlist overview、position decision 與資料限制文字的回答組裝。
- `backend/app/ai/ask.py` 的 human answer 主路徑已改委派到 `answer_composer.build_consumer_human_answer()`，`ask()` 更接近 orchestration wrapper。
- 已移除 `backend/app/ai/ask.py` 中已不再走到的舊 question-aware answer 分支與重複資料限制常數，避免回答規則出現兩份來源。
- 已新增 `backend/app/ai/stage_events.py`，集中 Signals/SSE 使用的 stage label、status payload、evidence passport、tool run 與 reasoning step 轉換規則。
- `backend/app/ai/streaming.py` 已改由 `stage_events.response_status_payloads()` 產生 status events，並新增工具執行與證據護照 status，保留原本 `evidence`、`tool_run`、`delta`、`final` 事件。
- 已新增 `backend/app/ai/progress_events.py`，定義 OMI pipeline progress callback 的輕量事件格式，讓同步 `/ask` 與 streaming 可共用同一個執行流程。
- 已新增 `backend/app/ai/pipeline_progress.py`，集中 OMI stage progress 的訊息、`phase`、`dedupe_key`、elapsed timing 與 reasoning step 發送規則。
- `backend/app/ai/pipeline_progress.py` 已新增 `run_stage()`，可統一發出 running/completed/failed，並保留原例外語意；已套用在 freshness、tool session 與 data/brief/analysis/report response building。
- 已新增 `backend/app/ai/ask_stages.py` facade，並將 `ask()` 中最容易穩定拆分的 orchestration helpers 拆到分檔模組：`ask_stage_models.py`、`ask_question_stage.py`、`ask_tool_stage.py`、`ask_mode_stage.py`、`ask_response_stage.py`。
- `ask_question_stage.py` 負責 target normalization、question understanding、policy enrichment 與 requested mode；`ask_tool_stage.py` 負責 tool session branching 與 freshness guard；`ask_mode_stage.py` 負責 report freshness fallback、mode dispatch 與 auto analysis fallback；`ask_response_stage.py` 負責 response analysis assembly。
- 已新增 `backend/app/ai/scope_resolution.py`，集中 request target parsing、台股/美股/指數/期貨/自選群組 scope resolution、clarification 與 response target 轉換。
- 已新增 `backend/app/ai/ask_policy.py`，集中 request validation、server trust/tool budget policy、mode gating、refresh-before-answer 開關與 scope id 需求檢查。
- 已新增 `backend/app/ai/ask_execution.py`，集中 data_only、brief、analysis、report 與 freshness check 的實際資料讀取/執行路徑。
- 已新增 `backend/app/ai/ask_response_support.py`，集中 analysis digest、position decision LLM 補強、reasoning steps、next actions、clarification response 與 response helper wrappers。
- 已新增 `backend/app/ai/ask_finalizer.py`，集中 `omi.ai.ask.v2` final response contract、evidence passport 建立與 answer_ready progress 發送，讓 `ask()` 不再直接組最後 response dict。
- 已新增 `backend/app/ai/technical_analysis.py`，集中 technical factor score model、horizon weighted summary、technical price levels、chart/point normalization 與 synthetic technical report generation。
- `backend/app/ai/ask.py` 主流程已改用 `ask_stages`，讓 `ask()` 更接近 request validation、scope resolution、stage orchestration、evidence passport 與 final response contract 的薄包裝。
- `backend/app/ai/ask.py` 目前約 400 行，保留既有私有 helper 名稱與 `reports/tools/orchestrator/freshness/llm` module attributes 作為相容層，避免既有 patch-based 測試與呼叫端一次性斷裂。
- `backend/app/ai/tools.py` 目前 3,373 行，已把技術分析純函式搬到 `technical_analysis.py`，但跨市場 reader 與 registry 持續成長；本輪未進行大型拆分。
- `backend/app/ai/ask.py` 已在問題理解、freshness、工具規劃、資料讀取、reasoning、evidence passport 與 answer_ready 階段呼叫 `OmiPipelineProgress`，避免 progress 組裝散落在 orchestration。
- `backend/app/ai/agentic_tools.py` 的 `execute_tool_plan()` 已能回報工具 running/success/blocked/skipped/error 狀態，讓外部刷新或工具被阻擋時不再只出現在最後結果。
- `backend/app/ai/streaming.py` 已改成背景 worker + queue，能在 `ask()` 尚未完成時即時輸出 progress status，並以 `dedupe_key` 對完成後的 response status 做去重。
- 已補 `backend/tests/test_ai_decision_core.py`，先覆蓋進場、回檔、持倉停損、盤中風險、波段/長線 horizon 與 ask wrapper 相容性。
- 已補 `backend/tests/test_ai_evidence_builder.py`，覆蓋休市 market session、近期高波動分類、資料品質、MACD、基本面與資料限制。
- 已補 `backend/tests/test_ai_decision_engine.py`，覆蓋 technical level 欄位/數字解析、追價判斷、持倉停損計算與 `ask.py` wrapper 相容性。
- 已補 `backend/tests/test_ai_answer_composer.py`，覆蓋 question-aware entry answer、LLM soft data-gap 過濾、position decision answer 與 `ask.py` wrapper 相容性。
- 已補 `backend/tests/test_ai_ask_stages.py`，覆蓋 target normalization、question/policy stage、tool session warnings/freshness 傳遞、analysis fallback 與 response analysis assembly。
- 已補 `backend/tests/test_ai_ask_refactor_modules.py`，覆蓋 scope resolution、policy trust gating、clarification response contract 與 `ask.py` 相容 alias。
- 已補 `backend/tests/test_ai_technical_analysis.py`，覆蓋 technical point normalization、synthetic technical report、factor weighted summary 與 technical price level contract。
- 已補 `backend/tests/test_ai_pipeline_progress.py`，覆蓋 structured stage events、`run_stage()` success/failure、phase、dedupe key、elapsed timing 與 invalid reasoning step 過濾。
- 已補 `backend/tests/test_ai_stage_events.py`，覆蓋初始 status、progress status、tool status、evidence status、reasoning status 與 answer_ready 序號。
- 已強化 `backend/tests/test_ai_streaming.py`，確認 SSE status 會包含 callback progress、`evidence_passport` 與 `tool_execution`。
- 已在 `backend/tests/test_ai_decision_core.py` 補 30 個常見中文問法 fixture，覆蓋買進、回檔、追價、停損、續抱、減碼、風險、走勢、短線/波段/長線 horizon。
- 已調整「現在」不再單獨觸發 intraday，避免「以現在來說能不能買」被誤判成盤中問題。
- 已補「追高風險」優先走風險檢查，避免新增追價關鍵詞後把風險問題錯分成進場問題。

尚未完成：

- `ask.py` 仍保留多個 thin wrapper / alias 名稱以維持既有測試與私有呼叫相容；後續可視呼叫端遷移情況逐步改為直接使用新模組。
- `tools.py` 仍保留 AI tool registry 與多個 reader function；後續若繼續瘦身，可依 `tool_registry.py`、`market_readers.py`、`stock_reader.py`、`watchlist_reader.py` 拆分，但這已偏 Phase 1.5 / P2 維護工作。
- 可持續把實際使用中踩到的問法追加到 regression fixtures，尤其是美股、台指期、加權/櫃買指數與自選群組語境。

### Phase 2：交易日與資料新鮮度統一

狀態：第二輪已完成，後端 API、AI evidence、前端 snapshot fallback、scheduler 與 refresh policy 已打通。

目標：

- UI、AI、scheduler 對交易日與資料發布時間使用同一份判斷。

工作：

1. 後端新增 calendar status API。
2. 前端 market time helper 改吃 API response。
3. AI evidence 使用 calendar status。
4. 新增休市/週末/發布前/發布後測試。

目前進度：

- 已新增 `backend/app/market/calendar_status.py`，集中台股/美股交易日、session phase、前後交易日與資料發布窗口。
- 已新增 `GET /api/market/calendar-status`，支援 `market=all|tw|us`。
- 已補 `backend/app/us_market/trading_calendar.py` 的 `next_us_trading_day()`、`us_market_holiday_name()` 與 holiday name map。
- `backend/app/ai/evidence_builder.py` 的 `market_session_evidence()` 會優先使用 calendar status，舊 technical report market session 保留為 fallback。
- `backend/app/ai/tools.py` 的 `stock_context.data` 會帶入 `market_calendar_status`，並把 `app.market.calendar_status` 放入 source refs。
- `backend/app/jobs/scheduler.py` 的台股 daily metrics、台股 market chip 與美股 daily refresh 已改用 calendar status 判斷交易日、expected trade date 與 release window。
- `backend/app/routers/market.py`、`backend/app/market/stock_selection_refresh.py`、`backend/app/ai/freshness.py`、`backend/app/watchlists/ranking_service.py`、`backend/app/watchlists/backfill_service.py`、`backend/app/us_market/service.py` 與 `backend/app/market/overnight_impact.py` 的 freshness/refresh policy 已改由 calendar status helper 推導預期交易日。
- 已新增 `frontend/src/lib/marketCalendarStatus.ts`，Dashboard 會定期讀取後端 status snapshot。
- `frontend/src/lib/taiwanMarketTime.ts` 與 `frontend/src/lib/usMarketTime.ts` 會優先使用後端 snapshot；snapshot 缺失或日期不符時才使用既有本地 fallback。
- 已補 `backend/tests/test_trading_calendar.py`、`backend/tests/test_ai_evidence_builder.py` 與 `backend/tests/test_calendar_status_integration.py`，覆蓋週末、休市、台股發布前/後、美股 holiday、AI evidence calendar 優先權與 scheduler release-window 行為。

尚未完成：

- 前端仍保留本地 holiday fallback；這是為了 API 載入失敗時維持 dashboard 可用，後續若有離線策略可再調整。
- 半日交易、臨時休市與補班交易日仍需外部資料源或手動 calendar table，尚未做資料庫化管理。

### Phase 3：前端互動元件拆分

狀態：P3 基線已完成，OMI dock 已回到 React portal 架構，SSE stream 已 hook 化，Chart layer 已完成第一輪低風險拆分，並已加入 Playwright smoke tests。

目標：

- 降低專業模式與 OMI dock 的回歸風險。

工作：

1. OMI dock 改 React portal。已完成：`frontend/src/components/OmiAskDock.tsx` 不再透過 raw script/runtime globals/dangerouslySetInnerHTML 注入 UI，改由 React component state 與 `createPortal()` 掛載到 stable inline portal anchor。
2. SSE stream hook 化。已完成：新增 `frontend/src/hooks/useOmiAskStream.ts`，集中 fetch、AbortController、request id stale guard 與 SSE buffer parsing。
3. Chart layer 拆分。已完成第一輪：`ProfessionalChartHeader`、`SelectedDrawingMetricsCard`、`ChartStaticIndicatorLayer` 已從 `LightweightKLineChart.tsx` 抽出。
4. 補 Playwright smoke tests。已完成：新增 `frontend/playwright.config.ts` 與 `frontend/e2e/omi-smoke.spec.ts`，覆蓋 OMI dock SSE 回答與台股指數專業圖表 shell。

本輪完成：

- OMI dock 的 open/close、question、answer、signals、tool count、final response rendering 皆改由 React state 管理。
- Signals popover 仍保留在 header 狀態鈕內，不再把處理節點整段插進 answer 本體。
- `analysis.human_answer` 有 headline 時才使用結構化回答卡；若 final response 缺少可渲染 answer，會回落到 streaming text 或空狀態提示。
- SSE parsing 可單獨測試，後續若加 retry、timeout、heartbeat 或 reconnect，不需要再改動 dock UI 主體。
- `LightweightKLineChart.tsx` 已把 header、選取畫線摘要卡與靜態 indicator SVG overlay 拆到 `frontend/src/components/chart/`，目前為 4,492 行。
- `MarketDashboardClient.tsx` 已把四市場 watchlist row projection、progressive ranking merge 與共用 ranking panel 拆到 `frontend/src/components/market-dashboard/`，由 6,042 行降至 5,365 行。
- `npm run test:e2e` 會用 Playwright 啟動隔離 backend 的 Next server，並以嚴格 route mock 測 OMI SSE、專業圖表入口、malformed payload、loaded Taiwan ranking 與 US 共用 regional panel；CI 在 production build 後以 standalone launcher 驗證正式 bundle。

後續可再做：

- `LightweightKLineChart.tsx` 仍是大型互動元件；可在下一輪繼續抽 `ChartCanvas`、互動畫線 layer、indicator calculation modules 與 projection helpers。
- `MarketDashboardClient.tsx` 仍需分批抽 ranking load/state、market selection 與各市場 tape；不得同時改 URL/API contract。
- Playwright 目前是 smoke + ranking characterization baseline；若後續要覆蓋畫線工具拖曳、時間週期切換、mobile layout，可再補更細的 e2e cases。

### Phase 4：美股 provider 與 source health

狀態：第一輪基線已完成，已建立 provider adapter module boundary、source health contract、API 與持久化 provider/source health table。

目標：

- 讓美股資料可信度與台股主線接近。

工作：

1. 拆 provider adapters。
2. 統一 provider result contract。
3. 建立 US source health。
4. 建立 US-specific decision adapter。

目前進度：

- 已新增 `backend/app/us_market/providers/`，先以 Alpha Vantage、Yahoo chart、SEC EDGAR、FINRA、FRED 的 adapter module 包住現有 fetch function，讓後續 provider-level retry/rate-limit/error contract 有清楚邊界。
- 已新增 `backend/app/us_market/source_health.py`，從現有 `us_daily_price`、`us_company_profile`、`us_sec_company_fact`、`us_corporate_action`、`us_short_volume_daily`、`macro_series_observation` 與 `us_stock_master` 推導 provider/resource health，不需要先做 migration。
- 已新增 `GET /api/us-market/source-health`，支援 `symbol` 與 `series_id` filter，回傳 `status`、`row_count`、`latest_data_date`、`expected_data_date`、`freshness_lag_days`、`data_quality` 與來源 URL。
- 已新增 `backend/app/ai/us_decision_adapter.py`，美股判斷改用 price trend、relative volume、fundamentals、FINRA short volume 與 source health 權重，不直接套用台股法人/分點/籌碼模型。
- `agentic_tools.read_us_stock_context()` 已把 `data.source_health` 與 `summary.source_health` 放進 US stock context，並把 stale source health 轉成 warnings；`reports.build_us_stock_brief()` 會把 US-specific decision adapter 結果放進 `data.analysis.decision_adapter`。
- 已新增 `provider_event` 與 `source_health_snapshot` 持久化表，`GET /api/us-market/source-health` 會把目前 health read model 同步到 snapshot，並帶入最近 provider event 摘要。
- 已補 `backend/tests/test_us_market_data.py` 的 source health regression，覆蓋 Yahoo daily stale、Alpha Vantage daily empty、profile available 與 SEC facts empty。
- 已補 `backend/tests/test_ai_us_decision_adapter.py`，覆蓋美股專屬權重與 source health penalty。

尚未完成：

- Provider adapters 仍先包住現有 `sources.py` fetch functions；下一輪可把 provider-specific payload validation、rate-limit classification、retry policy 與 `record_provider_event()` 寫入往 adapter 內移。
- US-specific decision adapter 已有第一版，但仍是本地資料規則；後續可再引入 sector/peer、macro/regime、earnings calendar 與更細的 valuation/fundamental quality。

### Phase 5：台股資料源 health/readiness

狀態：第一輪基線已完成，已建立 Taiwan source health read model、API、OMI context 注入與持久化 provider/source health table。

目標：

- 讓台股資料不足可以被明確歸因為 release timing、stale local data、empty local table，或 target 不適用。
- 讓 OMI 後續回答可以引用同一份資料源狀態，而不是各模組自行推斷。

工作：

1. 建立 Taiwan source health contract。
2. 接上 market calendar release windows。
3. 建立 API endpoint。
4. 讓 OMI 台股 context 帶入 source health。

目前進度：

- 已新增 `backend/app/market/source_health.py`，從 `stock_master`、`market_daily_price`、`institutional_trade_daily`、`margin_trading_daily`、`broker_branch_trade_daily`、`shareholding_distribution_weekly`、`monthly_revenue`、`financial_metric_quarterly` 與 `market_chip_daily` 推導資料健康度。
- 已新增 `GET /api/market/source-health`，支援 `stock_id`、`dataset`、`index_id` 與 `now` filter，回傳 `status`、`row_count`、`latest_data_date`、`latest_data_key`、`expected_data_date`、`freshness_lag_days`、`release_status`、`required` 與 `data_quality`。
- 每日資料會使用 `build_taiwan_calendar_status()` 的 release window 判斷 expected date，因此休市日與尚未發布時間不會誤判為 stale。
- `backend/app/ai/tools.py` 的 `read_stock_context()` 已把 `data.source_health` 與 `app.market.source_health` source ref 放進台股 context。
- 已新增 `backend/app/observability/provider_health.py`，提供 `record_provider_event()`、provider event 查詢、source health snapshot upsert 與查詢。
- 已新增 `provider_event` 與 `source_health_snapshot` 兩張表，migration 為 `20260615_0014_provider_source_health.py`。
- 已新增 `GET /api/system/provider-events` 與 `GET /api/system/source-health-snapshots`，作為最後驗收與後續 UI 面板的只讀入口。
- 已補 `backend/tests/test_market_source_health.py`，覆蓋 release 後 stale/empty 判斷，以及 ETF 對股權分散、營收、財報的 `not_applicable`。
- 已補 `backend/tests/test_provider_health.py`，覆蓋 provider event 寫入、latest event summary、consecutive error count 與 snapshot upsert。

尚未完成：

- 目前只有 source health API 會同步 snapshot；各外部 fetcher 還需要逐步接上 `record_provider_event()`，才能完整累積 HTTP status、proxy error、rate limit、retry-after 與連續失敗歷史。
- OMI 回答 composer 尚未系統性把 `data.source_health.entries` 轉成更友善的中文 data-limits 文案；目前先把 contract 放進 context。
- UI 尚未有資料源健康度面板；目前主要透過 API 與 AI context 消費。

## 驗證基準

每次完成上述任一階段，至少跑：

```powershell
.\scripts\run-backend-tests.ps1
```

```powershell
Push-Location frontend
npm run lint
npm run build
Pop-Location
```

若新增 Playwright/e2e 後，再補：

```powershell
Push-Location frontend
npm run test:e2e
Pop-Location
```

## 判斷標準

一項改善不只算「程式碼拆出來」，還要符合以下條件：

- 有明確 module boundary。
- 有至少一組 regression test 或 fixture。
- 前端顯示與 API contract 沒有隱性 fallback。
- README 或本文件更新目前狀態。
- 若涉及資料源，能說清楚缺資料是 release timing、source failure、target 不適用，還是本地 DB 尚未 refresh。
