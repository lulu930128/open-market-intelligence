# M5 Manual Runbook — 2026-08-21

> 2026-08-21執行結果：Preopen因realtime trial leakage失敗；修正已於09:07採用，但盤前/開盤窗已結束。本文件保留為歷史runbook，不得再用於宣告2026-08-21 session pass。下一次執行請使用`M5RetryRunbook20260824.md`與新checkpoint。

## Status boundary

- 今晚狀態：`READY_FOR_MANUAL_M5`。
- 明早完成preopen、opening、regular、cleanup與rollback前，不得標記`runtime-accepted`或`ready-for-02`。
- 只允許TW 2330、Quote viewer lease、bounded samples；禁止Account、Order、交易、backfill、repair、DB destructive/write probe與raw provider payload/credentials。

## Phase A — 08:15~08:25 manual preflight

在任何viewer lease前執行：

```powershell
cd "C:\project\Open Market Intelligence"
.\scripts\invoke-mdf-m5-preflight.ps1 `
  -RuntimeAction Prepare `
  -ExpectedMode compare `
  -ExpectedDate 2026-08-21
```

Pass必須同時成立：

- local date=`2026-08-21`。
- authoritative TW calendar為trading day且cache current。
- source checkpoint SHA-256=`703caf9b23b79189a5db65dfb8b248686e4f2c4635c251d4f3174ab0ea573799`，14個target mismatch=0。
- 正式launcher/listener lineage、project root、Python與selected port一致。
- `/api/system/health` effective mode=`compare`；`/api/system/readyz`=`ready`。
- public catalog digest=`fec3d7d071dd7ca92d5245b94fca59d99801b901a8228f09e62cc2e9ebfdd7e2`。
- frontend proxy與stdio MCP smoke pass。
- 2330 viewer active lease=0；KGI bridge process=0。

任一gate失敗：不得建立viewer lease，不得取provider sample；保留preflight artifact並先處理blocker。

## Phase B — Preopen

- 約08:30建立單一2330 viewer lease；採樣前記錄lease/subscription/process baseline。
- 約08:35採樣KGI、MIS、Canonical與compare telemetry。
- 必驗證session/trade state、bid/ask、indicative price/volume、provisional、event time與received time。
- `pz`、trial或indicative value不得成為actual trade；missing不得轉為0。
- Pass後保存`artifacts/session-preopen-20260821.json`，才可進Opening。

## Phase C — Opening transition

- 08:58開始bounded sampling，直到第一筆actual trade或最晚09:02。
- 驗證trial不洩漏、timestamp不倒退、cumulative volume不製造trade、compare無未分類核心mismatch。
- Pass後保存`artifacts/session-opening-20260821.json`，才可進Regular。

## Phase D — Regular

- 約09:05後驗證last trade、OHLC、cumulative/last volume、L5 depth、lots-to-shares lineage、event/received time與selected/candidate provider lineage。
- KGI/MIS不要求同毫秒數值相等；semantic必須一致，或差異有核准taxonomy。
- 未分類price、volume、unit、session或trade-evidence mismatch必須為0。
- 保存`artifacts/session-regular-20260821.json`。

## Cleanup and closure

- 每個stage都記錄before/active/after；結束時release lease，active lease、subscription symbol與bridge process必須回baseline。
- 只有三個session與cleanup全pass，才執行component-owned `compare -> off` rollback。
- Rollback後驗證health=`off`、ready、frontend、MCP與零殘留，建立`rollback.json`、`final-validation.md`與`foundation-checkpoint.json`。
- 任一stage失敗：release、保存dated failure artifact、停止；不得用後續stage補前一stage，也不得降低驗收標準。
