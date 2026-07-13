# OMI 大型模組責任解耦執行計畫

## 執行原則

1. 先固定 observable behavior，再移動 implementation ownership。
2. 每次只處理一個 state machine、use case 或 presentation boundary。
3. 先保留 facade，再搬 implementation；所有 caller 穩定後才縮減 facade internals。
4. 每批都採 stop-and-fix，不用後續批次掩蓋目前 regression。
5. 行數只記錄趨勢；驗收以 dependency direction、state ownership、contract 與測試為準。

## 里程碑 0：核准後保存第一批 baseline

範圍：目前尚未提交的 watchlist ranking row projection、共用 ranking panel、Taiwan/US Playwright characterization、architecture/task docs。

實作前動作：

- 重新檢查 branch、status、staged scope 與 untracked files。
- 重跑 TypeScript、lint、production build、完整 production Playwright 與 `git diff --check`。
- 確認沒有 `.env`、DB、logs、`.next`、測試產物或無關檔案。
- 驗證通過後建立獨立 baseline commit；建議訊息為 `refactor(frontend): extract watchlist ranking boundaries`。

驗收：目前 5 個 Playwright cases 全部通過，`MarketDashboardClient` 維持既有 API/URL 行為，commit 只包含第一批抽離、coverage 與本任務文件。

## 里程碑 1：Dashboard ranking state ownership

### 1A：補足跨市場 characterization

- 增加 JP/KR loaded、empty、error 與 stale request guard 的固定 fixture。
- 覆蓋 market switch、group switch、rank change、reload、selection href 與未知 API route fail-fast。
- 固定 Taiwan progressive batch、trend 延後載入、daily freshness refresh 與 US/JP/KR refresh nonce 行為。

驗收：所有案例在移動 state 前可重複通過；fixture 不依賴 live backend 或外部 provider。

### 1B：抽 Taiwan ranking hook

- 建立 colocated `useTaiwanRankingState`，擁有 ranking、load state、trend timer、request sequence、batch merge 與 freshness refresh guard。
- Hook 接收已解析的 group、rank mode、calendar/subscription setting 與 API adapter；不擁有 market URL 或 presentation。
- Dashboard 只消費 `{state, actions}`，不再直接操作 Taiwan ranking timer/ref/effects。

驗收：Dashboard 內不再存在 Taiwan ranking fetch/effect/timer；pending row、batch order、loaded values 與 refresh timing 等價。

### 1C：抽 regional ranking hooks

- 先建立 US、JP、KR 各自 typed hook，保留現有 endpoint、type 與 refresh nonce。
- 只有三個 hook 的 state transition 與 cancellation 行為經 characterization 證明一致後，才抽 shared regional state machine；市場 row projection 保留 typed adapter。
- 任何 market-specific freshness/status wording 留在既有 contract 或 view-model adapter，不進 shared core。

驗收：Dashboard 不再直接持有 US/JP/KR ranking state/effects；四市場 loaded/empty/error/reload 行為通過。

批次驗證：

```powershell
Push-Location frontend
npm exec tsc -- --noEmit --incremental false --pretty false
npm run lint
$env:PLAYWRIGHT_SERVER_MODE='production'
npm run test:e2e -- --grep "watchlist ranking|market selection"
Pop-Location
```

Commit boundary：1A coverage、1B Taiwan hook、1C regional hooks 各自可獨立 commit；不得合併未驗證批次。

## 里程碑 2：Dashboard selection、radar 與 shell

### 2A：Market selection 與 URL contract

- 建立 `useMarketSelection` 與純 `dashboardRoutes` helpers，擁有 active market、四市場 selected group/symbol、ensure-selected-group 與 push URL 行為。
- Crypto/resource/futures selection 保留現有 query/path contract。
- Hook 不載入 ranking/radar，不判斷 freshness，不產生 UI 文案。

驗收：market/group/symbol/futures/crypto/resource 切換後 URL、selected state 與 back/forward 行為等價；Dashboard 不再有成組的 `handleSelect*`/`ensureSelected*` URL mutation。

### 2B：Radar state ownership

- 抽 Taiwan radar、snapshot save、outcome evaluation/history 的 state machine。
- US/JP/KR radar 保留各自 typed adapters；共享 cancellation/load transition 前先有對應案例。
- 保留每日 snapshot 與 outcome reconciliation 契約，不讓 GET/render path 產生新的昂貴 side effect。

驗收：雷達 mode、reload、snapshot、history、empty/error 與 stale response guard 等價；每日 snapshot backend contract 不變。

