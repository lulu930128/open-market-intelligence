# 台股技術研究與 Price Map

## 責任與參數

技術序列由 TaiwanTechnicalService 計算。設定以 TechnicalAnalysisParameters 的內容雜湊 revision 識別；一次 Price Map 計算把同一參數物件傳給 Report 與 Evidence。Frontend 設定儲存事件只使畫面重新讀取；參數與計算語意仍由 Backend 擁有。舊設定的指標、報告或 Price Map 不會在新設定下繼續顯示。

TW 指標選單取 Backend capability、interval applicability 與實際 renderer mapping 的交集。Template 只控制顯示。VWAP / OBV 使用 Backend 值；缺值保持缺值，VWAP 不適用於日、週、月線，OBV 的負值與零都是有效值。

## Price Map v4

Daily continuity 使用 `market.tw_daily_day_state` 的 instrument × trade_date canonical
day-state 與 expected sessions。Calendar、historical instrument status、official daily
price、trade activity、corporate-action price basis 分別輸入純 resolver；缺失或未知
不能推成停牌或無成交。七種 day-state 與 blocker 由 executable contract 擁有。

Historical suspension/resume/capital-reduction/price-basis-changing evidence 由
`tw_corporate_events` 既有 official acquisition → normalized event → atomic cache → revision
lifecycle 擁有，透過 `TradingStatusObservation` 提供 historical eligibility。沒有獨立
historical JSON truth 或人工日期／price-basis import。官方公告 parser 只接受明示有效區間；
列表只提供 positive evidence，不能作為完整 negative coverage。來源不可達或回應未涵蓋目標
時 refresh 保留精確 blocker。Price basis resolver 回傳 unchanged/changed/unknown 與 coverage；
所有 price-changing event families 的 coverage 完整才可推導 unchanged。

`TaiwanOfficialDailyBarRepository.complete_no_trade_bars` 在 canonical resolution 後
消費 day-state，只對 verified no-trade 產生 read-only derived bar。必須是明確零量、零金額、
零筆數、連續的 prior resolved raw close，以及完整官方 event coverage 的 unchanged
price-basis；企業行動不明、
不安全、來源不可信、非零金額／筆數或缺 prior close 都保留缺口。衍生 bar 的 authority
為 derived、非官方成交價、不持久化價格，保留 raw/prior/basis lineage 及 limitation。
原始 MarketDailyPrice 不變；缺少 price-basis acquisition 時不製造 safety evidence。

Receipt visibility 與行情截止日分開：`to_date` 限制 market events；`requested_at`
限制可見 receipts。派報 `current_cache_bounded_report_date` 使用目前可見 cache，
所以今日補入的歷史官方證據可以供 replay 使用；明示歷史 requested_at 則仍排除晚收 evidence。
Bar revision 納入 day-state；Price Map snapshot dependency digest 使用 corporate-event semantic revision，避免沿用舊判定。
Semantic revision 只影響衍生結構的 invalidation：instrument event/window 先沿原 Raw hash、官方網域、
authority、區間與 receipt cutoff 驗證，再投影事件內容、有效 coverage 與資格；無引用的空 receipt、
健康／attempt 更新、同義重複證據不使全市場重算。完整 cache revision、原 receipt/lineage 與 PIT reader
不被改寫；歷史 Corporate Action 既有 current-only coverage gate 的有效狀態變化仍使版本失效。
Calendar dependency 同樣由原 owner 投影 TW verified years、holidays 與來源識別，排除 fetched/attempt/error
metadata；內建假日、臨時休市、方法／算法與 input-quality 版本依賴保持有效。切換 projection 後既有
Snapshot 需由原 bounded Producer 重建一次，後續相同證據刷新不反覆使全市場 stale。

`jobs.tw_technical_input_readiness` 是共用 write-side owner，按 canonical blocker 分派
既有 bounded daily backfill、instrument/corporate-event refresh 或 alternate official price
resolution，最後 canonical/technical reread。尚無 qualified alternate official price acquisition
時保留 unavailable；不能重新抓相同 null row 卻宣稱已解析。Technical 不解析 raw/provider/event
頁面，只消費 canonical bars、bar-state、expected sessions 與 day-state。

原 Price Map Producer 在同一趟 header 走訪與 partial publish commit 後，以每輪最多兩次、
三秒 admission 預算接納單股歷史修補；不另設全市場缺值掃描。Older blocker 日期未出現在
近期 day-state projection 時，共用 readiness 以明確日期範圍向原 Bar owner 重讀 eligibility；
blocker 本身不能證明 market open 或 tradable。歷史 UNKNOWN 先詢問原 instrument-event owner，
再允許真實官方成交資料交由 Canonical 判定，不能以空回應推導無停牌或製造價格。

