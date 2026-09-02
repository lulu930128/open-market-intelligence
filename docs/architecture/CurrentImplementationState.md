# Current Implementation State

本頁是最後已記錄且可追溯的 checkpoint index，不是即時 runtime、provider 或正式市場 session 的替代品。沒有本輪 evidence 時必須使用 `not_reverified`，不得沿用歷史 PASS。

## Fixed status vocabulary

- `accepted`：該 surface 的指定 gate 有本輪或明確引用的有效 evidence。
- `partial`：有可用能力，但仍有已知 gate 或 truth limitation。
- `pending`：尚未開始或尚無足夠 evidence。
- `blocked`：有明確 blocker，無法安全推進。
- `in_progress`：source work 正在進行，不可視為完成。
- `not_applicable`：該 truth layer 不適用。
- `not_reverified`：可能有歷史 evidence，但本 checkpoint 未重新驗證。
- `retired`：surface 已完成正式 removal，且 legacy gate 有證據。

不得使用 `planned`、`ready`、`green` 或單一 PASS 取代以上狀態。

## Truth layer definitions

- Source：source code、typed registry、contracts、migration files 與 deterministic tests。
- Runtime：launcher-selected process、project root、interpreter、port、migration 與 loaded source identity。
- Live：實際 entitlement、provider response、lease、release window 與正式交易 session。
- Product：API、AI、MCP、Frontend、Kuro 的最終可見語意。

## State matrix

| Surface | Source | Runtime | Live | Product | Last verified at | Evidence | Limitations |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Instruction／truth navigation | accepted | not_applicable | not_applicable | accepted | 2026-08-27 | `AGENTS.md`; `docs/architecture/index.md`; nested `AGENTS.md` | Source-only governance；不代表 mechanical enforcement |
| Mechanical architecture guard | accepted | not_applicable | not_applicable | not_applicable | 2026-08-29 | `architecture/constraints.toml`; `architecture/debt.toml`; `scripts/check-architecture.py`; `backend/tests/architecture/`; US/TW consumer convergence validation | Guard v2封住TW與US outward/research protected storage models；仍有22個既有exact debt，accepted不代表debt已清零 |
| Shared Market Data Foundation | partial | not_reverified | not_reverified | partial | 2026-08-27 | `backend/app/market_data/contracts.py`; `backend/app/market_data/registry.py`; architecture debt | Canonical／Resolver seams 存在；仍有精確 legacy debt |
| Taiwan market | accepted | partial | partial | partial | 2026-08-31 | `docs/exec-plans/active/tw-closing-session-convergence-20260831/`; `docs/exec-plans/active/tw-outward-semantic-closeout-20260831/`; `docs/exec-plans/active/tw-backend-outward-contract-convergence-20260828/`; `docs/exec-plans/active/tw-us-shared-core-4-4-0-consolidation-20260829/`; `docs/exec-plans/active/tw-fugle-realtime-resilience-20260830/`; current source／targeted tests | Current index、quote-component、closing headline、session-close、capture semantic health與intraday provider boundary的source semantic closeout已收斂；本checkpoint未restart、未provider IO、未production DB mutation，正式09:00／13:30 session與REST／AI／MCP／Frontend parity待隔日驗收 |
| United States market | accepted | partial | partial | partial | 2026-09-01 | `docs/exec-plans/active/us-market-truth-convergence-20260901/`; `docs/exec-plans/active/us-market-realtime-daily-root-repair-20260901/`; `docs/exec-plans/active/us-backend-shared-core-convergence-20260829/`; `docs/exec-plans/active/us-index-missing-data-repair-gate-20260830/`; executable registry／manifest；targeted source validation；architecture guard | 1m canonical identity、producer與repair根修仍有效；Market Truth Core Source已完成typed partial health、policy-owned close authority、interval quality gate、四種comparison purpose、WAL snapshot consistency與diagnostic shadow diff。Compatibility facade、AI／MCP／Frontend consumer cutover、production DB cleanup、running Backend adoption、正式Live與browser Product仍待分開驗收 |
| Secondary markets | partial | not_reverified | not_reverified | partial | 2026-08-27 | current market modules／outward contracts | JP／KR／Crypto／Resource 不得推定與 TW／US 同等 acceptance |
| `omi.decision.v4` | accepted | partial | not_applicable | partial | 2026-08-29 | `docs/architecture/OmiDecisionContract.md`; source capability／projection registries；4.4.0 selection-bound regression；既有running direct/proxy/MCP AAPL evidence | 4.4.0 source已把`daily.ohlcv` effective limit傳入US canonical／chart reader；runtime與MCP host尚未adopt本輪source，不能用先前AAPL readback宣稱新selection path已Product accepted |
| Market temporal axes | accepted | not_reverified | not_reverified | partial | 2026-08-27 | `backend/app/market_data/contracts.py`; `docs/architecture/MarketTemporalContract.md` | Shared axes 已分離；projection-local release／reconciliation vocabulary 仍需逐 contract 收斂 |

## Architecture Guard v1 known limitations

- GET purity 目前檢查 router 內 direct call 與 side-effect keyword；若 `GET -> read_service() -> provider fetch` 經間接呼叫發生，可能無法偵測。
- Frontend provider selection 目前是 scoped lexical scan；provider 若經 helper、`URLSearchParams` 或 wrapper 間接傳遞，可能無法偵測。
- AI provider boundary 目前主要禁止 direct provider import；AI 若依賴會間接啟動 acquisition 的 market service，可能無法完整阻擋。
- 以上是 Guard v2 candidates，不代表目前已有對應 enforcement。只有出現實際漏網案例時才擴充 rule；不為理論完整建立全 repo call graph 或第二套 compiler system。

Registry／debt manifest 是 executable truth；parity test 只驗證 invariant，不保存 capability、dataset 或 debt 的固定數量，也不建立 YAML／Markdown inventory。

## 2026-08-28 Taiwan consumer convergence checkpoint

- Source：completed daily exact/series/universe、official index exact/series、official breadth、valuation、next-session、ADR、volume pace、technical、chips、derivatives、Radar outcome/automation/backtest、dashboard baseline、index chart/contribution、stock market-cap與AI explicit trade-date均改用canonical owner；protected consumer raw imports由Guard v2阻擋。
- Historical research freshness同時套用release qualification與receipt available-at cutoff；storage future row、late backfill receipt與future checkpoint不會倒灌point-in-time consumer。
- Breadth：改由canonical daily universe聚合，TWSE OpenAPI與RWD不再形成兩套consumer truth；多receipt仍以`BREADTH_COMPONENT_LINEAGE_NOT_COHERENT` fail closed。
- Quality：20/20 request為complete；不足history、continuity或unit lineage仍truthful limited。ETF applicability在semantic quality前生效。
- Source validation：consumer primary matrix `254 passed / 8 subtests`；受cutover影響的extended matrix `110 passed / 5 subtests`；architecture `18 passed`；cold daily/index/breadth/quote/dashboard `19 passed`；compileall與diff-check通過。
- Full backend baseline：final source修正前完整suite為`2428 passed / 31 failed / 1 error / 476 subtests`。其中本輪相關21個failure已由extended matrix逐一轉綠；剩餘database fixed counts、KGI fixture schema、dark checkpoint、US旁線與Windows ACL未在本輪改動或宣告通過。
- Runtime：port 8400 health/ready與project root/interpreter正確，但live v4仍缺新`trade_value_unit` projection，證明running process尚未採用本輪source；未獲restart授權，因此Runtime/Product不得標accepted。

## 2026-08-29 Taiwan final-cleanup source checkpoint

- Historical technical observation：explicit `trade_date`已貫穿daily／weekly／monthly technical report、advanced evidence、TAIEX benchmark與corporate-action relevant analysis end；historical request不再混入today/current-partial evidence。
- Completed-session stock aggregate：market service以同一次canonical stock-only snapshot提供selected rows、active-stock denominator與TWSE／TPEX coverage counts；ETF不再污染sector/ranking。
- Outward quality：sector covered count欄位已對正；`market.sample_ranking`固定投影`sample_only`，Backend registry與repo MCP offline schema digest同步。
- Source validation：受影響regression `300 passed / 122 subtests`；architecture `18 passed`；guard `26 actual / 26 declared`；changed modules compileall通過。
- Runtime／Live／Product：本 checkpoint 未restart、未provider IO、未DB mutation，也未重新採用MCP host schema；維持partial／pending，不由Source測試推定accepted。

## 2026-08-30 Taiwan Fugle realtime resilience source checkpoint

