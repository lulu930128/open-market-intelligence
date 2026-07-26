# OMI 盤中健康與對外契約收旂

## Goal

- 修復 2026-07-20 實際盤中回歸暴露的台股、日股、韓股即時資料、freshness、市場時段、provider fallback、Query Plan 與 MCP 對外契約問題。
- 讓 quote、depth、intraday、daily、calendar、provider health 與 coverage 保持獨立可解釋的狀態，不再把過期、休市或部分資料投影成錯誤的 live/current。
- 讓 `/api/ai/ask`、main MCP 與 external `OMI_search` 保持 thin-consumer 且相容的 additive contract。

## Non-goals

- 不實作「除權息時間表」、公布財報、法說會、行事曆或專業模式 UI。
- 不修改 frontend 視覺、圖表交互或專業模式相關檔案，除非 backend contract 有必要的 additive type compatibility。
- 不刪除、重建或覆寫 `data/open_market_intelligence.db`。
- 不以大量 provider 請求人為製造故障，也不做無邊界全市場 refresh。

## Hard constraints

- Repo: `C:\project\Open Market Intelligence`
- Backend 是 market status、freshness、provider selection、display price、Query Plan 與 AI answer contract 的真相來源。
- Frontend、MCP 與 Kuro 不得重做 backend 市場邏輯。
- 對外契約優先 additive/versioned；保留現有 route、request envelope 與可忽略新欄位的 consumer 相容性。
- `stale`、`delayed`、`cached`、`partial`、`missing`、`not_applicable`、`provider_failure` 與 `runtime_drift` 必須可見。
- 即時資料只能由當前交易 session、quote timestamp 與 age gate 決定 live；provider 自稱 realtime 不是充分條件。
- 休市日最近收盤是 `latest_completed_session`，不是 realtime，也不必然是 stale。
- 只查 quote/intraday 時，不相關 reader/provider call count 必須為零。
- 工作樹已有大量未提交變更；一律保留、共存，不 revert 不相關修改。

## Context

- Source report: `C:\Users\thoma\Downloads\OMI_MCP_盤中健康檢查問題整理_2026-07-20.txt`
- Live verification on 2026-07-20 confirmed:
  - TWSE MIS 歷史有大量 `indices.twse_mis_breadth_batch` 批次失敗，事件未保留 HTTP/exception diagnostics。
  - TAIEX summary 與 direct MIS intraday 的時間、價格、volume 不一致。
  - JP holiday calendar 正確，但 JP reader 仍投影 `session_phase=regular`。
  - 否定詞「不刷新分點」仍路由到 `omi.read_stock_broker_branch`。
  - `N225` 與 `^N225` alias 不一致。
  - 2330 1m 與 5m 最新時間明顯不同步。
  - 2492/6173 有價格、累計量完全相同的重複盤中點。
- Existing long task `docs/agent-runs/omi-ai-decision-core/` already owns earlier outward-contract work; this task extends it with market/session/provider remediation and must preserve its invariants.

## Deliverables

- Shared market-session/live-freshness projection used by TW/JP/KR public market contexts.
- Unified quote/display-price contract with separate quote depth and intraday freshness/provenance.
- Transparent requested/effective provider and fallback diagnostics, including strict-provider behavior.
- Domain-scoped Query Plan and refresh behavior with explicit requested/excluded domains and negation handling.
- TWSE MIS bounded request protection: coalescing, rate/circuit behavior, and structured failure telemetry appropriate to current architecture.
- Correct JP index aliases and holiday semantics; KR stock age gate aligned with index semantics.
- Domain-aware global health/passport projection.
- Disposition-stock trading metadata and intraday duplicate suppression.
- Locally derived/current 5m bars or explicit timeframe freshness delta.
- Focused regression tests, full backend validation, MCP compatibility tests, and bounded live API smoke evidence.

## Done criteria

- The ten acceptance cases in the source report pass through backend HTTP and representative MCP calls.
- Quote/depth/intraday conflicts expose one canonical display price and preserve each source's independent status.
- Open-market data older than the configured age gate cannot be `live/current`; holiday latest close is non-realtime and non-stale when appropriate.
- Provider strict mode never silently falls back; non-strict fallback is explicitly attributed.
- Quote-only/intraday-only requests do not call monthly revenue, institutional, broker-branch or unrelated readers/providers.
- Global health separates operational health, live feed health, database freshness and coverage completeness.
- Relevant targeted suites and full backend regression pass; current runtime is restarted only after source changes settle, then live contract is rechecked.

## Open questions / assumptions

- Assumption: the other active work is limited to the ex-dividend/calendar feature and frontend professional mode; this task will not edit their primary files.
- Assumption: new public fields remain additive under `omi.ai.ask.v2`; a new nested quote/live-health contract can carry its own version.
- Assumption: external `OMI_search` may require a separate workspace write approval after backend/main MCP contract is stable.
