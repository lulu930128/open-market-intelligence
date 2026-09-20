# 台股技術研究與 Price Map

## 責任與參數

技術序列由 TaiwanTechnicalService 計算。設定以 TechnicalAnalysisParameters 的內容雜湊 revision 識別；一次 Price Map 計算把同一參數物件傳給 Report 與 Evidence。Frontend 設定儲存事件只使畫面重新讀取；參數與計算語意仍由 Backend 擁有。舊設定的指標、報告或 Price Map 不會在新設定下繼續顯示。

TW 指標選單取 Backend capability、interval applicability 與實際 renderer mapping 的交集。Template 只控制顯示。VWAP / OBV 使用 Backend 值；缺值保持缺值，VWAP 不適用於日、週、月線，OBV 的負值與零都是有效值。

## Price Map v4

Technical input quality 分開輸出 `decision_window` 與 `history_coverage`。近期所需完成 Bars 由可用指標的最大 warmup 決定；週／月由 Bar owner 附上每期缺少的交易日 component 數，未知 coverage、近期缺口、不合法順序與不足 warmup 都阻擋 decision。更早的缺口及 requested history 未達目標保留 warning，不單獨封鎖已足夠的近期視窗。計算仍保留既有歷史輸入與遞迴指標演算法；不適格歷史輸入仍保守阻擋，不以截斷或補值改寫來源。

尚未完成的週／月不計入 decision warmup、structures、signals 或 completed technical revision；觀測點可另列。Report 對四個 timeframe 提供 backend-owned structured state；Today 只投影 session 觀測，日線背景分開。Frontend 不重新計算狀態、指標或市場完成性。

Report 的未知技術分數在 Price Map 摘要中仍為 null，不投影成中性零分。標準與專業圖表都使用所選週期的 Backend 指標序列；指標成功載入與均線真正畫出是不同的驗收條件。

`tw.stock.price_map.v4` 區分 requested_timeframe、structure_timeframe、完成日線 reference 與 current observation。日、週、月結構沿用 Canonical Bar / Technical；Today 採完成日線結構，另帶目前成交觀察。週/月完成性使用最後一個日線 component 的日期與交易日曆判定，不能由聚合 Bar 的 start_at 或 component finalization 單獨推定。

週/月目前提供完成期的 Donchian、Bollinger 與 Support / Resistance 結構。Volume Profile 與 Anchored VWAP 保留 daily OHLCV 方法，週/月回傳明確 method_applicability，不把日線估計改名為週/月方法。Warmup、缺交易日與 Corporate Action coverage 分別保留；長週期歷史不足不補值。

Zone 寬度上限在合併、padding 及 tick rounding 後仍成立；裁切只移除 padding，保留 exact evidence 與 decision threshold。無法形成合法正寬度時 geometry_status 為 unavailable。混有 hypothetical target-close evidence、unknown evidence 或 pivot 的 zone 不可供 Scanner 當成成交觸及區間。研究顯示軸與法定漲跌停不同。

HTTP、Frontend、AI capability 與 MCP snapshot 以 v4 同步切換。v3 前端不接受 v4，v4 前端也不接受 v3；部署必須讓 Backend / Frontend / MCP contract 同批採用，混版時明確停止顯示。正式 runtime 完成同批更新後不保留 v3 private fallback。

## Snapshot 與 Scanner

背景 job 是唯一建置與寫入入口。Migration 20260914_0087 建立每個 symbol/timeframe 的 snapshot header，以及 monotonic technical input generation。DB triggers 在同一 transaction 中追蹤日線、lineage、reconciliation、receipt、source 與 instrument identity 的變更，包括 bulk update / delete。Migration 保留既有行情資料；沒有 migration 時 read 回報 migration_required，不自動建表。

