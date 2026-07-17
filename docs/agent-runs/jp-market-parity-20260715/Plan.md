# Plan

## Milestones

1. 基線與契約盤點
   - Scope: 讀取產品文件、JP/TW backend/frontend call chain、API schema、scheduler、DB coverage、現有 tests 與 dirty worktree diff。
   - Acceptance: 任務範圍、不可動區域、現況資料實證與風險寫入 `Prompt.md`／`Progress.md`。
   - Validation: read-only API/DB probes、`git status --short`、targeted source search。

2. 日本交易日、freshness 與更新可靠性
   - Scope: JP trading calendar、calendar-status、expected daily date、source health、index refresh、watchlist target date、symbol lifecycle 與 scheduler guard。
   - Acceptance: current/stale/holiday/partial 能以官方或明確 fallback 規則判斷；舊資料數量足夠不再阻止更新；失效標的不造成永久全組刷新。
   - Validation: `backend/tests/test_jp_market_data.py` 與 calendar/scheduler targeted tests、API source-health/ohlc/ranking smoke。

3. JP intraday 進入 AI／REST／MCP contract
   - Scope: `market_data_params.include_intraday`、payload levels、JP context projection、Ask routing、MCP schema、evidence passport 與 JP-specific decision limitations。
   - Acceptance: 明確盤中需求才做 bounded fetch；data-only/brief 及 MCP consumer 取得一致 slot/as-of/freshness；stale 日線不得標成 current。
   - Validation: JP AI context、AI ask stages、market-context projection、MCP payload regression。

4. 日股市場總覽與台股式資訊架構
   - Scope: JP overview endpoint、index/proxy contract、local/watchlist breadth、sector strength、coverage/source health；Frontend tape、ranking、detail 與 market overview 對齊台股節奏。
   - Acceptance: 使用者能從市場層進入群組/個股層，看到日經、TOPIX context、廣度、產業、資料日期與 coverage，不重複控制或錯誤框。
   - Validation: backend overview tests、Frontend lint/typecheck/build、Playwright/browser screenshot。

5. Resource coverage 與標的生命週期
   - Scope: fundamentals、margin interest、investor types、earnings disclosure projection、provider entitlement、inactive/delisted/renamed symbol handling、source events。
   - Acceptance: 每個 slot 回傳 available/partial/empty/blocked/planned/stale 與可解釋原因；無法取得時不污染 DB、不反覆無效 refresh。
   - Validation: provider parser/service tests、resource/source-health API smoke、failure-path tests。

6. 分鐘資料保存與最終驗證
   - Scope: 視前述 contract 決定是否加入 bounded JP intraday persistence/retention；完成 docs、regression、runtime/browser 驗證。
   - Acceptance: AI/overview/radar 可重用保存資料或明確維持 ephemeral 限制；所有 required validation 有可追蹤結果。
   - Validation: safe backend/frontend profiles、migration tests、API smoke、browser screenshot、`git diff --check`。

## Completion status

- Milestone 1：completed。
- Milestone 2：completed；日本交易日、午休、盤後與 expected trading date 已進入 backend contract。
- Milestone 3：completed；JP intraday 已使用既有 graded/bounded AI／MCP contract，並保留 trust policy gate。
- Milestone 4：completed；新增 JP overview，Frontend market tape／overview／ranking／detail 依台股資訊層級整理。
- Milestone 5：completed within provider limits；fundamentals／margin／investor／disclosure 均回傳可解釋 coverage/status，不把 entitlement 缺口偽裝成完整資料。
- Milestone 6：completed；本輪刻意維持 intraday 60 秒 ephemeral cache，未新增不必要的 DB schema；完整 backend regression、Frontend lint/typecheck/build、API/proxy smoke 已通過。Browser 已驗證盤中 market tape、今日雷達與更新狀態集中化；最新 overview reload 受 Browser URL policy 阻擋，未使用替代瀏覽器手段繞過。

## Stop-and-fix rules

- 任一 freshness 測試出現 stale 被標成 current，立即停止後續 UI 擴充並修正 backend contract。
- 任一 GET/read path 產生無界外部回補、長時間 job 或大量 quota，立即改成 bounded refresh／job。
- 任一 Frontend 需要自行推算交易日、provider truth 或 slot completeness，先補 backend contract，不在 UI 複製規則。
- 任一 DB schema 需求未有 migration 或會覆寫既有資料，停止並重新設計。
- 任一重疊檔案會覆蓋韓股、加密或使用者既有變更，縮小 patch 或拆出新 module。
- 任一 provider 只有脆弱 scraping、授權不明或 entitlement 不足，保留 blocked/partial，不假裝完成。
- 每個 milestone 的 targeted test 先通過再進入下一階段；失敗與本次無關時必須有證據隔離。

## Decisions

- 以 backend expected trading date 為唯一 freshness truth，Frontend 不再只用 weekday 判定日本交易日。
- 日股版面參照台股的資訊層級與操作節奏，不直接複製台股特有資料名稱或交易規則。
- `1306.T` 永遠標示為 TOPIX ETF proxy；取得正式 TOPIX 前不冒充官方指數。
- 市場廣度先以 local/watchlist coverage 提供可用結果，必須同時回傳 numerator、denominator、coverage scope 與 partial 狀態。
- JP intraday 採 graded/bounded payload；只有盤中 intent 或明確 `include_intraday=true` 才拉取。
