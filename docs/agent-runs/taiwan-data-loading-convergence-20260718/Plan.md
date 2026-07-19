# Plan

## Milestones

1. 固定基線、consumer map 與失敗模式
   - Scope：首頁 SSR、Taiwan tape、stock chart、data panel、ranking/Radar、selection/group refresh、provider events/source health。
   - Acceptance：
     - 列出所有會在 initial render、選股、切 tab、ranking 完成後觸發的 request 與 job。
     - 用 provider stub/fault injection 分別覆蓋 timeout、TLS、partial、空 cache、stale cache。
     - 保存 cold/warm latency、request count、payload size、job count 與 provider call count 基線。
     - 盤點既有 dirty worktree 的檔案 ownership，不覆蓋其他任務。
   - Validation：
     - `rg -n "indices/summary|ensure_history|selection-refresh|refresh-latest|rankings/latest-batch" frontend/src backend/app backend/tests frontend/e2e`
     - bounded direct/proxy probes 與既有 log/job evidence。

2. 建立 backend read/refresh contract
   - Scope：Taiwan index summary、OHLC/history、institutional/chips read service、refresh routers/jobs、source-health envelope。
   - Acceptance：
     - 定義 cache-only read 與 explicit refresh/job 的 additive contract。
     - Cache-only service 不呼叫 provider、不 commit、不排程 job。
     - Cache miss/stale 回傳可預測 status、資料日期、warnings 與可選 refresh action，不把缺口偽裝成空的 current data。
     - 保留既有 public response compatibility，或提供有測試的 migration/deprecation 路徑。
   - Validation：
     - targeted unit tests 以 mock/spy 證明 cache-only path 的 provider call count 與 commit count 為 0。
     - `backend/tests/test_api_contract_inventory.py`
     - `backend/tests/test_market_index_daily_stats.py`
     - OHLC、institutional、selection refresh 的新增 regression tests。

3. 首頁與個股資料改成 cache-first、非阻塞呈現
   - Scope：`frontend/src/app/page.tsx`、Taiwan market tape state、stock chart hook、Taiwan data panel、connection/freshness UI。
   - Acceptance：
     - 首頁 shell 不同步等待外部 provider-backed summary。
     - K 線與法人／籌碼先顯示 cache，refresh 狀態在 resource 層獨立更新。
     - Provider failure 不清空仍有效的 chart/table；warning 保留資料日期與 resource identity。
     - 選股與切 tab 不會因 effect 重複啟動相同 refresh。
   - Validation：
     - frontend lint、TypeScript typecheck。
     - Playwright route interception：index timeout、TDCC failure、partial chips、cache available。
     - request-count assertion：單次 initial render／選股／切 tab 的 API 與 mutation 次數。

4. 收斂 refresh job ownership 與 server-side dedupe
   - Scope：selection refresh、watchlist group refresh、jobs service/model、scheduler、frontend job polling。
   - Acceptance：
     - dedupe key 至少包含 market、resource/profile、target/group、expected trade date 與必要參數版本。
     - 並發／重送取得同一 active job 或明確 deduped result；completed-current job 在 policy window 內不重跑。
     - Component remount 不再是 dedupe 邊界。
     - 全群組 refresh 只由明確使用者操作、scheduler 或 freshness policy 觸發，不由 ranking load 完成自動觸發。
     - Job outcome 回報 refreshed/current/skipped/warning/error resource counts。
   - Validation：
     - job concurrency/idempotency tests。
     - `backend/tests/test_job_retry.py`
     - watchlist refresh targeted tests。
     - frontend E2E 跨 remount/reload request-count assertion。

5. Radar/ranking snapshot 與計算重用
   - Scope：watchlist ranking service、Radar service、既有 Radar automation/outcome persistence、frontend ranking loader。
   - Acceptance：
     - 先評估重用既有 persisted snapshot，不為了 cache 任意新增第二套真相。
     - Radar GET 可讀取符合 group/trade-date/params-version 的 snapshot；miss 時回傳明確狀態或啟動 bounded job。
     - 排行不再固定以 3 檔、約 28 次 serialized request 載入 83 檔；優先使用 bounded aggregate response、分頁或 server snapshot。
     - Radar snapshot freshness、calculated_at、input coverage 與 partial/error count 可見。
   - Validation：
     - `backend/tests/test_watchlist_ranking.py`
     - `backend/tests/test_watchlist_radar.py`
     - `backend/tests/test_watchlist_radar_automation.py`
     - 83 檔 cold/warm benchmark 與 frontend request-count smoke。

6. Provider resilience 與 source-health 精準化
   - Scope：TDCC shareholding transport、TPEx index endpoints、provider HTTP boundary、provider events、Taiwan source-health。
   - Acceptance：
     - TDCC 使用 scoped、可驗證的 TLS trust 解法，或改用經驗證的官方資料介面；不關閉全域 certificate verification。
     - TPEx transport failure 保留 exception category/cause，並採 bounded retry/backoff/circuit policy，避免每次 cold render 重打已知失敗來源。
     - Shareholding 等週資料有 expected-date/session-aware freshness，舊資料不只標成 `available`。
     - Composite chips refresh 將成功、stale、missing 與 provider failure 分 resource 回報。
   - Validation：
     - provider adapter unit tests 與 TLS/timeout fault injection。
     - `backend/tests/test_provider_http.py`
     - `backend/tests/test_provider_health.py`
     - `backend/tests/test_market_source_health.py`
     - bounded live TDCC/TPEx smoke；禁止全市場大量 refresh。

