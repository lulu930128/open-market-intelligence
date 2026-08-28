# 台股 Backend Outward Contract 收斂計畫

## 執行原則

- 本計畫承接既有 Shared Data Core、Gateway、Resolver、Dataset Registry、`daily_ohlcv_platform`、TW market policy與`omi.decision.v4`，不建立平行核心。
- 每一個issue只有一個canonical owner與主要milestone；consumer regression可在後續milestone補驗證，但不得複製market logic。
- 依序完成M0→M1→M2→M3；M4可在M1 truth contract穩定後開始，M5依賴M1–M4的canonical狀態，M6最後執行。
- 每個milestone先補會失敗的negative fixture，再做局部修改；測試沒有涵蓋真實bug時，不以既有green suite當完成證據。
- Source、Runtime、Live、Product gate分開更新`Progress.md`；不能用後一層證據回填前一層失敗。
- 不在read path觸發provider IO或DB mutation；normal acquisition只能由scheduler/job owner，repair只能由explicit bounded operation。

## Target ownership map

| Responsibility | Canonical owner to extend | Forbidden owner |
| --- | --- | --- |
| TW official daily release calendar | `backend/app/market/taiwan_rules.py` / trading calendar | Frontend、MCP、technical local clock |
| Released completed daily eligibility | `backend/app/market/daily_ohlcv_platform.py` + existing repository/transaction seam | chart service、freshness SQL、sector/ranking consumer |
| Storage/release lineage | existing `MarketDailyPrice` + `RawFetchResult` + transaction reread | consumer inference |
| Dataset freshness | existing dataset lifecycle/health + released candidate set | raw table `MAX(date)` |
| Sequence coverage/continuity | existing AI capability quality resolver with TW calendar input | payload-exists fallback |
| Technical sufficiency/score | backend technical analysis owner | frontend/MCP score repair |
| Intraday bars acquisition | `app.market.tw_intraday_platform` + dedicated bounded scheduler/job | GET、AI reader、Frontend viewer |
| Intraday age/usability | `tw_intraday_state.py` + canonical freshness policy | screening projector |
| Index/breadth status | existing current market Resolver/result | Dashboard/AI local aggregate |
| Applicability/selection | existing capability registry/query planner | reader-after-the-fact cleanup |
| Public contract | `omi.decision.v4` + Backend registry | MCP/manual duplicated enum |

## Issue traceability

| Issue | Disposition | Primary milestone |
| --- | --- | --- |
| P0-01 current-session daily提前finalized | 修復 | M1 |
| P0-02 freshness接受future-of-release row | 修復 | M1 |
| P1-01 daily污染sector/ranking日期 | 修復；保留既有sample-only gate | M1 |
| P1-02 requested history不足仍complete | 修復 | M2 |
| P1-03 daily continuity not applicable | 修復 | M2 |
| P1-04 technical不足仍強score | 修復 | M3 |
| P1-05 technical volume unit lineage遺失 | 修復 | M3 |
| P1-06 index outward status不一致 | 修復 | M5 |
| P1-07 breadth authoritative/legacy雙軌 | compatibility migration | M5 |
| P1-08 stale intraday仍decision usable | 修復 | M4 |
| P1-09 intraday bars缺normal scheduler | 新增既有owner下的bounded scheduler | M4 |
| P1-10 `TAIWAN_TZ` NameError | 局部修復與全surface regression | M4 |
| P2-01 `quote.session_close` MCP parity | 目前source/backend已通過；驗證installed/runtime adoption | M5/M6 |
| P2-02 policy-disabled折疊not applicable | 修復taxonomy/planner outcome | M2/M5 |
| P2-03 freshness與capability usability矛盾 | 強化既有六軸aggregate，不建新model | M2/M5 |
| P2-04 ETF applicability gate太晚 | 修復early planning/dispatch | M5 |
| P2-05 data-only被position context升級 | 修復intent lock | M5 |
| P2-06 explicit selection未限制execution | 修復dependency graph/reader plan | M5 |
| P3-01 source-health summary沒有problem row | 保留hard budget；增加budget-aware preview contract | M5 |
| P3-02 daily `bars` int/list碰撞 | additive去歧義與compatibility gate | M2/M5 |

