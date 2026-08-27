# Risk Register

| ID | Risk | Likelihood | Impact | Mitigation / stop condition | Status |
|---|---|---:|---:|---|---|
| R-01 | Blind rename`auction`破壞durable receipt identity | M | H | BASE-01 read-only DB inventory；有資料則formal alias/migration | OPEN |
| R-02 | DatasetHealth被放進generic Gateway並硬編TW policy | M | H | market lifecycle evaluator + forbidden import guard | OPEN |
| R-03 | Quote bundle合併不同component lineage | M | H | typed component results；parity/lineage tests | OPEN |
| R-04 | AI/MCP projection宣告supported但production reader無資料 | H | H | canonical-row vertical tests，不接受synthetic-only evidence | OPEN |
| R-05 | Portfolio valuation fallback移動時改變price semantics | M | H | additive reader、golden fixtures、unknown/stale tests | OPEN |
| R-06 | GET compatibility flag仍可間接refresh | H | H | call-graph/runtime sentinels，不只函式名稱AST | OPEN |
| R-07 | Sidecar被過度canonicalize造成migration/data污染 | M | H | 先classification；typed storage需獨立decision/replay理由 | OPEN |
| R-08 | Freshness收斂造成outward breaking response | M | M | 保留field shape，以adapter投影新health | OPEN |
| R-09 | Futures provider parameter相容性移除破壞client | M | M | deprecated但ignore/reject；provider由backend plan決定 | OPEN |
| R-10 | EOD cleanup擴大到US/scheduler rewrite | M | H | EOD-01 conditional；超界即DEFERRED | OPEN |
| R-11 | Dirty worktree覆蓋US/scheduler/frontend hunks | H | H | 每包pre-diff ownership；無法共存則BLOCKED | OPEN |
| R-12 | Prior runtime pass被誤當新source adopted | H | H | source變更後ADOPT-01必重跑 | OPEN |
| R-13 | Post-close或fixture被冒充live acceptance | M | H | official-session chronological artifacts；缺證據PENDING | OPEN |
| R-14 | Full-suite unrelated failures掩蓋task failure | M | M | targeted gate先全綠；unrelated failure明確隔離 | OPEN |
| R-15 | Health layers被合併成單一正常/異常 | M | H | Provider/Dataset/Resolved schema與tests分離 | OPEN |
