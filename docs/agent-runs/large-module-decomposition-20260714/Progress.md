# OMI 大型模組責任解耦進度

## 狀態

- 目前階段：里程碑 3（StockDetail 資料與 side-effect ownership）實作完成，完整 frontend gate 通過
- 最後更新：2026-07-14
- Implementation gate：已開啟
- Commit 狀態：里程碑 0 baseline 已保存為 `cc2ce8d`；里程碑 1 已保存為 `2493387`；里程碑 2A 已保存並推送為 `88f9958`；里程碑 2B 已保存為 `12669e6`；里程碑 2C 已保存為 `ea8acf0`；里程碑 3 將由本批 `refactor(frontend): extract stock detail ownership` 保存

## 已完成

### 里程碑 0：baseline

- 保存 watchlist ranking row projection、共用 ranking panel、Taiwan/US characterization 與架構文件。
- Baseline commit：`cc2ce8d refactor(frontend): extract watchlist ranking boundaries`。
- 確認 baseline 不含 `.env`、DB、logs、`.next`、測試產物或 private data。

### 里程碑 1A：跨市場 characterization

- 補齊 JP/KR watchlist tree、items、ranking、index/chart/breadth 與 readiness fixtures。
- regional ranking mock 支援延遲、HTTP error 與自訂 response，可重現 request race。
- 新增 JP 切換至 empty KR、JP error 後 reload、KR rank change stale response guard 三個 browser cases。
- 修正 US case 的 fixture 群組選取，避免 live SSR 初始 group id 影響 mock contract。
- 所有未知 mock API route 維持 fail-fast，不以 fallback response 掩蓋漏接 contract。

### 里程碑 1B：Taiwan ranking hook

- 新增 `useTaiwanRankingState`，擁有 ranking、load state、trend pending、last-updated state。
- 搬入 progressive batch merge、request sequence、trend timer、market polling、收盤 final refresh、daily release check 與 freshness guard。
- 透過 `prepareCompanionLoad` 保留「第一批 ranking row 到達後才啟動 radar」的既有順序。
- `MarketDashboardClient` 不再直接持有 Taiwan ranking endpoint、timer、request sequence 或 freshness effect。

### 里程碑 1C：regional ranking hooks

- 新增 typed `useUsRankingState`、`useJpRankingState`、`useKrRankingState`。
- 各 hook 保留自己的 endpoint、rank type、freshness job、refresh nonce/polling 與 stale request guard。
- 暫不建立 shared regional state machine；JP/KR 雖然相似，仍等待更多 transition parity coverage。
- `MarketDashboardClient` 只負責 ranking 與 radar/data-status 的 composition callback，不再直接 fetch regional ranking。

### 行為與 React 審查

- 恢復 Taiwan ranking/freshness data-status 原有標題、來源與 context key 語意。
- 恢復 regional freshness request guard 的既有失敗後行為，避免 ownership migration 混入 retry policy 變更。
- 保留 rank/group change 的立即 request invalidation，並由 KR stale-response case 驗證。
- 檢查 hooks 規則、dependency arrays、timer cleanup、request sequence cleanup 與 typed action boundary；未發現需擴大重構的問題。
- 重複的 dashboard time formatter 暫留各 ownership module，等里程碑 2C 處理 formatting boundary。

## Ownership 變化

| 指標 | Baseline | 里程碑 1 後 | 變化 |
| --- | ---: | ---: | ---: |
| `MarketDashboardClient.tsx` 行數 | 5,365 | 4,589 | -776 |
| Dashboard `useState` 呼叫 | 96 | 70 | -26 |
| Dashboard `useEffect` 呼叫 | 27 | 12 | -15 |
| Dashboard `useRef` 呼叫 | 29 | 13 | -16 |
| Production Playwright cases | 5 | 8 | +3 |

新 hooks 的行數與 state 數不作為品質分數；關鍵結果是 ranking request、polling、freshness、timer 與 cancellation 已有明確 owner，Dashboard 不再保存第二份 implementation。

## 驗證證據

