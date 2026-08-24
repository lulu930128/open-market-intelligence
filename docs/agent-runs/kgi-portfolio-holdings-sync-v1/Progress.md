# Progress

## Current status

Implementation and local validation complete. Live database replacement is intentionally not executed because the KGI account service did not initialize during the bounded smoke test.

## Confirmed decisions

- The target is the existing `portfolio_holding` / `PortfolioHoldingsPanel` surface, not watchlists.
- Sync is explicit and market-scoped (`tw` or `us`).
- Successful data replaces provider-owned fields; failed data leaves current rows intact.
- Matching holdings retain user-authored note, tags, horizon, and opened date.
- Taiwan cost basis comes from KGI inventory data when available.
- US cost basis is represented as unavailable because the official KGI US position response does not provide it.
- No order command is exposed.

## Validation evidence

- Portfolio/provider/API targeted suite: 41 tests passed with 60 contract subtests.
- Empty and legacy SQLite databases both migrated to head successfully.
- Frontend TypeScript, ESLint, and production build passed.
- Full backend safe validation reached 100% test execution with no reported test failure, but pytest exited during session cleanup because Windows denied access to the wrapper basetemp directory.
- Bounded live KGI smoke returned `failed` for both `tw` and `us`; the sanitized classification was account service / CA component / certificate initialization.

## Live-data state

- No production holding rows were overwritten.
- No live database migration or runtime restart was performed after the failed provider smoke.
- The next launcher restart will apply the Alembic migration; live sync remains explicit through the UI button.
