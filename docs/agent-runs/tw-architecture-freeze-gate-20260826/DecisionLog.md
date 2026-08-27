# Decision Log

## Accepted planning decisions

### D-001 — 獨立Freeze Gate task

- Date：2026-08-26
- Decision：建立`tw-architecture-freeze-gate-20260826`，不覆蓋前一輪Shared Data Core歷史。
- Reason：source convergence與architecture freeze是不同acceptance層級。

### D-002 — Lifecycle executable authority

- Decision：Shared Registry + dataset lifecycle是executable dataset authority；TW Catalog是market inventory/projection。
- Constraint：TW session/applicability input由market layer提供；generic core不硬編。

### D-003 — Componentized quote evidence

- Decision：quote/depth/auction/official close以bundle編排，但保留獨立result/health/lineage。
- Rejected：單一merged provider、health或lineage。

### D-004 — Read / acquire split

- Decision：cache-only reader與explicit acquisition operation為不同entrypoint。
- Rejected：`read(... allow_acquisition=True)`、`refresh=True`隱藏side effect。

### D-005 — Consumer valuation boundary

- Decision：Portfolio只消費market-owned valuation result；不持有ORM/fallback/provider selection。
- Constraint：Account state與Market Data health分離。

### D-006 — Sidecar先分類後migration

- Decision：先指定owner/status/health/limitations，再決定canonical persistence。
- Rejected：為了形式統一建立generic JSON platform或一次搬完長尾。

### D-007 — EOD debt conditional

- Decision：EOD physical transaction closure為P2 conditional package，不阻塞P0/P1 freeze。
- Constraint：debt allowlist必須exact且不可擴大。

## Implementation decisions

### D-008 — Legacy auction durable identity

- Date：2026-08-26
- Decision：source contract由`auction`直接統一為`quote.auction`；`result_kind="auction"`維持不變。
- Evidence：唯讀DB inventory顯示0069 typed depth/auction tables存在但都是0筆，auction table沒有capability欄；3筆raw payload文字命中`auction`皆來自breadth/daily來源，不是realtime auction receipt。
- Migration：不需要資料migration或runtime alias；若未來發現外部consumer仍送舊capability，只能在明確compatibility boundary加deprecated alias，不可讓兩個canonical IDs並存。
- Runtime note：使用者DB實際已在`20260826_0072`，先前「尚未套0069～0072」判斷已過時。

### D-009 — Depth / auction dataset IDs

- Date：2026-08-26
- Decision：採用`tw.quote.order_book.snapshot`與`tw.quote.auction.snapshot`。
- Reason：兩者是獨立canonical observations、typed tables、quality/Resolver result，不與last-trade quote或presentation telemetry合併。
- Operation：共用explicit `tw.refresh_realtime_snapshot` command；read operations仍獨立cache-only。

### D-010 — Taiwan DatasetHealth input seam

- Date：2026-08-26
- Decision：新增market-owned lifecycle evaluator，讓TW reader提供calendar/applicability與candidate dates，再呼叫Shared `evaluate_dataset_health`。
- Rejected：generic Gateway猜TW session；frontend/AI重算freshness；把provider health當dataset health。

### D-011 — Quote evidence orchestration

- Date：2026-08-26
- Decision：以`TaiwanQuoteEvidenceBundle`編排quote/depth/auction/official close四個`MarketDataResultV1`，但不合併component health、lineage或limitations。
- Read：`read_taiwan_quote_evidence_bundle`固定cache-only。
- Acquire：`acquire_taiwan_quote_evidence_bundle`只由explicit AI acquisition dependency或POST/job呼叫。
- Projection：stable quote-depth outward shape保留，並新增四元`data_core_components`給AI component contract；trial/auction仍不會覆蓋actual trade。
- Official close：realtime snapshot只能是final-trade telemetry/candidate，不得自我確認official close；只有canonical completed daily result能升級outward close semantics。
- Daily ownership：quote projection不再direct query`MarketDailyPrice`/`SourceRegistry`；daily volume與close都由bundle內canonical bar提供。

### D-012 — Portfolio valuation ownership