### 2C：Market tape、formatting 與 OMI context presentation

- 將 Taiwan/US/JP/KR tape 移入 presentation modules；fetch 與 polling 由對應 hook 擁有。
- 移動 sparkline、formatters 與 view-model builders，避免 presentation 重算 market policy。
- 將 `omiAskContext` 組裝移到純 builder；builder 只投影目前 hook state，不自行 fetch 或推論 freshness。

驗收：`MarketDashboardClient` 成為 composition shell，不直接呼叫 dashboard market API、不持有 request sequence/timer、不包含市場專屬 fetch effect；畫面與 OMI dock context 等價。

Phase gate：TypeScript、lint、production build、完整 production Playwright；實際 desktop/mobile browser screenshot 僅在 presentation DOM 移動時執行。

## 里程碑 3：StockDetail 資料與 side-effect ownership

### 3A：Characterization baseline

- 覆蓋 stock/index 切換、today/history/professional timeframe、chart reload、quote depth polling 與 partial failure。
- 覆蓋 data tab lazy load/cache、manual refresh、branch days、malformed payload containment。
- 覆蓋 drawing load/save、undo/redo、delete/clear 與 remote sync debounce。

### 3B：Drawing persistence

- 抽 `useChartDrawingPersistence`，擁有 drawing history、selected id、local storage、remote load/save、debounce 與 stale stock guard。
- Chart component 只接收 drawings、selected id 與 commands，不知道 persistence endpoint。

### 3C：Chart data 與 intraday refresh

- 抽 `useTaiwanStockChartData`，擁有目前約 392 行的 chart load effect、history backfill、intraday overlay、benchmark 與 cancellation。
- 抽 `useTaiwanQuoteDepth` 與 calendar-aware polling；不在 UI component 重複 session 判斷。
- Index product 的 list/contribution/chip/overnight context 移到 `useTaiwanIndexContext`。

### 3D：Data panel refresh

- 抽 `useTaiwanDataPanel`，擁有 active tab data、cache key、request key、resolved key、refresh job 與 partial result message。
- `StockDetailDataPanel` 和 data views 只接收 view model、loading/error 與 action callbacks。

### 3E：Pure projection

- 將 fallback technical report、signal chips、revenue/shareholding/institutional series projection 移到純 modules。
- 純 module 不 import React hook、API client 或 router。

驗收：`StockDetailPanel` 只保留視圖模式與 composition state；沒有超大型資料 load effect、data-tab fetch function 或 drawing persistence implementation。既有 UI、freshness 與 refresh job contract 不變。

Phase gate：每個 hook 跑 targeted Playwright + TypeScript；完成 3E 後跑 lint、production build、完整 Playwright。

## 里程碑 4：Stock detail presentation collections

- `StockDetailDataViews.tsx` 目前沒有 API/effect，屬於低風險 presentation collection；依 index、overnight、technical、revenue/earnings、shareholding、institutional 等真實 view domain 拆分。
- `StockDetailDataViews.tsx` 暫時保留 barrel/compatibility exports，避免一次修改所有 callers。
- `StockKLineChart.tsx` 的 indicator calculations 與 SVG rendering 分離，但不與 Lightweight chart 強行共用計算，除非輸入、精度與顯示語意已有 parity test。
- `USStockDetailPanel.tsx` 與 `CryptoMarketPanel.tsx` 只在台股 detail ownership pattern 穩定後套用同樣審查，不反向主導台股架構。

驗收：每個新 view module 只負責一組資料視覺；沒有把原 container 的 fetch/state 搬入 presentation collection。

## 里程碑 5：Lightweight chart engine 分層

### 5A：互動 characterization

- 覆蓋 chart mount/unmount、timeframe/style/indicator 切換、visible range、resize 與 theme change。
- 覆蓋 drawing create/select/drag/delete、undo/redo、keyboard navigation、pointer leave/cancel。
- 覆蓋 projection overlay 與 desktop/mobile 容器不重疊。

### 5B：Pure geometry 與 projection

- 將 coordinate conversion、snap、risk/reward geometry、volume profile、gap、support/resistance、technical signal projection 拆成無 React/DOM side effect 的 modules。
- 現有 `LightweightKLineChartDrawing.ts` 與 `LightweightKLineChartIndicators.ts` 依 geometry、model、projection、render contract 再分層，不建立另一個 2,000 行單檔。

### 5C：Interaction controller

