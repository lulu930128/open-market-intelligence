# 進度

## 狀態

- Current phase: completed
- Last updated: 2026-07-15 15:30 Asia/Taipei

## 已完成

- 追查 Naver index page 與 realtime payload，確認 page `volume` 是分鐘區間量、`cumulative_volume` 與 realtime `aq` 是當日累計量。
- 後端以 Seoul 分鐘作 canonical key，將 realtime 累計量差分成區間量，同分鐘輪詢改為覆寫而不是 append。
- intraday API 新增 `as_of`、`total_volume`、volume/trade-value unit 與 semantics、`is_partial`，並保留既有欄位相容性。
- `refresh=true` 改為保留同交易日 cache、只抓第一頁增量；新增 `reload_all=true` 作為明確完整重建。
- 首頁可讀取 Naver 宣告的 last page，使用最多 6 workers 的 bounded parallel fetch；單頁失敗會回 warning 與 partial，不隱藏缺口。
- partial cache 會在下一次刷新自動嘗試完整恢復。
- 前端韓股指數不再先發出必然 404 的 stock lookup；成交量顯示改為「千股」與 provider total；來源顯示 Naver 韓國指數分時。
- reveal key 不再包含 point count，避免每次 polling 都重播 1.44 秒動畫。

## 驗證證據

- 舊 runtime baseline：415 points 只有 356 個唯一分鐘；最新 `volume=355816` 被當區間量，前端加總為 19,338,237。
- 新後端完整 63 頁：7.564 秒（舊串行約 28.943 秒），375/375 唯一分鐘，`volume_sum=total_volume=373756`，無 warning、非 partial。
- 新後端 cache 增量刷新：1.266 秒，只抓 1 頁，`volume_sum=total_volume=381972`，無 warning、非 partial。
- 瀏覽器實測：API `total_volume=381972`、區間量加總 381972、畫面顯示 381,972；單位為「成交量(千股)」，來源為 Naver 韓國指數分時。
- 瀏覽器頁面有內容、無 Next error overlay、無 console error、無持續 loading。
- `run-safe-validation.ps1 -Profile backend -BackendPytestArgs @('backend\tests\test_kr_market_data.py')`：compileall、20 tests、global `git diff --check` 全部通過。
- `npm exec tsc -- --noEmit --incremental false`、`npm run lint`、`npm run build` 通過。

## 韓股整體掃描

- `source-health` 約 70 ms；symbol master 65 檔，Yahoo 日線 16,373 rows 且已到 2026-07-15。
- watchlist ranking 約 48 ms；65 檔中 63 檔為當日，2 檔較舊。
- 三個 index daily summary 仍全部 stale：KOSPI 2026-07-07，KOSDAQ/KOSPI200 2026-07-06；summary 約 9 ms，但資料新鮮度不足。
- KOSPI breadth 約 3 ms，但為 partial 且沒有可用 advance/decline counts。
- KRX daily、investor trading、OpenDART financials 仍為 empty；readiness 因此只能是 partial。

## 已知問題 / 後續建議

- 冷啟動完整分時仍需約 7.6 秒；下一階段應考慮持久化 intraday cache 或明確的 quick-first/full-later contract，不應讓 GET 暗中啟動無界 backfill。
- index summary 應新增可快取的 realtime overlay 或 batch quote contract，避免頂部市場卡片與今日分時互相矛盾。
- source-health 應補 index daily/intraday/realtime 三種資源，而不只 stock resources。
- breadth、investor trading、financials 應各自建立 bounded refresh 與缺口狀態；本次沒有自動大量回補或消耗外部 quota。
- 目前 8400/3000 runtime 未重啟。worktree 同時有其他未提交變更，直接重啟會把不屬於本任務的修改一起帶入 runtime，因此保留給使用者在確認整體 worktree 後重啟。
