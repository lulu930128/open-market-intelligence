# 美股公司事件行事曆 MVP

## 背景

OMI 目前在「設定 → 行事曆」提供台股個股事件，並在台股個股詳情中顯示未來 7 天提醒。本任務在不新增頁面或第二個對話框的前提下，讓同一個行事曆可切換台股與美股，並為日股、韓股保留後續可接的市場入口。

## 目標

- 在既有 `MarketCalendarDialog` 上方加入市場切換：台股、美股、日股、韓股。
- 台股保留既有行為。
- 美股顯示已快取的 earnings、dividend、split 公司事件。
- 美股個股詳情在未來 7 天內有事件時，顯示與台股一致節奏的提醒標籤。
- 日股、韓股入口顯示「規劃中」，不可發出 API 請求，也不可用空陣列假裝資料已接通。
- 所有 freshness、missing、stale、provider failure 與 coverage 限制由 backend contract 提供，frontend 僅呈現。

## 非目標

- 本次不串接日股、韓股公司事件 provider。
- 本次不新增獨立頁面、獨立 modal 或事件管理後台。
- 本次不實作 SEC、公司 IR、FMP、Alpaca、Benzinga、多來源衝突解決、版本回復或人工覆寫。
- 本次不擴充 AI decision contract、MCP 或 Kuro。
- 本次不把 GET read path 變成外部 API refresh。

## 硬性限制

- 台股仍是核心市場；美股是對齊台股體驗的 context layer。
- 公開 API 採 repo 現有 `/api/us-market/...` 命名，不照草案新增平行 `/api/v1/market/us/...` 路由。
- Alpha Vantage API key 只存在 backend 設定，不得進入 frontend bundle 或 API response。
- 美股事件日期以 `America/New_York` 為市場日期；只有 provider 提供確切時間時才能顯示時間，不得推測盤前或盤後。
- GET 只讀本機 DB；外部更新只允許 bounded POST 與 scheduler。
- Alpha Vantage earnings calendar 每次 refresh 最多一個請求，固定 `3month` horizon。
- 既有 corporate action 是逐檔更新，行事曆必須明示其 coverage 為已快取／觀察清單範圍，不得宣稱全市場完整。
- 日股、韓股按鈕保留可見但 disabled，並提供可讀的「規劃中」說明。
- 保留工作樹既有 Radar 變更，不 revert、不重新格式化其檔案內容。

## 交付物

- 美股事件 ORM model 與 Alembic migration。
- Alpha Vantage earnings calendar adapter、normalize、upsert、list、summary 與 refresh service。
- 美股公司事件 list、7 日 summary、bounded refresh API。
- scheduler 與設定欄位。
- 共用前端事件型別、行事曆市場切換、日韓規劃中狀態、美股個股 7 日提醒。
- backend targeted tests、frontend lint/typecheck/build 與必要的 API/UI smoke 證據。

## 完成條件

- `GET /api/us-market/corporate-events` 不觸發網路，能回傳事件、來源、freshness、coverage 與 warnings。
- `GET /api/us-market/corporate-events/{symbol}/summary` 僅回傳紐約市場日期 0–7 天內事件。
- `POST /api/us-market/corporate-events/refresh` 在有 key 時只執行一個 bounded earnings request；沒有 key 時回傳可預期的未設定錯誤且保留快取。
- 相同 symbol、event type、fiscal period 的 earnings 日期修訂會更新同一 logical event，不產生重複事件。
- 台股與美股可在同一 dialog 切換，切換會取消前一個市場的進行中請求。
- 日股、韓股入口不會呼叫 API，且畫面明示尚未接通。
- 美股個股未來 7 天有事件時顯示標籤；沒有或資料 missing 時不製造事件。
- source status 的 stale、degraded、missing、provider_not_configured、watchlist_only 可見。

## 假設

- MVP 先使用 repo 已有的 `ALPHAVANTAGE_API_KEY`；沒有 key 的安裝仍可讀取既有 DB 快取。
- earnings calendar 是全市場來源；dividend/split 沿用既有 `USCorporateAction` 快取。
- Alpha Vantage earnings calendar 未提供可靠的 event time，因此 MVP 將 earnings 視為 all-day scheduled event。