- 建立 `useChartDrawingInteraction`，擁有 pointer/keyboard/drag draft state 與 command callbacks。
- Hit testing 與 geometry 為純 dependency；hook 不建立 chart instance、不 fetch、不持久化 drawing。

### 5D：Imperative chart lifecycle

- 建立 `useLightweightChartEngine` 或等價 controller，唯一負責 chart instance、series lifecycle、subscriptions、resize 與 cleanup。
- 將目前大型 lifecycle effect 拆成可命名 setup/update/cleanup steps，所有 listener 與 timer 必須有對稱 cleanup。

### 5E：Presentation layers

- 建立 `ChartCanvas`、`DrawingLayer`、`IndicatorLayer`、`ProjectionLayer`；layer 只接收 projected view model 與 event callbacks。
- Root component 組合 controller 與 layers，不內嵌上千行 overlay JSX。

驗收：沒有 interaction hook 同時建立 chart instance；沒有 render layer自行計算市場資料；mount/unmount 無重複 listener；操作、圖形與像素 framing 維持等價。

Phase gate：TypeScript、lint、production build、完整 Playwright，並以 desktop/mobile screenshot 及 canvas/DOM 非空檢查驗證。

## 里程碑 6：AI tool/context boundaries

### 6A：Public 與 patch seam inventory

- 固定 `/api/ai/tools` inventory、`omi.read_*` tool names、payload level、slot/status、source refs、warnings 與 evidence passport。
- 列出所有 caller 與 `app.ai.tools.*` / `app.ai.agentic_tools.*` monkeypatch target。

### 6B：Tool catalog 與 Taiwan readers

- 將 `list_ai_tools()` 移到 `tool_catalog.py`。
- 將 TW market overview、index、futures、stock、watchlist、freshness projection 移到 `ai/market_context/` 的獨立 modules。
- `tools.py` 保留 public wrappers；patch-sensitive fetch/service symbols由 wrapper 每次傳入 implementation。

### 6C：Agentic planning/execution 與跨市場 readers

- 將 tool definition/budget/planning/execution 移到專責 modules。
- 將 US/JP/KR/crypto context readers 移到 `ai/market_context/`，共用 compact contract 只留在 `common.py`。
- `agentic_tools.py` 保留相容 wrappers 與 tool entrypoints。

驗收：facade 不直接含 SQL/context projection 主體；public identity/patch tests、AI contract、freshness、technical report、overnight impact 與 cross-market tests 通過。

Targeted validation：

```powershell
.\.venv\Scripts\python.exe -m compileall backend\app\ai
.\.venv\Scripts\python.exe -m pytest -q backend\tests\test_ai_market_context_projection.py backend\tests\test_ai_freshness_guard.py backend\tests\test_technical_report.py backend\tests\test_overnight_impact.py
```

## 里程碑 7：Answer composition 分層

- 將 question-aware、entry、trend、position、watchlist、digest 與 LLM answer renderer 移到純 answer composition modules。
- `answer_composer.py` 保留 dispatch/facade，不讀 DB、不呼叫 provider、不改 evidence。
- 保留 Traditional Chinese/English/Japanese 現有 wording contract 與 data-limit/freshness 警告。

驗收：每個 intent renderer 可用固定 evidence fixture 測試；`analysis.human_answer`、scenario/counter-evidence 與 data limit contract 不變。

## 里程碑 8：US market service use-case 分層

### 8A：Facade 與 transaction characterization

- 固定 router/jobs/dispatch/AI imports、exceptions、function signatures、provider patch targets 與 commit/rollback behavior。
- 增加 facade export contract 與 transaction regression，避免移動後 patch 失效。

### 8B：低 side-effect use cases

- 先拆 stock master/search、read queries 與 watchlist CRUD/tree。
- 再拆 watchlist ranking/radar projection，保留 calendar/freshness 與 intraday overlay contract。

### 8C：Provider-backed resources

- 拆 prices/OHLC/intraday、SEC/profile/corporate actions、FINRA、FRED 與 resource refresh orchestration。
- Provider modules、parser、chart projection、source health 已存在，沿用現有邊界，不重建第二套 adapter。
- `service.py` wrapper 每次傳入當下 facade fetch symbols，保留既有 `patch("app.us_market.service.fetch_...")` 行為。

驗收：`service.py` 成為 public facade；provider adapter 無 DB transaction；read path 無新增 refresh；所有 US market、provider、transaction、OHLC overlay 與 API inventory tests 通過。

Targeted validation：

