# OMI 大型模組責任解耦進度

## 狀態

- 目前階段：里程碑 5D（Lightweight chart imperative lifecycle）完成，進入 5E drawing presentation layer
- 最後更新：2026-07-14
- Implementation gate：已開啟
- Commit 狀態：里程碑 0 baseline 已保存為 `cc2ce8d`；里程碑 1 已保存為 `2493387`；里程碑 2A 已保存並推送為 `88f9958`；里程碑 2B 已保存為 `12669e6`；里程碑 2C 已保存為 `ea8acf0`；里程碑 3 已保存並推送為 `13264f0`；里程碑 4A 已保存為 `b9a9596`；里程碑 4B 已保存為 `3773a8f`；里程碑 5A 已保存為 `afc8bc2`；里程碑 5B 已保存為 `194ca89`；里程碑 5C 已保存為 `8a45765`；里程碑 5D 將由本批 `refactor(frontend): extract lightweight chart engine` 保存

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

## 2026-07-14 里程碑 4A：StockDetail presentation collections

### 已完成

- 將 `StockDetailDataViews.tsx` 由 3,351 行實作集合縮成 14 行 compatibility barrel，既有 consumer import path 與 export names 保持不變。
- 新增 `stockDetailTypes.ts`、`stockDetailFormatters.ts`、`stockDetailAnalytics.ts` 與 `stockDetailDataAccess.ts`，建立 types/constants、format/job wording、純市場衍生與 optional API 的單向基礎層。
- 將 technical、overnight、index、data panel primitives 分別移入 `TechnicalDataViews.tsx`、`OvernightDataViews.tsx`、`IndexDataViews.tsx`、`DataPanelPrimitives.tsx`。
- 將 SVG 共用座標、path、tooltip 與 nearest-point helper 移入無 React state 的 `stockDetailChartGeometry.ts`。
- 將營收／獲利圖表移入 `FundamentalCharts.tsx`，股權／法人圖表移入 `ChipCharts.tsx`；兩者只接收 projected series 與 UI callbacks。
- `stockDetailSeriesProjection.ts` 現在直接擁有 revenue/earnings/shareholding/institutional projection，不再從舊大檔轉手 re-export。
- 新模組不 import compatibility barrel；barrel 只向下 re-export，避免形成循環 implementation dependency。

### Ownership 指標

| 指標 | 里程碑 4A 前 | 里程碑 4A 後 |
| --- | ---: | ---: |
| `StockDetailDataViews.tsx` 行數 | 3,351 | 14 |
| 最大 presentation domain | 單檔 3,351 | `ChipCharts.tsx` 642 |
| compatibility consumer path | 既有 | 保留 |
| Playwright cases | 22 | 22 |

其餘主要模組：`IndexDataViews.tsx` 531 行、formatters 424 行、technical views 407 行、fundamental charts 387 行、series projection 357 行。這些邊界按可獨立理解與測試的 view/data domain 建立，不按單一 component 或函式任意碎切。

### 驗證證據

- 新增 domain modules targeted ESLint：通過，0 warning / 0 error。
- `npm exec tsc -- --noEmit --incremental false`：通過。
- `npm run lint`：通過，0 warning / 0 error。
- `npm run build`：Next.js 16.2.6 production build 通過，6/6 pages generated。
- StockDetail targeted Playwright：4/4 通過。
- `PLAYWRIGHT_REUSE_EXISTING_SERVER=1 npm run test:e2e`：22/22 通過；沿用既有 `3000` dev server。

### 風險與下一步

- 本批只移動 presentation、format/projection ownership；未修改 API、資料 shape、freshness、refresh job、SQLite 或 visible UX。
- 下一批 4B 處理 `StockKLineChart.tsx` 的 indicator catalog 與純計算，不改 chart interaction、K 線可視範圍或 SVG layout。

## 2026-07-14 里程碑 4B：StockKLineChart indicator projection

### 已完成

