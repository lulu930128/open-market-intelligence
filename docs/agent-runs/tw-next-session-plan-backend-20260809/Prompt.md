# 台股下一交易日技術位階

## Goal

- 建立獨立、唯讀、可版本化的台股個股 `next_session_plan` backend capability。
- 使用最新已完成日 K，計算下一交易日 MA20／MA60 條件轉換價、平盤假設 MA、均線漂移與已知 20 日高低區間。
- 在台股普通個股技術卡中加入獨立「隔日支撐／壓力預告」欄位，固定置於技術證據下、美股隔夜上。
- Frontend 只呈現 canonical backend contract；AI、MCP 與 Radar 仍不接入。

## Non-goals

- 不預測隔日高低、漲跌方向或保證支撐／壓力有效。
- 不產生自動交易指令、不修改 Radar 排名或分數。
- 不接 AI capability、MCP、Kuro 或 Radar。
- 不新增 scheduler、外部 provider refresh、DB table 或 migration。
- 不在 v1 對除權息或其他公司行動做價格還原。

## Hard constraints

- Repo：`C:\project\Open Market Intelligence`。
- Backend 擁有公式、交易日、freshness、readiness、角色與限制；consumer 不得重算。
- GET/read path 只讀既有 `market_daily_price` 與 `stock_master`，不得觸發 provider、backfill、commit 或其他 side effect。
- `target_trade_date` 必須使用台股交易日曆，不得直接日曆日加一。
- 盤中價格若日後代入，只能表述為 hypothetical close；本 contract 不把未知 `x` 包裝成正式 MA。
- raw/unadjusted close、缺資料、stale、partial、not-applicable 與 limitation 必須顯式輸出。
- 保留目前 worktree 的其他修改，尤其不碰正在進行中的 AI/MCP 工作。
- API transport error 詳情送入共用「更新狀態」；`partial`、`pending`、`stale`、`missing` 與限制則在欄位內保持可見。
- ETF 與指數不載入或顯示本欄位；不得把 backend 的 `not_applicable` 重新解讀成市場訊號。

## Context

- 現有 `indicator_service.py` 以 rolling close 計算 MA，並以先前區間 high/low 計算 support/resistance。
- 現有 technical report 與 AI 路徑有共用關係；為避免未授權接入 AI，本階段採獨立 market service 與獨立唯讀 endpoint。
- 台股 daily price expected date 由 `expected_daily_price_date()` 與 15:15 release policy 決定。

## Deliverables

- `backend/app/market/next_session_plan.py`：純計算與 DB read service。
- `backend/app/market/next_session_plan_schemas.py`：public response schema。
- `GET /api/market/technical/{stock_id}/next-session-plan`。
- 純計算、service/readiness、OpenAPI/API contract targeted tests。
- Frontend typed contract、獨立 data hook、responsive panel、三語文案與 focused E2E。
- 本任務 capability contract、計畫與驗證記錄。

## Done criteria

- MA20／MA60 轉換價符合 `mean(last N-1 completed closes)`，且 `candidate_price >= transition_price` 等價於 `candidate_price >= projected_MA_N(candidate_price)`。
- 下一交易日、freshness、lifecycle、missing/partial/stale/not-applicable 有 deterministic tests。
- API 有明確 response model，frontend 只消費該 contract，且不修改 AI/MCP/Radar。
- Targeted backend tests、compile check 與 `git diff --check` 通過。
- 普通台股個股頁能在指定位置顯示 target date、MA20／MA60 transition、scenario zones 與 readiness；loading/error/stale/partial 不被包成 ready。
- Frontend lint、typecheck、build 與 focused browser test 通過。

## Open questions / assumptions

- v1 只把 `StockMaster.instrument_type=stock` 視為完整適用；缺主檔或 `unknown` 可計算但降低 readiness，明確非股票則 `not_applicable`。
- v1 使用 raw/unadjusted official daily close。除權息檢查與調整留待後續 capability 版本，現階段以 limitation 揭露。
- v1 不加入任意 ATR/tick buffer；先輸出精確條件轉換價與由 MA20/MA60 自然形成的 scenario zones。
