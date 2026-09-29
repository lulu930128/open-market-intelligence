# Market Temporal / Evidence Axes Contract

本文件定義 OMI 如何分離市場時間、evidence lifecycle、authority、release、reconciliation 與 freshness。它不建立 universal `TemporalState`，也不以 Markdown 取代 source 中的 typed contract。

## Canonical owner

- Shared typed axes 以 `backend/app/market_data/contracts.py` 為 executable truth。
- Market-specific calendar、session transition 與 release window 留在各 market owner。
- Outward AI／API projection 必須保留正交 axes，不重新壓成單一 readiness 或 finalization 字串。
- 缺少的 axis 優先 additive typed extension；只有改變既有 serialized value、field meaning 或 consumer contract 時才需要 migration／version gate。

## Independent axes

台股 current breadth 的 receipt freshness、trade-state resolution 與 last-trade recency 分開投影。`valid_no_trade` 是獨立且有效的 state，不合併 `unchanged`，也不算 provider missing；`unknown_count` 仍保留非方向 partition 以完成 reconciliation。Observation coverage 使用 received/universe，directional coverage 僅使用 classified/universe；含未成交標的時，後者仍是 partial，即使 trade-state resolution 已 complete。

Same-session last-trade cache 必須有原始 event／receipt lineage 與 confirmed cumulative volume。只有當前 volume 與 confirmed volume 相等才可沿用；增加、倒退或缺乏基準皆不沿用。Full-market current-breadth refresh 後的 missing-z rescue 沿用現有 TWSE MIS batch、guard 與 canonical receipt transaction，受 symbol／batch／timeout／backoff 限制，cache-only read 不會觸發。Rescue 只接受同日、時間與累計量未倒退的正式 actual-trade evidence。

Stock-state 的 `event_time`／`snapshot_as_of` 保持 provider event 語意；receipt time 從 component lineage 獨立投影。Group／sector 可保留近期 receipt 內較舊成交的當日方向事實；`breadth_usable` 不豁免 decision、execution 或短期 rolling metric 的 recency gate。

### 1. Market Session

`MarketSession` 回答「市場現在或 observation 所屬的交易階段」。目前 shared values 是：

- `pre_open`
- `opening_auction`
- `continuous`
- `closing_auction`
- `close_resolution`
- `post_close`
- `closed`
- `unknown`

Market-specific presentation 可以顯示 `regular` 等 label，但不得把 presentation label 反向寫成 shared canonical value。

### 2. Instrument Trading Status

`InstrumentTradability` 回答個別商品能否交易。Market closed 不代表 instrument suspended；No Quote、No Trade、Halted 與 Suspended 不互相推導。

### 3. Evidence-object finalization

Finalization 必須由 evidence object 的 contract 定義，不建立跨所有 evidence 的大一統 enum。

- `BarObservation` 使用 `BarFinalization = provisional | final | corrected | unknown`，描述該 bar／time bucket 的成熟程度。
- `final` 本身不代表 exchange authority、official daily 已發布或 reconciliation 已完成。
- Session-close quote 是獨立 projection contract；它可以有 `resolving`／`session_final` 等 status，但不得因此擴張 generic `BarFinalization`。

### 4. Authority and lineage

`SourceLineage.authority` 回答來源權威類型，例如 exchange、broker、vendor、derived、cache。Authority 不代表資料已發布或已 final；exchange realtime 與 exchange official daily 仍是不同 dataset／evidence。

### 5. Release / publication

Release 回答特定 dataset 是否已到合法發布窗口並實際可用，例如 `pending_release`、`released`、`unavailable`、`unknown`。在 shared typed owner 尚未建立前，既有 outward `release_status` 是 projection semantics，不得被誤當 `MarketSession` 或 `BarFinalization`。

若新增 shared `ReleaseStatus`，必須是 additive source contract，並由 dataset lifecycle／market release policy 提供，而不是 frontend 或 consumer 依時鐘猜測。

### 6. Reconciliation

Reconciliation 比較兩份已具 identity 的 evidence，例如 session close 與 official daily close。常見狀態是 `pending`、`matched`、`mismatched`、`not_applicable`；比較結果不得覆寫任一原始 observation 的 session、authority 或 finalization。

### 7. Freshness