## Milestones

### M0 — Baseline、contract freeze與failing fixtures

- Scope：只建立可重現fixtures、consumer inventory、owner map與baseline capture；不改production behavior。
- 主要檔案類型：
  - `backend/tests/` temporal、quality、technical、planner、surface contract tests。
  - 必要的recorded raw excerpt／in-memory SQLite fixture；不得複製production DB或保存私人資料。
- Required fixtures：
  1. Pre-release DB已存在today official-source-shaped row。
  2. 15:15 clock已到但沒有post-release receipt。
  3. 15:15後有qualified receipt且transaction reread成功。
  4. Request 20、return 20/19/13/1/0。
  5. Daily duplicate、unordered、trading-day gaps。
  6. Technical daily count 1/10/20/60/120。
  7. Intraday event age 20s/90s/5m/60m。
  8. Same index timestamp跨Dashboard/AI projection。
  9. 0050 not-applicable fundamentals。
  10. Data-only explicit selection與saved position context。
- Acceptance：上述fixtures在修復前能精確重現對應問題；baseline輸出不依賴wall-clock race。
- Negative acceptance：不得以直接修改production DB、manual refresh或frontend filtering製造fixture。
- Validation：

```powershell
Set-Location backend
& ..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider `
  tests/test_tw_official_daily_platform.py `
  tests/test_tw_daily_freshness.py `
  tests/test_ai_technical_analysis.py `
  tests/test_tw_intraday_market_capabilities.py `
  tests/test_mcp_schema_contract.py
```

- Stop：若現有raw receipt與row lineage無法區分pre/post-release ingest，先完成M1 storage decision，不假設無schema方案可行。

### M1 — Released Completed Daily Truth

- Scope：P0-01、P0-02、P1-01。
- Target flow：

```text
Official acquisition
  -> Raw receipt
  -> Existing TaiwanOfficialDailyTransaction
  -> MarketDailyPrice + lineage
  -> ReleasedCompletedDailyReader
       - requested range clamp
       - expected release date
       - release-qualified receipt/transaction
       - canonical lineage
  -> MarketDataGateway / Resolver
  -> chart / freshness / sectors / rankings / technical / AI-MCP
