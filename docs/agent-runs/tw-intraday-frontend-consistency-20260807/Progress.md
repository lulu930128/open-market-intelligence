# Progress

## Status

- Current phase: canonical Index Today source implementation and deterministic validation complete；formal runtime adoption and real-session acceptance pending。
- Last updated: 2026-08-08 18:06 Asia/Taipei。
- Git: no commit or push performed。
- Runtime: existing runtime was inspected read-only；no launcher restart or formal adoption performed after source changes。
- Live acceptance: exact 2026-08-07 morning lag reconstruction unavailable；next real Taiwan preopen／opening／stable intraday session pending。

## Completed

- Read product direction、repo/frontend instructions and productized task workflow。
- Reviewed the user engineering report against current source、tests、launcher/backend logs、REST payloads and actual responsive layout。
- Classified ISSUE-01 as a confirmed contract/observability gap with the exact morning lag still not reconstructable post hoc。
- Confirmed ISSUE-02 TPEX Today special rendering、ISSUE-03 synthetic preview/replay coverage boundary and ISSUE-04 `xl` stacking behavior。
- Confirmed the existing 2026-08-06 volume contract work must be preserved rather than duplicated。
- Created a separate long-running task with milestones、stop rules and live-session boundaries。
- Added one canonical TWSE MIS actual-trade resolver shared by intraday and quote-depth paths：trade date、regular-session event time、`z` and positive `tv`／`v` evidence must all agree；`pz` and `z` without volume evidence remain non-trade observations。
- Extended the intraday response additively with history/current price source、event time、lag、availability、unavailable reason and whether current price was applied to history；existing price/volume dual-track fields remain intact。
- Prevented a positive cumulative volume with missing `z` from creating a new `price=null` point；the volume can only update an already aligned point。
- Made Quote Depth reuse the same actual-trade resolver and search persisted candidates for the latest confirmed same-session trade instead of promoting an unconfirmed `z`。
- Moved TPEX Today onto the shared intraday research surface while retaining trade-date、`bar_type` and `indicator_eligible` filtering；post-close summary bars no longer pollute the regular-session plot or indicators。
- Kept TPEX volume and VWAP controls unavailable when the source has no valid volume semantics；TWAP／EMA and the shared Today controls remain available。
- Added a compact Technical jump action below `xl` instead of forcing an over-narrow two-column chart at 1256／1280 px。
- Added a read-only `即時／試撮快照` mode using only persisted replay captures；coverage `0` disables replay and debug preview remains separate。
- Added focused backend and Playwright regressions for canonical MIS convergence、TPEX Today filtering/fallback、replay coverage and the intermediate-width Technical interaction。
- Added an index-only public projection after provider fetch/merge：raw TAIEX／TPEX 5-second points remain available through provenance/count metadata while public `points` are canonical 1-minute bars。
- Canonicalized the TPEX provider `99:99:99` closing summary into the 13:30 `official_close_marker`；the raw 13:30 value and post-close confirmation remain auditable, but 13:33 is no longer a plotted point。
- Added `source_interval`、`effective_interval`、`source_point_count`、`capabilities`、`current_observation` and bounded supplemental `observations` to the shared intraday response contract。
- Split `display_eligible` from `indicator_eligible`：13:25–13:29 closing-auction values remain visible but are provisional and excluded from indicators；the official 13:30 close is finalized and indicator-eligible。
- Removed the frontend `isTpexToday` branch and TPEX-only test ID；stocks、TAIEX and TPEX now use `today-intraday-surface` and backend capabilities control Volume、VWAP and price-limit behavior。
- Header Today price/time now prefer backend `current_observation`，so TPEX Header and the final plotted close use the same 13:30 canonical value。
- Prevented no-volume index series from creating thousands of zero-height SVG volume bars；the no-volume layout also removes the empty volume summary/panel space。
- Compacted both live and persisted replay quote-depth layouts：five-level depth remains the primary left column；the narrower right column shows volume scope metrics during regular live trading and auction calculations during preopen／closing auction states。Below 1024 px the same components stack vertically without changing any quote、volume or replay semantics。

## Validation evidence

