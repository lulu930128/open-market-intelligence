# SEC Ownership Operations

## Form 13F bounded history sync

Official release discovery is an explicit write operation. GET contracts never download archives or rebuild projections.

```powershell
.\.venv\Scripts\python.exe scripts\sync-us-sec-13f-history.py --max-releases 4
```

- Default batch size is four releases; `--max-releases` is bounded to 60.
- A release is promoted only after ZIP validation, Parquet creation, metadata reconciliation, storage-budget validation, and checkpoint persistence succeed.
- Reruns skip current releases by official source URL. A failed release leaves prior current partitions intact.
- `--cached-manifest` prevents a manifest network refresh. `--include-completed`, `--force-download`, and `--force-rebuild` are maintenance-only controls.
- Full-history completion does not imply full ticker coverage. Identifier mapping is a separate versioned OpenFIGI process and unresolved CUSIPs remain visible.

## Integrity verification

```powershell
.\.venv\Scripts\python.exe scripts\verify-us-sec-13f-warehouse.py --require-full-history
.\.venv\Scripts\python.exe scripts\verify-us-sec-13f-warehouse.py --require-full-history --verify-hashes
```

The fast check verifies current partition paths, status, file sizes, manifest coverage, and the 32 GiB storage guard. The hash mode additionally streams every Parquet file and compares its SHA-256 with SQLite metadata.

## Backup and restore boundary

The capability has three coordinated local assets:

1. `data/open_market_intelligence.db`: release, checkpoint, filing metadata, identifier mapping, and symbol projections.
2. `data/cache/us_sec/ownership/warehouse`: current immutable Parquet partitions.
3. `data/cache/us_sec/ownership/archives/form-13f`: official source ZIP files and cached manifest.

For a complete point-in-time backup, pause SEC ownership jobs, create the verified SQLite backup with `scripts/backup-omi-sqlite.py`, and copy both cache directories without modifying their relative paths. Run the warehouse verifier against the restored set before starting jobs or the runtime. If Parquet is missing but an official ZIP remains, the corresponding release can be rebuilt explicitly; never mark a missing partition current by editing SQLite.

## Failure recovery

- Provider or manifest failure: retain cached manifest and completed releases; rerun a bounded batch later.
- Download interruption: `.incoming` is not promoted and can be retried safely.
- Parse or reconciliation failure: release/checkpoint/provider event is marked failed; previous current partition remains readable.
- Missing or corrupt Parquet: verifier reports the exact release; run the quarter sync with the official URL and `force_rebuild=true`.
- Mapping failure or absent OpenFIGI key: warehouse remains queryable by CUSIP; symbol projections stay partial and must not be described as full-market coverage.

## OpenFIGI mapping and projection rebuild

Set `OPENFIGI_API_KEY` only in the local ignored `.env`; never place the value in docs, logs, fixtures, or Git. The authenticated mapper sends at most 100 jobs per request, spaces request starts by at least 0.26 seconds, and retries one HTTP 429 using bounded `Retry-After` handling.

Queue bounded 5,000-identifier slices until `requested_count` is zero:

```powershell
$body = @{
  cusips = @()
  max_identifiers = 5000
  refresh = $false
  rebuild_projections = $false
} | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8400/api/us-market/sec/ownership/jobs/13f-mapping-sync" `
  -ContentType "application/json" `
  -Body $body
```

After all CUSIPs have a versioned result, queue one final job with `max_identifiers=1` and `rebuild_projections=true`. The rebuild intentionally performs a fresh warehouse coverage scan and uses:

- DuckDB `memory_limit=1536MB` with external spill under `data/cache/us_sec/ownership/projection-tmp`.
- A JSONL shadow artifact so the long aggregation does not hold a SQLite transaction or replace the live projection early.
- One final atomic bulk replace of the live `openfigi.v3` rows; failures before commit leave the previous projection readable.

The 2026-08-13 full rebuild produced 252,796 projection rows for 10,650 symbols. Its shadow artifact reached about 5.8 GiB, and the completed local SQLite database was about 20.43 GiB. Treat this as a long, disk-intensive maintenance job; do not run it from GET/read paths or concurrently with another projection rebuild.
