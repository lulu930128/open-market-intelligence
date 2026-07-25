# 進度

## 目前狀態

- 已讀第四輪驗證問題清單。
- 已修正三個 P0 的實際根因：
  - `data.freshness` 仍從全域 `response.freshness` 投影。
  - budget compaction 僅在 brief mode 先做 capability summary，其他 mode 會進入 required evidence removal。
  - `_compact_intraday_points()` 使用全區間均勻抽樣，與 latest-N 語意衝突。
- 已收斂四個局部 P1：
  - `只查` / `只要` capability hint 使用 restrictive selection。
  - US 週末最近收盤使用 US trading calendar 判斷 completed session。
  - 未選取 intraday 缺口移到 supplemental context。
  - `problems_only=true` 時 `include_healthy` 回報 effective false，並保留 requested value。
- no-new-data cooldown 已由既有 refresh telemetry 與 deferred fill-plan tests 覆蓋。

## 工作邊界

- 僅修改三個 P0 直接相關的 backend projection、sampling 與 regression tests。
- 保留 repo 既有未提交變更，不做 reset、commit 或 push。

## 待完成

- [x] 建立並確認三個 regression failure。
- [x] 修正 selected freshness projection。
- [x] 修正 required evidence minimum projection。
- [x] 修正 US latest-N sampling metadata。
- [x] 收斂四個局部 P1 並驗證 cooldown。
- [x] 執行 targeted regression 與 full safe validation。
- [x] 審核禁止 artifact 與 key-shaped secret pattern。

## 驗證證據

- 三個 P0 regression：`3 passed`。
- P1 與 cooldown regression：`11 passed`。
- public tool catalog、MCP schema、v4 contract：`5 passed, 2 subtests passed`。
- full safe validation：
  - backend compileall：passed。
  - backend pytest：`1040 passed`。
  - frontend lint：passed。
  - frontend TypeScript：passed。
  - frontend production build：passed。
  - `git diff --check`：passed。

## 剩餘邊界

- E2E 未執行；本輪沒有修改 frontend 互動或版面。
- 正式 8400/3000 launcher runtime 未重啟，因此本輪證據是 source/test/build readiness，不是已部署 runtime 證明。
- repo 原本已有大量未提交 v4 批次變更；本輪未 stage、commit 或 push。