- Fugle新增為TAIEX current index、單一active-stock quote與1m bar的`SUBSCRIPTION` capability；單一runtime／allocator固定一條physical connection，訂閱組合為indices加active-stock aggregates／candles，總上限5。
- Stream event先進bounded latest-state buffer，duplicate／out-of-order／malformed event fail closed；materializer重用既有raw receipt與current-index／public-quote／intraday-bar transaction，使用`WEBSOCKET` lineage並mandatory reread，沒有新增migration或平行outward type。
- TWSE MIS index、quote、depth／auction與breadth共用provider-wide guard；429與`Retry-After`投影為`rate_limited`／cooldown，cooldown內不再發request，過期只允許單一recovery probe。
- Current index與breadth scheduler已拆成獨立lane；index job只刷新index，breadth使用獨立60秒設定。第二輪將breadth改為逐批bounded I/O並依實際calls計帳，429／cooldown後停止新批次；fresh且required fields完整的Fugle TAIEX partial evidence不再觸發MIS。
- Viewer lease採subscription-only sequential fallback：KGI acquire成功時不啟動Fugle，KGI unavailable／timeout才清理失敗handle並嘗試Fugle，任一時間只綁定一個public lease。Fugle lease只有在connection、entitlement、requested-symbol subscription ACK與fresh record全數成立時才標live。
- Fugle active-stock quote／1m bars的source scope擴至TWSE／TPEX；TPEX index仍未廣告。Provider payload venue不一致時fail closed，`isTrial`只投影indicative，不以`lastTrial`偽裝confirmed trade。
- Integration boundary：Fugle lease port是精確授權的market-owned `research_lease` integration；Fugle runtime health由`tw_realtime_lease_platform`投影，`system` router不再直接import provider runtime。
- Third-round source closeout：Fugle TAIEX previous-close seed由market platform強制exact previous-session official優先、same-session non-Fugle fallback，拒絕跨日current row、future lineage與Fugle self-seed；pending content hash在安全seed後可重試。
- Viewer lease heartbeat在provider terminal或bounded transition grace到期後，會清理舊provider handle並以同一public lease ID原子切換下一條subscription route；provider generation保持private，併發heartbeat共用單一replacement。
- TWSE MIS provider guard以generation／single-use attempt token關聯每個request outcome；較舊或重複的success不能清除較新的429 cooldown，只有當代single recovery probe成功可恢復healthy。
- Pre-release consistency closeout：breadth的external-call budget已在provider descriptor、runtime requirement、dataset operation、TW catalog與Shared registry一致為20，並由repair lifecycle執行；quote acquisition scope、AI／depth provider attempts與source health改以actual selected evidence為準，公共MIS availability維持獨立axis。
- Capability provenance closeout：quote outward的`primary_provider`／`provider_attempts`只由quote capability自己的`MarketDataResultV1.acquisition`產生，bundle-level `acquisition_scope`維持獨立request telemetry；KGI／Fugle cached quote不會再被MIS depth attempt改寫。Typed quote-depth API現在保留provider attempts、bundle scope與component lineage，AI只轉譯backend projection，Frontend沒有provider selection邏輯。
- Taiwan index context不再固定宣告Yahoo，source refs改列實際讀取的canonical current／daily與可選chips／contributions／intraday surface；`PUBLIC_BEST_EFFORT_NO_SLA`也已從canonical quote dataset移回public acquisition operation。
- Fugle TAIEX previous-close input lineage尚未獨立持久化；被選中的Fugle current-index evidence會以`FUGLE_INDEX_PREVIOUS_CLOSE_INPUT_LINEAGE_NOT_PERSISTED`明示。Owner為current-market platform／persistence，解除gate為additive versioned component-lineage migration、cache reread與outward replay regression。
- Frontend只為既有持久化資料保留legacy composite intraday source label mapping；Backend architecture regression禁止再emit `nstock_minute_stock_data_twse_mis_volume`或`yahoo_finance_chart_twse_mis_volume`。此相容seam必須等retention或migration清除既有rows後才可移除。
- Pre-release consistency source validation：affected matrix `242 passed / 3 subtests`；architecture checker `22 actual / 22 declared`、architecture／TW boundary matrix `53 passed`；changed Python modules `py_compile`與`git diff --check`通過。未做runtime restart、provider I/O、migration apply或production DB mutation。
- Capability provenance source validation：focused `84 passed`、public quote／component serialization `43 passed`、TW registry／dataset／architecture `110 passed`；architecture checker `22 actual / 22 declared`、Frontend TypeScript與OpenAPI property probe通過。未做runtime restart、provider I/O、migration apply或production DB mutation。
- Third-round source validation：Shared／TW擴大regression `214 passed`；architecture checker `22 actual / 22 declared`、architecture pytest `18 passed`。未做runtime restart、provider I/O或production DB mutation。
- Source validation：final affected matrix `227 passed`；architecture checker `22 actual / 22 declared`、architecture pytest `18 passed`、compileall通過。完整backend suite跑到100%且log未出現test failure，但pytest session cleanup遭既有`.tmp` Windows ACL `WinError 5`，因此safe profile未clean exit。
- Second-round source validation：focused加public-quote `82 passed`；Shared／TW擴大regression `213 passed`；architecture checker `22 actual / 22 declared`、architecture pytest `18 passed`、changed modules `py_compile`通過。未做runtime restart、provider I/O或production DB mutation。
- Runtime／Live／Product：source default仍為off；本機ignored `.env`已在commit後設為on，但running Backend尚未採用本輪source。兩次bounded provider probe均使用一條連線：TAIEX單一subscription，以及TAIEX加2330 aggregates／candles共3/5 subscriptions，credential、auth、entitlement與全部subscription ACK成功；未啟動materializer且DB零變更。週日無data event，因此payload、正式交易時段重連、production runtime與REST／MCP／Frontend outward parity仍pending。

## 2026-08-31 Taiwan outward semantic closeout source checkpoint

- Current index：AI market aggregate與index compact context在Shared Core `current_data_core.index`存在時只做outward projection，不再讀minute cache後二次resolve；legacy輸入缺canonical component時才保留相容resolver。Active-session legacy summary candidate同時要求same trade date與240秒內event time，stale／missing time不得fallback成current。
- Index contributions：market owner統一判斷expected trade date、component coverage、reconciliation、confidence與estimate availability；AI只消費producer `decision_usable`，row count與tool execution completed不再等同quality ready。
- Hot groups／quote components：Dashboard v1 list改投影正式scheduler-owned intraday group snapshot，preopen無actual trade如實為空；order-book／auction各自使用component resolved health、dataset health與lineage event time，parent quote stale/current不再污染component。
- Post-close／Fugle：Today technical report使用canonical session close，pending時只呈現最後盤中成交且不給技術分數；Fugle current-index descriptor不再廣告POST_CLOSE materialization，index anomaly ratio改由market-owned constant單一維護。
- Source validation：affected matrix `143 passed`；extended TW／AI／current-market matrix `160 passed / 12 subtests`；safe quick profile的architecture checker、architecture pytest、backend compileall、Frontend TypeScript與diff check全數通過。
- Acceptance boundary：未做runtime restart、provider I/O、production DB write／migration、MCP host adoption、browser E2E、commit或push。Runtime、正式交易Live與Product parity維持pending，隔日需分09:00 current-session與13:30 session-close兩個時窗驗收。

## 2026-08-31 Taiwan closing-session convergence Source checkpoint

- Headline identity：Quote outward新增backend-owned `headline_*` evidence bundle；session close與official daily只更新headline，不再覆寫`last_trade_*`。AI與Frontend改讀headline，保留last trade作獨立觀測。
- Compatibility closeout：REST `last_price/change/change_pct`在最終projection alias至同一組`headline_*`，真正成交identity只由`last_trade_*`持有；QuoteDepth僅在當下auction／preview／replay允許indicative覆蓋，盤後殘留indicative不得壓過official／session headline。
- Closing lifecycle：只有exchange authority、合法close-resolution session／event window與confirmation boundary可形成`session_final`；KGI broker callback維持candidate。Official daily reconciliation改成append-only metadata，不再把session finalization改名成official daily。
- Capture／health：收盤capture改由market-owned session-close acquisition執行，transport success與semantic ready分開計數；13:33後沒有current `session_final`時只能是partial／missing或帶明確原因的truthful unavailable，不能以舊quote假綠。
- Intraday boundary：KGI已可把bounded minute-kbar stream轉成canonical finalized 1m bars；NStock session total volume不再灌入最後一根bar；series coverage以requested-at為界區分`complete_prefix`／`complete_session`／`trailing_window`等狀態，AI、technical與volume projection都保留partial；quote／depth／auction candidate read按registered provider公平取樣，不讓單一provider先吃滿global limit。
- Intraday finalization／projection：NStock與Yahoo以interval end boundary擁有current-day bar finalization；Today與history保留`bar_type/finalization/indicator_eligible/price_semantics`。Completed-session close marker是cache-only projection event，official優先、session close fallback；它不寫DB、不計入`cached_count`、不進technical indicator。
- Closing volume／depth（2026-09-01 Source）：session-close canonical projection保留closing-match `tv`與session cumulative `v`；official marker可沿用official price但不奪取volume lineage。Production closeout在close-resolution以既有depth transaction做bounded MIS capture，13:33後cache-only；盤後只投影同交易日`closing_auction|close_resolution`的`closing_session_snapshot`，Frontend與AI明示non-tradable且`decision_usable=false`。Runtime／Live／Product尚未驗收。
- Production closeout owner：新增獨立於fixed-slot acceptance capture的bounded session-close scheduler，於13:30:01至13:34:01執行五個retry，使用Tier-A target planner、already-final short circuit與per-symbol partial／failure result。
- Current source validation：closeout targeted matrix `112 passed / 3 subtests`、相鄰matrix `32 passed`、Frontend純契約Playwright `6 passed`；safe quick的architecture checker、architecture pytest、backend compileall、Frontend TypeScript與diff check全數通過，targeted ESLint亦通過。Validation log：`.tmp/validation/20260831-231308/`。
- Acceptance boundary：未做runtime restart、provider I/O、production DB write／migration、commit或push。Source accepted不代表running Backend已adopt；現行port 3000的兩個較大TPEX smoke受既有dev runtime測試proxy隔離失敗，不列為Product acceptance。09:00 current-session、13:30 close-resolution、15:15 official daily與產品畫面仍須分開驗收。

## 2026-08-29 United States daily Shared Core source checkpoint

