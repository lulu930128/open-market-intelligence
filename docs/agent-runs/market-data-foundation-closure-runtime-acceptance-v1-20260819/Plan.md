# OMI Market Data Foundation 1.1 長專案計畫

## Execution model

```text
Planning accepted
  -> M0 baseline lock
  -> M1 contract hardening
  -> M2 source validation/checkpoint candidate
  -> Gate R: runtime mutation approval
  -> M3 runtime identity/adoption
  -> M4 off/shadow/compare
  -> Gate L: bounded live-provider approval
  -> M5 real market sessions
  -> M6 rollback
  -> M7 final validation/closure checkpoint
  -> ready-for-02
```

- Milestone必須依序通過；後一階段不能用來掩蓋前一階段failure。
- M0-M2是source工作；M3之後是獨立runtime gate；M5是獨立live-provider gate。
- 任一code/config變更都使先前建立的runtime identity失效；受影響gate必須重跑。
- 每完成一個milestone即更新本目錄`Progress.md`，並把機器可讀摘要放入計畫中的`artifacts/`路徑。

## Milestone 0 — Baseline lock and ownership map

### Scope

- 保存branch、HEAD、完整`git status --short`與Foundation target files SHA-256。
- 對63筆dirty entries建立target/non-target ownership inventory；只碰本計畫列出的localized files。
- 保存current launcher/runtime read-only baseline，但不把現有runtime直接算成修正後adoption。
- 鎖定public catalog hash、previous acceptance report與validation log。

### Expected files

- `backend/app/market_data/resolution.py`
- `backend/app/market_data/registry.py`
- `backend/app/ai/capability_contract.py`
- `backend/tests/test_market_data_resolution.py`
- `backend/tests/test_market_data_registry.py`
- `backend/tests/test_ai_capability_resolution_registry.py`
- 若mode不可觀察，最多新增一個不含secret/raw payload的startup observability seam及其test；不得順手重構launcher。

### Acceptance

- Target status/hash與既有修改owner明確。
- 不需isolated worktree；目前untracked Foundation integration base被保留。
- 沒有secret、DB、cache、log或frontend檔案進入修改範圍。

### Validation

```powershell
git status --short --branch
git rev-parse HEAD
Get-FileHash <foundation-target> -Algorithm SHA256
```

### Stop condition

- 任一target file在開始後出現無法歸屬的並行修改時暫停，不覆蓋對方變更。

## Milestone 1 — Contract hardening

### Work package 1A：Trading Status currentness/authority

- 將Trading Status ranking從共用`official_first`布林捷徑收斂為專用policy。
- Currentness tiers：invalid/unusable、current (`LIVE/FRESH`)、stale。
- Rank：validity/currentness -> official/authority -> freshness -> provider priority。
- 增加conflict detection，但不增加provider/network/DB dependency。
- Candidate lineage維持bounded；不加入raw payload。
- 對外沿用`ResolvedTradingStatus`與`ResolvedEvidenceHealth`既有version，除非實作證明無法truthful表達；若需schema變更先停下更新Prompt。

Tests至少包含：

1. current official `TRADABLE` + current broker `SUSPENDED`：select official，保留conflict limitation/candidates。
2. stale official `TRADABLE` + live broker `SUSPENDED`：不得select無限制的stale official；result為partial/conflicting且research unusable。
3. stale official與current broker同狀態：current evidence優先，不製造假conflict。
4. only stale official：可回stale，但不得標current/research-ready。
5. future/unknown/missing candidate保持ineligible。
6. resolution module import boundary不變。

### Work package 1B：Daily dataset eligibility

- 新增能表達listed instrument + market trading day + instrument trading eligibility的`EligibilityPolicy`。
- 將`tw.daily.ohlcv`切到新policy。
- 保留`evaluate_dataset_health()` tri-state input，不新增I/O。
- 增加`eligible=None -> UNKNOWN`與daily spec policy tests。
- 不接official status、scheduler、repair execution或DB。

### Work package 1C：US default capability truth

