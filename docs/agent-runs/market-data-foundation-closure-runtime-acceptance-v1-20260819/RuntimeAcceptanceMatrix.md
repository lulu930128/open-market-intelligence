# Runtime Acceptance Evidence Matrix

## Purpose

本矩陣定義「什麼證據才算通過」。HTTP 200、source test green、設定檔寫著某個mode，任何單一項都不能獨自代表runtime acceptance。

## Artifact rules

- 執行時的artifact root：`docs/agent-runs/market-data-foundation-closure-runtime-acceptance-v1-20260819/artifacts/`。
- 只保存摘要、hash、counter、redacted field matrix與log pointer。
- 不保存raw provider payload、credential、person ID、account identity、token、cookie或完整`.env`。
- 任何artifact都要包含：timestamp、Asia/Taipei session、source fingerprint、effective mode、target、provider、result與limitation。
- Artifact可使用`.json`/`.md`；大量runtime log留在既有`logs/`，文件只保存相對path與hash。

## Gate matrix

| Gate | Required evidence | Pass rule | Planned artifact |
| --- | --- | --- | --- |
| Source identity | branch、HEAD、dirty count、target SHA-256、last-write time | target manifest完整 | `artifacts/source-manifest.json` |
| Launcher owner | launcher/wrapper/listener PID lineage、command line、start time | owner為正式OMI launcher，無不明listener | `artifacts/runtime-identity-<mode>.json` |
| Selected ports | launcher `selected=`/service environment、listener、health URLs | log、listener、HTTP三者一致 | 同上 |
| Source adoption | listener start晚於target writes、repo root、catalog hash | 三者一致 | 同上 |
| Effective mode | running process startup evidence | 必須證明off/shadow/compare，不靠`.env`推測 | `artifacts/mode-<mode>.json` |
| OFF | legacy response、canonical event count | outward正常且canonical seam count=0 | `artifacts/off-baseline.json` |
| SHADOW | same-payload validation、external/subscription/DB counters | outward hash不變且side-effect delta=0 | `artifacts/shadow-result.json` |
| COMPARE | mismatch taxonomy、bounds、fault isolation | 未分類核心mismatch=0 | `artifacts/compare-result.json` |
| Preopen | quote/auction/trade-state field matrix | indicative不成為trade | `artifacts/session-preopen.json` |
| Opening | bounded transition samples | no trial leakage/timestamp regression | `artifacts/session-opening.json` |
| Regular | quote/OHLCV/depth/unit/time lineage | semantics/unit一致或classified | `artifacts/session-regular.json` |
| Subscription cleanup | before/active/after lease/subscription counters | after回baseline | 各session artifact |
| Rollback | compare identity、off identity、legacy/MCP smoke | 不需DB/cache deletion | `artifacts/rollback.json` |
| Final validation | commands、exit codes、test totals、log paths | Foundation-related failure=0 | `artifacts/final-validation.md` |
| Checkpoint | status、hashes、runtime、modes、sessions、remaining scope | 可由下一工作直接續接 | `artifacts/foundation-checkpoint.json` |

## Current read-only baseline — 2026-08-19

| Field | Observed value | Status |
| --- | --- | --- |
| Branch | `codex/tw-etf-provider-normalization` | observed |
| HEAD | `aa65e65424f2d5de7255c4168a18ded9f8794301` | observed |
| Dirty entries | 63 | observed |
| Launcher PID | 42700 | observed |
| Launcher start | `2026-08-19T21:00:19.838187+08:00` | observed |
| Launcher command | `scripts/omi-launcher.ps1` | observed |
| Backend wrapper/listener | 69668 / 66124 | observed |
| Backend listener start | `2026-08-19T21:00:24.168543+08:00` | observed |
| Backend URL | `http://127.0.0.1:8400` | observed |
| Frontend wrapper/listener | 26684 / 55704 | observed |
| Frontend URL | `http://127.0.0.1:3000` | observed |
| Health | 200, correct project root/backend/python | observed |
| Live/local catalog SHA-256 | `ebe6233ae0b3023a358e6976fc6bff4485879e74fa8e1ef0d132bb1438e2eb66` | match |
| Effective canonical mode | not directly observable | not accepted |
| Off/shadow/compare | not executed | pending |
| Real session smoke | not executed | pending |
| Rollback | not executed | pending |

此baseline在M1 source改動後失效；M3必須重新建立。

## Mode sample contract

每個mode sample至少記錄：

