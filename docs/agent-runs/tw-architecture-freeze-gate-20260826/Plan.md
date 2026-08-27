# 台股 Architecture Freeze Gate 實作計畫

## 狀態

- Program status：`SOURCE_FROZEN`
- Planning checkpoint：2026-08-26 17:52 +08:00
- Source implementation：FG1～FG6與FG9 source closeout通過；FG7～FG8等待runtime/live evidence
- Runtime adoption：本計畫尚未執行；prior task checkpoint不可替代新source adoption
- Official-session live gate：`PENDING`

## 執行原則

- 使用strangler / vertical slice；不做Shared Core big-bang rewrite。
- 每一work package先記錄current owner，再改最小seam，再跑targeted validation。
- 較晚gate不能覆蓋較早失敗；runtime pass不能覆蓋source failure，post-close不能覆蓋live-session gate。
- 每包保持localized diff與獨立rollback；不得以`git reset`、`checkout`或`stash`處理回退。
- 只有task-owned targeted tests通過才進下一包。

## Gate model

| Gate | 名稱 | 必要證據 |
|---|---|---|
| FG0 | Baseline | current truth、owner inventory、dirty worktree、durable capability read-only inventory |
| FG1 | Lifecycle contract | canonical IDs、registry/catalog/probe parity、DatasetHealth policy與architecture tests |
| FG2 | Consumer evidence | AI quote bundle、daily reader、valuation reader的真實vertical tests |
| FG3 | Read/command boundary | 全台股GET zero provider IO/commit/subscription；explicit command surfaces |
| FG4 | Freshness authority | Registry/lifecycle executable authority，AI/source health只做projection |
| FG5 | Sidecar classification | 所有outward sidecar有owner/status/refresh/lineage/limitation |
| FG6 | Cross-surface source | API/AI/MCP/frontend同一resolved truth，targeted suites與build全綠 |
| FG7 | Runtime adoption | named launcher identity、migration、direct/proxy/MCP/UI smoke |
| FG8 | Live acceptance | official-session KGI semantics、symbol switch、L5與zero-residual cleanup |
| FG9 | Freeze closeout | debt/allowlist縮減、exact manifest、未驗證項目如實保留 |

## Dependency map

```text
BASE-01
  -> LIFE-01 -> LIFE-02 -> LIFE-03
                 |          |
                 |          +-> AIQ-01 -> AIQ-02
                 |          +-> VAL-01 -> VAL-02
                 |
                 +-> GET-01 -> GET-02 -> GET-03
                 +-> FRESH-01 -> FRESH-02
                 +-> SIDE-01 -> SIDE-02

AIQ-02 + VAL-02 + GET-03 + FRESH-02 + SIDE-02
  -> CROSS-01
  -> EOD-01 (optional physical debt closure, only when risk budget allows)
  -> ADOPT-01
  -> LIVE-01
  -> CLOSE-01
```

## Phase 0 — Freeze baseline與durable identity inventory

Work package：`BASE-01`

範圍：

- 重讀所有預計touched files與existing diff。
- 保存Registry、Catalog、probe、candidate batch、AI dependency、GET route與sidecar inventory。
- 以read-only query確認user DB是否存在legacy capability identity；不修改schema/data。
- 固定本任務exact source manifest與forbidden boundary baseline。

Acceptance：

- 每個finding都有source/DB/test evidence與owner。
- `auction` durable identity是否存在有明確結果。
- 既有US/scheduler/frontend hunks已辨識，無法安全共存的file先標blocked。

Validation：source search、AST inventory、read-only DB query、task-doc update。

## Phase 1 — Lifecycle authority與capability vocabulary

Work packages：`LIFE-01`、`LIFE-02`、`LIFE-03`

範圍：

1. 統一`quote.order_book`與`quote.auction` canonical capability ID。
2. 新增depth/auction Shared DatasetSpec、TW catalog contract與storage/lineage probe。
3. 為intraday、depth、auction、current index、current breadth接market-owned lifecycle evaluator。
4. Registered production candidate batch必須提供non-null DatasetHealth。
5. TW applicability policy留在market layer；shared Gateway只轉送health。

Acceptance：

- Registry / catalog / descriptor / requirement capability集合exact parity。
- Cache missing、not applicable、partial、stale、future timestamp與healthy都有deterministic DatasetHealth。
- Dataset health與Resolved health不互相代替。
- 若需要alias/migration，upgrade/downgrade在disposable DB通過。

Validation：dataset registry/catalog/health、Gateway、realtime、intraday、current market、migration與architecture suites。

## Phase 2 — Canonical Taiwan quote evidence bundle

Work packages：`AIQ-01`、`AIQ-02`

範圍：

