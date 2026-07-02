# Progress

## Status

- Current phase: done
- Last updated: 2026-06-30 21:53 Asia/Taipei

## Completed

- Inspected existing TWSE MIS usage in `backend/app/market/intraday.py`.
- Inspected market calendar helpers, migration tests, frontend stock detail data flow, and right-column render structure.
- Defined selected-stock-only quote-depth scope and session phase contract.
- Added `taiwan_stock_quote_snapshot` ORM model and Alembic migration.
- Added selected-stock quote-depth parser/service/API at `/api/market/quote-depth/{stock_id}`.
- Added backend tests for phase boundaries, MIS parsing, TPEX exchange mapping, empty wait state, and DB fallback.
- Added `QuoteDepthPanel` and connected it to every non-index stock timeframe with phase-aware polling.
- Added quote-depth mock data to the frontend smoke test fixture.

## Validation evidence

- `.\\.venv\\Scripts\\python.exe -m pytest backend\\tests\\test_taiwan_stock_quote_depth.py -q`: passed.
- `.\\.venv\\Scripts\\python.exe -m pytest backend\\tests\\test_database_migrations.py -q`: passed.
- `npm exec tsc -- --noEmit --incremental false`: passed.
- `.\\scripts\\run-safe-validation.ps1 -Profile backend -BackendPytestArgs backend\\tests\\test_taiwan_stock_quote_depth.py,backend\\tests\\test_database_migrations.py -BackendTestTimeoutSeconds 180`: passed.
- `.\\scripts\\run-safe-validation.ps1 -Profile frontend`: passed.
- `.\\scripts\\run-safe-validation.ps1 -Profile quick`: passed.
- `GET http://127.0.0.1:8400/api/market/quote-depth/2330?refresh=true`: returned `post_close_snapshot`, last `2410`, bid `2410`, ask `2415`, `final_snapshot`.
- Browser desktop smoke at `http://127.0.0.1:3000/?market=tw&group_id=3&stock_id=2330`: switching to `今日` showed `QUOTE DEPTH`, post-close snapshot, last price `2,410`, and no console errors.
- Browser mobile smoke at `390x844`: no framework overlay, but current mobile layout did not enter the stock detail surface, so quote-depth mobile rendering remains unverified.

## Decisions made

- Put the full quote-depth panel above the technical panel in the stock detail right column.
- Show quote depth on daily/weekly/monthly too; quote-depth freshness belongs to the market session, not the selected chart timeframe.
- Treat MIS `f/g` size fields as lot counts and label them as lots.
- Show live ladder only for `preopen_auction`, `regular_live`, and `closing_auction`; show final trade summary for post-close snapshots.

## Known issues / risks

- TWSE MIS can be intermittently unavailable in this environment; the service must show source failures instead of presenting stale data as live.
- The repo has unrelated in-flight changes across crypto, calendar, frontend, docs, and tests; this implementation must keep diffs scoped.
- Existing runtime processes on ports `3000` and `8400` were already running during validation; they may need restart to serve the new backend route and frontend component.
- The running backend/frontend did pick up the new route/component during browser smoke. If stale UI appears later, restart both processes before retesting.

## Next step

- Mobile stock-detail navigation should be revisited separately if mobile support is a target for this surface.

## Follow-up fix 2026-06-30 20:48

- Reason: quote depth was only rendered on the `today` timeframe, so users on `日K` could not see it.
- Fix: quote depth now renders on every non-index stock timeframe while keeping backend phase/freshness as the source of truth.
- Validation: `.\\scripts\\run-safe-validation.ps1 -Profile frontend` passed.
- Validation: `.\\scripts\\run-safe-validation.ps1 -Profile quick` passed.
- Browser evidence: clicking the `2330 台積電` row showed `QUOTE DEPTH` above Technical while `日K` remained active.

## Preview support 2026-06-30 21:05