- `us.daily.ohlcv`的provider descriptor、Gateway planning、canonical acquisition、raw receipt、atomic persistence、cache reread、Resolver、quality與outward projection已接成單一production binding；manifest source gate為`US_DAILY_BACKEND_V1_SOURCE_ACCEPTED`，effective runtime mode仍維持off／未採用。
- US expected completed session、stock／ETF／index identity與volume applicability由US market-owned typed ports提供；`^SOX`不依賴company／SEC row，index volume保持`not_applicable`而不是0。
- Priority research與full-market EOD共用同一platform／transaction owner；Shared lifecycle不再反向import US service、calendar、ORM或transaction。
- REST chart/history compatibility、AI compact context、technical／Radar、valuation、overnight impact、ADR／cross-market、regional freshness與agentic daily refresh均由canonical platform／resolved bars投影；AI、market與watchlist consumer重新import `USDailyPrice`會由architecture guard失敗。
- Historical research candidate read以raw receipt `available_at` cutoff排除當時尚未取得的回補資料；GET/read path保持cache-only，provider I/O只存在於explicit POST／job operation。
- Source validation與未授權邊界記錄於`docs/exec-plans/active/us-backend-shared-core-convergence-20260829/SourceAcceptance.md`。本checkpoint未apply production migration、未provider I/O、未restart、未enable scheduler，也未驗證API／MCP／Frontend running parity。

## 2026-08-29 United States daily M9.0 rollout stabilization checkpoint

- Daily outward read明確固定為canonical cache-only；production acquisition另外由Shared `CapabilityRolloutState`控制。`canary`只允許設定內target，`off/shadow/compare`禁止acquisition，`on`才允許全市場。
- `USDailyOhlcvPlatform.refresh()`在任何Gateway/provider I/O前fail closed；US full-market EOD scheduler只有Daily acquisition rollout=`on`才可建立job。這是source enforcement，不以本機TW-only `.env`取代。
- REST chart/refresh response model以additive欄位保留expected/latest trade date、selected source/provider、fallback/reason、facts/decision usability、limitations、persistence/postcondition與raw receipt IDs；deprecated provider query只允許`auto`。
- Validation：兩組targeted/cross-boundary矩陣共119 passed；architecture checker `22 actual / 22 declared`、architecture pytest與compileall通過。Full backend 2505 tests執行到100%且無test failure輸出，但pytest session cleanup遭既有`.tmp` Windows ACL拒絕，正式profile未clean exit。
- Runtime：使用者透過正式launcher restart；direct／proxy health與readyz、runtime OpenAPI、三檔cache-only GET及read-only EOD job inventory證明M9.0 source/config已採用。Read binding=`canonical`，acquisition=`canary/canary_targets`且target count=1；restart後沒有新US full-market job。
- Live／Product：本checkpoint未provider I/O、未production DB write。AAPL／TSM／`^SOX`均truthful missing／unusable，direct與proxy一致；三檔allowlist/live seed、MCP/Frontend完整parity與canary gate仍pending。
- 最終runtime readoption：14:32正式launcher restart後，unknown canonical identity在direct與proxy均回結構化404；AAPL／TSM／`^SOX`合法cache-only GET仍truthful missing且不觸發acquisition。Read-only DB確認migration與US scheduler無新增副作用，因此M9.0 Runtime gate accepted。
- Precommit semantic preflight：既有focused matrix仍為`101 passed / 12 subtests`，但額外negative probe可重現technical payload明示missing／unusable後被generic builder提升為available／ready，以及Daily missing的`refresh_recommended=true`被清成false；public diagnostics repair仍可進legacy refresh owner，Chart／consumer尚未完整保留canonical truth。這不撤銷M9.0 rollout/runtime acceptance，但會阻擋`US_DAILY_PRECOMMIT_CLEAN`，必須先完成active plan M9.0.5。
- M9.0.5 Source closeout：上述negative cases已成regression並轉綠；repair job改走canonical Platform，legacy candidate store移除，Chart／Frontend改承接Platform truth。Focused matrix為`256 passed / 27 subtests`、architecture `22 actual / 22 declared`、Frontend ESLint／TypeScript通過。Runtime尚未restart採用，故下一gate為M9.0.6而非Live accepted。
- M9.0.6 Runtime adoption：15:30由既有tray owner正式`RestartServices`；repo root、root `.venv`、8400／3000、direct/proxy/UI與OpenAPI皆採用本輪source。Migration維持`20260829_0073`、US job count未變、三檔canonical row仍為0；restart期間新增raw receipts皆為既有TW scheduler，沒有US provider side effect。下一gate為三檔bounded live seed。
- M9.1 AAPL live evidence：一次explicit refresh用滿Yahoo／Alpha Vantage 2-call budget；Yahoo receipt已持久化，但8/28 bar的`close=null`，canonicalizer只接受到8/27，Alpha Vantage request失敗。修正post-acquisition receipt cutoff後，running direct／proxy都能cache-only重建Yahoo selection並truthfully回stale／facts-only；因expected/latest不相等，Live gate保持partial且未進TSM／`^SOX`。
- M9.1 retry／M9.3 stale Product parity：唯一追加的Yahoo-only retry job 8128只執行1次external call；receipt `116418` HTTP 200但8/28 close仍null，故postcondition正確失敗並永久套用本輪stop rule。完成typed Daily -> capability quality -> `omi.decision.v4` stale projection修正後，direct REST、frontend proxy、running OMI Search MCP與可見Frontend一致呈現expected 8/28、latest 8/27、Yahoo、stale、facts-only、decision unusable與refresh recommended；cache-only decision/MCP呼叫前後raw receipt與job計數不變。MCP snapshot digest為`107685377b25ccd1bcca72f4273a321d2aeeb4f15bbdbd172725622412f1321b`，runtime build為`df381534481ac358`。這只接受stale path，不建立三檔Live gate、precommit clean或publication權限。
- M9.1A／M9.1B free-provider Source checkpoint：Shared `ProviderResourceHealth`新增相容的resource identity，Daily legacy policy改由V2 descriptors投影；Alpaca SIP Historical已具備bounded client、pure canonical adapter、STOCK／ETF P2 descriptor、typed failure、transaction metadata與Yahoo missing-expected-session deterministic fallback。Fixture acceptance證明Yahoo 8/28 malformed時Alpaca candidate可經persist／mandatory reread由Shared Resolver選中，Yahoo完整時P2零call，index不會誤送stock endpoint。Source accepted不等於Live：本機尚未設定Alpaca credential，production active tuple仍保留Yahoo／Alpha Vantage；read-only DB顯示AAPL 8/28只有缺lineage的legacy Yahoo row，canonical full-lineage row仍為0、latest canonical仍為8/27。
- M9.1D Twelve Data Source checkpoint：Quote／Intraday REST client、header auth、typed provider errors與pure canonical fixtures已完成；2026-08-30 source又將Yahoo／Twelve capability-keyed descriptors接入US Quote／Intraday Shared Core。`PARTIAL_US_MARKET_VOLUME`保持可見，Twelve仍未加入Daily。這是source binding，不代表credential、runtime或live acceptance。
- M9.1C／M9.1E stock／ETF Live cutover：本機ignored env已設定測試credential；AAPL與TSM bounded live均在Yahoo expected-session不完整後由Alpaca SIP final OHLCV補至2026-08-28，receipt／canonical transaction／mandatory reread與Shared Resolver fallback通過。Production及candidate descriptor、manifest與legacy priority現固定Yahoo→Alpaca，Alpha Vantage Daily不在production inventory；其Fundamentals／Corporate Actions與quarantined rollback parser不受影響。
- M9.3A Candidate history coverage：同一`us.daily.ohlcv` executable truth新增typed minimum-bar intent及bounded `us.ensure_daily_history_coverage` operation；Gateway／Resolver不再把fresh-but-short series視為coverage完成，ordinary read/refresh仍保留temporal usability，history operation另要求provider-coherent coverage postcondition。AAPL與TSM以operation-scoped Alpaca-first planning各寫入537根canonical bars，restart後direct／proxy均cache-only回260/260 complete、latest 2026-08-28。Index volume `not_applicable`、Alpaca pagination truncation與`legacy_compat` lineage均有fail-closed regression；這不提供`^SOX`第二個Daily provider，也不解除index fallback缺口。
- M9.2／M9.3 runtime/product readback：19:56正式launcher restart採用repo root、root `.venv`、8400／3000；direct與proxy對AAPL／TSM均回8/28 current、Alpaca fallback且逐欄一致，running OMI Search `omi.decision.v4`與可見Frontend AAPL同樣current。cache-only read期間新增receipt全屬既有TW scheduler，沒有US provider side effect。
- Index limitation：`^SOX`只規劃Yahoo，8/28 malformed後latest維持8/27 stale；Alpaca descriptor正確不接受INDEX。Twelve Data官方資料描述與本機credential probe未建立可用`^SOX` Daily contract，實際1day request為HTTP 404。因此stock／ETF gate accepted，但三檔fresh／closeout gate保持partial，不能以SOXX等ETF替代`^SOX`身份。

## 2026-08-29 OMI 4.4.0 TW／US Shared Core source consolidation checkpoint

- TW Daily：market service將canonical completed Daily的`latest_data_date`作為finalized-through boundary；同日期provisional intraday evidence不再移除official close／volume／trade value／transaction count，較新的未finalized session仍可overlay。
- US Daily INDEX：Yahoo canonical adapter依instrument applicability處理volume；raw `0`與`null`對INDEX都產生`volume=None`／`volume_status=not_applicable`，不影響STOCK／ETF與1m regular zero-volume語意。
- AI／outward：normalized `omi.decision.v4` selection limit由Backend傳成US Daily既有`bars` bound；AAPL／TSM 260根需求同時限制Platform與chart reader，Frontend／MCP沒有新增補資料或coverage重算。
- Source validation：Shared／TW／US／AI matrix `282 passed / 27 subtests`；AI／API／US boundary補充matrix `54 passed / 64 subtests`；architecture pytest `18 passed`、checker `22 actual / 22 declared`；affected compileall、Frontend ESLint與TypeScript通過。
- 版本：source surface設定為4.4.0，定位為TW／US Shared Core consolidation立腳點，不代表全市場production complete。
- Runtime／Live／Product：本checkpoint未restart、未provider I/O、未production DB mutation，也未重新adopt MCP host；running 4.4.0 behavior仍為pending。`^SOX`第二Daily provider、full-market rollout與publication維持獨立gate。