```

- Implementation slices：
  1. 在existing daily platform/repository seam建立唯一released candidate predicate；名稱可依現有pattern調整，不新增平行service plane。
  2. Explicit `to_date`一律clamp至latest potentially released trading date，並回傳`REQUESTED_TO_DATE_EXCEEDS_LATEST_RELEASED_DAILY_DATE` limitation。
  3. Release qualification不得只看wall clock；必須要求可證明的post-release receipt／transaction qualification。
  4. `list_stock_ohlc_chart_data()`不再用`date.today()`決定completed end date。
  5. `read_taiwan_daily_freshness()`與batch freshness改讀同一released set；需要時同時揭露`storage_latest_date`與`released_latest_date`。
  6. Market sectors、sample ranking、distribution、top movers、value leaders與industry ranking停止讀generic raw latest date。
  7. 保留現有`sample_only / partial / is_full_market=false / decision_usable=false` coverage projection。
- Acceptance：
  - 14:00 storage有D row：所有completed consumer latest≤D-1。
  - 15:16、沒有post-release qualified ingest：latest仍≤D-1，release status為pending/missing after release，不得current。
  - 15:16、qualified ingest成功且reread：latest=D，可released/finalized/current。
  - Full-market 1/1973時trade date不超過released date，quality保持sample-only與decision unusable。
- Negative acceptance：
  - 禁止frontend、MCP、technical、sector各自加入15:15判斷。
  - 禁止只修caller而不保護daily platform public boundary。
  - 禁止以pre-release receipt在clock到達後自動升格。
- Targeted validation：新增或等價測試：
  - `test_tw_completed_daily_release_boundary.py`
  - `test_tw_daily_freshness.py`
  - `test_taiwan_market_context.py`
  - `test_market_daily_backfill_release_guard.py`
- Stop：若需要migration，完成isolated upgrade/downgrade、existing-row backfill semantics與rollback文件後，才進M2；不得直接套production DB。

### M2 — Sequence Quality、Continuity與Status Taxonomy

- Scope：P1-02、P1-03、P2-02、P2-03、P3-02。
- Implementation slices：
  1. 在existing quality resolver加入capability-specific `evaluate_sequence_coverage()`，輸入requested/effective/returned/available count、requested window、observed window、truncated與continuity。
  2. Daily continuity使用TW trading calendar，不以自然日判gap；輸出continuous、gap_detected、duplicate、unordered、partial。
  3. Coverage taxonomy至少區分complete、partial、insufficient_history、valid_empty、missing。
  4. Applicability、availability、request policy與execution outcome分開；`not_fetched_due_to_policy`不得折疊成not applicable。
  5. 沿用existing `CapabilityStatus`與`data.freshness`六軸aggregate，補正upstream canonical status；不新增平行status model。
  6. Daily payload新增明確`requested_bar_count`、`available_bar_count`、`returned_point_count`；array固定為`points`。
  7. 盤點`bars`所有Backend、MCP、Frontend consumers，明定其legacy count語意或移入compatibility namespace；禁止projector再把int當list。
- Acceptance：
  - 20→20 complete；20→19/13/1 insufficient_history或partial；0 valid-empty與0 missing可區分。
  - 最近20個交易日缺7個時continuity=`gap_detected`，technical decision unusable。
  - Applicable但policy forbids fetch時為policy_unsatisfied/not_fetched_due_to_policy，decision unusable。
  - `data.freshness.status`由selected required capabilities aggregate，temporal current不再等價fully usable。
- Negative acceptance：不得以payload truthiness推complete；不得把周末／假日當missing trading day；不得直接破壞`omi.decision.v4`既有consumer。
- Validation：quality resolver、decision envelope、daily projection、MCP schema與golden contract targeted tests；執行architecture checker。

### M3 — Technical Sufficiency與Measurement Lineage

- Scope：P1-04、P1-05。
- Implementation slices：
  1. 新增或整合`TechnicalEvidenceSufficiency`，至少記錄daily bar count、required count、available/required factor count、major indicators、timeframe coverage與continuity。
  2. 在indicator/factor normalization與decision score前執行sufficiency gate。
  3. Insufficient時可保留有明確scope的raw factual indicator，但`normalized_decision_score=null`、`decision_usable=false`；不得輸出強多／強空stance。
  4. Horizon minimum由backend strategy contract定義並測試；初始建議short≥20、swing≥60、long≥120，最終值需與現有indicator warm-up與product語意對齊，不只硬編數字。
  5. Technical derived quantity繼承`volume_unit`、price unit、currency與`source_capability=daily.ohlcv`；避免同時保留互相矛盾的裸numeric與quantity object。
  6. Levels、ATR fallback與scenario若依賴不足history，也必須limited或unavailable，不能只封鎖headline score。
- Acceptance：1 bar score null；10 bars partial；20/60/120依horizon門檻；continuity gap即使count足夠也不可正式decision score。
- Negative acceptance：不得對剩餘單一factor重新normalize到±7；不得由Frontend/MCP補算缺失technical。
- Validation：`test_ai_technical_analysis.py`、technical report、decision envelope、TW technical projection與Frontend authority contract targeted tests。

### M4 — Current-session Freshness、Intraday Acquisition與Runtime Error

- Scope：P1-08、P1-09、P1-10。
- Implementation slices：
  1. 修正`tw_current_market_platform.py` timezone import，統一使用`app.market.trading_calendar.TAIWAN_TZ`；掃描所有current-index call paths。
  2. `tw_intraday_state`先計算observation age與session-aware freshness，再決定facts/research/decision usability。
  3. Regular session stale/delayed row只保留bounded factual use；即時decision usability要求current且age≤policy threshold。
  4. Post-close completed-session facts不得套用regular live age邏輯；改由session-close/finalization owner決定用途。
  5. 在existing `app.market.tw_intraday_platform` owner下建立dedicated scheduler/job，不新增reader-side acquisition。
  6. Scheduler v1使用bounded target union：watchlist、holdings、actively viewed/leased；hard cap、dedupe、per-run call budget、timeout、retry/backoff、idempotent persistence與provider/dataset health全部可觀測。
  7. Startup catch-up只修可修復的current session materialization；powered-off期間無法重建的intraday gap保持missing，不偽造bar。
- Acceptance：
  - 20s current可decision；90s依明定threshold；5m/60m regular-session不得decision usable。
  - `tw.intraday.bars`正常scheduler可為bounded active targets materialize persisted bars；viewer read保持external calls=0。
  - TAIEX/TPEX intraday、events supplemental、dashboard、scheduler與index capture都不再NameError。
- Negative acceptance：不得full-market常駐抓取、read-on-demand provider fetch、broad kill process、viewer lease強制釋放或用quote snapshot偽造1m bars。
- Validation：intraday state、scheduler fake clock/provider、idempotency、index intraday endpoints、source health與zero-I/O read tests。

### M5 — Planner、Applicability與Outward Surface Convergence

- Scope：P1-06、P1-07、P2-01、P2-04、P2-05、P2-06、P3-01及M2 compatibility closure。
- Implementation slices：
  1. AI market context、Dashboard與API只投影existing canonical index/breadth result；移除local ready/current/decision upgrade。
  2. Authoritative fields保留primary namespace；legacy projection移入`compatibility`或明確標deprecated、canonical_ref、decision_usable=false。
  3. 擴充existing capability registry/spec的instrument applicability，planner在reader dispatch前停止ETF不適用能力；不得再建平行registry。
  4. Data-only explicit selection鎖定response intent；saved position只能作supplemental context，不能改`answer_kind`或`decision_required`。
  5. Planner建立selected capabilities的hard dependency graph；explicit locked只執行required/optional與hard dependencies，其他reader列為prohibited。
  6. Event/quote/broker現有fast path推廣為通用planner invariant，standard profile不再代表unbounded context assembly。
  7. Backend registry與repo MCP enum維持generated/parity test；installed MCP adoption只在M6驗證。
  8. Source-health normal budget至少回top problem preview；hard byte budget不足時允許summary-only，但必須標truncated、degradation level與returned/total count。
- Acceptance：
  - Same index timestamp在Dashboard、direct API、AI、MCP的freshness/finalization/decision/provider/event time一致。
  - AI/MCP projector不掃legacy breadth/index path。
  - 0050 revenue/financials not applicable時不執行reader、不建立blocked payload、不產生refresh action或無關health noise。
  - Data-only daily request不因saved position變成position decision。
  - Events-only不執行indices/breadth；daily-only不執行cross-market/chips/fundamentals/source-health，除非明列hard dependency。
  - Source health在budget足夠時`problem_count>0`必有preview；小budget維持`RESPONSE_BUDGET_TOO_SMALL`與required capability保護。
- Negative acceptance：不得由MCP/Frontend重算status，不得拿output projection isolation冒充execution isolation，不得為preview破壞hard response budget。
- Validation：query plan、ask stages、tool boundaries、data quality、decision envelope、market context、dashboard、MCP parity與response-budget tests。

### M6 — Architecture、Runtime、Live與Product Freeze Gate

- Scope：全issue跨surface驗收、docs同步、runtime adoption與封版判定。
- Source gate：
  - Targeted suites全綠。
  - `scripts/check-architecture.py`與architecture tests全綠；不得增加undeclared debt。
  - Backend safe validation依Tier 3執行；若Frontend contract受影響，再執行lint、typecheck、build與focused browser contract。
- Runtime gate：
  - 只用existing launcher lifecycle restart/adopt named OMI component。
  - 驗證project root、interpreter、selected port、version、migration、loaded source、DB、health/ready、Frontend proxy與MCP。
- Live gate：
  1. 交易日14:00 future-of-release fixture/actual row不可流入completed daily。
  2. 15:15後無qualified refresh仍pending/missing-after-release。
  3. Qualified official refresh後today released，且session close reconciliation可觀測。
  4. Intraday scheduler實際bounded materialization、stale gate與owner cleanup可證明。
  5. Direct API、AI、MCP、Dashboard逐欄比較trade date、event time、provider/source、OHLCV/units、freshness、release、coverage與decision usability。
- Product gate：逐列更新issue traceability為passed/closed/deferred；P0/P1不得deferred。
- Rollback：
  - Source問題：回退本milestone的localized diff，保留additive schema與data。
  - Runtime問題：使用existing launcher回到上一個verified source；不reset DB、不broad kill。
  - Scheduler問題：停用named job/feature gate，read path與explicit repair維持可用；不刪已persisted canonical bars。
  - Contract compatibility問題：保留canonical truth，恢復compatibility projection，不恢復consumer-owned logic。

## Stop-and-fix rules

- 任一completed daily consumer仍能在pre-release讀到today row，停止M1後續工作。
- Clock boundary可使pre-release receipt自動升格時，M1不得標完成。
- Coverage／continuity仍能讓20→1標complete，停止M2。
- Technical insufficiency仍能輸出normalized score或decision usable，停止M3。
- Scheduler需要read-path fetch、無界targets或無明確transaction owner，停止M4並重做ownership設計。
- 同evidence跨surface status不一致，M5不得以compatibility warning結案。
- Architecture checker新增violation、public contract無migration window、DB migration無rollback或dirty worktree變更無法隔離時，暫停並更新Prompt/Progress。
- Runtime、external refresh、production migration、scheduler enable、commit、push或release未獲授權時，停在source acceptance，不擴張權限。

## Validation matrix

| Surface | Minimum proof |
| --- | --- |
| Daily release | pre-release row、post-clock/no-ingest、post-ingest三態 |
| Freshness | storage/released latest、future row、missing/partial/full coverage |
| Sequence | 20/19/13/1/0、duplicate、unordered、trading-day gaps |
| Technical | 1/10/20/60/120 bars、factor/timeframe不足、unit lineage |
| Aggregate | full coverage、50%、1/1973，不得sample冒充full market |
| Intraday | 20s/90s/5m/60m、scheduler hit/miss/backoff/idempotency |
| Planner | daily-only、events-only、ETF not-applicable、position context |
| Budget | normal preview、small budget fail-closed、required payload preserved |
| Parity | Backend API、AI、MCP、Dashboard逐欄一致 |
| Safety | cache-only zero IO、no consumer fallback、no raw max completed date |

## Review checkpoints

1. 計畫核准：允許M0–M5 source/tests/isolated migration work。
2. Migration gate：只有M1證明需要schema時另行確認production migration策略。
3. Scheduler policy gate：確認v1 target scope、hard cap與provider budget後才enable production scheduler。
4. Runtime gate：source acceptance完成後另行授權named OMI restart/adoption。
5. Release gate：live/product acceptance完成後才討論commit、push、release與active→completed歸檔。

## 決策紀錄

- 2026-08-28：新任務作為既有TW Data Core與EOD工作的corrective convergence，不覆寫前置任務。
- 2026-08-28：P0修復同時要求date clamp與release-qualified ingest；wall clock不是充分條件。
- 2026-08-28：沿用existing六軸CapabilityStatus，不建立第二套Common Quality Resolver model。
- 2026-08-28：P1-01保留current sample-only quality gate，只遷移completed trade-date owner。
- 2026-08-28：P2-01先視為source/backend已解決，M6只驗證installed/runtime schema adoption。
- 2026-08-28：P3-01保留hard response budget，修正為budget-aware preview acceptance。
