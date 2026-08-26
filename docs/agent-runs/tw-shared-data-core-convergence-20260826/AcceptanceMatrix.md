# 架構確認矩陣

## 2026-08-26 source convergence recheck

| 目標 | Source狀態 | 證據／剩餘限制 |
|---|---|---|
| Central QualityRequirement executable | PASS | shared evaluator + Gateway/Resolver integration執行required fields、authority、partial、lineage與timestamps；rejections進health/limitations。 |
| Gateway depth / auction typed wiring | PASS | typed reader/acquisition/transaction ports、bounds、mandatory reread與existing Resolver。 |
| KGI quote/depth/auction Shared Core | PASS_SOURCE | market-owned descriptors/adapters、typed storage、raw receipt與multi-provider repository；live entitlement未驗。 |
| Provider-neutral realtime lease | PASS_SOURCE | router走market-owned lease/stream platform；owner token、symbol switch、cleanup由tests保護；live residual未驗。 |
| quote-depth GET boundary | PASS_SOURCE | public function固定cache-only且無provider IO/commit/subscription；capture/replay已移到獨立owner，legacy provider/persistence helpers已清除。 |
| Intraday bars convergence | PASS_SOURCE | NStock/Yahoo descriptor plan、0070 raw/derived lineage、GET cache-only、explicit POST refresh。 |
| Current index/breadth convergence | PASS_SOURCE | independent capabilities、0071 typed storage、raw lineage、unknown/coverage語意、GET cache-only；current provider IO已移到market-owned provider modules。 |
| Company profile seam | PASS_SOURCE | AI只使用market-owned reader port，不再direct query `StockProfile`。 |
| Derived state lineage | PASS_SOURCE | 0072保存component raw IDs/source/event/skew/calculation version；legacy missing lineage fail closed。 |
| Cross-surface source parity | PASS_SOURCE | API/AI/MCP/architecture regression通過；running runtime與visible UI parity未驗。 |
| Named runtime adoption | PASS | 2026-08-26 16:29正式launcher component-scoped restart；new listener lineage、repo venv/project root、compare、health/ready、frontend/MCP、Data Core catalog、Alembic 0072與zero baseline均通過。 |
| M5 official-session semantics | PENDING | post-close planner正確拒絕subscription，不能冒充readiness或session pass；仍需要新source identity的Preopen/Opening/Regular/Closing與real KGI evidence。 |

目前catalog實際數量：9 `PLATFORM_OWNED`、7 `COMPATIBILITY`、12 `LINEAGE_GAP`、2 `COMPATIBILITY_DERIVED`。後兩者已有component lineage，但仍保留compatibility狀態，避免把refresh/owner debt隱藏掉。

## 初始稽核基線（歷史）

下表記錄開始實作前的checkout，用來對照改善；其中`VERIFIED`表示當時缺口確實存在，不代表現在仍未修正。

狀態定義：

- `VERIFIED`：current source / tests 可直接證實。
- `PARTIAL`：方向成立，但敘述需要補充或尚缺 runtime evidence。
- `ADDED`：原文件未列，但同一 invariant 下實際存在的缺口。
- `PENDING`：不能由本次 source-only audit 證實。

