# Progress

## Status

- Current phase: complete
- Last updated: 2026-07-15 19:04 Asia/Taipei

## Completed

- 讀取 repo 與 frontend `AGENTS.md`、`docs/product/`、productized workflow 與 task-doc template。
- 確認 worktree 有韓股、加密、資源市場與共用 Frontend 的既有未提交變更；日股修改必須局部共存。
- 以 live API/SQLite 確認日股 freshness、coverage、AI contract 與 scheduler 基線。
- 建立本任務 Goal、non-goals、hard constraints、milestones、done criteria 與 stop-and-fix 規則。
- 建立日本交易日與 session contract：09:00–11:30、12:30–15:30、午休、盤後 release window、國定假日／振替休日／國民休日與 2025–2027 verified range。
- 將 JP source health、OHLC、watchlist ranking 與 scheduler 改為 backend expected trading date 判斷；舊 K 棒數量足夠不再阻止 bounded refresh。
- 新增 `GET /api/jp-market/overview`，提供日經、TOPIX ETF proxy、local breadth、sector breadth、top movers、active master/watchlist coverage、source health 與 partial warnings。
- 將 JP intraday 接入 AI／REST／MCP graded payload；只有明確盤中需求且 trust policy 允許時才做 bounded Yahoo fetch，stale 日線不再標成 current。
- Frontend JP market tape 加入盤中來源與時間、local coverage／breadth／sector overview、expected data date、午休／休市輪詢與 backend calendar fallback。
- 個股「今日」盤中分頁與更新狀態集中化保留並納入驗收；錯誤只由更新狀態入口呈現，freshness／provider／partial 仍在資料區可見。
- Resource disclosure 由永久 planned 改為 statement metadata 的 partial projection；margin／investor entitlement 缺口維持明確 empty／blocked 語意，未假裝成完整 TDnet。

## Validation evidence

- `GET /api/jp-market/intraday/8035.T`: 2026-07-15 Yahoo 1 分鐘盤中資料可用。
- Read-only SQLite: `^N225` 與 `1306.T` 最新日線為 2026-06-19，`8035.T` 為 2026-07-15。
- `GET /api/jp-market/source-health`: `freshness_policy.mode=availability_only`，明示日本休市日尚未建模。
- `GET /api/jp-market/watchlists/ranking`: 120 檔中 117 檔為 2026-07-15、`4384.T` 為 2026-05-28、`9613.T`/`9719.T` 無資料。
- Read-only SQLite: 4,456 檔 active master、120 檔 enabled watchlist、12 檔 fundamentals、0 檔 margin、0 筆 investor types。
- Runtime settings probe: `enable_scheduler=False`、`enable_jp_market_scheduler=False`。
- JP AI context probe: `^N225 as_of=2026-06-19` 仍被 evidence passport 判為 `data_freshness=current`；JP intraday slot 為 planned。
- Targeted backend/calendar/data/AI/MCP tests：89 passed；`backend/tests/test_jp_market_data.py`：39 passed。
- Safe backend validation：`compileall` 通過、完整 `backend/tests` 642 passed、`git diff --check` 通過；log 位於 `.tmp/validation/20260715-185052`。
- Frontend：`npm run lint -- --quiet`、`npm exec tsc -- --noEmit --incremental false`、`npm run build` 均通過；sandbox 內 build 的 child-process `EPERM` 已以核准的 unsandboxed build 重跑確認成功。
- Isolated backend `127.0.0.1:8428`：`GET /api/jp-market/overview` 200，`expected_trade_date=2026-07-15`、active stock denominator 3,925、current local daily coverage 117、breadth total 117、warnings 3。
- Isolated Frontend proxy：`GET /omi-data/jp-market/overview` 200，確認 proxy 使用本次新增 route 而非既有 8400 runtime。
- Browser smoke：日經與 TOPIX ETF 顯示 Yahoo 盤中 07/15 14:30、今日雷達資料日 2026-07-15、更新狀態集中在 sidebar 入口；最新 overview reload 被 Browser URL policy 阻擋，依規則未改用其他 browser surface 繞過。

## Decisions made

- 先完成 freshness/calendar/refresh truth，再做市場總覽與版面擴充。
- 先重用現有 US graded intraday contract pattern，避免建立 JP-only 外部介面。
- JP overview 的 breadth/sector 必須標示 local/watchlist coverage，不能宣稱全市場完整。
- 保留更新狀態集中化；freshness/provider/partial/missing 語意仍需在預期位置可見。

## Known issues / risks

- Yahoo 為 third-party/best-effort；J-Quants 部分 endpoint 受 plan entitlement 限制。
- Frontend 多個重疊檔案已有未提交變更，需在每次 patch 前讀取實際 diff。
- 全市場日股 daily coverage 尚不足，overview 目前明確標示 partial/local coverage；最新實測為 117/3,925。
- 日本 holiday fallback 僅將 2025–2027 標記為 verified；範圍外仍會計算規則，但 API 會揭露 verification limit，未宣稱永久官方完整。
- `1306.T` 是 TOPIX ETF proxy，不是正式 TOPIX 指數；UI/API 均保留 proxy 標示。
- 本機 `enable_scheduler=False`、`enable_jp_market_scheduler=False`，排程功能已具備交易日 guard，但若要自動每日更新仍需由使用者啟用 runtime 設定。

## Next step

- 產品功能已完成本輪範圍。下一個合理 milestone 是取得可授權的全市場日線／TOPIX／J-Quants margin 與 investor plan，將 partial coverage 升級，而不是在 UI 隱藏現有缺口。
