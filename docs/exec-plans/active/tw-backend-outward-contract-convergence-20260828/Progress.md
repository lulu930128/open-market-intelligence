# 台股 Backend Outward Contract 收斂進度

## 狀態

- 任務狀態：`consumer_convergence_source_implemented_runtime_adoption_pending`
- Source acceptance：`passed_consumer_convergence_targeted_with_known_full_suite_baseline_failures`
- Runtime acceptance：`backend_running_pre_consumer_source_mcp_not_reverified`
- Live acceptance：`failed_current_session_and_pending_next_session`
- Product acceptance：`not_ready`
- 最後更新：`2026-08-28 Asia/Taipei`
- Source baseline：`4936d4631bef18bb5ec26c1f50799e91a2a8b3be`

## 授權與邊界

- 使用者已授權H0–H7 source實作；本輪已修改Backend、repo MCP contract tests與exec-plan progress，但未修改production DB、未執行provider refresh、未restart runtime、未commit或push。
- Source授權不自動擴張為production migration、scheduler enable、runtime restart、external refresh、commit、push或release授權。
- MCP平行工作已結束，後續H6納入repo MCP、OMI_search lifecycle與Codex host adoption；adapter仍不得重建Backend market semantics。
- Worktree已有大量TW／US／architecture／MCP平行變更；後續只修改H0–H7明列owner，不reset、clean、revert或覆寫無關變更。

## 歷史 Source Checkpoint（保留但已重新開啟）

- M0–M3的daily release、coverage/continuity與technical fail-closed targeted source tests曾通過，仍是可重用基礎。
- M4曾加入`TAIWAN_TZ` source修正、intraday stale gate與bounded scheduler owner；M5曾加入planner/applicability/index/breadth/source-health與MCP registry snapshot修正。
- 歷史targeted evidence包括：technical `57 passed`、official daily `52 passed`、planner `95 passed`、scheduler/health/index/dashboard `104 passed`、daily/AI integration `335 passed`、補充回歸`75 passed`、architecture tests `17 passed`與compileall PASS。
- 這些結果只證明當時selected source paths；最新runtime/storage/consumer audit發現production-shaped gaps，因此M4、M5與M6不得繼續標為current complete。
- Full backend suite仍有既有pytest temp ACL問題，以及`test_database_model_contract.py`固定foreign-key count 102與dirty worktree metadata 114不一致；先前停止點為`734 passed / 1 failed / 377 subtests passed`，不能宣稱full suite green。

## 2026-08-28 H0–H7 Source實作結果

### H1 — Quote capture與session close

- Snapshot serializer已明確支援`Decimal`、date/time、Enum與Pydantic model；未知型別仍fail closed，不使用通用`str()`掩蓋schema錯誤。
- Serialization失敗會留下durable failed capture row；相同slot/symbol retry不覆蓋已成功snapshot，單一symbol例外也不阻斷同slot其他symbol。
- `quote.session_close available=false`會同步收斂availability/coverage/release/usability與facts/decision axes，不再因payload object存在而標complete/released。
- Source acceptance：`passed`；下一交易日17 fixed slots與session-close三態仍為Live pending。

### H2 — Index official lineage與finalization

- 13:30 point與13:33/13:34 clock不再是official confirmation evidence；只有explicit official status/canonical official daily result可升格。
- 缺`source_id/raw_result_id`的legacy row仍保持ineligible；scheduler-owned reconciliation只針對TAIEX/TPEX做bounded official refresh與postcondition reread，不由consumer放寬lineage。
- 舊的「post-close deadline controls confirmation」regression已改成clock-only仍pending。
- Source acceptance：`passed`；既有production legacy rows的實際repair與跨surface live parity仍pending。

### H3 — Intraday target與coverage

- 新增`tw.intraday.universe.v1` read-only planner，共用configured、active TW holdings、viewer leases與active watchlist，固定priority/dedupe、active StockMaster validation、hard cap及skipped reasons。
- Configured target不再遮蔽其他Tier-A來源；ETF是合法intraday target，缺bar/state時保持missing/unknown。
- Scheduler與global source health共用同一selected universe；health逐target揭露current/stale/pending/missing與coverage ratio，不再使用table-wide最新row冒充selected coverage。
- Source acceptance：`passed`；production job enable、provider budget與下一交易日2330/ETF materialization仍為Runtime/Live pending。