- 將公開指標型別、分類、選項、翻譯 helper 與預設參數移入 `stock-k-line/indicatorCatalog.ts`；`StockKLineChart.tsx` 保留 compatibility re-export，既有 consumer import path 不變。
- 將 MA、EMA、Bollinger、RSI、MACD、KD、VWAP、SAR、Donchian、ATR、DMI、OBV、MFI、CCI、Williams %R、ROC、StochRSI 與相對市場計算移入純 `indicatorProjection.ts`。
- 新增單一 `projectStockKLineData` 入口，集中合併 OHLC、backend indicator payload、benchmark 與 previous-close fallback；React 元件不再編排各演算法。
- `buildChartSignals` 與 `MergedPoint` 一併歸入 projection contract；該模組不 import React，不讀 DOM、window、API 或 router。
- `StockKLineChart.tsx` 保留 SVG path、座標、panel layout、visible range、hover、wheel、pointer drag 與 reveal lifecycle，避免在同一批更動互動行為。

### Ownership 指標

| 指標 | 里程碑 4B 前 | 里程碑 4B 後 |
| --- | ---: | ---: |
| `StockKLineChart.tsx` 行數 | 3,422 | 2,041 |
| 公開 indicator catalog | 與元件混合 | `indicatorCatalog.ts` 407 行 |
| 純 indicator projection | 與元件混合 | `indicatorProjection.ts` 1,017 行 |
| consumer import path | 既有 | 保留 |
| Playwright cases | 22 | 22 |

projection 檔案雖仍有 1,017 行，但內容是同一個無 side effect 的數值運算與資料投影邊界；目前再按單一公式拆檔只會增加跨檔跳轉，未形成更清楚的 ownership。

### 驗證證據

- 新增／變更模組 targeted ESLint：通過，0 warning / 0 error。
- `npm exec tsc -- --noEmit --incremental false`：通過。
- `npm run lint`：通過，0 warning / 0 error。
- `npm run build`：Next.js 16.2.6 production build 通過，6/6 pages generated。
- 台股專業圖表與 StockDetail targeted Playwright：4/4 通過。
- `PLAYWRIGHT_REUSE_EXISTING_SERVER=1 npm run test:e2e`：22/22 通過；沿用既有 `3000` dev server，未停止或替換其 process。

### 風險與下一步

- 本批未修改圖表公式、indicator defaults、公開 export、SVG layout、可視範圍、pointer interaction、API、SQLite 或使用者可見文案。
- `StockKLineChart.tsx` 剩餘 2,041 行主要是單一 SVG renderer 與互動 lifecycle；後續若要再拆，應先補 pointer／wheel／range characterization，不能按 JSX 區塊任意切 component。
- 下一步依計畫進入里程碑 5，處理 `LightweightKLineChart` 的 geometry、interaction controller 與 imperative chart lifecycle；不在本批混入另一套 chart engine。

## 2026-07-14 里程碑 5A：Lightweight chart interaction characterization

### 已完成

- `LightweightKLineChart` 新增穩定的 chart／overlay test ids，以及 drawing tool、drawing count、selection 狀態屬性；不改畫面與操作行為。
- 新增 Playwright case，實際選取「水平」工具、在 SVG overlay 落點、確認 drawing count 由 0 變 1、PUT payload 含 1 筆 drawing，再 undo 回 0 筆。
- characterization 同時覆蓋 overlay 非空尺寸、pointer coordinate conversion、drawing commit、history 與 700ms persistence debounce。

### 驗證證據

- Lightweight chart 與 E2E targeted ESLint：通過。
- `npm exec tsc -- --noEmit --incremental false`：通過。
- 新增 pointer／drawing targeted Playwright：1/1 通過；沿用既有 `3000` dev server。

### 風險與下一步

- 本批只增加 observability 與 regression coverage，未改 chart engine、drawing geometry、API contract 或 persistence policy。
- 下一步 5B 先把 `LightweightKLineChartDrawing.ts` 按 model／analytics／geometry 分層，保留原 compatibility import path，再處理 React interaction 與 chart instance lifecycle。

## 2026-07-14 里程碑 5B：Pure model、analytics、geometry 與 projection

### 已完成

- `LightweightKLineChartDrawing.ts` 由 2,824 行縮為 3 行 compatibility barrel，既有 public export 與 consumer import path 保持不變。
- drawing contract 分為 `drawingModel.ts`（types、defaults、time／format contract）、`drawingAnalytics.ts`（line／zone／Fibonacci／AVWAP／volume-profile evidence）與 `drawingGeometry.ts`（screen-space hit testing、ray／rectangle／drag geometry）。
- `LightweightKLineChartIndicators.ts` 由 1,583 行縮為 2 行 compatibility barrel；公式移入 `indicatorMath.ts`，lightweight-charts series payload 與 visible-range helper 移入 `indicatorSeriesProjection.ts`。
- implementation modules 直接依賴下層 model，不反向 import compatibility barrel；未建立 React、DOM、chart instance 或 API side effect。
- 以 Git baseline 逐字比對五個搬移區塊，model、analytics、geometry、indicator math 與 series projection 全部一致。

