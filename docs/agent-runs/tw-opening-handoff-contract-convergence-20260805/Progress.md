# Progress

## Status

- Current phase: Gate R formal launcher rollout passed; staged live-session acceptance remains pending.
- Last updated: 2026-08-05 21:37 Asia/Taipei.
- Milestones: M0-M9 and the formal-runtime portion of M10 complete.
- Formal launcher rollout: passed after explicit user approval and tray `Restart Services` at 2026-08-05 21:23 Asia/Taipei.
- Git: no commit or push performed.
- Database migration: none added by this task.

## Completed implementation

### Canonical presentation and observation contract

- Added a backend-owned Taiwan presentation session with an 08:00 Asia/Taipei rollover on authoritative trading days.
- Before 08:00, presentation remains on the latest completed session; at 08:00 it becomes today's `today_pending` empty frame; weekends and holidays do not roll into a false current session.
- Kept market-calendar phase, instrument phase and provider observation semantics as separate axes.
- Added a pure TWSE MIS observation resolver for preopen, delayed opening, regular trading, closing auction, delayed close and confirmed close.
- Preserved the 09:00 request / 08:59:55 provider-event boundary as auction evidence rather than relabeling it as an actual trade.
- Kept `pz/ps/ts` auction-only. A positive cumulative volume can prove that trading occurred but never supplies a missing actual-trade price.

### Quote depth, actual-trade retention and replay

- The 08:00 empty-session response returns before provider I/O and keeps current-session price, change, volume and price-as-of null.
- Same-session confirmed actual-trade prices can be retained from existing quote snapshots with their original event time and explicit cached source.
- Cached actual prices cannot cross stock identity or trade date; OHLC, order book and indicative prices are not substitutes.
- Official close requires a current confirmed close candidate rather than an earlier cached actual trade.
- Replay preserves the captured public payload, including indicative auction evidence, and exposes explicit replay/captured-contract metadata.
- Added bounded quote-contract slots `09:01`, `09:02`, `13:31` and `13:33`; the existing canary symbol and scheduler concurrency bounds remain unchanged.

### AI, capability and freshness contracts

- Added facts usability, intraday research usability and execution-grade usability as separate realtime axes while retaining legacy `decision_usable` compatibility.
- `quote.auction` applicability now follows instrument/provider evidence before request-clock aliases.
- Published presentation, phase, observation and actual-trade-cache fields through `quote.snapshot`; published market/instrument phase and observation reason through `quote.auction`.
- `prefer_live + external fetch denied + fallback_to_cached=true` can read persisted stock intraday bars with `refresh=false`, without a provider attempt or provider event.
- The persisted-cache exception remains scope-bounded: an untrusted market-overview request does not invoke market-index intraday tools.
- `decision_required=false` now keeps technical evidence while returning empty action, scenario, price-level and position containers.
- Question understanding separates `raw_matched_hints`, effective non-negated `matched_hints` and `negated_hints`.
- Aggregate freshness now separates temporal freshness, availability, completeness and usability; blocked required capabilities cannot appear fully current.
- Source-health output distinguishes current row state from historical latest provider-event state and timestamps.

### Frontend and public adapters

- Frontend types consume the backend presentation/phase/observation fields without reproducing calendar rules.
- The quote-depth hook schedules a single bounded refetch at a future backend-provided presentation transition, including the 08:00 boundary.
- Missing numeric fields continue to render as `"-"`; when no quote event time exists, the panel labels the backend presentation trade date.
- Regenerated `agents/omi_mcp_server/public_contract_snapshot.json`; backend and repo MCP share digest `b4b7119615f28eb272db0e8262c06d407aacc3c694617ab142751d1399c8d460`.

## Validation evidence

### Deterministic and integration tests

- Opening-handoff, quote, AI, freshness, source-health and API inventory integration set: `309 passed, 121 subtests passed`.
- Repo MCP snapshot and AI tool-boundary regression: `40 passed, 2 subtests passed`.
- Market trust-boundary correction plus decision/intraday regression: `28 passed, 33 subtests passed`.
- Full backend safe validation: `1486 passed, 5 warnings` in 160 seconds; compileall and `git diff --check` also passed.
- Full backend log directory: `.tmp/validation/20260805-204634`.

### Frontend validation

- `npm exec tsc -- --noEmit --incremental false`: passed.
- `npm run lint`: passed.
- `npm run build`: passed outside the filesystem sandbox after the sandboxed build compiled successfully but could not spawn a Next.js worker (`EPERM`).
- Production build completed TypeScript, page-data collection, six static pages and final optimization.

### Isolated runtime M9