單股 JobRun 固定缺口身份與 basis，沿原 JobService 每次執行一個單月官方操作（HTTP timeout
八秒），只由下一次原 Producer 走訪續接；完成 callback 不連鎖補月。MA60 最近窗口優先，
同一 Job 可續補至最近九十根所需歷史；已 ready header 只續接既有待辦，不建立新修補。
月份／操作 attempt 在外部 IO 前提交，無資料變化保留 partial，每操作最多三次、失敗冷卻六小時；
Owner PermissionError 停止後續操作。JobRun 只存精簡品質、缺日、revision、官方 receipt ID
與進度，完整 Raw／Canonical 留在原 owner。有效 revision 變動後由原 Snapshot claim/publish
自然重建，同版 ready／empty／partial 不重算；GET／HTTP／MCP 不入列或補資料。

派報 preparation 只固定本次八檔 selection → common readiness → receipt，同時 reread chart coverage 與 technical
`input_quality.decision_usable`。Coverage complete 且 technical partial 仍列 unresolved，
不能替換候選；`--prepare-only` 只執行 preparation、不發送 Discord。

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

Migration 20261101_0097 定點修正來源 UPDATE 的 technical generation trigger：只比較
official daily reader 使用的 source identity、priority、reliability 與 parser 欄位；健康時間／
錯誤訊息更新及相同值 UPDATE 不使全市場結構過期。Daily rows、receipts、lineage 與 reconciliation
的修訂 trigger 仍有效。此 migration 接續 0096；Source fixture 通過不表示正式 DB 已升級。

Migration 20261101_0098 接續修正 daily／lineage／stock-master UPDATE triggers。相同日 K
語意與相同 source/parser、成功且 release-qualified 的 acquired receipt 更替，保留新 Raw、
quality receipt、最新 lineage 與 PIT row，但不增加 technical generation；整份市場 payload
hash 改變也不單獨代表該股 OHLCV 更正。真正行情、authority/finality、品質／release 資格、
來源候選與 materialized lineage 變動仍失效；Raw 原位更新／刪除、其他 insert/delete 與
reconciliation guards 保留。Stock master 的 last_seen/updated/created 時間 metadata 不失效，
身份、market、instrument type、is_active 等實質變更仍失效。PIT reader 優先保留的真實
revision，只有沒有可見保留版本的 legacy row 才能推定相同 receipt 的歷史可見性；不能讓
後收 finality／quality 蓋過舊 cutoff。0098 downgrade 僅恢復原 UPDATE triggers，不刪資料。

Producer 使用 durable header 作 checkpoint：每輪有 symbol/timeframe 數量及時間預算，跳過已發布與未到 retry 時間的工作。Claim、publish、retry 時間一律 UTC。Lease 到期可接手，舊 token 不可覆蓋新 token；發布為單列原子更新，資料在計算中改動即拒絕發布。外部 metadata 與設定在發布前再讀一次，查詢時再比對。

Producer／專用 scheduler 預設只輪轉 daily；週／月仍可明示配置。先批次讀取不含 payload 的
durable headers，跳過有效／lease／retry-not-due 項目後，再對 due 項目執行原子 claim。
每輪 report/log 保留 coverage_before 的 status counts、跳過原因、published 品質與 failed／superseded；
一次 completed_batch 只代表有界批次。已 claim 項目計算失敗沿原 failure/retry owner 保存，不阻斷鄰股。

Due items 依原 durable header 的 claimed_at 由舊到新處理；尚無 header 的項目先前進。
持續 stale 的前段不再每輪占滿預算，舊 due 工作也會依最後 attempt 輪轉；不新增 cursor/store。
原 claim 仍於寫入時重驗版本、retry 與 lease。先完成原 header skip walk 與有界 repair admission，
再使用建置預算，避免前段 stale 也阻斷 current partial 的單股修補續接。

`screening.price_map` 和 `GET /api/market/screening/price-map` 只讀已發布 snapshot 及 backend-resolved current state，不計算指標、不建 snapshot、不排 refresh、不呼叫 provider。完整 requested universe 的 coverage 在 eligibility、排序與分頁前計算。沒有符合項目只有在 coverage complete 時才可稱 valid empty；部分覆蓋不得推成全市場沒有機會。Raw unadjusted 視窗含已知 Corporate Action 時，Scanner 保守排除並保留原因。

## 狀態、事件與盤前

near_zone、touching、above_zone、below_zone 是目前位置關係。zone_side 指完成日線 reference 的 upside/downside 結構側，不會隨即時價格自行翻轉。

Reaction / retest 使用明確帶有 actual price_as_of、received_at 與 lineage 的 canonical sampled trades。輪詢分鐘、重複收取同一筆成交、舊格式 samples 與 session OHLC 不可提供事件順序證明。僅使用 snapshot 發布後的同日樣本；樣本須嚴格依序、間隔不超過 90 秒，觸及後離開同側需至少 60 秒確認，touch 必須在最近 5 分鐘內。這是 sampled-trade research evidence，不能保證每筆中間成交路徑。

盤前使用獨立 indicative lane，明確非 actual trade，decision_usable 為 false，不能確認 reaction / retest。Actual lane 另外檢查真實成交時間與 receipt freshness，不以新收到的舊成交當成即時成交。

