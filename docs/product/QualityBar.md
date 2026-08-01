# Quality Bar

本文件定義 OMI 被視為「可長期使用」前必須維持的品質標準。

## 產品品質

OMI 必須讓使用者清楚知道自己看到的是什麼資料、資料到哪一天、是否 stale、是否 partial、缺了哪些來源，以及哪些判斷只是 best-effort。

AI 回答要能被檢查與反駁。結論必須連到 evidence、技術位階、條件與風險，不應只有方向性口號。

任何看起來像交易建議的內容，都必須包含失效條件、風險處理與資料限制。

## UX / UI 品質

前端是研究工作台。它要優先支援資訊掃描、比較、反覆操作與穩定版面。

必須避免：

- 文字溢出、卡片互相遮擋、圖表被控制列蓋住。
- 同一個 selection/action 控制重複出現在多個位置。
- 為了展示感降低資料密度或隱藏警告。
- 讓前端自行推論市場 freshness 或補資料。

新增市場或 detail panel 時，先對齊台股既有 UI pattern，再加入市場特有差異。

## 資料品質

資料管線要處理空輸入、缺欄、malformed data、timezone、交易日、休市、日界線、partial failure、cache stale 與 provider failure。

任何 drop、filter、merge mismatch、fallback 或 skipped data 都應能被記錄或回報。不得 silent data loss。

資料刷新必須 bounded：有明確 target、range、timeout、來源、結果摘要與錯誤狀態。

正式發行包不得包含開發者的本機 SQLite、私人 watchlist、secret、log 或市場資料 cache。首次安裝所需的股票代號必須由 backend 從公開記錄的官方來源有界取得，且 provider failure 不得阻塞應用啟動或被隱藏。

## 架構品質

市場邏輯留在 backend。Frontend、MCP、Kuro 與其他 consumer 不應重做 backend 的資料整併、freshness 或 AI reasoning。

大型元件可以逐步拆分，但拆分目標是降低責任耦合與 contract 模糊，不是為了追求行數數字。優先抽離純資料轉換、URL/state helpers、shared type、slot rendering 與 API contract。

新增抽象必須服務於真實重複、邊界隔離或既有 pattern；不要為單一用途引入新框架或大規模 rewrite。

## 驗證品質

驗證要和風險成比例：

- docs/prompt/template：UTF-8 讀回與 `git diff --check`。
- 局部 backend logic：compile/syntax 與最接近 targeted tests。
- contract/freshness/DB/API/cross-market：相關 regression、API/data smoke 與安全驗證 profile。
- frontend interaction/layout：lint/typecheck/build；需要真實 UI 風險時再加 browser/screenshot/e2e。

預設使用 repo wrapper：

```powershell
.\scripts\run-safe-validation.ps1 -Profile quick
```

不要把 e2e、build、長駐 runtime、外部大量 refresh 或清 port owner 當成預設檢查。

## 不可接受的捷徑

- 把 stale 或 missing 包成正常資料。
- 用前端 hardcode 修正 backend contract 缺口。
- 在 adapter 直接讀寫 DB 或複製 backend 市場邏輯。
- 無政策地消耗大量外部 quota。
- 未確認就刪除、重建或覆蓋本機 SQLite。
- 為了 demo 效果隱藏資料限制或風險條件。
