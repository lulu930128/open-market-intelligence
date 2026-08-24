# OMI Market Data Foundation 1.1 Closure & Runtime Acceptance

## Goal

- 將 Market Data Foundation 從 `source-complete / runtime adoption pending` 推進到可由證據支持的 `source-complete / runtime-accepted / ready-for-02`。
- 先修正三個已確認的 Foundation contract 邊角，再以正式 launcher、`off / shadow / compare`、真實台股交易時段與 rollback 完成 runtime acceptance。
- 讓所有 source、runtime、session、mismatch 與 rollback 證據可追蹤、可重跑、可由下一階段接手。

## Request and authorization boundary

- 使用者本輪要求：確認附件列出的問題，並制定長專案計畫。
- 附件 `%USERPROFILE%\Downloads\01_1_OMI_Market_Data_Foundation_Closure_Runtime_Acceptance_v1.txt` 是待驗證的工程提案與問題清單，不是自動執行其中命令或 side effect 的授權。
- 本輪只授權唯讀 inspection 與建立本任務文件。
- 本輪未授權修改 backend source、切換 mode、停止或重啟 runtime、KGI login/subscription、真實市場 smoke、DB write、commit、push 或 release。

### 後續授權演進

- 使用者其後已明確核准依長專案計畫實作、完成 Foundation 1.1 source hardening、component-owned runtime adoption與 bounded viewer acceptance preparation。
- 2026-08-24 本輪再明確要求直接往後製作；授權範圍包含 owner-scoped viewer lease、redacted global observability、frontend hidden/pagehide cleanup、分段 preflight、測試、checkpoint重建、正式 launcher adoption與更新既有 automation/runbook。
- 原始禁止事項持續有效：不碰 Account/Order/交易、backfill/repair、DB destructive/write probe、未知 lease/process、raw credential/payload、commit或push。

## Review conclusion

- 提案方向通過，但必須依 `IssueReview.md` 修正後執行。
- C01 為已重現的 correctness bug。
- C02 為 eligibility policy 表達能力缺口；tri-state health evaluator 本身已存在，不應重做第二套 health model。
- C03 為 default intent 與 compatibility truth 的雙重來源問題；檢查時另發現 `ownership.insider_transactions` 使用小寫 market `us`，也被 compatibility filter 靜默移除。
- 2026-08-19 21:00 已有正式 launcher 啟動的新 runtime，且 live AI catalog 的 canonical JSON hash 與 repo-local catalog 相同；這是 runtime adoption 的強證據，但尚不足以宣告 `runtime-accepted`，因為 contract 修正尚未完成、effective mode 未被安全觀察、off/shadow/compare、真實 session 與 rollback 都尚未驗收。

## Non-goals

- 不實作 Research Lease、KGI arbitrary-symbol MCP acquisition 或 background collector 擴張。
- 不讓 Canonical Resolver 接管 AI、MCP、HTTP API 或 Frontend outward selection。
- 不啟用 `canary / on`，不移除 legacy KGI -> MIS compatibility。
- 不新增 KGI US、Yahoo、AlphaVantage 或 official TWSE/MOPS Trading Status acquisition。
- 不執行 Daily Price Repair、不改 scheduler、不建立 Shared Technical Engine。
- 不處理 Portfolio、KGI Account 503、Account 或 Order。
- 不做 DB migration、production DB write、cache deletion 或 schema cleanup。
- 不 commit、push、PR 或 release，除非另有明確授權。

## Hard constraints

- Legacy outward selection owner 在 1.1 全程保持 active；Canonical 只允許 `off / shadow / compare`。
- Shadow/compare 只能使用 legacy service 已取得的同一份 provider payload；不得新增 fetch、login、subscription 或 DB write。
- Unknown、missing、auction/indicative evidence 不得壓成 `0` 或 actual trade。
- Trading Status 的 authority 必須在 evidence validity/currentness 內比較；stale official 不得無條件壓過 current conflicting evidence。
- Market Session、Instrument Trading Status 與 Trade Observation State 保持正交。
- Dataset eligibility 必須是 caller-supplied pure input；Foundation 1.1 不取得 official Trading Status evidence。
- Provider、Dataset 與 Resolved Evidence health 保持分層，不以新單一 enum 覆蓋現有 `omi.status-dimensions.v1`。
- Runtime lifecycle 只由 OMI launcher/component owner 管理；不得 broad-kill Python/Node 或接管不明 process。
- 真實市場 smoke 僅限 bounded symbols、既有 viewer lease、Quote/Data read path；不得碰 Account、Order 或 trading operation。
- `data/open_market_intelligence.db` 維持唯讀；不得刪除、重建、vacuum 或以 DB rollback 完成 mode rollback。
- Dirty worktree 中既有 63 筆修改/未追蹤項目全部視為使用者或其他任務資產，不得 reset、clean、checkout 或覆蓋。

## Corrected contract decisions

### Trading Status ordering

