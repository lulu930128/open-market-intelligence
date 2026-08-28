# CP5-R 台股個股收盤生命週期 Finalization 修正計畫

## 狀態

- 計畫狀態：`source_converged_runtime_adoption_pending`
- 規劃日期：`2026-08-27 Asia/Taipei`
- 所屬任務：`tw-market-data-platform-convergence-20260825`
- 目標狀態：`TW_SESSION_CLOSE_PRODUCTION_READY`
- 本文件是既有 CP5 public quote vertical slice 的 corrective extension，不建立新的 Data Core、Resolver、registry、service plane 或資料庫。
- 2026-08-27 CR0～CR6與CR7 source regression已完成；ownership、schema、health、session-close materialization、consumer、reconciliation與EOD postcondition已收斂至既有集中路徑。
- Runtime restart、installed MCP reload、provider refresh、production DB mutation、commit 與 push仍需依既有授權邊界進行；本輪未執行。

## 2026-08-27 full audit rebaseline

19:04 Asia/Taipei 的 source／runtime／SQLite／scheduler／MCP snapshot 唯讀交叉驗證，確認目前不是單一 bug，而是三層狀態不同步：

| Layer | Current truth | Gate status |
| --- | --- | --- |
| Source | 已有 `quote.session_close`、post-close acquisition route與technical provisional-close基礎，但phase mapping、source health、intraday schema、reconciliation與consumer ownership仍有缺口 | `partial` |
| Runtime | Backend於18:10以`backend_reload=False`啟動；18:25後router/schema/intraday/frontend修改尚未採用 | `not_adopted` |
| Quote storage | 3711 latest quote仍為11:49:55／601，沒有materialized session final | `missing` |
| Intraday storage | 3711有13:30／605 nstock minute bar，可供provisional research，但不是session-close owner | `available_non_owner` |
| Official daily | 3711 latest finalized daily仍為2026-08-26／592 | `stale_after_release` |
| Full-market EOD | Scheduler確實執行；1,973檔中861 current、19 partial、1,091 stale、2 missing，coverage 43.64% | `partial` |
| MCP adapter | Repo snapshot為68 capabilities且包含`quote.session_close`；installed OMI_search snapshot仍為66且缺少該capability | `adoption_drift` |

因此，文件後段原有的「PCF1～PCF6已完成」只能視為先前 source intent／targeted regression紀錄，不再構成current completion claim。後續完成判定一律改用下列獨立 gates：

1. `source_converged`
2. `source_regression_passed`
3. `runtime_adopted`
4. `post_close_live_accepted`
5. `official_eod_reconciled`
6. `http_ai_mcp_ui_accepted`

任一較早 gate 未通過，不得用較晚時段、fixture、unit test、HTTP 200或局部資料可見性代替。

## Goal

- 補齊台股現金股票／ETF 在 13:30 收盤後至 official daily 發布前的 completed-session price ownership gap。
- 讓既有 `tw.quote.snapshot` 資料管線能在 close resolution 完成後，把同一份 canonical `QuoteObservation` 投影為 `quote.session_close`。
- 13:33 後，已透過 bounded post-close acquisition 確認的標的可同時對外表達：
  - 當日 session close 已完成。
  - 當日 official daily 尚待發布。
  - 前一交易日 official close 仍是最近已完成的 official daily evidence。
- official daily 到達後，由既有 completed daily 與 session-close projection 完成 matched／mismatched reconciliation；technical completed 仍只使用 official daily。

## Non-goals

- 不新增 `tw_session_close.py`、`tw_session_close_resolution.py` 或另一個 session-close service。
- 不新增第二套 canonical observation、Gateway、Resolver、Dataset Registry、provider catalog 或 transaction owner。
- 不預先新增 session-close table；先證明既有 `taiwan_stock_quote_snapshot + raw_fetch_result` 是否足以承載 post-close confirmation lineage。
- 不把 `TAIWAN_DAILY_PRICE_RELEASE_TIME` 從 15:15 改成 13:30。
- 不把 MIS／KGI realtime evidence 改名為 `quote.official_close`。
- 不把 fixed-slot quote contract capture 或 configured symbols 改成全市場 finalizer。
- 不建立全市場 post-close collector、無界 refresh、subscription 或 background scan。
- 不讓 `quote_depth`、AI、MCP、Kuro、frontend 自行判斷 session close、provider fallback 或 freshness。
- 不把 session close 寫入 finalized daily OHLCV，也不讓 technical completed 使用 provisional evidence。
- KGI onboarding、depth、account、M5 live acceptance仍維持既有獨立邊界，不藉本修正暗示已完成。

