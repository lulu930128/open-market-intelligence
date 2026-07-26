# OMI Backend Hardening Convergence Progress

## Status

- Current phase: H0-H4 completed; ready for checkpoint review.
- Last updated: 2026-07-13 13:03 Asia/Taipei.
- Baseline commit: `1a4e84762de3aa56dc6447b9edfeebc6271dc3ec`.
- Baseline worktree: clean.

## Completed

- Committed the preceding M0-M9 architecture consolidation as `1a4e847`.
- Confirmed safe-validation baseline: `580 passed, 1 warning`.
- Ran the current CI command with the repo venv: all 580 tests passed, but the unittest runner emitted many SQLite connection ResourceWarnings.
- Reproduced the single pytest warning as an error in `compact_resource_ohlcv_raw_payloads`.
- Traced the warning to an untyped `updated_at` datetime parameter in a SQLAlchemy `text()` UPDATE.
- Confirmed `routers/market.py` is the only router with direct `db.commit()` / `db.rollback()` calls.
- Captured the five Taiwan futures OpenAPI operation IDs and response item schemas.
- Added explicit SQLAlchemy `DateTime(timezone=True)` processing to the resource maintenance raw SQL update.
- Added warning-as-error regression coverage and aligned GitHub backend CI to pytest.
- Made Taiwan futures quote and daily refresh explicit rollback-and-re-raise transaction owners.
- Moved quote fallback job persistence to `market/tw_futures_jobs.py` and `jobs.service` lifecycle methods.
- Moved all five Taiwan futures routes to `routers/tw_market_futures.py`; `market.py` includes the subrouter and re-exports handlers.
- Added a static architecture test that rejects direct transaction calls from router modules.
- Confirmed remaining direct transport imports are intentional stateful workflows, provider adapters or exception typing; no stateless provider IO returned to routers/services.
- Confirmed planned/provider-pending capabilities remain explicit and are not enabled by this refactor.
- Completed full backend validation with 586 tests and no warning summary.
- Completed isolated current-code runtime smoke and removed the process/listener.

## Validation evidence

- `python -m unittest discover -s backend/tests -p "test_*.py"`: `Ran 580 tests ... OK`, with ResourceWarning noise.
- Targeted pytest with `-W error::DeprecationWarning`: failed at `resource_market/maintenance.py:172`, proving the datetime bind root cause.
- Current OpenAPI inventory: 326 total operations, 325 under `/api/*`.
- `git status --short --branch`: clean after checkpoint commit.
- H1 resource suite with deprecations as errors: passed; logs `.tmp/validation/20260713-124941`.
- H2 targeted transaction/futures/jobs/API suite: `18 passed`; logs `.tmp/validation/20260713-125304`.
- H3 targeted API/transaction/futures/jobs suite: `21 passed`; logs `.tmp/validation/20260713-125612`.
- Combined resource/futures/transaction/API regression passed; logs `.tmp/validation/20260713-125806`.
- Strengthened futures query parameter/default contract: API inventory suite passed; logs `.tmp/validation/20260713-130533`.
- Full backend safe validation: `586 passed in 75.89s`; compile and diff check passed; logs `.tmp/validation/20260713-130020`.
- Isolated runtime on port `43214`: 11/11 read-only probes returned HTTP 200.
- Runtime OpenAPI: 326 operations and all five Taiwan futures paths present.
- Runtime cleanup: no listener remained on port `43214`.

## Decisions made

- Align CI with pytest instead of suppressing unittest warnings.
- Use an explicit SQLAlchemy `DateTime` bind parameter instead of global sqlite3 adapter registration.
- Preserve GET refresh behavior and every public Taiwan futures API default.
- Keep provider exception migration outside this slice because US/JP/KR route behavior needs separate characterization.

## Known issues / risks

- US/JP/KR routers still catch `requests.RequestException`; service/domain exception normalization remains a future architecture slice.
- Large transaction-owning market service façades remain intentionally intact unless a responsibility slice has direct tests.
- Planned provider capabilities remain unavailable by design.
- Git continues to report unreachable loose objects during auto packing; repository pruning is not part of this task.

## Next step

- Review the final changed-file scope and create a follow-up checkpoint commit when requested.
