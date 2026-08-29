# Progress

## Status

- Current phase: source and validation complete; local main integration authorized
- Last updated: 2026-08-29 Asia/Taipei

## Completed

- 建立 `codex/tw-frontend-performance-convergence` isolated worktree at `f8085f5`。
- 確認 target backend/TW frontend files 在原始 dirty worktree沒有未提交變更。
- 重現 health green、summary/home read slow 的 runtime split。
- 定位 full `RawFetchResult.raw_text` hydration 與 frontend state ownership 問題。
- Current index、current breadth、official daily candidate read 改為只載入 lineage 欄位，不再 hydrate `raw_text`。
- 加入 emitted-SQL regression assertions，防止 `raw_text` 回流 cache-only SELECT。
- 有 SSR initial summary 時不再 hydration 後立刻重打 summary API。
- 將 500ms quote-stream state 下移到 `TaiwanQuoteDepthSurface`，避免整個 `StockDetailPanel` 跟著即時 tick re-render。
- SSE failure 保留 fallback polling，並以 5/15/30 秒 capped backoff 重連；hidden/pagehide 停止 transport，visible/pageshow 恢復。
- 完成 Round 2 read-only audit：確認 intraday raw receipt hydration、viewer automatic POST、projection TTL/polling conflict、previous-close coupling、daily 2,600-bar load、SSR duplicate load 與 chart dependency retrigger。
- 確認正式 runtime 來自原始 dirty checkout而非隔離 worktree；provider-lineage OHLC 400 保留為獨立 integration gate，不帶入原始 dirty diff。
- Intraday candidate repository 只載入 raw lineage 欄位；emitted SQL negative assertion 防止 `raw_text` 回流。
- Intraday projection cache TTL 由 4.75 秒調整為 12 秒，與 5 秒 viewer polling 對齊但不改寫 canonical freshness。
- `previous_close` 改由 prior completed-session canonical daily evidence 補入；current quote stale／missing 不再抹除前收。
- 今日走勢、日 K automatic stale retry、quote depth baseline 與資料分頁 mount 全部改為 GET-only；provider refresh／backfill 只保留明確使用者操作，realtime viewer lease 仍由既有 backend capability 管理。
- 日 K 初始深度由 2,600 降至 260 根，indicator 使用 240 根；OHLC 與 indicator 平行讀取，valid SSR daily payload 只消費一次，stock-info resolution 不再重啟 chart effect。
- Production DB 唯讀 query plan 顯示 intraday 主查詢使用單欄 `interval` index並建立 temporary B-tree；新增 `20260829_0073t` additive composite read-index migration source與 downgrade test，避開平行 US workline 的未提交 `0073`，但未套用正式 DB。
- Quote depth realtime fixture 補齊 presentation-only contract flags，provider label 統一為 `KGI SUPER PY`，E2E 明示 `PRESENTATION STREAM`。
- Today 與 daily/indicator 改為帶 `stockId` 的 atomic state envelope；selection 改變時 current-only selector 立即隔離舊 symbol，不等待 effect 清空。
- Header、漲跌幅、MA fallback 與 technical report 改讀 timeframe/current-symbol gated data；today 只明確使用同 symbol 的 daily reference。
- SSR 保留 `initialOhlc.stock_id`，只有 identity 相符才重用 initial daily payload；intraday、OHLC 與 professional history response identity 不符時拒絕 adopt。
- 新增 loaded-state today pending、daily mismatched identity/error regression，並補強既有 stale-response test 的明確 group/stock 前置條件。
- Quote Depth 的「即時成交」與「試撮」固定共用左側五檔版型；即時 bid／ask 缺值時保留每側五列並顯示 `-` 與明確缺值狀態，不再退回 Open／High／Low／Volume 卡片，也不以試撮快照代填即時資料。

## Validation evidence

