# OMI 大型模組責任解耦進度

## 狀態

- 目前階段：長期架構規劃完成，等待使用者確認
- 最後更新：2026-07-14
- Implementation gate：尚未開啟；本輪未修改產品程式碼、未 commit

## 已完成

- 讀取 repo/root 與 frontend instructions、`docs/product/`、`BackendArchitecture.md`、`ARCHITECTURE_REVIEW.md` 和既有 task docs。
- 盤點 tracked TypeScript/Python 大檔，排除 DB、`.next`、cache 與其他 runtime artifact。
- 以 TypeScript/Python 結構分析確認 state/effect/API/function ownership，不只依 line count 判斷。
- 確認 Dashboard ranking 第一批已抽出 pure row projection 與共用 presentation panel。
- 確認 `tools.py`、`agentic_tools.py` 與 `us_market/service.py` 有大量 facade-level caller/monkeypatch seam，後續不能只做靜態 re-export。
- 確認 `models.py` 為單一 ORM registry，依既有架構決策不納入拆檔。
- 完成 `Prompt.md`、`TargetArchitecture.md` 與分十個里程碑的 `Plan.md`。

## 第一批既有成果

- `market-dashboard/watchlistRankingRows.ts`：四市場 group flatten、pending row、ranking merge 與 Taiwan progressive batch projection。
- `market-dashboard/WatchlistRankingPanel.tsx`：US/JP/KR 共用 ranking layout、loading rows 與 skeleton。
- `MarketDashboardClient.tsx`：由 6,042 行降至 5,365 行，未改 API/URL contract。
- Playwright：Taiwan parent/child ranking、selection href 與 US regional panel 已有 characterization。

## 既有驗證證據

- `npm exec tsc -- --noEmit --incremental false --pretty false`：通過。
- `npm run lint`：通過。
- `npm run build`：Next.js 16.2.6 production build 通過，6/6 static pages 完成。
- `PLAYWRIGHT_SERVER_MODE=production npm run test:e2e`：5 passed。
- `git diff --check`：上一輪通過。

這些是第一批完成時的證據；implementation gate 開啟前仍會依里程碑 0 重跑，不能視為永久有效。

## 規劃基線

| 模組 | 結構訊號 | 判斷 |
| --- | --- | --- |
| `MarketDashboardClient.tsx` | 96 state、27 effect、21 API call expression | 多市場 state machine 過載 |
| `StockDetailPanel.tsx` | 67 state、21 effect、23 API call expression | chart/data/refresh ownership 過載 |
| `LightweightKLineChart.tsx` | 16 state、12 effect、0 API；大型 lifecycle/overlay | 互動與圖表引擎耦合 |
| `StockDetailDataViews.tsx` | 5 state、0 effect、0 API | 大型 presentation collection，較低風險 |
| `backend/app/ai/tools.py` | 50 top-level functions；多個長 reader | AI facade 過重 |
| `backend/app/ai/agentic_tools.py` | 38 top-level definitions；四市場 reader | planning/execution/context 混合 |
| `backend/app/us_market/service.py` | 92 functions、7 exceptions | 多 use case/transaction owner 集中 |
| `backend/app/db/models.py` | 79 ORM classes、1 helper | 大型但一致 registry |

數字為粗略結構快照，之後用來比較 ownership 是否下降，不設任意行數 pass/fail。

## 已決定事項

- 拆分目標是單一 ownership 與清楚 dependency direction，不是追求小檔案。
- Frontend 使用 colocated hooks + pure projection + presentation layers，不新增全域 state framework。
- Dashboard 延續已完成的 ranking boundary，先拆 ranking state，再 selection/radar/tape。
- StockDetail 先拆 drawing/data/polling ownership，再處理純 view collections。
- Chart 先補互動 characterization，再動 lifecycle、geometry 與 overlay。
- Backend 保留 compatibility facade，以 wrapper runtime dependency handoff 維持既有 monkeypatch seam。
- US provider modules已存在；後續拆 use-case service，不重做 provider adapter。
- `models.py`、i18n 與長測試檔不按行數拆分。
- 每個 ownership migration 經 targeted gate 後獨立 commit。

## 已知風險

- 目前第一批產品程式碼與本規劃文件仍在同一個未提交工作樹；核准後必須先保存 baseline，不能直接疊第二批。
- 現有 Playwright 只有 5 個 smoke/characterization cases；Dashboard JP/KR、StockDetail 與 Chart interaction coverage 仍不足。
- Dashboard/StockDetail 內有多個 timer、request sequence、refresh nonce 與 local/remote persistence，搬移時最容易產生 duplicate effect 或 stale response regression。
- Chart 是最高 UI 互動風險區，只有 build/typecheck 不足以驗收。
- Backend tests大量 patch facade symbols；錯誤的 re-export 會讓測試看似能 import，但 patch 不再控制實際 dependency。
- `answer_composer.py` 的 wording 與多 locale 行為可能受 fixture 敏感，必須在純拆分前固定 intent evidence cases。
- Exact line/function counts 會隨後續修改變動，不能把本快照當成永久架構事實。

## 下一步

- 等待使用者確認 `TargetArchitecture.md` 與 `Plan.md`。
- 確認後執行里程碑 0：重新驗證、檢查 staged scope、提交目前 dashboard ranking baseline。
- Baseline commit 完成後才開始里程碑 1A 的跨市場 ranking characterization。
