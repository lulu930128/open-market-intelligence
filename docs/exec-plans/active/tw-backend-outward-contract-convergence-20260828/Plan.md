# 台股 Backend Outward Contract 收斂計畫

## 執行原則

- 本計畫承接既有 Shared Data Core、Gateway、Resolver、Dataset Registry、`daily_ohlcv_platform`、TW market policy與`omi.decision.v4`，不建立平行核心。
- 每一個issue只有一個canonical owner與主要milestone；consumer regression可在後續milestone補驗證，但不得複製market logic。
- M0–M5保留為前一輪source implementation歷史；最新Backend Health Audit已推翻部分runtime/product完成假設，後續依序執行H0→H1→H2→H3→H4→H5→H6→H7→H8。
- 每個milestone先補會失敗的negative fixture，再做局部修改；測試沒有涵蓋真實bug時，不以既有green suite當完成證據。
- Source、Runtime、Live、Product gate分開更新`Progress.md`；不能用後一層證據回填前一層失敗。
- 不在read path觸發provider IO或DB mutation；normal acquisition只能由scheduler/job owner，repair只能由explicit bounded operation。
- MCP已納入本次closeout，但只負責thin transport、schema sync與runtime/session adoption；Backend仍是canonical envelope與所有市場語意的唯一owner。

## Closeout residual milestones

### R1 — Technical outward fail-closed

- Insufficient evidence時，中和`selected_summary`、`composite_state`、timeframe score/title/summary與directional score maps。
- Primary projection不得輸出raw `+7`；entry/risk action levels必須清空，只保留非方向性的measurement basis與不足reason。
- `technical.indicators` top-level與completed/current-partial observations都繼承`volume_unit=shares`與`source_capability=daily.ohlcv`。
- 驗證：technical gate、TW market projection、quality contract與decision envelope targeted tests。

### R2 — Coverage-aware official daily series reconciliation

- 在TW completed-daily candidate/resolution boundary依trade date整合相同exchange authority的official sources；同日由deterministic provider priority選擇，跨日保留各bar原始lineage。
- Request 20時，不得讓只有2根的高優先series壓掉另一official source的完整history。
- 真正storage缺口仍保持`insufficient_history`；不得以consumer fallback或無界backfill掩蓋。
- 驗證：RWD 2根 + OpenAPI長history、同日衝突、release-qualified filter與cache-only zero-I/O tests。

### R3 — Backend execution isolation

- Technical explicit selection建立`technical_only`reader profile，只允許identity、released daily、technical evidence與freshness hard dependencies。
- 前一輪R3只驗證Backend planner與direct AI request metadata；MCP shortcut／transport後續改由H6接手。

### R4 — Backend runtime/live closeout

- 驗證direct API、`/api/ai/ask`與Dashboard；MCP surface標記external parallel gate。
- Intraday只驗證scheduler owner/source health與下一交易日live adoption，不重抓、重建或修改production DB。

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
| P2-01 `quote.session_close` MCP parity | Backend registry已具能力；完成repo MCP與host adoption | H6 |
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
  7. Backend registry維持public truth；repo MCP enum、snapshot與installed adoption必須由H6依live registry同步並完成transport parity，不保留手工第二份capability truth。
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

## 2026-08-28 Backend Health Audit Reopen Milestones

以下milestones只處理最新稽核仍可重現或尚未完成live acceptance的項目。M0–M5的source成果保留為歷史checkpoint，但不得再用「完成」推導目前Runtime、Live或Product已通過。

### H0 — Reopen Baseline、Failure Fixtures與Scope Freeze

- Owner：本exec plan、相關backend/MCP contract tests；不修改production資料。
- Scope：
  1. 把quote capture `Decimal` failure、session-close status contradiction、index lineage missing、13:30 provisional/official mismatch、2330/ETF intraday miss、source-health zombie、nested projection null與MCP host unknown-tool建立可重現fixture。
  2. 對每個fixture記錄Dataset Contract、Runtime、Storage、Resolver、Projection與Consumer證據；unknown保持unknown。
  3. 將M0–M5標為歷史source checkpoint，M4/M5與M6的runtime/product結論重新開啟。
