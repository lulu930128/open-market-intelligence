# OMI v4 第四輪驗證收斂

## 目標

在不擴大 public contract 與不改變 backend-owned trust boundary 的前提下，修正第四輪驗證報告中阻止 push 的三個 P0：

1. `data.freshness` 僅反映本次 selected capabilities 所依賴的 freshness。
2. 32 KB response budget 下仍保留 required evidence 的最小可用投影。
3. US intraday 的 latest-N 語意回傳連續的最新原始間隔點位，並公開 sampling metadata。
4. 收斂可局部驗證的 P1：restrictive capability selection、US 週末 completed session、未選 intraday 分流、source-health effective filter。

## 非目標

- 不在本輪重構 query planner、calendar service 或 refresh telemetry 架構。
- 不新增隱藏 fallback，不把 stale、missing 或 provider failure 偽裝成 ready。
- 不修改 MCP、Kuro 或 frontend 來承擔 backend 決策邏輯。
- 不 commit、不 push、不清理既有 dirty worktree。

## 完成條件

- 三個 P0 都有會先失敗、修正後通過的聚焦 regression。
- `omi.decision.v4` response 仍符合既有 schema 與 byte budget。
- selected capability quality 不再被 unselected freshness 缺口降級。
- latest-N US intraday 點位保持 1m 連續間距，metadata 與實際 sampling 一致。
- `只查` 類查詢不再混入 stock defaults，週末 US close 能以交易日曆判為 completed session。
- `problems_only` 與未選 intraday 的對外 metadata 不再自相矛盾或污染 selected quality。
- 相關 backend targeted tests 與安全驗證通過。