## 2026-08-30 US Quote／Intraday Shared Core source checkpoint

- Source：`us.quote.snapshot`與`us.intraday.bars`已拆成兩個registry lifecycle，共用`USIntradayMarketPlatform`。GET與AI compatibility reader為cache-only；explicit refresh才可經Yahoo／Twelve acquisition、raw receipt、transaction、mandatory reread與Shared Resolver。
- Persistence：Quote使用additive `us_quote_snapshot` migration；Intraday沿用`market_intraday_bar`，但只有inner-joined完整lineage rows可成為candidate。舊的lineage-free US rows保持在本機資料中但fail closed，不做隱性backfill。
- Daily dependency：Previous Close與Volume Pace改從`USDailyOhlcvPlatform`的resolved series取得；Volume Pace再以同一個resolved Intraday series做same-time comparison，不再query raw `USDailyPrice`做`max(volume)`。
- Consumer：REST legacy payload shape保留；AI fill owner拆成`us.refresh_quote`與`us.refresh_intraday_bars`，`us.read_intraday_trend`只保留為cache-only compatibility reader。Frontend與MCP維持既有stable outward contract，不新增provider selection。
- Acceptance：source tests與migration tests已建立；4.4.0 runtime adoption、Twelve credential/live probe、正式交易時段session驗證、restart readback與product acceptance尚未執行。Intraday canonical shadow在runtime／parity acceptance前保留。
- Persistent-read closeout：Twelve descriptor limitations會隨persisted candidate重建，evidence session由event timestamp擁有；Quote／Intraday identity與descriptor applicability fail closed。Intraday repository以provider-fair allocation遵守總`RequestBounds.max_rows`，35-day raw cache read與5-day provider acquisition requirement已分離。
- Product semantics closeout：Volume Pace同時檢查5／20-session sample depth，任一不足均維持partial；historical baseline改由bounded canonical lineage aggregate query讀取Resolver-selected provider／source，避免20日高密度1m資料突破raw row bound。Daily resolved read horizon增至30 bars，Previous Close不再以Intraday history替代resolved Daily。US manifest移除misleading singular Daily reader，只保留capability-keyed bindings。
- Retention：`us_quote_snapshot`定義為30-day recent canonical cache；Source已接上bounded daily cleanup job，只刪除horizon外Quote rows並保留raw receipt。Materializer與cleanup預設皆feature-off，因此大規模symbol polling仍禁止。
- Source acceptance：合併後US／Shared／AI／MCP／migration targeted matrix `188 passed / 78 subtests`；Fugle／TW integration boundary matrix `51 passed`，先前`test_market_data_v2_dark_boundary`與`test_tw_data_core_boundaries`兩個cross-branch failure已關閉。後段分段backend matrix另為`732 passed / 5 subtests`；architecture checker `22 actual / 22 declared`、architecture pytest `18 passed`與compileall通過。完整backend pytest的單一process仍受Windows basetemp ACL cleanup阻擋。Source gate為`US_INTRADAY_QUOTE_SOURCE_CLOSEOUT_ACCEPTED`；production migration apply、runtime restart、live provider／session與REST／AI／MCP／Frontend product parity仍pending。

## 2026-08-30 US Quote／Intraday materializer與outward Source checkpoint

- Materializer owner：新增feature-off的US market background owner；target universe由設定擁有，預設`AAPL,TSM`且hard bound為2。Quote預設300秒、Intraday預設60秒；只在US trading day的PRE_OPEN／CONTINUOUS／CLOSING_AUCTION／POST_CLOSE執行，Closed不開DB、不做provider I/O。Quote與Intraday共用non-blocking run lock，且每target的provider budget最多2。
- Persistence／retention：Materializer只呼叫既有`USIntradayMarketPlatform.refresh_quote()`／`refresh_intraday_bars()`，沒有第二套provider選擇、transaction或cache。Quote cleanup是獨立daily bounded batch，30-day horizon，不刪RawFetchResult或Intraday rows。
- Outward binding：REST新增cache-only resolved Quote GET；Intraday response嵌入同一份Quote projection與backend-owned `current_observation`。當Quote比最新resolved bar舊時，backend保留較新的bar作current observation；Ranking、AI、Detail Today與Regional Tape不自行選provider或觸發refresh。Yahoo delayed limitation不會被AI轉成live，Twelve provider與`PARTIAL_US_MARKET_VOLUME`維持可見。
- Source validation：materializer／US shared core／AI context／foundation seam／database contention／architecture targeted matrix `176 passed`；changed Python compile、Frontend ESLint／TypeScript與OpenAPI schema probe通過。這只是Source checkpoint；production migration apply、formal restart、Yahoo／Twelve live、session readback、MCP adoption、Frontend E2E與runtime p50／p95仍pending，尚不可宣告`US_INTRADAY_QUOTE_PRODUCT_CLOSEOUT_ACCEPTED`。

## 2026-08-30 US Market Core convergence Source checkpoint

- Priority Daily contract：`reconcile_us_priority_ohlc()`的executable intent已由monthly／72改為provider-coherent Daily／260；`^GSPC`、`^DJI`、`^IXIC`、`^SOX`、`^NDX`、`^VIX`仍共用`USDailyOhlcvPlatform`與既有canonical Daily repository。Temporal或minimum-history postcondition不足時維持partial與explicit coverage limitation，不以UI aggregation需求或provider best-effort冒充260根完成。
- Current observation lineage：Intraday outward現在分開提供`current_source_status`與`bar_source_status`；`source_status`只保留為chart／bar health相容alias。Backend依resolved Quote與resolved Bar的event time選`current_observation`，且該observation保留provider、source、freshness、fallback與limitations；headline與Regional Tape使用current evidence，professional intraday chart使用bar evidence。
- Consumer truth：AI intraday projection優先讀`bar_source_status`，不再把current Quote provider漏到bar contract；Frontend來源提示改為resolver-selected provider，並獨立呈現partial、delayed、stale、fallback與unavailable，不再將Twelve Data誤標成Yahoo。正式監控窗內的time-based stale優先於vendor delayed標記，避免較嚴重的老化被降級。
- Source validation：附件列出的US Daily／Index／Quote／Intraday／Materializer／Research／AI／Shared Technical affected matrix為`119 passed`；P1A／P1B聚焦矩陣為`66 passed`。Architecture checker、architecture pytest、backend compileall、Frontend TypeScript、targeted ESLint與`git diff --check`通過；pytest只有既有`.pytest_cache` ACL warning。
- Acceptance boundary：本checkpoint只建立`US_MARKET_CORE_CONVERGENCE_SOURCE_READY`。本輪沒有provider I/O、production DB write、migration apply、runtime restart、MCP host adoption、正式交易時段Live Gate、Frontend browser／E2E、commit或push；這些仍是獨立Runtime／Live／Product／Git gates。Worktree仍混有TW與Shared變更，後續只能exact file／hunk staging，禁止`git add .`。

## 2026-08-30 US Market Core Control Plane Source checkpoint

