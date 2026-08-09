# 台股盤前至盤中交界與正式 Runtime 後續收斂

## Goal

- 建立一個由 backend 擁有、可由 deterministic tests 與正式交易時段共同驗證的台股盤前至盤中交界契約。
- 在台股交易日 08:00（Asia/Taipei）把 OMI 的工作區／輸出 session date 切換為當日；08:00～08:29 的當日價格、成交量與漲跌資料維持 unavailable，Frontend 統一顯示 `"-"`，不得沿用昨日數值冒充今日行情。
- 將「市場時鐘」、「個股交易階段」與「觀測值語意」分離，避免 09:00 時鐘邊界直接把試撮價升級成正式成交價，或過早讓 auction capability 退場。
- 保留同一交易日已確認的最後實際成交狀態，使 TWSE MIS 單次 snapshot 的 `z="-"` 不會讓 OMI 遺失已知 last trade；同時不得以 `pz`、買賣價、OHLC 或累積量猜測缺少的 last trade price。
- 修正 quote replay 與 capture matrix，使 persisted evidence 能忠實重現 capture 當下的 `pz/ps/ts`、actual-trade、freshness 與 source-error 語意，並可驗證 09:00～09:02 handoff。
- 收斂正式 runtime 工程稿中既有的 A～E 問題：persisted intraday cache fallback、非決策 payload、negation diagnostics、canonical freshness aggregate 與 source-health historical-event 語意。
- 維持 `omi.decision.v4`、REST、repo MCP、Frontend 與外部 consumer 的相容性；consumer 只呈現 backend contract，不自行重做市場 session 或 freshness 判斷。

## Non-goals

- 不改變 OMI「台股核心、其他市場為 context layer」的產品定位。
- 不做自動交易、下單或把試撮資料包裝成可執行交易訊號。
- 不重寫整套台股 breadth v2、market indices、1 分 K continuity、TXF 或 AI decision architecture。
- 不將 provider raw semantics 放進 Frontend、MCP adapter 或 `trading_calendar.py`。
- 不為了觀察 delayed open 無限制掃描全市場；若正式驗收時自然未發生，維持 `not observed`。
- 不在 GET/read path 加入全市場 backfill、隱性 provider I/O、報告、LLM、dispatch 或 AI memory 寫入。
- 預設不新增 DB migration；只有現有 `TaiwanStockQuoteSnapshot`、`TaiwanQuoteContractSnapshot` 與既有 intraday tables 無法安全表達契約時，才停止施工並重新提案。
- 不做無關 refactor、dependency upgrade、格式化-only diff、commit、push 或發布。

## Hard constraints

- 使用者確認本計畫前，只能修改本任務文件；不得修改程式、DB、runtime、public snapshot 或排程。
- 08:00 rollover 只適用於台股交易日，且是今日 workspace/session context 的切換，不是 TWSE 已開放委託、已有試撮或 provider 已有當日行情的宣告；週末與休市日不得切成今日交易 session。
- Backend 的當日價格、成交量與漲跌等 machine-readable 欄位必須維持 `null`／unavailable，由 Frontend 顯示 `"-"`；不得把字串 `"-"` 寫入 numeric contract，也不得用 `0` 代表尚無資料。
- 昨日收盤如需保留，只能標成 previous-session reference，帶原交易日與 `price_as_of`，不得出現在今日即時價欄位。
- 不得只為了 08:00 日期切換而呼叫 TWSE MIS、建立 provider event 或把舊 snapshot 的 receipt time 更新成今天；已開啟的 Frontend 若需準點更新，只能做 bounded backend refetch。
- `pz/ps/ts` 只能代表 auction indicative evidence；不得填入 `last_trade_price`、actual-trade breadth、entry price 或 execution-grade decision。
- `market_calendar_phase=regular` 不代表個股已成交；09:00 後仍須容許 `opening_auction_delayed`、`awaiting_first_trade` 或 `regular_traded`。
- `current_for_requested_session=true` 只代表 session alignment，不得隱含 complete、actual trade 或 action usability。
- `facts_usable`、`intraday_research_usable`、`execution_grade_usable` 與 price-level `decision_usable` 必須是不同軸。
- same-session actual-trade cache 必須保留原 `price_as_of` 與 source；snapshot 的 receipt time 不得冒充成交時間。
- `v>0`、O/H/L 或 order book 可證明部分市場事實，但沒有 `z` 或已確認 same-session price cache 時，不得生成 last trade price。
- market clock owner 留在 `backend/app/market/trading_calendar.py`；provider observation 與個股 state owner 留在 market service／pure contract；AI 只消費 canonical contract。
- public field 若需新增，採 additive change；移除或改義既有 field 前必須完成 consumer inventory 與相容方案。
- `allow_external_fetch=false` 時，provider mock、provider event 與 telemetry 都必須證明沒有對外 fetch；若允許 cache fallback，可讀 persisted rows。
- 所有 stale、partial、missing、cached、provider failure、fallback 與 scope limitation 必須保持可見。
- 正式 DB 不得刪除、重建、覆蓋或 vacuum；任何 migration 提案需另做 offline backup、copy dry-run、integrity 與 rollback 計畫。
- dirty worktree 內既有變更視為使用者或其他工作成果；每個施工包使用明確檔案清單，不回復、不混入無關 diff。