## Architecture constraint

本修正只能沿用既有集中式資料路徑：

```text
TWSE MIS / future canonical quote provider
  -> existing provider adapter / QuoteObservation
  -> existing TaiwanPublicQuoteAcquisitionExecutor
  -> existing TaiwanPublicQuoteTransaction
  -> existing taiwan_stock_quote_snapshot + raw_fetch_result
  -> existing TaiwanPublicQuoteRepository
  -> existing MarketDataGateway.resolve_quote()
  -> existing shared Resolver
  -> Taiwan market-owned session/finalization projection
  -> quote.snapshot / quote.session_close / quote.official_close
  -> AI / API / MCP / frontend
```

`quote.session_close` 是同一 resolved quote evidence 的新增語意投影，不是新的 provider dataset 或平行 data plane。

## Existing owner map

| Responsibility | Existing owner to extend | Explicitly forbidden owner |
| --- | --- | --- |
| Global Taiwan phase | `backend/app/market/trading_calendar.py` | `quote_depth.py` local clock |
| Raw actual-trade／trial parsing | existing TW canonical quote adapter | AI／frontend inference |
| Acquisition planning and bounds | provider descriptor + shared planner | router/provider-specific branch |
| Single-symbol provider I/O | `TaiwanPublicQuoteAcquisitionExecutor` | GET cache reader |
| Atomic raw + quote persistence | `TaiwanPublicQuoteTransaction` | provider/parser/router |
| Candidate reread | `TaiwanPublicQuoteRepository` | acquisition response direct promotion |
| Candidate selection | `MarketDataGateway.resolve_quote()` + shared Resolver | new session-close resolver |
| Taiwan finalization policy | existing `public_quote_platform.py` market projection | provider adapter／consumer |
| Dataset capability mapping | existing `tw.quote.snapshot` Registry/catalog entry | new session-close dataset registry |
| Official daily | `daily_ohlcv_platform.py` | realtime quote path |
| Reconciliation postcondition | existing TW dataset lifecycle／health path | frontend／MCP |
| AI outward projection | existing Taiwan evidence bundle/projection | MCP-local computation |

## Capability contract

### Identity

- Market：`TW`。
- Venue：`TWSE`、`TPEX`。
- Instrument：registered stock／ETF。
- Existing dataset ID：`tw.quote.snapshot`。
- Existing canonical payload：`omi.market.quote.v1` / `QuoteObservation`。
- Existing acquisition capability：`quote.last_trade`。
- New outward capability projection：`quote.session_close`。
- Storage：先沿用 `taiwan_stock_quote_snapshot`、`raw_fetch_result`、`source_registry`、`data_quality_check`。
- Existing refresh operation：沿用 `tw.acquire_public_last_trade_quote` 的 single-symbol bounded plan；不得另建 generic finalization refresh-all operation。

### Why this is one capability family

- Provider只觀察 last actual trade、trade date、event time、trial state、cumulative volume與lineage。
- `session_final` 是 Taiwan market policy 對同一 canonical quote 的 resolved interpretation，不是 provider 提供的另一份價格。
- `quote.snapshot`、`quote.last_trade`、`quote.session_close` 共用相同 source row、raw receipt、provider health、dataset health與selection reason。
- `quote.official_close` 仍從 `market_daily_price` 的 official daily owner取得，不與上述 row共用 ownership。

## Authoritative phase taxonomy

`trading_calendar.py` 是唯一 global phase owner：

| Asia/Taipei trading day time | Global phase | Meaning |
| --- | --- | --- |
| `< 13:25` | `regular` | regular trading |
| `13:25 <= t <= 13:30` | `closing_auction` | closing auction input／matching boundary |
| `13:30 < t < 13:33` | `close_resolution` | individual delayed-close resolution window |
| `>= 13:33` | `post_close` | global close resolution completed |

Additional instrument state remains separate：

- `normal_close_settled`
- `closing_delayed`
- `settled_at_13_33`
- `no_actual_trade`
- `unavailable`

Shared `MarketSession` 可 additive 增加 `CLOSE_RESOLUTION`；所有 calendar mapping、provider descriptor、Gateway requirement、quote-depth schema與tests必須同一批更新。不得只改一個 enum 或讓 consumer保留 alias clock。