- Daily operation：priority repair現在執行operation-wide symbol、external-call、provider-attempt與runtime budgets，CANARY rollout由本次實際target universe建立；單一symbol失敗會rollback並記錄error result，不阻斷後續target。Daily candidate reader以跨registered providers與unregistered rejection lane共用的總`max_rows`做fair allocation與fail-closed sentinel。
- Daily eligibility：US-owned canonical eligibility specification現在同時要求row／raw receipt／Source Registry identity一致，且`raw.parser_version`與row contract為exact或`parser+suffix`相容；Daily repository與full-market EOD共用相同SQL-safe規則。Source mismatch、parser mismatch或其他不合格raw row只能回rejection／partial，不得誤判current。Shared candidate model未加入US-specific row-budget invariant，避免改寫TW repository行為。
- Current truth：current observation仍由resolved Quote／Bar event time決定，但Previous Close只接受exact expected completed-session Daily。Quote內的previous-close欄位只保留provider diagnostic；Daily缺失時REST／AI／Regional Tape保留null與`CANONICAL_US_DAILY_PREVIOUS_CLOSE_MISSING`，不在consumer端回退重算。
- Materialization：`USIntradayPlatformResult`正式擁有profile-aware postcondition，Materializer不再讀取Shared result不存在的欄位。`recurring_current`使用1-day acquisition／600 bars並要求current evidence；`bootstrap_latest_available`使用最多5-day／1000 bars，Closed session可將Friday canonical evidence判為bootstrap success，但health仍為stale且不冒充live。Yahoo range由typed requirement映射；executor在Gateway前強制`max_bars`與`max_rows`。Exception path以reservation守住operation external-call hard budget；runtime summary依lane + capability保留equity／index狀態。Explicit `us.bootstrap_current_market_cache`已接tracked internal Job、typed bounded operator POST與retry mapping；cache滿足時零call no-op，仍未接startup或GET。Quote retention可在materializer關閉時獨立註冊，所有新增enable flags預設off。
- Source validation：US／Shared／AI／cross-market targeted matrix `222 passed`；後續Canonical index fixture regression `3 passed`，US total-budget加TW boundary matrix `8 passed`，後段backend matrix `814 passed / 5 subtests`。Pre-runtime hygiene focused matrix `35 passed`，OpenAPI executable inventory同步為421 operations total／420個`/api` operations並明確守住Quote cache-only GET、refresh POST與Bootstrap operator POST。Architecture checker `22 actual / 22 declared`、architecture pytest `18 passed`，changed Python compile、Ruff、Frontend ESLint／TypeScript與`git diff --check`通過。完整single-process backend suite本輪未重跑；既有Windows default pycache／basetemp ACL風險不構成本Source gate的runtime證據。
- Final Closeout validation：Daily／Priority／Intraday／Bootstrap Job／EOD／AI boundary擴大矩陣`130 passed`，最終Platform／Materializer／acquisition focused matrix`46 passed`；architecture pytest `18 passed`，checker維持`22 actual / 22 declared`。Backend compileall、changed-file Ruff、Frontend TypeScript、targeted ESLint與`git diff --check`通過；pytest只有既有`.pytest_cache` ACL warning。
- Bootstrap budget／scheduler final Source closeout：Shared requirement新增typed `EvidenceTarget.CURRENT`／`LATEST_AVAILABLE`；Acquisition只把fresh evidence視為fresh，但Bootstrap遇到第一個required fields完整的usable stale candidate即可停止不必要fallback。加入Index Intraday lane後，Default cold-bootstrap budget固定為16個normal-path calls加2個fallback headroom；Sunday空cache的6 Index與AAPL／TSM各自Quote／Intraday fixture以16 calls完成，first-provider failure可在18-call hard bound內fallback，雙provider unusable維持fail-visible。Materializer ledger按actual acquisition summary計帳，persist／reread exception保留已知calls；pre-acquisition failure不再永久消耗後續lane budget。Scheduler尚未改為single owner，但runtime summary已累積每lane run outcome、lock contention、duration、provider calls與refreshed symbols；同lane連續兩個interval因`materializer_run_in_flight`跳過仍是明日Runtime starvation blocker。
- Final Source validation：Bootstrap／Gateway／Shared Core／Job／API inventory／manifest／architecture targeted matrix `142 passed / 64 subtests`；architecture checker維持`22 actual / 22 declared`。Changed-file Ruff、isolated Python compile與`git diff --check`通過。Executable integration manifest已交接至`US_MARKET_CORE_SOURCE_CHECKPOINT_READY`，但mixed-worktree dependency inventory仍未stage。
- Acceptance boundary：本輪沒有provider I/O、production DB write／migration apply、runtime restart、正式session Live Gate、MCP／Frontend runtime adoption、browser E2E、commit或push；Runtime／Live／Product／Git仍pending，scheduler contention必須在Runtime Gate實測，不能由Source counters取代。
- 22:23 Runtime preflight：官方8400／3000 runtime健康，backend identity為本repo root與root `.venv`，但running OpenAPI只有382 paths且沒有Bootstrap operator，materializer health也缺少current source的index lane與cumulative counters，因此仍是stale source、Runtime adoption未通過。Production DB已在Alembic `20260830_0074` head，但Quote cache與Bootstrap Job均為0；AAPL／TSM direct及frontend proxy cache-only GET如實回`policy_unsatisfied`與null quote，未觸發provider I/O。本次只做read-only probe，沒有migration、restart或DB mutation。

## 2026-08-30 US Index missing-data repair gate source checkpoint

- Control Plane新增獨立、預設啟用的六指數repair gate；每次interval先以canonical cache-only Daily／Quote read稽核，滿足時零provider call且不建立Job。GET、Frontend、MCP、AI與Shared Core未加入acquisition、enqueue或write。
- 缺口以`index-gate:<expected_trade_date>`建立tracked JobRun；active lease、30分鐘cooldown與同一completed-session最多2次attempt會抑制重複工作。單次Daily／Quote各有12 external-call hard budget，universe固定為`^GSPC`、`^DJI`、`^IXIC`、`^SOX`、`^NDX`、`^VIX`。
- Repair重用`reconcile_us_priority_ohlc`與`materialize_us_intraday_capability`的provider／transaction owner；只有持久化後重新讀取同時通過Daily temporal+260-bar coverage及Quote bootstrap-latest postcondition才標success。Priority ledger同步改用typed `AcquisitionSummary.external_calls`，不再讀取不存在的`attempts`。
- Source validation：新gate `10 passed`；priority+gate `18 passed`；scheduler／materializer／job retry／health／API inventory `66 passed / 64 subtests`；擴大US Daily／Intraday／Bootstrap matrix合計`149 passed`。Architecture checker為`22 actual / 22 declared`、architecture pytest `18 passed`，changed-file Ruff與isolated compile通過。Lineage migration第一次僅因sibling worktree `.tmp` sandbox權限失敗，取得精確目錄權限後同一測試通過。
- 已授權production repair JobRun `8377`保持truthful error：Quote 以6個Yahoo calls補齊6/6並由persisted reread通過；Daily取得每檔260 bars但最新只到2026-08-27，expected 2026-08-28仍缺一個session，因此6檔Daily postcondition未通過。Direct 8400與Frontend proxy 3000已可讀Quote價格及260根Daily，狀態仍為`stale`／`partial`。
- 後續cache-only planner回`cooldown`、attempt `1/2`且Quote缺口為0，沒有立即重打provider。Running process未restart採用新scheduler source，亦未做browser UI驗證；因此automatic Runtime adoption、完整Live freshness與browser Product acceptance仍pending。

## 2026-08-31 US temporal expectedness Source checkpoint

- Shared／US contract：Shared新增單一正交`CapabilityExpectation = not_expected | expected | required`；US policy依Backend calendar phase投影Quote／Intraday expectedness，session scope、descriptor support、instrument applicability、availability、evidence freshness、provider snapshot freshness與trade recency維持獨立欄位。`expected_but_missing`只作derived outcome，不能掩蓋producer／cache缺口。
- Quote freshness：Quote provider snapshot以`fetched_at`判斷，last trade以`event_at`判斷；fresh snapshot加old trade回`LAST_TRADE_OLD_BUT_PROVIDER_CURRENT`，不再把無新成交誤報為provider stale。Intraday bars仍以bar event age判freshness。
- Change reference：相容`previous_close`仍是exact expected completed-session Daily；新增`prior_regular_close`、`current_day_regular_close`與typed `change_reference_*`。盤前／正常盤只用prior regular close，盤後只用當日finalized regular close；缺失時回`CURRENT_DAY_REGULAR_CLOSE_PENDING`，不沿用前一交易日close。
- Outward consumer：REST Quote／Intraday、AI capability projection／brief與Frontend Today共用Backend `market_phase`、`capability_expectation`、source status及change reference。Frontend不從本地時鐘推session truth，也不把Daily close偽裝成current quote；missing、required missing、no trade與not expected使用不同文案。
- Source validation：Temporal／Shared Core／close-session `55 passed`；AI／US market `146 passed`；materializer／outward／foundation／capability `119 passed / 12 subtests`；US boundary／MCP補充`30 passed`。Architecture checker `22 actual / 22 declared`與architecture pytest `18 passed`；OpenAPI source probe、Frontend TypeScript／ESLint與mock Playwright `1 passed`。
- Acceptance boundary：`US_TEMPORAL_EXPECTEDNESS_SOURCE_ACCEPTED`只接受Source；Runtime restart、provider I/O、production DB mutation、正式盤前／盤中／盤後Live Gate、MCP host adoption與running browser Product驗證仍pending，不能由source tests取代。

## 2026-08-31 US regular-session runtime／consumer parity checkpoint

- Backend `current_observation`由未套presentation scope的current-session canonical Quote／Intraday evidence決定；`regular／extended／all`只過濾chart points，切換scope不得改變headline。`session_coverage`獨立揭露同一trade date的regular／extended coverage與requested slice count。
- Frontend不做silent session fallback；selected slice為空但其他session有資料時顯示明確可用筆數與切換提示。5秒cadence只標成local cache polling，不宣稱provider每5秒更新；internal pre-resolution code不當成warning，cache-only policy改以人類可讀文案呈現。
- 正式launcher於2026-08-31 22:14 Asia/Taipei採用bounded equity materializer設定，target固定AAPL／TSM；Quote與Intraday首輪均2/2成功、0失敗，Intraday使用2個external calls且無reentrant／lock skip。Index lane維持關閉，未擴大full market。
- TSM direct REST與Frontend proxy parity：regular 47、extended 295、all 342，三種scope headline相同；Quote provider snapshot fresh且trade current，Yahoo delayed limitation仍可見。實際browser Today regular圖表可見、scope切換不改headline、cache polling文案正確且console error為0。
- Source validation：Backend focused 161 passed；Frontend TypeScript、targeted ESLint、focused Playwright 1 passed；Architecture guard 22 actual／22 declared。此checkpoint接受bounded AAPL／TSM Runtime／Live／Product，不代表交易所級live entitlement或full-market coverage。

## 2026-08-31 US Realtime producer coverage repair Source checkpoint

- Producer owner：Index current lane 現在同時具有 feature-off 的 `quote.snapshot` 與 `intraday.bars` scheduler owner，兩者共用同一組 bounded 六指數 universe；cold-cache bootstrap 也同時覆蓋兩項 capability。Equity lane 可選擇由 configuration、active US portfolio holdings 與 enabled US watchlist 合併 universe，最終仍由 materializer hard bound 截斷；dynamic owner 預設關閉，不會自行擴張既有 AAPL／TSM runtime quota。
- Freshness contract：Shared freshness basis 新增明確 `event_time`／`received_time`／`fetched_time`；US Quote resolution 與 provider health 使用 fetched time，last-trade age 保持 event time，Intraday bars 使用最新 bar event time。Recurring profile 將 producer refresh-due 固定為 180 秒、consumer stale-after 固定為 300 秒；Quote scheduler tick 為 120 秒，避免 producer 與 consumer 同時跨過 stale boundary。
- Source health：US `GET /source-health` 已恢復純讀，不再 sync／commit snapshot；歷史 snapshot 改由明確 `POST /source-health/snapshot` mutation 擁有。Projection 納入 canonical Quote／Intraday provider-target rows、freshness basis、latest observed/fetched time、snapshot age、event age 與 descriptor limitations。
- Acceptance：本 checkpoint 只有 Source acceptance；尚未 restart 正式 launcher、未開啟 Index Intraday 或 dynamic universe、未做 provider I/O、未新增 production DB row，也未重新宣稱 Runtime／Live／Product accepted。
- Read-only runtime projection：8400 health 已可讀到 Quote 120 秒interval、Index `quote.snapshot,intraday.bars` capability 與新freshness contract，表示running API projection已載入source；但`index_intraday_enabled=false`，且本輪沒有producer run／provider／DB evidence，因此Runtime activation、Live與Product gate仍pending。

