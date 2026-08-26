# 實作計畫

> 2026-08-26 pre-commit audit重新開啟G2/G3。修正順序、acceptance與rollback以`PreCommitRemediationPlan.md`為準；原wave紀錄保留作歷史基線。

## 執行原則

- 採 strangler / vertical slice；每段完成後必須能獨立驗證與 rollback。
- 先建立共通可執行安全 seam，再讓新的 production candidate 進入 Resolver。
- 不以 legacy debt allowlist 當合規終態，也不因統一而重寫已通過驗收的 core。
- 本計畫已進入 source convergence 收束；各 package 的實際狀態以 `ExecutionBoard.md` 與 `Progress.md` 為準。

## Phase 0 — Current architecture audit

狀態：完成。

驗收：

- current truth、source、tests 與 dirty worktree 互相核對。
- 產出 current owner map、差異與未驗證清單。
- 沒有觸碰既有 US / scheduler / frontend dirty hunks。

## Phase 1 — Shared eligibility 與 typed application seam

範圍：

1. 在 shared boundary 新增 `QualityEvaluation` 與穩定 reason codes。
2. 執行 `required_fields`、`minimum_authority`、`allow_partial`、canonical lineage completeness 與 timestamp validity。
3. 將 eligibility / rejection reasons 接入既有 Resolver，不改寫 selection ranking。
4. 新增 `DepthCandidateBatch` / `DepthCandidateReader`、`AuctionCandidateBatch` / `AuctionCandidateReader`。
5. 新增 bounded acquisition / transaction ports，完成 `MarketDataGateway.resolve_depth()` / `resolve_auction()`。

順序差異：原規格把完整 Quality phase 放在 KGI onboarding 後。本計畫將「最低可執行 eligibility gate」提前到 KGI production cutover 前，避免新 KGI candidate 在缺少中央 quality enforcement 時先成為 decision-ready。完整 cross-capability quality regression 仍可在後段擴充。

驗收：

- cache satisfied 時 external calls 為 0。
- persist success 後 reader 必須再讀；transaction failure 不得假裝 resolve 成功。
- `require_live` 未滿足時 truthful `policy_unsatisfied`。
- depth、auction 與 quote typed contract 不混用。
- authority、partial、lineage、required field、future / stale timestamp 均有 deterministic rejection。

## Phase 2 — KGI quote / depth / auction canonical persistence

範圍：

1. 建立 TW market-owned KGI / MIS descriptors；shared core 只看 descriptor、health 與 requirement。
2. 沿用 `providers/kgi_canonical.py` 與 `providers/twse_mis_canonical.py` semantics。
3. 建立 raw receipt、SourceRegistry、RawFetchResult、canonical row 的 explicit transaction owner。
4. 將 public quote repository 改為 provider-neutral candidate reader，不再 hard-filter MIS。
5. 同時存在 KGI / MIS 時由既有 Resolver deterministic selection。

驗收：

- source / raw result / event / received / fetched time、parser version、content hash 與 provider identity 完整。
- auction indicative evidence 不會寫成 actual trade。
- KGI account health 不影響 quote health。
- legacy row 缺 canonical lineage 時 fail closed。

## Phase 3 — Provider-neutral realtime lease platform

範圍：

1. 定義 market-owned viewer lease intent / handle；KGI manager 留作 provider implementation。
2. router 改呼叫 provider-neutral platform，不直接 import `kgi_superpy`。
3. 明確協調現有 `research_lease.py` request-scoped lifecycle 與 viewer heartbeat lifecycle；不建立第三套無關 framework。
4. quote-depth read projection 改走 resolved repository truth。

驗收：

- owner token、heartbeat、cancel、timeout、symbol switch 與 cleanup 可驗證。
- subscription / symbol bounds 由 plan 或 lease owner 強制執行。
- cleanup 後 active handles 為 0；stale symbol lease 為 0。
- router direct KGI debt 可從 boundary allowlist 移除。

## Phase 4 — Legacy quote-depth 降級

範圍：

- `quote_depth.py` 只保留 thin compatibility projection 或 legacy adapter。
- 移除其 provider selection、fallback、HTTP、circuit-breaker ownership 與 DB transaction ownership。
- GET quote-depth 改為 cache-only；refresh / lease 使用 explicit POST / PATCH / DELETE。