### Ownership 指標

| 模組 | 拆分前 | 拆分後 |
| --- | ---: | ---: |
| `LightweightKLineChartDrawing.ts` | 2,824 | 3 |
| `LightweightKLineChartIndicators.ts` | 1,583 | 2 |
| drawing model | 混合 | 1,200 |
| drawing analytics | 混合 | 1,387 |
| drawing geometry | 混合 | 282 |
| indicator math | 混合 | 1,184 |
| indicator series projection | 混合 | 444 |

analytics 與 math 仍是中大型純模組，但各自只有單一數值領域、沒有 state 或 side effect；目前再依單一公式切碎不會增加 ownership 清晰度。

### 驗證證據

- `npm exec tsc -- --noEmit --incremental false`：通過。
- compatibility barrels 與五個新模組 targeted ESLint：通過，0 warning / 0 error。
- Git baseline 逐字比對：五個搬移區塊全部一致。
- 專業圖表 targeted Playwright：index shell、drawing persistence、pointer create/undo 3/3 通過。

### 風險與下一步

- 本批未改公式、drawing evidence、coordinate geometry、public exports、chart lifecycle、pointer state 或可見 UI。
- 下一步 5C 建立 drawing interaction controller；hit testing 只依賴 `drawingGeometry.ts`，hook 不建立 lightweight-charts instance，也不負責 persistence。

## 2026-07-14 里程碑 5C：Drawing interaction controller

### 已完成

- 新增 `useChartDrawingInteraction.ts`，集中 drawing draft、hover、snap、selection、context delete、Escape/Delete、pointer capture 與 drag preview state。
- 水平線、AVWAP、雙點工具、risk/reward 三點初始化、整線拖曳、控制點拖曳與 Shift 角度限制維持既有行為。
- hook 只透過傳入的 coordinate/chart callbacks 操作 lightweight-charts；不建立 chart instance、不載入 API，也不擁有 drawing persistence。
- `LightweightKLineChart.tsx` 移除第二份 interaction state 與 handlers，改以單一 hook contract 組合 overlay projection 與 SVG presentation。

### Ownership 指標

| 指標 | 5C 前 | 5C 後 |
| --- | ---: | ---: |
| `LightweightKLineChart.tsx` interaction 內嵌邏輯 | 約 700 行 | 0 |
| drawing interaction owner | 主元件混合 | `useChartDrawingInteraction.ts` |
| drawing persistence owner | `useChartDrawingPersistence.ts` | 不變 |

### 驗證證據

- Targeted ESLint（主圖表與 interaction hook）：通過，0 warning / 0 error。
- `npm exec tsc -- --noEmit --incremental false`：通過。
- 水平線建立、remote payload 與 undo targeted Playwright：1/1 通過；沿用既有 `3000` dev server。
- `git diff --check`：通過；僅有既有 Git line-ending 提示。

### 風險與下一步

- 本批沒有修改 drawing API contract、700ms persistence debounce、chart series、indicator formula 或 visible UI。
- 下一步 5D 抽出 imperative chart lifecycle；chart instance、series updater、ResizeObserver、visible range 與 interaction flush 應只有一個 owner。

## 2026-07-14 里程碑 5D：Imperative chart lifecycle

### 已完成

- 新增 `useLightweightChartEngine.ts`，唯一擁有 lightweight-charts instance、main/indicator series registration、series data updater 與 cleanup。
- ResizeObserver、overlay size/revision、visible logical range 保存／還原與 chart recreation key 收斂到 engine hook。
- pointer interactivity、interaction flush timer 與互動期間 pending series data 由同一 lifecycle owner 管理，避免 renderer 與 engine 各存一份狀態。
- 對外只暴露穩定 refs、range commands、interaction commands 與 overlay projection input；drawing hit test、persistence 與 SVG presentation 未移入 engine。

### Ownership 指標

| 指標 | 5D 前 | 5D 後 |
| --- | ---: | ---: |
| `LightweightKLineChart.tsx` 行數 | 3,819 | 約 2,993 |
| chart instance／series／ResizeObserver owner | 主元件 | `useLightweightChartEngine.ts` |
| engine hook 行數 | 0 | 約 930 |

