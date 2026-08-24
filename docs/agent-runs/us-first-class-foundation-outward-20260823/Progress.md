# Progress

## Status

- Current phase：第一塊 Foundation／Outward engineering與AAPL runtime canary complete；KGI US live entitlement是未授權的optional gate。
- Last updated：2026-08-23 17:45 Asia/Taipei。
- Authorization：已授權OMI程式重啟與bounded provider/runtime smoke；未授權KGI login／subscription、Account／Order、DB migration、commit／push或release。

## Completed

- 建立兩塊長專案文件；本目錄擁有Foundation／Outward，`../us-first-class-research-consumer-20260823/`擁有Research／Consumer。
- 修正US `market.breadth` scope leak；US technical、breadth、sectors與hot groups在未實作前truthful unsupported。
- 新增market-aware capability projection registry與US provider descriptors；`cache_only`不建立provider route，`require_live`在沒有live provider時truthful unfillable。
- 新增Yahoo quote／intraday／daily與Alpha Vantage daily pure canonical adapters，保留provider lineage、event／received／fetched time、currency、session、finalization與limitations。
- 新增neutral `omi.market.quote.snapshot.v1`與`omi.market.bars.v1` projection，優先於legacy TW-named或`points` shape。
- 新增AAPL allowlist shadow／compare；重用同一Yahoo payload，不增加provider call，只有exact match才附加resolved evidence，任一mismatch fail closed。
- 修正Yahoo 16:00 closing print語意：映射closing auction，regular/all包含，extended排除。
- 新增finalized daily cache canary：各provider候選獨立canonicalize後進shared Resolver；Alpha Vantage stale時truthful選Yahoo fallback；read path不做external fetch、commit或flush。
- AI US intraday read明確`persist_history=False`；private `_resolved_market_data`只在backend內部傳遞，outward前移除。
- neutral timestamp、price、series continuity與completed-session semantics已接入realtime／quality contract；response budget壓縮仍保留`already_attempted_actions`。
- KGI SuperPy 2.1.0 source review確認`MarketType.USStock`與獨立`api.USQuote` facade、subscribe／KBar／unsubscribe及US quote欄位存在。
- 新增KGI US fail-closed readiness contract與sanitized fixture gate；KGI不在US provider policy、不production wired、不允許Account／SubAccount／Order／portfolio payload。

## Runtime acceptance

- 正式launcher：由repo `scripts/omi-launcher.ps1`／hidden VBS擁有；backend使用repo `.venv`且`backend_reload=False`。
- 最新已驗證listener：backend PID 57576、frontend PID 56332；preferred ports為8400／3000，實際身份以launcher log與listener為準。
- Effective canary：process-scoped `CANONICAL_MARKET_DATA_MODE=compare`、`US_CANONICAL_SHADOW_SYMBOLS=AAPL`；未寫入`.env`，完整exit／正常啟動會回復off。
- AAPL quote：neutral quote schema、Yahoo lineage、completed-session selection、無private field leak。
- AAPL intraday：neutral bars schema，391 available，bounded outward truncate，closing-auction語意一致。
- AAPL daily：neutral bars schema，90 finalized bars；Alpha Vantage stale時Yahoo `COMPLETED_SESSION_FALLBACK`，無legacy `points`。
- HTTP `/api/ai/ask`、SSE `/api/ai/ask/stream`、repo MCP stdio `initialize → tools/list → omi.ask`與frontend `/omi-data/ai/ask`皆維持`omi.decision.v4` parity。
- `/api/ai/tools`仍只宣告`omi.decision.v4`，quote／intraday／daily capability存在；KGI US未被宣告。
- Rollback drill：formal launcher exit → normal off啟動回legacy → formal exit → compare+AAPL啟動恢復neutral；不需migration reversal或資料破壞。

## Validation evidence

- US／AI／runtime／KGI boundary final safe validation：388 passed、303 subtests passed；compileall與`git diff --check`通過；logs位於`.tmp/validation/20260823-174040/`。
- KGI US readiness targeted tests：38 passed in 0.72s；涵蓋readiness、US provider policy、US canonical adapter與既有KGI bridge regression。
- HTTP、SSE、MCP與frontend proxy均使用live AAPL bounded sample；quote／intraday／daily沒有`_resolved_market_data`private leak。
- 本工作流沒有執行DB migration、KGI login／subscription、Account／Order、commit、push或release。

## KGI US remaining gates

KGI US仍不是runtime-accepted provider，原因不是SDK完全缺少能力，而是OMI尚未完成並live驗證下列邊界：

- `US_BRIDGE_FACADE_NOT_IMPLEMENTED`：現有bridge初始化`api.Quote`，不是獨立`api.USQuote`。
- `US_QUOTE_FIELD_MAPPING_UNVERIFIED`：現有TW extractor期待depth arrays；US source是scalar best bid／ask並含`trading_session`。
- `US_SYMBOL_VENUE_MAPPING_UNVERIFIED`：canonical symbol、provider symbol、venue、currency與timezone尚無live sample。
- `US_SESSION_MAPPING_UNVERIFIED`：SDK session code尚未對應OMI premarket／regular／closing-auction／after-hours。
- `US_ENTITLEMENT_UNVERIFIED`：source inspection不能證明帳戶market-data qualification。
- `US_SUBSCRIPTION_CLEANUP_UNVERIFIED`：single-symbol lease、unsubscribe與disconnect cleanup未做live驗證。

## Known issues / risks

- Worktree在本工作流開始前已有大量modified／untracked內容；本工作流未reset、restore或清理其他變更，也尚未commit。
- Yahoo／AlphaVantage的legacy acquisition仍存在；AAPL neutral canary證明outward seam與Resolver語意，但不是全市場consumer cutover。
- Process-scoped compare mode會在完整launcher exit或電腦重開後回復off；這是刻意rollback設計，不是永久設定。
- Runtime曾持續出現與本工作流無關的Crypto persistence UNIQUE warning與startup interrupted jobs；未擴大scope處理。
- KGI US live smoke必須另行取得明確授權，並限制single symbol、single login、bounded timeout、Quote-only與cleanup proof。

## Next step

- 第一塊可交付給第二塊：先以neutral daily／intraday contract建立shared technical engine，再做US research capability與frontend consumer，不讓consumer自行選provider或重算freshness。