- Reason: off-hours users cannot validate the trial-auction or live quote-depth layout from real MIS data.
- Fix: added frontend-only `quote_depth_preview=preopen|live` URL mode. It preserves the parameter across Taiwan stock navigation, renders a five-level ladder, and labels the panel as preview data.
- Boundary: preview data is display-only and is not sent back to the backend snapshot/API/DB flow.
- Validation: `npm exec tsc -- --noEmit --incremental false` passed.
- Validation: `.\\scripts\\run-safe-validation.ps1 -Profile frontend` passed.
- Validation: `.\\scripts\\run-safe-validation.ps1 -Profile quick` passed.
- Browser evidence: `quote_depth_preview=preopen` showed `試撮預覽`, `預覽資料`, buy/sell five levels, and the preview warning.
- Browser evidence: `quote_depth_preview=live` showed `盤中預覽`, `預覽資料`, buy/sell five levels, and the preview warning.

## Inline preview controls 2026-06-30 21:17

- Reason: URL-only preview was too easy to miss during normal stock-detail use.
- Fix: added in-panel `真實 / 試撮 / 盤中` controls. `真實` keeps the actual quote-depth response; `試撮` and `盤中` apply the display-only preview transform locally.
- Validation: `.\\scripts\\run-safe-validation.ps1 -Profile frontend` passed.
- Validation: `.\\scripts\\run-safe-validation.ps1 -Profile quick` passed.
- Browser evidence: normal stock detail first showed `收盤快照`; clicking `試撮` showed `試撮預覽` with five levels; clicking `盤中` showed `盤中預覽` with five levels and no console errors.

## Split ladder layout 2026-06-30 21:27

- Reason: the live ladder still looked like stacked rows and carried redundant top summary cards plus `檔`/level labels.
- Fix: live quote-depth now uses a left/right bid-ask layout: left side `張數 / 買價`, right side `賣價 / 張數`, with side totals at the bottom.
- Removed: live-mode `買一`/`賣一`/`Spread`/`委買委賣` metric cards and row-level `買1`/`賣1`/`檔` labels.
- Validation: `.\\scripts\\run-safe-validation.ps1 -Profile frontend` passed.
- Validation: `.\\scripts\\run-safe-validation.ps1 -Profile quick` passed.
- Browser evidence: clicking `盤中` showed the split ladder, no redundant metric cards, no `檔`/level labels, and no console errors.

## Unified real snapshot ladder 2026-06-30 21:38

- Reason: post-close real snapshots should use the same professional split ladder as trial-auction/live views instead of switching back to OHLC summary cards.
- Fix: quote depth now renders the split bid/ask ladder whenever bid or ask levels exist, including `post_close_snapshot` / `final_snapshot`; OHLC cards remain only as a fallback when no depth levels are available.
- Removed: in-panel `真實 / 試撮 / 盤中` preview controls, keeping URL preview support for debug-only visual checks.
- Layout: bid size aligns left, bid price aligns toward the center; ask price aligns toward the center, ask size aligns right. Bar fills start from the center and extend outward on both sides.
- Validation: `.\\scripts\\run-safe-validation.ps1 -Profile frontend` passed.
- Validation: `.\\scripts\\run-safe-validation.ps1 -Profile quick` passed.
- Browser evidence: normal stock detail with no preview parameter showed `收盤快照`, split `張數 / 買價` and `賣價 / 張數` headers, no OHLC cards, no manual preview buttons, and no preview badge.

## Previous-close quote-depth colors 2026-06-30 21:53

- Reason: bid/ask side should not decide quote-depth row colors. Taiwan quote colors should follow yesterday close: above previous close is red, below previous close is green, flat is neutral/white.
- Fix: row price text and volume bars now use `price - previous_close` for tone. The bid/ask side still controls horizontal anchoring only.
- Fallback: if `previous_close` is unavailable, valid prices use a neutral tone instead of guessing red/green.
- Validation: `.\\scripts\\run-safe-validation.ps1 -Profile frontend` passed.
- Validation: `.\\scripts\\run-safe-validation.ps1 -Profile quick` passed.
- Browser evidence: normal `2330 台積電` detail showed post-close bid rows above previous close rendered red (`text-omi-market-up`, `bg-omi-market-up/10`) instead of the old bid-side green, with no console warnings or errors.