## Finalization policy

### Candidate evidence

一筆 canonical quote 只有在以下條件成立時，才可成為 session-close candidate：

1. `trade_date` 等於 authoritative Taiwan presentation trade date。
2. `trade_state=trade_observed`，且 `last_trade_price` 大於零。
3. trial／indicative evidence沒有被當成 actual trade。
4. provider event time屬於當日合法 actual-trade window；不要求一定落在 13:25～13:33。
5. source、provider、event／received／fetched time、raw receipt與content hash lineage完整。
6. cumulative volume若存在，不得相對同來源較新可信 observation倒退。
7. out-of-order、future time、trade-date mismatch、malformed與lineage incomplete candidate fail closed。

### Resolving

- `13:30 < requested_at < 13:33`：有效 evidence最多為 `resolving`，不可升格 `session_final`。
- resolution window內若收到較晚有效成交，既有 Gateway／Resolver照正常 candidate ordering選較新 evidence。
- 沒有 provider explicit final-match flag 時，不允許在 13:33 前提前確認。

### Session final

`requested_at >= 13:33` 後，必須有一份在 close-resolution 完成後取得的 authoritative snapshot，才能升格：

- canonical quote本身保存實際成交的 `event_time`；session-final promotion只接受13:30～13:33合法final-match／resolution event。
- persisted row的 `fetched_at`／`received_at` 與 `market_session` 證明該 last trade在 close resolution完成後重新被觀察。
- `confirmed_at` 由該 post-resolution evidence time投影，不把 event time偽造成 13:30／13:33。
- 若無 post-resolution confirmation，維持 `resolving` 或 `unavailable`；不得只因時鐘超過 13:33 把舊 cache升格。

### Storage decision gate

先用現有 schema驗證：

- `(provider, stock_id, quote_time)` upsert是否能把同一 last-trade event更新指向最新 post-close raw receipt。
- append-only `raw_fetch_result` 是否保留盤中與 post-close兩次 receipt。
- persisted `market_session`、`fetched_at`、`received_at`、`trade_state`、`raw_result_id` 是否足以在 cold read重建 `confirmed_at` 與 finalization reason。

只有 contract test證明上述任一資訊無法穩定重建，才提出 additive migration；不得先建立新 table或 generic JSON state store。若需要 migration，優先為既有 quote snapshot增加最小欄位，不新增平行 session-close row model。

## Outward projection

### `quote.session_close`

```text
status
available
price
trade_date
event_time
confirmed_at
provider
source
authority
finalization = resolving | session_final
official_daily = false
freshness
facts_usable
research_usable
reconciliation_status
limitations
```

- `authority` 沿用 shared `AuthorityClass`，不另建 `official_exchange_realtime` enum。
- `facts_usable=true` 代表可陳述當日 completed-session price。
- `research_usable` 依resolved health與limitations判定；不以單一 `decision_usable` 取代不同用途。
- `technical_completed_usable` 不屬於 session-close contract；在 official daily到達前固定為 false。

### Post-close headline priority

```text
official daily for current trade date available
  -> headline = official_close
else session_close.session_final available
  -> headline = session_close
     quote_semantics = completed_session_close
else
  -> headline unavailable
     status = session_close_unavailable | resolving
```

- 前一交易日 official close只能出現在 `latest_completed_official`／`previous_official_close`，不可成為今日 headline。
- 盤中 stale last trade不可在 post-close重新命名為 provisional/session close。

### Official daily dual-axis state

15:15 前應同時對外保留：

```text
latest_completed_trade_date = previous released trading day
latest_completed_price = previous official close
next_expected_trade_date = current trading day
release_status = pending_release
next_release_at = 15:15 Asia/Taipei
```

這不把 previous official daily標成錯誤，也不讓它遮住 current session close。

## Freshness ownership

- `quote.last_trade` active-session freshness仍以 provider `event_time` 與15秒門檻判定。
- `quote.session_close` freshness以 `trade_date == expected completed session`、post-resolution `confirmed_at` 與resolved health判定；不得因最後成交較早就自動 stale。
- Source observation age、session-final currency與official daily release status是三個不同維度。
- `quote.official_close`／`daily.ohlcv` 繼續使用 15:15 official release expected-date policy。
- `quote_depth` 不得把 source stale改寫成 `official_close_pending + is_stale=false`；應直接投影 platform給出的 component health。

