# 台股盤中成交量雙軌契約修正

## Goal

- 修正 `intraday.bars` 把 24 小時 history window 跨交易日加總成單日累計量的錯誤。
- 將 latest-trade-date 分鐘 K 加總與 TWSE MIS `v` 的 session cumulative volume 拆成可辨識、可對帳、可保留各自時間戳的雙軌契約。
- 讓 VWAP、累計成交值與量價 metadata 只使用 latest trade date 的 interval bars，不受前一交易日污染。
- 維持 `cumulative_volume_*` 相容欄位，但以明確 status/source/scope 揭露它是時間對齊的 MIS session total 或 bar-sum fallback。
- 將新增欄位 additive 地投影到 REST、AI `intraday.bars` capability 與 repo MCP public snapshot。

## Non-goals

- 不把 MIS 與分鐘 K 的差額灌進任何單根 K 棒。
- 不改變 history points 的跨日 chart coverage；只修正 session-cumulative metadata scope。
- 不在 standalone history GET 額外呼叫 quote provider，也不新增 DB migration。
- 不處理 3017 日線與週持股長期未更新問題；該問題維持獨立 P1。
- 不修改 Frontend、Kuro 或 MCP adapter 來重算市場語意。
- 不 commit、push、發布或重啟正式 runtime。

## Hard constraints

- TWSE MIS `v` 是 regular-session board-lot cumulative 的 as-of snapshot，不是無條件的當下總量，也不是 official daily aggregate。
- 只有同交易日、actual-session volume 可用、quote freshness 可接受，且 quote event time 未落後最新 bar 超過該 interval 容許範圍時，MIS 才能升級為 `cumulative_volume_*` 相容 alias。
- 同日但較舊的 quote 必須保留為 `session_cumulative_volume_*` 的帶時間 evidence，並回報 `time_skew`；不得覆寫較新的 bar-sum fallback。
- preopen auction、日期不一致、missing/stale/provider failure 必須保持 unavailable/date-mismatch/time-skew 等可見狀態。
- 分鐘 K points、每根 volume 與 bar-derived VWAP 不得被 reconciliation 修改。
- Backend 是 volume scope、freshness 與 reconciliation 的唯一 owner；consumer 保持 thin。
- dirty worktree 既有變更屬於使用者或其他工作；不得 revert、格式化或混入無關修改。

## Context

- Repo: `C:\project\Open Market Intelligence`
- Engineering ticket: `C:\Users\thoma\Downloads\OMI_盤中成交量契約修正_工程處理單_2026-08-06.txt`
- Related systems: Taiwan intraday history、quote-depth、AI market context、capability registry、OpenAPI、repo MCP snapshot。
- Confirmed 3017 evidence: quote `09:39:56` MIS `v=3091` lots；1m bars through `09:40` sum to `3012.567` lots；09:00 bar has OHLC but zero volume。
- Confirmed 2337 evidence: quote `09:34:35` MIS `v=53962` lots；the early 24-hour query window can include roughly `109312` lots from the prior session and inflate the result above `160000` lots。
- Current source and live OpenAPI still expose ambiguous `cumulative_volume_*` without the proposed dual-track fields。

## Deliverables

- Session-scoped intraday metadata and additive public schema fields。
- Quote/intraday reconciliation pure helper in backend AI market context without duplicate provider calls。
- Additive capability field inventory and regenerated repo MCP public contract snapshot。
- Regression tests for cross-date volume/VWAP、3017 gap、2337 cross-date、preopen、date mismatch、time skew、bar sum exceeding MIS and compact/capability projection。
- Targeted/full backend validation evidence and a next-session live acceptance checklist。

## Done criteria

- Multi-day points remain present, while all cumulative value/VWAP metadata uses only the latest trade date。
- 3017-style aligned evidence exposes MIS session total `3091` lots、bar sum `3012.567` lots、unallocated `78.433` lots without changing points。
- 2337-style previous-session bars cannot inflate current-session cumulative metadata。
- A stale same-day quote cannot overwrite newer bars；reconciliation reports `time_skew` and the compatibility alias remains an explicit bar fallback。
- Preopen volume remains unavailable and cannot inherit yesterday's bars。
- REST schema、AI compact projection and capability output retain the new fields；legacy fields remain present。
- Targeted tests、backend safe validation and diff checks pass。
- Tomorrow's 09:00-09:40 live checks remain explicitly pending until observed in the real session。

## Open questions / assumptions

- Reconciliation tolerance defaults to the effective bar interval, with a minimum of 60 seconds, because bar timestamps represent interval boundaries and can be a few seconds ahead of the quote event。
- Missing MIS evidence in standalone history uses latest-trade-date bar sum as the compatibility fallback with an explicit `fallback_bar_sum` status。
- No Frontend type change is required unless current UI directly consumes the new REST fields；consumer inventory will verify this before validation。
