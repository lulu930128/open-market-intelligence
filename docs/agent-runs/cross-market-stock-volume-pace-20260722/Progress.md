# Progress

## Status

- Current phase: complete
- Last updated: 2026-07-23 Asia/Taipei

## Completed

- Confirmed from the supplied US screenshot that TSM's 11:36 cumulative volume is compared with a full-day 20-day average (`-73.08%`).
- Traced current US/JP/KR intraday services: each uses a bounded Yahoo intraday request and memory cache, but does not persist reusable multi-session stock history.
- Confirmed `market_intraday_bar` can hold market/symbol/provider-specific intraday bars without a schema change.
- Added one backend-owned same-market-minute volume-pace contract shared by TW, US, JP, and KR stocks.
- Persisted bounded regular-session minute history into the existing `market_intraday_bar` table and reconciled complete sessions against finalized daily volume.
- Replaced the misleading US full-day comparison and JP/KR daily-volume fallback in the `today` technical view.
- Added explicit `ready`, `partial`, and `empty` states, sample counts, excluded-session diagnostics, warnings, and source references.
- Added frontend projections for TW, US, JP, and KR detail panels without moving calculation or freshness rules into the UI.
- Added backend regression coverage for the shared calculator and all four market integrations.

## Validation evidence

- Screenshot: US `today` view shows current cumulative volume `4,191,752` and full-day-relative volume `-73.08%`.
- Repo trace: US/JP/KR intraday routes all receive a database session, allowing service-owned bounded persistence.
- Full safe backend profile: compileall passed and `917 passed` in `98.40s`.
- Frontend lint and TypeScript typecheck passed.
- Next.js production build passed after the sandbox-only `spawn EPERM` was rerun in the permitted execution context.
- Live cache-only runtime probes:
  - US `TSM`: `partial`, 4 complete prior sessions.
  - JP `7203.T`: 322 points, `partial`, 3 complete prior sessions.
  - KR `005930.KS`: 361 points, `partial`, 4 complete prior sessions.
- Live responses kept provisional history visible instead of emitting a full-day-relative percentage.

## Decisions made

- Keep the calculation in backend and expose one cross-market-compatible `volume_pace` envelope.
- US pace is regular-session-only; JP/KR use their regular-session parser semantics.
- Require at least three complete prior sessions before showing a numeric pace ratio; five sessions are required for `ready`.
- Reconcile minute history with finalized daily volume and exclude incomplete or unreconciled sessions.

## Known issues / risks

- A bounded provider bootstrap normally yields fewer than five complete prior sessions during an active day, so first-run output is expected to remain `partial` until local history accumulates.
- The 20-session baseline improves incrementally; it is not silently backfilled with full-day averages.

## Next step

- Observe local history accumulation through normal use; no unbounded backfill is required.
