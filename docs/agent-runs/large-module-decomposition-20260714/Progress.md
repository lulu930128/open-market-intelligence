# OMI 大型模組責任解耦進度

## 狀態

- 目前階段：里程碑 2B（Radar state ownership）實作完成，完整 frontend gate 通過
- 最後更新：2026-07-14
- Implementation gate：已開啟
- Commit 狀態：里程碑 0 baseline 已保存為 `cc2ce8d`；里程碑 1 已保存為 `2493387`；里程碑 2A 已保存並推送為 `88f9958`；里程碑 2B 尚未提交

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

- 里程碑 2B 目前仍是未提交工作樹，進入里程碑 2C 前應建立可獨立回退的 commit boundary。
- Browser characterization 已覆蓋 visible loaded/empty/error/reload/stale 行為；Taiwan daily-release timer 與 regional freshness nonce 尚無 fake-clock/unit-level coverage，仍依既有 integration path 與 request guard。
- `MarketDashboardClient.tsx` 仍有 3,697 行；selection/URL 與 radar 已移交，market tape 與 OMI context ownership 尚待里程碑 2C。
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
- 里程碑 2B 應先建立獨立 commit boundary，再進入 2C。
- 里程碑 2C 抽離 market tape transport/state 與 OMI context projection；不把 detail panel 或純 formatting 混入同一批 ownership migration。
