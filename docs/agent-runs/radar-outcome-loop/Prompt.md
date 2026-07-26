# Radar Outcome Loop v1

## Goal

- Build a minimal closed loop for Taiwan watchlist radar: save an immutable daily radar snapshot, evaluate the next available trading-day outcome from local daily bars, and expose the result through backend API plus the Today Radar UI.

## Non-goals

- Do not turn radar into an automatic trade signal or order system.
- Do not auto-adjust radar rules, weights, or prompts from backtest results.
- Do not run broad historical backfills, external API refreshes, or paid/LLM calls in this version.
- Do not implement US/JP/KR radar outcome support in v1.

## Hard constraints

- GET/read paths must not create expensive or hidden DB side effects.
- Snapshot rows must preserve what OMI knew at that time, including stale/data-limit state and rule version.
- T+1 outcome must use existing local `market_daily_price` rows only.
- Outcome labels must be bucket-aware; "up next day" is not a universal hit condition.
- Data gaps, unevaluable rows, and sample size must be visible.

## Context

- Repo: `C:\project\Open Market Intelligence`
- Related systems: `backend/app/watchlists/radar_service.py`, `backend/app/routers/watchlists.py`, `backend/app/db/models.py`, `frontend/src/components/WatchlistRadarPanel.tsx`
- Current known state: radar is calculated on demand from ranking rows and returned as `buckets + results`; no durable radar snapshot or outcome table exists yet.
- Product direction: OMI is a research/decision-support workbench, not an auto-trading system.

## Deliverables

- DB models and Alembic migration for radar snapshot runs/items/outcomes.
- Backend service that saves current radar snapshot and evaluates latest or requested snapshot outcome.
- API endpoints for explicit snapshot creation and outcome retrieval/evaluation.
- Frontend radar panel entry point showing the latest outcome summary and save/evaluate controls.
- Targeted backend tests plus frontend type/lint validation.

## Done criteria

- Snapshot creation is idempotent per group/mode/trade date/rule version.
- T+1 evaluation can mark hit/miss/neutral/unevaluable with measurable price/volume fields.
- UI can show when no snapshot or no next-day data exists without hiding the limitation.
- Targeted validation passes.

## Open questions / assumptions

- v1 uses the next available local `market_daily_price.trade_date` after the snapshot trade date as T+1.
- v1 starts with Taiwan watchlist radar only because it depends on `market_daily_price`.
- Rule version is a static string in v1 and can later become configuration/versioned metadata.