Freshness 回答 evidence 相對需求與時間是否仍可用。`current`／`fresh`／`live` 不代表 official final；official evidence 也可能 stale。Freshness 必須考慮 requested policy、instrument eligibility、event time、received／fetched time與 market session。

Completed-session evidence 使用 market-specific expected trade date 驗證，不用
固定 wall-clock 秒數決定跨週末／休市日後是否仍有效。台股 session close 的
candidate 必須對齊 `taiwan_presentation_session()` 所給 expected trade date；新一個
completed session 出現後，舊 session 才失效。

Market-specific emergency closure overlay 高於 annual schedule cache。年度快取中
「該日不存在」只代表未列於原年度排程，不得壓過後續宣布的颱風或其他臨時休市；
所有 continuity、expected date 與 presentation-session 計算共用相同 calendar owner。

### 8. Capability Expectedness

`CapabilityExpectation = not_expected | expected | required` 回答「這個 capability
在目前 market policy checkpoint 是否理應存在」。它不攜帶 session、support、
availability 或 freshness，因此不得加入 `expected_extended`、`required_regular`、
`unsupported` 或 `not_applicable` 這類混合值；這些語意由獨立欄位保存。

US owner 位於 `backend/app/us_market/temporal_expectedness.py`，並只使用 Backend
`America/New_York` calendar projection：

| phase | `quote.snapshot` | `intraday.bars` | expected scope |
| --- | --- | --- | --- |
| `pre_market_pending` | `not_expected` | `not_expected` | `none` |
| `pre_market` | `expected` | `expected` | `extended` |
| `regular` | `required` | `required` | `regular` |
| `after_hours` | `expected` | `expected` | `extended` |
| `post_close`／`market_closed` | `not_expected` | `not_expected` | `none` |

Outward `omi.us.capability_expectation.v1` 同時保留 expectation、requested／expected
session scope、instrument applicability、descriptor-derived support／live support、
availability、evidence freshness、provider snapshot freshness、trade state／recency、derived outcome 與
reason code。`expected_but_missing` 是 derived outcome，不是 primitive expectation。

Quote 的 provider snapshot freshness 以 `fetched_at` 判斷；last trade recency 以
`event_at` 判斷。Provider 剛回應不代表舊交易日的成交可成為 current observation；
active phase 只接受Backend calendar投影的`current_session_trade_date`。若cache只有較早
交易日，provider snapshot仍可保持`fresh`，但trade recency必須是`historical`、current
session requirement不滿足，Today series不得回退到latest cached date。Intraday bar
freshness仍以最新bar event time判斷；off-session才可明示投影latest historical session。

明示 `trade_date` 的 US historical intraday 使用 `historical_intraday.py` 驗證已完成的交易時窗與 bounded horizon；read path 僅從 canonical cache 讀取指定交易日。獲授權的 acquisition 才將該時窗傳入 provider，經 transaction persistence 後 mandatory reread。Regular completeness 依交易日曆（含 early close）的逐分鐘時槽、重複／缺段與 finalization 判定，不以總筆數單獨推定完整。Partial evidence 保持可見，historical projection 與其 points 不宣稱 live／realtime／decision usable。Extended completeness 尚不升級為 complete。

一般 US Today 讀取選到已完成 regular session 時，也傳遞 Market Truth 的
`regular_session_coverage` 與 `regular_session_completed`。Compatibility API 保存
expected／observed／missing／gap 與 finalization，綁定 `requested_trade_date` 供既有
historical fill contract 使用；連續的半天資料不能升格為 complete。圖表聚合不得
覆寫來源明示的 partial／未 finalized；來源 unknown finalization 同樣不能升格。

US Quote／Intraday selected evidence 的event recency由
`evaluate_us_selected_evidence_temporal()`單一pure owner判定，Compatibility service與
US Market Truth共同消費。Market Truth的`current_observation`只表示observation屬於目前
expected session；它可以同時是`freshness=stale`、`trade_recency=old`與
`research_usable=false`。Consumer不得用`current_observation` identity反推freshness或
decision usability，也不得用recent `fetched_at`覆寫舊`event_at`。