## 2026-09-01 US Index Runtime activation／TW freshness checkpoint

- Runtime adoption：本機ignored `.env`已開啟`ENABLE_US_INDEX_QUOTE_MATERIALIZER`與`ENABLE_US_INDEX_INTRADAY_MATERIALIZER`，並由正式launcher restart採用。Health回Index lane兩項capability均enabled；Quote連續run為6/6 success，Intraday連續run為5/6 partial，累積counter持續增加。
- Live evidence：`^GSPC`、`^DJI`、`^IXIC`、`^SOX`、`^NDX`的cache-only 1m read均有current-session bars、Yahoo lineage、fresh provider snapshot與`CURRENT_INTRADAY_BARS_AVAILABLE`。`^VIX`最後bar停在2026-08-31 23:51:46+08:00，outcome為stale／`PROVIDER_SNAPSHOT_STALE`，因此Runtime summary保留單一failure，不將它冒充current。
- Product evidence：正式Frontend選取SOX後，Today的regular bars由151持續推進至164，Yahoo Chart延遲標記與實際盤中折線可見；「今日走勢資料不足」不再出現，browser console error為0。Frontend只輪詢cache，沒有新增GET acquisition或consumer provider fallback。
- Taiwan freshness：Dashboard v1 freshness不再使用固定90／600秒wall-clock門檻判斷所有session。Active session使用scheduler cadence加grace；completed／previous session只有trade date相符且存在13:30後evidence時投影`latest_completed_session`。2026-09-01 00:00後Direct與Frontend proxy均回trade date 2026-08-31、`previous_session`與`completed_session_date` basis。
- Source validation：TW Dashboard、US Materializer、US Shared Core與System Health focused matrix為`85 passed`；changed-file Ruff通過；Architecture checker維持`22 actual / 22 declared`。
- Acceptance boundary：主要US index surfaces的Runtime／Live／Product已接受；VIX仍是明確partial，不代表六指數全綠或exchange-grade realtime entitlement。Yahoo仍帶`DELAYED_VENDOR_EVIDENCE`，canonical US Daily previous close缺口仍可見。本輪未commit、未push、未擴張symbol universe或新增provider quota。

## 2026-09-01 US realtime／daily root repair Source checkpoint

- Minute identity：Yahoo 1m adapter把provider秒級timestamp保留為lineage event time，canonical bar identity固定為minute-aligned `[start, start+1m)`；同分鐘重複row以最新provider timestamp deterministic dedupe。Transaction owner拒絕非整分鐘、非一分鐘duration或future lineage event，避免錯誤identity再次落盤。
- Existing-data safety：新增Yahoo 1m bounded integrity inspector，只讀回報非整分鐘、同分鐘衝突、缺lineage與recommended survivor；固定`dry_run=true`／`writes_performed=0`。本checkpoint未對production DB執行cleanup或write。
- Cadence／ownership：recurring producer refresh-due為45秒、consumer stale-after為180秒，Quote與Intraday tick都是60秒；source目標為正常交易時段current evidence age p95不超過90秒。Materializer lock改為`lane_id + capability` keyed owner；同key fail-fast，不同lane／capability可獨立執行。Counters分離provider acquisition、cache satisfied、persistence與selected evidence，不再把cache hit算作refresh。
- Temporal／fallback：Quote與completed Daily新增calendar-owned `omi.us.session_date_relation.v1`，同日、current-session對previous completed session、真正Daily lag分開投影。Yahoo不可用時仍只依typed descriptor讓Stock／ETF進Twelve fallback；Index維持Yahoo-only並明示`US_SINGLE_ELIGIBLE_PROVIDER`。Index repair從永久exhausted改為cooldown、bounded attempt window、manual-attention backoff後可重試，lifetime attempt持續可觀測。
- Product source：US headline在所有Today／Daily／Weekly／Monthly圖表週期都只讀Backend `current_observation`，不再退回最後一根chart close；無current quote時明示missing與歷史reference。所有畫面輪詢仍是cache-only，不新增consumer acquisition。
- Source validation：US canonical／Shared Core／materializer／temporal／repair／health／foundation／Daily相鄰matrix `204 passed`；AI／selection／Daily補充matrix `21 passed`；architecture tests `18 passed`，guard `22 actual / 22 declared`；Python compile、task-owned Ruff、Frontend TypeScript／targeted ESLint與mocked Playwright `2 passed`。Safe quick全數通過，log在`.tmp/validation/20260901-020145/`。Full selected-file Ruff另看見進場時已存在於大型dirty `service.py`與`intraday_transaction.py`的unused imports，本輪未跨task清理；排除F401後沒有其他lint finding。

## 2026-09-01 US realtime／daily root repair Round 2 Source checkpoint

- AI canonical truth：agentic gap scanner改讀US cache-only resolved Quote／Intraday的`capability_expectation`；tool execution只保留為session diagnostics，不能把missing canonical data提升為ready。Explicit capability要求逐項滿足；legacy combined trend相容路徑仍接受Quote或Intraday任一可用。
- Priority Daily／EOD：scheduler預設開啟且每輪受20 symbols／20 external calls／2 provider attempts限制；六個US indices與active holdings固定排在rotating watchlist之前，cursor不再延後critical targets。所有read／repair仍重用`USDailyOhlcvPlatform`。
- Existing-data repair：新增`omi.us.intraday_minute_repair.v1` bounded transaction與tracked POST job，dry-run預設且apply必須產生per-job audit manifest；rollback可還原survivor、deleted bars與lineage。有minute-aligned canonical bar時完整保留其OHLCV；只有provisional snapshots時依event order合成OHLC，volume／trade value採max。GET inspector維持純讀。
- Read-side hardening：US Yahoo 1m candidate遇到非整分鐘或同minute bucket重複時分別投影`NON_CANONICAL_MINUTE_IDENTITY`與`DUPLICATE_MINUTE_BUCKET`，resolved dataset維持partial而非complete。
- Production read-only evidence：SQLite `mode=ro`第一批200 conflict groups涵蓋35 symbols與2026-07-22，planned delete 689、missing lineage 889、仍有後續批次，`writes_performed=0`。本checkpoint未apply cleanup、未restart、未做provider IO或正式Live／Product驗收。
- Round 2 validation：AI freshness `4 passed`、Priority EOD／scheduler `19 passed`、job retry `2 passed`、repair／rollback／OHLC policy `3 passed`、read-side rejection `1 passed`；architecture guard維持`22 actual / 22 declared`，changed Python compileall與OpenAPI inventory probe通過。
- Acceptance boundary：這是Source acceptance。未apply production DB cleanup、未restart正式launcher、未做provider I/O或正式交易時段Live量測、未驗證running MCP／Frontend product adoption，也未commit或push。Active universe擴張維持deferred。

## 2026-09-01 Taiwan index／close-auction wiring Source checkpoint

- Index intraday owner：`tw.market_index.intraday` 由 `taiwan_current_index_snapshot` 的 lineage-complete canonical observations 衍生；同分鐘先按 provider/source resolution 再做 deterministic OHLC aggregation。Fugle TAIEX raw identity 必須是 `IX0001`，歷史 `IR0001`／TAIEX TRI 誤標 row 會以 typed rejection 排除。`/indices/{index_id}/intraday` 已切換到此 cache-only platform，production scheduler 不再寫入 legacy `taiwan_index_minute_snapshot`；legacy table 未刪除、未改寫。
- Close semantics：13:30 current index observation 若仍是 provisional，只能投影 `session_close_marker`／`session_close`；只有 release-qualified、非 provisional 且 final/corrected/official-final 的 official daily evidence 才能投影 `official_close_marker`／`official_close`。兩種 marker 都是 projection event，不納入 indicator 或 persisted coverage。
- Index directory：新增 `tw.market_index.directory` durable versioned snapshot/items 與 explicit refresh operation。GET 只讀 latest successful snapshot；missing schema／empty DB 回 typed missing，stale 保留 items 並明示限制，provider failure／empty refresh 不覆蓋前次成功版本。Additive migration source 已建立但未套用 production/local DB。
- Tier-A targets：Production intraday、session-close 與 quote-contract acceptance 共用 typed ordered plan，canonical origin 順序為 configured、holding、active lease、watchlist；acceptance canary 是明確 operation profile，不代表 production universe completeness。
- Acceptance boundary：本 checkpoint 僅代表 Source 接線與 targeted source evidence。未 apply local/production migration、未 restart 正式 launcher、未做 provider I/O／refresh、未執行正式交易窗口 Live gate、未驗證 running Frontend／MCP adoption，也未 commit 或 push；Runtime、Live、Product 與 Git publication 全部維持 pending。

## 2026-09-01 Taiwan canonical bootstrap／runtime closeout checkpoint

