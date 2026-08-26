# 實際架構圖與 Owner Map

## Current truth 的共同主幹

```text
Provider / Integration
        -> Canonical Observation
        -> Resolution / Control Plane
        -> Market / Research Service
        -> AI / API
        -> Frontend / MCP / external consumer
```

這條依賴方向已存在，但目前只有部分 TW capabilities 完成 production adoption。

## 已收束的 public quote vertical slice

```text
AI / API explicit requirement
        -> PublicQuotePlatform
        -> MarketDataGateway.resolve_quote
        -> TWSE MIS market-owned descriptor
        -> MIS acquisition adapter
        -> PublicQuoteTransaction
           -> SourceRegistry + RawFetchResult + TaiwanStockQuoteSnapshot
        -> TaiwanPublicQuoteRepository reread
        -> shared resolve_quote
        -> TW projection / resolved health
```

限制：repository與transaction source defaults目前是 MIS-specific，因此這是已成立的單 provider vertical slice，不是 KGI-ready multi-provider quote platform。

## Current legacy KGI / quote-depth path

```text
Frontend hook
  |-- polling GET quote-depth?refresh=true
  |-- POST/PATCH/DELETE KGI lease
  `-- KGI realtime SSE
        -> routers/market.py
             |-- direct kgi_superpy manager
             `-- quote_depth.py
                   |-- KGI snapshot / stream cache
                   |-- TWSE MIS direct HTTP fallback
                   |-- circuit breaker + selection
                   |-- canonical shadow only
                   |-- TaiwanStockQuoteSnapshot upsert + commit/rollback
                   `-- legacy projection
```

實際 owner：`quote_depth.py` 與 KGI provider manager，而不是 Shared Gateway / repository / Resolver。

## Current intraday bars path

```text
GET trend / GET history / frontend chart polling
        -> intraday.py
             |-- NStock direct fetch
             |-- Yahoo direct fallback/fetch
             |-- local 1m -> 5m aggregation
             `-- MarketIntradayBar upsert + commit
        -> projection

Current actual trade（已分離）
        -> PublicQuotePlatform
```

正確成果：MIS quote不再偽裝 bar，current quote不應回填歷史 bar。

剩餘 owner debt：provider priority、URLs、IO、transaction、lineage與derived metadata仍在 service；trend GET與history GET都可能有 side effects。

## Current index / breadth path

```text
GET /indices/summary
        -> cache-only summary assembly
        -> attach completed official Shared Data Core evidence

POST refresh job
        -> indices.py legacy current-session orchestration
             |-- Yahoo
             |-- TWSE / TPEx official resources
             |-- TWSE MIS
             `-- local DB fallback

GET /indices/{index_id}/intraday
        -> indices.py prefer_live orchestration
        -> provider IO is still possible
```

Completed-session official index / breadth與current-session provisional observations已有語意分離；不能把 current path硬塞回 completed capability。

## Current quality paths

```text
DataRequirementV2.quality
        - required_fields
        - minimum_authority
        - allow_partial
        -> [目前沒有中央 consumer]

Candidate
        -> Resolver現有 checks
             - policy / cache-vs-live
             - observation missing
             - future timestamp
             - freshness / session-specific completed check
        -> selection / ResolvedEvidenceHealth

AI outward quality contract
        -> answer/data availability semantics
        -> 不是 candidate eligibility 的替代品
```

public quote reader內的 required-field check屬 capability-specific reader validation，不能取代 shared quality policy。

## Current realtime control primitives

```text
market_data/control_plane.py + research_lease.py
        -> provider-neutral request-scoped bounded acquisition
        -> owner token / poll / cancel / release / cleanup evidence

routers/market.py -> kgi_superpy manager
        -> persistent frontend viewer heartbeat / stream lifecycle
```

兩者可共用 bounded ownership primitives，但 public viewer lifecycle仍需 market-owned application seam；目前不能宣稱已統一。

## Target seams（不建立第二套 core）

```text
GET consumer
  -> cache-only DataRequirementV2
  -> MarketDataGateway
  -> candidate reader
  -> shared quality eligibility
  -> existing Resolver
  -> TW projection

Explicit POST/job/lease intent
  -> market-owned capability / realtime platform
  -> shared descriptor plan + bounds
  -> pure provider adapter
  -> raw receipts + canonical observations
  -> explicit transaction owner
  -> repository reread
  -> shared quality eligibility
  -> existing Resolver
  -> TW projection
```

## Layer ownership table

| Layer | Current owner | 應保留 | 需搬移／補齊 |
|---|---|---|---|
| Canonical contracts | `market_data/contracts.py` | quote/depth/auction/bar/index/breadth/status semantics | 不改 KGI-specific semantics；補 eligibility integration |
| Provider planning | `market_data/provider_catalog.py` | neutral descriptors、health與bounds | market-owned KGI/NStock/Yahoo/current descriptors；minimum authority eligibility |
| Application Gateway | `market_data/gateway.py` | bars/quote reread與bounds pattern | depth/auction typed ports；current acquisition wiring |
| Resolution | `market_data/resolution.py` | existing selection與health projection | 接受 shared eligibility/rejection，不重寫 ranking |
| TW public quote | platform/transaction/repository | MIS vertical slice與raw receipt pattern | repository/transaction generalize成合法 multi-provider candidates |
| KGI realtime | KGI manager + quote_depth | provider implementation與pure converter | public lifecycle、selection、transaction搬到 market/shared seams |
| Intraday bars | `market/intraday.py` | quote/bar分離、5m derived capability | provider planning、IO、transaction、lineage、GET side effects |
| Current index/breadth | `market/indices.py` | TW session/universe/finalization interpretation | provider orchestration、fallback、GET side effects |
| Completed official | existing platform-owned capabilities | 全部保留 | 只加 regression guards |
| AI / MCP / frontend | consumers | intent與presentation | 移除 refresh-through-GET、direct provider lifecycle與重建 quality semantics |

## P2 migration order

1. company profile reader / projection seam。
2. intraday bars lineage（同 Phase 5）。
3. minute / stock intraday derived component lineage。
4. high-decision-impact chips / fundamentals compatibility datasets。
5. ETF snapshot / NAV / PCF / iNAV lineage gaps。
6. futures / options / derivatives lineage gaps。

順序依 decision impact、現有 owner seam與資料污染風險調整；不以一次全搬為完成條件。

## BAR-01 current owner map（2026-08-26）

```text
GET /market/intraday/{stock_id}
  -> intraday.get_intraday_trend
  -> intraday._load_intraday_trend_uncached
  -> hardcoded NStock fetch
  -> exception / empty fallback to hardcoded Yahoo fetch
  -> intraday._upsert_market_intraday_bars
  -> db.commit