- Acceptance：每個P0/P1 residual在修改前至少有一個會失敗的targeted test或read-only probe；沒有fixture的項目不得直接以猜測改碼。
- Negative acceptance：不得用今天已錯過的slot／intraday資料偽造歷史成功；不得以clock advance回填未capture evidence。
- Validation：fixture-only pytest collection、read-only SQL、direct API/local MCP baseline；不做refresh、restart或DB mutation。

### H1 — Quote Capture Transaction與Session-close Truth

- Canonical owner：`backend/app/market/quote_contract_capture.py`、quote capture job/transaction、session-close resolver與quality projection。
- Implementation slices：
  1. `_json_default`明確支援`Decimal`與既有typed quantity/date值，輸出可逆且符合snapshot schema的JSON primitive；未知型別仍fail closed，不做通用`str(value)`吞錯。
  2. 把capture attempt與success payload persistence分層；serialization/provider/persistence任一失敗都留下bounded、redacted、durable failed row，並讓單一symbol失敗不阻斷同slot其他symbol。
  3. 對相同slot/symbol建立idempotency與duplicate retry行為；retry不能覆蓋已成功canonical snapshot。
  4. `quote.session_close`沒有eligible candidate時，availability/coverage/release/usability與payload一致為unavailable/partial-or-missing/not-released/unusable；不得由payload存在推成available。
  5. Session close與official close維持兩層finalization；13:33 session close不冒充15:15 official daily。
- Acceptance：Decimal fixture可persist/reread；forced serialization failure產生failed row；17 slots每一slot的captured/failed/missing總數可守恆；session-close match/mismatch/unavailable三態六軸一致。
- Live acceptance：下一交易日以既定17 slots capture代表TWSE/TPEX symbols；錯過的2026-08-28 slots保留不可重建限制。
- Validation：`test_taiwan_stock_quote_depth.py`、`test_tw_quote_volume_contract.py`、`test_source_health_contract.py`、`test_ai_capability_contract.py`、`test_ai_decision_envelope.py`。

### H2 — Index Official Lineage與Finalization Convergence

- Canonical owner：official index acquisition transaction、`backend/app/market/index_resolution.py`、current-index platform與dashboard/AI projection。
- Implementation slices：
  1. 新official index write必須持有`source_id/raw_result_id`或等價typed lineage；缺lineage既有row保持ineligible並揭露`INDEX_ROW_LINEAGE_MISSING`，不得由consumer放寬。
  2. 若需修復既有row，只能透過explicit bounded repair與原始receipt對帳；找不到receipt就保持partial，不手工補lineage。
  3. 移除「event time到13:30即official/finalized」heuristic；authority、official-close status、item finalization與reconciliation由canonical candidate/result決定。
  4. Index capture的舊`TAIWAN_TZ`failed rows保留歷史結果；source修正後以新job/live capture證明，不篡改舊row。
  5. Dashboard、market API、AI與MCP只投影同一`tw.index.resolution.v1`結果。
- Acceptance：缺lineage official row不被選中；provisional 46307.67/402.19不得覆蓋official 46331.45/402.83；同timestamp跨surface的provider/event_time/finalization/freshness/decision usability一致。
- Negative acceptance：不得把數值接近、13:30 timestamp或provider label當成official lineage。
- Validation：`test_taiwan_index_resolution.py`、`test_taiwan_index_contract_snapshot.py`、`test_tw_official_index_platform.py`、`test_tw_market_dashboard.py`、`test_ai_market_context_projection.py`。

### H3 — Intraday Materialization Coverage與ETF Current State

- Canonical owner：`backend/app/jobs/taiwan_intraday_bar_scheduler.py`、TW intraday platform/state與dataset/source health。
- Implementation slices：
  1. Scheduler target planner使用deterministic bounded union：explicit configured targets、holdings/watchlist、active leases/viewers；設定priority、dedupe、hard cap、per-run provider budget與skipped reasons。
  2. Configured list存在不得完全遮蔽其他Tier-A targets；超過cap時必須輸出eligible/selected/skipped counts與reason。
  3. Persistence維持idempotent、per-symbol failure isolation、session-aware bar semantics與cache-only read path。
  4. Health從table-wide row count升級為selected-universe coverage：eligible、selected、persisted-current、stale、missing、not-applicable與skipped。
  5. ETF watchlist使用instrument-aware applicability；沒有state就保持unknown/state_missing，不補0、不拿stock-only資料假裝available。
  6. Startup catch-up只處理可修復的current session/EOD materialization；powered-off期間無法重建的intraday gap保持missing。