- Targeted ESLint（Dashboard、四個 ranking hooks、E2E fixture）：通過。
- `npm exec tsc -- --noEmit --incremental false --pretty false`：通過。
- `npm run lint`：通過。
- `npm run build`：Next.js 16.2.6 production build 通過，6/6 static pages 完成。
- `PLAYWRIGHT_SERVER_MODE=production npm run test:e2e`：8 passed。
- Regional targeted Playwright：US/JP/KR 4 passed。
- Production E2E 使用獨立 `3100` standalone server；完成後 listener 已釋放，既有 `3000` dev server 未停止。

## 已知風險

- 里程碑 2C 目前仍是未提交工作樹，進入里程碑 3A 前應建立可獨立回退的 commit boundary。
- Browser characterization 已覆蓋 visible loaded/empty/error/reload/stale 行為；Taiwan daily-release timer 與 regional freshness nonce 尚無 fake-clock/unit-level coverage，仍依既有 integration path 與 request guard。
- `MarketDashboardClient.tsx` 已降至 1,837 行且不再擁有 effect/ref/API transport；剩餘主要是四市場 ranking/radar composition、sidebar 與 active detail panel wiring，後續不應只為行數拆碎。
- JP/KR hooks 有刻意保留的相似 transition；在 parity coverage 足夠前抽 shared core 仍可能隱藏市場差異。
- Chart、StockDetail 與 backend facade 尚未開始，本批驗證不能外推到後續里程碑。

## 已決定事項

- 拆分目標維持單一 ownership 與清楚 dependency direction，不追求任意小檔案。
- Frontend 使用 colocated hooks + pure projection + presentation layers，不新增全域 state framework。
- Ranking hook 不擁有 URL、router、presentation 或 market-specific visible wording。
- Dashboard 只保留 radar URL composition 與 data-status wording；完整 radar state machine 已由里程碑 2B 移交 domain hooks。
- 每個 ownership migration 必須先通過 targeted gate，再建立獨立 commit。

## 里程碑 1 交接（已完成）

1. 已完成 repository diff/hygiene 審查並保存里程碑 1 commit。
2. 已補 market/group/symbol/futures/crypto/resource URL 與 Back/Forward characterization。
3. 已建立 `useMarketSelection` 與純 `dashboardRoutes` helper；本批未搬 radar、tape 或 formatting。

## 2026-07-14 里程碑 2A：Market selection 與 URL contract

### 已完成

- 新增純 route boundary `market-dashboard/selection/dashboardRoutes.ts`，集中既有 `market`、`group_id`、`stock_id`、`futures`、`symbol`、`jp_symbol`、`kr_symbol`、`radar_mode` 與 `quote_depth_preview` parse/build contract。
- 新增 `useMarketSelection.ts`，接管 active market、台股/美股/日股/韓股 group 與 instrument selection、futures、crypto/resource selection、URL push dedupe 與 Next App Router search synchronization。
- 新增無 React 的 `marketSelectionState.ts`，集中 initial state、route projection、synthetic regional stock selection 與 explorer reconciliation；避免把 843 行的第一版 hook 留成新的大檔技術債。
- `MarketDashboardClient.tsx` 不再直接持有四市場 selection state，不再包含成組 `handleSelect*`、`ensureSelected*`、`window.history` 或 route builder；只保留 ranking/radar reset、chart focus 與 status 等 domain side effects。
- Sidebar 背景 reload 現在只透過 `onExplorerDataChanged` reconciliation 更新資料，不再冒充使用者 group selection、清掉已選 instrument 或新增 history entry。
- 相同 href 不再重複 `pushState`，修正 sidebar 同時觸發 `mousedown`/`click` 時一次互動寫入兩筆 history 的問題。
- URL source of truth 改用 Next 16 `useSearchParams`；Back/Forward 會同步 active market、group、symbol、futures 與 sidebar selected state。
- JP/KR detail master-data callback 只補強目前仍選中的 symbol；舊 request 完成時不會覆蓋 Back/Forward 已還原的 selection。
- 保留現有 query 順序與 regional selection shape；台股 `stock_id` 仍只 trim，不新增強制 uppercase 的相容性變更。