```json
{
  "source_fingerprint": "sha256:...",
  "effective_mode": "off|shadow|compare",
  "backend": {"url": "...", "listener_pid": 0, "started_at": "..."},
  "target": {"market": "TW", "symbol": "...", "session": "..."},
  "legacy_response_sha256": "...",
  "provider_event_delta": 0,
  "external_call_delta": 0,
  "subscription_delta": 0,
  "db_write_delta": 0,
  "comparison": {"mismatch_count": 0, "reason_codes": []},
  "latency_ms": {"p50": 0, "p95": 0, "max": 0},
  "result": "passed|failed|not_applicable",
  "limitations": []
}
```

數字欄位只能由可觀察counter填入；若目前沒有可信counter，填`null`並將gate判為未完成，不得用0代替unknown。

## Session field matrix

| Session | Required semantic fields | Forbidden interpretation |
| --- | --- | --- |
| Preopen | session、trade_state、last_trade_price、indicative_price/volume、provisional、bid/ask、event/received time | indicative/`pz`當actual trade |
| Opening | prior indicative、first actual trade、quote/depth times、cumulative volume | trial price殘留、timestamp倒退、volume製造trade |
| Regular | last trade、OHLC、cumulative/last volume、L5 depth、quantity unit/conversion、lineage times | lots/shares混淆、cross-provider拼欄 |

## Mismatch taxonomy

預先核准：

- `LEGACY_ZERO_NORMALIZED_TO_MISSING`：僅限legacy trial OHLC zero與canonical missing的representation差異。

需要stop-and-fix：

- 未分類price difference。
- shares/lots/contracts unit difference。
- indicative vs actual trade difference。
- market session/trade date difference。
- event time倒退或future timestamp。
- current/stale/partial/not-applicable差異無可驗證原因。
- official/broker Trading Status conflict未保留candidate lineage。

## MCP compatibility smoke

- `initialize`。
- 保留`Mcp-Session-Id`。
- `notifications/initialized`。
- `tools/list`。
- Representative read/call使用cache/no-LLM/no-write/no-external-fetch policy。
- 驗證`omi.decision.v4`、partial/missing/stale/limitations語意未漂移。

## Invalidation rules

- Foundation target file、mode mechanism、launcher或public catalog任一改動：runtime identity與其後mode/session證據失效。
- Provider adapter或comparison改動：相關session與compare證據失效。
- 只有docs更新不使runtime證據失效，但必須重算checkpoint manifest。
- 不同source fingerprint的三個market sessions不能合併成同一次Foundation acceptance。

## M5 retry identity revalidation — 2026-08-20

- `scripts/omi-launcher.ps1`新增local-only owner control seam後，2026-08-19的process identity不再作為目前runtime identity。
- 新版launcher已重新建立off、shadow、compare identity：
  - `artifacts/m5-preflight-20260820-mode-off.json`
  - `artifacts/m5-preflight-20260820-mode-shadow.json`
  - `artifacts/m5-preflight-20260820-mode-compare-final.json`
- 三份artifact均驗證source checkpoint 14/14、launcher/listener lineage、effective mode、health/ready、authoritative calendar、public catalog、frontend/MCP與viewer/bridge baseline。
- 未執行`refresh=true` runtime same-payload probe，因該legacy path可能進行外部fetch與quote upsert；先前同一Foundation source checkpoint的deterministic/same-payload語意證據保留，但不取代2026-08-21 live-session evidence。
- 2026-08-21的preopen、opening、regular仍必須使用同一source fingerprint與dated artifact逐階段驗收；目前狀態只有`READY_FOR_MANUAL_M5`。

## M5 Preopen failure remediation identity — 2026-08-21

- 08:34~08:35的正式Preopen以`PREOPEN_TRIAL_LEAKAGE_IN_REALTIME_STREAM`失敗；舊fingerprint `703caf9b...`的session evidence維持failed且不可覆寫。
- Root cause是KGI callback在`simtrade=0`、正`close/volume`但`total_volume=0`時被realtime manager列為trade。修正後actual trade必須同時具備正price、正single volume與正cumulative volume；zero cumulative只能成為indicative/auction evidence。
- Per-symbol stream buffer改為event-date isolated且日期不可倒退；舊日quote/KBar不得回寫目前session。Outward `recent_trades`仍是newest-first，跨sample才驗event time/sequence不得倒退。
- Source manifest由14個擴為30個production/runtime/test owners。現行checkpoint SHA-256=`99f95233bb35afb033bcce7c0f959a00eb74b785c4734608b80e0f153e80a39d`且`validation.result=passed`；舊checkpoint保存在`artifacts/source-checkpoint-20260819.json`。
- Preflight現在除checkpoint/hash外也強制`validation.result=passed`；否則以`SOURCE_VALIDATION_NOT_PASSED` fail closed。validation metadata更新不改30個source hashes，依docs-only invalidation rule不使09:07 runtime adoption失效。
- 最終runtime adoption artifact=`artifacts/m5-preflight-20260821-preopen-fix-final-restart.json`：launcher PID=56040、listener 56364 -> 51492、mode=`compare`、source 30/30、health/ready/calendar/public contract/frontend/MCP/viewer baseline全pass。
- Fix diagnostic artifact=`artifacts/m5-preopen-fix-validation-20260821.json`：TW 2330 lease=`0 -> 1 -> 0`、4 samples、invalid trade=0、cross-date trade/KBar=0、ordering regression=0；不保存raw provider payload。
- Official backend source validation=`1915 passed, 801 warnings`、compileall/git diff check passed；artifact=`artifacts/m5-preopen-fix-source-validation-20260821.json`。先前sandbox basetemp cleanup failure不再是source validation blocker。
- 外部frontend viewer可在restart後自動reacquire並切換symbol（本輪觀察6173 -> 2478）。它存在時global bridge process不為0不是2330 probe leak；但下一次正式Preopen preflight仍必須由viewer owner退出並取得乾淨global baseline，不降低gate。
- 2026-08-21盤中diagnostic不能取代同fingerprint Preopen與Opening。正式M5狀態仍是Preopen/Opening/Regular pending、rollback not executed、Foundation not ready。

