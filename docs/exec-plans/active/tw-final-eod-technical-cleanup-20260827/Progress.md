# 進度

## 狀態

- 目前階段：source fix 與 runtime-discovered outward gap complete；runtime adoption / live acceptance pending
- 最後更新：2026-08-28

## 已完成

- 讀取 current architecture、nested AGENTS、dataset lifecycle、provider descriptor、transaction、Resolver、EOD coverage 與 frontend chart/report surfaces。
- 證明 scheduler 與 EOD job 已執行；阻塞點是 TWSE resource payload date，不是 background owner 未啟動。
- Bounded official read 證明 `MI_INDEX ALLBUT0999` 在 2026-08-27 提供 1377 列同日個股 OHLCV。
- 確認 frontend 三個收尾缺口仍存在：unknown unit fallback、canonical indicator silent fallback、technical snapshot 混顯。
- 在既有 TWSE official daily provider family 內加入 `MI_INDEX ALLBUT0999` 同日 full-market resource；`STOCK_DAY_ALL` 保留為次順位 resource。
- 同日 resource 仍經既有 acquisition planner、`TaiwanOfficialDailyTransaction`、candidate repository 與 Resolver；沒有新增 scheduler、table 或 EOD owner。
- EOD coverage job 注入既有 market-owned venue refresh，full-market checkpoint 持續擁有嚴格 postcondition；all-market freshness 不再由兩 venue 的最大日期掩蓋 partial coverage。
- 前端 unknown volume unit 改為原值與 generic label；只有明確 `shares` 才標示股，不再預設除以 1000。
- 台股日 K canonical indicator 改為 backend authority；missing／parameter mismatch 時 MA、RSI、MACD 等為 null，presentation-only overlays 仍可本機計算。
- Technical mapping 正式拆出 `decision_state` 與 `current_observation`；主標題、分數、rows、chips 使用 finalized state，今日暫估另區顯示且明標不可作 finalized decision。
- 台股日線 backend report 缺失時 fail closed 顯示資料不足，不再使用本機完整技術報告替代。
- Read-only runtime／DB 診斷確認 2026-08-28 00:11 啟動後，2026-08-27 TWSE coverage 仍 deferred 到 2026-08-28 15:15；根因是既有 release guard 以 current calendar date 重算，不是 MI_INDEX resource 或 session-close owner 缺失。
- 修正既有 EOD release policy：已發布的 pinned historical session 可立即 catch-up；same-day official release 仍維持 15:15；future／non-trading date fail closed。
- Scheduler 在 enqueue 前固定 expected trade date並傳入 job request，避免等待期間跨 release boundary 後日期漂移。
- 只有 `repair_status=deferred + repair.phase=release_guard` 可因 release eligibility 改變而略過舊 retry timestamp；provider rate-limit／error backoff 仍保留。
- Post-close projection 將 official daily 的 pending 與 released-but-unavailable 分開；次日 05:00 前也可正確提升前一交易日 canonical official close。
- 修正 provider resource route 的 typed `max_symbols` 上限，使既有 full-market planner 可攜帶 TWSE 1086／TPEx 887 等實際 active universe，不在 acquisition 前被 500 截斷；coverage checkpoint 仍是唯一成功 gate。
- 修正 `days=1` 台股 intraday read range，直接使用既有 `taiwan_presentation_session()` 的 trade date；午夜至 08:00 前不再把「今日」切到尚未開盤的 calendar day。
- 修正既有 public quote session-close candidate／projection：finalization 依 evidence trade date、13:30–13:33 event window、actual trade、confirmed boundary、freshness 與 volume monotonicity判斷，不再錯誤綁定目前 market session 必須是 `post_close`。
- 修正台股 stock header 的 price／change／change_pct atomicity：優先 current evidence，否則使用明確 completed-session evidence；兩者皆無時三個欄位一起 unavailable，不再顯示 `-` 搭配另一 session 的漲跌。
- 移除受新 headline primitives 影響的兩個 presentation-only manual memoization；保留純計算並由既有 React Compiler 處理，lint 不再跳過 component optimization。

## 驗證證據

