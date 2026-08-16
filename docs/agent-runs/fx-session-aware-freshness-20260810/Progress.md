# Progress

## Status

- Current phase: complete
- Last updated: 2026-08-11 21:43 Asia/Taipei

## Completed

- 依 frontend → API → service → SQLite/cache → provider event → job/runtime 路徑完成唯讀根因確認。
- 確認 ASX `2026-08-07` 與 expected US daily date一致；目前 cross-market stale 僅由 USD/TWD 引起。
- 確認 live USD/TWD event/fetch time 為 `2026-08-03T11:46Z`，約 169 小時，這次畫面同時包含 genuine stale cache，不能只用 holiday exemption 處理。
- 確認 `adr_parity.py`、`fx_flow_context.py` 與 `cross_market/refresh.py` 各自使用固定 72h；resource source-health 對 FX session 回 unknown 並使用 4h threshold。
- 確認 composite refresh plan 已可規劃單一 USD/TWD operation，但 stock-detail legacy ensure 只刷新 US daily symbols，正式 DB 也沒有 cross-market refresh job/event。
- 建立 `Prompt.md` 與 `Plan.md`，將 root fix 收斂為 FX session/freshness owner、四條 backend integration、bounded refresh handoff、consumer contract 與正式 runtime acceptance。
- 新增 `backend/tests/test_fx_freshness.py`，鎖定 daily trend、ADR 對齊、週末休市、maintenance window 與 future observation 五個 deterministic contract。
- 新增 `app.resource_market.fx_freshness` canonical owner；daily trend、ADR alignment 與 spot quote 依 purpose 分流，不再共享固定 72h。
- ADR parity 會優先使用 ADR trade date 的 USD/TWD 1d bar；任意較晚 spot 只作 fallback 並明確標記 future／misaligned。
- FX flow 排除 latest completed session 之後的 provisional daily bars，保留 observed／excluded point 數量。
- Cross-market refresh plan 使用 canonical `refresh_eligible`；休市與 maintenance 進 deferred，open-session stale 才進 bounded job，FX refresh 同時補 quote + 1d。
- Resource source-health 對 FX 回傳 session-aware nested freshness，保留既有 `live/delayed/stale` facade。
- Overnight read additive 投影 `refresh_decision`／`refresh_plan`；stock-detail 改成 cache-only GET，只有 backend `should_execute` 才 enqueue 一次既有 cross-market job，完成後 reread。
- Cross-market job 歸類到台股「更新狀態」；transport/provider failure 保留既有 payload並發布 stable dedupe event；currency snapshot 與 FX flow 顯示「最新已完成時段」。
- 實際 bounded canary 揭露 Yahoo FX 1d bar 使用 provider exchange timezone 標記（`Europe/London`），例如 `2026-08-06T23:00Z` 代表 `2026-08-07` data date；canonical owner 現在會解析 compact payload metadata，而不是直接使用 UTC date。
- Resource source-health 會先排除 latest completed FX date 之後的 current-day provisional 1d bar；ADR parity、FX flow 與 cross-market refresh plan 共用同一 data-date normalization。
- 普通股 overnight follow-up：確認 `build_us_overnight_impact_report` 把選配的 US watchlist baskets 誤併入必要 `missing`；即使核心美股因子已到 expected date 且 `valid_weight=1.0`，仍會把 3711 壓成 `unknown`／`weighted_change_pct=null`。
- 將核心 factor freshness 與選配 basket coverage 分流：只有核心 factor 缺漏或落後才封鎖方向訊號；basket 缺漏、partial 或落後會被排除於當期分數並留在 warning 與 `freshness.optional_basket_coverage`，不再偽裝成完整 coverage。
- 新增 3711 類型 regression，鎖定核心因子 current、四個選配 baskets 未設定時仍應產生 factor-only 隔夜判斷，且 confidence 降為 `medium`、限制保持可見。
- 正式 backend 已以 exact process lineage 重啟採用新 source；官方 launcher 隨後恢復 frontend。未觸發 provider、未 enqueue job、未寫 live DB。

## Validation evidence