7. K 線資料 invariant 與 reload 收斂
   - Scope：Taiwan OHLC projection、intraday overlay、Lightweight Charts adapter、chart reload trigger。
   - Acceptance：
     - Backend contract 在輸出前正規化 timestamp order/uniqueness，並記錄 dropped/merged anomaly。
     - Frontend adapter 在第三方 chart boundary 做 defensive validation，不讓單一 malformed point crash 整張圖。
     - Basic/chips refresh 只在相關 price resource 真正更新後觸發一次 chart reload。
   - Validation：
     - duplicate/out-of-order/empty payload regression。
     - `backend/tests/test_ohlc_intraday_overlay.py`
     - chart frontend unit/E2E smoke，確認 daily/weekly/intraday 切換不拋 assertion。

8. 跨邊界驗證與交付
   - Scope：backend、frontend、jobs、provider telemetry、live runtime、task docs。
   - Acceptance：
     - Provider 故障時的 UI、API、job、source-health 與 log 行為一致。
     - Done criteria 的 latency、request count、job dedupe 與 chart invariant 全部有證據。
     - 無 DB destructive operation、無 secrets、無 unrelated refactor。
     - `Progress.md` 完整記錄 before/after、known issues 與 deferred work。
   - Validation：
     - `.\scripts\run-safe-validation.ps1 -Profile backend`
     - frontend lint、TypeScript；依實際 UI 變更再執行 build 與 bounded E2E。
     - direct backend、frontend proxy、browser workbench smoke。
     - `git diff --check`。

## Work packages

- Package A：read/refresh contract 與 fault-injection tests。
- Package B：首頁、K 線、法人／籌碼 cache-first UX。
- Package C：refresh dedupe 與全群組 job ownership。
- Package D：Radar/ranking snapshot 與 request 收斂。
- Package E：TDCC／TPEx provider resilience 與 source-health。
- Package F：chart invariant、全套 regression 與 runtime benchmark。

每個 package 都應可獨立驗證與回退。不要同時重寫所有 frontend hooks、backend services 與 job schema。

## Stop-and-fix rules

- 若 cache-first 使 stale、partial、missing 或 provider failure 不可見，立即停止並修正。
- 若 GET/read path 仍會外呼 provider、commit 或隱性建立 job，視為 read/refresh contract 未完成。
- 若 dedupe 會錯誤合併不同 target、trade date、profile 或參數版本，停止上線並修正 key contract。
- 若 job retry 可能重複寫入、重複 provider quota 或污染 transaction，先修正 idempotency。
- 若 Radar snapshot 日期或 params version 不符仍被當成 current，停止並修正 freshness 判定。
- 若 TDCC 解法需要 `verify=False` 或全域信任未知憑證，拒絕該方案並改用 scoped trust/official endpoint。
- 若 migration 不可驗證、會覆蓋現有 SQLite 或破壞舊資料，暫停並要求確認。
- 若 current dirty worktree 的既有修改與某個 package ownership 衝突，先釐清 diff，不 revert 或覆寫。
- 每個 milestone 的 targeted validation 失敗時先修正，不把問題累積到 full validation。

## Decisions

- 2026-07-18：建立獨立 `taiwan-data-loading-convergence-20260718`，不擴張已完成的 frontend/backend connectivity stability 任務。
- 2026-07-18：以 read/refresh 解耦為主因修復，不以延長 20 秒 timeout 當解法。
- 2026-07-18：台股先行；其他市場只在共用 helper/contract 不產生額外風險時受益。
- 2026-07-18：先顯示 cache 與 freshness，再背景刷新；provider failure 必須是 degraded state，不得阻塞整個研究工作台。
- 2026-07-18：優先重用既有 Radar automation/outcome persistence，確認不足後才考慮 migration。
- 2026-07-18：基線確認後依使用者指示直接完成 Milestone 1-8；以既有 Radar snapshot schema、additive cache contract與explicit refresh job完成，不新增第二套 snapshot table。
- 2026-07-18：TDCC採 host-scoped verified TLS adapter；保留certificate與hostname驗證，只移除該官方站在目前OpenSSL環境不相容的strict chain flag。
- 2026-07-18：TPEX OpenAPI確認為相同`Missing Subject Key Identifier`；在共用HTTP client只對`https://www.tpex.org.tw/`套用相同verified compatibility policy，完整breadth恢復後不再使用failed fallback。
- 2026-07-18：Browser視覺驗證因使用者正在操作電腦而延後；本輪以localhost HTTP、runtime log、targeted regression、lint、typecheck與production build作為交付證據。