- TWSE official GET：`stat=OK`、`date=20260827`、daily table rows=1377。
- 3711 official row：O/H/L/C `608/608/593/605`、volume `11,658,860`、trade value `7,011,817,192`、transactions `18,048`。
- Backend expanded targeted regression：`128 passed`；最後 source-lineage 調整後再跑核心 `35 passed`，僅 `.pytest_cache` 權限 warning。
- Frontend：`npx tsc --noEmit`、`npm run lint` 通過。
- Frontend pure contract：canonical fail-closed、unknown volume raw value、finalized/provisional mapping，`3 passed`。
- Frontend browser smoke：technical disclosure、signal chip routing、finalized/provisional visible separation，`3 passed`。
- Architecture guard：`PASS`，actual violations `26` 與 declared debt `26` 一致。
- `git diff --check`：通過；僅既有 Windows line-ending 提示。
- Catch-up／scheduler pinning／quote projection targeted suite：`35 passed`。
- Official daily／source health／daily freshness／quote-depth related suite：`36 passed`。
- Quote components／AI market-context suite：`37 passed`；合併重跑核心修正 suite：`72 passed`。
- 工程書指定 AI realtime／decision envelope／freshness／calendar／MIS／official daily regressions：`256 passed, 18 subtests passed`。
- 修正後 architecture guard 再驗證：`PASS`，actual violations `26` 與 declared debt `26` 一致。
- Full-market route／official daily scale regression：`34 passed`；包含 1086-symbol route 與任意 3711 persist/reread fixture。
- Intraday／public quote／catalog 核心 regression：`43 passed`；EOD scheduler、quote、calendar 擴充 regression：`65 passed`。
- 工程書指定 quote／AI／technical／calendar 全組 regression：`327 passed, 18 subtests passed`。
- 實際 DB read-only smoke：3711 的 `days=1` 在 2026-08-28 00:53 正確讀出 2026-08-27 09:00–13:30、266 points；既有 13:30 evidence 投影 `session_final` price 605、trade date 2026-08-27，current session 可為 pre-open。
- Frontend 最終驗證：`npm run lint`、`npx tsc --noEmit` 通過；focused `tw-eod-contract.spec.ts` 為 `4 passed`。
- 最終核心 source regression（provider catalog、official daily、intraday、public quote）：`63 passed`；僅 sandbox 無法寫入 `.pytest_cache` 的非功能性 warning。
- Architecture guard 最終驗證：`PASS`，actual violations `26` 與 declared debt `26` 一致。

## 已做決策

- 沿用 `daily_ohlcv_platform` 與 `TaiwanOfficialDailyTransaction`；MI_INDEX 是同一 provider family 的新 resource，不是新 EOD owner。
- EOD job 繼續以 full-market coverage postcondition 為成功條件。
- Runtime restart 與 live acceptance 不在本輪 source edit 的隱含授權內。
- Production build 未在本輪執行：既有 Next dev server 持有 `.next` lock，避免干擾使用者正在運行的 frontend；以 typecheck、lint、pure contracts 與 browser smoke 取代。

## 已知風險

- 停牌／無成交 instrument 的 expected eligibility 仍可能使 full-market coverage 保持 partial；不得以零值或舊 close 補齊。
- 目前 worktree 有大量既有 TW／US 未提交變更，本任務只做局部 diff。
- 一項既有 selection-change smoke 在 watchlist ranking fixture 前置條件失敗，畫面載入的是另一組 group/ranking state；失敗發生在圖表與 technical assertions 之前，且本任務未修改 watchlist/ranking owner。其他三項本任務直接相關 browser smoke 均通過。

## 下一步

- 由使用者檢查 source diff；若要進一步做 runtime adoption，需另行授權以既有 launcher lifecycle 重啟，然後驗證 3711 同日正式資料、full-market coverage checkpoint、source health 與前端 finalized/provisional 呈現。

## 2026-08-28 整日 live acceptance