- 從`us_stock/general` raw defaults移除`technical.structure`。
- 將`ownership.insider_transactions`的market由`us`正規化為`US`，修復explicit/domain selection truth。
- 同時從`us_stock/general` raw defaults移除`ownership.insider_transactions`，使一般預設selection維持目前outward行為，不在1.1新增SEC acquisition/latency。
- Compatibility filter仍保留作defense in depth。
- 新增test：US general raw default IDs全部存在且對`us_stock/US`compatible；normalized defaults不靠filter移除technical/insider才truthful；explicit insider capability對`us_stock/US`compatible。
- Market metadata若進入public digest/MCP snapshot，必須同步更新並說明這是casing truth修正；不做其他snapshot churn。

### Acceptance

- 三個pure reproducer都轉為預期行為。
- 既有official-current、dataset health與explicit unsupported-capability tests仍通過。
- 無public request/response shape、DB schema、provider call或frontend改動。

### Validation

```powershell
cd "C:\project\Open Market Intelligence\backend"
..\.venv\Scripts\python.exe -m compileall app\market_data app\ai\capability_contract.py
..\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  tests\test_market_data_resolution.py `
  tests\test_market_data_registry.py `
  tests\test_market_data_contracts.py `
  tests\test_ai_capability_resolution_registry.py `
  tests\test_ai_tool_boundaries.py -q
```

### Stop condition

- 若需要新增official provider、改outward capability schema、改DB或讓consumer解讀conflict，立即停下；這表示範圍已越過1.1。

## Milestone 2 — Source validation and checkpoint candidate

### Scope

- 跑Foundation/KGI/MIS/shadow/capability targeted matrix。
- 跑backend safe validation。
- 生成修正後target hash manifest、public catalog hash與diff inventory。
- 確認default mode仍為`off`，`canary/on`仍fail closed。

### Acceptance

- Compileall passed。
- Foundation-related tests failure = 0。
- Backend safe validation passed。
- `git diff --check` passed。
- 無unexplained public catalog/snapshot drift。
- 只形成checkpoint candidate，不宣告runtime adoption。

### Validation

```powershell
cd "C:\project\Open Market Intelligence"
.\scripts\run-safe-validation.ps1 -Profile backend
git diff --check
git status --short --branch
```

### Stop condition

- Safe validation若有與本次target相關failure，先修正；不得以「既有dirty worktree」概括帶過。

## Gate R — Runtime mutation approval

執行M3前必須取得明確授權，內容包含：

- 允許使用正式OMI launcher/component owner進行bounded restart/reload。
- 允許以process-scoped `CANONICAL_MARKET_DATA_MODE`執行off/shadow/compare；不修改或輸出`.env` secret。
- 允許保存process/listener/log/API read-only evidence。

未通過Gate R時，Progress停在`source-hardened / runtime adoption pending`。

## Milestone 3 — Runtime identity and source adoption

### Scope

- 只透過`scripts/omi-launcher.ps1`及既有component lifecycle啟動；不broad-kill。
- 記錄launcher owner、wrapper child、listener PID、executable path、command line、working directory、start time、selected backend/frontend ports。
- 確認listener start time晚於所有Foundation target last-write time。
- 比較live `/api/ai/tools`與repo-local catalog canonical JSON hash。
- 探測`/api/system/health`、`/api/system/readyz`與frontend `/omi-ui-health`。
- 有效mode必須出現在不含secret的startup log或等價read-only runtime evidence。

### Acceptance

- Launcher lineage與repo root一致，backend/frontend均ready。
- Source fingerprint、process timing與public catalog一致。
- Actual mode可證明，不靠設定檔推測running process。
- Existing frontend與MCP transport可連線。

### Validation surfaces

- `logs/launcher/<date>/launcher.log`
- process/listener metadata
- `/api/system/health`
- `/api/system/readyz`
- `/api/ai/tools`
- `/omi-ui-health`
- retained-session MCP `initialize -> notifications/initialized -> tools/list`

### Stop condition

- 只要source identity、effective mode或listener owner任一無法證明，停止後續mode驗收。

## Milestone 4 — OFF / SHADOW / COMPARE runtime acceptance

### Common controls

- 每個mode使用同一source fingerprint與相同bounded targets。
- 保存legacy response canonical JSON hash、provider metadata、status/error、latency摘要。
- 外部call、subscription count、provider event、DB write counter在每個window前後取樣。
- Artifacts不得含raw payload、credential、account identity或personal data。

### Step 4A：OFF baseline

