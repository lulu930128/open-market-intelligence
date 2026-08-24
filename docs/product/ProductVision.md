# Product Vision

本文件是 Open Market Intelligence（OMI）的長期產品基線。若和 repo `AGENTS.md` 衝突，以較新的 repo instructions 為準。

## 產品定位

OMI 是本機優先、evidence-first 的市場情報與交易決策研究工作台。

它的核心不是「預測下一根 K 線」，而是讓使用者能在同一個系統中：

- 取得可信且可追溯的市場資料。
- 知道資料是否 live、delayed、stale、partial、missing 或 unavailable。
- 比較不同 provider 與跨市場 evidence，而不必自己理解底層來源差異。
- 使用技術、籌碼、基本面與跨市場脈絡形成可檢查的研究判斷。
- 產出情境、回測區、確認條件、失效條件、風險與反證。
- 將研究結果交給人做最後決策，而不是把 AI 變成自動交易機器。

OMI 的雙核心是：

1. **Market Data Foundation**：Canonical Observation、Resolver、freshness、repair、source health、trading status 與 source lineage。
2. **Research / Decision Core**：技術、籌碼、基本面、跨市場、情境、風險與 AI decision。

## 市場定位

### 台股

台股是 OMI 的 primary / reference market。

這代表：

- 台股優先擁有最完整資料覆蓋與 production validation。
- UI、資料模型與市場語意優先從台股建立 reference implementation。
- 新市場若沒有特殊理由，應優先對齊台股已驗證的共同 contract。

「台股優先」不代表其他市場只能當附屬資訊。

### 美股

美股是 first-class research market。

OMI 應支援美股獨立研究需求，包括：

- regular / premarket / after-hours quote semantics。
- 日線與盤中 OHLCV。
- technical structure。
- fundamentals / SEC / provider-specific limitations。
- ADR / cross-market relation。
- watchlist / portfolio valuation。
- KGI、Yahoo、AlphaVantage 等多來源 evidence。

美股可以服務台股隔夜 context，也可以單獨成為研究標的。

### 其他市場

日股、韓股、Crypto、Resource 與其他市場預設是 secondary / context markets。

它們可以逐步升級，但不應各自建立一套無法和 TW/US 共用的資料 contract。

## 主要使用者與場景

主要使用者是需要在本機做市場研究、看盤、追蹤 watchlist、管理研究上下文、檢查資料品質與形成交易計畫的人。

核心流程：

- 盤前：市場 session、前一交易日、隔夜市場、watchlist、資料健康度。
- 盤中：行情、深度/Level 1、K 線、族群、Radar、technical 與 source health。
- 盤後：official close、籌碼、基本面、資料 repair、隔日觀察條件。
- 跨市場：TW/US/ADR/FX/sector relation。
- 持倉：Position 與 Market Data Resolver 結合後估值；Account 與行情故障彼此隔離。
- 決策：形成 scenario、entry confirmation、invalidation、risk、counter-evidence。

## 核心體驗

第一屏應是可操作的研究工作台，不是 landing page。

使用者打開 OMI 後應能迅速回答：

- 現在是哪個市場 session？
- 我看到的價格是 live 還是 fallback？
- 目前 selected symbol 的資料是否完整？
- 哪些族群/標的值得深入？
- 這筆研究成立的條件與失效點是什麼？
- 哪些資料缺口正在影響判斷？

UI 應保持安靜、高密度、可掃描、可反覆操作。

## 市場資料產品原則

OMI 不把「有一個數字」當作「有可信資料」。

每個重要 outward result 都應盡量保留：

- provider / source。
- event time / received or fetched time。
- market session。
- instrument trading status。
- freshness / delay。
- partial / finalized。
- fallback chain / selection reason。
- warnings / missing / provider failures。

OMI 的資料來源可以增加，但新增 provider 不應增加 consumer 複雜度。

Provider 只提供 Observation；OMI Resolver 決定最後使用哪一筆 evidence。

## AI 與研究

AI 是 Research / Decision Core 的重要組成，但不是市場資料 truth 的 owner。

AI 不應：

- 自己 call provider。
- 自己推斷 freshness。
- 自己把 missing 補成零。
- 自己重新實作 market session / trading status。
- 自己繞過 capability readiness。

AI 應建立在 backend 已解析的 evidence 之上。

## Broker / Account 邊界

Broker Quote、Historical Data、Account/Portfolio 必須是不同 capability。

OMI 可以整合券商作為市場資料來源與私人帳戶來源，但：

- Quote failure 與 Account failure 分開。
- Account 503 不代表市場行情不可用。
- Position / Cost / Cash 是 Account truth。
- Price / FX 是 Market Data truth。
- Portfolio Valuation 是兩者的 join。
- 不做 AI 自主交易。

任何未來下單功能必須是明確使用者操作、獨立 Execution Plane、可追蹤且不可被 research pipeline 自動觸發。

## 非目標

- 自動交易或保證績效。
- 隱藏資料缺口。
- 為 demo 合成假行情。
- 把 frontend / MCP / Kuro 變成第二套市場後端。
- 為每個市場複製一份互不相容的 service architecture。
- 無界全市場 backfill。
- 讓 provider-specific payload 直接變成 OMI canonical truth。
- 為了短期功能速度長期保留 provider masquerading。

## 成功樣貌

OMI 成功時：

- 使用者可在 TW 與 US 進行真正獨立、可驗證的研究。
- 新 provider 可以接入而不改變 consumer contract。
- 資料出問題時能明確知道是 provider、dataset、instrument status 還是 resolver 問題。
- stale 資料有明確 repair owner；不能補的資料會如實顯示。
- AI/MCP/UI 看到同一套 backend-owned market semantics。
- Account 與行情互相隔離，Portfolio valuation 不會因單一 provider failure 污染。
- 產品可在本機長期運行，也能逐步開源、安裝與擴充。