engine hook 雖為中大型檔案，但內容是單一 imperative chart lifecycle；series 建立、更新與 cleanup 必須共同存在，否則容易形成跨 hook ref race。

### 驗證證據

- Targeted ESLint（主圖表、engine hook、drawing interaction hook）：通過，0 warning / 0 error。
- `npm exec tsc -- --noEmit --incremental false`：通過。
- 專業圖表 targeted Playwright：canvas shell、drawing persistence/clear/undo、pointer create/undo 3/3 通過。
- `git diff --check`：通過；僅有既有 Git line-ending 提示。

### 風險與下一步

- 本批未修改 indicator formula、series options、pane order、visible-range policy、drawing API、SVG 樣式或使用者操作文案。
- 下一步 5E 將 drawing SVG node tree 抽成 presentation component；它只接收 projected drawings 與 event callbacks，不讀 chart instance 或 API。

## 2026-07-14 里程碑 5E：drawing presentation 與完整回歸

### 已完成

- 新增 `ChartDrawingLayer.tsx`，統一擁有 projected drawings、draft、snap marker、selection badge 與 SVG event binding 的 presentation。
- `ChartDrawingLayer` 只接收 projection 結果、顏色、目前工具與 callbacks；不持有 chart instance、不發 API request，也不管理 drawing persistence。
- `LightweightKLineChart.tsx` 收斂為資料投影、engine、interaction 與 presentation 的 composition root，由 5A 前約 4,497 行降至 1,870 行。
- 將抽取前後完整 drawing SVG node tree 正規化後逐字比對：51,769 characters，SHA-256 均為 `66CD6403EF4522D9A568F33E5504FF637038F7A25C7EC58F0706B08F12059289`。
- 完整 E2E 發現區域市場已選分組被再次點擊時會重設 ranking request sequence，造成 in-flight response 永久失效；US／JP／KR selection handler 改為只有 group id 真正變更時才 reset ranking/radar state。

### Ownership 指標

| 指標 | 5A 前 | 5E 後 |
| --- | ---: | ---: |
| `LightweightKLineChart.tsx` 行數 | 約 4,497 | 1,870 |
| drawing interaction owner | 主元件 | `useChartDrawingInteraction.ts`（820 行） |
| chart lifecycle owner | 主元件 | `useLightweightChartEngine.ts`（933 行） |
| drawing SVG presentation owner | 主元件 | `ChartDrawingLayer.tsx`（1,228 行） |

這些 owner 檔案仍偏長，但各自只有一個可命名的變更理由。繼續依函式數量機械拆分，會讓 pointer state、imperative chart refs 或 SVG branch 在多個 owner 間往返，反而增加 race 與行為漂移風險。

### 驗證證據

- Targeted ESLint、完整 `npm run lint`：通過，0 warning / 0 error。
- `npm exec tsc -- --noEmit --incremental false`：通過。
- `npm run build`：Next.js 16.2.6 production build 通過，6/6 pages generated。
- 專業圖表 targeted Playwright：3/3 通過。
- 日本排序失敗在修正前以單 worker 重複 3 次皆可重現，修正後重複 3 次皆通過。
- 完整 Playwright suite：23/23 通過。
- 實際瀏覽器：桌面 1,096 x 768 與手機 390 x 844 viewport 均有非空 canvas/SVG 渲染；手機圖表寬 346px，horizontal overflow 為 0。
- 桌面圖表截圖 entropy 2.6548；手機可見圖表 crop entropy 2.9719，RGB channels 均有 0-255 variation，排除空白 canvas。
- `git diff --check`：通過；僅有既有 Git line-ending 提示。

### 風險與下一步

- 本批未改 indicator formula、drawing analytics、series options、drawing API contract、persistence debounce 或 visible-range policy。
- 里程碑 5 的 lightweight chart 大檔拆分完成。下一步重新掃描 tracked production files，依責任混雜程度排序後端里程碑 6-8，不再以行數作為唯一拆分條件。

## 2026-07-14 里程碑 6A／6B-1：AI tool catalog boundary

### 已完成