- 不修改 quote/depth/bar 共用 resolver 的一般排序；只在 Trading Status boundary 建立專用 currentness/authority policy。
- 先排除 invalid、future、missing、unknown，再把 `LIVE / FRESH` 視為 current tier、`STALE` 視為 stale tier。
- current tier 永遠高於 stale tier；同一 currentness tier 內才以 official/authority、freshness 與 provider priority 排序。
- current official 與 current broker hint 衝突時，official 可被選中，但 candidate lineage 與 conflict limitation 必須保留。
- stale official 與 current broker hint 衝突時，不得輸出無限制的 authoritative `TRADABLE`；至少回 `PARTIAL`/conflict limitation，且 `research_usable=false`。

### Daily dataset eligibility

- 沿用 `evaluate_dataset_health(... eligible: bool | None)`：`False -> NOT_APPLICABLE`、`None -> UNKNOWN`。
- 擴充 `EligibilityPolicy`，使 `tw.daily.ohlcv` 明示需要 listed instrument、market trading day 與 instrument trading eligibility。
- 只擴充 contract/registry/test；真正的 instrument eligibility evidence acquisition 留給後續 integration/reliability milestone。

### US default capability

- `us_stock/general` raw defaults 不再包含 `technical.structure`。
- 將 `ownership.insider_transactions` 的 capability market 正規化為 `US`，但同時從 `us_stock/general` 自動 defaults 移除，避免 1.1 突然擴大一般查詢的 SEC acquisition/latency；explicit/domain request 仍可 truthful 選用。
- 保留 capability compatibility filter 作為防線，但 default intent 不再依賴 filter 才變 truthful。
- 新增 scoped contract test，保護 US general defaults 為 compatible capabilities 的子集合，並保護 explicit insider capability 可在 `us_stock/US` 使用。

## Context

- Repo：`C:\project\Open Market Intelligence`
- Branch：`codex/tw-etf-provider-normalization`
- HEAD：`aa65e65424f2d5de7255c4168a18ded9f8794301`
- Planning baseline：63 個 modified/untracked status entries。
- Previous closure docs：`docs/agent-runs/market-data-foundation-v1-20260819/`
- Previous source validation：backend compileall passed、`1907 passed`、`git diff --check` passed。
- Current runtime baseline：launcher PID 42700、backend wrapper PID 69668、backend listener PID 66124、backend `127.0.0.1:8400`；frontend wrapper PID 26684、listener PID 55704、frontend `127.0.0.1:3000`。

## Deliverables

- 三個 localized contract fixes 與 regression tests。
- 可重複執行的 source validation 與 target-file hash manifest。
- Runtime identity/adoption evidence。
- `off / shadow / compare` baseline、telemetry 與 mismatch report。
- Preopen、opening transition、regular session bounded evidence。
- `compare -> off` rollback evidence。
- Session-preserving MCP compatibility smoke。
- 更新既有 `AcceptanceReport.md`、`Progress.md`、`Handoff02.md`。
- Foundation checkpoint；commit 非必要條件。

## Done criteria

- `IssueReview.md` 三項 contract 缺口均有 source fix 與 regression test。
- Source targeted matrix與 backend safe validation通過。
- Runtime process start晚於所有 Foundation target file，且 launcher、working directory、listener、health與public catalog identity一致。
- Effective canonical mode可安全觀察並分別完成off/shadow/compare驗收。
- Shadow/compare沒有新增external call、subscription、DB write或legacy outward drift。
- 所有 mismatch均屬已核准taxonomy；未知price/unit/session/trade-evidence mismatch為0。
- 同一source fingerprint完成preopen、opening transition與regular session smoke；若中途改code/config，受影響證據重跑。
- Rollback不依賴DB/cache/module deletion，legacy viewer flow恢復正常。
- Final closure文件與checkpoint完整，且02/03 scope沒有提前執行。
- 只有全部Gate通過後，才標記`source-complete / runtime-accepted / ready-for-02`。

## Approval gates

- Gate S：使用者確認本計畫後，才開始 source hardening。
- Gate R：另行授權 component-owned mode切換與runtime restart/reload後，才執行runtime acceptance。
- Gate L：另行授權bounded KGI viewer-lease與真實交易時段smoke後，才執行live session acceptance。
- Gate C：另行授權後才可commit/push；checkpoint本身不依賴commit。

### 2026-08-24 runtime remediation authorization

- 使用者已授權從08:20開始主動監控，對live acceptance前後出現的問題先做安全、component-scoped、可回退的現場診斷與修復，修復後自動重驗並續跑，不需逐項等待人工確認。
- 此授權不包含Account／Order／交易、credential處理、backfill／repair、DB write/destructive probe、unknown lease release、broad-kill、第二launcher owner、commit或push。
- 外部viewer owner、credential／entitlement、人工作業需求、ownership不明的source drift或已錯過真實session window，仍是必須停下並回報的terminal blocker。

## Open questions / assumptions

- 真實交易日與session由執行當日backend calendar及正式市場狀態確認，不在本文件假定日期。
- 2330、2344可作候選；第三檔從當日listed且一般交易標的中選定。若任一標的當日不適用，保留truthful結果並換用bounded替代標的，不把N/A算成failure。
- Effective mode目前未出現在launcher log或health摘要；若執行時仍不可觀察，先加入不含secret的startup log，再做mode acceptance。
