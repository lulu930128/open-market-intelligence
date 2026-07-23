# Plan

## Milestones

1. 建立後端匯率與外資 context
   - Scope: cache readers、1／5／20 日聚合、regime、flow state、combined signal、freshness、schema。
   - Acceptance: ready／partial／stale 與確認／背離狀態可預測，且不改 overnight score。
   - Validation: `python -m pytest tests/test_fx_flow_context.py tests/test_overnight_impact.py -q`

2. 加入預設收合 UI
   - Scope: TypeScript type、`OvernightDataViews`、三語文案與 focused fixture。
   - Acceptance: 收合列顯示 USD/TWD、台幣 regime、combined signal 與 stale/partial；展開顯示 1／5／20 日與資料日期。
   - Validation: targeted ESLint、`tsc --noEmit`、focused Playwright。

3. 完成契約與 runtime 驗證
   - Scope: API schema regression、production build、代表性 stock loopback probe。
   - Acceptance: optional field 向後相容，實際 runtime 可取得 nested context。
   - Validation: API inventory、`npm run build`、bounded HTTP probe。

## Stop-and-fix rules

- 若 FX 方向、TWD 反向報酬、外資單位或交易日 freshness 測試失敗，先修正再進 UI。
- 若必須新增 GET 外部 refresh、migration 或前端市場判讀，暫停並更新 `Prompt.md`。
- 若 worktree 既有變更與本次檔案重疊，逐段保留，不使用 reset 或全檔覆寫。

## Decisions

- 2026-07-23：combined signal 使用 5 日大盤外資與 5／20 日 USD/TWD regime；個股外資作個股層確認，不直接改全市場 signal。
- 2026-07-23：採「confirmation not causation」契約，避免把台幣貶值寫成外資賣超的單向原因。
- 2026-07-23：20 日資料不足只顯示 limitation；核心 5 日資料不足才將 status 降為 partial。
