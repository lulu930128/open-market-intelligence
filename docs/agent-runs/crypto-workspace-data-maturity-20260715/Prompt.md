# Crypto 工作區資料成熟度

## 背景

Crypto 側欄目前只呈現自選清單與群組筆數，使用者無法從畫面判斷後端實際支援的資產、provider、資料資源與本機 coverage。現有後端已具備 provider contract、source health、行情、深度、OHLCV、衍生品、市值、價差、清算、多空比等能力，但缺少可供側欄直接使用的資產層級成熟度摘要。

## 目標

- 建立 read-only 的 Crypto 工作區摘要 contract，以 backend registry 為資產 universe 真相來源。
- 將各資產核心資料與進階資料的本機 coverage、freshness、applicability 聚合成穩定狀態。
- 讓側欄保留既有密度與架構，同時顯示 registry 數量及 ready / partial / missing 狀態。
- 修正既有 source-health 對 CoinGecko symbol 與非適用資源的判斷落差。
- 對齊台股的自動資料體驗：主畫面不要求使用者操作 Reload／更新報價，選取、過期與背景 polling 依 backend subscription policy 自動執行。

## 非目標

- 不新增自動下單或任何 execution 能力。
- 不做大量外部 API refresh、全市場回補或付費 provider 啟用。
- 不重建、清除或 migration 現有 SQLite。
- 不大幅改版 Crypto 主面板或重寫 watchlist。
- 不把 freshness 或成熟度判斷複製到 frontend。
- 不把所有 Crypto、商品與貨幣改成無邊界 always-on；維持 selected / background cadence 與 provider timeout 邊界。

## 硬性限制

- GET 路徑只讀本機資料，不產生 refresh side effect。
- stale、partial、missing、provider pending 與 event-driven quiet 必須可區分。
- 非適用資源不得被計為 missing。
- 保留既有 API route 與 response shape；新增 contract 採 additive change。
- 與目前 dirty worktree 共存，不覆寫使用者的商品、貨幣、韓股與其他既有修改。
- 商品與貨幣主畫面不得依賴手動 refresh 才能取得正常資料；舊的 resource `manual` 設定要能安全升級為 `on_select`。

## 交付物

- Backend workspace summary service、schema 與 API endpoint。
- Source-health applicability / CoinGecko identity 修正。
- Backend regression tests。
- Frontend type、側欄摘要呈現與三語文案。
- 必要的 smoke fixture / assertion。
- Crypto／商品／貨幣主畫面移除 Reload／更新報價控制，並保留自動 refresh 與 freshness / failure 可見性。

## 完成標準

- Backend registry 的 9 個資產都出現在摘要中，自選清單 8 個與 registry 9 個不再混淆。
- 每個資產都有 core / advanced slot 狀態及整體 maturity。
- BTC 等資產的 stale/ready 狀態由後端 timestamps 決定。
- TON 市值可依 CoinGecko coin_id 正確識別，不依賴 provider 回傳 symbol。
- SOL 等不支援台灣價差的資產不會因 spread 空資料被誤判 missing。
- 相關 backend tests、frontend lint/typecheck 與必要 build / browser smoke 通過。
- 貨幣預設及既有 manual resource policy 解析為 `on_select`；選取貨幣會自動觸發 bounded snapshot refresh。