- Started current source on `127.0.0.1:18400` with `APP_ENV=test`, a new isolated SQLite database, isolated runtime locks, bootstrap disabled, all schedulers disabled and crypto background loops disabled.
- Runtime identity: repo root `C:\project\Open Market Intelligence`, interpreter `.venv\Scripts\python.exe`, Python 3.13.9.
- New database migrated to `20260804_0051`; it was 5.3 MB rather than copying the 14.0 GB formal database.
- Seeded only one temporary `stock_master` row for `2330`. Counts remained `job_run=0`, `provider_event=0`, `dispatch_schedule_run=0`, `taiwan_quote_contract_snapshot=0`.
- `/api/system/readyz` returned runtime/database ready.
- `/api/market/calendar-status?market=tw` returned presentation trade date `2026-08-05`, state `completed`, rollover `08:00` and next transition `2026-08-06T08:00:00+08:00`.
- `/api/market/quote-depth/2330?refresh=false` returned presentation date `2026-08-05`, `post_close/closed`, reason `SESSION_COMPLETED`, null price/change/volume, `price_available=false`, `actual_trade_occurred=false` and `refresh_outcome=not_attempted`.
- The read-only quote probe created no provider event.
- OpenAPI exposed the new quote and presentation-session schema fields.
- `/api/ai/tools` exposed 55 capabilities and digest parity with the repo MCP snapshot.
- Repo MCP protocol smoke passed `initialize -> tools/list -> tools/call(omi.ask)` with protocol `2025-06-18`, public tools `omi.ask`/`omi.ask_stream`, `isError=false` and explicit blocked/unusable semantics for unavailable quote evidence.
- Stopped exact isolated PID pair `38768/49248`; port `18400` has no listener.
- Removed the temporary SQLite database and temporary launcher. Preserved only M9 logs under `.tmp/isolated-runtime/tw-opening-handoff-20260805-m9`.
- Formal `8400` health remained `ok` with `environment=development`; no formal process was restarted or stopped.

### Formal runtime Gate R

- The official tray launcher recorded `Restart requested` at `2026-08-05 21:23:45`, stopped only its tracked frontend/backend wrapper PIDs `56356/21476`, and started new wrapper PIDs `61948/71976` through the normal launcher flow.
- The prior backend shim/listener PIDs `55224/63420` and tracked wrapper PIDs are absent after restart. The existing launcher remains PID `53748`; a secondary `Start-OMI-Launcher.cmd` invocation acquired no second mutex and only re-registered the existing tray icon.
- Launcher-selected service URLs are backend `http://127.0.0.1:8400` and frontend `http://127.0.0.1:3270`; frontend moved to `3270` because launcher port selection is dynamic.
- Runtime identity is the current repo, backend `.venv\Scripts\python.exe` on Python 3.13.9, and frontend `C:\Program Files\nodejs\npm.cmd`. Listener PIDs are backend `62628` and frontend `66392`; launcher wrapper PIDs are `71976/61948`.
- Backend `/api/system/health` returned `status=ok` and the current repo/interpreter identity; `/api/system/readyz` returned runtime/database `ok`.
- Frontend `/omi-ui-health` returned the current frontend path, port `3270`, proxy path `/omi-data` and target `8400`; `/omi-data/system/health` returned the same backend identity, and `/` returned HTTP 200.
- The formal database remained `C:\project\Open Market Intelligence\data\open_market_intelligence.db`, revision `20260804_0051`; read-only `PRAGMA quick_check(1)` returned `ok`. This task added no migration.
- Formal calendar status returned TW trade date/presentation date `2026-08-05`, `post_close`, presentation state `completed`, rollover `08:00` and next transition `2026-08-06T08:00:00+08:00`.
- Formal `quote-depth/2330?refresh=false` returned trade/presentation date `2026-08-05`, `post_close_snapshot/closed`, reason `SESSION_COMPLETED`, official close/actual trade `2405`, source `current_snapshot_z`, price-as-of `13:30 +08:00`, `price_available=true`, `actual_trade_occurred=true`, freshness `official_close` and `refresh_outcome=not_attempted`.
- Formal OpenAPI contains the additive presentation, phase, observation, actual-trade-cache and availability fields.
- Formal `/api/ai/tools` exposes 55 capabilities, 22 targets and digest `b4b7119615f28eb272db0e8262c06d407aacc3c694617ab142751d1399c8d460`, matching the repo MCP snapshot.
- Repo MCP protocol smoke passed `initialize -> tools/list -> tools/call(omi.ask)` against formal `8400`: protocol `2025-06-18`, tools `omi.ask`/`omi.ask_stream`, digest parity, `isError=false`, `omi.decision.v4`, target `tw_stock:2330`, `cached_data_returned=true`, no LLM/write/external fetch.
- Normal formal startup reconciliation marked three previously unfinished jobs as interrupted and existing schedulers queued/resumed their bounded work. Background crypto/provider events and quote-contract capture slots continued independently; Gate R probes themselves used `refresh=false` or `cache_only` and did not request provider refresh.

## Compatibility decisions

- All outward fields are additive; existing `session_phase` and legacy `decision_usable` remain available.
- `quote.snapshot` remains schema version `tw.quote.snapshot.v2`; the registry digest changed because its additive field inventory changed.
- No migration was necessary because same-session actual-trade retention uses existing quote snapshots.
- Frontend and MCP remain thin consumers of backend-owned market/calendar/freshness semantics.
- Public capability snapshot was updated only in the repo. The standalone `C:\GPT_MCPtool\OMI_search` runtime has not been changed at Gate R.

## Remaining evidence and risks

- Fixed-time deterministic cases T00-T19 passed, but exact live-session outward capture at 07:59-08:01, 08:30-09:02 and 13:25-13:34 is still `not_observed` unless already captured on the required surface.
- Existing 2026-08-05 raw/persisted provider evidence is real, but it does not automatically prove the new AI/MCP/frontend runtime during those windows.
- A naturally delayed opening or close may remain `not_observed`; no broad all-market provider scan will be used to force it.
- The formal runtime now serves the current contract and passed Gate R; this does not prove tomorrow's live preopen/opening-handoff behavior.
- The worktree contains unrelated dispatch, breadth, Radar and other edits; this task did not revert or isolate those user-owned changes.

## Next step

- Run the staged live-session acceptance probes tomorrow; do not relabel deterministic, isolated or formal-runtime evidence as `live_session_passed`.
- No additional formal restart is required unless source changes again before those probes.
- Commit and push require separate explicit instructions.