## Technical and reconciliation

### Technical

- `completed`：只使用 Resolver-selected official finalized daily OHLCV。
- `current_partial`：盤中使用 current quote；post-close只能使用 `quote.session_close.finalization=session_final`。
- Session close產生的 partial bar：
  - `bar_status=provisional_close`
  - `official_daily_confirmed=false`
  - `facts_usable=true`
  - `research_usable`依health判定
  - 不進 completed indicator history
- Session close unavailable時，不可把舊 intraday quote標成 `provisional_close`。

### Reconciliation

- Reuse existing official daily read與Dataset Lifecycle postcondition；不新增 reconciliation service或 scheduler。
- Official daily到達後，以相同 symbol／trade date比較 normalized decimal price：
  - equal：`matched`
  - different：`mismatched`，official daily wins finalized EOD
  - either side absent：`unavailable`
- GET／AI read只做 pure projection，不寫 observability。
- Existing official EOD refresh／startup catch-up在 transaction完成與repository reread後，才可透過既有 data-quality／dataset-health path記錄 mismatch；不得在 provider adapter或frontend寫警告。
- 電腦關機期間若未保存 session-close evidence，重開後只能如實 `reconciliation_status=unavailable`；不得用 official daily反造 realtime session-final lineage。

## Milestones

### PCF0 — Freeze contract and storage proof

- Scope：fixed-time fixtures、existing schema/upsert/raw-receipt cold-read audit、outward golden contract；不改production behavior。
- Acceptance：證明是否可在無migration下由既有row重建post-close confirmation；3711／TWSE與一檔TPEx fixture具完整lineage。
- Validation：repository／transaction idempotency、same-event later-receipt、restart readback、raw receipt append-only tests。
- Stop：若最新receipt linkage或confirmation time不可穩定重建，先提出最小additive migration與rollback，再進PCF1。

### PCF1 — Centralize phase taxonomy

- Scope：`trading_calendar.py`、shared `MarketSession`、public quote mapping、quote-depth與MIS normalized phase consumers。
- Acceptance：13:30～13:33只由calendar產生 `close_resolution`；market phase與instrument delayed state分離；所有consumer沒有第二套clock。
- Validation：13:24／13:25／13:30／13:30:00.001／13:32:59／13:33 boundaries、non-trading day、TWSE／TPEx tests。
- Stop：若新增phase造成provider route、freshness或existing active-session contract ambiguity，先修正taxonomy，不在consumer加alias workaround。

### PCF2 — Extend existing public quote Data Core path

- Scope：讓既有 descriptor／planner／acquisition／transaction／repository／Gateway 支援single-symbol close-resolution／post-close confirmation。
- Acceptance：最多1 symbol、1 call、10秒、0 retry、0 subscription；persist後mandatory reread；`cache_only`仍0 call；不新增第二個resolver／table／transaction owner。
- Validation：post-close route plan、timeout／HTTP／empty／trial、stale cache fallback、same-event idempotent upsert、out-of-order與volume regression tests。
- Stop：若一般 `quote.last_trade require_live` 被誤判為post-close live，分離requirement purpose／projection，不在consumer補判斷。

### PCF3 — Add resolved `quote.session_close` projection

- Scope：existing `tw.quote.snapshot` Registry/catalog capability mapping、public quote projection、quote-depth shared projection與Taiwan evidence bundle。
- Acceptance：session close與official close共存但不混用；post-close headline只採session-final evidence；previous official有明確trade date。
- Validation：capability advertised => projection、API schema、quote components、3711 golden fixture、cold cache read。
- Stop：若需建立新dataset或繞過Gateway才能輸出，退回調整existing projection boundary。

### PCF4 — Freshness and AI/MCP convergence

- Scope：Taiwan projection、capability contract、freshness-by-capability、decision envelope與MCP parity。
- Acceptance：session-close／official-daily兩套expected date與release state分開；HTTP／SSE／MCP同一backend evidence；consumer不重算。
- Validation：14:00 pending-release golden、stale-source masking regression、AI realtime/freshness/decision/MCP contract tests。
- Stop：任何previous official或stale intraday price再次成為今日headline即停止。

### PCF5 — Technical partial and official reconciliation