- Live runtime：launcher-selected backend `http://127.0.0.1:8400`；`/api/system/health` 與 `/api/ai/tools` 回 200，僅作 runtime/schema baseline。
- `/api/market/calendar-status?market=all`：2026-08-10 台股與美股皆為 trading day；US daily expected date 為 `2026-08-07`。
- `/api/market/cross-market/context/3711`：`status=stale`、`adr_is_current=true`、`fx_is_current=false`、`stale_reasons=[fx]`。
- `/api/resource-market/source-health?symbols=USD-TWD&intervals=1m`：quote `status=stale`、`session_status=unknown`、`stale_seconds=14400`、age 約 609800 秒。
- `build_cross_market_refresh_plan(..., "3711")`：只有一筆 planned `resource_quote:USD-TWD`，`read_path_provider_refresh=false`。
- `test_current_read_recomputes_freshness_when_unchanged_inputs_age_stale` 與 `test_resource_quote_health_uses_best_effort_session_window`：`2 passed`；同時證明現有測試仍把固定 age threshold 當 contract。
- 本輪只改 task docs；未呼叫 provider、未寫 live DB、未 enqueue job、未重啟 runtime。
- R0 red proof：由 `backend/` 執行 `..\.venv\Scripts\python.exe -m pytest tests\test_fx_freshness.py -q -p no:cacheprovider`，因 canonical module 尚不存在而 collection failed，證明新 contract 尚未被 production code 實作。
- M1：同一命令 `5 passed`。
- M2 targeted：`test_fx_freshness.py test_adr_parity.py test_fx_flow_context.py test_cross_market_refresh.py test_resource_market.py` 共 `48 passed`；後續 cross-market/overnight regression 暫有舊 72h assertion，已改為 session-aligned contract 並進一步重跑中。
- Backend targeted regression：7 個相關 test modules 共 `76 passed`。
- `run-safe-validation.ps1 -Profile backend`：compileall passed、完整 backend `1679 passed`、`git diff --check` passed；log 在 `.tmp/validation/20260810-215606`。
- Frontend：`npm exec tsc -- --noEmit --incremental false` passed、`npm run lint` passed、`npm run build` passed（Next.js 16.2.12 production build）。
- 新增 Playwright bounded handoff regression；執行時先遇到 `spawn EPERM`，升權請求又被 Codex usage limit拒絕，因此未取得 browser pass。
- 以新 source 對正式 SQLite 做 read-only canary：3711 的 ADR date=`2026-08-07`、FX actual=`2026-08-03` 被正確判為 genuine stale，plan 僅列一筆 USD/TWD、`should_execute=true`、`read_path_provider_refresh=false`。
- Live 8400 canary仍回舊 contract（缺 `fx_freshness`／`refresh_decision`）；精準 restart approval 因 Codex usage limit被拒，未停止 PID、未觸發 provider、未寫 live DB。
- 使用者由 tray 完成 restart；launcher log 證明 2026-08-10 22:05:44 重啟，backend/frontend PID 分別為 `44996`／`35376`，`/api/system/health` 與 `/omi-ui-health` 皆為 200，新 live contract 已包含 `fx_freshness`、`refresh_decision` 與 resource source-health nested freshness。
- 執行唯一一次 bounded provider canary job `#5304`：`stock_ids=3711`、`max_symbols=1`、`max_runtime_seconds=120`。Job backend status=`success`、public status=`partial`；USD/TWD quote + 10 根 1d bar 成功寫入，ASX 因 source limit 被 deferred，沒有重複 job。
- Canary 後確認 quote freshness=`current`；同時發現 raw latest 1d 是 8/11 provisional，而 8/7、8/10 completed bars 的 UTC timestamp 在前一日 23:00。這個真實 provider 標記差異已納入 root fix。
- 新 source 對正式 SQLite 的 read-only canary：3711 ADR 8/7 現在使用 `resource_ohlcv_bar.1d` 的同日 FX，`fx_status=current`／`fx_usable=true`；USD/TWD 日線健康選到 8/10 completed bar，`latest_completed_session`／`ok=true`；refresh plan 只剩 genuine stale 的 ASX。
- Provider-timezone/provisional regression 的 7 個相關 test modules 共 `80 passed`。
- 最終 `run-safe-validation.ps1 -Profile backend`：compileall passed、完整 backend `1682 passed`、`git diff --check` passed；log 在 `.tmp/validation/20260811-174346`。
- 最後一次 runtime reload：launcher 於 2026-08-11 17:53:02 啟動，backend PID=`14652`、frontend PID=`47704`；API/UI health 皆為 200。
- Cache-only live reread：ADR 8/7 使用 `resource_ohlcv_bar.1d`，FX actual/expected 都是 8/7、status=`current`、usable=true；USD/TWD 1d actual/expected 都是 8/10、status=`latest_completed_session`、refresh_eligible=false；refresh plan 只剩 ASX，未再規劃 USD/TWD。
- Browser outward acceptance：3711 ADR 明細顯示「匯率 2026-08-07」，不再顯示 raw UTC 8/6 或固定 72 小時警告；匯率與外資明細顯示 FX 8/10，stale warning 明確歸因於大盤外資落後預期 8/11。
- ADR 明細改用 `fx_freshness.actual_data_date`，fallback 才使用 `fx_as_of`；追加 e2e assertion 後，frontend typecheck、lint、Next.js 16.2.12 production build 全部通過。
- Overnight targeted regression：`test_overnight_impact.py test_adr_parity.py test_fx_flow_context.py` 共 `32 passed`；compileall 與 target-path `git diff --check` passed。
- 新 source 對正式 SQLite 的 read-only smoke：3711 `as_of=2026-08-10`、`is_current=true`、`valid_weight=1.0`、`stance=strong_risk_off`、`weighted_change_pct=-1.4841`、`missing=[]`；四個未設定 baskets 留在 optional coverage，confidence=`medium`。
- Runtime adoption 後 direct API 與 frontend proxy `/omi-data/market/overnight-impact/3711?refresh=false` 都回相同新 contract；`refresh_should_execute=false`，沒有 read-path provider side effect。
- app 內瀏覽器首次載入儀表板成功；frontend 中途停止後由官方 launcher 恢復，但重新載入 localhost 被 Browser URL policy 阻擋，因此本 follow-up 沒有取得第二張實際卡片 screenshot。Frontend proxy contract 已驗證，且本輪沒有修改 frontend renderer。
- 最終 `run-safe-validation.ps1 -Profile backend`：compileall passed、完整 backend `1725 passed`、`git diff --check` passed；log 在 `.tmp/validation/20260811-214429`。

