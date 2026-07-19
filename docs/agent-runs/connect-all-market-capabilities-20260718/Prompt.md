# OMI 全面市場能力對外整合

## 目標

- 將 OMI 後端已具備、但尚未由 public `omi.ask` 穩定投影的市場資料能力接入統一對外契約。
- 補齊台股跨市場 context、整體市場籌碼、TXF 多日法人與 Put/Call Ratio 趨勢、統一 freshness/source-health、跨市場 watchlist、portfolio、resource、macro 與 KR intraday。
- 對尚需新 provider、憑證或授權政策的能力建立可驗證的 provider contract、AI slot 與明確 `blocked`／`provider_not_connected` 狀態。

## 非目標

- 不自動下單，不把商品、外匯、港股或其他 context market 提升為與台股同等的核心市場。
- 不硬編碼 API key、token、付費 endpoint 或私人帳號設定。
- 不以 placeholder、零值或舊 cache 冒充已接通、即時或完整資料。
- 不在 frontend、MCP 或 Kuro 重做 backend 的市場邏輯。
- 不在未選定來源、授權與 quota 政策前大量回補新聞、選擇權或海外市場資料。

## 硬性限制

- 台股仍是核心市場；US、JP、KR、Crypto、Resource、Macro 與未來 HK 只作輔助 context。
- public contract 必須 additive、bounded、consumer-safe，並維持既有 `omi.ai.ask.v2` 呼叫相容性。
- 所有新增資料需顯示 provider、as-of、freshness、coverage、warnings、missing 與 source refs。
- GET/read path 只讀 cache；外部 refresh 必須由明確 POST、tool policy 或 scheduler 擁有，並有 timeout、request count 與 fallback 邊界。
- DB schema 若需變更必須走 Alembic migration；不得刪除或重建 `data/open_market_intelligence.db`。
- 保留目前 dirty worktree 的既有變更，不 revert、不做無關 cleanup。
- TAIFEX 法人未平倉與 Put/Call Ratio 是官方盤後資料，不得標成夜盤即時籌碼。

## 背景

- Repo：`C:\project\Open Market Intelligence`
- Public AI entrypoint：`POST /api/ai/ask` 與 MCP `omi.ask`
- 目前 public target：`auto`、`market`、`data_freshness`、`tw_stock`、`tw_watchlist`、`tw_index`、`tw_futures`、`us_stock`、`jp_stock`、`jp_index`、`kr_stock`、`kr_index`、`crypto_market`、`crypto_asset`
- 已確認後端另有 resource market、portfolio、FRED macro、US/JP/KR watchlist、KR stock/index intraday、market chip history 與各市場 source-health 能力。
- 目前 TW `cross_market`／`news_events` slot 仍有 planned 狀態；JP/KR/Crypto 的 analysis/report 也尚未達到 TW/US parity。

## 交付項目

- 新增與同步 public target、scope resolution、ask execution、tool catalog、MCP schema 與 consumer-safe response。
- Resource asset context：商品與外匯 quote/OHLCV、watch-only、best-effort、stale 可見。
- Portfolio context：跨市場持倉、成本、報價覆蓋、集中度、幣別與缺口；空投資組合為有效空狀態。
- Macro context：FRED cache、bounded series selection、credential-required 與 release-frequency 說明。
- US/JP/KR watchlist context：沿用各市場既有 ranking/radar 與 freshness，不複製前端邏輯。
- KR stock/index intraday 接入 AI context，支援 bounded payload 與 session/freshness。
- TW cross-market pack：US overnight、JP/KR index、Crypto、FX、commodity 的可用摘要與 freshness。
- Unified source-health context：TW、US、JP、KR、Crypto、Resource 的統一 projection。
- TW market-wide chips/coverage 與 TXF market-chip 歷史趨勢。
- 新 provider 能力契約：news/events、TW options chain/IV/skew/Greeks、TAIFEX large traders/basis/term structure、TDnet、OpenDART、US options/flows/earnings、HK market。
- Targeted backend tests、MCP contract tests、必要 frontend lint/typecheck 與 bounded API smoke。

## 完成條件

- 後端已有資料的能力可透過 public `omi.ask` 或穩定的既有 target context 取得，不依賴使用者先在 frontend 選取個股。
- 新 target 在 backend schema、routing、MCP、tests 與 consumer fallback 一致。
- 所有 evidence slot 都能區分 `ready`、`partial`、`missing`、`stale`、`planned`、`blocked`、`not_requested`、`not_applicable`。
- 新 provider 未設定時回傳可理解的 capability/blocked contract，不回傳假資料，也不在預設 UI 顯示為可用訊號。
- 相關 targeted tests、contract inventory 與安全 API smoke 通過；若既有 dirty worktree 有無關失敗，必須清楚隔離並記錄。

## 假設與待確認事項

- 未指定付費資料商時，優先採官方/public/free 來源；需要帳號或 API key 的 provider 以可設定 adapter 與 blocked contract 交付。
- 新聞、完整選擇權鏈、海外機構流與港股 provider 可能無法在同一里程碑達到 live-ready，需以來源授權與實際可用性決定最終狀態。
- 本任務不自動 commit 或 push。

## 第二階段：TAIFEX 衍生品對外契約

### 目標

