# Operating Model

本文件定義 OMI 的長期責任邊界與運作模型。它不是單次任務計畫。

## 1. 核心責任分層

OMI backend 是市場資料語意、資料品質、Research/Decision 與 outward contract 的真相來源。

主要平面：

```text
Provider / Integration Plane
        ↓
Canonical Observation Plane
        ↓
Resolution / Control Plane
        ↓
Market / Research Plane
        ↓
AI / API
        ↓
Frontend / MCP / Kuro
```

旁邊獨立：

```text
Broker Account
    ↓
Account / Portfolio Plane
    ↓
Position / Cost / Cash
    ↓
Portfolio Valuation
    ↑
Market Data Resolver
```

## 2. Provider / Integration Plane

負責：

- HTTP / WebSocket / SDK / subprocess。
- provider login / reconnect。
- subscribe / unsubscribe。
- raw payload parsing。
- provider-specific error / entitlement normalization。
- 產生 provider-neutral Canonical Observation。

不得：

- 自行決定跨 provider fallback。
- 自行判斷 AI decision readiness。
- 直接把 provider payload 當 OMI canonical truth。
- 直接寫 Market/AI DB 狀態，除非透過明確 service/transaction owner。
- 偽裝成其他 provider。

KGI、TWSE MIS、Yahoo、AlphaVantage 都遵守同一原則。

## 3. Canonical Observation Plane

Canonical Observation 是不同 provider 之間的共同市場資料語意。

核心類型應包含：

- InstrumentKey
- QuoteObservation
- DepthObservation
- AuctionObservation
- BarObservation
- TradingStatusObservation
- ProviderCapabilityStatus
- SourceLineage

市場特有欄位可以保留為 bounded metadata，但 consumer 不直接依賴 provider raw schema。

## 4. Resolution / Control Plane

這一層是「OMI 目前應相信什麼」的 owner。

負責：

- provider policy。
- candidate selection。
- cross-provider fallback。
- realtime policy。
- viewer / research / collector lease lifecycle。
- cache policy。
- market session。
- instrument trading status resolution。
- freshness。
- dataset health。
- repair planning。
- source health aggregation。
- selected evidence lineage。

Consumer 不得重做這些行為。

## 5. Market / Research Plane

Market-specific service 負責市場差異：

- trading calendar。
- tick / volume semantics。
- session 特性。
- regulation。
- official data release。
- market-specific fundamentals / flow / derivatives。

共用 Research engine 處理可跨市場共用的算法，例如基於 Canonical OHLCV 的：

- MA
- RSI
- MACD
- ATR
- KDJ
- Bollinger
- technical structure

除非市場差異真的改變算法語意，否則不要複製 TW / US 兩套相同 technical engine。

## 6. Frontend

Frontend 是研究工作台呈現與互動層。

它可以擁有：

- layout。
- selection。
- loading UX。
- display density。
- interaction state。
- viewer lease 的「使用者正在觀看」意圖。

它不得擁有：

- provider priority。
- fallback。
- freshness。
- trading status inference。
- repair policy。
- AI decision logic。

Frontend 要求即時資料時，對 backend 表達 `require_live` / viewer intent，不直接指定 KGI。

## 7. MCP / External Adapter

`agents/` 保持 thin。

MCP / external adapter：

- 轉送 public request。
- 保留 schema / transport compatibility。
- 不直接讀 DB。
- 不直接呼叫 provider。
- 不重算 market semantics。
- 不自行擴張 refresh scope。

`omi.decision.v4` 與 backend public tools 是 outward business contract。

## 8. Kuro

Kuro 是 OMI consumer。

Kuro 負責：

- persona。
- TTS。
- reminders。
- UI / desktop interaction。
- workflow composition。

Kuro 不重做市場研究、provider fallback、freshness 或 Portfolio valuation。

## 9. 市場定位

### Taiwan

台股是 primary / reference market，優先 production coverage 與驗證。

### United States

美股是 first-class research market，與台股共用 Market Data Foundation / Research contract，但保留美股 session、provider、Level 1、SEC/IFRS 等差異。

### Secondary Markets