- Effective mode=`off`。
- 取得代表性legacy quote/depth response與error behavior。
- 確認canonical adapter/comparator/telemetry event count為0。

### Step 4B：SHADOW

- Effective mode=`shadow`。
- 由既有viewer-selected symbol flow取得legacy payload；canonical只驗證同一payload。
- Legacy response hash/shape與off baseline一致。
- Canonical failure fault injection不得改變legacy response。
- External call/subscription/DB write增量不得由shadow seam造成。

### Step 4C：COMPARE

- Effective mode=`compare`。
- Regular KGI/MIS fixture/runtime sample不得有未分類重大mismatch。
- KGI trial `legacy OHLC=0 -> canonical missing`必須保持`LEGACY_ZERO_NORMALIZED_TO_MISSING`，不得把missing改回0。
- Comparison/metrics/mismatch bounds仍生效。

### Acceptance

- Legacy outward contract三個mode一致。
- Shadow/compare fault isolation通過。
- Price、volume、unit、session、trade-evidence未知mismatch為0。
- Latency/memory以同一小樣本比較；若超過off baseline預先約定budget即停下調查，不以平均值掩蓋尖峰。

### Stop condition

- 任一mode新增provider acquisition/subscription、寫DB、改legacy response或產生未分類核心mismatch，立即回`off`並記錄blocker。

## Gate L — Bounded live-provider approval

執行M5前必須取得明確授權，內容包含：

- 使用現有KGI Quote/viewer lease；不使用Account/Order。
- Symbols最多3檔，單一selected-symbol lifecycle，不做全市場訂閱。
- 可在一個或多個正式台股交易時段觀察；不執行MCP arbitrary-symbol acquisition。
- 可保存redacted semantic evidence與subscription before/after counters。

## Milestone 5 — Real market session smoke

### Session preparation

- 執行當日先用backend calendar/status確認是authoritative trading day。
- 固定source fingerprint、mode、symbols、viewer lease與evidence template。
- 候選：2330、2344、1檔當日listed且一般交易標的；不適用者truthful標N/A後以bounded替代。
- 每個session前後確認active viewer lease/subscription symbols沒有leak。

### Session A：Preopen

- KGI：`simtrade`、indicative close/volume、bid/ask。
- MIS：`ts`、`pz`、`ps`、`b/a`。
- Canonical：`INDICATIVE`、`INDICATIVE_OBSERVED`、`last_trade_price=None`、auction provisional=true。
- 禁止把`pz`或試撮價當actual trade。

### Session B：Opening transition

- 在08:59:xx至09:00:xx的bounded window連續取樣。
- 第一筆正式成交覆蓋auction evidence；舊indicative value不得殘留成trade。
- Quote/depth event time不倒退；cumulative volume不製造last trade。

### Session C：Regular

- 驗證last trade、OHLC、cumulative volume、last trade volume、Level 5 depth。
- 驗證lots -> shares lineage、provider event time、received/fetched time。
- KGI/MIS不要求同毫秒相等，但語意、單位、session與trade evidence必須一致或有已分類原因。

### Acceptance

- 三個session皆用同一accepted source fingerprint。
- 每個symbol/session都有pass、truthful N/A或classified mismatch；不得以缺資料當pass。
- Subscription在viewer lease結束後回到baseline，沒有新增leak。
- 無Account/Order/trading操作。

### Stop condition

- Auction leakage、timestamp regression、unit mismatch、subscription leak或未知status conflict任一出現，停止session並回`off`；不把workaround推給02。

## Milestone 6 — Rollback acceptance

### Scope

- 在已通過compare後執行`compare -> off -> component-owned reload/restart`。
- 不刪DB/cache/module，不跑migration rollback。
- 重做runtime identity、legacy baseline、viewer flow與MCP transport smoke。

### Acceptance

- Effective mode確定為off。
- Legacy outward response恢復baseline範圍，canonical telemetry停止。
- Backend/frontend/MCP正常。
- KGI viewer lease/subscription回baseline。
- Rollback沒有資料或schema副作用。

### Stop condition

- Off不能恢復legacy baseline、仍有canonical side effect或需刪資料才恢復時，Foundation不得close。

## Milestone 7 — Final validation, closure docs and checkpoint

### Scope