- Scope：technical intraday projection、official daily postcondition、data-quality／dataset-health observability。
- Acceptance：13:33～15:15 current partial可使用session final；completed仍停在前一official day；official arrival後matched/mismatched可見且official wins。
- Validation：provisional-close gate、completed rollover、mismatch、missing side、restart/catch-up tests。
- Stop：任何session close進入completed indicator history或GET產生write即停止。

### PCF6 — Regression and bounded acceptance

- Scope：targeted backend suite、safe backend profile、bounded live source/runtime acceptance。
- Acceptance：3711 592→605 case、任意非configured symbol、TWSE／TPEx、no-trade／suspended／unavailable、runtime cold reread與AI/MCP outward均通過。
- Validation：本文件「Validation matrix」與正式 launcher-selected API probes。
- Live bounds：每個venue各1 symbol、每symbol最多1 call、10秒、0 retry、0 subscription；不以fixed-slot configured universe作coverage proof。
- Stop：外部來源、授權、runtime identity或正式session window不成立時維持pending，不以fixture或晚場 evidence冒充live pass。

### PCF7 — Adoption and closure

- Scope：exact-scope staged validation、runtime adoption、source identity、API/MCP/technical smoke與rollback proof。
- Acceptance：正式launcher採用新source；post-close live sample與15:15後reconciliation按時間順序通過；existing F-07 active-session gate仍獨立記錄。
- Validation：source checkpoint、backend profile、launcher identity、readiness、representative API、MCP `omi.ask`、cold restart。
- Rollback：回退application build並保留兼容schema／raw receipts；不刪資料、不downgrade production DB作首選。

## Current authoritative execution order

原PCF0～PCF7保留為contract decomposition；以下CR0～CR8是2026-08-27 full audit後的實際修改順序。每個CR完成後必須更新`Progress.md`，前一項未通過不得進入有依賴的下一項。

### CR0 — Freeze audit baseline and ownership matrix

- Scope：鎖定dirty worktree、launcher-selected runtime、API outward、SQLite rows、EOD checkpoint、installed MCP snapshot與相關test baseline；不改production behavior。
- Acceptance：source/runtime/data三層證據可重現；所有先前completion claim依gate重新分類；不存在「source test passed = runtime adopted」描述。
- Validation：read-only endpoint、SQLite `mode=ro`、launcher/backend log、exact-file diff與targeted baseline tests。
- Stop：若runtime在實作期間被其他流程重啟或DB checkpoint前進，先更新baseline，不混用不同時間證據。

### CR1 — Converge the single phase owner

- Scope：只以`trading_calendar.py`與shared `MarketSession.CLOSE_RESOLUTION`為global phase truth；修正realtime platform、comparison、current-market requirement、instrument policy、AI finalizer、intraday contract與Taiwan projections的mapping／phase sets。
- Frontend：移除`taiwanMarketTime.ts`對session／release／holiday的業務fallback；backend calendar snapshot不可用時，只能進truthful unavailable／paused polling state，不自行猜13:30／15:15或休市日。
- Acceptance：13:31在calendar、Gateway requirement、quote-depth、source health、AI、technical、frontend polling都保留同一`close_resolution`；但instrument trial／delayed-close／tradability仍是獨立維度。
- Validation：13:24、13:25、13:30、13:31、13:32:59、13:33、non-trading day、exception calendar與frontend calendar-unavailable tests。
- Stop：任何consumer新增alias clock或把`close_resolution`一律當regular tradable／closing auction即停止。

### CR2 — Repair outward serialization and health truth

- Scope：在intraday outward boundary將point time規範成schema要求的ISO string；補FastAPI response-model regression。Source health分開raw snapshot availability、session-close readiness與official-daily release狀態。
- Quote-depth schema：決定並固定public `data_core_components`／acquisition diagnostics的typed exposure；不可讓response model靜默丟棄backend已計算的component evidence。
- Acceptance：`GET /api/market/intraday/3711`不再500；11:49 raw quote可標available history，但不可再標成completed-session current；session close unavailable必須獨立可見。
- Validation：router/TestClient response validation、source-health exact reason/status、quote-depth schema round-trip與OpenAPI contract tests。
- Stop：不得把time改成`Any`、吞掉validation，或以`is_after_close`直接把舊quote改成current。

### CR3 — Materialize session close through the existing acquisition path