Producer refresh-due 與 consumer stale-after 是兩個不同門檻。US recurring
Quote／Intraday producer 在 evidence age 達 45 秒時即可 refresh；cache-only consumer
要到 180 秒才標 stale。Quote／Intraday scheduler tick 目前都是 60 秒，因此正常交易
時段每個 tick 都能重新評估已到期 evidence；tick 本身不代表必定呼叫 provider，
Shared Core 仍先讀 canonical cache，只有 refresh-due 才進 acquisition。這組契約的
source 目標是 current evidence age p95 不超過 90 秒；Runtime／Live 必須另行量測，
Consumer 不得把 producer cadence 複製成自己的 stale 規則。

US current-market comparison base 是另一個獨立 projection：盤前／正常盤使用
`prior_regular_close`，盤後／extended 結束後使用 exact finalized
`current_day_regular_close`。相容欄位 `previous_close` 仍表示 exact expected
completed-session Daily；consumer 不得用它猜測盤後漲跌基準。若當日正常盤 close
尚未可證明，`change_reference_status=missing` 並回
`CURRENT_DAY_REGULAR_CLOSE_PENDING`，不得沿用前一交易日 close。

## Derived labels

`official_final` 若需要作為 outward convenience label，只能是 derived state，不是 primitive enum member。至少同時需要：

```text
dataset_semantics == official_daily
and authority == exchange
and release_status == released
and item_finalization in {final, corrected}
```

Derived label 必須保留其 constituent fields；consumer 不得只收到單一 `official_final=true` 而失去 lineage、release 或 correction semantics。

## Taiwan session-close example

14:00 後、official daily 尚未發布：

```text
request_market_session = post_close
observation.market_session = closing_auction
session_close.status = session_final
session_close.authority = exchange
official_daily.release_status = pending_release
reconciliation.status = pending
```

Official daily 到達後：

```text
request_market_session = post_close
observation.market_session = closing_auction
session_close.status = session_final
official_daily.release_status = released
official_daily.finalization = final
official_daily.authority = exchange
reconciliation.status = matched | mismatched
```

Official daily 的到達不應把 session-close observation 從 `session_final` 改成另一種跨軸狀態；兩份 evidence 與 comparison result 應分別保存。

Quote／depth／auction persistence 的 `market_session` 一律由 observation
`event_at` 經 Taiwan calendar owner 分類，不得沿用 acquisition request 的 session。
因此 08:20 evidence 保存為 `pre_open`，不是 09:01 request 的 `continuous`；13:30:00
closing match 保存為 `closing_auction`，13:33 後的 request 則是控制面
`close_resolution`／`post_close`。`pre_open` 只是開盤集合競價前等待階段，只有
`opening_auction` 才可投影 opening-auction applicability。

Today／intraday history若需要在13:30顯示completed-session close，必須新增projection event，而不是製造或回寫一根成交bar：

```text
bar_type = official_close_marker | session_close_marker
price_semantics = official_close | session_close
display_eligible = true
indicator_eligible = false
synthetic = false
projection_event_count += 1
cached_count unchanged
```

`session_close_marker` 表示13:30 formal close 已有同交易日的 session-close evidence；即使該 evidence 具 exchange authority，只要仍是 provisional，就不得升格成 `official_close_marker`。`official_close_marker` 只接受 release-qualified、非 provisional 且 final/corrected/official-final 的 official daily evidence。當兩者都合格時 official marker 優先。Marker可引用canonical close evidence，但其圖表時間是formal close boundary；evidence event time、trade date、authority與finalization必須另行保留。Consumer不得把marker納入EMA、RSI、MACD、VWAP、TWAP、bar volume或persisted coverage count。

Marker可以攜帶兩個獨立的volume facts：closing-match volume與session cumulative volume。兩者必須來自session-close canonical observation並保留各自source field／event time；official close只擁有price axis。Interval bar sum與`bar_volume_latest_time`仍排除marker，technical若使用session cumulative volume，必須改用其volume event time與`session_final`狀態，不得把marker時間誤稱為最後一根interval bar。

收盤五檔也是獨立temporal evidence。`depth_available`只代表當下live order book；盤後保存值使用`depth_snapshot_*`，只接受同交易日且stored market session為`closing_auction`或`close_resolution`的canonical depth。它的語意固定為`closing_session_snapshot`、`decision_usable=false`，盤後read path為cache-only，Consumer必須明示該資料不代表目前可成交掛單。Regular-session殘留值或前一交易日depth不得升格為收盤snapshot。

