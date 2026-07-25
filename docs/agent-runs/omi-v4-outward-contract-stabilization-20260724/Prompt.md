# OMI v4 對外契約穩定化

## Goal

- 修正 2026-07-24 live runtime 已重現的 `omi.decision.v4` 對外契約缺陷。
- 讓 backend canonical evidence、HTTP/SSE、repo MCP、Frontend 與外部 `OMI_search` 對同一個成功、部分、拒絕與 transport failure 語意達成一致。
- 保證已成功取得的資料不會在 outward projection 遺失，也不會因狀態、單位、trust 或 refresh 對帳錯誤而被誤標。

## Non-goals

- 不新增市場、provider、capability 或分析功能。
- 不擴大成市場資料全面補齊、全市場 backfill 或 provider coverage 專案。
- 不修改 `data/open_market_intelligence.db` schema，不重建或重置本機資料。
- 不讓 frontend、MCP、Kuro 重做 backend 的資料品質、freshness 或決策邏輯。
- 不執行 LLM、報告、記憶寫入、付費 quota 或無邊界外部 refresh。

## Hard constraints

- Public contract 維持 `omi.decision.v4` only。
- Backend 是 capability selection、evidence、freshness、quality、bounded refresh、decision readiness 與 business error 的唯一真相來源。
- `missing`、`stale`、`partial`、`not_applicable`、provider failure 與 projection omission 必須保持可見。
- Structured business rejection 是成功傳輸的 canonical result；HTTP/MCP transport error 不得與它混淆。
- Outward payload 必須受 `selection.fields`、`selection.limits` 與 `max_response_bytes` 限制，不得直接暴露 raw tool payload。
- 必須保留目前 worktree 內既有改動，不做無關重構、dependency upgrade、格式化或 cleanup。

## Context

- Repo: `C:\project\Open Market Intelligence`
- Related adapter: `C:\GPT_MCPtool\OMI_search`
- Current public contract: `omi.decision.v4`
- Baseline runtime: launcher-selected backend URL，以當次 `logs/launcher/<date>/launcher.log` 為準。
- 已重現問題：
  - US intraday、TW daily OHLCV、source-health 在雙重 projection 後遺失。
  - broker-branch primary intent 使複合請求落入過窄 fast path。
  - 成功 refresh 與 fill plan 未對帳，會重複建議相同 action。
  - quote volume unit、quality authority 與 passport trust tuple 不一致。
  - 外部 `OMI_search` 將 structured business rejection 標成 `isError=true`，且 live schema 未完整暴露 v4 controls。
  - `projection.truncated` 無法說明非 capability 欄位裁切。
  - `TARGET_NOT_FOUND` envelope 過大，request target 被誤標成 resolved identity。

## Deliverables

- Canonical internal evidence 到 v4 outward projection 的單一路徑或明確 capability normalizer。
- Multi-intent union 與 pure fast-path routing。
- Refresh attempt/outcome 與 remaining fill actions 的可追蹤對帳。
- Volume unit、availability/freshness/completeness/continuity/unit 與 trust/readiness invariant。
- Repo MCP 與 standalone `OMI_search` schema、business-error parity。
- 可解釋的 projection trimming metadata 與最小 rejected envelope。
- Producer-to-final integration tests、HTTP/SSE/MCP parity tests、完整 validation 與代表性 live smoke。

## Done criteria

- AAPL intraday tool 成功後，`evidence.data["intraday.bars"]` 含 bounded points，且不再重複產生相同 fill action。
- 2330 daily/technical 請求能投影本機既有 daily OHLCV，不誤報 provider refresh。
- Source-health request 能投影 bounded `filters/summary/entries`。
- 複合 2330 請求能同時保留 quote、daily、technical、chips 與 broker-branch 需求。
- Quote volume 有明確單位；facts/readiness/trust 欄位不互相矛盾。
- HTTP、SSE、repo MCP 與 standalone `OMI_search` 對 `TARGET_NOT_FOUND` 保留 canonical business error，MCP `isError=false`。
- `projection.truncated=true` 時，metadata 能精確指出 capability omission 或欄位／list 裁切。
- Rejected request 不產生虛假的 ready identity、realtime 或 fill plan。
- Targeted regression、backend safe validation、必要 frontend/MCP checks 與 bounded live smoke 全部通過。

## Open questions / assumptions

- 假設 v4 可以直接從 finalizer 內部、尚未 legacy mode projection 的 result 建立；若現有 pipeline 邊界不允許，採 capability-specific canonical normalizer，但不複製 market logic。
- Standalone `OMI_search` 位於目前 workspace writable root 之外；程式修改需依 sandbox 權限另行取得核准。