- Scope：沿用`acquire_taiwan_quote_evidence_projection`、existing single-symbol planner／adapter／transaction／repository／Gateway；每個request只建立並共用一個acquisition adapter，避免quote refresh與session-close acquire重複provider call。
- Frontend：初次與必要的post-close reacquire走explicit bounded POST；失敗fallback可以保留cache-only GET，但必須透過既有更新狀態流程揭露結果，不能靜默假成功。
- Acceptance：任意registered symbol可在13:33後由post-resolution receipt materialize session final；GET維持0 provider I/O；不依賴fixed-slot configured universe。
- Validation：single-call assertion、post-resolution same-event confirmation、trial/date mismatch/out-of-order/volume regression、3711與TWSE／TPEx fixtures、cold reread。
- Stop：若需要第二個resolver／table／scheduler或GET side effect才能完成，退回既有Gateway／projection boundary修正。

### CR4 — Make every consumer use the same session-close component

- Scope：intraday不再以`selected_session == POST_CLOSE`自行推導completed-session close；technical、Taiwan AI projection、quote headline、chart today state只消費backend-owned`quote.session_close`與official-daily components。
- Acceptance：session close available時，headline與current partial使用同一price／trade date／lineage；unavailable時不得以11:49 quote或8/26 official close冒充今日；technical completed仍只使用official daily。
- Validation：14:00 golden case、cold-cache first request、AI decision/freshness、technical provisional-close、chart today與HTTP／SSE parity tests。
- Stop：任何consumer重新比較時鐘、猜finalization或自行選provider即停止。

### CR5 — Separate reconciliation from session-close ownership

- Scope：`_reconcile_session_close()`只增加`reconciliation_status`、official reference與mismatch limitations；不得把session-close的`official_daily`改為true或把`finalization`改成`official_daily_confirmed`。
- Acceptance：session-close永遠維持`session_final`／`official_daily=false`；official daily component獨立confirmed；matched／mismatched時official daily只在finalized EOD／technical completed層勝出。
- Validation：matched、mismatched、missing side、restart/catch-up與GET zero-write tests。
- Stop：若reconciliation需要新的storage owner或read path寫DB，先回到existing lifecycle／data-quality seam。

### CR6 — Repair the existing official EOD postcondition

- Scope：只修既有`market_eod_coverage_reconcile`、official TWSE／TPEx bulk ports、coverage checkpoint與job outcome；不新增第三套EOD scheduler。整理`market_daily_refresh`實際只刷新法人資料的命名／訊息，保留必要compatibility alias。
- Acceptance：job execution success與dataset outcome partial／stale分開；TWSE／TPEx provider fetch success不能取代universe postcondition；3711與full-market partition重新計算後一致。
- Validation：scheduler registration、job result semantics、two-venue max-call bound、provider partial publication、startup catch-up、coverage partition conservation與read-only outward projection。
- Stop：不得把`max_symbols=2`當兩支股票、不得在provider成功但postcondition partial時標healthy、不得建立新全市場collector。

### CR7 — Source regression and scoped runtime adoption

- Scope：完成exact-scope backend/frontend tests與safe validation；經使用者授權後才以existing launcher lifecycle採用source，再驗證selected endpoint、process lineage、API/schema、DB identity與frontend proxy。MCP只做installed adapter scoped reload／schema refresh，不改backend ownership。
- Acceptance：source fingerprint、runtime process start與endpoint outward一致；installed MCP `tools/list`實際包含`quote.session_close`；runtime不再回舊quote-depth schema。
- Validation：targeted pytest、backend profile、frontend lint/typecheck/build、launcher health/ready、representative GET/explicit bounded POST、MCP initialize/tools/list/tools/call。
- Stop：runtime identity、port、DB或MCP retained session不明時fail closed；不得用local snapshot檔代替loaded runtime proof。

### CR8 — Chronological live and visible acceptance

- Scope：在下一個可用台股交易日依實際時間順序驗證close resolution、post-close session final、official EOD reconciliation與可見UI；active-session F-07仍是獨立gate。
- Acceptance：
  - 13:30～13:33 candidate/resolving語意正確。
  - 13:33後TWSE／TPEx各一個bounded sample可讀session final。
  - 15:15前official current-day維持pending且previous official有日期。
  - official EOD到達後matched／mismatched與technical rollover正確。
  - 3711畫面「今日」可用，headline／圖表／technical／更新狀態與backend contract一致。
  - AI／MCP明確說明session close與official daily的不同finalization層級。
