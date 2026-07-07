# Architecture Hardening 1/2/4 Progress

## 2026-07-07

Status: completed

## Completed

- 確認 worktree 從上一批 push 後保持乾淨。
- 讀取 repo `AGENTS.md`、`frontend/AGENTS.md`、README 摘要、既有 productized market payload contract 文件與相關前後端程式。
- 確認 `docs/product/` 原本是空模板且有亂碼，不能作為產品方向 source of truth。
- 確認 `MarketRegion` 目前由 `SidebarWatchlistExplorer` 匯出，`MarketDashboardClient` 內含純 URL builder，形成 UI 大元件之間的型別耦合。
- 確認 backend 已有 slot envelope 與部分 payload-level tests，可在不改 API shape 的情況下補 schema invariant。
- 更新 `docs/product/` 四份產品基線文件，替換原本空模板。
- 新增 `test_stock_context_compact_slots_follow_consumer_contract`，固定台股 compact evidence 的 canonical slots 與 slot envelope 必要欄位。
- 新增 `frontend/src/lib/dashboardNavigation.ts`，集中 `MarketRegion`、`DashboardHrefParams` 與 `buildDashboardHref`。
- 更新 dashboard、台股 sidebar、US/JP/KR sidebar 改用 shared market navigation type。

## Decisions

- 第 1 點以 repo 已確認方向整理文件，不新增未被 README/AGENTS 支撐的商業承諾。
- 第 2 點先補 contract invariant 測試，不在本輪擴張外部資料來源。
- 第 4 點先抽離 market navigation helper/type，不做大規模 dashboard rewrite。

## Validation

- `.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs backend\tests\test_technical_report.py` passed.
- `.\scripts\run-safe-validation.ps1 -Profile frontend` passed.

## Next

- 後續若要繼續第 4 點，下一個低風險切面是抽離 OMI Ask slot rendering/type 與 dashboard selection state helper。
- 後續若要繼續第 2 點，下一個切面是讓 US/JP/KR/crypto compact evidence 每個市場至少有一個 slot projection regression。