驗收：

- frontend polling GET 不會 provider IO、commit 或建立 subscription。
- quote、depth、auction 各自保留 canonical lineage 與 health。

## Phase 5 — Intraday bars vertical slice

範圍：

1. NStock / Yahoo 純 adapter + market-owned descriptors。
2. Bar acquisition / transaction / repository reread 接既有 Gateway。
3. 所有 intraday GET 改 cache-only，包括 trend 與 history。
4. explicit POST / job 承擔 refresh。
5. `MarketIntradayBar` 補 canonical raw lineage；5m aggregate 補 derived metadata。

驗收：

- NStock / Yahoo priority 不存在於 `intraday.py`。
- provider identity 不會把 NStock row 標成 Yahoo。
- current quote 不寫回 bars。
- aggregate 保留 source interval、component raw IDs、calculation version。

## Phase 6 — Current-session index / breadth vertical slice

範圍：

1. 建立 `market.index.snapshot`、`market.breadth.current` 等 current-session capability。
2. Yahoo / MIS / official current adapters 只產生 candidates。
3. TW policy 只解釋 session、provisional / official / final 與 universe semantics。
4. `indices.py` 移除 current-session cross-provider fallback ownership。
5. `/indices/{index_id}/intraday` GET 改 cache-only。

驗收：

- completed official platform 不回退或混入 provisional current semantics。
- breadth 保留 universe、classified、unknown、not-received、coverage 與 limitation。
- TAIEX / TPEX capability、session 與 venue 分離。
- current-session GET external calls 為 0。

## Phase 7 — P2 migration seams

範圍：

- company profile 建立 market-owned reader / projection，AI 不直接 query ORM model。
- 為 compatibility、lineage gap、compatibility-derived datasets 排定 owner 與 migration order。
- minute / stock intraday derived state補 component raw IDs 與 derivation metadata。

驗收：

- 不新增 direct SQL、consumer provider selection 或 generic JSON platform debt。
- dataset catalog ownership 與 outward limitation 保持 truthful。

## Runtime / live gate

只有 source、targeted tests、API smoke 與 frontend validation 通過後，才進行 Regular / symbol switch / Closing / cleanup 的 M5 live-session gate。沒有官方時段證據時維持 `pending`；不得用收盤後或其他時段樣本補造通過。

## 長專案執行狀態

每個 work package 使用下列狀態，不用模糊的「差不多完成」：

- `NOT_STARTED`：尚未修改。
- `IN_PROGRESS`：已有 task-owned diff，但 acceptance 尚未全過。
- `SOURCE_COMPLETE`：source 與 targeted tests 已完成，尚未 runtime adoption。
- `RUNTIME_ADOPTED`：launcher-selected runtime 已載入並通過 direct / proxy probe。
- `LIVE_ACCEPTED`：相符官方 session 的 live evidence 已通過。
- `BLOCKED`：有明確外部 blocker，且已保留 evidence。
- `DEFERRED`：不在本輪 P0 / P1 done criteria，只建立 seam 或 guard。

## Program gates

| Gate | 名稱 | 必要證據 | 可否進下一階段 |
|---|---|---|---|
| G0 | Current truth | product / architecture docs、source owner map、dirty worktree baseline | 必須 |
| G1 | Contract | typed contract、reason codes、compatibility tests | 必須 |
| G2 | Vertical slice | adapter -> receipt -> transaction -> reread -> quality -> Resolver -> projection | 必須 |
| G3 | Cross-surface | API / AI / MCP / frontend 使用同一 resolved truth | 必須 |
| G4 | Runtime adoption | launcher-selected endpoint、direct/proxy readiness、runtime identity、DB migration | source release前必須 |
| G5 | Live session | 正式 session semantics、symbol switch、cleanup、無 trial leak | realtime closure必須 |
| G6 | Debt closeout | legacy owner移除、allowlist縮減、docs/catalog/guards更新 | program closure必須 |

G0 到 G6 是累進 gate。較晚 gate 的通過不能覆蓋較早 gate 的失敗；post-close readiness 也不能替代 G5。

## Work package dependency map