- Validation：dated API/MCP artifacts、SQLite readback、EOD checkpoint、browser DOM/screenshot、cold restart與rollback smoke。
- Stop：錯過對應session window即維持pending，不以晚間cache、fixture或unit test補證。

## Cross-phase stop-and-fix rules

- 任一階段發現需要新增Data Core、Resolver、session-close table、full-market collector或scheduler，先暫停並提出現有邊界無法承載的可重現證據與最小替代方案。
- 任一GET／cache-only read產生provider I/O、repair或DB write，立即停止。
- 任一previous official、stale intraday或trial evidence成為今日session-close headline，立即停止。
- 任一job／provider回傳success但dataset postcondition未成立仍對外標healthy，立即停止。
- 任一source test、HTTP 200、static snapshot或post-close replay被當成runtime／live acceptance，立即停止。
- 任一targeted test失敗先修正；只有可證明與本CR無關的既有dirty-worktree failure才可隔離記錄。

## Planned file boundaries

| Boundary | Expected change |
| --- | --- |
| `market/trading_calendar.py` | authoritative `close_resolution` phase |
| `market_data/contracts.py` | additive shared phase enum only if required |
| `market/providers/tw_public_quote.py` | existing descriptor post-close eligibility；parser仍只輸出canonical evidence |
| `market/public_quote_platform.py` | same-dataset session-final policy與projection |
| `market/public_quote_repository.py` | existing candidate read所需confirmation lineage；不選provider |
| `market/public_quote_transaction.py` | existing atomic upsert／raw receipt behavior；不新增transaction owner |
| `market_data/registry.py`、`market/tw_dataset_catalog.py` | `tw.quote.snapshot`增加projection capability mapping；不新增dataset |
| `market/quote_depth.py` | 移除local clock/finalization，改投影Data Core result |
| `market/taiwan_quote_evidence.py` | 同一bundle增加`quote.session_close` component |
| `ai/capability_contract.py` | outward capability schema |
| `ai/market_context/taiwan_projection.py` | headline、dual-axis freshness與limits |
| `market/technical_intraday_projection.py` | provisional close只接受session-final evidence |
| `market/daily_ohlcv_platform.py`／existing lifecycle | official read不變；只提供reconciliation input/postcondition seam |
| tests | phase、Gateway、persistence、projection、AI/MCP、technical、runtime regression |

禁止新增的檔案類型：新的session-close service、resolver、repository、transaction、provider transport、scheduler或DB table，除非PCF0以可重現contract test證明既有邊界無法承載，並先取得使用者確認。

## Validation matrix

Required focused tests：

- `test_twse_mis_observation.py`
- `test_taiwan_stock_quote_depth.py`
- `test_tw_quote_components.py`
- `test_tw_official_daily_platform.py`
- `test_public_quote_platform.py`／實際repo等價檔案
- `test_tw_public_quote_transaction.py`／實際repo等價檔案
- `test_tw_data_core_cold_read.py`
- `test_market_data_registry.py`
- `test_ai_realtime_contract.py`
- `test_ai_decision_envelope.py`
- `test_intraday_contract_remediation.py`
- `test_calendar_status_integration.py`
- `test_ai_freshness_guard.py`
- `test_technical_intraday_projection.py`

Required scenarios：

1. 13:24 regular actual last trade：不可為session final，即使時鐘已跨過13:33也不得升格。
2. 13:28 trial：不可成為actual/session close。
3. 13:30 actual match：close-resolution candidate。
4. 13:31 later valid trade：取代較早candidate，仍resolving。
5. 13:33 post-resolution confirmation：session final。
6. 14:00 session close current、official current-day pending、daily finalized仍前一日。
7. 15:15 official match：matched與completed rollover。
8. Official mismatch：mismatched、official wins、observability可見。
9. Trade-date mismatch、future/out-of-order、cumulative-volume regression：不得promotion。
10. No trade／no quote／suspended：維持不同狀態，不猜測。
11. Arbitrary 3711：不依賴configured capture universe。
12. TWSE／TPEx各一檔。
13. Non-trading day。
14. 13:30～13:33 calendar／Gateway／quote-depth／AI同一phase taxonomy。
15. Restart後cache-only session close仍可讀且external calls為0。
16. Session close unavailable時technical不得產生provisional close。
17. HTTP／SSE／MCP使用相同component status、price、trade date、lineage與limitations。

