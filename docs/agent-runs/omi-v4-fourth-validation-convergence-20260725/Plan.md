# 執行計畫

## Milestone 1：建立失敗基準

- 新增 selected freshness isolation regression。
- 新增 non-brief required evidence budget regression。
- 新增 US latest-N sampling regression。

驗收：三個 case 能分別重現報告中的錯誤語意。

## Milestone 2：局部修正

- 在 v4 decision projection 階段建立 selected freshness view，保留全域狀態但不讓未選取缺口影響 selected quality。
- 在 optional/required evidence removal 前先套用 capability minimum summary projection。
- 將 agentic intraday 壓縮改為 latest-N，並把 source/effective interval、sampling mode 與原始點數傳到 US context。

驗收：不改 route、request shape 或既有 capability id。

## Milestone 3：驗證與交付前審核

- 收斂 restrictive selection、US 週末 session、intraday supplemental 與 source-health filter metadata。
- 驗證既有 no-new-data cooldown 與 deferred fill-plan regression。
- 執行聚焦 pytest。
- 執行 full safe validation profile。
- 檢查 diff、禁止檔案、secret pattern 與既有 dirty worktree 邊界。

驗收：只回報已實際驗證的結果；runtime 未重啟與未執行 E2E 明確保留為剩餘風險。
