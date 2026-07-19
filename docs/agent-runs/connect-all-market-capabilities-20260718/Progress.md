# 進度

## 狀態

- 目前階段：第四階段「session／question-required evidence／反問壓測」已完成；未接 provider 依 blocked contract 留待來源／授權決策
- 最後更新：2026-07-19 Asia/Taipei

## 已完成

- 讀取 repo-level 與 frontend `AGENTS.md`、產品方向與 backend architecture。
- 讀取 `productized-project-workflow`、`omi-add-market-capability`、`omi-evolve-ai-decision-contract` 及必要 references。
- 確認 live public tool surface 目前只暴露 `omi.ask`。
- 初步盤點 Resource、Portfolio、Macro、US/JP/KR watchlist、KR intraday、TW market chip 與各市場 source-health。
- 確認 worktree 已有大量未提交變更，後續將採 additive 修改並保留既有內容。
- 新增 public targets：`resource_asset`、`portfolio`、`us_macro`、`us_watchlist`、`jp_watchlist`、`kr_watchlist`、`source_health`、`capability_status`。
- 新增 clear-question auto routing；不必先在 frontend 選取個股或市場頁。
- Resource、Macro、Portfolio、regional watchlist、unified source health contexts 已接入 `omi.ask`。
- KR stock/index 已接 bounded intraday，並沿用 server-side external-fetch trust gate。
- 台股 market context 已接 bounded US/JP/KR/Resource/Crypto local-cache pack；台股個股 cross-market slot 已接 US overnight impact。
- 台股 market chips 已分離官方 aggregate 與 per-stock DB coverage；排行不再冒充全市場。
- TXF 已接 3/5/20 日外資 OI、PCR 趨勢與價格背離，保留官方盤後 release semantics。
- News、Options、TAIFEX large traders/term structure、TDnet、OpenDART、US options/earnings、HK 已建立可查詢 blocked provider contracts。
- MCP target/schema 與 frontend target type 已同步。
- 已確認 TAIFEX 官方 OpenAPI 免 key 提供 `DailyMarketReportFut`、`DailyMarketReportOpt`、`DailyOptionsDelta`、`OpenInterestOfLargeTradersFutures`、`OpenInterestOfLargeTradersOptions`。
- 已以五次有界官方 probe 驗證 2026-07-17 payload：期貨 2,093 列、選擇權 11,396 列、Delta 7,860 列、期貨大額交易人 1,366 列、選擇權大額交易人 328 列；後續只保存 TX/TXO subset。
- 已確認 TX curve 同時含正規盤、盤後與 spread rows；期限結構只採正規盤、純 `YYYYMM` 月契約。
- 已確認大額交易人特殊月份代碼：`666666` 為週契約彙總、`999912` 為所有契約彙總；`TypeOfTraders=0` 是所有交易人排名合計、`1` 是其中的特定法人合計。
- 新增 `20260718_0036` migration 與三張 cache table：`taiwan_option_chain_daily`、`taiwan_derivatives_large_trader_daily`、`taiwan_futures_term_structure_daily`。
- 新增 TAIFEX OpenAPI provider contract 與 `tw_derivatives` service；每次 refresh 固定最多五個 request，partial failure 可保存成功 resource，transaction failure rollback。
- 新增四條 public routes：一個 derivatives refresh POST，以及 options-chain、large-traders、term-structure 三個 bounded GET。
- `tw_futures` AI context 已新增 `data.derivatives`，包含 nearest live expiry chain slice、官方 Delta、derived IV/Greeks/skew、大額交易人集中度與 basis/curve；MXF/TMF 明確回 `not_applicable`。
- Capability status 已把三項台股衍生品能力從 `provider_not_connected` 升為 `connected`／`connected_derived`；blocked capability 現為 News、US options/earnings、TDnet、OpenDART、HK 五項。
- MCP schema 已加入 `option_contract_month` 與 bounded `option_strike_limit`，仍由 backend 決定計算與 freshness。
- 已重啟並確認目前 `127.0.0.1:8400` runtime 載入現有 worktree，可用於第三階段基線 smoke。
- 已完成 HTTP、repo MCP、獨立 `C:\GPT_MCPtool\OMI_search` adapter、frontend 與 21 個 concrete target 的契約盤點。
- 已確認 TXF 夜盤 quote、日 K、外資 OI 與 Put/Call Ratio 資料實際存在，但目前摘要混用時間軸且未完整投影籌碼。
- 已確認 TWSE 官方廣度不依賴自選清單；live summary 約 5–10 秒更新，但 scope label 仍把上市範圍與 OMI 樣本混稱。
- 已確認 freshness 判斷只把 literal `missing` 視為問題，會讓 stale/empty/provider error 資料錯誤產生 ready slot。
- 已確認部分 target 缺 slots/compact、部分 `brief` 宣告可回答卻無 `human_answer`，且 compact fallback 可能回傳整包大型 context。
- 已確認獨立 MCP adapter 缺 8 個 backend target、`include_raw=false` 會裁掉主要 result，且未輸出 structured content。
- 已確認 `SOX` 未自動 canonicalize、auto resolver 會讓 freshness 字樣蓋過明確 symbol、未知 contract version 未被拒絕。

