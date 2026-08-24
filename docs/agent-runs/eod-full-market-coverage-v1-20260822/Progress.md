# Progress

## Status

- Current phase: complete（source、runtime adoption 與 startup catch-up 驗證完成；資料依 checkpoint 持續收斂）
- Last updated: 2026-08-22 14:43 Asia/Taipei

## Completed

- 已讀 current product truth、BackendArchitecture 與兩個適用 skill 的必要 reference。
- 已盤點本機 universe 與 coverage：TW 1,973 active ordinary stocks；US 7,427 active non-ETF/non-test stocks。
- 已確認現有 per-symbol dataset registry、TW official bulk source、US Nasdaq Trader universe 與 Yahoo per-symbol daily provider 邊界。
- 已固定 v1 capability contract、non-goals、request bounds 與 stop-and-fix rules。
- 已新增 0064 migration、coverage checkpoint model、TW/US full-market dataset registry 與 cache-only projection。
- 已完成 TW official bulk repair、US Yahoo bounded resumable shard、provider backoff、tracked job、POST API 與 scheduler startup catch-up。
- 已將 full-market operation 保持為 scheduler-only lifecycle，不加入 AI fill allowlist。
- 已加入 partial payload destructive replacement guard。
- 已將 tracked job 接到共用更新狀態，依 target 歸入台股／美股並呈現 backend coverage partitions。
- 已完成 cache-only GET、tracked POST、啟動補跑、週期 reconcile、provider backoff 與 TW release window。

## Validation evidence

- `git status --short --branch`: worktree 有大量既有 Market Data Foundation/KGI/portfolio/UI 修改；本任務需以 localized diff 共存。
- Read-only SQLite inventory: `us_stock_master=12,710 active`，其中 stock 7,460、ETF 5,250、test issue 33；TW ordinary stock 1,973。
- Source inspection: TWSE `STOCK_DAY_ALL` 與 TPEx `tpex_mainboard_quotes` 為既有 official bulk endpoint；US daily refresh 為 per-symbol provider call。
- `pytest tests/test_eod_coverage.py tests/test_eod_coverage_scheduler.py tests/test_market_data_registry.py -q`: 15 passed（初版）；rate-limit regression 加入後 EOD tests 9 passed。
- `pytest tests/test_database_migrations.py tests/test_api_contract_inventory.py -q`: 15 passed、60 subtests passed。
- `pytest tests/test_market_data_registry.py tests/test_ai_capability_contract.py tests/test_ai_capability_resolution_registry.py -q`: 88 passed、228 subtests passed。
- Live read-only coverage computation: TW 1,973 universe，current 132／stale 1,838／missing 3；US 7,427 universe，current 2／stale 300／missing 7,125；兩邊 query 均少於 0.5 秒。
- `run-safe-validation.ps1 -Profile backend`（20260822-142316）：compileall passed；75 targeted tests passed；`git diff --check` passed。
- `run-safe-validation.ps1 -Profile frontend`（20260822-142355）：lint passed；TypeScript `tsc --noEmit` passed；`git diff --check` passed。
- Source validation 階段未執行外部 provider refresh、DB migration 或 runtime restart；後續由使用者重啟觸發正常 migration 與 startup catch-up。
- 使用者重啟後 live launcher 選到 backend `127.0.0.1:8400`／frontend `127.0.0.1:3000`；health 回報正確 repo、`.venv` 與 proxy target。
- Live migration：Alembic 已由 `20260819_0063` 升級到 `20260822_0064`，checkpoint table 存在。
- Startup catch-up TW job `6576`：2/2 official bulk sources success；coverage 1,947 current／15 partial／9 stale／2 missing（universe 1,973）。
- Startup catch-up US job `6577`：bounded shard 正常完成並保存 cursor `AGM$H`；180 current／302 stale／6,945 missing（universe 7,427），192 provider successes、15 errors，public status 如實為 `partial`。
- Live cache-only GET 回傳兩個 checkpoint；frontend dev chunk 包含新 job type，`/omi-ui-health` 指向 backend `8400`。

## Decisions made

- 使用新 checkpoint table，而不把跨交易日 durable state 塞進只代表單次 execution 的 `job_run`。
- 使用 full-market stock universe，不把 enabled watchlist 誤稱全市場。
- TW 可一次兩個 bulk source repair；US 先以 bounded resumable shard 實作，並保留 bulk provider 後續擴充點。
- Full-market reconcile 不進 AI tool allowlist，只能由 explicit POST 或 backend scheduler 啟動。

## Known issues / risks

- `backend/app/db/models.py`、`backend/app/config.py` 等目標檔已有使用者既有變更；修改必須鎖定局部區塊。
- 美股 free per-symbol provider 仍可能 rate limit；v1 已有 error budget 與 scheduler backoff，但不得保證單次或固定時間內完成。
- Yahoo 對 Nasdaq Trader 的 NYSE punctuation symbol 不是同一命名（例如 `ABR$D` 對 Yahoo `ABR-PD`）；目前會標記 provider 404、保存 cursor 並退避，不會把失敗包成 current。Provider-specific symbol mapping 仍是後續品質改善。

## Next step

- 讓 scheduler 依 checkpoint 繼續收斂美股；另行加入經驗證的 Nasdaq Trader → Yahoo provider-symbol mapping，降低特別股／權證／單位的 404。