## Invariants

- Market Session != Instrument Trading Status。
- Market Session != item finalization。
- Freshness != finalization。
- Capability expectedness != availability／freshness／support。
- Fresh provider snapshot != fresh last trade。
- No Trade != missing evidence。
- Authority != release。
- `BarFinalization.final` != official daily released。
- Session final != official daily final。
- Post close != official daily released。
- Live order book != closing-session depth snapshot。
- Reconciliation 不得 mutate 原始 evidence semantics。
- `post_close + session_final + pending_release` 是合法組合。
- release window 已到但 canonical official daily evidence 尚未到達時，必須投影為 released-but-unavailable；不得繼續顯示 `pending_release`，也不得用前一交易日 official close 假裝當日資料。

## 台股 quote、breadth 與 screening 的對外一致性

- MIS 單檔與 batch 的新成交判讀共用 `resolve_twse_mis_actual_trade`；試撮、非有限數值、交易日不符與缺少成交證據不得成為新成交。Batch 可保留同日先前實際成交，但必須保留原 price event time 與 `session_cache` lineage，不能用新試撮時間更新舊價格。
- Midpoint 是研究估計，只能保存在獨立估計欄位與帶 `is_estimate` 的結構；不能填入 `price`、`latest_price` 或 `last_price`。
- `quote.session_close` 預設 outward projection 保留 facts／research／decision usability。Quality 按此 dataset 解讀 `session_final`，保留 official-daily reconciliation pending，但不把 pending 本身視為 availability blocker；mismatch 與未滿足 require-live policy 仍會限制 decision。
- Breadth 的完成 session projection 保留 `observation_market_session`；canonical persisted observation 的 provisional 不因讀取時鐘而變更。只有 classified constituents 全部具 closing-match evidence、exchange authority 與收盤確認邊界後的 receipt，producer 才能持久化非 provisional observation。Unknown／missing coverage 仍獨立存在，不因 finality 歸零。
- Screening 與 Hot Groups／Sectors 在排序、分頁、mean／median／momentum 聚合前共用 `tw_intraday_state` ranking eligibility：expected session、actual trade、完整 lineage、成交與 receipt 時間都必須符合 current gate；receipt current 不使 old trade 可排名。Completed-session 候選需經既有 canonical session-close owner 確認 price、trade date、event time 與 lineage；沒有確認的 cache 不參與排名。Observation coverage 與 ranking coverage 分開，排除 stale 不縮小 universe。
- Breadth registered-universe reader、intraday screener 與 groups 委派 `tw_universe` ordinary-stock reader；沿用 `regular_stock_code`，bounded stock IDs 同時約束 numerator 與 denominator。
- 5m／15m return 的 reference 使用成交時間、必須在目標時間以前且 gap 不超過 `ROLLING_REFERENCE_MAX_GAP_SECONDS`；稀疏或舊版已存 metrics 在讀取時重新投影為 insufficient_data／null。全市場 state 沒有 canonical 1m volume-weighted 輸入時，VWAP deviation 為 unavailable，公式 owner 保持 `TaiwanTechnicalService.session_average()`。Full-market depth imbalance 沒有 producer 時回 unsupported，不逐檔抓 depth。
- Quote 先合併已確認的同 session 成交事實，再由既有 observation classifier 重算 instrument phase／reason；保留原成交時間，不因收到新 snapshot 升格成新成交或 official close。
- Taiwan Bar owner 將 explicit presentation date 與 implicit current session 綁到同一 window；其他 exact date 限制 from/to，不回退到其他日期。對外保留 expected／observed dates、history identity 與 materialization state；`not_materialized` 不代表任意標的已取得 Tier-A 資格。

## 台股盤前／盤中 evidence lane