```text
BASE-01 -> BASE-02 -> CORE-01 -> CORE-02 -> CORE-03
                                  |          |
                                  |          +-> KGI-01 -> KGI-02 -> KGI-03
                                  |                                -> KGI-04 -> KGI-05
                                  |
                                  +-> BAR-01 -> BAR-02 -> BAR-03 -> BAR-04
                                  |
                                  +-> IDX-01 ----\
                                  +-> BRD-01 -----+-> IDX-02
                                  |
                                  +-> TAIL-01
                                  +-> TAIL-02 -> TAIL-03

KGI-05 + BAR-04 + IDX-02 + TAIL-01 + TAIL-02
        -> CROSS-01 -> ADOPT-01 -> LIVE-01 -> CLOSE-01
```

詳細 scope、依賴與 acceptance 見 `WorkPackages.md`；執行狀態見 `ExecutionBoard.md`。

## 實作波次

1. Wave 0 — Baseline：完成 architecture audit 與 program plan。
2. Wave 1 — Shared Safety：中央 quality evaluator、Gateway integration、depth / auction typed wiring。
3. Wave 2 — KGI Canonical：descriptors、quote/depth/auction raw lineage、repository reread。
4. Wave 3 — Realtime Cutover：provider-neutral viewer lease、router/frontend cutover、legacy quote-depth降級。
5. Wave 4 — Intraday Bars：NStock/Yahoo shared acquisition、lineage、explicit refresh、GET cache-only。
6. Wave 5 — Current Index/Breadth：current-session candidates、TW policy、shared resolution、legacy orchestration移除。
7. Wave 6 — P2 Seams：company profile、derived component lineage、長尾 migration guard。
8. Wave 7 — Convergence：cross-surface、runtime adoption、M5 live acceptance、debt closeout。

## Stop-and-fix rules

- 若 touched file 在開始 package 前已有不明 dirty hunk，先重讀並記錄；不能安全共存就停止該 package。
- 若 shared core 出現 KGI、MIS、Yahoo、NStock 名稱或 TW-specific session rule，停止並把 ownership退回 market layer。
- 若 provider adapter 出現 `commit()` / `rollback()`，停止並移至 explicit transaction owner。
- 若 GET route 可產生 provider call、subscription、repair 或 DB mutation，該 package不得標成 source complete。
- 若 unknown / missing / partial / indicative 被轉為 0、actual trade 或 decision-ready，停止並新增 regression test。
- 若 completed-session official evidence被 provisional current path覆蓋，停止並先修復 selection / finalization contract。
- 若 persist後沒有 repository reread，或 Resolver收到 adapter memory object，停止並補齊 transaction boundary。
- 若 validation failure 與本輪 task-owned diff相關，先修正，不跨 package累積失敗。
- 若失敗只存在於既有 unrelated dirty work，保留命令、error與隔離證據，不修改無關模組。
- 若 runtime identity、launcher-selected port或 DB migration不明，不宣稱 runtime adoption。
- 若錯過正式 market session，live gate維持 `PENDING`，等下一個合法 session。

## Rollback model

- Source：每個 package保持 localized diff；回退只反向修改 task-owned hunks，不使用 reset / checkout / stash。
- API：新 explicit command surface先 additive；GET cutover在 command path與cache reader已驗證後才進行。
- Provider：先 shadow / candidate-visible，再進 public selection；public cutover前保留舊 projection compatibility。
- DB：migration先在 disposable DB copy驗證 upgrade / downgrade；不對 user DB做破壞性 rehearsal。
- Runtime：只使用 repo launcher lifecycle，並保留 cutover前後 identity與health evidence；未經明確授權不 restart。
- Live：M5 cleanup與compare/off復原是 gate的一部分；active handles非 0 不算成功。

## Program-level decisions

- 2026-08-26：先完成最低 shared quality gate，再允許 KGI candidate進 production selection。
- 2026-08-26：`minimum_authority` 使用明確 policy mapping，不依 Enum名稱或宣告順序比較。
- 2026-08-26：canonical raw lineage requirement採 additive、向後相容 contract；不從 capability名稱暗猜。
- 2026-08-26：viewer lease與request-scoped research lease共用 bounded ownership primitives，但保留不同 lifecycle。
- 2026-08-26：P0 / P1必須完成；P2本輪只要求可執行 seam、migration order與anti-debt guards。