- Source：Stock/ETF canonical Base-1m與TAIEX/TPEX Base-1d都有explicit bounded tracked jobs；Stock/ETF使用Tier-A plan、1m/5d及既有acquisition/transaction，TAIEX保留最近最多260 sessions，TPEX最多20 sessions且HTTP 520最多重試3次。Legacy約226萬intraday rows沒有bulk promotion，GET/read仍cache-only。
- Projection semantics：post-close Index headline在official close未到位時可選trade-date相符、final且qualified的canonical Base-1d；Chart quote-side改讀canonical public quote projection，不再呼叫legacy intraday trend。VWAP只適用intraday且跨session reset；1d/1w/1mo明示not applicable。
- Runtime：launcher-owned精確restart後，8400 identity為本repo與`.venv`，3000 identity為本frontend且proxy指向8400。Running OpenAPI包含兩個bootstrap routes；3711 direct/proxy chart同時回quote value 610與Base-1m history missing，TAIEX post-close selected candidate為`completed_daily_bar`且official close保持pending。
- Product：3711 Today實頁顯示「最近完成交易日 610」與「1 分 K 尚未建立完整」；Daily／Weekly／Monthly日期分別顯示`YYYY/MM/DD`、`YYYY/MM/DD 週`、`YYYY/MM`。`last_verified_at=2026-09-01 Asia/Taipei`。
- Validation：targeted Backend `161 passed / 72 subtests`，bootstrap補強`2 passed`；Frontend TypeScript、targeted ESLint、production build與contract `5 passed`；architecture checker `22 actual / 22 declared`，safe quick PASS。
- Acceptance boundary：Source、Backend/Frontend Runtime adoption與上述cache/product truthfulness accepted；provider bootstrap未執行，正式09:00／13:24／13:31／15:15 Live windows與MCP host未重驗，因此完整Live／Product／Consumer parity仍pending。未commit、未push、未啟用pruning、未刪legacy data。

## 2026-09-01 US Market Truth convergence shadow Source checkpoint

- Contract owner：新增typed `USCloseEvidence` identity/version/fingerprint、close roles、latest/current/headline observations、comparison references、backend-owned numeric change metrics、named-policy reconciliation與Snapshot／Series component revisions；dangling identity、price-unit／currency／basis incompatibility與impossible-state由contract fail closed。
- Read owner：`market_truth.py`只使用caller-owned SQLAlchemy Session、caller-provided `evaluated_at`與既有resolved Quote／Intraday／Daily platform；不建立Session／clock，不做provider selection、provider I/O、refresh、repair、enqueue、commit或第二份cache。
- Close policy：released exact Daily優先；time落在close bucket的bar只形成unverified close-boundary evidence，沒有instrument-specific official proof就不能升格official。Provider previous-close hint採deterministic default-deny gate，只能在qualified context作display-limited reference，永遠不是research-usable或exchange authority。
- Session boundary：US session分類移到market-owned `session_policy.py`；`MarketSession.CLOSING_AUCTION`不再進legacy regular points、volume pace或current-day regular close。Series scheduled interval count由交易日calendar close動態計算，early close不固定390。
- Shadow surface：新增cache-only `GET /api/us-market/truth/{symbol}`，大型1m series由revision-linked `GET /api/us-market/truth/{symbol}/intraday`分離；既有intraday endpoint尚保留為rollback surface。Compatibility facade、shadow diff telemetry、AI／MCP／Frontend consumer cutover與legacy owner removal仍pending，故本checkpoint不是完整Market Truth convergence closeout。
- Source validation：targeted matrix `120 passed / 64 subtests`，新增route／contract focused matrix `29 passed / 64 subtests`；唯一pytest temp ACL setup error在sandbox外精確重跑為`1 passed`。Architecture checker `22 actual / 22 declared`、architecture pytest `27 passed`；safe quick的Backend compileall、Frontend TypeScript與`git diff --check`通過。Read-only production SQLite smoke驗證AAPL／TSM／`^SOX`可以compose且既有missing／limited／data-quality限制未被隱藏。本checkpoint未做provider I/O、production DB write、runtime restart、running OpenAPI／MCP adoption或browser Product驗證。

## 2026-09-01 US Market Truth core-closeout Source checkpoint

- Partial truth：Snapshot health改為typed quote／intraday／daily component status；單一或全部component missing都維持可序列化的partial／missing truth。Unknown symbol為404，已知client input為400，內部identity／contract錯誤不再被誤包成400。
- Close authority：移除evidence自帶的eligibility claim；`USCloseResolutionPolicy`依NASDAQ／NYSE／NYSE Arca venue或明確index identity採default-deny proof rule，policy context必須與evidence identity一致。沒有宣告的venue、index或proof source不能升格official close。
- Interval quality：final regular interval close必須同時通過parent facts health、minute identity／duplicate integrity與calendar-derived完整session coverage；正常390分鐘與2026-11-27 early-close 210分鐘均有regression。瑕疵evidence保留但`display_usable=false`；closing-auction bucket亦不再進volume pace。
- Comparison truth：Backend固定產生regular／extended／headline／research四種reference與metric purpose。After-hours只接受同交易日close；不能退回前一日或provider hint。Official-vs-interval差異標為cross-semantic `diverged`，真正same-semantic差異才是`mismatched`。
- Snapshot consistency與shadow：SQLite read path在首次component read前建立同一MVCC snapshot，真實WAL concurrent-writer regression確認Quote／Intraday／Daily讀到同generation。新增pure、bounded、diagnostic-only legacy／Truth shadow diff；未接router或consumer，不構成cutover。
- Source validation：core focused `51 passed / 64 subtests`；affected US regression `205 passed / 64 subtests`，唯一pytest temp-ACL setup error在sandbox外精確重跑為`1 passed`。Architecture checker維持`22 actual / 22 declared`、architecture pytest `28 passed`；safe quick的Backend compileall、Frontend TypeScript與`git diff --check`通過，log為`.tmp/validation/20260901-210807/`。Ruff未安裝，沒有宣稱Ruff通過。
- Acceptance boundary：本輪Market Truth Core Source已完成；Frontend／AI／MCP、legacy compatibility facade與consumer cutover仍pending。未做provider I/O、production DB write、runtime restart、running runtime adoption、browser Product驗證、commit或push。

## 2026-09-02 Taiwan index Truth convergence Source checkpoint

- Canonical owner：`ResolvedTaiwanIndexTruth`升為`tw.index.resolution.v3`，只組合已解析的current／intraday／completed daily／official-close evidence role，不擁有provider priority、I/O或storage winner selection；selected value、previous close、change與change percentage保留同一semantic lane及reference lineage。REST summary、Dashboard、AI `market.indices`、AI compact quote與index contract snapshot共用同一resolution identity；`current_data_core.index`只保留diagnostic／live snapshot與明示版本、limitation的短期compatibility fallback。
- Intraday boundary：`tw.market_index.intraday` executable registry與Taiwan dataset catalog改指向`TaiwanBarService`，由Canonical Bar repository、Shared Gateway與既有Resolver產生`tw.bar.series_read.v1`；registered refresh依序acquire current evidence、沿用既有materializer/transaction落Base-1m、再reread Unified Bar。舊current-snapshot minute selector不再是production/registry可達owner，沒有新增provider、cache、table或manager。
- Finality truth：release-qualified、exchange-authority、final/corrected completed daily evidence可確認official close；未滿足者仍保留pending。Derived／pending-release completed evidence可明示為latest-completed reference，但保留`official_source=false`、`official_close_status=pending`與`provisional_estimate=true`，不把Unknown或provisional偽裝成official。
- Read-path：current index／breadth repository先查七日近期視窗，沒有資料才回退歷史cache；`20260902_0077`新增符合scope/provider/latest ordering的composite indexes。Read-only source probe由每次27 queries降至21，五次median約1.31秒；production DB尚未apply migration，故不是running runtime latency acceptance。
- Source validation：本checkpoint既有affected matrix `170 passed / 3 subtests`；headline adoption另通過`254 passed / 12 subtests`、architecture pytest `28 passed`、checker `22 actual / 22 declared`、backend compileall與`git diff --check`。Safe quick（含Frontend TypeScript）通過，log為`.tmp/validation/20260902-213049/`。Current-source cache-only smoke確認TAIEX／TPEX的REST summary、Dashboard及AI在value、previous close、change、source、provider與resolution ID一致，且未走compatibility fallback。Safe backend全量pytest超過420秒上限，wrapper終止child時先遇到Windows access denied，精確中斷wrapper後確認child已結束；此項不得記為pass或assertion failure。
- Runtime projection：本輪未主動restart，但8400 listener在驗證期間由外部流程換成PID 48892；cache-only GET已回`tw.index.resolution.v3`，TAIEX／TPEX的summary與Dashboard selected fields及resolution ID一致，證明這兩個HTTP projection已載入本次行為。該PID實際executable為`C:\miniconda3\python.exe`，health未暴露project root且command line無法讀取，與預期`.venv` launcher identity不一致，故完整Runtime identity仍未accepted；running AI `market.indices`另只有current-source direct smoke，沒有獨立transport proof。
- Acceptance boundary：Headline consumer Source accepted，summary／Dashboard runtime behavior accepted但launcher identity pending；未apply production migration、未做provider I/O、正式交易session Live、running AI／MCP transport parity、browser Product、commit或push。260-session historical coverage仍是獨立gate。

## 2026-09-02 US index architecture convergence Source checkpoint

- Phase A：US cash index canonical volume固定為`null`／`not_applicable`；transaction拒絕不合規輸入，repository對legacy rows fail-safe中和且不提供index volume sessions。新增bounded、dry-run-first、audited、reversible repair與tracked job；production SQLite query-only dry-run辨識6746 rows／6 symbols，`writes_performed=0`，尚未apply。
- Phase B：`app.us_market.market_indices`以單一caller-owned clock組合既有六份US Market Truth，固定`^GSPC`、`^DJI`、`^IXIC`、`^NDX`、`^SOX`、`^VIX`順序並保留selected lineage、freshness、fallback、reference、truth revision與partial/missing。新增cache-only `GET /api/us-market/indices`，`omi.decision.v4` `market.indices`擴充為TW／US且遵守bounded selection。
- Source validation：A+B targeted regression `95 passed`；US indices／Market Truth／AI capability `121 passed / 12 subtests`；MCP／outward contract `64 passed / 2 subtests`且offline snapshot digest已同步；audited repair rollback精確測試`1 passed`。Safe quick的architecture checker、architecture pytest、compileall、Frontend TypeScript與diff check全數通過，log在`.tmp/validation/20260902-221858/`。
- Read-only local evidence：query-only aggregate為6/6 complete並保留每項resolved Yahoo lineage；running 8400 OpenAPI尚未包含新indices／repair routes，本輪未restart，故Runtime adoption維持pending。這不代表外部provider live或產品端驗收；Massive維持source-ready canary-only，沒有production promotion。

