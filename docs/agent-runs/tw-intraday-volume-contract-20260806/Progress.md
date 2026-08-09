# Progress

## Status

- Current phase: deterministic implementation and source validation complete；formal runtime adoption and next-session live acceptance pending。
- Last updated: 2026-08-06 22:10 Asia/Taipei。
- Git: no commit or push performed。
- Database migration: none required or performed。
- Runtime: source contract is updated；the process currently listening on `127.0.0.1:8400` is still the pre-change build and was not restarted by this task。
- Live acceptance: next Taiwan opening session pending。

## Completed

- Confirmed the 3017 MIS/bar-volume gap and zero-volume 09:00 bar from persisted live API evidence。
- Confirmed the 2337 cross-date 24-hour-window inflation from read-only SQLite evidence。
- Confirmed current source sums all history points for cumulative volume、trade value and VWAP。
- Confirmed current live OpenAPI lacks the dual-track intraday volume fields。
- Defined an additive compatibility and time-alignment policy that prevents an older same-day quote from overwriting newer bars。
- Scoped bar-derived volume、trade value and VWAP metadata to the latest trade date while retaining every requested history point for charting。
- Added explicit bar、window、MIS session cumulative、compatibility cumulative、unallocated-volume and reconciliation metadata to the API schema、AI projection and `intraday.bars` capability contract。
- Reconciled MIS `v` only when source、scope、trade date and event time are usable；pre-open、date mismatch、stale quote、time skew and bar-sum-exceeds-exchange states remain explicit。
- Regenerated the repo-owned MCP public contract snapshot without modifying the standalone MCP checkout。
- Added regression coverage for cross-date windows、3017-style provider gaps、2337-style older quote versus newer bars、pre-open isolation、date mismatch、bar overflow、OpenAPI and AI capability projection。

## Validation evidence

- Existing targeted baseline: `76 passed, 13 subtests passed`。
- Pure current-behavior reproduction: cross-date input produced `33000` cumulative shares and polluted VWAP `109.09` instead of latest-session `3000` shares / VWAP `200`。
- Focused market tests after session scoping: `60 passed, 3 subtests passed`。
- AI/capability focused regression: `150 passed, 15 subtests passed`。
- Broader targeted market、quote、AI、OpenAPI and MCP suite: `230 passed, 87 subtests passed`。
- Contract checksum gate after snapshot update: `50 passed, 62 subtests passed`。
- Full safe backend validation: compile passed、`1495 passed, 5 warnings`、full `git diff --check` passed；logs at `.tmp/validation/20260806-212958`。
- Source OpenAPI reports 72 `MarketIntradayChartRead` properties and includes all five sampled new fields；public contract digest is `279aef0f9bc9340d4efa0b56a03e437d39834ef1ae1a53e1f3f61af93d04ec0c`。
- Current live `8400` OpenAPI still reports 44 properties and none of the sampled new fields；this is an expected runtime/source drift until a formal launcher restart adopts the source build。
- Frontend build/e2e was not run because this task did not change frontend code；no provider refresh or database write was used for validation。

## Decisions made

- Keep all history points for charting；scope only cumulative metadata to latest trade date。
- Preserve both MIS and bar evidence with their own dates/times/sources；only aligned MIS is canonical。
- Treat the exact cause of unallocated volume as provider coverage/auction uncertainty, not proven allocation to a specific bar。
- Preserve legacy cumulative fields additively as a compatibility alias；the authoritative meaning is exposed through the new source、field、scope、trade-date、event-time and status fields。
- A quote slightly older than the newest bar may reconcile within one bar interval, but remains `time_skew`；an older quote outside tolerance cannot overwrite newer bar evidence。
- Positive unallocated volume lowers the approximate VWAP confidence instead of injecting synthetic volume into a chart bar。

## Known issues / risks

- The exact `159135` lots reported for 2337 cannot be reconstructed after later bar updates, but the cross-date mechanism and inflation magnitude are confirmed。
- A real 09:00-09:40 session is required to validate live quote/bar handoff after implementation。
- The formal OMI runtime must be restarted through the normal launcher/tray path before live acceptance；source test success alone is not runtime adoption evidence。
- The worktree contains unrelated existing changes across backend、Frontend、dispatch、breadth and Radar areas。

## Next-session acceptance checklist

1. Before observation, formally restart OMI through the launcher/tray path and verify the selected backend port from `logs/launcher/<date>/launcher.log`。
2. Verify runtime OpenAPI exposes `bar_volume_sum_shares`、`session_cumulative_volume_shares`、`cumulative_volume_source`、`unallocated_volume_shares` and `volume_reconciliation`。
3. During 08:50-08:59 pre-open, confirm session cumulative volume is unavailable/null and no previous-day bar total is reused as today's cumulative volume。
4. During 09:00-09:02 opening handoff, confirm `bar_volume_trade_date`、MIS trade date and both evidence timestamps remain visible；do not treat `pz` or auction state as an actual cumulative trade。
5. During 09:05-09:40, observe 3017、2337 or equivalent liquid canaries and compare MIS cumulative volume against latest-trade-date bar sum using the reconciliation status and signed difference。
6. Confirm a positive provider gap appears only as `unallocated_volume_*` with lower VWAP confidence；the response must not inject that gap into any OHLCV point。
7. Confirm an older quote outside interval tolerance cannot replace newer bar evidence, and that partial、time-skew、date-mismatch or unavailable states remain user-visible。
8. Record the exact runtime URL、observation time、trade date、provider timestamps and representative payloads before marking live acceptance complete。
