# Broker Branch Behavior Capability Contract

狀態：V0 observation quality、shadow feature、tracked job 與 read-only readiness report 已實作；`broker_branch.behavior` 仍未 advertised，V1 classification、flow-risk 與 Radar integration 仍未開放。本文同時定義已實作 V0 與後續 V1 gate，不代表未通過的能力已可 production 使用。

## 1. Product scope

- Market: Taiwan。
- Target: active TWSE／TPEx ordinary stocks；ETF、權證、inactive 與 unknown instrument 不自動納入。
- Purpose: 描述「可觀測分點流量的重現、反向、延續、淨額化與價格情境關聯」，提供研究 evidence 與反證。
- Not a claim: 不辨識單一投資人，不推定主力、真實部位、持有期間、隔日沖帳戶或未來必然買賣。

## 2. Dependency direction

```text
nStock / future licensed provider
        ↓
BrokerBranchObservationBatch
        ↓
backend-selected coverage / quality semantics
        ↓
shadow behavior features
        ↓
validated branch profile
        ↓
optional flow-risk evidence
        ↓
AI / API
        ↓
Frontend / MCP / Kuro / Radar
```

- Provider/parser 只做 bounded IO、payload parsing、provider error normalization 與 observation conversion。
- Service/job 擁有 persistence、transaction、incremental recompute 與 retry。
- Behavior engine 只讀 backend-selected observation batches，不呼叫 provider、不 commit、不做跨 provider fallback。
- Consumer 只呈現 backend contract。

## 3. Provider contract

### Current source

| Item | Contract |
| --- | --- |
| Provider | `nstock` |
| Resource | broker branch buy/sell Top15 snapshot |
| Coverage | `ranked_top_n` |
| Rank limits | buy 15、sell 15 |
| Absence | `unknown_not_ranked` |
| Event time | provider-reported Taiwan trade date |
| Fetch time | backend `fetched_at`／raw ingestion timestamp |
| Availability | conservative post-close release window，provider date probe authoritative |
| History | latest snapshot only；cannot provider-backfill past dates |
| Reliability | `third_party`、undocumented API contract |
| Cost/credential | current path no configured API key；usage/license remains an explicit risk |
| Bounds | per-stock timeout > 0；existing all-market max 2,500 stocks、max 7,200 seconds、sleep 0.5 seconds |

### Future source

- Licensed TWSE／TPEx full-daily data may use `coverage_mode=full_daily` only after actual product schema、price、delivery、license、history、normal/odd-lot/block-trade semantics and redistribution rights are verified.
- Full-daily and Top15 are separate candidates. Resolver/service selects one observation batch per source/stock/date; behavior engine never silently combines incompatible absence semantics.
- Purchasing or activating a paid source requires explicit user approval and a bounded cost plan.

## 4. Observation batch

Proposed provider-neutral batch fields:

```text
source_id
raw_result_id
stock_id
expected_trade_date
provider_trade_date
fetched_at
coverage_mode
buy_rank_limit
sell_rank_limit
observed_branch_count
absence_semantics
coverage_status
fetch_status
source_contract_version
includes_block_trades
warnings
```

### Coverage mode

- `ranked_top_n`: only ranked observations are known。
- `full_daily`: provider contract explicitly guarantees complete branch rows for the selected market/session/trade mode。
- `partial_provider`: response exists but provider says or evidence shows incomplete coverage。
- `unknown`: coverage cannot be established。

### Coverage status

- `censored`: valid TopN observation，absence remains unknown。
- `complete`: only valid for a verified full-daily contract。
- `partial`: some expected content or targets missing。
- `ready_empty`: successful eligible observation that is explicitly empty under a contract capable of confirming empty。
- `invalid`: malformed/schema-drifted payload。
- `missing`: no persisted observation attempt/evidence。
- `provider_failure`: timeout、blocked、rate limited、auth or transport failure。

`nStock + ranked_top_n` 正常狀態固定為 `censored`，不能升級成 `complete`。

## 5. Raw normalization

- `lots == 0` 時，derived observation 的同側 `avg_price = None`。
- Raw payload 與 raw table 不 destructive rewrite；V0 normalization 發生在 observation conversion seam。
- `branch_code`、`branch_name` 都保留 provider 原值與 normalized display value。
- V0 identity key 使用 `(source_id, branch_code)`；若 code 缺失，該 row 標 `invalid_identity`，不可只靠名稱自動合併。
- Alias、rename、merge 必須使用有 evidence 的 effective-dated mapping；單純去空白或字串相似度不能改變 canonical identity。
- 交易日以 Taiwan trading calendar 對齊；lookback 使用 sessions，不使用 calendar days。