- Acceptance：fixture同時包含2330、代表ETF與超過cap targets；priority與skipped reason deterministic；current state與persisted bars可區分；27 ETF watchlist不再被global current health掩蓋。
- Live acceptance：下一交易日證明job registration、owner PID、target inventory、provider calls、persisted bars、quota與failure isolation；至少2330及一檔watchlist ETF有明確結果。
- Negative acceptance：不得read-on-demand fetch、全市場2,000檔常駐抓取、用quote snapshot偽造1m bar或回填斷電期間intraday。
- Validation：`test_taiwan_intraday_bar_scheduler.py`、`test_tw_intraday_platform.py`、`test_tw_intraday_market_capabilities.py`、`test_tw_intraday_contract_acceptance.py`、`test_market_source_health.py`。

### H4 — Health Lifecycle、Status Axes與Bounded Projection完整性

- Canonical owner：dataset/source-health lifecycle、`backend/app/ai/data_quality_contract.py`、`backend/app/ai/capability_contract.py`與v4 projection。
- Implementation slices：
  1. Source-health snapshot加入scope identity/generation或等價supersession規則；舊`target=all` optional row不得永久保持active並污染current request readiness。
  2. Required operational、optional operational、dataset freshness與selected capability readiness維持分軸；aggregate不能由optional zombie升級或降級selected truth。
  3. Capability quality以payload內availability與canonical resolver證據決定，不再由「object存在」推available/complete/released。
  4. 修正bounded projection的nested depth行為：selected canonical fields要保值，真正裁切時必須記錄`projection.truncated`與trim metadata，不能靜默寫成null。
  5. Source-health normal budget保留top problem preview與nested detail；small budget仍fail closed並保護required capabilities。
- Acceptance：舊scope可superseded；quote session-close unavailable六軸一致；`missing_symbol_slots`經direct v4 projection與MCP仍保持array/object值或明示裁切；`projection.truncated=false`時不得出現depth-caused null。
- Negative acceptance：不得在MCP重建被Backend丟失的nested值；不得無界提高所有response depth/bytes。
- Validation：`test_source_health_contract.py`、`test_market_source_health.py`、`test_ai_capability_contract.py`、`test_ai_decision_envelope.py`、`test_omi_mcp_server.py`與response-budget regressions。

### H5 — Completed-session Coverage、Breadth與Corporate-action Residuals

- Scope：對已通過M1–M3的daily/technical主幹做剩餘truth補強，不重寫核心。
- Implementation slices：
  1. Full-market EOD health揭露完整instrument denominator與逐symbol分類：current、stale、missing、not-eligible、halted/suspended（只有authoritative status evidence時）、provider/lineage failure。
  2. Breadth unknown拆成not_received、received_unclassified與其他有證據reason；preview可抽樣，但aggregate總數必須守恆。
  3. Corporate-action evidence新增`checked_through_date`、source scope與absence semantics；沒有event row只能在已證明檢查範圍內表示none-observed。
  4. 重新驗證technical analysis date與corporate-action coverage；coverage只到8/24時，8/28 analysis不得宣告完整adjustment evidence。
- Acceptance：1973 universe分類總數守恆；1-row/sample仍不得full-market ready；breadth unknown reason總和一致；corporate-action absence有checked-through evidence。
- Negative acceptance：Unknown不等於0、無事件不等於已檢查、停牌不得由缺quote自行推斷。
- Validation：`test_eod_coverage.py`、`test_eod_coverage_scheduler.py`、`test_tw_market_breadth_session_contract.py`、`test_tw_official_breadth_platform.py`、`test_tw_corporate_events.py`、`test_technical_evidence.py`。

### H6 — MCP Public Surface、Runtime Registration與Transport Parity