- 08:20 source/runtime preflight 通過：HEAD 為 release `ba1682e5`，包含 fix `2c603da7`，`VERSION` 與 runtime OpenAPI 均為 `4.3.1`。
- 正式 launcher lineage、project root、`.venv` Python、backend `8400`、frontend `3000`、health/ready、Alembic head、frontend proxy 與 stdio MCP 均已驗證。
- 2026-08-28 由 TWSE authoritative calendar 判定為交易日，08:23 phase 為 `preopen_pending`；official daily release time 維持 `15:15`。
- Realtime global baseline 為 active leases `0`、bridge process `false`；未執行 restart、lease release、DB write、commit 或 push。
- Canonical stock master 動態候選為 3711、TWSE 1101、TPEX 1240；preopen gate 仍須驗證 realtime descriptor eligibility 與正常交易狀態，不能由 source preflight 升格。
- Source-ready：passed；runtime-adopted：passed；live-accepted：pending；product-accepted：pending。
- Redacted evidence：`artifacts/live-acceptance-preflight-20260828.json`。
- 08:30～08:33 Preopen 真實時窗 gate 通過：3711、canonical stock master 動態候選 TWSE 1101、TPEX 1240 都可訂閱並取得 L5 depth；39 個 callback 全部分類為 auction evidence，trade additions `0`、trial leakage `0`、cumulative decrease `0`、negative latency `0`。
- 三檔 quote-depth 均為 `preopen_auction`／`preopen_indicative_match_and_depth`，`actual_trade_occurred=false`、today OHLC／cumulative volume unavailable、session close unavailable；public quote read 對缺少 `last_trade_price` fail closed，intraday today bars 為 `0`，沒有把 indicative match 升格為成交。
- Acceptance probe 只釋放自身三個循序 lease；global baseline 由 `0` 回到 `0`，bridge 在自然 idle 125.299 秒後停止，沒有外部 overlap、request error 或強制 cleanup。
- Preopen Live gate：passed；Opening、Regular、Closing、official EOD 與最終 Product acceptance：pending。
- Redacted evidence：`artifacts/live-acceptance-preopen-20260828.json`、`artifacts/live-acceptance-preopen-outward-20260828.json`。
- 08:58～09:05 Opening 真實 gate 通過：3711、TWSE 1101、TPEX 1240 都取得 2026-08-28 actual trade、OHLC、event time 與 lots/shares；3711 初段在正式撮合前結束，於 09:04:40 bounded retry 成功補到同一 Opening gate 的真實成交。
- Callback 分類維持守恆；3711 retry 的 cumulative advance `64` 對應 trade addition `64`，1 個 cumulative decrease 被 non-trade suppression，trial leakage 與 negative latency皆為 `0`。
- Opening outward read 已選出三檔 `kgi_superpy_quote_all` canonical quote snapshot，trade date皆為 2026-08-28；session close仍 unavailable。當時 intraday/current partial尚未形成，technical today誠實顯示 `waiting_intraday`／missing，daily finalized仍停在2026-08-27，沒有把昨日 official bar冒充今日。
- 初次 cleanup等待期間執行同任務3711 retry；active lease仍為循序單一owner，最終global leases `0`、bridge `false`。Opening Live：passed；Opening outward truthfulness：passed；current-partial availability：partial，留待Regular gate重驗。
- Redacted evidence：`artifacts/live-acceptance-opening-20260828.json`、`artifacts/live-acceptance-opening-3711-retry-20260828.json`、`artifacts/live-acceptance-opening-outward-20260828.json`。
- 09:12～09:17 Regular opening representative live gate 通過：以 3711、TWSE 1101、TPEX 1240 循序 bounded sampling 取得 `187` 個 callback；cumulative advance `31` 對應 trade addition `31`，same cumulative `153` 全部被 non-trade suppression，trial leakage、negative latency、decreasing cumulative、request error 均為 `0`。
- 三檔 quote snapshot 皆為 2026-08-28 `regular_live`／`regular_traded` actual trade，OHLC、lots/shares 與 KGI lineage 可見；backend quote-depth 與 frontend proxy 一致。Probe cleanup 等待 125.279 秒後回到 global leases `0`、bridge `false`，沒有外部 overlap 或強制 release。
- Regular outward freshness trace 顯示 `tw.intraday.bars` 雖宣告 `current_session` expected state，但三檔皆無 2026-08-28 canonical bar；read path 正確回傳 `TW_INTRADAY_CANONICAL_CACHE_MISSING`／`READ_POLICY_FORBIDS_ACQUISITION`、resolved `policy_unsatisfied`，technical today 維持 `waiting_intraday`，AI context仍只含前一 finalized session，未把昨日資料冒充今日。
- 此差異定位在 storage／normal acquisition scheduling 之前，不是 frontend、AI 或 Resolver fallback。依 live acceptance 安全邊界未手動執行 refresh／DB write probe，也未把 KGI quote snapshot 偽裝成 intraday bar；Regular Live quote gate與consumer quote parity為 passed，current-partial availability維持 partial，排定11:30再以正常 persisted state重驗。
- Redacted evidence：`artifacts/live-acceptance-regular-opening-20260828.json`、`artifacts/live-acceptance-regular-opening-outward-20260828.json`。
- 11:30～11:36 Regular midday representative live gate 通過：3711、TWSE 1101、TPEX 1240 共 `161` callbacks；cumulative advance／trade addition均為 `37`，same cumulative `121` 全部被 non-trade suppression，trial leakage、decreasing cumulative、negative latency與request error皆為 `0`。
- 三檔 2026-08-28 quote snapshot 仍為actual trade且freshness=`live`，backend與frontend proxy欄位一致；owner-only cleanup在120.409秒後回到global leases `0`、bridge `false`，沒有external overlap。
- Midday重驗確認current-partial不是短暫opening lag：三檔 `tw.intraday.bars` 均無2026-08-28 persisted observation，source health entries為 `0`，Resolver持續回傳`CACHE_ONLY_NO_ELIGIBLE_CANDIDATE`，technical today仍為`waiting_intraday`，AI context仍停在2026-08-27 finalized evidence。
- Executable trace顯示dataset owner是`app.market.tw_intraday_platform`、bounded operation是`tw.refresh_intraday_bars`，目前只有explicit POST command surface；`backend/app/jobs`沒有該operation的normal scheduler owner。這不是frontend／AI／Resolver bug，也不能以manual refresh／DB write probe或KGI quote-to-bar偽裝處理；若要根除需另行設計scheduler／normal acquisition ownership，故本輪安全地維持current-partial為partial並繼續Closing gate。
- Redacted evidence：`artifacts/live-acceptance-regular-midday-20260828.json`、`artifacts/live-acceptance-regular-midday-outward-20260828.json`。
- 13:20～13:28 Closing pre-close bounded sampling通過：3711、TWSE 1101、TPEX 1240共`458` callbacks，cumulative advance／trade addition均為`144`，auction evidence `2`且只出現在1240，same cumulative suppression `309`；trial leakage、decreasing cumulative、negative latency與request error皆為`0`。Cleanup回到global leases `0`、bridge `false`。
- 13:28:40啟動formal-match capture，以兩輪3711→1101→1240短步驟嘗試讓第二輪跨過13:30。第一輪結束後，第二輪3711於`close_resolution`無法取得owned lease，正式failure code為`LEASE_ACQUIRE_FAILED`；attempt未產生自動artifact，但owner lease已歸零且bridge在13:33自然idle。
- Root cause是current `KGI_QUOTE_SNAPSHOT_DESCRIPTOR`只支援pre-open／opening／continuous／closing-auction，不支援`close_resolution`新訂閱；sequential harness每次只持有一檔，因此無法同時讓3711、TWSE 1101、TPEX 1240都跨過13:30 formal callback。不能為製造pass而擴張provider descriptor或用post-close replay補證；未來需以經驗證的pre-acquired concurrent owner-safe probe或明確close-resolution provider semantics重做。
- 13:30:48 cache-only outward read正確顯示calendar／三檔quote／frontend proxy為`close_resolution_candidate`、session close unavailable、official close pending；13:34:17 post-close read三檔都誠實轉為`session_close_unavailable`，沒有把13:25～13:29 snapshot或2026-08-27 official close冒充2026-08-28 session final。
- Closing auction classification為passed；formal-match evidence與session-final projection維持partial／failed truthfully unavailable，不能由14:00或official EOD evidence回填成pass。Automation仍繼續後續post-close與official EOD gates。
- Redacted evidence：`artifacts/live-acceptance-closing-preclose-20260828.json`、`artifacts/live-acceptance-closing-formal-failure-20260828.json`。
- 14:00 post-close Product gate實際開啟3711前端並完成API／frontend proxy／AI／stdio MCP對帳；quote-depth在14:01後取得3711 `session_final` 621，但1101／1240仍為`session_close_unavailable`，且later evidence不得回填13:30 formal-match gate。Technical completed維持2026-08-27，AI context亦停在2026-08-27。
- Browser navigation暴露P0 release bug：日K history auto-backfill把intraday presentation date 2026-08-28當成official daily backfill end date，於15:15 release前透過legacy TWSE stock-day path寫入3711同日`market_daily_price`。MCP `omi.decision.v4`可見`daily.ohlcv=2026-08-28`但`quote.session_close=missing`，正確阻擋decision，卻也證明official daily publication semantics已被提前污染。
- 已在backend owner最小修復：TWSE／TPEx daily backfill acquisition與persistence一律cap到`expected_daily_price_date()`；完全未發布range在provider／DB access前回傳`skipped_unreleased`。新增三個release-guard regression，與既有job retry合計`21 passed`；architecture checker與architecture pytest通過。Full backend suite只因既有不可讀`backend/tests/tmpla6tzx59`於collection失敗，非功能性test failure。
- 修正後於global leases=0、bridge=false時只透過正式launcher `RestartServices`重新adopt；14:12 backend health／ready、project root、`.venv` Python、OpenAPI 4.3.1、frontend proxy、stdio MCP與zero baseline全部重驗通過。沒有刪除或改寫已污染的production row，也沒有manual refresh／repair；15:15後由正式EOD owner做正常reconciliation。
- 14:00 Product acceptance維持partial：source bug已根除並runtime-adopted，但本日live state已有一筆pre-release 3711 official row、1101／1240 session close缺失、current-partial無normal scheduler owner。Redacted evidence：`artifacts/live-acceptance-postclose-outward-20260828.json`；同一automation續排15:15～16:00 official EOD reconciliation。