## Decisions made

- 不用更長 timeout 掩蓋問題；以 expected session + event/fetch dual age 修正。
- 不把 FX、ADR parity daily alignment 與 currency spot quote 當成同一 freshness profile。
- FX 先採 provider-defined 24x5/weekend/maintenance contract；NYSE calendar只能支援 ADR daily，不是完整 FX holiday truth。
- ADR parity 應使用 session-aligned FX；current spot 只作另一個 context，不混入 aligned parity。
- Frontend 只消費 backend `refresh_decision` 並 enqueue既有 POST job；不在 UI 寫 holiday/freshness 判斷。
- US watchlist baskets 是加值 coverage，不是 overnight 核心 factor 的必要 freshness gate；缺漏必須可見但不能覆蓋完整、當期的 factor-only 判斷。
- 選配 basket 中落後 expected US session 的成員不參與當期加權，避免用過期加值資料污染 current core signal。

## Known issues / risks

- Current branch 為 `codex/tw-etf-provider-normalization`，且 `tw_corporate_events.py`／其測試有無關在途修改；實作時必須維持 isolated diff。
- Yahoo FX 是 best-effort，沒有單一官方全球 FX holiday calendar；無法驗證的 closure 必須保留 `calendar_unverified`，不能假裝完整。
- 若現有 1d FX bars不足以做 ADR session alignment，可能需要 bounded backfill或清楚 partial fallback；不能靜默退回任意 latest spot。
- Legacy overnight GET 仍有 US daily refresh side effect；本任務只避免擴大並轉移 frontend owner，完整移除需另做 compatibility migration。
- Runtime canary 會產生一個明確 bounded provider/job side effect；只能在 M5 且 scope=`3711`、`max_symbols=1` 時執行。
- Job `#5304` 的 `max_symbols=1` 只容納 USD/TWD，ASX 8/7 對 expected 8/10 仍為 genuine stale；本輪不再送第二個 provider job，避免把 canary 變成重試迴圈。
- Optional basket warning 會把 confidence 從 high 降為 medium；這是刻意保留的資料限制，不應再呈現成整份「美股隔夜資料不足」。

## Next step

- 任務完成；若要提交版本，先以 path-scoped staging 排除既有 `tw_corporate_events.py` 與其測試的無關在途修改，再由使用者明確要求 commit/push。
