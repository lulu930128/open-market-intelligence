# Roadmap

本 Roadmap 描述 OMI 的長期技術收斂順序，不是日期承諾表。

若任務與本文件衝突，先回到 `ProductVision.md`、`OperatingModel.md`、`QualityBar.md` 與 repo `AGENTS.md` 判斷。

## 北極星

OMI 要成為本機優先、可驗證、可跨 provider 的市場研究工作台。

台股是 primary / reference market。
美股是 first-class research market。
其他市場逐步建立在同一套 Market Data Foundation 上。

AI decision 必須建立在可信 evidence 之上，而不是靠 provider-specific shortcut 或 consumer-side fallback。

## M1 — Market Data Foundation

建立 provider-neutral 市場資料地基。

目標：

- Canonical Observation contract。
- InstrumentKey / SourceLineage。
- Quote / Depth / Auction / Bar / Trading Status。
- Provider Capability Status。
- Resolver / Control Plane。
- `cache_only / prefer_live / require_live / completed_session`。
- Provider Health / Dataset Health / Resolved Evidence Health。
- Dataset Registry v1。
- Capability `advertised => projection exists` contract test。

遷移原則：

- 不 Big Bang rewrite。
- 新 canonical path 先 shadow。
- outward API 第一階段維持 compatibility。
- feature flag cutover。

## M2 — TW / US Market Data Integration

讓台股、美股真正共用 Foundation。

### Taiwan

- KGI TW 直接輸出 Canonical Observation。
- TWSE MIS 直接輸出 Canonical Observation。
- 移除新功能對 KGI->MIS masquerading 的依賴。
- Viewer Lease / Research Lease。
- preopen / opening handoff / regular / close acceptance。
- depth / auction / quote semantics。

2026-08-25 Data Core production adoption checkpoint：official daily OHLCV、full-market EOD lifecycle、official index/breadth與single-symbol public last-trade已接入共同Gateway/Resolver/result contract；28個production dataset與18個bounded operations已由running production runtime公開。Production DB採用0067/0068，named launcher、TPEX actual official index persistence/cold read、API、visible UI、frontend proxy與MCP `omi.decision.v4`已驗收。Active-session public quote F-07、TAIEX expected-date source gap、current public quote lineage gap與official breadth completeness仍如實pending/partial；完成F-07前不得標記common platform operational。KGI、depth/auction及既有M5依使用者決策留待共同平台完成後另案onboard。

### United States

- KGI US quote integration。
- Yahoo / AlphaVantage canonical alignment。
- regular / premarket / after-hours semantics。
- Level 1 contract。
- US provider policy / fallback。
- 美股正式 first-class research outward support。

2026-08-23 source checkpoint：US capability truth gate、Yahoo／Alpha Vantage
canonical adapters、market-owned provider descriptors、bounded shadow／compare 與
neutral resolved projection seam 已完成；production canary／on、KGI US live 與
consumer cutover仍未驗收。

## M3 — Data Reliability / Trading Status / Repair

處理「知道壞了但補不回來」的資料生命週期問題。

目標：

- Instrument Trading Status。
- Market Session 與 Trading Status 分離。
- TW daily price repair owner。
- US bounded refresh owner。
- expected date + trading eligibility。
- source-health current/request/persisted convergence。
- TAIEX/TPEX live index reliability。
- stale / partial / not-applicable semantics。
- Dataset Registry 擴充到 production datasets。

## M4 — Account / Portfolio Plane

將私人帳戶正式從 Market Data 分離。

目標：

- KGI Account capability diagnostics。
- 503 / unavailable semantics。
- PositionObservation。
- CostBasisObservation。
- CashObservation。
- partial / complete sync。
- destructive replace guard。
- unknown cost integrity。
- Portfolio Valuation 使用 Market Data Resolver + FX。
- legacy cost semantics audit。

不以「帳戶 API 成功」作為 Market Data readiness 條件。

## M5 — Research / Decision Alignment

在 Foundation 穩定後再收斂研究層。

目標：

- Shared Technical Engine 使用 Canonical OHLCV。
- US `technical.structure` 真正實作或 truthful disable。
- TW/US technical contract 對齊。
- ADR / cross-market relation 雙向 resolver。
- fundamentals provider limitations 清楚化。
- evidence / capability readiness 與 Decision v4 對齊。
- scenario / counter-evidence / risk 只使用 resolved evidence。

## M6 — Consumer / UX Convergence

讓 UI / MCP / Kuro 完全只依賴 backend-owned contract。

目標：

- Frontend 不自行 provider/freshness inference。
- MCP research lease 由 backend 取得。
- Kuro 使用同一 evidence/decision contract。
- TW / US detail panel 共用資訊架構。
- 資料品質與 provider/fallback 狀態清楚但不佔滿 UI。
- mobile / desktop 穩定。

## M7 — Secondary Markets

JP / KR / Crypto / Resource 逐步遷移到共同 Foundation。

原則：

- 不複製 provider selection architecture。
- 不為了「所有市場平等」犧牲 TW/US production quality。
- 先 canonical / freshness / health，再擴充 AI feature。

## 暫緩項目

- AI 自主交易。
- 無界全市場 KGI subscription。
- 無 freshness policy 的大量 backfill。
- 未定義 trust/budget 的付費資料與自動寫入。
- 為單一 provider 重寫 public contract。
- Foundation 未穩定前大規模 frontend redesign。
- Foundation 未穩定前把所有歷史 service 一次搬家。

## Milestone 完成原則

每一 Milestone 都必須有：

- 明確 owner。
- contract / schema。
- regression tests。
- runtime/data smoke。
- failure semantics。
- rollback / feature flag（若涉及 cutover）。
- current docs 同步。

「看起來能跑」不是完成條件。