### Characterization 與 regression

- 新增 TW -> US -> JP -> KR query contract case，並覆蓋 KR group 中間狀態與 JP/KR Back/Forward selected row 還原。
- 新增 TAIEX -> TXF -> Back -> Forward case，直接鎖定單一互動只能產生一筆 history 且 visible instrument 必須同步。
- 新增 crypto -> currency -> resource case，鎖定兩類 instrument selection 不新增 history、URL 維持 `market=crypto`，且內容 panel 與 sidebar selected state 同步切換。
- 擴充 regional detail mock，只補首屏必需的 stock master、SEC supplement、JP fundamentals/resource 與 KR resource/investor/source-health contract；未知 API route 仍維持 fail-fast。
- 擴充 crypto/resource read-only fixture，provider contract、source health、subscription policy 與空資料 endpoint 均採明確 payload；未知 API route 仍維持 fail-fast。
- 修正完整 suite 揭露的既有 reconciliation mismatch：空 tree 的背景 reload 不再清掉 direct-link TAIEX selection。

### Ownership 指標

| 指標 | 里程碑 1 後 | 里程碑 2A 後 | 變化 |
| --- | ---: | ---: | ---: |
| `MarketDashboardClient.tsx` 行數 | 4,589 | 4,188 | -401 |
| Dashboard `useState` 呼叫 | 70 | 46 | -24 |
| Dashboard `useEffect` 呼叫 | 12 | 12 | 0 |
| Dashboard `useRef` 呼叫 | 13 | 13 | 0 |
| Production Playwright cases | 8 | 11 | +3 |

Selection modules 行數：`dashboardRoutes.ts` 130、`marketSelectionState.ts` 455、`useMarketSelection.ts` 465。

### 驗證證據

- `npm exec tsc -- --noEmit --incremental false`：通過。
- `npm run lint`：通過，0 warning / 0 error。
- `npm run build`：Next.js 16.2.6 production build 通過，6/6 pages generated。
- selection/history targeted production Playwright，兩案各 repeat 3 次：6/6 通過。
- crypto/resource selection targeted production Playwright repeat 3 次：3/3 通過。
- TAIEX professional chart targeted production Playwright repeat 3 次：3/3 通過。
- `PLAYWRIGHT_SERVER_MODE=production npm run test:e2e`：11/11 通過。
- Production E2E 使用隔離的 `3100` standalone server，未停止既有 `3000` dev server。

### 2A 交接（已完成）

1. 已保存並推送 `88f9958 refactor(frontend): extract market selection ownership`。
2. 里程碑 2B 沿用 2A 的 route boundary，不在 radar hooks 內直接操作 browser history。

## 2026-07-14 里程碑 2B：Radar state ownership

### 已完成

- 新增 `useTaiwanRadarState.ts`，接管 mode、radar、load state、outcome summary/history、history dialog、selected snapshot、outcome evaluation 與 request sequence。
- ranking companion load 在 ranking request 開始時預留 radar request sequence；若使用者先切換 mode，較舊的 ranking callback 不會蓋回新請求。
- 新增 `useRegionalRadarState.ts` typed market adapter，只抽出已有共同證據的 load/cancel/reset transition；US 保留 intraday policy，JP/KR 維持 technical-only policy。
- `MarketDashboardClient.tsx` 不再直接持有 radar API endpoint、request sequence、mode ref 或成組 setter，只保留 route composition 與 data-status wording。
- route mode 改由 `dashboardRoute` 同步，Taiwan Back/Forward 會還原正確 mode 並重新載入資料。
- US/JP/KR 的非預設 mode 會保存在 group/symbol URL；預設 `action` 仍維持既有省略 contract。
- `normalizeDashboardRadarMode` 集中處理 route normalization，保留 legacy `volume -> momentum` 與 `weakness -> risk` aliases。
- 移除 `WatchlistRadarPanel` 無可達 UI 的 manual snapshot/outcome mutation props；daily snapshot 仍由 backend scheduler 管理，本批未在 read/render path 增加寫入 side effect。
- route/group synchronization 使用可取消的 zero-delay timer，符合 React 19 effect lint，cleanup 同時使舊 request 失效。

