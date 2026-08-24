# M5 Retry Preparation

## Goal

- 在正式交易時段前把環境推進到 `READY_FOR_MANUAL_M5`，但不提前宣告 Foundation 1.1 runtime accepted。
- 讓正常 `off` 或重開機後的 OMI，能透過正式 launcher owner 重新建立 process-scoped `compare` runtime。
- 讓明早 preflight 在任何 KGI viewer lease 前完成 source、calendar、runtime、frontend、MCP 與零殘留檢查。

## Confirmed root cause

- `CANONICAL_MARKET_DATA_MODE` 的正式預設維持 `off`。
- 2026-08-19 22:21:49 的 compare launcher 已完成 M3/M4 evidence。
- Windows 於 2026-08-19 23:22:20 重新開機；一般啟動流程於 23:24:46 建立新 launcher，backend 於 23:24:51 以 `off` 啟動。
- 2026-08-20 08:37 preopen 因 effective mode=`off` 正確 fail closed；當時沒有建立 viewer lease、KGI subscription 或 provider sample。
- 這不是 KGI semantic failure，而是 acceptance runtime 在 reboot 後沒有重新 bootstrap。

## Corrected design

### Official owner handoff

- `scripts/omi-launcher.ps1` 提供 local-only named control events：`Exit` 與 `RestartServices`。
- 第二個 launcher instance只傳送 control event；它不能搶 mutex、不能直接停止不明 process。
- `Exit` 由既有 tray owner 執行原本的 `Stop-Services`與 application shutdown。
- preflight等待launcher mutex釋放後，才以同一支正式launcher與process-scoped mode建立新runtime。
- Production default、`.env`、DB與backend source均不因acceptance bootstrap改成compare。

### Single preflight entry

```powershell
cd "C:\project\Open Market Intelligence"
.\scripts\invoke-mdf-m5-preflight.ps1 `
  -RuntimeAction Prepare `
  -ExpectedMode compare `
  -ExpectedDate 2026-08-21
```

`Prepare` 必須依序驗證：

1. local date。
2. source checkpoint file hash與14個target file hashes。
3. official launcher owner handoff與新listener lineage。
4. `/api/system/health` effective mode與`/api/system/readyz`。
5. TWSE calendar source、current cache、verified year、trading day與warning。
6. live `/api/ai/tools` digest。
7. frontend project/proxy identity。
8. stdio MCP `initialize -> notifications/initialized -> tools/list`。
9. 2330 viewer lease與KGI bridge process baseline皆為0。

任何失敗都產生machine-readable artifact並停止；preflight本身不建立viewer lease，除非今晚明確加上`-RunViewerReadiness`。

### Runtime acceptance commands

OFF baseline：

```powershell
.\scripts\invoke-mdf-m5-preflight.ps1 `
  -RuntimeAction Check `
  -ExpectedMode off `
  -ExpectedDate 2026-08-20
```

建立compare：

```powershell
.\scripts\invoke-mdf-m5-preflight.ps1 `
  -RuntimeAction Prepare `
  -ExpectedMode compare `
  -ExpectedDate 2026-08-20
```

驗證component-owned service restart仍保留compare：

```powershell
.\scripts\invoke-mdf-m5-preflight.ps1 `
  -RuntimeAction RestartServices `
  -ExpectedMode compare `
  -ExpectedDate 2026-08-20
```

今晚Quote-only readiness：

```powershell
.\scripts\invoke-mdf-m5-preflight.ps1 `
  -RuntimeAction Check `
  -ExpectedMode compare `
  -ExpectedDate 2026-08-20 `
  -RunViewerReadiness
```

## Viewer readiness boundary

- 只允許TW 2330、Quote viewer lease、單一bounded subscription。
- 不呼叫Account、Portfolio、Order、backfill、repair或交易operation。
- before/active/after記錄active lease、safe stream summary與KGI bridge process identity；不保存lease id、raw payload或credential。
- acquire後35秒內只接受`subscribing`、`live`或post-close可解釋的`stale`；`disabled`、`unavailable`與`reconnect_failed` fail closed。
- release後active leases必須回0；最多等待150秒，KGI bridge process必須回baseline。

## Artifact policy

- 所有preflight與session artifact使用日期／timestamp命名且不可覆寫。
- 2026-08-20失敗保留為`session-preopen-20260820-failed.json`。
- 2026-08-21正式產物使用：
  - `m5-preflight-<timestamp>.json`
  - `session-preopen-20260821.json`
  - `session-opening-20260821.json`
  - `session-regular-20260821.json`
- Final checkpoint直接列出被接受的dated artifact，不用覆寫歷史失敗證據。
- Artifact另保存launcher、preflight與MCP smoke helper SHA-256；Foundation checkpoint仍獨立證明backend/canonical target source未變。

## Tonight done criteria

- OFF baseline preflight passed。
- 新launcher control seam已被正式runtime採用。
- off -> compare bootstrap passed。
- component-owned RestartServices後compare仍pass且listener PID更新。
- public contract、frontend、MCP與viewer baseline pass。
- 2330 Quote-only viewer readiness及idle cleanup pass。
- 明早runbook可直接執行。
- 不修改production default、不進02、不碰Account/Order、不commit/push。

只有全部完成才標記`READY_FOR_MANUAL_M5`。

## Stop-and-fix

- Source checkpoint或任一target hash改變。
- Launcher owner、listener、project root、python或selected port無法證明。
- Effective mode不是expected mode。
- Control event無法由正式owner執行。
- Calendar不是current authoritative trading-day evidence。
- Public catalog、frontend proxy或MCP transport drift。
- Viewer baseline不為0、subscription/process leak或KGI runtime unavailable。
- 需要broad-kill、永久compare、DB寫探測、Account/Order或降低M5標準。

## Execution result — 2026-08-20

- Result：`READY_FOR_MANUAL_M5`。
- Foundation final status仍為`source-complete / runtime acceptance pending`；未宣告`runtime-accepted`或`ready-for-02`。
- OFF baseline、首次compare bootstrap、component-owned restart、第二次冪等bootstrap均pass。
- 2330 Quote-only readiness與release/idle cleanup pass；before=`0/0`、active=`1 lease/2 bridge processes`、after=`0/0`。
- Launcher control seam變更後，off/shadow/compare process identity均以新版launcher重建；final running mode=`compare`。
- 未重跑`refresh=true` runtime same-payload probe，避免新增外部fetch與legacy quote upsert；此限制保留在summary artifact，不把unknown偽造為0。
- Machine-readable summary：`artifacts/m5-retry-preparation-20260820.json`。
- Parser、syntax、JSON/UTF-8讀回、stdio MCP、current health/ready、viewer/bridge零殘留與targeted diff check均pass。
- 明早操作入口：`M5ManualRunbook.md`。