## 6. Event and censoring semantics

對可計算次一交易日的每個 initial observation，只能得到：

- `opposite_flow_observed`: 次一 session 同 stock/branch 再進榜，且 net direction 相反。
- `same_direction_flow_observed`: 次一 session 再進榜，方向相同。
- `not_ranked_next_session`: 次一 session 未再進榜；outcome censored/unknown。
- `next_session_unavailable`: 下一交易日 raw batch missing/partial/invalid，不能評分。

不得產生：

- `closed_observed`
- `confirmed_unwind`
- `confirmed_zero_if_absent`（除非 selected source 是 verified `full_daily`）

Episode 只可描述連續「被觀測」的 same-direction/opposite-direction sequence。Top15 gap 結束時使用 `censored_gap`，不能解讀成 close。V0 不持久化 flow-episode table；先證明 feature/audit 需求後再決定。

## 7. V0 feature definitions

### Required flow-only features

```text
observation_count
eligible_initial_count
reobserved_count
opposite_observed_count
same_direction_observed_count
censored_count
session_count
stock_count
reappearance_rate
reverse_given_reappearance_rate
same_direction_given_reappearance_rate
censored_rate
gross_netting_ratio
observed_sequence_persistence
```

Definitions:

```text
reappearance_rate = reobserved_count / eligible_initial_count
reverse_given_reappearance_rate = opposite_observed_count / reobserved_count
same_direction_given_reappearance_rate = same_direction_observed_count / reobserved_count
censored_rate = censored_count / eligible_initial_count
gross_netting_ratio = 1 - abs(net_lots) / gross_lots
```

- Denominator 為 0 時結果是 `None`，不是 0。
- 每個 rate 回傳 numerator、denominator 與 interval；V0 使用 deterministic Wilson 95% interval。
- 同一 session 內跨股票 observations 高度相關，`observation_count` 不等同獨立樣本數；quality 同時揭露 `session_count`、`stock_count` 與 concentration。

### Optional price-context features

```text
momentum_buy_association
dip_buy_association
price_join_count
price_join_missing_count
price_context_status
```

- Join key: `stock_id + trade_date`，只允許 `as_of` 以前資料。
- 大量流量 threshold 需對股票流動性做標準化，例如 visible net lots / session volume 或 within-stock percentile；不能使用全市場固定張數門檻。
- 缺少 `market_daily_price` 時 flow-only profile 仍可計算，但 price-context 為 `partial`。
- `association` 只描述共同出現，不宣稱 causality 或 branch intent。

## 8. History/readiness gates

High-coverage session 暫定定義：當日 observation-batch status 可用，且 ordinary-stock universe coverage 至少 95%。門檻必須保存實際 numerator/denominator。

| High-coverage sessions | Allowed status |
| --- | --- |
| `< 20` | `insufficient_history` |
| `20–59` | `exploratory_only`，shadow metrics only |
| `60–119` | `calibration_candidate`，不得 production classify |
| `>= 120` | `production_candidate`，仍需 walk-forward gate |

Individual profile 另需最低 session、stock、reobserved denominator 與 concentration gate；未達一律 `insufficient_data`。Stock-specific profile 不以 global observation count 代替自己的有效歷史。

## 9. Classification contract

V0 不輸出 primary class，只輸出 feature components。

V1 候選類型：

- `next_session_opposite_flow_tendency`
- `short_horizon_mixed_flow`
- `persistent_same_direction_flow`
- `mixed`
- `insufficient_data`

禁止類型：

- `overnight_likely`
- `long_term`
- `trend_accumulator`
- `main_force`
- `institution`
- `smart_money`

V1 deterministic weights、thresholds 與 confidence mapping 必須來自 frozen training/calibration window，並在後續 out-of-sample sessions 驗證。文件中的示例權重不能直接成為 production constants。

## 10. Quality and uncertainty

不把所有限制壓成單一 confidence。Outward 至少分開：

