# Cross-market stock same-time volume pace

## Goal

- Replace misleading intraday full-day volume comparisons with a backend-owned same-market-minute volume pace for TW, US, JP, and KR stocks.
- Keep missing, partial, provisional, and complete historical coverage explicit.

## Non-goals

- Market indices, market-wide volume, crypto, resources, automated trading, or unbounded full-market backfill.
- Redesigning the stock detail panels or changing daily-chart volume indicators outside the `today` timeframe.

## Hard constraints

- Backend owns the calculation, session rules, persistence, and freshness status.
- Existing intraday routes remain backward compatible.
- Provider calls remain bounded to the selected symbol and one compact intraday history range.
- US volume pace uses regular-session volume even when the chart includes extended hours.
- JP lunch-break/non-regular points do not enter the baseline.
- No database reset or schema change; reuse `market_intraday_bar`.

## Context

- Repo: `C:\project\Open Market Intelligence`
- Related systems: backend market services, SQLite intraday cache, US/JP/KR frontend detail panels.
- Current known state: TW stock pace is implemented. US compares current cumulative volume with a full-day 20-day average. JP/KR `today` views still expose daily volume-relative metrics rather than a true intraday pace.

## Deliverables

- Shared same-time volume-pace calculation and bounded intraday-history persistence.
- US/JP/KR intraday responses exposing `volume_pace`.
- US/JP/KR `today` technical metrics consuming the backend result.
- Targeted backend and frontend regression coverage plus live selected-symbol smoke evidence.

## Done criteria

- TW behavior remains covered and compatible.
- US/JP/KR individual-stock responses distinguish `ready`, `partial`, and `empty` pace states.
- Daily-average comparisons are not shown as intraday volume pace.
- Targeted tests, compile, frontend typecheck, and bounded live probes pass.

## Open questions / assumptions

- Yahoo `5d / 1m` is used as the bounded bootstrap surface already supported by OMI's intraday provider contract; longer history accumulates locally over subsequent sessions.