- 新增 `test_ai_tool_boundaries.py`，固定 public inventory、29 個 internal tool names、完整 schema digest 與 mutable isolation。
- 新增 `tool_catalog.py`，唯一擁有 OMI AI tool title、description 與 input schema catalog。
- `tools.py` 保留 `list_ai_tools()` public wrapper；router、dispatch、report 與外部 caller import path 不變。
- catalog 每次呼叫仍建立獨立資料結構，避免 caller mutation 污染後續 request。

### Ownership 指標

| 指標 | 搬移前 | 搬移後 |
| --- | ---: | ---: |
| `tools.py` 行數 | 3,373 | 2,639 |
| tool schema/catalog owner | `tools.py` | `tool_catalog.py`（742 行） |
| internal tool inventory | 29 | 29 |
| catalog SHA-256 | `73e3d669...d42d1be` | `73e3d669...d42d1be` |

### 驗證證據

- `backend/tests/test_ai_tool_boundaries.py`：3/3 通過。
- `python -m compileall -q app/ai`：通過。
- 測試僅有 sandbox 無法寫 `.pytest_cache` 的 warning，沒有 assertion、import 或 runtime failure。

### 風險與下一步

- 本批未修改任何 tool name、schema、reader、DB query、provider call、freshness 或 evidence contract。
- 下一步將 Taiwan market/index/futures/stock/watchlist context implementation 移入 `ai/market_context/`；`tools.py` 保留 patch-compatible wrappers。

## 2026-07-14 里程碑 6B：Taiwan AI context readers

### 已完成

- 新增 `taiwan_projection.py`，統一擁有 Taiwan slots、compact payload、freshness domain、technical evidence 與 passport projection；靜態檢查確認沒有 SQLAlchemy Session、provider、HTTP 或 transaction ownership。
- 新增 `taiwan_freshness.py`、`taiwan_market.py`、`taiwan_index.py`、`taiwan_futures.py`、`taiwan_stock.py`、`taiwan_watchlist.py`，每個 module 只擁有一個 reader/use case。
- `tools.py` 保留七個 public wrappers 與既有 import/patch path；每次呼叫以 typed dependency bundle 傳入當下 facade provider/service symbols，避免 module import 時捕捉 stale dependency。
- 固定 clock、market overview、futures 與空 freshness contract；既有 quote depth、intraday history、index summary/OHLC/intraday/chip/contribution monkeypatch tests 全部維持有效。
- watchlist radar 仍使用同一次 ranking 結果，不增加第二次 ranking read，也未新增 refresh 或 DB write side effect。

### Ownership 指標

| owner | 行數 | 主要責任 |
| --- | ---: | --- |
| `tools.py` | 191 | public facade 與 runtime dependency handoff |
| `taiwan_projection.py` | 1,282 | pure evidence/slot/freshness projection |
| `taiwan_stock.py` | 555 | Taiwan stock context use case |
| `taiwan_market.py` | 384 | Taiwan market overview use case |
| `taiwan_index.py` | 227 | Taiwan index context use case |
| `taiwan_futures.py` | 158 | Taiwan futures context use case |
| `taiwan_freshness.py` | 135 | local table freshness use case |
| `taiwan_watchlist.py` | 94 | watchlist ranking/radar context use case |

`taiwan_projection.py` 仍偏長，但只有純 projection 一個變更理由，且不持有 transport/state/DB；後續只有在出現獨立修改熱點或 contract owner 時才按 slots、freshness、compact evidence 再拆。

### 驗證證據

- `python -m compileall -q app/ai`：通過。
- AI tool boundary、market context projection、technical report、overnight impact、dispatch 與完整 AI freshness guard：98/98 通過。
- public/internal tool catalog contract：29 tools 與 schema digest 未變。
- `git diff --check`：通過；僅有既有 Git line-ending 提示。

### 風險與下一步

- 本批未改 API route、tool name、reader signature/default、payload level、slot/status、freshness、source refs、evidence passport、DB schema 或 provider refresh policy。
- 里程碑 6B 完成；下一步 6C 處理 `agentic_tools.py` 的 planning/execution 與 US/JP/KR/crypto readers，保留既有 facade 與 patch targets。

## 2026-07-14 里程碑 6C：Agentic planning／execution 與區域 readers

### 已完成

- 新增 `agentic_common.py`、`agentic_policy.py`、`agentic_planning.py` 與 `agentic_execution.py`，分離共用轉換、allowlist/budget、tool planning 與 provider dispatch。
- US／JP／KR／crypto context reader 移入 `ai/market_context/`；`agentic_tools.py` 保留 session orchestration、freshness 與 patch-compatible wrappers。
- `agentic_tools.py` 由約 2,949 行降至 479 行；service module、planner LLM 與 refresh patch target 均維持原 import path。

