# US Market Data Core Integration Risk Register

## 使用方式

- Probability／Impact：`low`、`medium`、`high`。
- Status：`open`、`monitoring`、`mitigated`、`accepted_with_limit`、`closed`。
- 每個work package開始與完成時重新檢查相關risk。
- 風險若觸發stop condition，先更新`Progress.md`與本表，不跨gate繼續。

## Active risks

| ID | Risk / trigger | P | I | Owner boundary | Prevention / early evidence | Contingency | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| R-01 | Dirty worktree含TW Core、M5、US OHLCV交疊修改；同檔覆寫他人工作 | high | high | Program governance | A0已固定branch/SHA/status與21檔hash；持續exact-scope diff | 暫停衝突檔；協調owner或拆更小seam | monitoring |
| R-02 | US依prototype猜final Core API，形成永久compatibility layer | medium | high | Shared Core handoff | G0要求final version/code/tests/handoff packet | 刪除未接production的guess binding；回G0 | open |
| R-03 | 台股Core只有source/dark/shadow，卻被誤認可供US production | high | high | Shared Core handoff | G0-14/15要求actual-data、runtime與TW closure | 保持B1+ blocked | open |
| R-04 | Priority scheduler source default enabled，未接Core便自動呼叫Yahoo | high | high | Dataset lifecycle/runtime | A2已default off，workflow即使啟用也external calls=0 | runtime adoption前不宣稱live已採用 | mitigated |
| R-05 | Public provider selector有repo外consumer，直接移除造成breaking change | medium | high | API compatibility | caller inventory、OpenAPI snapshot、deprecation plan | 保留deprecated diagnostic route；product route provider-neutral | open |
| R-06 | 現有`USDailyPrice`/source tables不足保存final lineage/quality/finalization | medium | high | Persistence/DB | A3 repository contract、schema readback、gap report | 獨立additive migration proposal；不silent drift | open |
| R-07 | Yahoo unstable/block/rate-limit造成compare/canary噪音 | high | medium | Provider port/rollout | fixture first、bounded calls、provider health/error normalization | 降回cache/off；不以retry放大quota | open |
| R-08 | AlphaVantage free/plan quota不足，fallback驗證耗盡額度 | high | medium | Provider policy/validation | fake fixtures為主；live smoke需明確call budget | 標plan_restricted/rate_limited；延後live fallback smoke | open |
| R-09 | Raw-unadjusted daily bars缺corporate-action completeness，technical結果被過度用於decision | high | high | US policy/research | 保留price basis、corporate-action limitation與decision_usable gate | facts可顯示但decision blocked；不假裝adjusted | open |
| R-10 | 美東timezone、DST、early close、extended hours導致session/bar切錯 | medium | high | US market policy | calendar fixtures、timezone-aware timestamps、dated session tests | 保持legacy/off或partial；修policy後重跑compare | open |
| R-11 | 跨provider欄位被混成一筆candidate，lineage失真 | medium | high | Adapter/candidate store/Core | A3 all-provider batch保留獨立records；G0仍需Core conflict fixtures | 拒絕candidate/mark invalid；不進resolver on | monitoring |
| R-12 | Watchlist/ranking多symbol resolved read產生N+1與UI latency regression | medium | medium | Candidate repository/projection | batch API、query count、376/500-symbol performance baseline | 保持legacy read；優化batch後再canary | open |
| R-13 | Provider/Dataset/Resolved health混用，fallback結果被錯誤標stale/healthy | medium | high | Shared Core/outward projection | G0 health contracts、scenario matrix | 阻擋consumer cutover；保留完整limitations | open |
| R-14 | HTTP/SSE/MCP/Frontend各自投影US semantics，Decision v4或UI分叉 | medium | high | Consumer cutover | shared projection、contract snapshots、transport parity/golden tests | rollback個別consumer；不在consumer補logic | open |
| R-15 | KGI US entitlement/capability未知卻advertise supported | high | high | US provider catalog | readiness/live sample before descriptor registration | 維持planned/unavailable；不納入closure必備scope | open |
| R-16 | 一次切全市場daily/intraday導致quota、latency、資料污染難以回退 | medium | high | Rollout | single-symbol→bounded set→priority universe；per-capability mode | 立即回前一mode；不刪candidate資料 | open |
| R-17 | Source修改後runtime仍跑舊SHA/舊port，誤判修復成功 | high | high | Runtime acceptance | official launcher selected PID/port/mode/source identity | 停止驗收；在獲授權後精準restart named component | open |
| R-18 | Repair operation回success但coverage/postcondition未達標 | medium | high | Dataset lifecycle | mandatory reread/postcondition、partial result | 標partial/failed、保留cursor與remaining coverage | open |
| R-19 | Provider IO期間持有SQLite transaction造成contention/lock | medium | high | Transaction owner | DB contention/fault tests、IO outside transaction | rollback/rethrow；拆mutation owner | open |
| R-20 | Rollback依賴schema downgrade或刪除新資料而不可安全執行 | low | high | DB/rollout | additive schema、compatibility reader、mode rollback | 不升canary；另行migration/backup設計 | open |
| R-21 | AST/string guard把lineage展示誤判為provider control，造成維護噪音 | medium | medium | Boundary tests | AST route/call classification與US request segment scan已通過 | 收斂guard scope；不關閉整體boundary protection | mitigated |
| R-22 | Authority datasets被錯誤納入quote/OHLC fallback架構 | low | high | US domain | ArchitectureMap ownership與import tests | 回退genericization；保留shared lifecycle envelope即可 | open |
| R-23 | External live/provider smoke在未授權下消耗quota或改寫本機資料 | medium | high | Validation/trust | Track A只跑fixture/in-memory/source checks；external calls=0 | G0後live/write仍需明確授權與budget | mitigated |
| R-24 | Legacy removal過早，compare mismatch時無可用rollback | medium | high | Closure | F3依賴all on + rollback rehearsal + stability window | 保留具名compatibility seam直到closure gate | open |

## Risk thresholds

以下任一情況自動阻擋下一個production gate：

- 任一open `high impact` risk已觸發且沒有可驗證mitigation。
- Runtime source identity、port、mode或lease ownership不明。
- External call／quota bound無法計算。
- DB migration或transaction owner尚未審查。
- Public contract breaking caller inventory未知。
- Resolver selection、candidate coherence或lineage有任何未分類mismatch。
- `cache_only`或completed-session read觀察到external IO/write。

## Decision/escalation records

重大風險處置記錄格式：

```text
date:
risk_id:
trigger/evidence:
affected_package:
decision:
owner_boundary:
mitigation:
validation:
remaining_risk:
next_gate_status:
```
