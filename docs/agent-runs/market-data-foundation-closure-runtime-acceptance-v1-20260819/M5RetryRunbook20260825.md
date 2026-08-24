# M5 Retry Runbook — 2026-08-25

## 固定邊界

- 只允許TW 2330、Quote viewer lease、bounded samples。
- 禁止Account、Order、交易、backfill、repair、DB destructive/write probe與raw provider payload/credentials。
- Runtime lifecycle只走正式OMI launcher/component owner；不broad-kill、不建立第二個launcher owner。
- 固定source checkpoint SHA-256=`8acbaea6fa4566416c67dc1e1745e4a080e2b6ee8e341fd1c0edc501f56badf2`，30個target mismatch必須為0，且checkpoint `validation.result=passed`。
- 任一source/config變更都使本runbook的session evidence失效；先重算checkpoint、adopt runtime，再從Preopen重跑。
- 2026-08-21盤中regular diagnostic只證明fix behavior，不是正式M5 Regular pass。
- Closing Auction unchanged-cumulative paired callback已完成source regression修正；正式尾盤live retest仍pending，且不替代Preopen／Opening／Regular。
- 2026-08-24 preflight確認瀏覽器中的3711頁面會持續建立外部viewer lease；新版frontend會在hidden/pagehide主動release，但08:10前仍須確認viewer owner正常退出並等global bridge回0，automation不得release或終止它。
- Viewer lease必須明示`owner_kind`；正式session probe只可建立`acceptance_probe`，global summary不得保存lease ID或私人identity。

## 07:50 Source-only gate

此階段不得讀取或修改runtime；只提前攔截source drift。

```powershell
cd "C:\project\Open Market Intelligence"
.\scripts\invoke-mdf-m5-preflight.ps1 `
  -RuntimeAction SourceOnly `
  -ExpectedDate 2026-08-25 `
  -ExpectedCheckpointSha256 8acbaea6fa4566416c67dc1e1745e4a080e2b6ee8e341fd1c0edc501f56badf2 `
  -ArtifactPath docs/agent-runs/market-data-foundation-closure-runtime-acceptance-v1-20260819/artifacts/m5-source-only-20260825.json
```

Pass必須是source 30/30、checkpoint validation passed、harness hashes已記錄；runtime/calendar/frontend/MCP/viewer欄位必須明示`not_run`。若失敗，立即保存artifact並分析exact mismatch；只有task-owned、localized且可在完整validation後重建checkpoint的問題才可自動修復。Ownership不明或廣泛drift維持fail closed並回報，不得等到08:20才開始辨識。

## 08:10 Compare preparation

先由所有viewer owner正常退出；確認任何前端selected symbol都不再heartbeat。禁止刪除未知lease或終止bridge process。只有global lease=0但bridge仍存在時，harness可bounded等待最多150秒讓idle cleanup自然完成。

```powershell
cd "C:\project\Open Market Intelligence"
.\scripts\invoke-mdf-m5-preflight.ps1 `
  -RuntimeAction Prepare `
  -ExpectedMode compare `
  -ExpectedDate 2026-08-25 `
  -ExpectedCheckpointSha256 8acbaea6fa4566416c67dc1e1745e4a080e2b6ee8e341fd1c0edc501f56badf2 `
  -ArtifactPath docs/agent-runs/market-data-foundation-closure-runtime-acceptance-v1-20260819/artifacts/m5-prepare-20260825.json
