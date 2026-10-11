# US intraday verification 與 daily chart overlay

## Owner 與讀寫邊界

盤後 reconciliation 屬於既有 `intraday_materializer`／scheduler owner，acquisition、provider selection、persistence、canonical reread 沿用 `USIntradayMarketPlatform` 與 Shared Gateway。GET 不會啟動 repair、排程或 provider IO。

`reconcile_us_intraday_session` 接受明示股票／ETF symbols 與已完成 regular trade date；最多兩檔、每 run 合計兩次 reservation，每 attempt 最多一次 provider call。超過設定容量或含 index 的 scope 整輪 fail closed，回報 `invalid_configuration`，不會默默截取前兩檔。相同 symbol／NY trade date／regular／1m 的義務保存在既有 `JobRun`，job type 為 `us.intraday_eod_obligation`。不建立第二份 coverage table；result 是附 checked_at 的最近 canonical reread 診斷，不是市場資料 truth。

G2 SQLite migration `20261009_0092` 以 scoped partial unique index 保護所有狀態的 target identity。短 `BEGIN IMMEDIATE` transaction 內驗證 index 欄位與完整 predicate、建立義務、檢查 attempts／cooldown 並預留額度；commit 後才允許 IO。每 target lifetime 最多三次；保存唯一 reservation ID、unknown outcome 與 15 分鐘 next_retry_at。失敗、空資料及 crash 均不退款，job success 不重置額度。缺少 migration、錯誤 index 或非 SQLite backend 時 fail closed。

每個本機 SQLite DB 使用一個相鄰 `.us-eod.lock` advisory lock，僅既有 EOD worker 持有，不持有跨 IO 的 DB transaction。活著的 worker 不以 timeout 被搶占；OS 在 worker process 死亡時釋放 lock，下一 tick 可回收殘留 running，仍遵守原 cooldown／attempt budget。Thread unwinding 同樣釋放 lock。無法取得／建立 lock 時不 acquisition；不支援 network-filesystem／distributed DB。Finish 需 current running status、attempt count 及 reservation ID 均相符，過期 worker 不得覆寫新 reservation。既有 lifecycle `mark_interrupted_jobs` 保留 request ledger；即使它改變 status，OS lock 仍阻止並行 provider IO。

排程 opt-in 預設關閉、symbols 預設空值。僅接受明示設定的有限 symbols，不讀取或展開整份 watchlist。每 15 分鐘先檢查最新 completed date，再檢查 NY 今日至五個日曆日前的 completed sessions，共享同一 run 的兩次 call budget。沿用 backend holiday／DST／early-close，保留五分鐘 settlement buffer。各日期 obligations 可由 JobRun 恢復；complete 不 acquisition。過期義務每 symbol 以 index range seek 讀最近六筆，最多 12 筆；未完成者保存 `retention_expired`，不宣稱可補齊，不刪 bars 或 ledger。更早的紀錄保留歷史結果，但超過五日一律不重新 admission。

Complete 必須 canonical reread 有完整分鐘 identity／順序、無缺口、所有 bars finalized／corrected 且 facts usable。診斷分開呈現 complete／partial／missing／error、corrected count、coverage、reason、unfillable reason、next_retry_at 及 reservation。Acquisition 成功、daily current 或 worker 完成不等於 intraday complete。不補造 no-trade／zero-volume bars。此 obligation 的 JobRun 只有 complete 才標 success；partial／missing／provider error 保持 error。

Canonical bar transaction 在 commit 後、Gateway post-processing 前失效化既有 US intraday read cache；partial/full/corrected 新 evidence 都適用。Materializer 無論 reread 成功或失敗，都在觀察到該 symbol 的失效化後提交原 bounded cache-only publisher。Publisher 延遲、飽和或失敗不還原舊快照。既有 reader 與 publisher 用有界 per-symbol generation token 防止晚到 projection 寫回舊 cache；token eviction 不重用 generation。其他 symbol 的提交不會失效目前 symbol 的 token。TTL、stale/current、raw receipt 與 Tape 語意不變。

既有 GET health 的 `runtime.us_intraday_reconciliation` 顯示有效 process settings、symbols／invalid scope、scheduler registration、limits 與背景 snapshot。`last_decision_in_process_only=true` 明示本程序執行紀錄；scheduler 註冊及每輪完成時讀取 `persisted_jobs_snapshot`，每 symbol 以 index range seek 讀最近六筆，共最多 12 筆 JobRun，恢復 attempts／backoff／coverage 診斷。Snapshot 有來源及 loaded_at，coverage 是最後紀錄而非 GET 當下 audit。Health 不開 DB、不 IO、不 enqueue；無 snapshot 時明示 unavailable，不能把 source defaults 宣稱為正式 effective runtime evidence。

以上為 source contract。G2 只在隔離 SQLite／fixture 驗證，未執行正式 migration、啟用設定、restart、provider call 或 runtime／live／product 驗收。

Completed regular read 先把交易日的 regular 邊界交給既有 US platform，再由 Shared Resolver 對整份單一來源做 eligibility／finalization／coverage 選擇。明示 `BarCoverageRequirement.allow_partial_fallback` 的 completed single-source cache read 可選完整來源，或無完整來源時選可用 finalized 分鐘數較多的來源；相同／足夠 coverage 維持既有 freshness 與 provider priority。預設 request 不啟用此行為，不跨來源拼接。沒有 finalized 候選時仍可顯示原有 provisional factual fallback，但不可標 completed。Historical 與 EOD canonical reread 共用此入口。