```powershell
.\.venv\Scripts\python.exe -m compileall backend\app\us_market
.\.venv\Scripts\python.exe -m pytest -q backend\tests\test_us_market_data.py backend\tests\test_market_provider_adapters.py backend\tests\test_market_transaction_contracts.py backend\tests\test_ohlc_intraday_overlay.py backend\tests\test_api_contract_inventory.py
```

不執行 live provider refresh；任何需要外部 API 的驗證另列 bounded smoke 並先確認。

## 里程碑 9：次級大型模組重新評分

- 重新盤點 `StockKLineChart.tsx`、`StockDetailDataViews.tsx`、`USStockDetailPanel.tsx`、`CryptoMarketPanel.tsx`、`jp_market/service.py`、`crypto_market/service.py` 與 `market/indices.py`。
- 只有在仍同時擁有多個 use case/state machine、修改熱點或 contract ownership 模糊時才排入後續拆分。
- `models.py`、i18n messages、長測試檔維持「大型但可連續檢查」分類；除非 migration/import/search 成本有新證據，不按行數拆分。
- 台股 core 與 AI decision core 的風險優先於其他市場 context layer。

驗收：`ARCHITECTURE_REVIEW.md` 更新為目前事實，列出 active、monitor、deferred 與理由，不保留已完成但過時的建議。

## 里程碑 10：完整驗收與收尾

Frontend：

```powershell
Push-Location frontend
npm exec tsc -- --noEmit --incremental false --pretty false
npm run lint
npm run build
$env:PLAYWRIGHT_SERVER_MODE='production'
npm run test:e2e
Pop-Location
```

Backend：

```powershell
.\.venv\Scripts\python.exe -m compileall backend\app
.\scripts\run-safe-validation.ps1 -Profile backend
```

Repository：

```powershell
git diff --check
git status --short
```

最終驗收：

- 所有 milestone 的 contract、UI、API/data regression 通過。
- 沒有殘留 dev server、敏感 port owner、測試產物、secret、DB 或 log 進入 staged scope。
- 更新 `Progress.md` 的前後責任指標、驗證證據與剩餘技術債。
- 每個 commit 都能獨立 build/test，並可在不改資料 schema 的前提下單獨回退。

## Stop-and-fix 規則

- Characterization 在移動前不穩定：先修 fixture 或確認 runtime，不移動 implementation。
- URL、API、SSE、tool name、payload/slot、source-health 或 freshness contract 改變：停止並恢復相容行為；產品變更另開任務。
- 抽 hook 後出現重複 polling、timer、request race 或 stale response：停止下一批，先建立單一 owner 與 cleanup。
- 抽 backend module 後既有 facade monkeypatch 不再生效：改成 wrapper dependency handoff，不修改測試去配合錯誤邊界。
- 新 abstraction 只有單一簡單 consumer、只是換名字或增加跳轉：不建立，保留局部實作。
- 需要新 dependency、DB migration、外部大量 refresh、付費 quota 或 live data repair：停止，更新 `Prompt.md` 並取得使用者確認。
- 發現不相關 dirty changes：不 revert；調整 staging scope，若與目標檔衝突則先理解後共存。
- 任一 milestone 的 targeted gate 未通過：該 milestone 不 commit、不進下一步。

## 回退策略

- 一個 ownership migration 對應一個或少量連續 commit，不跨 milestone 混合。
- Facade/barrel 在 caller 遷移完成前保留；回退時只需移除新 implementation import，不需改 public consumer。
- 本任務不含 migration，因此 rollback 不操作本機 DB。
- 純 projection 搬移優先用同 fixture 前後比對；不在 production runtime 長期維持 dual-run。

## 已決定事項

- 2026-07-14：以責任密度而非行數門檻驅動拆分。
- 2026-07-14：第一批 ranking data/presentation 已完成並通過 frontend gates，等待規劃確認後保存 baseline。
- 2026-07-14：不新增全域 state library；先採 colocated domain hooks 與純 projection modules。
- 2026-07-14：frontend 先完成目前已開始的 Dashboard 路徑，再進 StockDetail/Chart；backend 依 AI context、answer、US service 順序處理。
- 2026-07-14：`tools.py`、`agentic_tools.py`、`us_market/service.py` 使用 compatibility facade + runtime dependency handoff，避免破壞 patch seam。
- 2026-07-14：`models.py` 維持唯一 ORM registry；i18n/test fixtures 不因行數拆檔。
- 2026-07-14：每個 milestone 獨立驗證與 commit，不做 mega commit。
