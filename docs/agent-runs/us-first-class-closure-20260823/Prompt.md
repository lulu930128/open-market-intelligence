# OMI 美股 First-Class Closure 修復

## Goal

- 關閉 2026-08-23 engineering audit 已重現的美股 outward contract、session、Resolver ownership、research consumer 與 rollout gate。
- 讓 HTTP、SSE 與 MCP 的 `omi.decision.v4` 對 1m／5m／15m／30m／1h／4h 請求回傳真實 effective interval，不再只揭露 mismatch 而未完成 requested aggregation。
- 將 Yahoo extended-hours zero-filled volume 正規化為 unknown／provider-unavailable evidence，不把未知量冒充成交量零。
- 讓 US early-close、provider session eligibility、selected session、daily provider priority 與 cache-only resolved read seam 由 backend contract 統一擁有。
- 建立可持久採用、可 fail-closed、可回復 `off` 的 `canary`／`on` rollout，並以正式 launcher runtime 驗證。

## Non-goals

- 不執行 KGI US login、subscription、Account、Order 或 entitlement smoke；KGI US 保持 `blocked_live_validation`、unadvertised、unwired。
- 不因本次 closure 偽造 corporate-action completeness；checkpoint 沒有 provider evidence 前，US raw-price technical 仍可 facts-usable，但 `decision_usable=false`。
- 不以目前 local symbol master 宣稱 full-market universe，不啟用 `market.breadth`、`market.sectors` 或 `market.hot_groups`。
- 不執行付費／稀缺 quota refresh、無界 backfill、DB rebuild、destructive migration、commit、push 或 release。
- 不實作目前 truthful unsupported 的 US advanced technical、options 或 earnings intelligence。

## Hard constraints

- Provider adapter 只負責 payload normalization 與 Canonical Observation；Resolver／Control Plane 擁有 cross-provider selection、session eligibility、fallback 與 selected evidence health。
- `cache_only` 的 HTTP／AI／MCP read path不得啟動 provider fetch、subscription、repair或DB write。
- Unknown volume 不得轉成零；regular、premarket、after-hours volume coverage必須可區分。
- Early-close calendar必須由US market-specific backend contract擁有；consumer不得硬編碼13:00或16:00。
- 新增 rollout mode不得在 mode identity、symbol allowlist、mismatch budget或resolved evidence缺失時默默回 legacy並宣稱 canonical on。
- 保留既有 public paths與 `omi.decision.v4` compatibility；新增欄位採 additive contract。
- 保留目前 dirty worktree中的使用者變更，不 reset、restore、clean 或格式化無關檔案。

## Context

- Repo：`C:\project\Open Market Intelligence`
- Audit：`%USERPROFILE%\Downloads\OMI_US_First_Class_Closure_Engineering_Audit_v2.txt`
- Upstream task：`docs/agent-runs/us-first-class-foundation-outward-20260823/`
- Research task：`docs/agent-runs/us-first-class-research-consumer-20260823/`
- Runtime baseline（2026-08-23 22:11 Asia/Taipei）：backend health `ok`，但 `canonical_market_data_mode=off`。
- Live MCP baseline：5m request回 `source_interval=1m`、`effective_interval=1m`、`interval_status=unsupported`；after-hours zero-filled volume卻回 `volume_status=available`、`volume_semantics=interval_shares`。
- Data baseline：AAPL daily resolved research facts usable；corporate-action completeness unknown，因此decision blocked。US market coverage gate仍未通過。

## Capability contract

| 項目 | Closure contract |
|---|---|
| Product scope | US first-class read-only research；不包含交易執行。 |
| Target | `us_stock`／US equity與ETF；沿用既有symbol／venue normalization。 |
| Provider | Yahoo quote／intraday／daily；Alpha Vantage daily；KGI US保持blocked。 |
| Resource | quote snapshot、intraday bars、daily OHLCV、technical research與coverage metadata。 |
| Freshness | `America/New_York`；regular／pre-market／after-hours／early close分離。 |
| Request bounds | 單一symbol；intraday最多500 bars；research daily最多500 bars；cache-only不做外部calls。 |
| Persistence | 本輪不新增DB table或migration；只讀既有cache／SQLite rows。 |
| Failure | missing／partial／stale／provider_unavailable／policy_unsatisfied保持truthful。 |
| Transaction | Provider IO不持有DB transaction；本輪closure read seam不commit。 |
| Public API | 保留既有US routes與Decision v4；selected session／volume coverage採additive fields。 |
| AI contract | selected capability決定reader workload；supplemental gaps不得污染selected quality或warnings。 |
| Consumer | MCP保持thin；frontend沿用backend projection，不重算interval／volume／session。 |
| Validation | Pure contract tests → AI/API regression → safe backend profile → launcher HTTP/MCP runtime acceptance。 |

## Deliverables

- Interval propagation與HTTP／MCP end-to-end regression。
- Extended-hours volume normalization、coverage metadata與Canonical/outward tests。
- Versioned US early-close schedule helper及calendar／canonical／aggregation tests。
- Session-aware provider policy、single US daily priority owner與selected-session outward projection。
- Stable cache-only resolved daily read seam；Research consumer不再直接依賴canary/private store helper。
- Selection-bounded US context，明確選取intraday時不讀無關SEC／profile／13F／corporate-action／market coverage。
- `off → shadow → compare → canary → on` source與launcher contract、fail-closed tests及rollback證據。
- 更新current architecture／task progress，區分code closure與external gates。

## Done criteria

- Live MCP 5m request回 `requested_interval=effective_interval=5m`，bars真為5m aggregation，且`external_fetch_attempted=false`的cache-only path仍成立。
- Extended-hours zero-filled Yahoo volume outward為`null`，top-level volume status不再是`available/interval_shares`；regular positive volume不退化。
- 2026-11-27等official early-close session使用13:00 close／13:05 daily release，normal day仍16:00／16:05。
- Provider policy會使用`DataRequirement.session`，Resolved health與projection保留selected session；US daily priority只有一個backend owner。
- Research service只依賴stable resolved read seam；explicit intraday selection不執行無關US supplemental readers，且不再出現無關Form 4 warning。
- `canary`只允許bounded symbols並在canonical evidence不合格時fail closed；`on`只回canonical selected evidence；restart後effective mode與allowlist由launcher明確設定。
- Targeted regression與backend safe validation通過；正式runtime health、HTTP與MCP證明採用新contract。

## Open questions / assumptions

- Early-close日期以NYSE official published calendar及可驗證規則為準；若未來calendar例外無法由規則安全推導，需改為versioned explicit override而不是猜測。
- 本輪不將現有full-market／corporate-action／KGI external gate改名成完成；code closure完成後它們仍可能阻擋更高階capability activation。
