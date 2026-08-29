# US Market Data Architecture Map

## 文件定位

- 本文件是本長專案的架構地圖，不是 production completion 證明。
- Snapshot：2026-08-25，branch `codex/tw-etf-provider-normalization`，HEAD `6d508c7021c1050680262ce4a83f5b33e9f5eda7`。
- Source audit 時 worktree 有 41 個 modified／untracked entries；所有後續工作必須與既有台股 Foundation、美股 OHLCV 與 M5 工作共存。
- 使用者附件是 proposal／integration input；repo current truth 與實際 source/runtime evidence 優先。

## 1. 現況地圖

### 1.1 已存在但尚未統一成 production owner 的資產

```text
app.us_market.market_data_policy
  -> market-owned Yahoo / AlphaVantage descriptors
  -> build_us_acquisition_plan()

app.us_market.providers.canonical
  -> pure Yahoo / AlphaVantage canonical conversion

app.market_data.control_plane + resolution
  -> bounded acquisition / pure resolver primitives

app.us_market.resolved_reads + market_data_projection
  -> cache-only resolved daily read / provider-neutral projection seam

app.us_market.market_data_shadow + market_data_canary
  -> off / shadow / compare / canary scaffolding
```

這些資產代表新路徑已有基礎，但不代表 production consumer 已全部切換。

### 1.2 目前仍在 legacy production ownership 的路徑

```text
Frontend / Router / AI / Scheduler
            |
            | provider or provider="auto"
            v
app.us_market.service
  -> Yahoo IO
  -> on failure AlphaVantage IO
  -> service-local fallback / source status / refresh decision
  -> USDailyPrice / chart projection / legacy outward payload
```

主要問題：

- `app.us_market.service` 同時擁有 provider IO、fallback、refresh、部分 persistence orchestration 與 outward compatibility。
- Public US route與Frontend仍存在 provider control input。
- AI planner/executor仍可把 provider selection帶進US tool path。
- `app.market_data.eod_coverage` 反向 import US legacy service，Shared layer知道Yahoo acquisition implementation。
- Dirty OHLC priority repair/scheduler將pure continuity policy與Yahoo-specific acquisition綁在一起。
- New Control Plane／Resolver大多仍是source／test／shadow資產，不是唯一production truth path。

## 2. 目標地圖

```text
Yahoo / AlphaVantage / future KGI US
        |
        v
US Provider Ports + Adapters
  - IO / auth / parsing / error normalization
  - Canonical conversion
  - no fallback / no transaction ownership
        |
        v
Shared Market Data Core
  - DataRequirementV2 / RefreshRequirementV1
  - ProviderCapabilityDescriptorV2 registration
  - cache-first Gateway / bounded acquisition
  - Candidate repository ports / transaction owner
  - Resolver / fallback / freshness / health / lineage
  - Dataset Registry / operation dispatcher / postcondition
        |
        v
MarketDataResultV1 / Resolved Evidence
        |
        v
US Market Policy + Stable Projection
  - premarket / regular / after-hours / early close
  - US symbol / venue / price-basis / corporate-action limitations
        |
        v
Research / API / AI
        |
        v
Frontend / MCP / Kuro
```

## 3. Ownership 地圖

| Layer | Long-term owner | Inputs | Outputs | Forbidden ownership |
| --- | --- | --- | --- | --- |
| Provider IO | `app.us_market.market_data.adapters`／provider ports | bounded acquisition request | provider-coherent Canonical candidates | fallback、selection、commit、AI/market decision |
| Provider catalog | `app.us_market` | provider capability facts | descriptors／factories | external IO、selected provider result |
| Shared Core | `app.market_data` | requirements、descriptors、candidate ports | resolved evidence、health、acquisition summary | US session projection、SEC/FINRA interpretation |
| Candidate persistence | explicit transaction-owning repository/service | canonical provider batch | persisted candidate readback | fallback、resolved truth |
| US policy/projection | `app.us_market` | resolved evidence | stable US typed projection | provider acquisition、cross-provider fallback |
| Research | shared research + US profile | resolved OHLCV／quote | versioned technical/research result | provider IO、freshness reconstruction |
| API/AI | router／decision core | requirement intent／resolved projection | stable outward contract | provider priority、session/freshness guessing |
| Frontend/MCP/Kuro | consumers | stable outward data | UI/workflow/presentation | provider selection、repair planning、market truth |

## 4. 資產處置地圖

