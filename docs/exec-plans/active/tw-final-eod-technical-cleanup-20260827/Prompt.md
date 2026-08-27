# 台股 EOD 與 Technical 最終收斂

## 目標

- 讓 TWSE／TPEx 同日 official daily OHLCV 透過既有 `daily_ohlcv_platform`、Canonical Observation、transaction 與 Resolver 集中管理。
- 保留 `session_close` 與 official EOD 的分權，完成後由 official daily 接手 K 線、official close 與 finalized technical。
- 根除前端 unknown volume unit、canonical indicator silent fallback，以及 finalized／provisional 混顯。

## 非目標

- 不重做 Taiwan Data Core、close-resolution 或 session-close lifecycle。
- 不新增第三套 EOD scheduler、資料表或 consumer-owned market logic。
- 不把 provisional session bar 寫成 official daily。
- 本輪不自行重啟正式 runtime、不 commit、不 push。

## 硬性限制

- `TAIWAN_DAILY_PRICE_RELEASE_TIME` 保持 official dataset release 語意，不改成 13:30。
- Provider resource 只產生 canonical observation；既有 platform／transaction／Resolver 保持 owner。
- Frontend 對 backend-authoritative canonical indicator fail closed；只有 presentation-only indicator 可本機計算。
- Unknown volume unit 不得預設除以 1000。
- 保留 dirty worktree 內其他 TW／US 既有變更。

## 背景

- Repo：`C:\project\Open Market Intelligence`
- 2026-08-27 23:16 runtime checkpoint：TPEx 已同日，TWSE `STOCK_DAY_ALL` 仍只提供 2026-08-26，導致全市場 coverage partial。
- 2026-08-27 23:35 對 TWSE 官方 `MI_INDEX?type=ALLBUT0999` 的 bounded read 顯示同日 2026-08-27、1377 列，3711 為 O/H/L/C 608/608/593/605、volume 11,658,860 shares。
- 現有 `backend/app/market/indices.py` 已使用相同 `MI_INDEX` resource 做 full-market breadth；本任務把個股 OHLCV 接回既有 official daily owner，不建立平行服務。

## 交付物

- TWSE RWD MI_INDEX official daily resource descriptor、parser、acquisition 與既有 transaction／Resolver 整合。
- EOD job 透過 market-owned venue refresher 執行，coverage postcondition 保持唯一成功 gate。
- EOD scheduler 固定 enqueue 當下的 expected trade date；已發布的前一交易日 catch-up 不再被次日 15:15 guard 阻塞。
- Release guard deferred 到期後重新評估 eligibility；provider rate-limit／error backoff 不得被繞過。
- All-market `market_daily_price` health 讀取 full-market coverage checkpoint，避免跨 venue `max(date)` 假 current。
- Full-market official daily route 的 typed bound 與實際 TWSE／TPEx active universe 一致，不得在 acquisition 前被 500-symbol schema 截斷。
- 「今日」intraday range 使用既有 Taiwan presentation session 的 trade date；跨午夜至 08:00 前仍讀前一個展示交易日。
- `session_close` finalization 與 current market session 正交；合法 13:30 final match 在 13:33 確認後可跨午夜保留，不要求目前 session 仍是 post-close。
- Header price／change／change_pct 必須來自同一個 current 或 completed-session evidence，禁止缺價格時混用另一 session 的漲跌。
- 普通／專業 K 線 volume 與 canonical indicator authority 收尾。
- Technical finalized／provisional 明確分區。
- Targeted backend regression、frontend lint/type/build 與 architecture guard 證據。

## 完成條件

- Recorded MI_INDEX fixture 可 parse、atomic persist、Resolver reread，3711 official row 值正確。
- TW EOD reconciliation 優先使用同日 MI_INDEX，失敗才依既有 planner 嘗試下一個 official resource。
- Partial coverage 仍是 partial，job 不因 transport success 假成功。
- 2026-08-28 00:13／10:00 對 2026-08-27 的 pinned EOD repair 可立即進入既有 venue refresher；15:15 後 queued job 仍不得漂移成 2026-08-28。
- `session_close` 在 official release 前顯示 pending；release 已到但 canonical daily 缺失時顯示 unavailable-after-release。
- 3711 等任意 active instrument 的 full-market route 保留完整 universe size，且 transaction／coverage success gate 不變。
- 2026-08-28 08:00 前查詢「今日」仍可讀 2026-08-27 intraday cache；08:00 起才切換 2026-08-28 presentation trade date。
- 合法 previous-session final match 可投影為 `session_final`，stale／trial／date mismatch／volume regression 仍不得升格。
- 「今日」沒有 price 時 header 的 change 與 change_pct 同時為 unavailable；有 605／previous close 592 時三者一致。
- Backend indicator 缺值或 parameter mismatch 時，TW daily UI 顯示 unavailable，不本機重算 canonical 值。
- Decision state 與 current observation 不再組成同一個標題／摘要。
- Targeted validation 全綠；runtime／live adoption 留待使用者另行授權重啟後驗收。

## 假設

- TWSE `MI_INDEX` 的 `ALLBUT0999` 表為官方同日 completed-session resource；item eligibility 仍由 active ordinary-stock universe 與 coverage checkpoint判定。
- 官方資料與 session-close 不一致時，official daily 依既有 authority 勝出，差異保留在 reconciliation／warning surface。