```

Pass必須同時成立：

- local date=`2026-08-25`且authoritative TW calendar=`trading_day`、cache current。
- source 30/30、official launcher/listener lineage、project root、Python與selected port一致。
- health mode=`compare`、ready=`ready`、public catalog、frontend proxy與stdio MCP pass。
- 2330 active lease=0、global summary total=0且global KGI bridge process=0。

任一gate失敗：不得建立lease或取provider sample；保存dated artifact後進入stop-and-fix。Runtime／frontend／MCP transient failure只可透過正式launcher做component-scoped Prepare／RestartServices並重驗；不得手動kill。Active lease固定分類為`EXTERNAL_VIEWER_LEASE_PRESENT`；零lease但bridge未自然退出才是`BRIDGE_IDLE_CLEANUP_TIMEOUT`。

## 08:20~08:31 Active observation and remediation

Prepare通過後，以`RuntimeAction Check`再驗一次相同source/runtime/calendar/catalog/frontend/MCP/global baseline。Check通過後，立即加上`-RunViewerReadiness`完成單一TW 2330 `acceptance_probe`的 acquire／sample readiness／release／idle-cleanup lifecycle；這只證明接線與生命週期可用，不能算正式Preopen pass。

若runtime stage回`RUNTIME_LINEAGE_PROBE_UNAVAILABLE`，代表目前execution environment無法讀取listener/WMI lineage，不等於真實owner mismatch。使用完全相同參數在normal Windows permission重跑；只有該次完整pass才可繼續，不得略過lineage gate。

```powershell
.\scripts\invoke-mdf-m5-preflight.ps1 `
  -RuntimeAction Check `
  -RunViewerReadiness `
  -ExpectedMode compare `
  -ExpectedDate 2026-08-25 `
  -ExpectedCheckpointSha256 8acbaea6fa4566416c67dc1e1745e4a080e2b6ee8e341fd1c0edc501f56badf2 `
  -ArtifactPath docs/agent-runs/market-data-foundation-closure-runtime-acceptance-v1-20260819/artifacts/m5-preflight-20260825.json
```

Automation不得把第一次failure直接等同terminal blocker；依下列順序bounded處置：

1. `RUNTIME_LINEAGE_PROBE_UNAVAILABLE`：以normal Windows permission原參數重跑，不改任何gate。
2. Effective mode、health/ready、frontend proxy或MCP transient failure：只透過正式launcher執行Prepare或RestartServices，等待bounded readiness後重跑完整Check/readiness。
3. Global lease=0但bridge逾idle timeout：先完成既定150秒自然等待；仍未清除才可用component-owned RestartServices，之後必須重新證明lineage、compare與zero baseline。
4. `EXTERNAL_VIEWER_LEASE_PRESENT`：不得release未知lease。保存redacted owner/symbol counts，將相同automation依序重排08:24、08:28、08:31重驗；owner正常清除後自動繼續。
5. KGI Python／CA／login／subscription readiness失敗：先release本probe並確認after baseline，再讀取redacted log/config status。可由task-owned source、harness或正式launcher修復者，做targeted/full validation、checkpoint重建與runtime adoption後重試；需要credential、entitlement或人工作業才回報。
6. Source drift：列出exact target與ownership。只允許localized task-owned修復；修復後依affected boundary執行最小足夠至full validation、重建30-target checkpoint、同步automation pin並重新adopt。未知或跨任務drift不得自動接受新hash。

只有以下情況可在08:31前暫停並通知使用者：安全邊界外操作才可解除、需要credential/entitlement/人工作業、外部owner仍持有lease、source ownership不明／廣泛drift，或完成必要修復後已無法取得同一真實Preopen window。其餘可修復問題不通知，保留dated attempt artifacts後繼續。

## 08:30~08:55 Preopen

- 08:20 readiness通過後，automation排到08:30；若仍在bounded外部lease recheck，最晚08:31開始。不得在08:20用尚未出現的auction evidence預判pass。
- 建立`owner_kind=acceptance_probe`的單一2330 lease，保存redacted lease/subscription/process `before / active / after`。
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
- Rollback後驗證health=`off`、ready、frontend、MCP與零殘留，再建立本輪dated rollback與final-observation artifacts。因Closing Auction正式live retest仍pending，本輪不得建立final `foundation-checkpoint.json`或宣告closure。
- 正式session的semantic failure可在安全範圍內現場修復，但任何source/config改動都會使舊session evidence失效；必須重建checkpoint、重新adopt，並在仍存在的同一真實session window重跑。若window已錯過，保留failure並停止，不得用後續session補前一stage。
- 不得標記`runtime-accepted`或`ready-for-02`，直到所有正式gate與Closing Auction live retest依原計畫完成。