### Characterization 與 regression

- 實作前重現 Taiwan Back/Forward 只改 URL、未還原 radar mode/load 的缺陷。
- 實作前重現 regional mode request 正確但 URL 遺失 `radar_mode` 的缺陷。
- 新增 Taiwan mode/reload/Back/Forward synchronization case。
- 新增 Taiwan radar API error 後 reload recovery case。
- 新增 history snapshot select 與 evaluate contract case；POST 使用 `mode`、`snapshot_run_id` query parameters，不送 JSON body。
- 新增 regional mode URL preservation 與 stale response guard case。
- 所有未知 fixture API route 持續 fail-fast，避免漏接 contract 被假成功掩蓋。

### Ownership 指標

| 指標 | 里程碑 2A 後 | 里程碑 2B 後 | 變化 |
| --- | ---: | ---: | ---: |
| `MarketDashboardClient.tsx` 行數 | 4,188 | 3,697 | -491 |
| Dashboard `useState` 呼叫 | 46 | 22 | -24 |
| Dashboard `useEffect` 呼叫 | 12 | 8 | -4 |
| Dashboard `useRef` 呼叫 | 13 | 3 | -10 |
| Production Playwright cases | 11 | 15 | +4 |

Radar hooks 行數：約 `useTaiwanRadarState.ts` 430、`useRegionalRadarState.ts` 195。檔案大小不是成功指標；重點是 request lifecycle、mode synchronization、outcome/history 與 stale guard 只有一個 owner。

### 驗證證據

- `npm exec tsc -- --noEmit --incremental false --pretty false`：通過。
- `npm run lint`：通過，0 warning / 0 error。
- `npm run build`：Next.js 16.2.6 production build 通過，6/6 pages generated。
- Radar targeted production Playwright 四案各 repeat 3 次：12/12 通過。
- `PLAYWRIGHT_SERVER_MODE=production npm run test:e2e`：15/15 通過。
- Production E2E 使用隔離的 `3101` standalone server；既有 `3000` dev server 未停止。

### 風險與下一步

- 本批未修改 backend daily snapshot scheduler、外部 provider、SQLite schema 或本機市場資料。
- 里程碑 2B 已保存為 `12669e6 refactor(frontend): extract radar state ownership`。
- 里程碑 2C 抽離 market tape transport/state 與 OMI context projection；未把 detail panel 混入同一批 ownership migration。

## 2026-07-14 里程碑 2C：Market tape、formatting 與 OMI context

### 已完成

- 新增 `useTaiwanMarketTapeState.ts`，接管台股指數 summary、request sequence、交易時段 polling、每日 market-chip refresh、localStorage guard 與錯誤 callback。
- 新增 `useRegionalMarketTapeState.ts`，以已有相同行為證據的 polling core 接管 US/JP/KR tape；各市場仍保留自己的 index resolver、endpoint、query、session cadence、breadth 與 intraday fallback。
- 新增 `MarketTapePanels.tsx`，集中四市場純 presentation；元件不直接 fetch、不保存 timer，也不重新判定 freshness policy。
- 新增 `dashboardFormatters.ts` 與 `rankingPresentation.tsx`，抽離 number/time/tone、freshness label、rank/status/trend 與 sparkline projection。
- 新增純 `buildOmiAskContext.ts`，投影 TW stock/index/futures/watchlist、US、JP 與 KR target/ui context；不自行 fetch 或推論資料新鮮度。
- 新增 `useDashboardRuntime.ts`，接管全域 market calendar polling 與 resource background quote subscription；維持原 interval、visibility、request dedupe 與 silent-failure 行為。
- `MarketDashboardClient.tsx` 不再直接呼叫 dashboard market API，不持有 request sequence、timer、`useEffect` 或 `useRef`；只保留 selection/ranking/radar hook composition、可見錯誤文案與 active panel wiring。

### Characterization 與 regression