Scanner 的 `completed_daily` lane 獨立讀取既有 `TaiwanOfficialDailyBarRepository` 的 exact completed
session official close，保留 receipt cutoff、exchange authority、final/corrected、raw basis 與 selected lineage。
沒有該完成日的合格 close 就回 missing，不從 intraday state 或更舊的日期補值。週末／假日以交易日曆
的最後完成日為 basis。此 lane 支援 near_zone、within_zone、above_zone、below_zone；within_zone
只表示收盤位於區間，拒絕 touching 與 reaction/retest。Actual／indicative 語意與 freshness 守則不變。
HTTP 與 `screening.price_map`／generated MCP schema 共用同一 backend builder；不建立另一個 capability。

## Swing 研究與監控

Price Map Producer／Scanner 與 Swing 共用 `tw_universe.list_taiwan_stock_universe` 的 active
TWSE／TPEx 普通股母體與 regular-stock code 判定。Considered／eligible／limited 是 cheap
prefilter 覆蓋；Top-N selected／detail considered／research-qualified candidates 是不同分母。
Deferred institutional flow 保留 unknown 與來源策略，不當作 cheap 資格缺陷；真日 K 缺口、
cutoff／source／corporate／snapshot 品質限制維持。Prefilter quality 與全研究 quality 分開，
全市場 cheap scan 不等於全市場詳細研究。原 scheduler 優先把有限 detail 名額給 eligible
輸入，缺口仍走原 repair／checkpoint／late-data recheck；版本 token 包含原 prefilter policy。

Journal nomination 保留 F01 candidate 的 aggressive／confirmed 模式與原 Entry／Stop／TP1／TP2，
原 1:2 R/R 僅排序／偏好標示。Monitor 是同 Journal revision 的 cache-only GET：到價、原策略
確認與研究品質成立可為 REVIEWABLE；事件 coverage partial、regulation／borrow／funding／broker
unknown 原樣公開，不因此變成 coverage complete 或 execution ready。已驗證停牌、處置、
holding-window 限制、錯誤價位／quote 與真正研究缺口仍阻擋。Confirmed 沿用 completed-daily F01，
aggressive 沿原價位條件；兩者不因無關 1m／5m 缺值被阻斷，也不代替原本所需證據。
前端可選每 15 秒純讀；不自動保存觀測或寫入 Broker Pending。原 Candidate promotion 仍是明示
操作；無法表達 completed-daily confirmed 時保留具體限制，不降級模式或新增執行能力。

## 已完成日盤中修補

原 `tw.bootstrap_intraday_base_1m`／demand／completed repair owner 對完成日使用 exact-date
Canonical Bar read，包括最新 presentation day 已收盤的情形。覆蓋由原 owner 的 observed trade／
verified no-trade 與 market semantics 判定；missing minute 不能推定無成交或補造價格。
結果保存原 bars count 與 covered／expected buckets，未完成回報 completed-session coverage
incomplete。成功取得但完成日 canonical revision／coverage 無進展時不重排相同短間隔取得，
保留原 obligation、延後 audit、provider backoff、attempt／call budget 與公平輪轉；真正新進展或
provider failure 仍由原 retry owner 處理。這不證明正式股票缺口已修復或 live session 已驗收。

## 採用與驗收

單獨選取 `technical.price_map` 時，AI technical reader 直接委派既有 Price Map owner，沿用其 Bars、Technical 與 Corporate Action 依賴；不額外計算未要求的全週期報告、advanced evidence 或產業比較。混合能力請求維持完整 reader 與各自 projection。

一次同步 Bar／Technical 計算以同一份交易日曆 snapshot 完成查詢，避免每個交易日重複檔案 I/O。範圍結束立即釋放，下一次計算重新檢查日曆更新；不加入跨請求 TTL，也不更動休市日、臨時停市與 fallback 規則。

週／月 component continuity 只使用已知年度日曆。若某年既無 verified cache 也無內建年度表，component missing count 保留 null；近期視窗以 coverage unknown 阻擋，不把平日 fallback 當成已確認的歷史交易日缺口。

2025/1/23–1/24 依 [TWSE 春節公告](https://eshop.twse.com.tw/zh/news/detail/8a82e9e69471d3e8019495d573f70017) 屬只交割、不交易日，已列入內建日曆。Snapshot 依賴 digest 同時納入內建年度日曆、臨時休市與 verified cache，避免日曆修正後沿用舊品質判定。

`ENABLE_TAIWAN_PRICE_MAP_SNAPSHOT_SCHEDULER` 預設 false。正式採用順序為備份與 migration、同批更新 Backend / Frontend / MCP、啟用 bounded producer，再驗收實際 coverage 與延遲。每輪成功不等於全市場完成；吞吐、盤前及盤中行為必須在正式資料與交易時段確認。切換前可保留原本日線 read path，但不宣稱 Scanner 已有正式 snapshot。

Source / fixture tests、Runtime adoption、Live/provider 與 Product acceptance 是分開的 gate。當次證據與尚未通過項目記錄於 active exec plan，不由本文件宣告正式市場可用。