### Ownership 指標

| owner | 行數 | 主要責任 |
| --- | ---: | --- |
| `agentic_tools.py` | 479 | public facade、freshness 與 session orchestration |
| `agentic_policy.py` | 126 | allowlist、tool definition 與 budget policy |
| `agentic_planning.py` | 422 | deterministic／LLM tool plan |
| `agentic_execution.py` | 405 | budget enforcement、dispatch、result summary 與 progress |

### 驗證證據

- policy boundary：66/66 通過。
- planner／ask stage／overnight：77/77 通過。
- execution、market context 與區域回歸：174/174 通過。
- US／JP／KR／crypto reader 各批 targeted regression：121、93、74、104 個測試通過。

## 2026-07-14 里程碑 7：Answer composer architecture

### 已完成

- `answer_composer.py` 由 2,936 行降至 524 行，只保留 consumer answer fallback、dispatcher 與既有相容 export。
- `answer_evidence.py` 擁有資料摘要、技術位階與 decision evidence formatter；`answer_radar.py` 擁有雷達 label、row selection 與 radar answer。
- `answer_question.py` 只建立共用 evidence context 並 dispatch 語系；原約 820 行單函式拆為英文、日文、中文策略，集中於 `answer_question_locales.py`。
- 新增 facade identity regression，固定 localization、data limit、scenario、evidence、question 與 radar export 不漂移。

### Ownership 指標

| owner | 行數 | 主要責任 |
| --- | ---: | --- |
| `answer_composer.py` | 524 | consumer answer dispatch 與 compatibility facade |
| `answer_question.py` | 237 | common context 與 locale dispatch |
| `answer_question_locales.py` | 846 | 三語 intent decision templates |
| `answer_evidence.py` | 919 | evidence／technical level formatter |
| `answer_radar.py` | 637 | watchlist radar localization 與 answer |

### 驗證證據

- composer、pure module、ask refactor 與 ask stage regression：41/41 通過。
- compileall 與 `git diff --check`：通過；僅有既有 Git line-ending 提示。

## 2026-07-14 里程碑 8：US market service boundaries

### 已完成

- `us_market/service.py` 由 3,275 行降至 1,543 行，保留 provider orchestration、公開 façade 與動態 workflow dependency handoff。
- 新增 catalog、price、fundamentals 與 watchlist ORM store；DB persistence/read model 不再和 provider refresh 混在同一 owner。
- watchlist reference/freshness calculation 移入 `watchlist_metrics.py`；ranking 與 resource refresh 移入 `watchlist_workflows.py`。
- 所有 US exceptions 統一由 `errors.py` 擁有，`service.py` 保留同一 class identity。
- workflow dependencies 在每次 façade 呼叫時解析，確保測試／runtime patch 的 expected date、intraday overlay、daily/profile/SEC refresh 不會在 module import 時被凍結。

### Ownership 指標

| owner | 行數 | 主要責任 |
| --- | ---: | --- |
| `us_market/service.py` | 1,543 | provider orchestration 與 public facade |
| `fundamentals_store.py` | 595 | SEC／profile／actions／short／macro persistence |
| `watchlist_workflows.py` | 539 | ranking 與 bounded refresh workflow |
| `watchlist_store.py` | 404 | group／item CRUD 與 tree validation |
| `watchlist_metrics.py` | 192 | close reference、intraday compact 與 date parsing |
| `catalog_store.py` | 163 | symbol master persistence/query |
| `price_store.py` | 140 | daily price persistence/query |

### 驗證證據

- 完整 `test_us_market_data.py`：57/57 通過。
- store alias、exception identity 與 dynamic dependency boundary：3/3 通過。
- US market 合計 targeted regression：60/60 通過。

### 停止拆分判斷

- `service.py` 雖仍超過 1,500 行，但剩餘函式皆屬公開 provider orchestration、chart/intraday workflow 或薄 wrapper；繼續只為行數拆分會增加 callback／patch 轉接層，未形成更清楚的 transaction owner。
- 後續若 price provider 或 fundamentals provider 各自出現獨立修改熱點，再以 typed dependency bundle 抽出 workflow；目前不做預防性碎片化。