- 擴充 market tape mock，可按 market/kind/target/request number 精準延遲、失敗或回傳自訂 payload；未知 route 仍 fail-fast。
- 新增 OMI context case，鎖定 TAIEX 為 `tw_index`、KOSDAQ 為 `kr_index`，並驗證對應 `ui_context`。
- 新增 Taiwan summary race case：較舊首請求在 manual reload 後完成時不得覆寫新 summary。
- 新增 US tape query/cancellation case：鎖定 daily `bars=60`、`ensure_history=true`、`outputsize=compact`、`provider=yahoo_chart` 與 intraday request；舊 context failure 不得污染新選擇。
- 新增 US unmount/remount case：第一次載入失敗後，離開再返回市場必須重新載入並恢復成功。

### Ownership 指標

| 指標 | 里程碑 2B 後 | 里程碑 2C 後 | 變化 |
| --- | ---: | ---: | ---: |
| `MarketDashboardClient.tsx` 行數 | 3,697 | 1,837 | -1,860 |
| Dashboard `useState` 呼叫 | 22 | 13 | -9 |
| Dashboard `useEffect` 呼叫 | 8 | 0 | -8 |
| Dashboard `useRef` 呼叫 | 3 | 0 | -3 |
| Dashboard 直接 market API/job 呼叫 | 有 | 0 | 全部移交 |
| Production Playwright cases | 15 | 19 | +4 |

新 ownership modules 行數：約 `MarketTapePanels.tsx` 544、`useRegionalMarketTapeState.ts` 516、`useTaiwanMarketTapeState.ts` 222、`useDashboardRuntime.ts` 192、`buildOmiAskContext.ts` 262、`rankingPresentation.tsx` 322。行數不是完成條件；檢查重點是 transport/state、純投影與 presentation 不再互相重做責任。

### 驗證證據

- Targeted ESLint（Dashboard、tape/runtime hooks、presentation、OMI builder、E2E fixture）：通過。
- `npm exec tsc -- --noEmit --incremental false`：通過。
- `npm run lint`：通過，0 warning / 0 error。
- `npm run build`：Next.js 16.2.6 production build 通過，6/6 pages generated。
- 2C targeted production Playwright 四案各 repeat 3 次：12/12 通過。
- `PLAYWRIGHT_SERVER_MODE=production npm run test:e2e`：19/19 通過。
- Production E2E 使用隔離的 `3102`、`3103`、`3104` standalone servers；完成後 listener 均已釋放，未停止既有偏好 port runtime。

### 風險與下一步

- 本批未修改 backend、API response shape、SQLite、refresh cadence 或 visible information architecture。
- `MarketTapePanels.tsx` 刻意保留為同層級 presentation collection；四個 component 沒有 transport/state，現階段再拆成四個薄檔案不會改善 ownership。
- 台股 daily-release/calendar timer 尚無 fake-clock unit test；本批維持既有 integration contract，並以 request race、完整 E2E 與 cleanup review 驗證。
- 里程碑 2C 應先建立獨立 commit boundary，再開始 3A；下一步先補 `StockDetailPanel` characterization，不直接搬約 392 行 chart load effect。

## 2026-07-14 里程碑 3：StockDetail 資料與 side-effect ownership

### 已完成

- 擴充 Playwright OMI API fixture，支援通用 request capture、延遲與自訂 response；新增 stock/chart/quote、drawing 與 broker branch 的固定 payload。
- 新增 `useChartDrawingPersistence.ts`，唯一擁有 localStorage、remote load/save、700ms debounce、history、undo/redo、delete/clear 與 stale stock guard。
- 新增 `useTaiwanStockChartData.ts`，接管日／週／月／盤中／professional chart load、history backfill、intraday overlay、benchmark 與 request cancellation。
- 新增 `useTaiwanQuoteDepth.ts`，接管 quote depth polling、in-flight guard 與切換股票後的 stale response 防護。
- 新增 `useTaiwanDetailContext.ts`，接管 overnight impact、index list/contribution 與 market chip context。
- 新增 `useTaiwanDataPanel.ts`，接管 market calendar release status、basic detail、lazy tab data、refresh jobs、partial result、branch day cache key 與 chart reload nonce。
- 新增 `useTaiwanTechnicalReport.ts`，接管 backend technical report request、timeframe gating 與 stale stock response guard。
- 新增純 `stockDetailTechnicalReportProjection.ts`、`stockDetailSignalProjection.ts` 與 `stockDetailSeriesProjection.ts`；均不 import React hook、API client 或 router。
- `StockDetailPanel.tsx` 現在只保留 chart/view mode、indicator controls、derived memo wiring 與 JSX composition；不再內嵌大型 fetch effect、drawing persistence 或 data-tab loader。
- `playwright.config.ts` 新增明確 opt-in 的 existing server reuse；預設測試啟動策略不變，且本批未停止使用者既有 `3000` dev server。