## 2026-09-02 US intraday current-session date boundary Source checkpoint

- Calendar owner：`build_us_calendar_status()`新增獨立`current_session_trade_date`；active
  `pre_market／regular／after_hours`只接受紐約當地當日交易日。Completed Daily release
  規則沒有改動；2026-09-02 09:54 ET的Intraday expected date是09/02，Daily expected
  completed date仍是09/01。
- Selection owner：Compatibility intraday與Market Truth series共用
  `select_us_intraday_trade_date()`。Active session的cache若只有09/01，Today points與
  `trade_date`為空並明示expected 09/02、latest available 09/01、unsatisfied；mixed cache
  只選09/02；off-session才允許latest historical。
- Current truth：Quote provider snapshot freshness與event trade date保持正交。Fresh
  transport不再把前一交易日last trade升格current；source status回`historical`、
  `current_session_satisfied=false`、`decision_usable=false`。Market Truth current／headline
  與legacy `current_observation`同樣拒絕前一session Quote／Bar。
- Frontend：Today polling只消費Backend date-selection契約，不做browser timezone計算；
  mismatch／missing會主動清空上一輪chart state並抑制舊current price。Daily／previous
  close reference仍可獨立顯示。
- Source validation：boundary targeted matrix `104 passed / 3 subtests`；Frontend
  `tsc --noEmit`與targeted ESLint通過。未執行browser E2E，未restart runtime、未做provider
  I/O、production DB mutation、commit或push；Runtime／Live／Product acceptance均pending。

## 2026-09-03 US index temporal／AI final convergence Source checkpoint

- Temporal owner：`temporal_expectedness.py`新增pure selected-evidence assessment，Compatibility service與US Market Truth共用同一event-age、current-session與provider-snapshot判定。Recent `fetched_at`不再能把old／previous-session `event_at`升格current；`current_observation`改為session identity，freshness、trade recency與research usability保持獨立。
- Market Truth／aggregate：Quote與Bar observation additive保留provider snapshot freshness、trade recency、current-session expected／satisfied。VIX-like today-but-old evidence仍可facts display且保留current-session identity，但`freshness=stale`、`research_usable=false`；`market.indices`六項coverage仍可complete，aggregate `is_current=false`、`decision_usable=false`並帶stale limitation。
- AI／quality：US Quote compact與`quote.snapshot` default projection保留`source_status`、`session_date_relation`、expected/event trade date及current-session fields。Generic realtime先消費Backend normalized fields，不重算US calendar；valid-empty awaiting-first-trade不再提升previous price。Data Quality只接受typed aligned Quote／completed-Daily relation，真正mismatch仍blocking。MCP offline public contract snapshot已重生。
- Source evidence：核心temporal／Market Truth／indices／AI矩陣`177 passed / 15 subtests`；compatibility／capability／service矩陣`201 passed / 12 subtests`；architecture pytest `30 passed`，MCP／offline snapshot `34 passed / 2 subtests`，guard維持`22 actual / 22 declared`；Frontend TypeScript與9-file no-write AST compile通過。Active-session production SQLite query-only smoke顯示SOX current／research-usable，VIX current-session identity成立但`trade_recency=old`、`freshness=stale`、`research_usable=false`，aggregate 6/6但not-current／not-decision-usable。Running 8400唯讀對照仍回VIX live／decision-usable且AI quote缺relation／source-status，證明Phase C source尚未被runtime採用；本輪未restart、未provider I/O、未DB write、未commit／push，AI／MCP transport與Product parity仍是獨立gate。

## 2026-09-02 Taiwan index history／directory reconciliation closeout

- Source：TAIEX／TPEX daily history沿用`TaiwanBarService`與既有bounded tracked bootstrap owner；90-bar不足時不再回complete，outward coverage包含requested／available／returned、range、minimum、missing與bootstrap recommendation。TPEX historical materialization固定使用explicit formal-close component，TPEX專用version升為`tw.tpex.daily.materialize.v2`，舊version不再eligible；official daily存在時同一transaction flow會補做reconciliation。GET/read維持cache-only。
- Calendar／directory：2025年9月29日、10月24日、12月25日依交易所年度休市日程納入Taiwan calendar。Index directory將transport age與observation trade date分開；2026-09-02 live refresh中，TWSE為transport fresh但latest 09/01／expected 09/02，因此投影stale與`TW_INDEX_DIRECTORY_OBSERVATION_DATE_STALE`；TPEX latest／expected均09/02且為fresh。
- Production data：執行前SQLite backup為`data/backups/open_market_intelligence.before-tw-index-history-reconciliation.20260902.db`，quick check通過且SHA-256為`8013cbfa2de296ffbdc1d62849fb1f1b4904f666897aab7d684d45e8b84e7cd0`。Canonical readback為TAIEX 260／TPEX 260個唯一交易日、2025-08-08至2026-09-02、OHLC 520/520非空且無重複；TPEX 260/260均有v2 component receipt/hash lineage。TPEX 2026-09-01 derived close已由410.60重建為410.77，official reconciliation為matched。
- Runtime／Product：launcher收斂為本repo、`.venv`、single backend 8400；frontend採用3214並proxy至8400。Tracked jobs `11088`（historical 3-session reread）與`11090`（09/01 reconciliation）均為success／completed且postcondition true。TAIEX／TPEX的90與260 daily readback皆完整，latest為2026-09-02、日期嚴格遞增；canonical chart technical各260 points，兩者MA5／20／60皆非空。Chrome實頁驗收同時確認TAIEX／TPEX顯示`日K · 260 根`與K線／技術指標區塊。
- Validation：affected Backend matrix `96 passed`，postcondition／calendar focused matrix `33 passed`；architecture checker `22 actual / 22 declared`、architecture pytest `29 passed`；Frontend TypeScript、production build、contract Playwright `6 passed`與live Playwright `2 passed`。早期job `11067`／`11068`與`11079`保留為partial／runtime-adoption／postcondition失敗證據，不作PASS。未commit、未push；外部Fugle／Crypto連線失敗與本次index history acceptance無關。

## 2026-09-03 Taiwan index 300-session history extension

- Source／contract：TAIEX／TPEX canonical Base-1d bootstrap共用單一`TAIWAN_INDEX_DAILY_BOOTSTRAP_MAX_SESSIONS=300`上限；operator schema、retry fallback、validation與Frontend index Daily SSR／client request window同步採用300，一般台股仍維持260。相鄰Stock OHLC cache-only projection同步補齊既有required coverage fields，避免共用response model在非index路徑驗證失敗。GET/read仍為cache-only，沒有新增provider、table、fallback或consumer-owned market semantics。
- Runtime／data：launcher已採用本repo與root `.venv`，running OpenAPI兩個session上限均為300。Tracked job `11105`在bounded 2025-06-01～2025-08-07窗口寫入TAIEX 40根、TPEX 39根；TPEX 2025-08-06經3次HTTP 520後正確標記partial，沒有冒充成功。單日補跑job `11106` success且postcondition true。Canonical readback為TAIEX／TPEX各300個唯一交易日、2025-06-13至2026-09-02、OHLC 600/600非空；TPEX 300/300均為v2 materialization且具component receipt/hash lineage。
- Outward／Product：兩個`bars=300` index OHLC response皆為requested／available／returned 300、coverage complete、missing 0；canonical chart bundle各300 bars／300 technical points、history ready，最新MA5／20／60非空。3214實頁驗收確認TAIEX／TPEX皆顯示`日K · 300 根`與K線／技術指標區塊，沒有page error。
- Validation：Backend affected matrix `112 passed`；architecture pytest `30 passed`、guard `22 actual / 22 declared`；Frontend TypeScript與targeted ESLint通過，contract Playwright `6 passed`，首次contract＋live合跑`8 passed`，final restart後live覆核另`2 passed`；`git diff --check`通過（僅既有CRLF warning）。本checkpoint未commit、未push；job `11105`保留為真實partial證據，完成證據由`11106`與最終canonical reread共同提供。

## Governance v1 freeze boundary

Architecture Governance v1 自 2026-08-27 起視為 frozen：新增未宣告 violation 必須 fail，stale debt 必須 fail，既有 exact debt 僅在 manifest 精確對應時暫時允許；source violation 移除時必須同步移除 debt entry。

後續工程重心是逐筆消除 architecture debt，不再重寫 truth hierarchy、Temporal Contract、constraints schema 或建立第二份 inventory。只有實際工程案例證明現有 guard 漏網時，才以最小 rule／negative regression 擴充治理層。

## Source and runtime capability truth

- Source capability truth = source registry、typed contract 與 projection registry。
- Running capability truth = loaded runtime `/api/ai/tools`、OpenAPI／schema、migration 與 source identity。
- 若兩者不同，狀態是 runtime adoption mismatch；不得描述成兩份同時有效的 current truth。

## Update contract

更新本頁時每列至少保存 surface、Source、Runtime、Live、Product、`last_verified_at`、evidence path 與 limitations。只引用 durable evidence／task lineage，不貼完整 runtime log、秘密、provider payload、固定 PID／port 或容易過期的 capability inventory。