- `/api/market/indices/summary`: 12.9-15.5 seconds before changes, HTTP 200, canonical cache payload present.
- `/`: 15.8 seconds before changes, HTTP 200, approximately 531 KB response.
- Read-only profile: current TWSE breadth about 2.35 seconds; official TWSE breadth about 1.98 seconds.
- Patched direct `get_market_index_summary()` against the same 31.26 GB database: 841.1 ms, `canonical_cache`, 2 indices.
- Projection-only SQL probes: current index 25.2 ms / 16 rows; current breadth 300.1 ms / 16 rows; official daily 17.4 ms / 1,972 rows.
- Final targeted backend regression: 103 passed in 13.44 seconds；migration 使用 task-owned temporary SQLite，production DB 未變更。
- Python AST parse: 4 changed backend/test files OK.
- Frontend TypeScript: `tsc --noEmit --incremental false` passed.
- Targeted ESLint: all changed frontend／E2E files passed.
- Production build: `next build --webpack` passed after final source changes；Turbopack cannot follow the temporary out-of-root `node_modules` junction used by this isolated worktree.
- Browser smoke: TW dashboard rendered canonical cache values; no console errors/warnings; no hydration-time `indices/summary` resource request; stock detail rendered two `即時成交` surfaces without console errors.
- Browser regression: 6／6 quote-depth／SSE／replay／rapid-switch cases passed；today viewer、ETF tab 與 stale stock-switch GET-only cases passed individually。
- Cross-symbol production-standalone fixture-only browser acceptance: 5／5 passed（GET-only today viewer、late old response、loaded today pending、daily wrong-identity rejection、quote-depth rapid switch）。
- Cross-symbol frontend validation: targeted ESLint passed with zero warnings；TypeScript passed；Next 16.2.12 production webpack build passed；`git diff --check` passed。
- Quote Depth fixed-book frontend validation: targeted ESLint 與 TypeScript passed；Next 16.2.12 production webpack build passed；production-standalone Quote Depth browser regression 7／7 passed，涵蓋即時成交、試撮 replay、stream-first、GET failure、無 depth placeholder、rapid switch 與 auction details；另以單一切換情境明確驗證「即時成交 → 試撮 → 即時成交」三段左欄都維持委買五列加委賣五列。
- Production DB read-only intraday probe (`3711`): 266 points, source `nstock_minute_stock_data`, `previous_close=605`, no usable current trade；cold 904.90 ms，warm cache hit 2.64 ms，payload identical。
- SQL timing probe: 15 SELECTs／872.29 ms total；`market_intraday_bar` query 652.98 ms。SQLite plan used `ix_market_intraday_bar_interval` plus temporary B-tree，證實剩餘 cold-read index gap。

## Decisions made

- 先修 repository projection，再做 React boundary，避免 frontend 優化被 backend read latency 掩蓋。
- 不新增 global polling manager，不改 backend-owned market truth。
- 保留 quote-depth lease/depth/replay ownership；只把 high-frequency stream state 隔離到實際消費元件。
- 不 restart 正式 runtime、不套用 production DB migration、不 commit／push。
- 2026-08-29 使用者另行授權建立 task commit、合併到本機 `main` 並移除 worktree；仍不授權 push、production DB migration adoption 或正式 runtime restart。

## Known issues / risks

- 現有正式 runtime 仍載入原 worktree；browser 首屏仍受舊 backend 12-15 秒 summary latency 影響，不能當作 patched runtime acceptance。
- Migration `0073t` 尚未套用 31 GB production DB；建立 index 可能需要維護時窗並帶來 SQLite write lock／額外磁碟占用，且與平行 US head 合併時需要明確 merge revision，必須在 runtime adoption 階段另行量測與批准。
- 原始 dirty checkout 的 provider-lineage guard 仍讓代表性 daily OHLC 回 HTTP 400；這是正式整合 gate，不能以前端 fallback 繞過。
- React Profiler commit-count before／after 尚未取得；500 ms quote surface ownership 已隔離，5 秒 dashboard tape／radar boundary 未在沒有 profiler 證據時擴大重構。
- Production E2E 的 SSR backend 被刻意指向不可達 endpoint，因此 valid-SSR OHLC reuse 目前只有 source gate與 build 證據，尚未取得 live SSR network acceptance。
- Indicator endpoint 目前仍是無 stock envelope 的 array；本輪在已驗證 OHLC request identity 後與同次 request stockId 原子封裝，未改 backend outward contract。若未來 endpoint 增加 identity envelope，應再升級為 payload hard check。

## Next step

- 合併到本機 `main` 後，production DB migration、provider-lineage canonical guard 與正式 launcher runtime／live／visible-UI acceptance 仍需分別安排；本次 closure 不執行這些 adoption gate。