GET /market/intraday/{stock_id}/history?refresh=true (default)
  -> intraday.get_market_intraday_history
  -> hardcoded Yahoo fetch
  -> optional local 1m -> 5m aggregation
  -> intraday._upsert_market_intraday_bars
  -> db.commit
  -> direct ORM reread / projection
```

現況 ownership 結論：

- `intraday.py`同時持有兩個provider URL、HTTP、parsing、primary/fallback、persistence transaction、cache與projection。
- `MarketIntradayBar.provider`在legacy upsert固定寫`yahoo_finance_chart`，即使實際source是NStock，確認存在provider identity污染風險。
- `MarketIntradayBar`沒有SourceRegistry / RawFetchResult連結；現有row不能由storage證明raw lineage。
- trend GET與history GET皆可能external IO + commit；frontend professional history仍傳`refresh=true`。
- 已有使用者dirty hunk移除MIS偽bar與quote volume回填；BAR packages必須保留這些刪除，不恢復舊混源行為。

BAR target ownership：

```text
GET /intraday...
  -> cache-only TW intraday platform
  -> Shared Gateway -> repository -> Resolver -> projection

POST /intraday.../refresh
  -> provider-neutral requirement + bounds
  -> descriptor-planned NStock/Yahoo acquisition
  -> pure adapters + raw receipts
  -> explicit transaction owner
  -> repository reread -> Resolver
```

## BAR-01～BAR-04 realized owner map（2026-08-26）

```text
GET /intraday/{stock_id}[/history]
  -> intraday compatibility projection
  -> tw_intraday_platform cache-only requirement
  -> Shared Gateway -> canonical repository -> quality -> Resolver

POST /intraday/{stock_id}/history/refresh
  -> tw_intraday_platform bounded live requirement
  -> shared descriptor plan
  -> NStock / Yahoo pure adapter
  -> raw receipt + canonical bars
  -> explicit transaction owner
  -> repository reread -> quality -> Resolver -> TW projection
```

Ownership已確認：provider priority只在market-owned descriptors；adapter不commit；GET不IO；4h derived lineage保留component raw IDs。`intraday.py`只保留既有TW disposition、quote/bar分離與compatibility projection語意。

## IDX-01～IDX-02 realized owner map（2026-08-26）

```text
GET index summary / intraday
  -> indices.py compatibility projection
  -> tw_current_market_platform cache-only requirement
  -> Shared Gateway -> typed repository -> quality -> Resolver

POST summary refresh
  -> market-owned current capability descriptors
  -> descriptor-planned MIS / Yahoo candidate adapters
  -> raw receipt + typed current index/breadth observations
  -> explicit transaction owner
  -> repository reread -> quality -> Resolver -> TW projection
```

- `market.index.snapshot`與`market.breadth.current`不覆蓋completed official datasets。
- TAIEX/TPEX、TWSE/TPEX venue與provisional/finalization semantics分開。
- breadth保存universe、classified、unknown、not_received、received_unclassified、coverage、decision usability與limitations；unknown不補0。
- current-session provider URL、HTTP、parser與circuit已分別移到`providers/twse_mis_current_index.py`、`providers/yahoo_current_index.py`與`providers/twse_mis_current_breadth.py`；`indices.py`不再持有current acquisition helper或cross-provider selection。
- StockMaster registered universe由`tw_current_market_operations.py`讀取後注入breadth provider；provider module無DB/transaction ownership。

## TAIL-01～TAIL-03 realized owner map（2026-08-26）

```text
AI company context
  -> injected market-owned company profile reader
  -> cache-only StockProfile + SourceRegistry/RawFetchResult validation
  -> market projection

current index/breadth + component stock rows
  -> minute/stock derived state transaction
  -> component raw IDs + sources + event times + skew + calculation version
  -> legacy missing lineage => partial / not decision-ready
```

長尾剩餘owner與排序見`MigrationOrder.md`；沒有建立generic JSON blob platform，也沒有把compatibility refresh owner宣稱成fully converged。

## Source完成後的剩餘邊界

- shared core沒有KGI/MIS/Yahoo/NStock imports；provider specifics留在market-owned descriptors/adapters。
- router不再direct import KGI provider manager或legacy `kgi_market_data`；explicit KGI maintenance backfill經market-owned operation seam。
- `quote_depth.py`只保留Shared Core cache-only read、TW semantics與stable compatibility projection；capture/replay已搬到`quote_contract_capture.py`，provider IO/fallback/direct persistence已清除。
- realtime stream為明示presentation-only telemetry；canonical research truth仍走raw receipt、transaction、repository reread、central quality與Resolver。
- runtime、user DB migration、external provider、KGI entitlement與official-session live evidence均尚未建立，不能由source map推論完成。
