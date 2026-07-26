# OMI Backend Hardening Convergence

## Goal

- 以 checkpoint commit `1a4e847` 為乾淨基線，清除已證實的 backend warning 與 validation drift。
- 移除 Taiwan futures router 對 JobRun persistence 與 transaction 的直接 ownership。
- 在不改 public API contract、DB schema、provider fallback 或 runtime side effect 的前提下，完成下一個可驗證的架構收斂 slice。

## Non-goals

- 不按行數拆分所有大型 service。
- 不新增或啟用 JP/KR/Crypto/KGI planned provider capability。
- 不修改 frontend、MCP、Kuro、資料庫 schema 或本機 SQLite 資料。
- 不觸發 live provider refresh、backfill、付費 quota、report/memory write 或發送流程。
- 不在本批全面改寫 US/JP/KR router 對 provider exception 的相容處理。

## Hard constraints

- Taiwan futures 五條 route 的 method、path、query defaults、operation ID、response schema 與 fallback behavior 必須保持不變。
- `routers/market.py` 必須 re-export 搬移後的 handler，保護既有 import seam。
- Job persistence 必須由 jobs/domain service 擁有；router 不得直接 `commit()`。
- Raw SQL datetime parameter 必須走明確 SQLAlchemy type processor，不依賴 Python 3.12 deprecated sqlite3 adapter。
- CI 與 repo-local backend validation 必須使用同一個 pytest collection surface。

## Context

- Repo: `C:\project\Open Market Intelligence`
- Baseline branch: `codex-kr-market-readiness`
- Baseline commit: `1a4e84762de3aa56dc6447b9edfeebc6271dc3ec`
- Baseline backend: `580 passed, 1 warning`
- Baseline runtime smoke: 9/9 read-only probes HTTP 200
- CI `unittest discover` baseline: 580 tests passed, but emitted many connection ResourceWarnings and used a different runner from `run-safe-validation.ps1`.

## Deliverables

- Typed raw-SQL datetime binding and a warning-as-error regression.
- CI backend test command aligned to pytest.
- Taiwan futures job/fallback domain service and route-family subrouter.
- OpenAPI and import-seam characterization for all five Taiwan futures routes.
- Updated architecture/progress documentation and final validation evidence.

## Done criteria

- The targeted resource maintenance test passes with `DeprecationWarning` promoted to error.
- No router under `backend/app/routers/` calls `db.commit()` directly.
- OpenAPI remains 326 total operations and 325 `/api/*` operations.
- All five Taiwan futures operation IDs and response item schemas are unchanged.
- Full backend safe validation passes with no warning summary from project code.
- Isolated current-code runtime smoke passes and leaves no listener behind.

## Assumptions

- Existing GET refresh query behavior remains a compatibility surface and is not changed in this batch.
- Existing provider/network exceptions may continue to be translated at market-family routers until a separate domain-error migration has full route characterization.