- 將 `tw_options_chain_iv_greeks`、`tw_large_trader_positions`、`tw_futures_basis_term_structure` 從 blocked capability 升級為可查詢、可刷新、可由 `tw_futures` AI context 消費的正式能力。
- 使用 TAIFEX 免 key OpenAPI 的當日官方資料，不依賴 frontend 當前選取狀態。

### 資料邊界

- Universe 僅限台股核心商品：臺指期貨 `TX`／外部 symbol `TXF` 與臺指選擇權 `TXO`。
- 官方來源：`DailyMarketReportFut`、`DailyMarketReportOpt`、`DailyOptionsDelta`、`OpenInterestOfLargeTradersFutures`、`OpenInterestOfLargeTradersOptions`。
- 每次 refresh 最多各呼叫一次上述五個 endpoint；只保存當次官方交易日的 TX/TXO 列，不做隱性歷史回補。
- GET/read path 只讀本機 cache；外部更新由明示 POST 擁有 transaction。
- Delta 優先使用 TAIFEX 官方值。IV、Gamma、Vega、Theta 為 OMI 衍生值，使用明確標示的 pricing model、標的價格與零利率／零股息假設；缺少可靠輸入時保留 `null` 與 calculation status。
- 大額交易人的 `TypeOfTraders=0` 對應所有交易人前五／前十大合計，`1` 對應其中的特定法人合計；不得解讀為外資排行或單一交易人策略。
- 基差以同交易日 TAIEX close 與 TX 正規盤月契約結算價計算；缺 spot close 時保存 curve 價格但 basis 保留 `null`。

### 第二階段完成條件

- Alembic/model contract 可保存完整 TXO chain、官方 Delta、衍生 Greeks、TX/TXO 大額交易人與 TX curve。
- 對外提供 bounded read routes 與一個明示 refresh route，OpenAPI inventory 可測。
- `tw_futures` context 新增 options chain summary/skew、large-trader concentration 與 term structure slots，舊欄位保持相容。
- Capability status 不再把三項能力列為 `provider_not_connected`，並清楚標示盤後、derived 與假設。
- Provider/parser/service/migration/API/AI tests 及一次有界 TAIFEX smoke 通過。

## 第三階段：對外契約完整化與可信失敗語意

### 目標

- 將 backend HTTP、repo MCP、獨立 `OMI_search` adapter 與 frontend 對齊同一份 `omi.ai.ask.v2` consumer contract。
- 修正 freshness、slot readiness、payload projection 與人類可讀摘要中「資料存在就當成可用」的錯誤假設。
- 對尚未穩定、尚未連線、過期、空資料或 provider 失敗的能力保留穩定欄位，並明確回傳 `stale`、`missing`、`partial`、`blocked` 或 `failed`，不得以 `0`、空陣列或 `ready=true` 冒充成功。
- 讓 TXF 的夜盤最新成交、日 K 收盤、法人未平倉與 Put/Call Ratio 各自保有正確時間軸與發布語意。
- 讓所有 public target 在 `brief`／`data_only`／`compact` 模式下都能得到有界、可判讀、可向後相容的結果。

### 交付項目

- 統一 freshness severity、slot vocabulary、missing/failed details 與 compact projection。
- `tw_futures`、`tw_watchlist`、freshness 與其他 legacy context 補齊 slots/compact；未提供的結算價、未平倉或 provider 欄位使用 `null` 加 status。
- TXF 摘要明確區分「夜盤最後成交」與「日 K 最新收盤」，並在可用時投影外資 OI、OI 日變化、Put/Call Ratio 與其盤後時點。
- SOX/SPX/DJI 等既有指數 alias 由 backend resolver 正規化；明確 id 優先於問題文字中的 freshness intent。
- `contract_version` 僅接受明確支援版本；未知版本回 predictable validation error。
- 市場廣度區分上市全市場、上櫃全市場、上市註冊範圍與 OMI 樣本；排行與產業標籤不得把負值稱為上漲或強勢。
- MCP `include_raw=false` 仍保留穩定 `result`；`include_raw` 只控制附加原始封包；MCP 同時提供 text content 與 structured content。
- 消除 adapter 端重做 live-intent、target、freshness 或 refresh policy 的邏輯；adapter 只傳遞 caller 明示參數。
- 將 GET/read path 的外部抓取與寫入逐步移至明確 refresh owner，保留相容 read contract 與可見 freshness。

### 第三階段完成條件

- 21 個 concrete public targets 的 backend schema、routing、projection、repo MCP 與獨立 adapter enum 一致，並有 parity test。
- `include_raw=false` 的 MCP 回應仍含可直接消費的 `result`、`human_answer`（若該 target 支援）與 bounded `data`；`include_raw=true` 僅額外加入 `raw_response`。
- stale、empty、provider error、blocked 與 missing 不得產生 `ready` slot；錯誤來源、as-of、freshness 與警告可由 consumer 取得。
- compact/data-only response 不包含重複的大型 analysis/full context，並有 payload-size 或 heavy-key regression test。
- TXF runtime smoke 同時驗證夜盤成交、日 K 收盤、法人 OI、PCR 與盤後限制文字。
- 市場廣度與排行的 backend label、frontend label、OMI 回答一致，不依賴使用者先選取其他自選股。
- 所有無法在本階段穩定接通的 provider 都有固定 slot、明確 failure contract 與下一步依賴，不留下假資料。