JP / KR / Crypto / Resource 預設為 secondary / context market。新增能力時優先使用共同 canonical/outward contract，不建立平行架構。

## 10. Realtime Policy

Backend public policy：

### cache_only

- 只讀現有 evidence。
- 不啟動 provider fetch / subscription。

### prefer_live

- 優先 live / current。
- 可 fallback 到 completed session / cache。
- 必須標示 fallback 與 freshness semantics。

### require_live

- 可啟動 bounded external acquisition。
- 可建立 ephemeral research lease。
- 無法取得 live 時明確回報 policy unmet。
- 不得把上一交易日資料冒充 live。

### completed_session

- 只需要最近完成 session。
- 不應啟動即時 subscription。

## 11. Lease Model

### Viewer Lease

- 由 UI 使用意圖觸發。
- persistent + heartbeat。
- selected symbol lifecycle。

### Research Lease

- 由 AI/MCP `require_live` 觸發。
- request-scoped。
- bounded symbol count。
- bounded timeout。
- request completion 後 release。

### Collector Lease

- 只給明確 bounded universe。
- 不得演變成無界全市場 KGI subscription。

## 12. Dataset Lifecycle

資料 read 先判斷：

1. dataset 是否應存在。
2. instrument 是否 eligible。
3. current evidence 是否滿足 expected state。
4. 若不滿足，是否有 bounded repair operation。
5. repair 成功後是否滿足 postcondition。

Dataset contract 應集中定義：

- owner。
- frequency。
- expected date。
- trading eligibility。
- refresh operation。
- refresh scope。
- postcondition。
- health rule。
- stale rule。

Freshness 能發現 stale 不代表系統有 repair 能力；兩者必須分開呈現。

## 13. Health Model

### Provider Health

某 provider / capability 本身狀態。

例：

- KGI TW Quote live。
- KGI Account 503。
- Yahoo rate_limited。

### Dataset Health

Canonical dataset 是否達到 OMI 預期。

例：

Yahoo stale 但 AlphaVantage current 時，US daily dataset 仍可 current。

### Resolved Evidence Health

這次 request 最後 selected evidence 是否可用。

不得用 fallback provider 的問題污染 selected evidence 狀態。

## 14. Trading Status

Market Session 與 Instrument Trading Status 分開。

例：

```text
TW Market = REGULAR
2344 = TRADABLE
8105 = STOP_TRADING
```

沒有 quote 時不能自行推論：

- 尚未成交。
- 停牌。
- provider fail。

Trading Status 必須由明確 evidence resolve。

## 15. Account / Portfolio

Account Plane 管理：

- AccountStatus
- PositionObservation
- CostBasisObservation
- CashObservation

Portfolio sync 原則：

- success + complete 才可 destructive replace provider-owned state。
- partial 不 destructive replace。
- provider 503 / unavailable 時保留既有 state。
- confirmed empty 才代表 truly empty。
- unknown cost != zero cost。

Portfolio Valuation：

```text
Position
+ Resolved Market Quote
+ FX
= Valuation
```

## 16. Trust / Side Effects

Read path 預設輕量。

可自動執行的 bounded refresh 必須符合既有 trust/budget/policy。

以下操作仍需明確 policy 或使用者確認：

- 大量外部 quota。
- 報告/記憶寫入。
- 發送/發布。
- 交易。
- destructive DB/data operation。
- secrets / machine-wide settings。

## 17. Consumer Contract

Consumer 應直接讀 backend-owned：

- readiness。
- evidence data。
- capability status。
- freshness。
- provider failures。
- limitations。
- fill/continuation plan。

Consumer 不得從 UI label、空欄位或 provider 名稱自行推導市場狀態。

## 18. 變更流程

非平凡變更先判斷 owner：

- Provider
- Canonical
- Resolver / Control
- Dataset lifecycle
- Market-specific service
- Research / AI
- Account / Portfolio
- Frontend
- MCP
- DB
- Runtime
- Docs

跨 owner 修改要同步更新 contract tests。

歷史 `docs/agent-runs` 不回寫新世界觀；current truth 只放在 repo AGENTS、product docs 與 architecture docs。