## 驗證證據

- `git status --short`：確認目前 dirty worktree 範圍。
- `GET http://127.0.0.1:8400/api/ai/tools`：目前 public tool list 僅有 `omi.ask`。
- `GET /api/resource-market/instruments`：確認 6 種商品與 9 組匯率 instrument contract。
- `GET /api/resource-market/quotes/latest`：確認本機 cache 存在，但資料 freshness 必須顯示。
- `pytest tests/test_ai_supplemental_contexts.py tests/test_ai_tool_boundaries.py tests/test_omi_mcp_server.py`：37 passed、13 subtests passed。
- backend 整合 regression（AI freshness、technical、portfolio、KR、market chips、TW futures、market index、API inventory、migrations）：159 passed、17 subtests passed。
- frontend `npm run lint`：通過。
- frontend `npm exec tsc -- --noEmit --incremental false`：通過。
- 臨時 backend `127.0.0.1:18400` HTTP smoke：health、capability status、market、TXF、source health、resource、portfolio 全部可呼叫；smoke 後已關閉。
- 正式 `127.0.0.1:8400` health 正常，但仍是 `reload=False` 舊 process，拒絕新 target；需重啟 OMI 才會載入本次程式。
- 新增衍生品 targeted regression：203 passed、124 subtests passed。
- `scripts/run-safe-validation.ps1 -Profile backend`：compileall、完整 backend pytest、diff check 全部通過；最終 714 passed。
- TAIFEX 實際 service smoke（記憶體 SQLite、每個官方 endpoint 一次）：5/5 request 成功；TXO chain 6,060 列、官方 Delta 5,412 列、derived Greeks 2,816 列、TX/TXO 大額交易人 18 列、TX term structure 6 列。

## 已做決策

- 既有資料先完成 public projection；新 provider 不以 placeholder 冒充完成。
- TAIFEX 法人未平倉與 Put/Call Ratio 保持官方盤後資料語義。
- 跨市場能力只作台股輔助 context。
- `source_health` 與 `capability_status` 分離：前者是 runtime，後者是 implementation/provider readiness。
- Portfolio 對外資料需 server trust；估值維持原幣別，不做未明示 FX 換算。
- 第二階段採三張專用 table，避免把 options chain 或 concentration semantics 塞進既有 futures quote/bar table。
- 每次 derivative refresh 最多五個官方 request，只抓當日快照；歷史累積由每日重跑形成，不做 GET 隱性 backfill。
- 官方 Delta 與 OMI 衍生 Greeks 分欄；計算假設、pricing source 與 failure status 必須對外可見。
- 預設 chain summary 會略過已到期的當日序列，選下一個仍有效到期日；呼叫者仍可用 `option_contract_month` 明確查歷史／特定週別。

## 已知問題 / 風險

- 新聞、完整選擇權鏈、海外機構流與 HK 已有 blocked contract，但 live data 仍需 provider、授權與 quota 決策。
- 既有 dirty worktree 涵蓋 AI、market、frontend 與 launcher，驗證失敗需區分本任務與既有改動。
- TAIFEX OpenAPI 是盤後快照；derivatives refresh 由明示 POST 與交易日 16:20 scheduler 擁有，兩者都維持固定五次 request 上限。
- IV/Greeks 只在有效 option price、未到期序列與同日 TAIEX close 齊全時產生；實際 smoke 的其餘列保留 `missing_option_price`、`expiry_reached` 或 `iv_not_solved`，不補零。
- TW watchlist、US/JP/KR、Crypto、Resource、Macro 仍有真實 stale/missing/provider-not-connected 資料；本階段先保留穩定 slot 並修正失敗語意，不將不可控 provider 冒充已接通。
- TPEX 全市場廣度曾在 runtime smoke 發生 provider 失敗；API/UI 當下正確回傳 `breadth_status=failed`、reason 與 warning，後續 refresh 恢復時則回到 `ready`，不再以 `null` 或 OMI 樣本取代。
- `5s` 指數 scheduler 只在台股交易日 08:55–13:40 執行；盤後與休市日維持最後 shared cache，明示 POST 仍可做 bounded refresh。