### H4 — Health lifecycle與projection

- 新bounded universe generation會supersede舊`target=all` health snapshot；stock-specific incidental request不會取代canonical bounded scope。
- Session-close unavailable quality已fail closed；normal source-health budget保留problem preview。
- Bounded projection不再於depth 6靜默輸出null；正常nested evidence完整保值，極端depth 64才回explicit truncation marker。
- Source acceptance：`passed`；MCP runtime deep parity仍依H6 host adoption待驗。

### H5 — Completed-session residuals

- EOD detail新增active cash-market instrument inventory、eligible ordinary-stock denominator、not-eligible instruments、逐symbol classification/reason、classification counts與守恆assertion。
- Halt/suspension沒有authoritative status evidence時保持0，絕不從missing row推斷；same-day no-close仍為partial。
- Breadth既有`received_unclassified_count`與`not_received_count`canonical projection及守恆tests確認通過。
- Corporate-action technical contract新增`checked_through_date`、provider/coverage source scope與bounded absence semantics；analysis超過coverage end時維持partial。
- Source acceptance：`passed`；1973 production universe實際數字仍需runtime reread確認。

### H6 — Repo MCP source

- Repo MCP保持thin：live`tools/list`取Backend`/api/ai/tools`，offline snapshot以digest驗證，public tools固定`omi.ask`、`omi.ask_stream`、`omi.read_refresh_status`。
- `quote.session_close`已在Backend registry與offline snapshot；`omi.ask`原樣保留canonical v4，structured business rejection維持`isError=false`。
- Repo source acceptance：`passed`；OMI_search adapter/tunnel與Codex host session仍未restart/re-adopt，Runtime acceptance維持partial。

### H7 — Typed lineage claim triage

- Executable TW dataset catalog現在禁止`LINEAGE_GAP` dataset標`advertised=true`；ETF、futures、options/large-trader/term-structure等已知debt仍可透過catalog/health稽核，但不再宣稱production-ready。
- Platform-owned與compatibility dataset維持原有lineage/convergence分類；未擴張成derivatives平台重寫。
- Source acceptance：`passed_truthful_debt`；typed raw-receipt migration仍是後續獨立工作。

## 本輪驗證證據

- H1–H7 targeted matrix：`445 passed / 58 subtests passed`。
- H2 stale deadline regression修正後單測：`1 passed`。
- Architecture checker：`PASS`，`26 actual violations / 26 declared debt`，未增加undeclared violation。
- Architecture pytest：`passed`；Backend app compileall：`passed`。
- `git diff --check`（本輪owner files）：PASS，只有既有LF→CRLF提示。
- Backend safe-validation全套在collection被既有不可讀`backend/tests/tmpla6tzx59`阻斷；精確排除後確認下列非本輪baseline failures：
  - `test_database_model_contract.py`固定期待`131 tables / 102 foreign keys`，current metadata為`137 / 114`。
  - `test_kgi_superpy_quote.py`的market stream producer缺新schema required fields，屬其他dirty工作線。
  - `test_market_data_v2_dark_boundary.py`freeze checkpoint有41個hash mismatches，符合目前dirty worktree狀態。
  - pytest temporary directories仍可能於session cleanup觸發WinError 5；未刪除或改ACL。
- 本輪未做HTTP/provider call、production DB mutation、runtime restart、scheduler enable、host schema refresh、commit或push。

## 最新稽核確認問題

### H1 — Quote capture與session close：未完成

- 17個fixed-slot jobs均有執行，但在snapshot persistence前因`Decimal` serialization TypeError失敗。
- Failure path沒有留下failed capture row，health顯示`captured=0 / failed=0 / missing=17`，無法稽核實際attempt結果。
- `quote.session_close`無eligible candidate；同一capability仍出現payload unavailable與quality available/complete/released的矛盾。
- 2026-08-28已錯過slots不可偽造回填；source修復後需下一交易日live acceptance。

### H2 — Index lineage與finalization：未完成

- TAIEX/TPEX official daily values存在，但`source_id/raw_result_id`為null，canonical reader以`INDEX_ROW_LINEAGE_MISSING`拒絕。
- 既有10筆index contract capture保留`TAIWAN_TZ`失敗；current source/direct endpoint不再NameError不等於歷史capture成功。
- 13:30 provisional points仍可能由時間heuristic標official/finalized，且與正式close數值不同；cross-surface canonical parity未通過。