- `coverage_quality`: source/target/session coverage。
- `statistical_interval`: rate estimate uncertainty。
- `history_status`: history gate。
- `calibration_status`: uncalibrated/calibrating/validated/failed。
- `data_freshness`: raw and derived dates。
- `decision_usable`: backend quality gate conclusion。

可以提供 summary `confidence_band`，但必須可追溯至上述 components，且 coverage/censoring 可設上限。

## 11. Persistence contract

### V0 required table

`broker_branch_snapshot_quality`

- Unique selected-state key: `(source_id, stock_id, expected_trade_date)`。
- 保存 latest selected observation state；每次原始 attempt 仍由 `RawFetchResult`／provider event 保留。
- 支援 empty、partial、invalid、provider failure 與 provider-date mismatch，不依賴 trade row existence。
- Upsert/idempotent；transaction failure rollback and rethrow。

### Shadow feature table

`broker_branch_behavior_feature_snapshot`

- Key: `(source_id, branch_identity_key, scope_type, scope_id, as_of_trade_date, lookback_sessions, methodology_version)`。
- 保存 feature numerators/denominators、intervals、coverage、history/calibration status、source max date、price max date、computed_at、input fingerprint。
- `scope_type`: `global`、`stock`; `sector` deferred until sector identity/history semantics are proven。

### V1 profile table

`broker_branch_profile_snapshot`

- 只有 V1 calibration gate 通過後才新增或啟用寫入。
- 不讓 stock-specific 低樣本 profile 覆蓋較高品質 global evidence。

### Deferred

- `broker_branch_flow_episode`: V0 不建表。
- `broker_branch_flow_risk_snapshot`: 只在 flow-risk methodology gate 通過後新增。

## 12. Incremental compute and jobs

- Raw collector 保持既有 owner，不在 provider transaction 內同步跑 heavy research compute。
- Derived job target 使用 `trade_date + methodology_version`，再由 DB 查詢該日期 affected branches/stocks；不把數千 IDs 塞進 job JSON。
- 每次只讀 bounded lookback sessions，預設上限 120；不得掃描全部歷史。
- Raw coverage partial 時允許產生 partial shadow snapshot；reconciliation 後 coverage/input fingerprint 改變時可 idempotent recompute。
- Global snapshot 每日最多一個 methodology version；stock snapshot 只計算當日 affected stocks。
- Job output 保存 input coverage、rows read、profiles written/skipped、partial/error counts、runtime 與 next retry。
- Read path 只讀 snapshots；不隱性 recompute。
- 是否新增 composite DB index 先以 `EXPLAIN QUERY PLAN` 與 bounded benchmark 決定；不得只因猜測就在 24 GB local DB 上建立重索引。

## 13. Freshness

分開保存／投影：

- `source_as_of`: selected raw branch observation date。
- `price_source_as_of`: price-context latest joined date。
- `derived_as_of`: feature snapshot input cutoff。
- `computed_at`: derived execution time。
- `methodology_version`: algorithm contract。
- `input_fingerprint`: exact bounded input identity。

Rules:

- raw stale => behavior warning/stale，即使 derived computation 很新。
- raw current + derived lagged => behavior stale/partial。
- raw current + price partial => flow-only current，price-context partial。
- methodology changed + old snapshot => incompatible/stale until recomputed。
- cache-only read never refreshes raw or derived evidence。

## 14. Outward capabilities

### `broker_branch.summary`

- Unchanged。
- Answers who is in current/recent stored Top15 summaries。

### `broker_branch.behavior`

- V0: not advertised；shadow/admin evidence only。
- V1: advertise only with registry、projection、quality、query-plan and contract tests complete。
- Required outward fields:
  - `as_of`
  - `source_as_of`
  - `lookback_sessions`
  - `coverage_mode`
  - `coverage_quality`
  - `history_status`
  - `calibration_status`
  - `methodology_version`
  - `profiles[]`
  - `warnings`
  - `freshness`

### `broker_branch.flow_risk`

- Deferred until V1 behavior is validated。
- Dimensionless output only:
  - `short_horizon_flow_risk_index`
  - `visible_entry_lots`
  - `observed_opposite_flow_lots`
  - `components`
  - `coverage_quality`
  - `history_status`
  - `methodology_version`
  - `warnings`
- No `weighted_short_term_lots`、`confirmed_unwind`、`remaining_inventory`。