## 下一步

- provider 未接能力維持 blocked contract；待使用者選定來源、授權與 quota 後，再依 capability status 的 `next_fill` 逐項接入。

## 2026-07-18 完成快照

- 共用 freshness severity、slots、compact projection 已覆蓋 outward targets；stale、missing、partial、blocked、failed 不再回 `ready` 或假零值。
- TXF 已分離夜盤最新成交、日 K 收盤、盤後法人 OI、Put/Call Ratio 與 derivatives，human answer 明示不同資料時軸。
- `SOX` 等美股指數 alias 已 canonicalize，並相容讀取舊 `SOX` 儲存列；未知 contract version 會 predictable reject。
- 台股廣度 UI/API 已區分上市全市場、上櫃全市場、註冊範圍、OMI 樣本與本機資料集；上漲／下跌排行只收正／負報酬，負報酬領先產業改稱相對抗跌。
- index summary GET 已為純 cache read；明示 POST、refresh job 與交易時段 `5s` scheduler 擁有 bounded refresh。runtime 驗證確認 GET 不改 shared cache、POST 才更新。
- Repo MCP 與外部 `OMI_search` target/schema 已對齊；`include_raw=false` 保留單一 `result.human_answer` 與 `result.data`，用 `*_ref` 取代重複 payload。
- runtime smoke：TWSE breadth `ready`（1,091 檔 full_market）；TPEX 曾回 `failed` 並附 reason/warning，後續 refresh 已恢復 `ready`；capability blocked count 5；TXF institutional/options slots 皆有明確狀態。
- payload smoke：`OMI_search` market 19,472 bytes、TXF 19,199 bytes、capability 10,156 bytes，皆無 `raw_response`。
- 最終 safe validation：backend compileall、完整 pytest、`git diff --check` 全通過；frontend lint 與 TypeScript typecheck 通過；外部 adapter 20 tests 通過。

## 2026-07-19 對外契約強化續作

- TXF 日 K 的 GET route 已改為純讀取；舊 `refresh=true` 參數仍保留相容入口，但會明確回傳 409 並指向 POST refresh。
- 新增 `POST /api/market/tw-futures/{symbol}/daily/refresh`，回傳 requested/effective end date、正式發布日、partial warning 與資料列。
- Service 層加入 14:30 Asia/Taipei 正式發布防線；即使其他 caller 直接呼叫 refresh，也不能在發布前寫入當日 daily bar。
- Frontend futures panel 已改走 POST refresh；未發布當日會顯示資料狀態警告，不會把 provisional bar 當正式日 K。
- 驗證：`38 passed, 44 subtests passed`（Taiwan futures、API inventory、transaction contracts）。
- 下一步：統一 backend live/session/previous-close 與 TXF top-level/compact 投影。

## 2026-07-19 session、evidence 與反問壓測完成快照

- TXF 正式日 K 寫入加上 14:30 Asia/Taipei release window；GET 維持純讀，明示 POST refresh 會回傳 requested/effective date 與未發布日警告。
- `market_live_summary.v1` 已統一 backend／MCP 的 quote、intraday、session 與 live 語意；一分鐘來源不再等於目前仍在交易。
- SOX live smoke：target canonicalize 為 `^SOX`、`instrument_type=index`；2026-07-19 週末回 `is_live=false`、`market_status=closed`、上一交易時段 2026-07-17。
- SOX `previous_close_trade_date` 已由本機 daily row 補齊並投影到 top-level compact quote；live 值為 `2026-07-16`，不再是 `null`。
- SOX 指數問題只要求 question-required 能力；company profile、SEC company facts、corporate actions 與 company short volume 標為 `not_applicable`，不再拖低價格問題的 Evidence Passport。
- Yahoo 指數成交量不再以 `0` 或 ETF proxy 冒充；compact quote 明確回 `volume=null`、`volume_status=provider_unavailable`。
- TXF 盤中 report 加入 0.15% change deadband、0.10% MA deadband、0.30% range-span gate、factor scores、effect size 與 confidence reasons。
- Live TXF 驗證：夜盤最新成交 43,481（2026-07-18 04:59:58）、正式日 K 收盤 42,725（2026-07-17）；5/20 期變動約 -0.03%/-0.11% 時，today score=0、title=盤中震盪、confidence=low。
- 外資期貨淨 OI 與 Put/Call Ratio 已可用：2026-07-17 foreign net OI -86,189、日變動 -1,736；PCR volume 83.63%、PCR OI 92.94%。這些都是官方盤後資料，不代表夜盤即時變化。
- 執行一次明示、5-request bounded TAIFEX derivatives refresh：5/5 成功；option chain 6,060 列、large traders 18 列、term structure 6 列。之後 live `tw_futures` derivatives/missing 均為 ready/empty。
- 外部 `OMI_search` MCP live protocol 確認 `include_raw=false` 仍保留 `result`、`human_answer` 與 compact evidence，且不包含 `raw_response`。
- 反問壓測：24 requests、8 concurrency、4 組誘導問題各 6 次，0 failures；median 783.3 ms、p95 1,404.3 ms、max 1,432.0 ms。驗證 closed 不得改口成 live、index 不得要求公司能力、盤中不得改稱波段、夜盤價格不得推論法人即時方向。