### H3 — Intraday materialization與ETF state：未完成

- Scheduler source owner存在，Backend runtime也曾採用較新source，但configured target可能遮蔽watchlist/holdings/lease union。
- 2330 persisted intraday bars與lineage為missing；27檔ETF watchlist current state均為unknown/state_missing/unavailable。
- Global intraday health雖有大量current rows，沒有selected-universe denominator，不能證明2330或ETF coverage。

### H4 — Health lifecycle與projection：未完成

- 舊`target=all` quote health snapshot仍可能被視為active lifecycle；required operational count已分離，但optional zombie仍可污染aggregate freshness/readiness。
- Persisted source-health JSON與direct builder的`missing_symbol_slots`正確，經v4 bounded projection後nested值可變null，且`projection.truncated=false`。
- 此為Backend projection bug；MCP不得自行補回。

### H5 — Completed-session residuals：未完成

- Full-market EOD約`1944 current / 27 stale / 2 missing`（1973 universe），仍缺逐instrument eligibility/status/reason證據。
- Breadth仍有TWSE/TPEX unknown rows，需要not_received與received_unclassified等reason守恆。
- Technical corporate-action evidence缺`checked_through_date`與absence semantics；coverage終點早於analysis date時不能宣稱完整。

### H6 — MCP public transport adoption：未完成

- Repo local stdio adapter的`tools/list`為三個public tools，且Backend registry包含`quote.session_close`。
- Codex host仍顯示舊internal tools，呼叫`omi.ask`得到`Unknown tool`；host session/schema adoption未完成。
- Direct Backend nested projection尚有null bug，因此目前不能宣稱direct/MCP deep parity。

### H7 — Typed lineage debt：待分類

- TW ETF profile/nav/pcf/inav、futures與options相關能力存在typed lineage缺口。
- 尚未完成public/required/shadow矩陣；在分類前不得把這些能力一律視為production-ready，也不應直接擴成全平台重構。

## Reopen Milestone 狀態

| Milestone | 狀態 | 完成門檻摘要 |
| --- | --- | --- |
| H0 baseline/fixtures | `source_passed` | production-shaped fixtures與owner baseline完成 |
| H1 quote/session close | `source_passed_live_pending` | Decimal/failed-row/quality已通過；17-slot live待下一交易日 |
| H2 index truth | `source_passed_runtime_repair_pending` | 去time heuristic與bounded reconciliation完成；production lineage repair待授權 |
| H3 intraday coverage | `source_passed_live_pending` | bounded union/per-target health完成；2330/ETF live結果待下一交易日 |
| H4 health/projection | `source_passed_mcp_runtime_pending` | scope supersession、六軸與nested projection完成 |
| H5 completed residuals | `source_passed_runtime_recheck_pending` | denominator/reason守恆與checked-through完成 |
| H6 MCP adoption | `repo_source_passed_host_pending` | 三public tools/local schema通過；adapter/host adoption未執行 |
| H7 lineage debt | `truthful_debt_classified` | lineage-gap datasets已fail closed為not advertised |
| H8 freeze | `blocked_by_runtime_live_product_gates` | Source完成；Runtime、Live、Product仍需另行授權與證據 |

## 計畫文件本輪驗證

- 已讀取productized task-doc template、OMI freshness probe matrix與AI consumer contract map。
- 已對齊`docs/architecture/index.md`、`OmiDecisionContract.md`、Backend/MCP scoped `AGENTS.md`。
- 三份文件UTF-8讀回正常、標題與結尾換行存在，未發現replacement character。
- H1–H6明列的19個targeted test files均存在。
- `git diff --check -- <Prompt.md> <Plan.md> <Progress.md>`：PASS；只有既有LF→CRLF工作樹提示。
- 舊的「本輪排除MCP／平行MCP處理」文字已移除，H6成為正式milestone。
- 尚未執行source tests、runtime probe、MCP restart或provider call；本輪只做文件Tier 0驗證。

## 已決策

