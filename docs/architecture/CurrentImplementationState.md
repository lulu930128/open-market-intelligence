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
| Taiwan market | accepted | partial | partial | partial | 2026-08-30 | `docs/exec-plans/active/tw-backend-outward-contract-convergence-20260828/`; `docs/exec-plans/active/tw-us-shared-core-4-4-0-consolidation-20260829/`; `docs/exec-plans/active/tw-fugle-realtime-resilience-20260830/`; current source／targeted tests；read-only port 8400 probe | Completed daily/index/breadth consumer與final-cleanup source已收斂；Fugle realtime resilience為feature-off source capability，running Backend尚未adopt，credential／entitlement／正式交易時窗與outward parity未reverify |
| United States market | accepted | partial | partial | partial | 2026-08-30 | `docs/exec-plans/active/us-backend-shared-core-convergence-20260829/`; `docs/exec-plans/active/us-index-missing-data-repair-gate-20260830/`; executable registry／manifest；US index JobRun `8377`；direct／proxy readback；architecture guard | 六個index Quote已落盤且API可讀，Daily各有260 bars但只到2026-08-27，expected 2026-08-28仍缺一個session。新repair gate為source accepted但running Backend尚未restart採用，Live／browser Product仍不得標accepted |
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
- Bootstrap budget／scheduler final Source closeout：Shared requirement新增typed `EvidenceTarget.CURRENT`／`LATEST_AVAILABLE`；Acquisition只把fresh evidence視為fresh，但Bootstrap遇到第一個required fields完整的usable stale candidate即可停止不必要fallback。Default cold-bootstrap budget正式固定為10個normal-path calls加2個fallback headroom；Sunday空cache的6 Index Quote、AAPL／TSM Quote與Intraday fixture以10 calls完成，first-provider failure可在12-call hard bound內fallback，雙provider unusable維持fail-visible。Materializer ledger按actual acquisition summary計帳，persist／reread exception保留已知calls；pre-acquisition failure不再永久消耗後續lane budget。Scheduler尚未改為single owner，但runtime summary已累積每lane run outcome、lock contention、duration、provider calls與refreshed symbols；同lane連續兩個interval因`materializer_run_in_flight`跳過仍是明日Runtime starvation blocker。
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

## Governance v1 freeze boundary

Architecture Governance v1 自 2026-08-27 起視為 frozen：新增未宣告 violation 必須 fail，stale debt 必須 fail，既有 exact debt 僅在 manifest 精確對應時暫時允許；source violation 移除時必須同步移除 debt entry。

後續工程重心是逐筆消除 architecture debt，不再重寫 truth hierarchy、Temporal Contract、constraints schema 或建立第二份 inventory。只有實際工程案例證明現有 guard 漏網時，才以最小 rule／negative regression 擴充治理層。

## Source and runtime capability truth

- Source capability truth = source registry、typed contract 與 projection registry。
- Running capability truth = loaded runtime `/api/ai/tools`、OpenAPI／schema、migration 與 source identity。
- 若兩者不同，狀態是 runtime adoption mismatch；不得描述成兩份同時有效的 current truth。

## Update contract

更新本頁時每列至少保存 surface、Source、Runtime、Live、Product、`last_verified_at`、evidence path 與 limitations。只引用 durable evidence／task lineage，不貼完整 runtime log、秘密、provider payload、固定 PID／port 或容易過期的 capability inventory。