- Date：2026-08-26
- Decision：Portfolio/AI只消費provider-neutral `ValuationPriceEvidence`；price storage query與market-specific fallback分別由TW/US/JP/KR market reader擁有。
- Taiwan：actual-trade canonical quote優先；不符合actual trade/facts usable時才讀completed official daily evidence；兩條路徑皆cache-only。
- Regional：US/JP/KR先以market-owned compatibility reader隔離舊daily storage，並明確標`REGIONAL_DAILY_LINEAGE_NOT_YET_SHARED_CORE`。
- Unknown rule：cost basis缺失不進cost total，unrealized PnL保持unknown；不得轉0。
- Rejected：Portfolio context直接import各市場price models、把Account state與Market Data health合併、偽稱regional compatibility已具canonical lineage。

### D-013 — GET compatibility flags fail closed

- Date：2026-08-26
- Decision：既有GET的`refresh`/`ensure_*`/provider參數可暫留schema compatibility，但true值只能409或被明示忽略，永遠不得啟動IO、commit或subscription。
- Commands：provider acquisition只由POST/job/lease觸發；POST完成後再由cache-only reader投影。
- Index：list/contribution/OHLC cache miss回truthful empty/missing/partial，不以GET填補來源。

### D-014 — Sidecar classification與holding cache

- Date：2026-08-26
- Decision：Corporate events、ETF、futures/derivatives引用TW Catalog；disposition與institutional holding ratio使用explicit `COMPATIBILITY_CACHE` exemption。
- Holding：atomic JSON cache、GET zero IO、POST bounded fetch；`canonical_truth=false`、`decision_usable=false`、`NO_RAW_FETCH_RESULT_LINEAGE`。
- Guard：每個classified surface的outward route、owner、read/refresh、storage、lineage、health與AI usability都是machine-readable且exact。

### D-015 — Canonical daily freshness owner

- Date：2026-08-26
- Decision：market-owned `tw_daily_freshness`只讀完整official canonical daily rows，使用Shared Registry evaluator產生`DatasetHealth`；AI不再raw-query`MarketDailyPrice`判斷freshness。
- Probe naming：`tw_dataset_health`是storage/lineage platform projection，不是完整freshness gate；新明確名稱取代catalog/router owner，舊名稱只作compatibility alias。
- Rejected：AI或source-health重新定義platform-owned price expected/current/stale semantics。

### Q-003 — Institutional holding storage（resolved by D-014）

- Options：typed canonical history、bounded file/DB cache + compatibility status、outward noncanonical exemption。
- Resolution：bounded atomic cache + compatibility status；未具raw receipt前不升級為canonical dataset。

### Q-004 — Disposition classification（resolved by D-014）

- Options：`COMPATIBILITY` dataset、explicit noncanonical cache class、canonical event table。
- Resolution：explicit noncanonical cache class；現有cache-only GET + explicit POST不可倒退。

### D-016 — Daily source health consumes canonical DatasetHealth

- Date：2026-08-26
- Decision：`source_health`對platform-owned daily price只投影`tw_daily_freshness`結果；不得再查相同storage建立第二套expected/current/stale判斷。
- Boundary：compatibility chips/fundamentals仍可暫留legacy evaluator，直到各自migration，不藉此假裝全市場已converged。

### D-017 — Disposition semantics fail closed

- Decision：只有`cache_status=current`且`is_active`為typed bool才能輸出continuous或batch-auction semantics。
- Rejected：missing/stale/degraded或malformed cache以false-y值推定`continuous/time_bars`。

### D-018 — Intraday auction is explicit TW policy

- Decision：active disposition在continuous session使用`AuctionType.INTRADAY`，並把type放入request、converter、transaction與repository reread。
- Constraint：Shared Core不理解disposition；opening/closing/intraday row不可互相被選中。

### D-019 — Platform evidence is not lifecycle health

- Decision：新canonical route名稱為`platform-evidence`，只回答storage/lineage；舊`/health`標deprecated compatibility。
- Rejected：把`freshness_status=not_evaluated`的probe outward稱為完整dataset health。

### D-020 — Quote vocabulary alias is market-owned and observable

- Decision：AI/API quote bundle對外一律使用`quote.snapshot`；market orchestration才轉成內部public last-trade capability `quote.last_trade`。
- Evidence：acquisition scope分開列requested capability、actual resource attempt與materialized canonical result。
- Rejected：implicit alias導致quote-only intent被當成空selection而刷新全部component。