## Closing Auction diagnostic — 2026-08-21

- 本次只作額外diagnostic，不是Preopen、Opening或Regular正式gate，也不改變既有gate順序。
- 正常Windows權限層preflight通過：checkpoint=`99f95233...`、source=30/30、launcher/listener lineage、mode=`compare`、authoritative TW trading day、health/ready、public contract、frontend/MCP與viewer baseline均pass。
- 實際sample window為13:28:33~13:30:10；因前置WMI sandbox假陰性與harness字串修正，未涵蓋13:25~13:28，且沒有owned regular-session baseline。此限制不得隱藏。
- Quote-depth projection在final match前維持`CLOSING_AUCTION_INDICATIVE_OBSERVED / AUCTION_INDICATIVE_ONLY / actual_trade_occurred=false`，但realtime stream在13:30前已有16筆`recent_trades`，因此`indicative vs actual trade` stop-and-fix rule觸發。
- 具代表性的paired evidence：13:29:58 auction seq=33與trade seq=34皆為price=2410、volume=4045，trade cumulative仍是11655；13:30正式match seq=35才把cumulative提高到15700，delta=4045。
- Time/order/cross-date/unit checks通過；13個sample-aligned compare events全為`matched`、mismatch=0。這證明compare projection未漂移，但不能抵銷realtime stream semantic failure。
- Lease只由本probe建立與釋放：`0/0 -> 1/2 -> 0/2`；configured idle shutdown=120秒，13:32:52 component-owned cleanup後為`0 lease / 0 bridge`，未broad-kill。
- Result=`failed`，failure code=`CLOSING_AUCTION_TRIAL_LEAKAGE_IN_REALTIME_STREAM`；artifact=`artifacts/session-closing-diagnostic-20260821.json`。正式Preopen/Opening/Regular仍pending，rollback未執行。

## M5 08:20 preflight — 2026-08-24

- Local invocation time=`2026-08-24T08:21:22+08:00`，expected checkpoint SHA-256=`99f95233bb35afb033bcce7c0f959a00eb74b785c4734608b80e0f153e80a39d`。
- Checkpoint artifact hash與`validation.result=passed`仍符合預期，但30個受保護target中14個actual hash不再符合checkpoint；source identity gate=`failed`，failure code=`FOUNDATION_TARGET_CHANGED`。
- Ordered fail-closed在source gate立即停止；calendar、runtime preparation、effective mode、launcher lineage、health/ready、frontend/MCP與viewer baseline均未執行，因此不得沿用舊證據推定pass。
- 未建立viewer lease、未啟動provider sample、未做Account/Order、backfill/repair、DB write probe、unknown lease release、process kill、commit或push。
- Artifacts：`artifacts/m5-preflight-20260824-082122-735.json`、`artifacts/m5-preflight-20260824-082122-source-mismatch.json`。
- Preopen、Opening、Regular與rollback仍為pending；重算並驗證新checkpoint、完成component-owned runtime adoption之前不得重排session acceptance。

## M5 source recovery and runtime preparation — 2026-08-24

