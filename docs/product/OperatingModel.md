# Operating Model

本文件定義 OMI 的長期責任邊界與日常運作模型。它不是單次任務計畫；修改架構、contract、UI 資訊架構或市場資料流程時，應先對齊這裡的邊界。

## 責任分層

Backend 是市場資料、freshness、AI reasoning、tool orchestration 與 answer contract 的真相來源。

Frontend 是研究工作台的呈現與互動層。它可以決定 layout、loading、顯示密度與互動節奏，但不應重做市場判斷、freshness 規則、資料補齊策略或 AI decision logic。

`agents/` 只放外部 adapter，例如 MCP。Adapter 應保持 thin：轉送 request、整理 schema、呼叫 backend API，不直接讀寫 DB，也不複製市場資料邏輯。

Kuro 或其他外部工具負責呈現、語音化、提醒與工作流串接；市場分析與資料 contract 仍由 OMI backend 提供。

## 資料與刷新模型

OMI 採本機優先資料模型，`data/open_market_intelligence.db` 是本機狀態，不得在未確認前刪除、重建或覆蓋。

資料讀取流程應先檢查本機資料與 freshness；若資料不足或過舊，backend 可以執行 bounded refresh。bounded refresh 必須有明確目標、資料範圍、成本/次數/timeout 邊界、來源紀錄與失敗回報。

Read path 預設要輕量。昂貴 refresh、付費或稀缺 quota、報告寫入、AI memory 寫入與發送/發布行為必須有明確 policy 或使用者確認。

## 開源與發行模型

OMI 原始碼以 Apache License 2.0 開源，NOTICE 著作權人為盧星豪。Windows 發行包不得夾帶 build machine 的 SQLite、watchlist、token、log 或股票主檔 seed；空白安裝首次啟動時，由 backend 建立可追蹤、有明確來源與請求次數上限的 TWSE／TPEx 股票代號 bootstrap job。

第三方相依套件保留各自授權。市場與 provider 回傳資料不因 OMI 採 Apache-2.0 而被重新授權；發行與文件必須保留這個邊界。

## 市場模型

台股是主線市場，資料模型、UI pattern、AI decision contract 與驗證標準先以台股為基準。

其他市場是 context layer。新增市場時應優先對齊共同 contract：target、quote、daily chart、intraday、fundamentals、flows/liquidity、derivatives、data_quality 與 slot status，而不是各市場各自長出不相容 payload。

市場差異可以存在，但差異要留在 backend adapter/service 層，並透過 slot status、capability、payload_level 與 warnings 暴露給 consumer。

## AI Decision Contract

OMI AI 的輸出應優先是結構化決策輔助，而不是單句方向。

標準回答應盡量包含：

- 目前狀態與資料日期。
- 看多、觀望、風險與失效情境。
- 回測區、支撐/壓力、均線、VWAP、量價區或前高低。
- 進場確認條件。
- 失效條件與反證。
- 停損、停利、減碼、續抱或等待條件。
- freshness、missing、partial、provider failure 與 best-effort 限制。

如果 evidence 不足，backend 可以先用 tool 補資料；tool 失敗時必須回報缺口，不得編造。

## Consumer Contract

所有 consumer 應使用 backend 回傳的 answer contract：

- ChatGPT/MCP 優先讀 canonical `answer`、`evidence.data` 與
  `evidence.capability_status`；`analysis.human_answer` 只作 legacy
  compatibility fallback。
- Kuro 預設使用 summary/compact payload，語音化核心 slot，不展開大量原始資料。
- Frontend 以 `evidence.capability_status` 作 readiness 唯一權威，決定
  completeness、警告、disabled/loading/expandable state；舊
  `result.data.slots`／`evidence.slots` 只作相容 fallback，不把 readiness
  解讀成市場建議。

需要更多資料時，consumer 應提高 `market_data_params.payload_level` 或調整 bounded params 重新詢問 backend，不應在 adapter 或 UI 自行補資料。

## 變更流程

非平凡變更要先判斷層級：backend AI、market data、frontend UI、MCP adapter、database migration、launcher/runtime config 或 docs。

牽涉 contract、freshness、DB、scheduler、tool policy 或跨市場邊界時，應同步更新相關測試與 agent-run 文件，避免只改單一 call site。

若臨時需求會破壞上述邊界，應先指出衝突與風險，再提供較穩定的替代方案。