- 不另開競爭性plan；直接在原`tw-backend-outward-contract-convergence-20260828`重新開案。
- 修復順序為quote → index → intraday → health/projection → completed-session residuals → MCP adoption → typed lineage debt → freeze。
- Local adapter ready、OMI_search adapter/tunnel ready與Codex host session adopted是三個獨立acceptance。
- 已錯過的fixed slot與intraday gap不做假資料回填；completed-session EOD只有在原始receipt/lineage可證明時才可bounded repair。
- H6只修transport/schema/adoption；Backend nested projection與status contradiction必須在H1/H4修復。

## Known risks

- Dirty worktree跨TW、US、architecture與MCP，後續每一milestone都需先取精確diff並避免覆寫他人修改。
- 下一交易日live gate受市場時間與provider availability限制；source green後仍可能停在Live pending。
- Quote/index既有失敗rows可能只能保留歷史失敗，不能補成成功。
- Production migration、scheduler policy／enable、runtime restart與external refresh尚未授權。

## 下一步

1. 使用者複檢本輪source diff與targeted evidence。
2. 取得授權後，以既有named lifecycle分別adopt Backend與OMI_search；不以Backend ready推定Codex host已adopt。
3. 下一交易日執行17-slot quote/index capture、intraday 2330/ETF與official daily三態live acceptance。
4. Live gate通過後才更新H8 Product acceptance、討論commit/push/release與active plan歸檔。

## 2026-08-28 Consumer convergence reopen

- 使用者已授權H9–H15 source實作，目標是移除台股production consumer對raw canonical storage與consumer-owned provider selection的旁路。
- 唯讀baseline已直接重現TPEX mixed candidate、future requested/effective limitation遺失、3711同日多provider aggregate重複，以及ADR早盤raw quote優先於official close。
- Current target owner是既有`TaiwanOfficialDailyBarRepository`、official/current index repositories、`MarketDataGateway`與Resolver；不建立第二套Resolver。
- 本階段不執行provider IO、production DB mutation、schema migration、runtime restart、commit或push。

## 2026-08-28 H9–H15 Consumer convergence實作結果

### Canonical owner與Guard

- Architecture Guard新增`python_forbidden_import_names`，可在允許repository owner讀storage的同時，精確禁止outward/research consumer import `MarketDailyPrice`、`MarketIndexDailyStat`、`TaiwanStockQuoteSnapshot`與Radar raw intraday model。
- `tw_consumer_canonical_storage_access`已涵蓋AI、market service、valuation、next-session、ADR、technical、chips、derivatives、volume pace、official breadth、dashboard及Radar outcome/automation/backtest production paths。
- Checker維持`26 actual violations / 26 declared debt`；本輪沒有新增broad allowlist或undeclared debt。

### Completed daily與breadth

- `TaiwanOfficialDailyBarRepository`現在提供release-qualified exact series與bounded universe；同symbol多provider candidate做deterministic reconciliation，並輸出examined/rejected/duplicate limitations。
- Daily platform統一requested/effective date clamp與canonical row projection；service caller保留原始requested date，future boundary limitation不再被consumer提前吞掉。
- Official breadth不再自己限定TWSE OpenAPI並掃raw rows，改從canonical daily universe聚合；因此RWD/OpenAPI不再形成互斥consumer truth。多receipt component仍fail closed，不犧牲lineage coherence。
- Local read-only DB在模擬2026-08-28 14:18時，3711最新completed daily停在2026-08-27，並帶`REQUESTED_TO_DATE_EXCEEDS_LATEST_RELEASED_DAILY_DATE`；8/27 universe為1940個unique selected instruments，duplicate candidates已reconciled。

### Index、AI與secondary consumers

- Official index exact與series加入future-date clamp、receipt release/available-at gate及bounded preload；series只做一次SELECT，但每一session仍經`MarketDataGateway`／Resolver。
- `market.indices`的value/change/date/source改由同一selected observation輸出；`TAIWAN_TZ`統一使用trading-calendar owner。
- Explicit TW `trade_date`當時已穿透market overview、daily與stock context entry point；2026-08-29稽核確認technical report／advanced evidence尚未收到cutoff，此項在F1重新開案，不能沿用原完成宣告。ETF `not_applicable`不再被semantic missing/blocked覆寫。
- Valuation、next-session、ADR、volume pace、technical benchmark、market chips、derivatives、Radar outcome/v2/shadow與legacy daily routes均不再自行選raw provider。
- Radar due/not-due改讀`tw_daily_freshness.latest_date`，不再以raw MAX或純日曆expected date代表canonical materialization；Radar backtest coverage使用distinct released sessions與receipt available-at cutoff，避免多provider重複及look-ahead。
- Public index chart改讀official index series，index contribution改由venue freshness + canonical daily universe提供unique component bars；dashboard previous-session baseline與stock market-cap也不再直接取raw latest row。
- Daily/chart與technical projection保留shares/TWD unit lineage；public OHLC response schema加入`trade_value_unit`與`currency`。