- Ownership audit確認02A完成artifact的Foundation 30-target mismatch=0；08:20揭露的14個drift全部發生在02A之後，不能把它們歸因於02A或直接接受舊validation。
- Closing Auction classifier以per-symbol cumulative-volume advance補上paired callback evidence：unchanged cumulative的trial/non-trial pair不得新增actual trade；正式cumulative advance才可進`recent_trades`。正式尾盤live retest仍pending，不能由source regression取代。
- 官方backend profile完整通過：compileall passed、`2096 passed, 801 warnings in 248.56s`、git diff check passed；log=`.tmp/validation/20260824-085844`。
- 舊checkpoint `99f95233...`封存為`artifacts/source-checkpoint-20260821.json`；current checkpoint SHA-256=`6f2e0e8724704b83a22a63750583e6a5d4d2ed7a4a8d651e0332b9e64d1c543e`，`validation.result=passed`、30/30 mismatch=0、checkpoint guard=`7 passed`。
- 09:03 `Prepare`完成component-owned compare adoption：source、lineage、health/ready、calendar與public catalog passed；frontend約4秒後ready，但原本的單次probe在其ready前connection refused，artifact=`artifacts/m5-preflight-20260824-090349-790.json`。
- Acceptance harness已新增bounded frontend readiness retry（default 30秒、500ms interval）與attempt/wait/error evidence；後續`Check`的frontend及stdio MCP均passed。
- 09:06最後baseline gate如實failed：外部frontend正在觀看3711並持有viewer lease，故2330 active lease=0但global KGI bridge process=2；artifact=`artifacts/m5-preflight-20260824-090641-554.json`。本task不得release或終止該外部owner資源。
- Source recovery完成時已跨過Preopen與Opening window；不得用09:03後regular資料補前兩個gate，也未建立本task lease或取provider sample。2026-08-24 Preopen/Opening/Regular全部維持pending，rollback與closure未執行。
- 下一輪使用`M5RetryRunbook20260825.md`及current checkpoint。08:20前必須先由所有viewer owner正常退出，取得2330與global bridge baseline=0；任一source hash或runtime identity不符仍fail closed。

## M5 owner-scoped baseline hardening — 2026-08-24

- Current source checkpoint=`8acbaea6fa4566416c67dc1e1745e4a080e2b6ee8e341fd1c0edc501f56badf2`，validation=`2098 passed`、30/30 target mismatch=0。
- Runtime adoption artifact=`artifacts/m5-preflight-20260824-102944-059.json`：effective mode=`compare`、health/ready/calendar/catalog/frontend/MCP passed。
- Global lease summary直接觀察到`total_active_leases=1`、`leases_by_owner_kind.frontend_viewer=1`、`leases_by_symbol.3711=1`；2330 active lease=0不再被誤解為global baseline乾淨。
- Gate result=`failed / EXTERNAL_VIEWER_LEASE_PRESENT`。本preflight owned lease=0，因此沒有release任何lease；這是正確fail-closed，不是provider semantic failure。
- `SourceOnly`已能在07:50獨立驗source/harness；08:10 Prepare與08:20 Check仍須取得global lease=0、bridge=0後才可排Preopen。
- Sandbox無法讀listener/WMI時現在分類為`RUNTIME_LINEAGE_PROBE_UNAVAILABLE`，不得誤報真實owner mismatch；相同Check必須在normal Windows permission重跑。
- Final normal-Windows Check=`passed`：global lease=0、bridge=false、subscription worker=0，runtime lineage、compare、health/ready、calendar、catalog、frontend與MCP全pass；artifact=`artifacts/m5-preflight-owner-clean-final-20260824.json`。

## 08:20 active remediation decision matrix — 2026-08-24

| Evidence / failure | 自動處置 | 繼續條件 | Terminal blocker |
| --- | --- | --- | --- |
| `RUNTIME_LINEAGE_PROBE_UNAVAILABLE` | normal Windows permission原參數重跑 | exact lineage pass | normal Windows仍無法驗證 |
| mode／health／frontend／MCP transient | 正式launcher Prepare／RestartServices、bounded wait、完整重驗 | compare、ready、catalog、frontend、MCP全pass | component owner無法恢復 |
| zero lease + bridge idle timeout | 先等150秒；仍存在才component-scoped restart | global lease=0、bridge=0 | restart後仍殘留或ownership衝突 |
| external viewer lease | 不release；08:24／08:28／08:31 redacted recheck | owner自行退出且baseline=0 | 08:31仍存在 |
| KGI readiness failure | release owned probe、讀redacted evidence、修task-owned seam並重驗 | acquire/sample/release/cleanup全pass | credential／entitlement／人工作業需求 |
| source drift | exact target/ownership audit；只修localized task-owned範圍 | validation、new checkpoint、runtime adoption全pass | ownership不明、廣泛drift或錯過session |

本矩陣不降低M5順序：source/runtime identity -> compare -> bounded readiness -> 真實Preopen／Opening／Regular -> cleanup。08:20 readiness不是session pass；正式Preopen從08:30起取得當下evidence。
