# Plan

## Milestones

1. 固定 continuity 與 repair contract
   - Scope: task docs、US OHLC schema、pure trading-calendar／continuity helper。
   - Acceptance: additive fields能區分freshness、tail gap、歷史深度與previous-close validity。
   - Validation: `pytest backend/tests/test_us_market_data.py -k "ohlc or previous_close"`

2. Backend fail-closed correctness
   - Scope: `app.us_market.service`、intraday previous-close reference、OHLC projection。
   - Acceptance: reference date不符expected completed session時不 outward stale close；overlay不改變finalized freshness truth。
   - Validation: exact UMC/SPX fixture regressions。

3. Explicit bounded repair與priority lifecycle
   - Scope: per-symbol repair service/job/API、priority universe、durable JobRun cursor、scheduler/startup catch-up、Dataset Registry。
   - Acceptance: indices／holdings／enabled watchlist先於full-market cursor；每次有明確call/runtime/error bounds與postcondition。
   - Validation: `pytest backend/tests/test_eod_coverage.py backend/tests/test_eod_coverage_scheduler.py backend/tests/test_us_market_data.py`

4. Frontend contract cutover
   - Scope: market types、US detail chart/header、repair enqueue／job polling與data status events。
   - Acceptance: frontend不以array adjacency推 previous close；缺口顯示local compact status，operation detail在更新狀態；GET保持cache-only。
   - Validation: frontend lint、TypeScript、build；必要browser smoke。

5. Regression與runtime acceptance
   - Scope: safe validation、live API／SQLite／provider-bounded smoke、Progress.md。
   - Acceptance: tests通過；live payload可證明missing gap、repair postcondition與correct reference date；無unrelated diff。
   - Validation: `run-safe-validation.ps1` targeted backend/frontend profiles與read-only/runtime probes。

6. Runtime contention remediation
   - Scope: OHLC intraday cache-read Session、repair／priority tracked-job Session ownership、SQLite engine pool policy、historical chart首屏、startup staggering、frontend additive-contract compatibility。
   - Acceptance: provider wait不占SQLite pooled connection；SQLite不因固定QueuePool容量拖垮無關readiness；priority reconcile不重用JobRun Session；歷史K線首屏不等待intraday provider；舊backend payload不使frontend `.join()`崩潰。
   - Validation: `pytest backend/tests/test_database_contention_boundaries.py backend/tests/test_us_ohlc_contract.py backend/tests/test_us_ohlc_priority.py backend/tests/test_eod_coverage_scheduler.py`，frontend TypeScript／targeted ESLint，runtime `readyz`／jobs／cache-only OHLC timing probe。

## Stop-and-fix rules

- 若GET、render或source-health read path觸發provider I/O／job enqueue，立即停止並修正owner。
- 若priority scheduler可能無界掃描、每次重抓已current/full-history symbol或消耗Alpha Vantage quota，先修正再繼續。
- 若previous-close reference date不符仍 outward數值，視為blocking correctness failure。
- 若continuity把休市日當缺口、把unknown eligibility當0或偽造bar，視為blocking data failure。
- 若migration會刪除、重建或覆蓋existing SQLite，停止並改用additive/persisted seam。
- 若frontend新增duplicated inline operational error而未送更新狀態，先修正。

## Decisions

- 2026-08-24：先保證wrong number impossible，再提高repair速度；repair最終一致性不能替代fail-closed presentation。
- 2026-08-24：保留OHLC GET cache-only；viewer-selected repair使用explicit tracked POST job。
- 2026-08-24：priority lifecycle和full-market stock coverage分開，避免把indices偽裝成stock universe。
- 2026-08-24：priority target order為index、active US holdings、enabled active watchlist；一般stock繼續full-market bounded cursor。
- 2026-08-24：latest-session postcondition與history-depth postcondition分開，new listing不足歷史不得阻塞latest correctness。
- 2026-08-25：不以放大QueuePool掩蓋問題；修正cache read／provider IO／write的Session ownership。startup delay保留可設定但預設0，因單worker FIFO下固定延遲會讓priority repair排在長任務後方。
- 2026-08-25：SQLite採`NullPool`作跨endpoint fail-safe，Session close即釋放file handle；歷史K線先呈現completed-session cache，intraday不再阻塞首屏。