- 新增market-owned typed bundle，編排quote/depth/auction/official close的cache-only resolved reads。
- Bundle保留每個component自己的`MarketDataResultV1`、provider health、dataset health、resolved health、lineage與limitations。
- Explicit acquisition由獨立command/operation執行；read API不接受`allow_acquisition`或mutation flag。
- AI dependency改注入bundle reader/acquirer，不再只讀public last trade後推測depth/auction。
- Capability contract做真實vertical test，而非直接注入完整synthetic projection payload。

Acceptance：

- `quote.order_book` / `quote.auction`在有canonical rows時能由AI outward返回真實resolved evidence。
- Missing/NA/partial component不污染其他component。
- Trial/auction永遠不能成last trade；official close只來自completed official/daily owner。
- AI/MCP不importrealtime stream或provider manager。

Validation：AI context、capability contract、outward contract、MCP schema、quote/depth/auction persistence與projection tests。

## Phase 3 — Daily research與Portfolio valuation boundary

Work packages：`VAL-01`、`VAL-02`

範圍：

- 建立market-owned latest daily/official-close projection seam，重用既有daily platform與repository。
- AI Taiwan context改用reader port，不再呼叫legacy raw ORM service。
- 定義provider-neutral`ValuationPriceReader` / result contract，至少包含price、as_of、market、source/provider、selection reason、health與limitations。
- Portfolio context只組合Account Plane position/cost/cash與valuation results，不持有quote→daily fallback或ORM model mapping。
- Regional market implementation可分階段接入，但consumer interface一次固定；不在TW package重寫US/JP/KR providers。

Acceptance：

- `backend/app/ai/`與Portfolio context沒有market price model direct query/import。
- Unknown price/cost不轉0；stale/partial/market-closed semantics outward可見。
- TW current quote、official close與daily fallback由market policy/Resolver決定。

Validation：AI Taiwan context、portfolio context、valuation contract、daily platform、official close與boundary tests。

## Phase 4 — GET read-only與explicit command closure

Work packages：`GET-01`、`GET-02`、`GET-03`

範圍：

1. 建立actual GET side-effect inventory與runtime sentinel。
2. Market chips、institutional、margin、shareholding、revenue、financials、overnight impact移除GET refresh ownership。
3. Legacy query flags改成忽略、410/409或compatibility warning；不得執行IO/mutation。
4. Futures latest/intraday GET改cache-only，consumer provider參數不得控制production selection。
5. Institutional holding ratio改為cache reader + explicit bounded refresh；再依classification決定是否canonical persistence。
6. Frontend/MCP若仍以GET refresh，改呼叫explicit command或shared status flow。

Acceptance：

- 所有台股GET在provider/commit/subscription sentinel下external calls=0、commits=0、leases=0。
- POST/job/lease具有bounds、timeout、provider lineage、結果摘要與truthful failure。
- Router、frontend、AI、MCP不指定provider。

Validation：route inventory、API contract、provider monkeypatch sentinel、DB commit spy、frontend fetch search、targeted suites。

## Phase 5 — Lifecycle / freshness authority convergence

Work packages：`FRESH-01`、`FRESH-02`

範圍：

- Shared Registry + dataset lifecycle成為executable dataset authority。
- TW Catalog保留market inventory、owner、projection與limitations；以parity guard防漂移。
- `TAIWAN_DATASET_SPECS`降級為compatibility projection或由canonical specs產生，不再獨立決定freshness。
- Source health只描述provider/source/storage訊號；AI freshness只投影dataset/resolved health。
- `tw_dataset_health.py`名稱/contract需清楚區分storage-lineage probe與完整DatasetHealth。

Acceptance：

- 同一dataset expected date、eligibility、frequency、freshness rule只有一個executable owner。
- Provider/Dataset/Resolved health仍分層。
- AI/source health不存在對platform-owned price dataset的raw freshness SQL重算。

Validation：freshness、source health、dataset lifecycle、AI context、catalog parity與architecture guards。

## Phase 6 — Sidecar classification與anti-debt guards

Work packages：`SIDE-01`、`SIDE-02`

範圍：

- 對disposition、corporate events、ETF、futures/derivatives、institutional holding ratio逐項指定：dataset ID、owner、convergence status、read/refresh operation、storage/lineage、health與limitations。
- 若未canonicalize，必須明示`COMPATIBILITY`、`LINEAGE_GAP`或等效noncanonical狀態；不可假裝platform-owned。
- 建立guard：新增outward台股dataset/route時，必須在catalog或explicit exemption registry出現。
- 不建立generic JSON blob平台；migration只服務明確typed/replay需求。

Acceptance：

- 每個sidecar都可回答「誰讀、誰refresh、是否IO、是否persist、health在哪、AI可否決策使用」。
- Institutional holding ratio GET不再direct provider IO。
- Futures GET provider-neutral、read-only；legacy transaction debt被明確列出或收回transaction owner。

Validation：catalog/health/route inventory、sidecar targeted tests、architecture guard與migration tests（若有）。

## Phase 7 — Optional EOD transaction physical closure

Work package：`EOD-01`