- Read-only runtime evidence: selected stock `2344` intraday and quote-depth endpoints both continued returning HTTP 200 at the frontend polling cadence。
- Preserved checkpoint: `2344` 12:07 intraday and quote depth both reported `164.5`；later MIS provider failures were separately observed。
- Browser viewport evidence: at `1256x900`, Technical started around `3126px` below the panel；at `1280px`, the two-column chart area was already only about `538px` wide。
- Replay evidence: `2330` had approximately `94.1%` fixed-slot coverage；`2344` had zero coverage。
- Focused backend safe validation：`99 passed, 73 subtests passed`，log directory `.tmp/validation/20260808-000746`。
- Full backend safe validation：compileall passed；`1507 passed, 5 warnings in 217.01s`；`git diff --check` passed，log directory `.tmp/validation/20260808-000859`。
- Frontend ESLint and TypeScript passed，log directory `.tmp/validation/20260808-001256`。
- Production build passed outside the restricted sandbox；the first sandboxed build compiled and typechecked but worker spawn was blocked by Windows `EPERM`，not by a source error。
- Production Playwright smoke：all `47 passed (55.0s)`，including the five new/updated issue regressions。
- No database writes、external market refresh、launcher restart、commit or push were performed。
- 2026-08-08 focused backend regression：`80 passed`，including TPEX sentinel close、dense 5-second projection、closing-auction indicator exclusion and stock MIS convergence；log directory `.tmp/validation/20260808-161904`。
- 2026-08-08 full backend safe validation：compileall passed；`1509 passed, 5 warnings in 161.10s`；`git diff --check` passed，log directory `.tmp/validation/20260808-162430`。
- 2026-08-08 frontend ESLint、TypeScript and `git diff --check` passed；log directory `.tmp/validation/20260808-162737`。
- 2026-08-08 production build passed with Next.js 16.2.12。
- Focused production Playwright：`4 passed (9.8s)` for stock、TAIEX、TPEX canonical Today and snapshot fallback；TAIEX／TPEX SVG descendant budget stayed below 500 and no volume bars rendered。
- Full production Playwright smoke：`47 passed (52.1s)`；the initial-backend `fetch failed` messages are the expected mocked-proxy condition and all routed UI regressions passed。
- Read-only projection of the existing 8400 runtime payload：TAIEX `3242 -> 271`、TPEX `3242 -> 271`；both ended at 13:30，TPEX plotted/current observation both `384.19`，`source_interval=5s`、`effective_interval=1m`。
- 2026-08-08 quote-depth layout validation：frontend ESLint、TypeScript and `git diff --check` passed，log directory `.tmp/validation/20260808-174528`；Next.js 16.2.12 production build passed；focused production Playwright passed at both 1280 px side-by-side and 900 px stacked layouts。
- 2026-08-08 live-layout follow-up：frontend ESLint、TypeScript and `git diff --check` passed，log directory `.tmp/validation/20260808-180315`；production build passed；focused production Playwright passed for both regular-live volume summary and persisted auction replay (`2 passed`)；component screenshot confirmed all three volume values remain readable in the 13rem right column。

## Decisions made

- Preserve `pz` as indicative-only and require canonical actual-trade evidence for MIS `z` convergence。
- Keep history bars and current observation as distinct evidence with explicit source/time/lag metadata。
- Keep provider parsing/daily OHLC untouched and isolate index Today normalization in the public projection layer。
- Drive all Today controls from backend capabilities rather than symbol-specific frontend templates。
- Use a discoverable single-column Technical interaction at intermediate widths instead of blindly lowering the grid breakpoint。
- Keep replay coverage visible and bounded；do not fabricate or on-demand backfill missed auction snapshots。

## Known issues / risks

- Relevant backend and frontend files already contain substantial uncommitted work from volume、opening-handoff、dispatch、breadth、Radar and other tasks。
- Current runtime may not identify with the latest source after subsequent edits；formal adoption must be a separate verified step。
- Consumers that inspect index intraday `point_count` or the last raw 13:33 point will observe the intentional public behavior change；raw interval/count and post-close observation are preserved additively for audit/migration。
- Real preopen、opening handoff and stable intraday convergence cannot be certified after hours。
- Replay remains bounded by persisted scheduler coverage；a stock with no captured slot correctly remains unavailable。
- The shared MIS helper file and its focused test were already untracked in the overlapping worktree and must not be omitted from any later intentional staging scope。

## Next step

- Perform formal launcher/runtime adoption, then verify process/path/port/build identity plus REST and frontend outward behavior。
- During the next real Taiwan session, capture probes at preopen、opening handoff and stable intraday：confirm canonical `z` + volume evidence、history/current event times、lag and Header／Today／Quote Depth convergence within two 5-second polls（≤10 seconds）。
- Keep any window not actually observed as `not_observed`；a health endpoint、HTTP 200 or after-hours replay is not live acceptance。
