# Progress

## Status

- Current phase: completed
- Last updated: 2026-07-14

## Completed

- 建立 checkpoint commit `ee91d6e`，保存前一輪 provider boundary、台灣期貨 router/job 與雷達每日快照維護。
- Frontend 對 portfolio response 加入 runtime array/item 驗證；malformed payload 會留在面板內顯示錯誤，不再造成整頁 `holdings.map` crash。
- Playwright fixtures 改為逐條 API contract，未列出的 `/omi-data/**` request 直接使測試失敗；新增 malformed portfolio regression。
- E2E 改用隔離 backend target，CI 使用 standalone production server；GitHub Actions 新增 TypeScript、Chromium 與 Playwright gate。
- 新增共用 provider fallback telemetry，以獨立短生命週期 session 記錄 canonical provider failure，不 commit 或 rollback 呼叫端 transaction。
- Source-health response 新增 snapshot age 與 stale 欄位；read path 不觸發 refresh 或昂貴 side effect。
- 新增跨程序 runtime file lock；只有 background leader 啟動 scheduler、crypto refresh 與 realtime collectors，follower 僅提供 API。
- 正常 startup 改為 Alembic migration 單一 schema truth，不再呼叫 `Base.metadata.create_all()`；migration test 驗證完整 table parity。
- 鎖定 backend direct dependencies，明確支援 Python 3.11/3.13，並在 CI 執行 `pip check`、compile 與完整 backend tests。
- 更新 README、backend architecture 與 architecture review，使 runtime、migration、observability、CI 及剩餘技術債與實作一致。

## Validation evidence

- `scripts/run-safe-validation.ps1 -Profile full`：backend compile 通過、backend `612 passed in 71.12s`、frontend lint 與 TypeScript 通過；sandbox build 僅因 Windows `spawn EPERM` 受阻。
- 沙盒外 `npm run build`：Next.js 16.2.6 production build 通過，6/6 static pages 完成。
- `PLAYWRIGHT_SERVER_MODE=production npm run test:e2e`：standalone production server 下 `3 passed (5.1s)`。
- Provider/fallback/health/http targeted regression：`16 passed`。
- Intraday/index targeted regression：`31 passed, 6 subtests passed`。
- Runtime lock/runtime/migration targeted regression：`10 passed`。
- `pip check`：沒有 broken requirements。

## Decisions made

- 大型元件與巨型模組拆分延後；本輪收斂其餘可局部驗證的 contract、runtime、schema、observability 與 release debt。
- Provider fallback telemetry 採 best-effort independent session，避免改變市場資料 transaction ownership。
- Alembic head migration 是 deployed schema 唯一真相；`init_db()` 僅保留給明確 legacy/seed 用途。
- Background leader election 採 OS file lock，不新增 runtime dependency；程序退出時由 OS 釋放鎖。
- Source-health GET 僅揭露 persisted snapshot age，不在 read path 重算全市場 health。
- Python requirements 只鎖 direct dependencies，以 CI matrix 驗證支援版本，不維護平台特定的完整 transitive lock。

## Remaining technical debt

- `frontend/src/components/MarketDashboardClient.tsx`、`LightweightKLineChart.tsx`、`StockDetailPanel.tsx` 仍是大型 frontend 元件。
- `backend/app/ai/tools.py`、`backend/app/us_market/service.py`、`backend/app/models.py` 仍是大型 backend 模組。
- 以上拆分需要獨立 contract characterization 與分階段 regression，不納入本輪收斂範圍。

## Next step

- 下一輪以 characterization tests 先固定大型模組行為，再按 ownership boundary 分批拆分，避免一次性 rewrite。