## 2026-07-19 最終驗證

- `scripts/run-safe-validation.ps1 -Profile backend`：compileall、完整 backend pytest、diff check 通過；最終 724 passed。
- `scripts/run-safe-validation.ps1 -Profile frontend`：lint、TypeScript typecheck、diff check 通過。
- repo MCP：18 passed；獨立 `C:\GPT_MCPtool\OMI_search` adapter：17 passed。
- live backend 已由既有 `run-service-logged.ps1` 監管程序重啟，目前 `127.0.0.1:8400/api/system/health` 為 `ok`。

## 2026-07-19 仍不可用或非即時的資料

- `news_events`：provider、授權、歸因、去重與 quota policy 尚未決定，維持 `provider_not_connected`。
- `us_options_flow_earnings`：美股 options flow 與 earnings provider／quota 尚未接，維持 `provider_not_connected`。
- `jp_tdnet_disclosures`：issuer mapping、文件 provenance 與 polling policy 尚未接。
- `kr_opendart_disclosures`：API key、corp-code mapping 與 bounded polling 尚未接。
- `hk_market`：symbol master、calendar、daily/intraday provider 與 freshness contract 尚未建立。
- FRED macro 能讀本機 cache，但外部 refresh 仍需要 key；能力狀態為 `connected_key_required_for_refresh`。
- Yahoo 的 SOX 指數成交量不可用；OMI 明確回傳 provider failure semantics，不以 0 或 ETF proxy 補值。
- TAIFEX MIS 夜盤 quote 的 `settlement_price` 與 quote-level `open_interest` 目前仍為 `null/field_status=missing`；正式結算與法人 OI 走不同的官方盤後資料契約，不能混為同一欄。
- TAIFEX 法人 OI、PCR、option chain、large traders、term structure 均只有官方盤後時點；程式無法用這些資料確認夜盤當下是否進一步加多／加空。

## 2026-07-19 盤後排程與最終自檢

- 新增 `scheduler.taiwan_derivatives_refresh`：台股交易日 16:20 後才可排入，固定 `request_limit=5`，以 expected trade date、active-job dedupe 與 12 小時成功 cooldown 避免重複抓取。
- 排程 job 只在所有必要資料達 expected trade date 且狀態為 `ready` 時成功；partial、stale 或日期不符會以 tracked job error 明確結束，已成功保存的官方 resource 不回滾。
- derivatives refresh 新增 `expected_trade_date`、`dataset_trade_dates`、`stale_datasets`、`unverified_date_datasets` 與 `is_stale`。`DailyOptionsDelta` 官方 latest-only payload 沒有可獨立驗證日期，因此保留資料並明示 date unverified，不假稱已驗證。
- SOX 自然語言 auto resolver 已把已知美股指數 alias 視為高信心 canonical target；`SOX` 無須另帶 explicit id 即解析為 `^SOX`／`instrument_type=index`。
- `夜盤` 納入 intraday horizon hint；live OMI 回 `selected_timeframe=today`、`selected_title=盤中震盪`，不再沿用波段標題。
- 真實 `POST /api/market/tw-futures/derivatives/refresh`：5/5 bounded requests 成功，狀態 `ready`，`as_of=expected_trade_date=2026-07-17`，options chain 6,060 列、large traders 18 列、term structure 6 列。
- 真實 `/api/ai/ask` 反問壓測：32 requests、8 concurrency、market breadth／TXF／data freshness／SOX 各 8 次，32/32 通過；median 875.3 ms、p95 2,039.6 ms、max 2,161.8 ms。
- Repo MCP 18 tests 通過；獨立 `C:\GPT_MCPtool\OMI_search` 21 tests 通過。三組 live MCP call 均在 `include_raw=false` 保留 `result.human_answer`、`result.data` 與 refs，且未回傳 `raw_response`。
- Frontend lint、TypeScript typecheck 與 production build 已通過；Windows sandbox 內 build 曾遇 `spawn EPERM`，改在核准的非 sandbox build 後成功。
