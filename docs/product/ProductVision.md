# Product Vision

本文件是 Open Market Intelligence（OMI）的長期產品基線。內容整理自 repo `README.md`、repo-level `AGENTS.md` 與既有 agent-run 文件；若和更上層 agent instructions 衝突，以 `AGENTS.md` 為準。

## 產品定位

OMI 是本機優先的市場情報與交易決策研究工作台。它的核心不是「預測漲跌」，而是把市場資料、技術位階、資料新鮮度、風險條件與反證整理成可檢查的決策輔助。

台股是核心市場。美股、日股、韓股、加密貨幣與商品資料是台股研究的 context layer；除非使用者明確改變策略，其他市場不應取代台股成為產品主線。

OMI 不是自動交易系統，不做自動下單、不代替使用者執行交易，也不把研究建議包裝成保證結果。

## 主要使用者與場景

主要使用者是需要在本機環境中做市場研究、看盤、追蹤 watchlist、整理技術決策稿與檢查資料品質的投資研究者。

核心日常流程：

- 盤前：確認市場日曆、資料來源健康度、關注清單與前一交易日狀態。
- 盤中：查看台股 watchlist、K 線、雷達、籌碼與 source health，必要時用 OMI dock 提問。
- 盤後：整理市場概況、個股技術位階、資料缺口與隔日觀察條件。
- 決策：產出情境、回測區、進場條件、失效條件、停損/停利、續抱/減碼與反證。
- 驗證：讓 stale、partial、missing、best-effort 與 provider failure 都可見。

## 核心體驗

第一屏應該是可操作的研究工作台，而不是 landing page。使用者打開 OMI 後應能立刻看到：

- 目前選定市場與 watchlist。
- 台股優先的 detail panel、K 線/技術資料與 radar。
- OMI dock 可針對目前 context 產出結構化決策輔助。
- 資料新鮮度、來源狀態、缺口與警告。

UI 要支援高頻掃描、比較與反覆操作；設計語氣應是安靜、密集、穩定的研究工具，而不是行銷展示。

## 方向保護

以下方向需要被主動反駁或改成更安全版本：

- 把 OMI 做成單句買賣建議或猜漲跌工具。
- 隱藏 stale、partial、missing、provider failure 或 best-effort。
- 讓 frontend、MCP adapter、Kuro 或其他外部工具重做 backend 的市場邏輯。
- 讓 GET/read path 隱性觸發昂貴 refresh、大量 quota、報告寫入或 AI memory 寫入。
- 把其他市場提升成和台股平等的核心市場，除非使用者明確重新定義產品策略。
- 將展示層需求凌駕於資料可信度、架構邊界與可驗證性之上。

## 非目標

- 不做自動交易、下單機器人或保證績效的投資建議。
- 不追求一次塞滿所有市場資料；先完成 bounded、可驗證、可解釋的資料 contract。
- 不把外部 API refresh 變成無限制全市場抓取。
- 不為 demo 視覺效果犧牲資料缺口可見性。

## 成功樣貌

OMI 的成功標準是：使用者能在同一個本機工作台中看到可信資料、知道資料缺口、追蹤市場 context，並用 AI decision core 產出可回測、可反駁、可執行風險管理的研究結論。
