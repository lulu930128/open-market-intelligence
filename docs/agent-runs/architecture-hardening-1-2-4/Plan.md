# Architecture Hardening 1/2/4 Plan

## Milestone 1：產品方向文件

Acceptance criteria:

- `ProductVision.md` 定義 OMI 的產品定位、主要流程、方向保護與 non-goals。
- `OperatingModel.md` 定義 backend/frontend/MCP/Kuro/DB 的責任邊界。
- `QualityBar.md` 定義資料、AI、UI、架構與驗證品質。
- `Roadmap.md` 將近期技術債收斂到產品化 milestone。

Validation:

- UTF-8 讀回。
- `git diff --check`。

## Milestone 2：Payload Contract 可測

Acceptance criteria:

- 新增測試確認 compact evidence slots 至少有 `status`、`capability`、`priority`。
- Canonical core slots 對外名稱穩定。
- 有 payload 的 core slots 保留 `payload_level` / `payload_ref`，consumer 不需要猜欄位。

Validation:

```powershell
.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs backend\tests\test_technical_report.py
```

## Milestone 3：Frontend Routing / Type 邊界

Acceptance criteria:

- `MarketRegion` 不再由 `SidebarWatchlistExplorer` 定義。
- Dashboard href builder 不再留在 `MarketDashboardClient` 大元件內。
- Sidebar、dashboard、US/JP/KR sidebar 共享同一個 market navigation type。

Validation:

```powershell
.\scripts\run-safe-validation.ps1 -Profile frontend
```

## Stop-and-fix Rules

- 若 backend tests 顯示 slot status 語意改變，先修測試或實作，不能只放寬 assertion。
- 若 frontend typecheck 發現 circular import 或 client/server 邊界問題，優先把 shared helper 放在 `frontend/src/lib/`，不要從 component 反向匯入。
- 若 validation 失敗原因是已知 sandbox limitation，要用更小命令或已核准方式隔離，不能直接宣稱通過。
