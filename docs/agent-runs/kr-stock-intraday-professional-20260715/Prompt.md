# 韓股個股今日走線與專業圖表補齊

## 目標

- 讓韓股個股具備可見 freshness 與失敗狀態的「今日」即時走線。
- 移除韓股個股畫面不必要的「更新日 K」操作。
- 對齊台股既有圖表能力，補上技術指標選單與放大後的專業模式。

## 非目標

- 不把韓股提升為與台股同等的核心市場。
- 不新增自動下單或漲跌預測能力。
- 不重做既有共用圖表元件或大範圍改版。
- 不隱藏 provider failure、partial、stale 或 missing 狀態。

## 硬性限制

- 韓股個股分時資料由 backend API 統一提供，frontend 不直接呼叫外部 provider。
- 外部 refresh 必須有明確 timeout、cache 與資料範圍。
- 保留既有 route 與 response compatibility。
- 不覆蓋或回退 worktree 中其他任務的既有修改。

## 完成條件

- 韓股個股可選「今日」，並顯示 1 分鐘正常交易時段走線與股數成交量。
- provider 不可用時，UI 能顯示空資料或警告，不偽造走勢。
- 個股畫面不再顯示「更新日 K」。
- 一般圖表可開啟技術指標選單。
- 專業模式支援分時與日／週／月 K、圖表樣式、技術指標與畫線工具。
- Backend targeted tests、frontend typecheck/lint/build 與必要 browser smoke 通過。