OHLCV 相同不代表 bar evidence 相同：finalization 變更必須保存 lineage 並失效 read cache；較舊 receipt 不可將相同 OHLCV 的較新 finalization 倒退。Twelve Data 被選取時保留 `PARTIAL_US_MARKET_VOLUME`／`PERSONAL_INTERNAL_USE_ONLY`，完成分鐘 coverage 不代表 consolidated SIP volume，歷史每棒 `volume_based_decision_usable=false`。上述修正只有 Source／隔離測試與正式資料唯讀重播證據；running release adoption 仍由 R1 Gate 阻擋。

## G-B 跨排程候選路由（Source contract）

Completed acquisition 明示 typed `acquisition_window=dated`；CURRENT 維持 `relative`。
既有 Yahoo／Twelve intraday descriptors 宣告 bounded dated support／五日 lookback，Shared Planner
仍檢查 market、instrument、interval、date、health/entitlement 與 budget。Descriptor 的 unknown-health
policy 未改：unknown/stale health 只在 descriptor 允許時帶 caveat admission，不代表已驗證真實 quota
或 plan entitlement；已知 disabled/auth/plan/rate-limit 則按 Shared policy 拒絕。

同一原 JobRun 先做無 reservation 的 `route_pending` 檢查，再由 Gateway 選出單一合法 route。
Gateway 的 `before_acquire` callback 將 typed planned resource 交回原 JobRun owner；owner 重讀 canonical，
在短 BEGIN IMMEDIATE 內重查 migration、attempts、cooldown、run budget 與 provider history，commit 後
才允許 acquire。Callback 僅適用單 fetch route、max_provider_attempts=1、max_external_calls=1、零 subscription；
Gateway 不持有 DB transaction。原 OS lease 橫跨 plan/admit/IO/finish，scheduler 不選 provider 或 coverage。

`request_json.attempts[].planned_resource` 保存 Shared plan 的完整 route identity／bounds／limitations；
finish 保存實際 reported `selected_resources`，不把 canonical selected provider 當成此次呼叫的 provider。
所有已預留的 provider，包括 unknown／失敗，傳給 Shared Planner 的 `excluded_providers`，以
`PROVIDER_ALREADY_RESERVED` 排除其所有 resource；只剩合法次來源時下次 admission 才選它。不把單次
budget 提升為 2。兩來源已消耗而仍不完整則回報 `acquisition_plan_unfillable`，最多三次是上限，
不是保證可以重送三次。未 reserve 的分支不重寫原 request_json；原三次耗盡維持 `retry_budget_exhausted`。

舊 attempts 缺少可識別 planned_resource 時回報 `legacy_route_history_unknown`，不從排序、結果或
現行 catalog 回填。原 ledger 不退款、不重置；restart/orphan 繼續消耗 prior reservation。
無 eligible route 保存 Planner 的精確 skip reasons；timeout 加上 `INTRADAY_PROVIDER_TIMEOUT`，未取得
可靠 acquisition summary 的中斷標 `PROVIDER_OUTCOME_UNKNOWN`／external_call_count_unknown。
Canonical coverage／quality 仍完全沿用既有 single-source Resolver，不因分鐘完整提升 volume/decision usability。

部署前與耗盡 SSO 的人工處理規格位於
[本輪 operator runbook](../exec-plans/completed/us-gb-durable-routes-20261010/OperatorRunbook.md)。
這是 Source／離線 fixtures 工作，未部署、未讀正式 SQLite、未呼叫 Provider；原 exhausted SSO 不會被自動重試。


## Finalized Daily 與 provisional display

`read_us_daily_ohlcv_chart` 的 `points`、`point_count`、continuity、previous close 及 daily usability 一律維持 finalized canonical Daily 語意。AI、research 與 Tape 不會在這些欄位收到暫定日 K。

只有 chart API 明示啟用 `include_intraday_overlay`；一般 Python reader 預設關閉，research／AI 不為暫定圖形額外讀 intraday。Overlay 是獨立的 `USProvisionalDailyOverlayRead`，來自同日 canonical regular 1m bars，不選 provider、不取得外部資料、不寫回 daily storage。

Overlay 保留 trade date、source、event time、full regular-session coverage、freshness、market session、derived authority、daily release status 與 `finalization=provisional`；`decision_usable=false`。缺少任何 volume 不填零；重複、非單調、off-grid 或混合 price basis 不產生 overlay。盤前、不同交易日、weekly/monthly 與明示歷史日期不混入 overlay。同日 finalized Daily 存在時不再讀 overlay，回傳 `intraday_overlay=null`。

USStockDetailPanel 的專用 visible chart series 才合併 `intraday_overlay.point`，並顯示暫定、coverage 與 freshness marker。Canonical `chartData`、technical indicators 與 shared daily consumers 保留 finalized series。Daily／calendar／intraday revisions 失效圖形讀取；response generation guard 拒絕晚回應。

## Frontend request lifecycle

Identity、chart、Today、research、目前 supplemental tab 各自開始讀取，不以其他 request 成功為前置條件。Today 使用 symbol/scope/interval scoped state，取消離開的 scope，拒絕 response identity mismatch。Timeout／HTTP error 有終止 error 與 retry；保留已顯示快照時明示本次未驗證。

Today cadence 消費 backend market phase。非 active phase 每 60 秒 cache-only revalidate，可跨越 15 分鐘 reconciliation 週期；不因成功 partial read 達固定次數而停止。連續 6 次 request failure 才暫停，保留 error 與手動 retry；focus／visibility 恢復亦可再驗證。背景隱藏頁面不發讀取。

Supplemental partial failures 不轉成偽 empty success；成功欄位照常呈現，失敗欄位保留先前值並顯示 request error。Failed load key 不加入成功快取，明示 retry 可重新讀取。