### Characterization 與 regression

- 新增股票切換 race case：舊股票的 OHLC 與 quote depth 延遲完成時，不得覆寫目前股票。
- 新增 drawing persistence case：local drawing 必須同步 remote，clear 後仍可 undo，三次 PUT payload 依序為 1、0、1 筆 drawing。
- 新增 branch cache case：切離再回到 branch tab 不重抓相同 day key，切換 `days=5` 才發新 request。
- 保留 TAIEX professional chart shell case，並以 `data-testid`／state attributes 固定 chart、drawing 與 data-tab 可觀察契約。
- 完整 suite 揭露三個既有 fixture 脆弱點，已修正 hydration 前 dock click、summary 額外 reload request 與 regional 預選 group history 假設；測試仍驗證原 API、stale guard 與 URL contract。

### Ownership 指標

| 指標 | 里程碑 3 前 | 里程碑 3 後 | 變化 |
| --- | ---: | ---: | ---: |
| `StockDetailPanel.tsx` 行數 | 4,206 | 1,424 | -2,782 |
| StockDetail `useState` 呼叫 | 67 | 17 | -50 |
| StockDetail `useEffect` 呼叫 | 21 | 2 | -19 |
| StockDetail `useRef` 呼叫 | 11 | 0 | -11 |
| Playwright cases | 19 | 22 | +3 |

新 ownership modules 約為：`useTaiwanDataPanel.ts` 750 行、`useTaiwanStockChartData.ts` 624 行、`useChartDrawingPersistence.ts` 356 行、`useTaiwanDetailContext.ts` 177 行、`useTaiwanQuoteDepth.ts` 114 行、`useTaiwanTechnicalReport.ts` 61 行、technical report projection 658 行、signal projection 379 行、series projection 187 行。這些檔案依 state machine／純投影責任切分，不再以任意行數繼續拆碎。

### 驗證證據

- Targeted ESLint（StockDetail、六個 ownership hooks、三個純 projection、E2E fixture）：通過。
- `npm exec tsc -- --noEmit --incremental false`：通過。
- `npm run lint`：通過，0 warning / 0 error。
- `npm run build`：Next.js 16.2.6 production build 通過，6/6 pages generated。
- StockDetail targeted Playwright：index shell、stale stock response、drawing sync/history、branch cache 4/4 通過。
- `PLAYWRIGHT_REUSE_EXISTING_SERVER=1 npm run test:e2e`：22/22 通過；使用既有 `3000` dev server，未停止或替換其 process。
- `git diff --check`：通過；僅有既有 Git line-ending 提示，無 whitespace error。

### 風險與下一步

- 本批未修改 backend、API response shape、SQLite schema、market refresh policy 或可見資訊架構。
- `useTaiwanDataPanel.ts` 與 `useTaiwanStockChartData.ts` 仍屬中大型 state owner；目前各自只有單一 lifecycle boundary，後續應依修改熱點與測試證據再評估，不按行數拆成薄函式檔。
- `StockDetailDataViews.tsx` 仍是大型 presentation collection；里程碑 4 應按 index、technical、revenue/earnings、shareholding/institutional view domain 拆分並保留 compatibility exports。
- 下一步進入里程碑 4 前，先保存本批獨立 commit；不要把 chart engine interaction migration 混入同一 commit。