- Canonical owner：Backend `/api/ai/tools`與`omi.decision.v4`；repo MCP只擁有thin transport，OMI_search lifecycle/host registration只擁有連線與tool discovery。
- Implementation slices：
  1. Repo MCP `tools/list`從Backend live schema取得public contract，離線fallback snapshot只做版本相容且有digest/adoption測試。
  2. Public surface固定驗證`omi.ask`、`omi.ask_stream`、`omi.read_refresh_status`三工具；舊internal tools不得再次掛載為public surface。
  3. 分開驗證local stdio server、OMI_search adapter/tunnel與Codex host session/schema cache；`Unknown tool`先修registration/name mapping或重新adopt，不改Backend business logic。
  4. `omi.ask`成功、structured business rejection、response budget與refresh-status均保留MCP transport semantics。
  5. Direct HTTP與MCP canonical envelope做deep equality；只允許明列transport metadata差異，不允許nested source-health、status或capability內容分叉。
- Acceptance：三層`tools/list`一致；host可用精確名稱`omi.ask`呼叫；`quote.session_close`可select；direct/MCP payload parity通過；business rejection為`isError=false`。
- Negative acceptance：不得為host舊cache新增永久alias/internal tool，不得在adapter補status/freshness/fallback，不得把local adapter ready當host adopted。
- Validation：`test_mcp_schema_contract.py`、`test_omi_mcp_server.py`、local stdio protocol smoke、OMI_search `/health`/`upstream-health`/tunnel readiness與Codex host實際call。

### H7 — TW Typed Lineage/Public Claim Debt Triage

- Scope：`tw.etf.profile/nav/pcf/inav`、futures quote/intraday/daily、options/large-trader/term-structure等已識別typed lineage缺口。
- Implementation slices：
  1. 從executable registry與current source建立public/required/shadow/internal矩陣，不在Markdown複製永久inventory。
  2. Public或required capability若對外宣稱ready，必須接canonical observation、transaction/raw lineage、health與resolver；無法在本次安全完成者改為truthful partial/unavailable並建立declared architecture debt與owner。
  3. Shadow/internal能力可延期，但不得被AI/MCP selection或source-health aggregate誤認為production-ready。
  4. 只做必要的localized lineage closure；不藉機擴成TW derivatives全平台重寫。
- Acceptance：每個gap有source owner、public claim、lineage、health、resolver與disposition；沒有「public ready但無typed lineage」。
- Negative acceptance：不得用docs聲明取代executable registry，不得將unknown lineage標official。
- Validation：registry/schema contract、architecture checker/tests、capability parity與代表ETF/futures/options fixture。

### H8 — Source、Runtime、Live與Product Freeze

- Source gate：H1–H7 targeted suites全綠；`scripts/check-architecture.py`與architecture tests不增加undeclared debt；執行`run-safe-validation.ps1 -Profile backend`，既有ACL/固定count問題需隔離並留下證據，不能靜默忽略。
- Runtime gate：
  1. 只用既有named lifecycle分別adopt OMI Backend與OMI_search；驗證project root、interpreter、selected port、source identity/digest、migration、DB、health/ready與job inventory。
  2. Backend ready、OMI_search adapter/tunnel ready與Codex host session adopted為三個獨立結果。
- Live gate：
  1. 下一交易日完成fixed-slot quote capture、session-close/official-close reconciliation與index capture。
  2. 完成pre-release、post-release/no-qualified-ingest、post-qualified-ingest三態daily acceptance。
  3. Intraday scheduler證明selected-universe target、provider budget、persisted bars、ETF state與stale gate。
  4. Direct market API、`/api/ai/ask`、repo MCP/OMI_search、Codex host與Dashboard逐欄比對。
- Product gate：P0/P1不得deferred；P2/P3需passed、truthful partial或有owner/sunset的declared debt。任何public surface仍互相矛盾、host unknown-tool、quote capture無結果或index official lineage缺失時，`Product acceptance=not_ready`。
- Docs gate：只有完成實際contract/owner變更後才更新`docs/architecture/*`與`CurrentImplementationState.md`；task folder在Product gate通過後才移到`completed/`。
- Release gate：commit、push、release與production migration仍需使用者明確授權。

## Stop-and-fix rules