### Validation

- Primary consumer matrix：`254 passed / 8 subtests passed`。
- Extended cutover matrix（cross-market、financial、index snapshot、technical report、ETF、Radar、cold read）：`110 passed / 5 subtests passed`。
- Official daily/index/breadth cold-read group：`19 passed`；index/technical/derivatives：`47 passed / 8 subtests`；stock volume pace：`3 passed`。
- Architecture tests：`18 passed`；checker：PASS，`26 actual / 26 declared`；Backend compileall與targeted `git diff --check`：PASS。
- 最終跨模組consumer regression（daily/freshness、AI、valuation、ADR、next-session、technical、derivatives、aggregate、Radar、dashboard、index/breadth與market-cap）：`397 passed / 29 subtests passed`。
- 完整Backend suite在final fixture收斂前取得`2428 passed / 31 failed / 1 error / 476 subtests`。本輪相關21個failure其後已由110-test extended matrix逐項轉綠；未重跑5分38秒全套，剩餘已知baseline為database固定table/FK count、KGI producer缺required schema fields、dark checkpoint hash、US旁線、runtime launcher temp ACL。
- Windows pytest cleanup仍會因既有temp ACL出現WinError 5；為取得一次完整摘要，只在單次test process內停用pytest dead-symlink cleanup hook，未修改ACL、未刪除既有temp目錄。

### Runtime read-only probe

- `http://127.0.0.1:8400/api/system/health`=`ok`、`readyz`=`ready`，project root與interpreter均指向本repo／`.venv`。
- Current post-close OHLC read為2026-08-28、20/20；v4 explicit data-only selection也正確限制required capability，20/20 coverage為complete且technical未執行。
- Running v4仍未輸出本輪新增的`trade_value_unit`，quality因此保留`volume_unit_missing`；這是明確的source-not-adopted runtime evidence，不以source tests掩蓋。
- 本輪沒有restart Backend/OMI_search、沒有provider IO、DB mutation、scheduler enable、commit或push。Runtime、MCP host、Live與Product acceptance仍pending。

## H9–H15狀態

| Milestone | 狀態 | 證據／限制 |
| --- | --- | --- |
| H9 Freeze and contract | `source_passed` | Guard v2與negative architecture tests通過 |
| H10 Canonical read ports | `source_passed` | daily/index exact/series/universe、bounded preload與release gate通過 |
| H11 Outward truth fixes | `source_passed_runtime_pending` | source projection/tests通過；running runtime尚未adopt unit欄位 |
| H12 Primary cutover | `source_passed` | aggregate、valuation、next-session、ADR與legacy routes targeted green |
| H13 Secondary cutover | `source_passed` | volume/Radar/chips/technical/derivatives targeted green |
| H14 Legacy removal | `source_passed_with_declared_repo_debt` | protected consumer imports歸零；repo仍有26筆非本輪exact debt |
| H15 Source closeout | `source_passed_runtime_pending` | targeted/architecture/compile/diff完成；full suite仍有隔離baseline |

## 下一步（更新）

1. 使用者複檢H9–H15 source diff與architecture boundary。
2. 另行授權後以既有named lifecycle採用Backend source，再重跑OHLC/v4 unit、trade-date、index/breadth與MCP deep parity。
3. OMI_search adapter/tunnel與Codex host schema分別adopt；Backend ready不得代替MCP host accepted。
4. 下一交易日保留H1–H8既有quote/index/intraday/live gates；通過前不歸檔active plan、不commit/push/release。

## 2026-08-29 Final cleanup source結果

### F1 — Historical technical observation boundary