## Context

- Repo: `C:\project\Open Market Intelligence`
- Branch: `main`
- Baseline date: `2026-08-05`（Asia/Taipei）
- Related systems: Taiwan market service、AI decision contract、SQLite、scheduler、REST、repo MCP、Frontend types、official launcher runtime。
- User engineering draft: `C:\Users\thoma\Downloads\OMI_正式Runtime後續施工計畫_20260805.txt`
- Prior task: `docs/agent-runs/tw-preopen-intraday-contract-convergence-20260804/`
- Public contract: `omi.decision.v4`
- Baseline digest: `3c03b3a51b72854b90b58c7b778d9ba519ae1565e7c15f74c4745166df14f6aa`
- Formal backend: `http://127.0.0.1:8400`
- 2026-08-05 planning inspection observed 72 dirty worktree entries; implementation must remain localized.

### Official market-time baseline

- TWSE regular-order entry: 08:30～13:30.
- Pre-open simulated information: 08:30～09:00.
- Regular trading: 09:00～13:30; opening and closing use call auction, intraday uses continuous trading.
- An individual security may be delayed two minutes at the open and match around 09:02 when the official volatility condition is triggered.
- Closing simulated information: 13:25～13:30; an individual delayed close may continue to approximately 13:33.
- Primary reference: <https://www.twse.com.tw/zh/products/system/trading.html?hl=zh-TW>
- OMI 08:00 rollover 是產品端的交易日準備邊界，早於 TWSE 08:30 的正式盤前委託／試撮時段；兩者必須保持不同語意。

### Confirmed 2026-08-05 runtime evidence

- `/api/system/health` and `/api/ai/tools` returned HTTP 200; live public tools contain the baseline digest and `omi.decision.v4`.
- `GET /api/market/quote-depth/2330/replay?trade_date=2026-08-05` returned 13/13 captured slots with `read_path_side_effects=false`.
- Persisted raw public quote payload at 08:50: `pz=2385`、`ps=1168`、`ts=1`、`z="-"`; preopen indicative evidence was current while actual trade was unavailable.
- Persisted raw public quote payload at 08:59: `pz=2385`、`ps=1935`、`ts=1`、`z="-"`.
- The 09:00 capture was requested at `09:00:00`, but provider event time was `08:59:55`; raw payload still had `pz=2385`、`ps=2113`、`ts=1`、`z="-"`、`v=0`.
- Current clock-only projection labeled that 09:00 sample `regular_live + live_depth_only` and removed auction indicative evidence. This is a confirmed boundary defect.
- At 09:05, raw payload had `z="-"`、`v=3141` plus current-day O/H/L. Actual trades had occurred, but the current quote contract exposed no last trade.
- At 13:24, raw payload again had `z="-"` with cumulative volume `27545`, confirming that `z` is not guaranteed in every snapshot after trading has begun.
- At 13:28, raw payload had closing-auction `pz=2410`、`ps=3815`、`ts=1`; the persisted capture correctly separated it from official close.
- At 13:30, the provider response had a JSON parse failure and cache fallback; 13:32 remained official-close pending; 13:34 confirmed official close `2405`.
- The replay API currently removes persisted indicative fields for TWSE replay while retaining semantics such as `preopen_indicative_match_and_depth`; this makes replay internally contradictory.
- `taiwan_market_minute_state` on 2026-08-05 correctly kept 08:55～08:59 cumulative trade value null, then switched to explicit intraday estimates from 09:00. The prior preopen trade-value quarantine is functioning and should not be rewritten.

## Target contract

The implementation should preserve existing compatible fields while establishing the following canonical axes, either as additive outward fields or as an internal canonical object projected into existing fields after consumer inventory:

```text
presentation_session
  trade_date: latest completed session before 08:00
  trade_date: today from 08:00 on a Taiwan trading day
  state: previous_session | today_pending | observing | completed

market_calendar_phase
  preopen_pending | preopen | regular | closing_auction | post_close | market_closed

instrument_phase
  preopen_auction
  opening_auction_delayed
  awaiting_first_trade
  regular_traded
  closing_auction
  closing_auction_delayed
  closed

observation_semantics
  auction_indicative
  live_depth_only
  actual_trade
  cached_actual_trade
  current_interval_bar
  official_close_pending
  official_close
```

Minimum invariants:

