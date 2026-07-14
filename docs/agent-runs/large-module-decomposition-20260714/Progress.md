# OMI 大型模組責任解耦進度

## 狀態

- 目前階段：里程碑 1（Dashboard ranking state ownership）實作完成，完整 frontend gate 通過
- 最後更新：2026-07-14
- Implementation gate：已開啟
- Commit 狀態：里程碑 0 baseline 已保存為 `cc2ce8d`；里程碑 1 尚未提交

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

- 里程碑 1 目前仍是未提交工作樹，必須在進入里程碑 2 前建立可獨立回退的 commit boundary。
- Browser characterization 已覆蓋 visible loaded/empty/error/reload/stale 行為；Taiwan daily-release timer 與 regional freshness nonce 尚無 fake-clock/unit-level coverage，仍依既有 integration path 與 request guard。
- `MarketDashboardClient.tsx` 仍有 4,589 行；selection/URL、radar、market tape 與 OMI context ownership 尚待里程碑 2。
- JP/KR hooks 有刻意保留的相似 transition；在 parity coverage 足夠前抽 shared core 仍可能隱藏市場差異。
- Chart、StockDetail 與 backend facade 尚未開始，本批驗證不能外推到後續里程碑。

## 已決定事項

- 拆分目標維持單一 ownership 與清楚 dependency direction，不追求任意小檔案。
- Frontend 使用 colocated hooks + pure projection + presentation layers，不新增全域 state framework。
- Ranking hook 不擁有 URL、router、presentation 或 market-specific visible wording。
- Dashboard 保留 radar/data-status composition，直到里程碑 2B 再移交完整 radar state machine。
- 每個 ownership migration 必須先通過 targeted gate，再建立獨立 commit。

## 下一步

1. 完成 repository diff/hygiene 審查並保存里程碑 1 commit。
2. 進入里程碑 2A，先補 market/group/symbol/futures/crypto/resource URL 與 back/forward characterization。
3. 建立 `useMarketSelection` 與純 `dashboardRoutes` helper；不在同批搬 radar、tape 或 formatting。