Both derived capabilities use backend capability-specific data paths and freshness. They may share the coarse `broker_branch` domain/slot for compatibility, but manifest、quality and `evidence.data` remain capability-specific。

## 15. Query and answer behavior

- 「今天／最近 N 日分點買賣」=> `broker_branch.summary`。
- 「歷史上再出現時偏反向或延續」=> `broker_branch.behavior`。
- 「目前是否有短期反向流量風險」=> `broker_branch.flow_risk` + optional quote/technical evidence。
- 問句使用「隔日沖」時，answer 可以解釋 colloquial intent，但 canonical claim 必須是 observed next-session flow tendency。
- Pure broker-branch path 不偷載 fundamentals；multi-domain query 使用 standard reader/selection。
- `insufficient_data` 是成功但受限的 business result，不用 placeholder 或 fabricated class。

## 16. Consumer contract

- Frontend 顯示 observed/censored、lookback sessions、history/calibration status 與 methodology version。
- UI 不把 0–100 risk index 標成張數或機率。
- MCP/Kuro 原樣消費 v4 evidence，不維護分點名單或門檻。
- Radar 只把 validated flow-risk 當 counter-evidence；低品質／partial evidence 不改變 breakout/support quality。

## 17. Failure matrix

| Failure | Required behavior |
| --- | --- |
| Provider timeout/network | structured provider event；保留既有 cache；quality 不冒充 current |
| 429 | rate_limited + Retry-After；不密集 retry |
| 401/403/blocked | explicit provider status；不切成 fake empty |
| Empty Top15 payload | 保存 raw attempt + quality；未證實 full-daily 時不得 `ready_empty` |
| Malformed/schema drift | `invalid` + safe error；不 silent drop |
| Single stock failure | market job partial；不清除其他 stock/date rows |
| Raw partial coverage | derived partial；保留 numerator/denominator |
| Price join missing | flow-only retained；price-context partial |
| Derived transaction failure | rollback；old snapshot remains selected |
| Methodology mismatch | old snapshot incompatible/stale；不混用 versions |
| Insufficient history | `insufficient_data`；不輸出 class/risk conclusion |

## 18. Validation contract

- Parser/observation: normal、empty、malformed、rank bounds、zero avg-price normalization、provider-date mismatch。
- Quality persistence: ready/censored/partial/invalid/failure、upsert、rollback、ready-empty guard。
- Behavior pure tests: absent != zero、denominators、intervals、contiguous sessions、no look-ahead、price join partial。
- Incremental service: bounded 120 sessions、input fingerprint、idempotency、partial recompute、methodology version isolation。
- Migration: upgrade/downgrade、existing raw table/data preserved、model registry。
- Capability: resolution dependency、freshness、projection、manifest、field allowlist、payload budget、advertised invariant。
- Query/answer: summary vs behavior vs flow-risk、pure fast path、multi-domain scope、truthful Chinese copy。
- Transport: HTTP/SSE/MCP v4 parity。
- Runtime: selected PID/port、migration head、job result、representative cache-only API/MCP、source/derived date evidence。
- UI/Radar: only after corresponding milestone；lint/typecheck/build and browser evidence when user-visible behavior changes。

Read-only readiness command（repo root）：

```powershell
.\.venv\Scripts\python.exe -B .\scripts\report-broker-branch-behavior-readiness.py --format json --pretty
```

- 只讀 `broker_branch_behavior_feature_snapshot`、`broker_branch_snapshot_quality` 與 source metadata，不呼叫 provider、不寫 DB、不揭露 branch identity。
- `broker_branch.behavior.readiness_report.v0` 只負責 eligibility、coverage consistency 與 walk-forward split planning；`validation_results_present=false` 時固定不得 promotion。
- 2026-08-22 live evidence 只有 25 個 high-coverage sessions，因此結論為 `exploratory_only`／`shadow_only`；詳見 `BoundaryReport.md`。

## 19. Source and release safety

- 本機 SQLite、raw payload、derived snapshots 不進 Git。
- Public sample/fixture 使用 synthetic rows，不複製第三方 production data。
- Open-source code若包含 provider adapter，需另行確認服務條款與 redistribution boundary；未確認時以 feature flag/explicit local configuration 隔離。
- 正式接入 TWSE／TPEx paid data 前，先取得 explicit cost approval，並確認 listed/OTC、ordinary/odd-lot/block trade、history、delivery、internal/external-use licenses。
