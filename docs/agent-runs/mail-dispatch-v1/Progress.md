# Progress

## Status

- Current phase: v1 implemented and verified
- Last updated: 2026-06-22 22:25 +08:00

## Completed

- Scoped v1 as manual mail dispatch only.
- Confirmed repo has existing FastAPI, SQLAlchemy/Alembic, `JobRun`, and watchlist/AI report foundations.
- Added backend dispatch recipient groups, delivery snapshots, SMTP sender, preview builder, job task, API router, and Alembic migration.
- Added Settings > Dispatch UI for recipient groups, fixed-template preview, manual send, and delivery history.
- Added focused backend dispatch tests and aligned the scheduler integration test with the refresh execution resolver boundary.
- Added first-pass mail-safe HTML report rendering with inline styles, metric cards, tables, data-limit sections, and preserved text/plain output.
- Added HTML/Text preview toggle in Settings > Dispatch.
- Verified Gmail SMTP can send to the user's own mailbox from local `.env` settings.
- Expanded Taiwan market overview evidence with market structure, price-move distribution, value leaders, industry strength/weakness, concentration, and richer text/html sections.
- Changed report HTML from narrow briefing layout to desktop-oriented 1080px report canvas with table-based two-column sections for related report blocks.
- Enlarged Settings > Dispatch HTML preview modal so the desktop report layout can be inspected before sending.
- Added market/country selection to Settings > Dispatch report controls.
- Added US market-overview dispatch preview backed by the existing US watchlist ranking with Yahoo intraday overlay.

## Validation evidence

- `.\.venv\Scripts\python.exe -m compileall backend\app` passed.
- `$env:PYTHONPATH = 'backend'; .\.venv\Scripts\python.exe -m pytest backend\tests\test_dispatch.py -q` passed: 5 tests.
- `.\scripts\run-backend-tests.ps1` passed: 330 tests.
- `npm run lint` passed.
- `npm exec tsc -- --noEmit --incremental false` passed.
- `npm run build` passed.
- `.\.venv\Scripts\python.exe -m compileall backend\app\dispatch` passed.
- `.\.venv\Scripts\python.exe -m compileall backend\app\ai backend\app\dispatch` passed.
- `$env:PYTHONPATH = 'backend'; .\.venv\Scripts\python.exe -m pytest backend\tests\test_dispatch.py -q` passed after HTML renderer assertions.
- Gmail SMTP smoke test sent 1/1 test message successfully.
- Local market overview preview smoke check produced 55 text lines and HTML sections for market structure, value focus, and industries.
- `.\scripts\run-backend-tests.ps1` passed after market overview expansion: 330 tests.
- Desktop layout smoke check confirmed `width="1080"`, two-column cells, and all market report sections in generated HTML.
- `npm run lint`, `npm exec tsc -- --noEmit --incremental false`, and `npm run build` passed after preview modal changes.
- `.\.venv\Scripts\python.exe -m compileall backend\app\dispatch` passed after US market dispatch support.
- `$env:PYTHONPATH='backend'; .\.venv\Scripts\python.exe -m pytest backend\tests\test_dispatch.py -q` passed: 6 tests.
- `npm run lint`, `npm exec tsc -- --noEmit --incremental false`, and `npm run build` passed after market selector UI changes.
- Live `/api/dispatch/preview` smoke check with `scope_id=us` succeeded; `as_of=2026-06-22T10:09:12-04:00`, intraday overlay coverage was 30/67 symbols.

## Decisions made

- SMTP secrets stay in environment variables.
- Preview must remain read-only and work without SMTP.
- Dispatch email should be multipart text/plain + text/html; HTML uses inline styles and no JavaScript.
- Country selection is template scope, not a separate dispatch type. `market_overview` now accepts `scope_id=tw` or `scope_id=us`.
- US market overview is explicitly a US watchlist-pool realtime overview, not full US-market breadth.
- Watchlist brief remains Taiwan-only in v1; the UI disables it when market is US.
- Scheduling and rapid market-move alerts are follow-up milestones, not v1.

## Known issues / risks

- The current Gmail App Password was provided interactively for local testing and should be rotated after validation.
- Existing worktree contains unrelated changes; this task must avoid reverting them.

## Next step

- Restart backend/frontend if needed, then send one real HTML dispatch to the "自己" recipient group and inspect Gmail rendering.