- 重跑targeted、adapter、shadow/compare、AI/public/API/MCP tests與backend safe validation。
- 執行session-preserving MCP representative read/call；使用cache/no-LLM/no-write/no-external-fetch policy。
- 更新既有：
  - `docs/agent-runs/market-data-foundation-v1-20260819/Progress.md`
  - `docs/agent-runs/market-data-foundation-v1-20260819/AcceptanceReport.md`
  - `docs/agent-runs/market-data-foundation-v1-20260819/Handoff02.md`
- 生成checkpoint：branch、HEAD、status、target hashes、runtime identity、mode results、session results、mismatch taxonomy、validation log與remaining 02 scope。

### Acceptance

- Backend safe validation、`git diff --check`與public/MCP compatibility通過。
- Acceptance report列出runtime source identity、ports/owner、mode、session、mismatch、rollback與remaining scope。
- `source-complete / runtime-accepted / ready-for-02`只在所有Gate通過後寫入。
- Commit不強制；若dirty ownership不清，保留文件化checkpoint且不commit。

## Validation matrix

| Boundary | Minimum validation | Runtime/live requirement |
| --- | --- | --- |
| Trading Status resolver | pure regression + import boundary | compare/live conflict sample |
| Dataset Registry | tri-state health + spec contract | 不需provider acquisition |
| US defaults | raw default compatibility + normalized selection | live `/api/ai/tools` hash |
| Shadow/compare | fixtures + fault isolation + bounds | same-payload runtime sample |
| Runtime identity | source hash + PID/command/port/health/catalog | component-owned restart |
| Preopen/opening/regular | adapter semantics + redacted evidence | authoritative trading session |
| Rollback | mode/config + legacy response + MCP | compare -> off restart |

## Stop-and-fix rules

- Canonical path改變legacy outward result。
- Shadow/compare新增provider fetch、login、subscription或DB write。
- Unknown/missing/indicative value被轉成0或actual trade。
- Stale official仍無條件壓過current conflict。
- Dataset stale忽略known instrument ineligibility，或unknown eligibility被猜成eligible。
- Default/public capability超過implementation。
- Runtime source、owner、port或effective mode無法證明。
- 未分類price/volume/unit/session/trade-evidence mismatch。
- Latency/memory或telemetry cardinality超出bounded contract。
- Rollback不能在不刪資料的情況恢復legacy baseline。
- Dirty worktree ownership不清、需要DB migration、Account/Order、無界subscription或consumer cutover。

## Decisions

- 2026-08-24：M5 retry preparation新增 `M5ReliabilityHardeningPlan20260824.md`。Viewer ownership由production viewer manager擁有，不接線02A dark research lease；preflight拆為07:50 SourceOnly、08:10 Prepare、08:20 Check。
- 2026-08-24：global summary只輸出redacted counts；lease ID仍是單一owner的capability token，不進summary/artifact。任何baseline lease一律視為external並fail closed。
- 2026-08-24：使用者將08:20後流程由one-shot fail/pause改為active observation/remediation。Automation先做Check與單一viewer readiness；runtime transient、component-owned restart、idle cleanup及localized task-owned source/harness問題可現場修復、完整重驗後續跑。External lease採08:24／08:28／08:31 bounded recheck，不得代為release。
- 2026-08-24：正式Preopen提前至08:30起（最晚08:31），但只接受當下真實auction evidence；08:20 readiness不得替代session gate。只有需要credential/entitlement/人工作業、未知source ownership、外部lease逾窗口或session已錯過才PAUSED並通知。
- 2026-08-24：hidden/pagehide release是主動cleanup，TTL與120秒idle shutdown仍保留作fallback；不得以process kill取代正常release/idle cleanup。

- 2026-08-19：附件作為工程提案審核，不視為執行授權。
- 2026-08-19：C01採Trading Status專用currentness policy，不改全域resolver排序。
- 2026-08-19：C02沿用既有tri-state evaluator，只補eligibility policy truth。
- 2026-08-19：C03移除US general raw default中的technical/insider；insider market正規化為`US`以恢復explicit truth，但不擴大general default acquisition。
- 2026-08-19：現有21:00 runtime只作baseline；修正後仍須重新完成Gate R。
- 2026-08-19：Source、runtime、live provider、commit/push維持四個獨立授權面。