| Current asset | Planned disposition | Removal gate |
| --- | --- | --- |
| `app.us_market.market_data_policy` | 保留market-owned descriptor facts；依final Core contract改成正式registration input | G0 contract verified |
| `app.us_market.providers.canonical` | 保留pure conversion；逐步包進正式adapter/port | fixture parity passed |
| `app.us_market.resolved_reads` | 保留cache-only seam；改由final Gateway／candidate repository contract供應 | Daily resolved cutover passed |
| `app.us_market.market_data_projection` | 保留並收斂為stable US projection | API/AI/frontend parity passed |
| `app.us_market.market_data_shadow/canary` | 保留rollout能力；調整為per-capability evidence | production `on` + rollback rehearsal |
| `app.us_market.service` | Strangler拆出IO、persistence、policy與compatibility；最後只留US domain service或移除legacy branch | 所有product callers inventory為0 |
| `app.us_market.price_store`／`USDailyPrice` | 優先沿用provider-coherent candidate store；若lineage不足另提additive migration | DB contract + restart readback passed |
| `app.market_data.eod_coverage` direct US service import | 改成Dataset Registry operation binding／US market callback | Refresh lifecycle cutover passed |
| Public provider selectors | product route移除；必要provider audit移到diagnostic/admin | caller inventory + deprecation window passed |
| Frontend local technical math | 正式research series改為backend authority；local overlay須明示scope | golden-series cross-surface parity passed |
| `app.us_market.market_data` Pre-Core package | 已建立descriptors、pure adapter aliases、truthful candidate read、projection與G0-disabled manifest | G0後建立final binding；不得先接production |

## 5. Gap 與 work package 對照

| Gap ID | Gap | Current status | Work package |
| --- | --- | --- | --- |
| US-GAP-01 | 新增consumer仍可指定provider | guarded；Frontend已歸零，legacy API/AI allowlisted | A1 passed；E1/E2待G0 |
| US-GAP-02 | `service.py`擁有Yahoo→AlphaVantage fallback | open／G0 blocked | B1/B2 Core binding與Daily cutover、F2 Legacy removal |
| US-GAP-03 | Control Plane沒有production US port caller | manifest ready；production binding disabled | B1 US bindings／ports |
| US-GAP-04 | Daily reads仍可自行挑`USDailyPrice.provider` | open／G0 blocked | B2 Daily resolved read |
| US-GAP-05 | Repair/scheduler hardcode Yahoo | priority audit mitigated；legacy diagnostic/full-market仍open | C1 Dataset operation binding、C2 Scheduler cutover |
| US-GAP-06 | `eod_coverage`反向依賴US service | named debt guarded；open | C1 Lifecycle inversion |
| US-GAP-07 | Intraday outward semantics仍綁Yahoo | open／G0 blocked | D1 Quote/intraday Core path |
| US-GAP-08 | AI context仍有provider compatibility control | named debt guarded；open | E2 AI/MCP cutover |
| US-GAP-09 | Frontend傳provider並計算正式technical math | provider selector closed；technical authority open | E3 Frontend/research convergence |
| US-GAP-10 | Source-ready與runtime-adopted尚未閉環 | source-only；runtime未重啟驗證 | F1 Cutover runbook／runtime evidence |

## 6. 台股 Core 依賴地圖

US正式接線只依賴Shared Core public seam，不依賴`app.market`實作：

| US need | TW umbrella expected evidence |
| --- | --- |
| `DataRequirementV2`／Gateway | TW AcceptanceMatrix B-01、B-03、B-04 passed |
| `ProviderCapabilityDescriptorV2` registration | B-02 passed；TW catalog證明market-owned injection |
| Stable typed result／Resolver ownership | B-05、B-06、B-07 passed |
| Dataset operation dispatcher／postcondition | E-01、E-02、E-04 passed |
| Consumer-neutral outward semantics | F-01、F-02、F-03 passed |
| Rollout／runtime adoption model | G-02、G-03、G-04 passed |
| Production reference closure | TW task label `TW_MARKET_DATA_PLATFORM_PRODUCTION_CONVERGED` |

若TW側改名、改module或contract version，US只更新binding與本任務文件；不得建立US compatibility clone來模擬舊介面。

## 7. 明確排除的平行架構

- 不新增US-only Resolver、Control Plane、Dataset Registry或health model。
- 不從`app.market_data` import `app.us_market.service`。
- 不讓US adapter先fallback後只交一筆candidate給Core。
- 不用Frontend／AI provider selector保留「暫時可用」production路徑。
- 不把SEC／FINRA／FRED的authority semantics硬塞進quote/OHLC provider catalog。
- 不以一次大搬移`service.py`取代per-capability cutover。

## 8. G0與後續cutover前重新驗證

- Public provider selector是否有repo外consumer。
- `USDailyPrice`與相關source/raw tables是否足以保存final Core lineage、quality、finalization與price basis。
- 台股Core final module/type/version與registration方式。
- 現有rollout flag是否可真正per-capability rollback，或需additive registry。
- Yahoo／AlphaVantage quota、rate-limit與historical coverage的當下實際限制。
- KGI US entitlement、sessions與capability；未驗證前維持unavailable／planned，不advertise。