- 任一completed daily consumer仍能在pre-release讀到today row，停止M1後續工作。
- Clock boundary可使pre-release receipt自動升格時，M1不得標完成。
- Coverage／continuity仍能讓20→1標complete，停止M2。
- Technical insufficiency仍能輸出normalized score或decision usable，停止M3。
- Scheduler需要read-path fetch、無界targets或無明確transaction owner，停止M4並重做ownership設計。
- 同evidence跨surface status不一致，M5不得以compatibility warning結案。
- Quote capture仍因serialization在persistence前失敗，H1不得進入live slot acceptance。
- Official index沒有typed lineage或仍由13:30時間heuristic升格，H2不得標完成。
- Intraday health只能提供table-wide row count、無selected-universe denominator時，H3不得標coverage complete。
- `projection.truncated=false`但selected nested value變null時，H4不得交給MCP workaround。
- Local MCP可用但OMI_search／Codex host仍`Unknown tool`時，H6只能標partial，不得宣告transport adopted。
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
| Quote capture | Decimal/quantity serialization、failed row、17-slot守恆、session-close三態 |
| Index | official lineage missing、provisional/official mismatch、跨surface canonical result |
| Intraday coverage | configured/watchlist/holdings/lease union、cap、skipped reasons、ETF state |
| Health projection | scope supersession、六軸一致、nested值保留或明示裁切 |
| MCP adoption | local stdio、adapter/tunnel、host tools/list/call、direct deep equality |
| Lineage debt | public/required claim不得無typed lineage或假裝ready |

## Review checkpoints

1. Reopen計畫核准：允許H0–H7的TW Backend、repo MCP、tests與isolated migration work。
2. Migration gate：只有fixture證明現有schema不足時另行確認production migration策略；source code可先做isolated migration test。
3. Scheduler policy gate：確認target priority、hard cap、provider budget與health denominator後才enable production scheduler。
4. Runtime gate：source acceptance完成後另行授權named Backend與OMI_search lifecycle adoption。
5. Live gate：下一交易日的quote/index/intraday證據不可由mock或較晚時段回填。
6. Release gate：live/product acceptance完成後才討論commit、push、release與active→completed歸檔。

## 決策紀錄

- 2026-08-28：新任務作為既有TW Data Core與EOD工作的corrective convergence，不覆寫前置任務。
- 2026-08-28：P0修復同時要求date clamp與release-qualified ingest；wall clock不是充分條件。
- 2026-08-28：沿用existing六軸CapabilityStatus，不建立第二套Common Quality Resolver model。
- 2026-08-28：P1-01保留current sample-only quality gate，只遷移completed trade-date owner。
- 2026-08-28：P2-01先視為source/backend已解決，M6只驗證installed/runtime schema adoption。
- 2026-08-28：P3-01保留hard response budget，修正為budget-aware preview acceptance。
- 2026-08-28：最新Backend Health Audit推翻部分M4/M5 runtime/product完成假設；保留歷史source結果並新增H0–H8重新收口。
- 2026-08-28：MCP平行工作已結束，repo MCP與runtime/session adoption正式納入；Backend canonical truth與thin-adapter邊界不變。
- 2026-08-28：先修Backend nested projection與status contradiction，再做MCP parity；禁止adapter重建遺失語意。
- 2026-08-28：使用者授權consumer convergence實作；新增H9–H15，target owner固定為既有Taiwan market repositories + MarketDataGateway/Resolver，不建立第二套Resolver。
- 2026-08-28：Guard v2先以deterministic AST/lexical rules凍結protected raw models與consumer-owned source priority，再逐consumer移除exact debt；不得用broad allowlist吸收新違規。
- 2026-08-28：completed daily universe使用單次bounded batch candidate query與deterministic per-instrument resolution，禁止全市場N+1 Gateway call。
- 2026-08-28：Radar automation/backtest的due-date與history coverage也屬research consumer；統一讀`tw_daily_freshness`，並以receipt available-at gate防止point-in-time look-ahead。
- 2026-08-28：public index chart/contribution與stock market-cap讀取納入H12；index acquisition/persistence、StockMaster bootstrap與EOD diagnostic仍是storage owner，不誤列為consumer旁支。

## Consumer convergence milestones (H9–H15)

### H9 — Freeze and contract

- Scope：architecture guard、exact debt、regression fixtures、exec-plan baseline。
- Acceptance：新增production consumer存取protected Taiwan storage或`SourceRegistry.priority`必須失敗；current occurrences只能是exact debt。
- Validation：`python scripts/check-architecture.py`與architecture tests。

### H10 — Canonical Taiwan read ports