Snapshot header 的 corporate_revision 欄位保存依賴 digest，內容包括 Corporate Action、TW calendar、技術演算法與聚合演算法版本。另比對參數、methodology、輸入 generation 與 completed-session basis date。Successful empty、partial、failed、building 與 not computed 分開。Payload 的 stock、timeframe、參數及方法版本必須符合 claim；reference date 缺少或落後時只發布 partial，未來 reference date 一律拒絕。

Producer 使用 durable header 作 checkpoint：每輪有 symbol/timeframe 數量及時間預算，跳過已發布與未到 retry 時間的工作。Claim、publish、retry 時間一律 UTC。Lease 到期可接手，舊 token 不可覆蓋新 token；發布為單列原子更新，資料在計算中改動即拒絕發布。外部 metadata 與設定在發布前再讀一次，查詢時再比對。

`screening.price_map` 和 `GET /api/market/screening/price-map` 只讀已發布 snapshot 及 backend-resolved current state，不計算指標、不建 snapshot、不排 refresh、不呼叫 provider。完整 requested universe 的 coverage 在 eligibility、排序與分頁前計算。沒有符合項目只有在 coverage complete 時才可稱 valid empty；部分覆蓋不得推成全市場沒有機會。Raw unadjusted 視窗含已知 Corporate Action 時，Scanner 保守排除並保留原因。

## 狀態、事件與盤前

near_zone、touching、above_zone、below_zone 是目前位置關係。zone_side 指完成日線 reference 的 upside/downside 結構側，不會隨即時價格自行翻轉。

Reaction / retest 使用明確帶有 actual price_as_of、received_at 與 lineage 的 canonical sampled trades。輪詢分鐘、重複收取同一筆成交、舊格式 samples 與 session OHLC 不可提供事件順序證明。僅使用 snapshot 發布後的同日樣本；樣本須嚴格依序、間隔不超過 90 秒，觸及後離開同側需至少 60 秒確認，touch 必須在最近 5 分鐘內。這是 sampled-trade research evidence，不能保證每筆中間成交路徑。

盤前使用獨立 indicative lane，明確非 actual trade，decision_usable 為 false，不能確認 reaction / retest。Actual lane 另外檢查真實成交時間與 receipt freshness，不以新收到的舊成交當成即時成交。

## 採用與驗收

單獨選取 `technical.price_map` 時，AI technical reader 直接委派既有 Price Map owner，沿用其 Bars、Technical 與 Corporate Action 依賴；不額外計算未要求的全週期報告、advanced evidence 或產業比較。混合能力請求維持完整 reader 與各自 projection。

一次同步 Bar／Technical 計算以同一份交易日曆 snapshot 完成查詢，避免每個交易日重複檔案 I/O。範圍結束立即釋放，下一次計算重新檢查日曆更新；不加入跨請求 TTL，也不更動休市日、臨時停市與 fallback 規則。

週／月 component continuity 只使用已知年度日曆。若某年既無 verified cache 也無內建年度表，component missing count 保留 null；近期視窗以 coverage unknown 阻擋，不把平日 fallback 當成已確認的歷史交易日缺口。

2025/1/23–1/24 依 [TWSE 春節公告](https://eshop.twse.com.tw/zh/news/detail/8a82e9e69471d3e8019495d573f70017) 屬只交割、不交易日，已列入內建日曆。Snapshot 依賴 digest 同時納入內建年度日曆、臨時休市與 verified cache，避免日曆修正後沿用舊品質判定。

`ENABLE_TAIWAN_PRICE_MAP_SNAPSHOT_SCHEDULER` 預設 false。正式採用順序為備份與 migration、同批更新 Backend / Frontend / MCP、啟用 bounded producer，再驗收實際 coverage 與延遲。每輪成功不等於全市場完成；吞吐、盤前及盤中行為必須在正式資料與交易時段確認。切換前可保留原本日線 read path，但不宣稱 Scanner 已有正式 snapshot。

Source / fixture tests、Runtime adoption、Live/provider 與 Product acceptance 是分開的 gate。當次證據與尚未通過項目記錄於 active exec plan，不由本文件宣告正式市場可用。
