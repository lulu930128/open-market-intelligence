# Validation Strategy

## 原則

- 驗證面跟著work package風險增加；不把full suite、runtime restart、外部refresh或live subscription當預設。
- 優先使用repo wrapper：`scripts/run-safe-validation.ps1`。它會對child process設timeout並把log放在 `.tmp/validation/<timestamp>`。
- 每次保存：命令、exit code、passed/failed/skipped counts、log path、task-owned failure與unrelated baseline failure的區分。
- external provider、runtime adoption、GUI與live session都需要當下明確scope；不得由unit tests推論通過。

## V0 — Docs / plan

適用：BASE-02與純文件更新。

- strict UTF-8讀回、無BOM、newline、trailing whitespace。
- Markdown fences / required headings。
- JSON artifacts `ConvertFrom-Json`。
- `git diff --check`；既有LF/CRLF warning與whitespace error分開記錄。

## V1 — Shared contracts / quality / Gateway

建議命令：

```powershell
.\scripts\run-safe-validation.ps1 `
  -Profile backend `
  -BackendPytestArgs @(
    "backend/tests/test_market_data_contracts.py",
    "backend/tests/test_market_data_integration_contracts.py",
    "backend/tests/test_market_data_provider_catalog_v2.py",
    "backend/tests/test_market_data_gateway.py",
    "backend/tests/test_market_data_resolution.py",
    "backend/tests/test_market_data_quality_policy.py"
  )
```

必要案例：

- required fields、minimum authority、allow partial、canonical lineage。
- missing / stale / future timestamp。
- cache-only zero acquisition、require-live truthful failure。
- bounds、transaction rollback、mandatory reread、attempt route subset。
- quote/depth/auction/bar typed result與stable reason codes。

## V2 — KGI canonical / lease / quote-depth

建議 targeted files：

```powershell
.\scripts\run-safe-validation.ps1 `
  -Profile backend `
  -BackendPytestArgs @(
    "backend/tests/test_tw_public_quote_platform.py",
    "backend/tests/test_taiwan_stock_quote_depth.py",
    "backend/tests/test_kgi_superpy_quote.py",
    "backend/tests/test_market_data_research_lease_v2.py",
    "backend/tests/test_market_data_control_plane_v2.py",
    "backend/tests/test_tw_data_core_boundaries.py"
  )
```

必要案例：

- MIS regression、KGI/MIS deterministic selection、legacy lineage fail closed。
- trial/indicative不是actual trade；depth/auction/quote不混型。
- owner-scoped/redacted lease、heartbeat、symbol switch、cancel、timeout、cleanup residual=0。
- router/provider import guard與GET zero IO/commit/subscription。

## V3 — Intraday bars

```powershell
.\scripts\run-safe-validation.ps1 `
  -Profile backend `
  -BackendPytestArgs @(
    "backend/tests/test_intraday_trend.py",
    "backend/tests/test_intraday_history.py",
    "backend/tests/test_intraday_contract_remediation.py",
    "backend/tests/test_ohlc_intraday_overlay.py",
    "backend/tests/test_tw_public_quote_platform.py",
    "backend/tests/test_tw_data_core_boundaries.py"
  )
```

必要案例：GET zero IO/mutation、explicit refresh bounds、NStock/Yahoo descriptor selection、raw lineage、derived 5m metadata、quote/bar separation。

## V4 — Current index / breadth

```powershell
.\scripts\run-safe-validation.ps1 `
  -Profile backend `
  -BackendPytestArgs @(
    "backend/tests/test_market_index_daily_stats.py",
    "backend/tests/test_tw_official_index_platform.py",
    "backend/tests/test_tw_official_breadth_platform.py",
    "backend/tests/test_tw_market_breadth_session_contract.py",
    "backend/tests/test_tw_data_core_boundaries.py"
  )
```

必要案例：completed official不回退、current provisional分離、unknown不轉0、coverage/scope、TAIEX/TPEX venue/session、GET zero IO。

## V5 — Cross-surface / frontend

Backend contract：

```powershell
.\scripts\run-safe-validation.ps1 `
  -Profile backend `
  -BackendPytestArgs @(
    "backend/tests/test_ai_realtime_contract.py",
    "backend/tests/test_ai_public_v4_contract.py",
    "backend/tests/test_ai_outward_contract.py",
    "backend/tests/test_omi_mcp_server.py",
    "backend/tests/test_mcp_schema_contract.py",
    "backend/tests/test_tw_data_core_cold_read.py",
    "backend/tests/test_tw_data_core_boundaries.py"
  )
```

Frontend：

```powershell
.\scripts\run-safe-validation.ps1 -Profile frontend -SkipBuild
```

在KGI/front-end cutover或final integration時再加：

```powershell
.\scripts\run-safe-validation.ps1 -Profile frontend -IncludeBuild
```

只有存在實際互動/畫面風險時使用browser screenshot / DOM evidence；backend green不等於UI通過。

## V6 — Final source integration

```powershell
.\scripts\run-safe-validation.ps1 -Profile quick
.\scripts\run-safe-validation.ps1 -Profile backend
.\scripts\run-safe-validation.ps1 -Profile frontend -IncludeBuild
```

只有task-owned targeted failures已清零才進final profiles。若full profile需要，必須先確認timeout與dirty worktree不會把無關工作納入誤判。

## V7 — DB migration

- 在disposable DB copy跑upgrade、schema inspection、data compatibility、downgrade、re-upgrade。
- 記錄前後revision、row counts、null lineage counts、orphan raw IDs、unique/index constraints。
- 不刪除、重建或覆蓋 `data/open_market_intelligence.db`。
- existing lineage gap不做silent mass backfill；若來源無法證明，維持missing/compatibility。

## V8 — Runtime adoption

前置：使用者明確授權named component lifecycle。

- 讀launcher log的實際 `selected=`，不硬編preferred port。
- 驗證source fingerprint / runtime identity / interpreter / migration revision。
- backend direct readiness、frontend proxy readiness、API contract與DB read分層驗證。
- 對GET routes使用可觀察test double或provider call counter證明zero IO；不能只看200 response。
- 實際打開TW UI並確認quote/depth/chart/index/breadth可見狀態與limitations。

## V9 — M5 live acceptance

- SourceOnly只代表source-ready。
- Preopen、Opening、Regular、Closing Auction分別保存獨立正式session artifact。
- symbol switch驗證L5、舊symbol lease消失、subscription bounds。
- cleanup驗證active handles=0；未知viewer lease不force release。
- duplicate trade、trial leak、cumulative decrease都必須為0。
- 缺任何時段：該gate `PENDING`，不得以fixture/replay/post-close資料補造。

## Evidence naming

建議在本task的 `artifacts/` 使用：

```text
wp-<lowercase-id>-source-<YYYYMMDD>.json
wp-<lowercase-id>-validation-<YYYYMMDD-HHmm>.md
wp-<lowercase-id>-runtime-<YYYYMMDD-HHmm>.json
wp-live-01-<session>-<YYYYMMDD-HHmm>.json
```

Artifact不得包含credentials、account資料、private lease IDs或未redact raw payload。