- Scope：completed daily close/series/universe、resolved current-or-completed price、official index reference/series。
- Acceptance：輸出保留selected lineage、release/finalization、health、limitations與units；read path不做provider IO或commit。
- Validation：daily repository/platform與official-index targeted tests。

### H11 — Outward truth fixes

- Scope：index selected-candidate field bundle、TW trade-date propagation、requested/effective limitation、ETF applicability precedence、daily units。
- Acceptance：同一`resolution_id`欄位一致；historical request不洩漏較晚日期；future request limitation可見。
- Validation：AI projection、capability quality與official daily tests。

### H12 — Primary daily/current consumer cutover

- Scope：market overview、valuation、next-session、ADR、legacy `/daily/*`、dashboard completed-index baseline、public index chart/contribution與stock market cap。
- Acceptance：不保留raw provider winner logic；universe row唯一；public compatibility mirror canonical selection。
- Validation：aggregate、valuation、next-session、ADR與API contract tests。

### H13 — Secondary research consumer cutover

- Scope：volume pace、Radar outcome/automation/backtest、market chips、technical RS、derivatives。
- Acceptance：daily/intraday/index research input帶canonical lineage；selected evidence unavailable時fail closed。
- Validation：technical、Radar、chips與derivatives targeted tests。

### H14 — Legacy removal and debt closure

- Scope：移除舊selection helper/import與對應exact debt，只保留repository/transaction/diagnostic owner。
- Acceptance：protected consumer occurrence歸零，除非是獨立且精確登錄的debt。
- Validation：architecture guard與negative tests。

### H15 — Source closeout

- Scope：targeted regression matrix、compile、safe backend validation、Progress更新。
- Acceptance：明確完成Source acceptance；Runtime/Live/Product維持待named adoption與正式交易時段證據。

## 2026-08-29 Final cleanup milestones

### F1 — Historical technical observation boundary

- 在`technical_indicator_gateway`、`technical_report`與`technical_evidence`既有public read seam加入optional `to_date`，由AI stock context傳入explicit `trade_date`。
- Daily、weekly、monthly、TAIEX relative-strength benchmark與corporate-action analysis window使用相同cutoff；historical request禁止current-session partial/today report。
- 未指定`trade_date`時維持現行current-session behavior與public route compatibility。
- Acceptance：同一request的chart、technical reports、advanced evidence與corporate-action relevant end均`<= trade_date`。

### F2 — Canonical stock aggregate snapshot

- 擴充`TaiwanOfficialDailyUniverseRead`回傳TWSE/TPEX universe與selected counts；新增market service snapshot projection，一次repository read同時提供rows與coverage metadata。
- AI market overview使用`include_etf=false` snapshot；industry metadata仍可讀`StockMaster`，但不得再用第二次query建立coverage truth。
- Compatibility `/api/market/daily`仍可包含ETF，不改public既有scope。
- Acceptance：stock+ETF fixture中sector/ranking只有stock；sample、covered、universe與by-market counts守恆，`OTHER=0`。

### F3 — Outward coverage parity與source closeout

- 修正sector `covered_stock_count`欄位映射；`market.sample_ranking`新增additive `coverage_status=sample_only`並由quality resolver fail closed。
- 重新產生Backend-owned repo MCP offline snapshot；adapter不新增任何business logic。
- 跑technical、daily repository、market aggregate、capability/v4、MCP schema、architecture guard與compile regression；更新Progress但不宣告Runtime/Live/Product adopted。

### F4 — Precommit outward-contract polish

- 在Backend `selection.fields` normalization建立capability-owned semantic companion mapping；`daily.ohlcv.points`會補入`volume_unit`、`trade_value_unit`與`currency`。
- Projection與manifest繼續直接消費同一份effective selection；quality resolver不新增例外或fallback。
- Sector capability保留canonical stock snapshot scope，partial coverage warning使用ordinary active-stock denominator語意；compatibility missing keys與sample-only gate不變。
- 驗證effective field順序、explicit companion去重、default selection不變、unsupported field拒絕、v4 payload／manifest／quality一致，以及TW market context與MCP schema parity。
- Source acceptance可標`passed`；未經named runtime adoption與live evidence前，不更新Runtime／Live／Product或將active plan歸檔。
