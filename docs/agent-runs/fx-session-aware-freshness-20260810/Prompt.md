# FX Session-Aware Freshness 與跨市場刷新根修

## Goal

- 建立 backend-owned、session-aware、用途分流的 FX freshness contract，讓休市期間的最近有效資料不再因純日曆時間被誤判為 stale，同時保證市場重新開啟後仍未更新的資料繼續明確標成 stale。
- 讓個股 ADR parity、canonical cross-market context、FX flow context 與「商品／貨幣」快照使用同一套 FX session primitives、reason codes 與 refresh eligibility，不再各自維護 `72h`／`4h` magic threshold。
- 讓個股頁在 backend 判定 FX 可刷新時，透過既有 bounded cross-market job 完成 refresh handoff；read path、historical replay 與 Radar GET 不得隱性觸發 provider side effect。

## Non-goals

- 不以把 `72 小時`改成 `96/120 小時`、隱藏警告或把 stale 改文案的方式掩蓋問題。
- 不更改 ADR/ADS identity、換股比率、relation registry governance、proxy relation、Radar ranking、technical score 或交易決策方向。
- 不新增付費 provider、不做全市場或無界 FX backfill，也不把 USD/TWD 改成無條件 always-on。
- 不在 frontend、MCP 或 Kuro 重算市場日曆、FX freshness、refresh policy 或 provider fallback。
- 不在本任務移除 legacy `/api/market/overnight-impact/{stock_id}` 的既有相容行為；只停止擴大其 GET side effect，並讓新 frontend flow 使用明確 POST job owner。
- 預設不做 DB migration；只有現有 `ResourceQuoteSnapshot`／`ResourceOhlcvBar` 無法保存 acceptance 所需 lineage 時，才另提 migration 決策。

## Hard constraints

- Backend 是 FX session、freshness、資料選擇、refresh eligibility 與 answer contract 的唯一真相來源。
- 必須分開處理三種用途，不能用同一個 release window 粗暴套用：
  - `spot_quote`：貨幣快照的近即時／best-effort 報價。
  - `adr_alignment`：與 ADR 收盤 session 對齊的換算輸入。
  - `daily_trend`：FX flow context 使用的日線序列。
- Freshness 至少分辨 `event_time`、`fetched_at`、資料日期、目前 session、latest completed session 與 next expected update；cache 最近被讀取不等於市場事件是最新。
- FX 是 OTC／provider-defined 24x5 context，不得直接把 NYSE holiday calendar 冒充完整 FX 休市日曆。可確認的 weekend／maintenance 規則與未驗證 holiday 限制必須分開揭露。
- 對 current read，可依目前時間重新計算 freshness；對 replay，必須以 `decision_at` 與 `available_at <= decision_at` 重建當時狀態，不能拿現在的日曆或資料改寫 immutable snapshot。
- Provider refresh 必須 target-bounded、可 dedupe、有 timeout、cooldown、provider event 與 predictable partial failure；不得因同一 USD/TWD 被多檔 ADR 共同依賴而重複抓取。
- Public API 預設 additive compatible；既有 top-level `ready/stale/partial` 與 resource-health `live/delayed/stale` consumer 不得無預警 breaking change。
- 真實 `2026-08-03` USD/TWD 在 `2026-08-10` 市場已重新活動的情境仍必須判為 stale，不能因 holiday-aware 修正而變成 current。
- 不刪除、重建或覆寫 `data/open_market_intelligence.db`；不得修改或回退無關的 `tw_corporate_events` 在途變更。

## Context