- `calculate_active_latest_daily_indicator()`、technical report daily／weekly／monthly與advanced technical evidence現在共用optional `to_date`。
- Explicit Taiwan `trade_date`由technical-only與full stock context傳入report、official daily series與TAIEX benchmark；historical request不再建立today/current-partial observation。
- Corporate-action acquisition coverage仍保留自身`checked_through_date`；只有`relevant_analysis_end`依實際technical observation cutoff收斂，沒有把較新的coverage evidence偽造成缺失。
- Regression以2026-02-20 cutoff驗證daily／weekly／monthly、relative-strength stock/benchmark latest date與corporate-action relevant end均不晚於cutoff。

### F2 — Canonical stock aggregate snapshot

- `TaiwanOfficialDailyUniverseRead`新增TWSE／TPEX universe與selected counts；market service以一次repository read投影`TaiwanMarketDailySnapshot`，rows與coverage denominator不再分別取得。
- AI market overview改讀`include_etf=false` snapshot；ETF仍保留於既有public daily compatibility read，但不再進stock sector／ranking sample。
- `_daily_sample_coverage()`只接受snapshot metadata，不再query第二份`StockMaster` universe；industry名稱查詢只做selected stock metadata enrichment，不擁有coverage truth。
- Stock＋ETF fixture驗證stock-only與compatibility scope分離、TWSE／TPEX counts守恆且aggregate `OTHER=0`。

### F3 — Coverage、MCP schema與驗證

- Sector `covered_stock_count`改讀`covered_universe_count`。
- `market.sample_ranking`新增additive `coverage_status=sample_only`，capability allowlist與quality resolver同步；`is_full_market=false`不得被generic payload truthiness升級為complete或decision usable。
- Repo MCP offline snapshot由Backend registry generator重建，digest=`4c93b90b60493439c34e5377ffd45b85c81793edc203132b1baa824e08a27570`；adapter沒有新增market logic。
- Targeted/cross-boundary regression：`300 passed / 122 subtests passed`。
- Architecture tests：`18 passed`；checker：PASS，`26 actual violations / 26 declared debt`。
- Changed Backend modules compileall：PASS。
- 本輪未執行production DB mutation、provider IO、runtime restart、scheduler enable、commit或push；Runtime、MCP host、Live與Product acceptance維持pending。

## 2026-08-29 Precommit final polish source結果

### F4 — Selection measurement metadata與sector scope

- 新增Backend-owned `CAPABILITY_FIELD_COMPANIONS`；只有explicit `daily.ohlcv` fields包含`points`時，才依序補入`volume_unit`、`trade_value_unit`、`currency`。
- Effective selection、v4 projected payload與manifest現在共用相同expanded fields；quality仍照projected outward evidence檢查，不再因selection先移除producer metadata而誤報`volume_unit_missing`。
- Explicit unit不重複、requested field順序不變；未指定fields仍回空override並使用既有default fields，unsupported field validation未放寬。
- Sector sample coverage不再把helper的`canonical_active_stock_universe`覆寫成`active_stock_master`；partial warning明確標示ordinary active stocks。
- `market_daily_price.full_market_coverage`與`market_daily_price.full_market_sector_index` compatibility keys未改，sector/sample ranking仍保持partial/sample-only與decision unusable。

### F4驗證

- 新增regression先取得`4 failed`，精準重現effective fields、v4 measurement metadata、sector scope與warning四項問題；修正後局部`4 passed`。
- Capability／v4／TW aggregate／quality policy／MCP schema matrix：`151 passed / 27 subtests passed`。
- TW market context projection／tool boundary／intraday contract／screening matrix：`61 passed`。
- Architecture tests：`18 passed`；checker：PASS，`26 actual violations / 26 declared debt`。
- Changed Backend modules compileall與targeted `git diff --check`：PASS；只有既有LF→CRLF提示。
- MCP offline snapshot未變更且schema parity通過；adapter沒有新增selection、unit或coverage邏輯。
- Read-only runtime probe：`/api/system/health=ok`、`readyz=ready`，但PID 28256的launcher始於`01:02:06`，本輪`capability_contract.py`更新於`01:32:50`；explicit daily fields仍只回原四欄manifest、unit為null且quality含`volume_unit_missing`，確認F4 source尚未adopt。
- 本輪未執行provider IO、production DB mutation、runtime restart、scheduler enable、commit、push或release。F4僅完成Source seal；Runtime、Live與Product acceptance維持pending。