Implementation validation command由實作時按實際test filenames收斂，先跑targeted pytest，再跑：

```powershell
.\scripts\run-safe-validation.ps1 -Profile backend
```

Docs-only planning gate只做UTF-8讀回、link／structure檢查與`git diff --check`，不執行build或runtime smoke。

## Done criteria

- `quote.session_close` 只是一個既有 `tw.quote.snapshot` resolved projection，沒有第二套data architecture。
- 13:33後，bounded request取得的post-resolution authoritative evidence可持久化並在cold read重建session final。
- Session close必須來自13:30～13:33合法final-match／resolution event與post-resolution confirmation；13:24與其他舊cache不可promotion。
- Session close、latest completed official close與current-day official pending release同時truthful outward。
- Post-close headline不再使用stale intraday或previous official冒充今日close。
- Technical completed／current partial邊界正確。
- Official daily arrival後matched/mismatched可觀測，official daily維持final EOD owner。
- TWSE／TPEx與任意registered target不依賴fixed-slot capture universe。
- Existing Gateway、Resolver、Registry、repository、transaction、dataset與consumer ownership invariant持續由boundary tests保護。

## 2026-08-27 先前執行紀錄與audit reclassification

以下「已完成」只代表先前source intent與targeted regression紀錄。19:04 full audit後，PCF1、PCF3、PCF4、PCF5與PCF6均需按CR0～CR8重新驗證；在`runtime_adopted`、`post_close_live_accepted`、`official_eod_reconciled`與`http_ai_mcp_ui_accepted`完成前，不得標記`TW_SESSION_CLOSE_PRODUCTION_READY`。

### 已建立的source基礎

- PCF0：existing `taiwan_stock_quote_snapshot + raw_fetch_result` 可承載 finalization lineage；same-event post-close receipt 保留 2 筆 raw receipt、1 筆 quote row，cold read 可由最新 receipt 重建 `confirmed_at`，因此不新增 migration 或 table。
- PCF1：`trading_calendar.py` 成為 13:25／13:30／13:33 唯一 phase owner；`quote_depth`、MIS observation、canonical adapters、calendar status 與 technical report 共用相同 taxonomy。
- PCF2：post-close confirmation 沿用既有 single-symbol descriptor、acquisition executor、transaction、repository、Gateway 與 Resolver；bound 保持 1 symbol／1 call／10 秒／0 retry／0 subscription，persist 後 mandatory reread。
- PCF3：既有 `tw.quote.snapshot` 增加 `quote.session_close` projection；未新增 dataset、service、resolver、repository、transaction、scheduler 或 DB schema。
- PCF4：post-close headline 由 current-day session final 擁有；session close unavailable 時不以 previous official 或 stale intraday 冒充；AI capability/freshness 只投影 backend contract。
- PCF5：technical `current_partial` 只在 explicit session final 時成為 `provisional_close`；`completed` 仍只使用 official daily。Official daily 到達後可投影 `matched`／`mismatched`，且 official daily wins。
- PCF6 source regression：3711 592→605、TWSE／TPEx、trial／13:24／date mismatch rejection、13:30 candidate、13:31 resolving、13:33 final、volume regression、cold read zero I/O、generic post-close `require_live` zero I/O、AI／technical outward contract 已納入測試。
- 先前廣義source gate：`553 passed, 1 deselected, 284 subtests passed`。本輪收斂修正後的最終直接regression：`407 passed, 242 subtests passed`；frontend ESLint、TypeScript與production build通過。

### 尚未完成

- CR7 runtime adoption：未重啟目前OMI runtime，未對launcher-selected API／installed MCP loaded contract執行採用後probe。
- CR8 chronological acceptance：仍需在下一個可用台股交易日按13:30～13:33、14:00、15:15+完成3711、TWSE／TPEx、official reconciliation與可見「今日」UI驗收。
- Full-market official EOD production coverage仍可能為partial；CR6已修正錯誤success contract，但本輪未執行explicit provider repair，不會將source fix宣稱為data healed。
- Backend safe profile的compileall通過且full pytest跑到100%；2個失敗來自共享worktree未追蹤的US OHLC continuity tests，另有Windows basetemp cleanup `WinError 5`。本任務未越界修改那批US變更，也不宣稱full-repo green。
- F-07 active-session public-source live acceptance 維持獨立 pending；不得由本次 completed-session evidence 取代。
- Commit／push 未授權，未執行。
