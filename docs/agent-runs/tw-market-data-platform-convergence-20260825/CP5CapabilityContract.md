# CP5 Capability Contract — TWSE MIS public last-trade quote

## Product scope

- 服務台股單一標的request-time研究，提供「目前是否有可驗證的實際成交價」；不產生買賣建議、不觸發交易。
- 第一個production path只納入public TWSE MIS HTTP fetch；KGI、broker account、subscription與M5均不在本capability依賴鏈。
- Quote、depth、auction、intraday bars與session volume是不同component。本slice只對外resolve `QuoteObservation.last_trade_price`，不把單點快照製造成minute bar。

## Target

- Market：`TW`。
- Venue：`TWSE` / `TPEX`；provider channel分別為`tse_{symbol}.tw`與`otc_{symbol}.tw`。
- Instrument：第一階段支援`stock`與`etf`，symbol必須來自active `StockMaster`，對外只接受`stock_id`，不得接受provider/channel控制。
- 一次只處理一個symbol；request不得跨market或改寫instrument identity。

## Provider and usage boundary

- Provider identity：`twse_mis`；source：`twse_mis_quote_depth`；resource：`twse_mis.stock_info`。
- Public endpoint：`https://mis.twse.com.tw/stock/api/getStockInfo.jsp`；無credential、無API key、無付費quota。
- TWSE官方只確認MIS網站免費供投資人瀏覽，提供個股即時交易與五檔資訊；未找到`getStockInfo.jsp`的正式public API/SLA文件。因此本contract標記為`public_best_effort_no_sla`，不能宣稱穩定授權API。
- 本地個人研究只允許single-symbol bounded request；不做全市場collector、不大量重試、不向外redistribute raw payload。任何資料加值後對外傳輸/傳播另涉及TWSE資訊使用授權，非本task授權範圍。
- timeout上限10秒；每次最多1 provider attempt、1 external call、0 subscription、0 automatic retry。

## Resource and timestamps

- Capability ID：`quote.last_trade`；dataset ID：`tw.quote.snapshot`；schema：`omi.market.quote.v1`。
- Provider event time：message `d + t/%`，Asia/Taipei。
- Received time：HTTP response完成時的UTC timestamp。
- Fetched/raw receipt time：同一bounded response被封存為`RawFetchResult`的UTC timestamp；若transport無更細的分離點，received/fetched可以相同，但語意欄位不可省略或猜造。
- `z`只有在trade date吻合、非trial、event落在actual-trade window且`tv`或`v`有正量證據時才是actual last trade；positive price本身不足。
- `v`是累積成交張數、`tv`是最後一筆成交張數，canonical quantity轉成shares並保留原始board-lot unit/scale。
- `b/g`與`a/f`屬depth；`pz/ps/ts`屬auction/indicative evidence。本slice可保存raw與normalized row，但不得把它們塞入last-trade value。

## Session and freshness

- Session owner：Taiwan trading calendar；Market Session與instrument trade state分開。
- Active acquisition sessions：pre-open/opening auction、continuous、closing auction。Closed/post-close的`require_live`必須zero-I/O且`policy_unsatisfied`。
- Active-session live threshold：15秒（以provider event time為主）；超過即`stale`，不得標current。
- `cache_only`永遠0 provider call；persisted row以`cache_hit=true`進Resolver。
- `prefer_live`：fresh/live persisted candidate可直接回傳；missing/stale/partial才允許一次bounded fetch，失敗可回stale cache但要揭露provider failure。
- `require_live`：只有active-session、同trade date、15秒內且有actual last trade的candidate可滿足；indicative、awaiting-first-trade、stale、post-close全部truthful `policy_unsatisfied`。

## Persistence and migration

- Candidate table：`taiwan_stock_quote_snapshot`；unique key維持`(provider, stock_id, quote_time)`，避免破壞legacy reader。
- Additive migration `20260825_0068`新增nullable `source_id`、`raw_result_id`、`received_at`、`observation_state`、`market_session`、`trade_state`、`raw_contract_version`。
- Legacy rows完整保留；新platform repository在缺source/raw/state lineage時fail closed，不把legacy row冒充共同平台evidence。
- Raw receipt append-only寫入`raw_fetch_result`；candidate row可idempotent upsert到最新raw receipt。content hash由raw receipt join取得。
- Retention沿用local DB policy；本task不刪除、compact或重建production資料。

## Ownership and transaction

```text
TWSE MIS provider transport / pure parser
  -> QuoteAcquisitionPort (one route, no DB/fallback)
  -> TaiwanPublicQuoteTransaction (source + raw + quality + quote row, atomic)
  -> TaiwanQuoteCandidateRepository (read only, no provider/commit)
  -> MarketDataGateway.resolve_quote()
  -> shared Resolver
  -> provider-neutral API
```

- Transaction owner是`TaiwanPublicQuoteTransaction`；commit failure必須rollback並重新拋出。
- Provider error若已發生response或transport exception，仍產生bounded failure receipt；不得清空既有candidate。
- Adapter不commit、不選fallback；repository不做I/O、不選provider；router不辨識transport error。

## Public API

- `GET /api/market/quotes/{stock_id}/public-last-trade`：固定`cache_only`、`MarketDataResultV1(result_kind=quote)`、0 external call。
- `POST /api/market/quotes/{stock_id}/public-last-trade/refresh?policy=prefer_live|require_live`：最多1 call，persist後強制repository reread再resolve；不接受provider、channel、timeout或budget參數。
- Existing `/api/market/quote-depth/{stock_id}`維持compatibility；本slice不假裝它已完成cutover。CP7/CP8再搬consumer與移除GET refresh side effect。

## Failure contract

- Network/timeout：provider health `disconnected/failed`，保存failure receipt；舊cache不被destructive replace。
- HTTP 429：`rate_limited`，不重試；401/403：explicit entitlement/blocked limitation。
- Empty/target missing/schema drift：parser明確reason code、0 observation、raw receipt保留。
- Trial/preopen：`INDICATIVE_OBSERVED`且last trade缺失；不能變0或actual trade。
- Event date mismatch/future timestamp/stale：candidate rejected或Resolver降級；不改用consumer-local provider chain。

## AI and consumers

- CP5只交付stable backend API與platform evidence；AI/MCP/Kuro/frontend正式cutover在CP7。
- Consumer切換後只能讀resolved quote、health、candidate rejection與limitations；不得自行解讀MIS欄位或重做freshness/fallback。

## Validation contract

- Actual TWSE regular/post-close recorded payload：2330，2026-08-25 13:30:00。
- Actual TPEx preopen indicative recorded payload：6173，2026-08-21 08:59:20；證明`unknown/indicative != zero/actual trade`。
- Pure parser：regular、trial、empty、target mismatch、malformed、HTTP error、timeout。
- Gateway/service：cache hit zero-I/O、stale prefer-live bounded fetch、require-live success與session/stale fail、mandatory reread、provider health。
- Persistence：source/raw/quote atomicity、idempotency、rollback、failure receipt、legacy row fail closed。
- Migration/model：empty upgrade、0067->0068->0067 row preservation、historical partial schema compatibility、FK/index inventory。
- API/OpenAPI：method/path、no provider input、GET zero-I/O。
- External smoke只在明確bounded single-symbol條件下執行；若不在active session，不能作live acceptance。