- Repo: `C:\project\Open Market Intelligence`
- Related systems: `backend/app/resource_market/`、`backend/app/market/adr_parity.py`、`backend/app/market/fx_flow_context.py`、`backend/app/market/cross_market/`、`backend/app/market/overnight_impact.py`、Frontend stock detail／Resource panel、job／provider-event runtime。
- Current branch: `codex/tw-etf-provider-normalization`；工作樹另有 `backend/app/market/tw_corporate_events.py` 與 `backend/tests/test_tw_corporate_events.py` 在途修改，本任務不得碰觸。
- 2026-08-10 live baseline：
  - ASX latest/expected trade date 都是 `2026-08-07`，`adr_is_current=true`。
  - USD/TWD event/fetch time 停在 `2026-08-03T11:46Z`，約 169 小時，cross-market context 僅因 `fx` 成為 stale。
  - Cross-market plan 已能規劃唯一 `resource_quote:USD-TWD` operation，但正式 DB 沒有 cross-market refresh job/event。
  - Resource source-health 對 `exchange=FX` 回 `session_status=unknown`，quote 只套 `4h` best-effort threshold。
  - 個股 detail GET 的 legacy ensure 只執行 US daily `refresh_symbols`，不執行 composite plan 的 FX operation。
- Existing related task: `docs/agent-runs/cross-market-relation-context-20260809/`；本任務沿用 relation、snapshot、current/replay 與 bounded refresh contract，不重開 M7/M8 ranking scope。

## Deliverables

- 一個純 backend FX session／freshness module，提供 purpose-specific evaluation、reason codes、refresh eligibility 與 next expected update。
- ADR parity、FX flow、cross-market refresh plan、resource source-health 的一致 integration。
- Additive API/schema/type projection，讓 consumer 能看見 FX purpose、session、expected/actual data date、event/fetch age、usable 與 refresh decision。
- 個股頁明確的 bounded refresh handoff：初讀、enqueue、job/status-center、完成後 reread；不得 frontend 自行判 freshness。
- Deterministic regression matrix、focused backend/frontend tests、safe validation 與正式 runtime canary 證據。
- 任務進度與決策持續記錄於本目錄的 `Progress.md`。

## Done criteria

- 最近完成 session 的 FX 在 weekend／maintenance／已知 closure 期間不因純牆鐘 age 被誤判 stale，且輸出清楚標示 `latest_completed_session` 或等價 reason。
- FX session 已重新開啟並超過 grace window、provider 仍沒有新 event 時，ADR parity、cross-market 與貨幣 source-health 一致判 stale，且只規劃一筆可執行 USD/TWD refresh。
- ADR parity 的 FX input 與 ADR session 對齊；若只能用 fallback，lineage、alignment status 與 limitation 必須可見，不能拿任意最新 spot 冒充 aligned FX。
- Currency snapshot 不再回 `session_status=unknown` 作為正常 FX 狀態；closed/open/maintenance/unknown 與 reason 可由 API 讀取。
- Provider refresh 成功但 market event 未前進時，結果依 session 判 `latest_completed_session` 或 stale，而不是以新 `fetched_at` 自動冒充 current。
- Stock detail current flow 能依 backend `refresh_decision.should_execute` enqueue bounded job，完成後 reread；cooldown／partial failure 不形成重複迴圈。
- Historical replay、Radar GET、MCP thin adapter 與既有 top-level response shape 保持相容。
- Focused regression、backend safe validation、frontend typecheck/lint、代表性 API/runtime smoke 全部通過；正式 runtime PID/build identity 與 source/provider events 有證據。

## Open questions / assumptions

- 初始 FX session policy 以 provider contract 的 America/New_York 24x5 weekend／daily maintenance 規則為基線；沒有可靠 provider holiday calendar時輸出 `calendar_unverified` limitation，不捏造 holiday name。
- ADR parity 預設改用 ADR trade date 對齊的 `1d` FX bar；若該日 bar 缺失，可 bounded refresh 後再評估，不能直接用跨多個 session 的 latest quote 當作無限制 fallback。
- 是否未來將 USD/TWD 提升為 background dependency maintenance，留待本任務完成 on-select／AI bounded handoff並取得 provider call-rate證據後再決定。
