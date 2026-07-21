# 執行計畫

## Milestone 1：契約與測試盤點

- 驗證 technical card、signals、ranking、Radar 與 frontend mapping 的實際 call chain。
- 記錄盤中/日線時間點、現有 MA60 缺口與 bounded refresh 約束。
- 找出最接近的 backend/frontend 測試面。

驗收：能指出每一項強化應落在哪一層，以及哪些現有欄位需保持相容。

## Milestone 2：Backend 技術語意

- 新增共用的價格相對均線結構 helper。
- 擴充 daily report 的 MA5/20/60 距離、均線排列、盤中覆蓋與 freshness basis。
- 擴充 signal service 的 MA60 靜態與穿越訊號。

驗收：pure helper 與 technical report targeted tests 覆蓋跌破 MA60、均線落後價格及盤中 provisional 情境。

## Milestone 3：Radar 決策資訊

- 擴充 MA60 signal label、risk/momentum family、權重與 factor scores。
- 改善主訊號優先順序與關鍵價位選擇。
- 先算完整日線 ranking，再在 bounded limit 內選擇最需盤中覆蓋的候選。

驗收：Radar tests 覆蓋 MA60 support break、最近回收壓力與後段高風險股票被納入盤中候選。

## Milestone 4：Frontend 呈現

- 日線技術卡請求盤中覆蓋，保留 backend metadata、warnings 與 basis。
- 增加必要的 technical terms/i18n。
- Radar 細節加入 MA60 關鍵位，不改變摘要優先/折疊結構。

驗收：lint/typecheck 通過，卡片能區分盤中現價與已收盤指標日期。

## Milestone 5：整合驗證

- 執行最小充分 backend targeted tests。
- 執行 frontend lint 與 typecheck；必要時執行 focused browser/e2e。
- 檢查 dirty worktree diff，只保留本任務局部修改。

停止並修正規則：任何 contract regression、freshness 隱藏、無界限 provider I/O 或既有測試失敗，都先修正再進下一步。