- Quote snapshot 的價格、OHLC、quote time 與來源由原 snapshot 擁有。`current_price` 是獨立的 `resolved_current_price` 物件；1m fallback 不覆寫 snapshot 的價格或時間。既有 display／decision consumer 讀取此物件，沒有建立第二份 bar selection policy。
- Quote component 的 freshness 由選中 canonical candidate 傳遞；Resolved Evidence 為 stale 時，即使 `facts_usable=true`，也不得升為 current/live/decision usable。數值仍可作為帶時間的事實保留。
- `AuctionBreadthObservation` 是 actual breadth 同次 acquisition 的 typed companion，保存自己的 lineage、event time、session、indicative partition 與 provisional 語意。使用既有 transaction/repository 儲存，GET 不解析 raw receipt 或觸發 acquisition。它不進 actual breadth／regular screening 的計算。
- Auction breadth 在 requested session 過期時標 stale；離開對應 auction session 標 not_applicable。Unknown coverage 不補成 unchanged。Canonical companion 的持久化需要對應 Alembic migration；舊資料不推算出不存在的試撮 observation。
- Breadth acquisition diagnostics 分開描述 snapshot failed batches 與 latest attempt/fallback；partial attempt 不取代 transport-complete last-good baseline。Latest stock rows 不合併舊列偽裝 current。
- Actual-trade screening 只讀 expected session；盤前標 not_applicable。`observation_received_freshness`、`last_trade_recency`、`facts_usable_for_ranking` 與 decision/execution usability 分開；不放寬既有成交 age gate。
- Health 的 acceptance canary、bounded Tier-A 與 request-symbol scope 必須明示；單一標的缺資料不重定義全域 health。

## Today 行情摘要

`tw_session_summary.py` 是既有台股 market owner 的唯讀顯示投影；typed contract 擁有實際欄位。它不新增 persistence、provider selection 或 refresh。前端的圖表週期只改視圖，行情摘要固定引用同一顯示交易日的 1m canonical bars。

- 分時均價由 `TaiwanTechnicalService.session_average` 重用 canonical HLC3-volume 指標方法；明示估算、coverage 與 bars 範圍。零量沒有權重，缺量或不合格 bar 不可重啟後綴均價冒充整個 session。
- 分時成交值不含獨立 close marker；缺少真實 turnover 時的 close-volume 乘積只能標估算。部分有值只呈現 partial subtotal。
- 昨量錨定顯示交易日的前一交易日，保留 official daily aggregate 與 quote cumulative 的範圍差異；同時段相對量引用既有 volume-pace owner。
- Quote freshness、官方收盤確認及各欄位時間仍各自保留。摘要不因收盤價確認而升格 stale quote，不以 bar 尾端時刻重新推定 canonical coverage。

## 台股收盤 evidence 與有界回查

- Public quote 候選先通過顯示交易日與角色資格，再套 provider candidate bound。Current breadth price-state bridge 保留原始 trade receipt；讀取時點不能製造 session-close confirmation。Tier-A 收盤確認仍是有界股票集合與時窗，不能代表全市場確認。
- Index official-close 最早評估時間由 `official_index_contract.py` 擁有，與股票 Daily release 分開。最早評估不代表 provider 發布保證；reconciliation 必須驗證官方日期、receipt、authority 與 finalization，breadth ready 不足以停止重試。
- Bar 的 market phase 由 `TaiwanBarService` 傳遞至 AI compact／capability；current interval bar 可以滿足研究用 freshness，但不因此取得 execution usability。
- 成交值與 baseline 組合由 `taiwan_market_state.py` 擁有。兩市場 component 需有可比日期、分鐘、scope 與明示 authority；baseline 另需相同 comparison date、minute、component scope 與足夠樣本。Warnings、ratio、field status 隨資格重算。AI 只委派組合與投影。
- Breadth 的參考價缺失、實際成交價缺失各有 coverage partition，diagnostic reasons 另行核對；舊 `mapping_error` partition 仍可讀，新分類不將缺價解釋為 symbol mapping failure。Trade-value semantics／estimate flag 經既有 canonical companion 保存；舊 row 缺 metadata 保留 unknown，不推定 official。
- `TaiwanAuctionRepository` 依交易日及可見 receipt 時間查詢；歷史 reader 位於既有 realtime platform，與 current applicability 分開。盤後 history 可讀但保持 indicative／provisional，decision／indicator／execution usability 均為 false。沒有可見 row 僅表示 missing，不能證明從未採集；不引用 acceptance capture table 作 production fallback。
- Shared EOD coverage 由 job composition 注入 `qualify_taiwan_eod_universe`，以既有 Daily batch source／receipt／OHLC 資格判 current。拒絕原因與 provider receipt diagnostics 分開，不把 transport success 當 coverage success，也不縮小 active ordinary-stock 分母。Diagnostic parser 只處理有界已存 receipts，不 acquire 或寫入。