| ID | 狀態 | 實際證據與判斷 |
|---|---|---|
| P0-1 KGI quote/depth/auction 未 onboarding Shared Core | VERIFIED | `market/quote_depth.py` 直接 import KGI、直接 MIS HTTP、直接 commit；market-owned descriptor catalog 目前只有 public MIS quote / TW official datasets。 |
| P0-2 router 直接綁 KGI lease / stream | VERIFIED | `routers/market.py:60` 起直接 import `app.market.providers.kgi_superpy`，lease routes 直接呼叫 provider manager。 |
| P0-3 quote_depth 擁有 selection/fallback/cache/IO/transaction/projection | VERIFIED | `market/quote_depth.py:1866` 的主流程同時讀 KGI、fallback MIS、upsert/commit 與投影；canonical KGI 目前只作 shadow comparison。 |
| P0-4 Gateway 沒有 depth/auction application wiring | VERIFIED | Resolver 有 `resolve_depth()` / `resolve_auction()`；Gateway 只有 bars、quote、market breadth、market index methods，且 codebase 沒有 depth/auction candidate/port types。 |
| P0-5 public quote repository hard-filter MIS | VERIFIED | `market/public_quote_repository.py:88` 及 validation 分支要求 TWSE MIS provider/source；KGI row 不能成為此 reader 的 candidate。 |
| P0-6 KGI canonical raw lineage 未完整持久化 | VERIFIED | canonical converter 可產 observation；legacy persistence沒有 RawFetchResult transaction owner，KGI `SourceLineage` 也未填 raw receipt ID/content hash。 |
| P0-7 cp0 boundary debt 不是終態 | VERIFIED | boundary test只阻止新增 debt；allowlist仍容許 router 的 KGI-specific imports。 |
| P1-7 intraday 自持 NStock -> Yahoo fallback/fetch/persist | VERIFIED | `market/intraday.py:1260` 的 uncached path自行選 provider並直接 upsert/commit。 |
| P1-8 history GET 預設 refresh | VERIFIED | `routers/market.py:1118` 與 `market/intraday.py:1368` 預設 `refresh=True`。 |
| P1-9/10/11 indices 自持 current provider orchestration | VERIFIED | `market/indices.py` 直接 import provider/HTTP helpers；current index與 breadth均有 local fallback chains。 |
| P1-12/13 QualityRequirement 未中央執行 | VERIFIED | `integration_contracts.py:110` 定義 contract；production search沒有 `requirement.quality` / `minimum_authority` / `allow_partial` consumer。public quote reader只檢查 request required fields。 |
| P1-14 tw_dataset_health 不等於 freshness gate | VERIFIED | module明示只做 cache-only storage/lineage probe，回傳 `freshness_status=not_evaluated`。 |
| P2-15 AI direct company profile ORM query | VERIFIED | `ai/market_context/taiwan_stock.py:161` 的 `_load_company_profile()` 直接 query `StockProfile`。 |
| P2-16/17/18 catalog counts | VERIFIED | catalog與 tests目前為 6 PLATFORM_OWNED、7 COMPATIBILITY、13 LINEAGE_GAP、2 COMPATIBILITY_DERIVED。 |
| P2 derived component raw IDs | VERIFIED | `TaiwanMarketMinuteState` 與 `TaiwanIntradayStockState` model保存 aggregate source文字，但沒有 component source/raw-result IDs。 |
| A-1 trend GET 也能 provider IO / commit | ADDED | `/api/market/intraday/{stock_id}` 進入 `_load_intraday_trend_uncached()`；cache miss時會 fetch NStock/Yahoo並 persist。 |
| A-2 index intraday GET 預設 prefer_live | ADDED | `market/indices.py:4350` 預設 `acquisition_policy="prefer_live"`；router GET 未將其固定成 cache-only。 |
| A-3 quote-depth GET / frontend polling 會 refresh | ADDED | router與service均預設 `refresh=True`，frontend hook polling也傳入 refresh；可能 provider IO + DB commit。 |
| A-4 intraday provider identity 有污染風險 | ADDED | `MarketIntradayBar` 沒有 raw lineage；legacy upsert以固定 history provider identity寫入不同來源資料，需在 migration前做資料兼容設計。 |
| A-5 shared quality 與 AI quality 是不同層 | PARTIAL | AI已有 outward `data_quality_contract`；本輪缺的是 candidate eligibility。應接 resolved health，不應複製或把 AI contract塞入 provider adapter。 |
| A-6 viewer lease 可直接由 research_lease 取代 | PARTIAL | `research_lease.py` 已有 owner token、poll/cancel/release primitives，但屬 request-scoped acquisition；frontend heartbeat / symbol switch仍需 market-owned persistent lifecycle。 |
| V-1 existing completed official path不 regression | PENDING | source contract與tests存在；本次未執行 tests或 runtime smoke。 |
| V-2 KGI/MIS deterministic live selection | PENDING | 尚未有 KGI canonical repository candidate與 live sample。 |
| V-3 M5 semantics / cleanup | PENDING | 必須在相符 official session 執行，不能由 source-only audit判定。 |
| V-4 API/AI/MCP/frontend runtime parity | PENDING | 需要後續 cross-surface smoke與可見 UI evidence。 |

## 已有但不等於完成的保護面

- Gateway tests已保護 bars/quote 的 cache-only zero acquisition、mandatory reread、bounds與 truthful `policy_unsatisfied`。
- Resolver tests已保護 cache/live policy、future timestamp與 quote fallback；auction只有直接 Resolver typed test，沒有 Gateway application test。
- public quote tests已保護 MIS acquisition/persistence/reread、cache-only與 legacy lineage fail-closed。
- architecture guard已限制 shared core新增 provider-specific imports，但仍有明示 legacy debt。

## 後續 acceptance 不可降級

- source-only green 不等於 runtime adoption。
- runtime health不等於 frontend可見行為。
- post-close sample不等於 Regular / Opening / Closing gate。
- missing live evidence維持 `PENDING`，不得標成 pass。
