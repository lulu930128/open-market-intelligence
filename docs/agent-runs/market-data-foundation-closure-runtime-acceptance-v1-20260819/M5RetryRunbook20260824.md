# M5 Retry Runbook — 2026-08-24

## 固定邊界

- 只允許TW 2330、Quote viewer lease、bounded samples。
- 禁止Account、Order、交易、backfill、repair、DB destructive/write probe與raw provider payload/credentials。
- Runtime lifecycle只走正式OMI launcher/component owner；不broad-kill、不建立第二個launcher owner。
- 固定source checkpoint SHA-256=`99f95233bb35afb033bcce7c0f959a00eb74b785c4734608b80e0f153e80a39d`，30個target mismatch必須為0，且checkpoint `validation.result=passed`。
- 任一source/config變更都使本runbook的session evidence失效；先重算checkpoint、adopt runtime，再從Preopen重跑。
- 2026-08-21盤中regular diagnostic只證明fix behavior，不是正式M5 Regular pass。

## 08:15~08:25 Preflight

先由所有viewer owner正常退出；確認任何前端selected symbol都不再heartbeat。禁止刪除未知lease或終止bridge process。

```powershell
cd "C:\project\Open Market Intelligence"
.\scripts\invoke-mdf-m5-preflight.ps1 `
  -RuntimeAction Prepare `
  -ExpectedMode compare `
  -ExpectedDate 2026-08-24 `
  -ExpectedCheckpointSha256 99f95233bb35afb033bcce7c0f959a00eb74b785c4734608b80e0f153e80a39d
```

Pass必須同時成立：

- local date=`2026-08-24`且authoritative TW calendar=`trading_day`、cache current。
- source 30/30、official launcher/listener lineage、project root、Python與selected port一致。
- health mode=`compare`、ready=`ready`、public catalog、frontend proxy與stdio MCP pass。
- 2330 active lease=0且global KGI bridge process=0。

任一gate失敗：不得建立lease或取provider sample；保存dated artifact後stop-and-fix。

## 08:30~08:55 Preopen

- 建立本次probe擁有的單一2330 lease，保存lease/subscription/process `before / active / after`。
- Bounded sampling需驗證：session/trade state、indicative price/volume、bid/ask、provisional、event/received time與compare telemetry。
- `simtrade=1`或`total_volume=0`的正價量不得進`recent_trades`；`last_trade_price=None`，auction semantics保持indicative。
- 不得有舊日期quote/KBar、未分類price/unit/session/trade-evidence mismatch。
- Pass後建立新的dated Preopen artifact，才可進Opening。

## 08:58~09:02 Opening

- 從08:58 bounded sampling到第一筆actual trade或最晚09:02。
- 驗證trial不洩漏、跨sample event time/sequence不倒退、actual trade具正price/volume/cumulative volume、舊日buffer未混入。
- `recent_trades`清單contract為newest-first；清單內event time/sequence須遞減，跨sample top-level event time/sequence須不遞減。
- Pass後建立新的dated Opening artifact，才可進Regular。

## 09:05後 Regular

- 驗證last trade、OHLC、cumulative/last volume、L5 depth、lots-to-shares lineage、event/received time與selected/candidate provider lineage。
- KGI/MIS不要求同毫秒值相同，但語意必須一致或屬核准taxonomy；未分類核心mismatch=0。
- 每階段只釋放本probe擁有的lease；after須回到該階段before baseline。

## Rollback與closure

- 只有Preopen、Opening、Regular及cleanup全pass，才執行component-owned `compare -> off`。
- Rollback後驗證health=`off`、ready、frontend、MCP與零殘留，再建立`rollback.json`、`final-validation.md`與`foundation-checkpoint.json`。
- 任一stage失敗都保留真實artifact並停止；不得用後續session補前一stage，也不得標記`runtime-accepted`或`ready-for-02`。