## 台股盤中觀察修復的讀取契約

- `TaiwanBarService.read_current_session_presentation_events` 是 chart 與 AI 共用的收盤展示事件 owner。即使當日分 K 為空，仍可呈現符合日期、receipt 與 authority 的收盤 evidence；`presentation_events`、`display_event_count` 不計入 bar count、coverage、materialization 或 technical eligibility。Official close 的價格來源與 session-close 成交量來源分別保存，事件使用獨立 evidence ID，修正事件不改寫 Bar revision。
- 完成交易日的 intraday ranking 與 Hot Groups 使用同一 session-close requirement 進行有界批次讀取，再以 detached input 更新價格、漲跌幅、累計量及估算成交值。收盤時窗與可見 receipt 在 candidate bound 前過濾；不用新價格搭配舊 rolling volume 或短週期報酬。不改寫 scheduler rows、不縮減原始 universe 分母。Partial group 可保留 `facts_usable`，但 `ranking_scope=qualified_sample_only`、`is_complete=false`、`decision_usable=false`。
- Completed-session 讀取明確傳遞 market-owned trade date；`requested_at` 只保留當次可見時間，不能用週末日曆日期取代最近交易日，也不能移動 receipt cutoff 製造 confirmation。Breadth companion 在有界選取前檢查 snapshot 與 raw receipt 可見性，逐 symbol 再驗原始 lineage；一般 ingestion／live reader 未指定 trade date 時仍限當日。Single／batch close 共用此日期語意。Detached ranking input 的 observation phase 由成交 event time 決定，與 request phase 分開。
- Current breadth 的 `auction_breadth` 仍表示當前時段適用性。`latest_completed_auctions` 從既有 canonical snapshots 讀取當日已完成的開盤／收盤試撮，各至多一筆；驗證 phase、trade date、receipt 可見性與 lineage。盤後保留 historical／indicative／provisional，current／live／decision 為 false，不用它補 current actual breadth。 Actual breadth 缺失時保留既有 `breadth=null`，由 index summary 的獨立 `latest_completed_auctions` 提供歷史證據；HTTP／AI／廣度明細都不以零值補出 actual counts。
- MIS batch diagnostics 分開記錄 attempted、failed、skipped，並保留安全的 HTTP／timeout／parse／budget／guard 原因。429 後未送出的批次不算 failure；成功批次保留 partial coverage，retry 不擴大既有 budget。Last-good fallback 保留原始 event 與 observation receipt；新嘗試的 raw fetch 時間不能使舊 evidence 變 current。
- Source-health 單項 malformed metadata 以 unavailable diagnostic 回報，其他 entries 繼續可讀；這不等同 provider failure，也不能取代當時的 provider error／raw receipt。
- Current-session Bar 的 `read_diagnostics` 分開 snapshot cache、canonical store 與最終 series revision。Recent snapshot reuse 先比對有界 DB row／lineage revision；新增、刪除或修正後必須重新解析。按指定 revision 取 immutable snapshot 的既有語意不變。Canonical Bar projection 明示 persisted hit／miss，不以 missing legacy cache metadata 推斷 miss。
- Futures volume metadata 由已實作的 futures provider parser／persistence owner 宣告 contracts、interval／session／trading-day 語意與 contract month，經 normalization、technical report 與 outward quality 原樣傳遞。AI 不依 TXF 名稱補單位；未知 provider 或 metadata 仍不能通過 volume unit guard。
- 同分鐘量能 baseline 額外揭露歷史 session 數、可用樣本數及 date／minute／market component／scope／lineage 篩除原因。零樣本不補零或插值，一個 prior-session sample 仍為 warming-up。離線 latency 與 bytes 量測不表示 runtime／live SLO 已驗收。

## Negative acceptance

任何下列變更都必須被 architecture／contract review 拒絕：

- 建立混合 `pre_open`、`continuous`、`session_final`、`official_final` 的 universal enum。
- 以 exchange authority 自動推導 released／official final。
- 以 `current` 自動推導 live 或 official final。
- 讓 frontend、MCP 或 AI consumer 自行依時間決定 release／finalization。
- Official reconciliation 完成後覆寫原始 session-close authority、event time 或 session status。
