# 執行計畫

## Milestones

1. Backend current-state contract
   - Scope: `technical_structure.py`、`technical_report.py`
   - Acceptance: 輸出 headline、qualifier、均線位置、修復/風險 levels、四組 evidence 與 next conditions。
   - Validation: `backend\tests\test_technical_structure.py`、`backend\tests\test_technical_report.py`

2. Session finalization
   - Scope: daily technical report intraday overlay gate
   - Acceptance: 收盤後同日 finalized indicator 存在時使用 daily phase；盤中仍保留 provisional overlay。
   - Validation: targeted session tests。

3. Frontend progressive disclosure
   - Scope: Taiwan stock detail technical card、types、i18n
   - Acceptance: 日線顯示現在狀況與修復階梯；四組證據與 context 預設收起；其他 timeframe 使用既有 UI。
   - Validation: TypeScript、ESLint、focused Playwright。

4. Integration validation
   - Scope: backend/frontend contract、2478 representative API/UI
   - Acceptance: targeted regression、build、diff check 與實際畫面通過。
   - Validation: safe validation commands、API probe、browser screenshot。

5. Signal chip hierarchy and evidence navigation
   - Scope: `stockDetailSignalProjection.ts`、`StockDetailPanel.tsx`、i18n、focused Playwright
   - Acceptance: 核心／背景分組；日線技術 chip 取自 `current_state`；背景數值具正確週期/單位語意；點擊可展開證據。
   - Validation: TypeScript、targeted ESLint、production build、focused Playwright。

## Stop-and-fix rules

- 若 current-state contract 需要 frontend 重算市場語意，先停下把語意移回 backend。
- 若收盤後切換會隱藏 stale/partial 狀態，先修正 freshness 再繼續。
- 若 targeted test、typecheck、lint、build 或 browser smoke 失敗，先修正再進下一步。
- 若修改碰到其他 dirty worktree 任務，縮小 diff，不覆寫或 revert。

## Decisions

- 2026-07-23：保留舊 `value/value_label/rows/badges`，在 `data.current_state` 新增 v1 contract。
- 2026-07-23：以摘要優先、細節收合取代三條等權 metric bars；不新增 UI library。
- 2026-07-23：修復幅度採 `(level / price - 1) * 100`，明確區分既有「價格相對均線」百分比。
- 2026-07-23：移除與 headline 重複的 classification chip；技術 chip 使用 backend current-state evidence。
- 2026-07-23：隔夜 chip 沿用 backend stance；相對大盤顯示百分點；融資餘額變化保持中性色。