只有FG1～FG6全部通過且risk budget允許才執行。

範圍：

- 把`market_data/eod_coverage.py`的commit/rollback移至explicit transaction port/owner。
- 保留full-market EOD lifecycle、repair state、TW/US既有語意與outward API。
- 縮減cp0 transaction debt allowlist。

Acceptance：shared lifecycle module不直接commit/rollback；repair成功/失敗/重試狀態與bounds無regression。

Stop：若需要順便重寫scheduler、US EOD或coverage schema，延後此包，不阻塞TW P0/P1 freeze。

## Phase 8 — Cross-surface source gate

Work package：`CROSS-01`

必要證據：

- Backend targeted integration、compileall、architecture guards。
- API/AI/MCP同一resolved fixture與limitations。
- Frontend ESLint、TypeScript與production build（只有touched frontend時必須）。
- Disposable migration upgrade/downgrade/re-upgrade（只有新增migration時）。
- `git diff --check`、UTF-8/JSON/Markdown readback、exact task-owned manifest。
- Staged files仍為0，除非使用者另行明確要求。

## Phase 9 — Runtime adoption與official-session acceptance

Work packages：`ADOPT-01`、`LIVE-01`、`CLOSE-01`

順序：

1. 使用者明確授權後，component-scoped launcher restart/adoption。
2. 驗證launcher-selected endpoint/interpreter/project root/migration revision。
3. Direct API、frontend proxy、MCP與visible UI parity。
4. 新source identity下依時間完成Preopen、Opening、Regular、Closing Auction、symbol switch、L5、duplicate/trial/cumulative與cleanup。
5. 未取得合法session evidence維持pending，不用其他時段補造。

## Stop-and-fix rules

- 若shared generic core出現provider/TW session名稱，停止並把policy退回market layer。
- 若Gateway開始自行推算dataset freshness/applicability，停止；health應由market lifecycle提供。
- 若evidence bundle合併component lineage/health，停止並恢復componentized contract。
- 若AI/Portfolio仍有market price ORM direct query，consumer package不得標complete。
- 若GET觸發IO/commit/subscription，即使default為false也不得標complete。
- 若provider adapter出現commit/rollback或跨provider fallback，停止並修復owner。
- 若legacy capability durable identity存在，不direct rename；先做alias/migration決策。
- 若unknown/missing/partial/indicative變成0、actual trade或decision-ready，立即停止並加regression。
- 若task-owned test失敗，先修正，不跨package累積。
- 若failure屬unrelateddirty work，保留evidence並隔離，不修改無關模組。
- 若runtime identity或migration不明，不宣稱adopted。
- 若錯過official session，live gate維持`PENDING`。

## Phase 10 — Final architecture closure

Work packages：`FINAL-01`～`FINAL-06`

順序：

1. `source_health.market_daily_price`改讀canonical daily lifecycle owner，不移動compatibility長尾。
2. disposition cache semantics集中到TW market policy；unknown/malformed一律fail closed。
3. 以explicit `auction_type`接通continuous disposition intraday auction，transaction與repository皆做type guard。
4. 將generic storage probe outward名稱固定為`platform-evidence`；舊`health`只保留deprecated alias。
5. Quote bundle提供requested/acquired/materialized scope，並在market boundary正式轉譯`quote.snapshot`與內部`quote.last_trade`。
6. 先跑focused regression，再跑Shared Core/realtime/intraday/current market/AI/boundary整合；最後更新exact hash checkpoint與source freeze artifact。

Acceptance：

- daily freshness只有一個executable owner，source health不再對同表重算。
- disposition未知不可產生continuous semantics或研究可用analysis basis。
- normal continuous不得看到opening/closing auction；active disposition可persist/reread intraday auction。
- platform storage evidence與lifecycle health不再同名混淆。
- AI只要求`quote.snapshot`時只取得quote resource，不暗中刷新depth/auction。
- Source gate通過仍只代表source closure；ADOPT-01與LIVE-01保持獨立。

## Rollback model

- Source：只反向修改task-owned hunks；不使用reset/checkout/stash。
- Contract：先additive reader/command/alias，再切consumer，最後移除legacy owner。
- DB：只在disposable copy演練；user DB migration需明確授權與named launcher adoption流程。
- Runtime：只用既有launcher component lifecycle；保留before/after identity evidence。
- Live：cleanup與compare/off復原是gate的一部分；active handles非0不算成功。

## Planning decisions

- 2026-08-26：建立獨立freeze-gate task，不改寫前一輪source-convergence歷史。
- 2026-08-26：Registry/lifecycle為executable authority；TW catalog為market inventory/projection，不新建第三套registry。
- 2026-08-26：Quote evidence bundle採componentized results，不做單一merged health/lineage。
- 2026-08-26：read與acquire使用不同entrypoint；不以boolean flag隱藏side effect。
- 2026-08-26：P0/P1先完成；EOD physical cleanup為條件式P2 package。