```text
trading_day && 08:00 <= request_now < 08:30 => presentation_session.trade_date is today
trading_day && 08:00 <= request_now < 08:30 => current-session price/volume/change values are null and UI renders "-"
non_trading_day => no 08:00 today-session rollover
previous_session_reference != current_session_market_fact
auction_indicative => actual_trade.price is null
auction_indicative => execution_grade_usable is false
actual_trade.price != null => source is z or a validated same-session canonical source
cached_actual_trade => price_as_of remains the original trade time
request_now >= 09:00 alone != auction not_applicable
v > 0 without a known price => trade occurred but last_trade_price is unavailable
replay public semantics == persisted captured public semantics
```

## Deliverables

- A pure, shared TWSE MIS observation resolver or equivalent canonical owner used by quote-depth and breadth-related readers without duplicating alias or price-usability logic.
- A backend-owned 08:00 trading-day presentation-session rollover, plus bounded Frontend boundary refetch only when existing polling cannot guarantee an already-open screen updates at 08:00.
- A clear unavailable-to-display contract: backend numeric values remain `null` with reason/status, Frontend renders `"-"`, and previous-session reference stays separately labeled.
- Evidence-driven opening and closing handoff behavior in `quote_depth.py` and downstream projection.
- Same-session confirmed actual-trade retention with explicit `price_as_of`、source、cache status and missing-price behavior.
- Realtime assessment that separates temporal freshness from fact, research, execution and decision usability.
- Replay output that preserves captured indicative evidence and exposes captured-versus-current contract metadata when needed.
- Fixed-slot capture coverage for at least `09:01` and `09:02`; closing symmetry should include exact `13:31` and `13:33` or a documented equivalent.
- Persisted intraday cache fallback for `prefer_live + external fetch denied + fallback_to_cached=true`.
- Non-decision quote/data-freshness responses with non-actionable `decision` payload while preserving technical evidence.
- Negation-aware `matched_hints` diagnostics.
- Canonical data freshness aggregation aligned with `evidence.capability_status` and required blocked/unavailable capabilities.
- Source-health historical-event fields that cannot be mistaken for current-row freshness.
- Targeted regression tests, full backend safe validation, isolated REST/repo MCP smoke, and staged formal runtime evidence.
- Updated public contract snapshot/digest and Frontend types only if the approved implementation adds outward fields.
- Updated `Progress.md` after every milestone and a final acceptance record that distinguishes deterministic passed、live passed、not observed and provider limitation.

## Done criteria

- All issue rows in `IssueMap.md` are either completed with validation evidence or explicitly deferred with user-approved reason.
- The `AcceptanceMatrix.md` deterministic cases pass on backend service、REST projection、AI contract and replay surfaces.
- On a Taiwan trading day, an OMI screen already open at 07:59 changes its displayed session date to today at 08:00 without manual reload; current-session price/volume/change cells show `"-"`, and no provider fetch or false live/auction claim is created solely by the rollover.
- On weekends and exchange holidays, 08:00 does not create a false current trading session; previous-session references remain correctly dated.
- At 09:00, a provider event from 08:59:55 with `ts=1/pz` remains auction indicative; no actual trade is invented and auction does not disappear because of request time alone.
- A confirmed same-session `z` can be retained across later `z="-"` snapshots with original `price_as_of`; without a confirmed price, OMI reports actual-trade occurrence or depth availability without inventing price.
- Preopen and closing indicative observations remain `facts_usable` where fresh, but never execution-grade or actual-trade decision-usable.
- Replay preserves persisted indicative values and does not contradict its own `quote_semantics`.
- 09:01/09:02 fixed-slot evidence exists for the canary contract; a naturally occurring delayed open remains `not observed` if it does not occur.
- `prefer_live` with external fetch denied reads persisted intraday cache when fallback is allowed and produces no provider event.
- Pure data requests produce no price zone, position or action plan in the decision container.
- Raw freshness、freshness-by-capability and capability status agree for required unavailable/blocked cases.
- Targeted suites pass, then `scripts/run-safe-validation.ps1 -Profile backend` passes.
- Isolated REST and repo MCP return the approved contract with no provider I/O, no production DB mutation and no scheduler side effects.
- Before formal launcher restart, implementation and isolated validation evidence are reported for a rollout checkpoint.
- After approved formal rollout, PID/path/port/digest and representative outward behavior are verified; real-session results are not promoted from `not observed` without time-window evidence.
- No unrelated worktree changes are reverted, staged, committed or pushed.

## Open questions / assumptions

- Default design is to reuse existing outward fields where unambiguous and add only the minimum axes required by consumers. Exact new field names are finalized after consumer inventory in M1.
- Default actual-trade cache uses existing persisted quote/intraday evidence and no migration. If the current schema cannot preserve an authoritative `price_as_of`, implementation stops for a separate schema proposal.
- `2330` remains the fixed canary because 2026-08-05 evidence already exists. A delayed-open security is not actively hunted with broad provider calls.
- The project includes the original A～E runtime follow-up packages, but transition truth and evidence integrity are implemented first because they are now source/runtime-confirmed P0 issues.
- Formal runtime rollout is a separate checkpoint after source and isolated validation; plan approval does not authorize commit or push.
