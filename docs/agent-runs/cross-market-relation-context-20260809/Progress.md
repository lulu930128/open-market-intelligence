# 進度紀錄

## 目前狀態

- 專案狀態：實作中。
- 目前里程碑：Foundation Release（M0–M3）與 Consumer Release code slice（M4–M6）已完成；M9 的 live DB／HTTP／MCP／launcher adoption slice 已完成，user-visible browser acceptance 與 rollback drill 尚未完成；M7–M8 尚未開始。
- Branch：`main`。
- Worktree：已有大量使用者／其他任務在途變更；本任務以 temporary detached worktree 隔離兩個 cross-market commits。正式 launcher 已重載 backend，live SQLite 已由 startup migration 前進至 `20260809_0055`；未呼叫 provider refresh。
- 發布邊界：已建立 `188ea9e feat(cross-market): add relation context consumers` 與獨立 AI／outward commit `feat(ai): expose cross-market decision context`。未 push、未發布。

## 2026-08-09 現況基線

### Radar

- Active route 使用 `radar_v2.0`，v1 為 frozen read-only rollback 面。
- Radar v2 已有 `context_signals` 與 `context_alignment_score` 接點。
- `priority_score` 目前由 direction strength、confidence、risk、urgency 與 event actionability 組成，未使用 `context_alignment_score`；active sort 依 `priority_score`。
- `validation_status` 與 active version 分離，不能因 production active 就宣稱 walk-forward verified。

### 個股詳細頁

- `/api/market/overnight-impact/{stock_id}` 已回傳 stance、summary、score、weighted change、ADR parity、FX/foreign flow、factors、baskets、freshness、missing、warnings 與 evidence passport。
- 既有 GET 預設會做 bounded refresh，最多 8 個 symbols；新 architecture 將讓 Radar、AI 與新 consumer 使用 read-only context path，legacy route 保留相容期。
- `OvernightDataViews.tsx` 已是 summary-first 呈現，可直接演進成 canonical context 的 consumer。

### 對外 contract

- Canonical envelope 是 `omi.decision.v4`。
- Readiness owner：`evidence.capability_status`；evidence owner：`evidence.data[capability_id]`。
- 已有 stock-level `cross_market.overnight` 與 market-level `market.cross_market`；目前 stock capability 宣告 `signals`，既有 overnight response 則主要使用 `factors`／`baskets`，需在里程碑 6 收斂為 additive canonical projection。
- MCP 公開面應維持 thin adapter，Kuro 後續只吃 structured contract。

### Relation 與 market data

- ADR mapping、profile、factor weights 與部分 basket selection 仍在 Python logic／constant。
- 現有 ADR parity 已處理 ratio、FX、TW reference、expected trade date、freshness、warnings 與 remaining gap，可作為 parity v2 golden。
- 現有 overnight service 會依 mapping profiles 選 factor/basket，尚無正式 relation/evidence registry 與 point-in-time cross-market snapshot。
- 目前 migration chain 在 worktree 中至少到 `20260804_0051`，但該 migration 與多個相關檔案尚未提交；實作開始前必須重新執行 `alembic heads`，不能預設下一個 revision。

## 已完成的設計決策

1. 建立 backend-owned `cross_market.context.v1`，三個 consumer 只做 projection。
2. Relation registry 與 point-in-time signal snapshot 都是必要基礎；只做 mapping table 不足以安全接 Radar。
3. Direct ADR 使用 parity gap；proxy 使用 benchmark residual；direct source 不重複計分。
4. 個股頁沿用目前 `OVERNIGHT` summary-first 版型，technical core 保持主體。
5. Radar 第一個 release 僅 display-only；不改 direction、priority、bucket 或 sort。
6. Radar ranking 影響是獨立、可失敗的後段實驗，不阻擋個股頁與 outward evidence 上線。
7. `cross_market.overnight` 是 stock-level context；`market.cross_market` 保持 market-level，不混用。
8. Read path 不發 provider HTTP；refresh 由 bounded job／scheduler owner 執行。
9. Relation candidate 與 production approval 分離；不提供 public CRUD，LLM 不可直接核准。
10. 所有演進 additive、feature-flagged、可 dual-read／shadow diff／rollback。

## 2026-08-09 里程碑 0：Golden baseline

- 重新核對 branch、dirty worktree、現有 migration chain、active Radar v2 與 OMI v4 contract owner。
- Alembic migration files 的目前 head chain 到 `20260804_0051`；因 repo 使用程式化 `create_alembic_config()`，不能以不存在的 `backend/alembic.ini` 執行 CLI。
- 新增 `backend/tests/test_cross_market_golden_contract.py`，鎖住：
  - 四組已驗證 ADR identity／ratio／verified date。
  - memory profile 的 legacy factor／basket weights。
  - `cross_market.overnight` 目前公開欄位。
  - `context_alignment_score` 改變不得影響 Radar direction、priority 或 bucket。
- 未呼叫外部 provider、未修改或 migration live SQLite、未啟動 runtime。

### 驗證證據

- M0 既有 targeted baseline：`94 passed, 12 subtests passed`。
- 新增 cross-market golden regression：`4 passed`。
- 測試皆使用 `-p no:cacheprovider` 與 workspace `.tmp` pycache。

## 2026-08-09 里程碑 1：Relation／Evidence Registry

- 新增 backend-owned `backend/app/market/cross_market/`：canonical instrument identity、relation taxonomy、Pydantic contract、read service 與 trusted maintenance command。
- 新增 `cross_market_relation` 與 `cross_market_relation_evidence` ORM／Alembic schema：
  - direct relation ratio 與 proxy ratio NULL constraint。
  - relation identity 的 `valid_from` 與 `version` 雙重唯一性。
  - candidate／approved／rejected／revoked review lifecycle。
  - `created_by` 與 `reviewed_by/reviewed_at` 分離，避免審核覆蓋建立者。
  - A／B relation 必須有 primary A／B evidence；validity overlap 由 maintenance transaction fail closed。
- migration `20260809_0052` seed 四組已驗證 ADR：2330/TSM、2303/UMC、3711/ASX、8150/IMOS；`valid_from=2026-07-22`，不宣稱此前歷史有效性。Consumer slice 另加入 2408/MU 的 reviewed Tier C DRAM cycle proxy；其 evidence statement 明示非供應、客戶、持股或公司特定因果關係。
- 新增 read-only API：`GET /api/market/cross-market/relations/{stock_id}`。GET 只讀 registry，不呼叫 provider、不 refresh、不寫 DB。
- historical `as_of` 同時遵守 effective validity 與 `verified_at` availability；當時尚未驗證的 relation/evidence 不會被回放讀取。
- `not_applicable` 不偽裝成 missing；contract invariant 失敗時回傳 `blocked` 與 machine-readable `missing`。
- maintenance command 支援 validate、list、create candidate、approve／supersede、reject 與 disable；沒有 public CRUD。
- 操作邊界與指令記錄於 `M1RelationRegistryRunbook.md`。

### 驗證證據

- M1 focused contract／store／migration／API／model：`19 passed, 79 subtests passed`。
- 完整 Alembic chain upgrade/model parity：`5 passed`。
- API inventory：`14 passed, 60 subtests passed`，operation inventory 由 367 增為 368，且明確鎖住新增 GET。
- M0 AI／Radar regression 重跑：`94 passed, 12 subtests passed`。
- 新 package、router、ORM 與 migration `compileall` 通過。
- `git diff --check` 通過；只有 repo 既有 LF/CRLF 提示。
- SQLite migration 測試有 Python 3.12 預設 date/datetime adapter deprecation warnings；不影響本次結果，後續 DB hardening 再統一 adapter。
- 未對 `data/open_market_intelligence.db` 執行 upgrade/downgrade，未啟動或重載 runtime。

## 2026-08-09 里程碑 2：Parity v2 與 canonical context

- `adr_parity.py` 已改為 relation registry 優先、hardcoded mapping fallback 的 dual-read；response additive 帶出 `mapping_resolution`、relation/evidence lineage 與 shadow differences。
- 新增 backend-owned `cross_market.context.v1` contract；目前 methodology 為 `cross_market.relation_context.v2`，統一 status、signal、bucket score、coverage、freshness、limitations 與 evidence passport。
- 新增 read-only relation/context API。讀取路徑只查本機 cache，不發 provider HTTP、不寫 DB。
- 新增 bounded refresh API/job：最多 8 個來源、32 檔台股、dedupe、timeout、per-source partial failure；planner 現在由 Registry 同時解析 direct source、proxy source 與 proxy benchmark。
- 修正 SQLite transaction 邊界：table existence inspection 使用目前 Session connection，避免 in-memory SQLite inspector 另開 transaction 破壞 savepoint。
- Relation replay 同時限制 effective date 與精確 `verified_at <= data_available_at`，不讓未來才驗證的 relation/evidence 洩漏到歷史 decision。

## 2026-08-09 里程碑 3：Overnight facade 與個股詳細頁

- `OvernightImpactRead` 與 report additive 提供 canonical `cross_market_context`，並在 top-level facade 投影 `context_status`、`decision_usable`、`signals`、`bucket_scores`、`coverage`、methodology/relation/snapshot IDs、limitations 與 source。
- Evidence passport 帶入同一 canonical snapshot lineage；既有 stance、score、factors、baskets、ADR parity 與 FX flow 保持相容。
- `OvernightDataViews.tsx` 新增 summary-first 跨市場 strip：direct 顯示 parity，proxy 顯示 raw return、benchmark return 與 residual；proxy 文案固定標示「同業代理（非因果）」及限制。
- zh-TW、en-US、ja-JP 與 frontend types 已同步；新增 direct 與 proxy Playwright fixtures/assertions。

## 2026-08-09 里程碑 4：Proxy residual、aggregation 與 snapshot

- 新增 `proxy_signal_engine.py`：2408/MU 使用 `^SOX` simple sector residual，beta 固定 1.0，Tier C confidence multiplier 0.6；benchmark missing、日期不對齊、stale 或 policy missing 均 fail closed。
- 新增 `aggregation.py`：bucket 內正規化、configured/available/decision-usable coverage、excluded reason；blocked signal 不灌高 coverage。
- Direct/proxy 同 source double-count guard 已鎖測試；direct source 不會再以 proxy raw return 重複計分。
- 新增 migration `20260809_0053`、point-in-time snapshot materializer/batch reader；Radar scheduler 固定 decision time 後 materialize，Radar GET 只讀 snapshot。
- Event classification 目前刻意維持 `unresolved`，`event_context_unresolved` 與非因果限制對 UI/outward 可見；尚未建立 M7 的 statistics/beta/event policy。

## 2026-08-09 里程碑 5：Radar v2 display-only

- Active Radar 以 batch snapshot 接入 canonical context，投影 confirm／contradict／info badge、coverage、snapshot/methodology/relation lineage 與 limitations。
- `cross_market_radar_display_enabled` 與 materialize flag 可回退；summary 明示 `ranking_effect: none`。
- Context alignment 只供呈現；開關前後 direction、direction score、priority、bucket、rank 與 matched universe 由 regression 鎖定不變。
- Radar UI 將跨市場 badge 提前顯示，仍不把外部逆風改寫成技術看空。

## 2026-08-09 里程碑 6：OMI v4、MCP 與 outward contract

- 擴充 `cross_market.overnight` bounded fields，新增 `cross_market.relations`、`cross_market.parity` capability；三者共用 canonical snapshot/relation lineage。
- 新增 `cross_market` question intent 與 query-plan domain；台股個股的預設 selection 只選 target、三個 cross-market capabilities 與 freshness。
- Taiwan stock analysis digest 已接入 canonical overnight context，並投影成 `cross_market_decision_context_v1`；固定 `role=confirmation_or_counter_evidence`、`ranking_effect=none`、`technical_score_effect=none`。
- `answer_composer`、Taiwan projection、OMI v4 evidence 與 MCP capability inventory 已接線；跨市場專問回傳 structured summary 且不產生交易 action，一般技術回答只 additive 增加支持／反證／資料限制，不翻轉既有技術 stance、headline 或 action plan。
- Kuro-facing decision contract 透過 `context.cross_market` 暴露 bounded summary；完整 signals 仍由 `evidence.data[capability_id]` 擁有，避免 outward summary 成為第二真相。契約與 consumer 規則記錄於 `M6OutwardContract.md`。
- MCP adapter 保持 thin，不直接讀 DB 或重算市場邏輯。
- MCP public contract snapshot 已由隔離 commit 的 backend registry 重生：57 capabilities，digest `ff82494f4f50483649fb7a429ed28300443f6ce18bfe33fe3dae65d02231f3e9`。

### Consumer Release 驗證證據

- Cross-market focused（refresh、proxy、aggregation、context、overnight）：`29 passed`。
- 跨 relation/context/refresh/parity/Overnight/Radar/AI/MCP/API/model 的整合回歸：`293 passed, 168 subtests passed`。
- AI／outward focused contract：`9 passed`；涵蓋 intent、default selection、query plan、analysis evidence、answer augmentation、bounded decision projection、完整 v4 envelope、stale data limit 與 overnight readiness invariant。
- AI answer／capability／decision envelope／projection／outward／MCP regression：`256 passed, 68 subtests passed`。
- `compileall`：cross-market domain 與 overnight service 通過。
- Frontend `npm exec tsc -- --noEmit --incremental false`：通過；本任務檔案 targeted ESLint：通過。
- Frontend 全量 `npm run lint`：被另一條在途 ETF 功能的 `TaiwanETFDataPanel.tsx:120` `react-hooks/set-state-in-effect` 阻擋；為避免干預他人 worktree，本任務未修改該檔。
- Direct ADR 與非因果 proxy 兩個短時 Playwright 情境：`2 passed`。測試前將 dead PID 44752 遺留的 `.next/dev/lock` 移至 `.tmp/stale-runtime-locks/` 保留；測試後 3100 無 listener、Next lock 已清除。
- 隔離 commit `188ea9e` 已用 detached temporary worktree 驗證：`64 passed, 54 warnings, 75 subtests passed`；驗證後已移除 temporary worktree。
- 第二個隔離 AI／MCP commit 驗證：`252 passed, 1 deselected, 68 subtests passed`。唯一 deselect 的 optional-stale quality test 已在乾淨 `188ea9e` baseline 重現；主 worktree 中另一批在途 data-quality 修正可使該 test 通過，本 commit 未混入該批變更。
- 正式 runtime：8400 listener PID `42420` → `11668`，health `ok`；HTTP 與 MCP 都讀到 `omi.decision.v4`、cross-market intent／style／decision context 與三個 evidence capabilities。
- Readiness live invariant：overnight、relations、parity 對 stale context 均為 stale／unusable，`facts_usable=false`、`decision_usable=false`。
- Standalone OMI_search：protocol `2025-06-18`、session preserved、6 tools、`omi.ask isError=false`；`mode=full` 才承諾 human answer 與 decision context，`mode=data_only` 只承諾 evidence。
- Live SQLite：Alembic `20260809_0055`，relation 5、evidence 6、signal snapshot 0；startup 同時套用其他在途 migrations，未執行 provider refresh。

## 後續里程碑

- M7：event policy、rolling beta/correlation/stability statistics、purged walk-forward 與 Radar ranking shadow。
- M8：達到預先定義樣本門檻後的 promotion decision；目前 Radar 必須維持 display-only。
- M9：live DB migration、API/MCP protocol smoke 與正式 launcher runtime adoption 已完成；user-visible browser acceptance 與 rollback drill 待完成。

## 已知風險

- Dirty worktree 涵蓋 AI contract、Radar、Frontend types 與 migration；實作前需逐檔確認 owner 與重疊範圍。
- Legacy overnight GET 有 bounded refresh side effect；不能在同一版直接破壞預設行為，需先轉移 internal consumers 與觀察 caller。
- Existing `context_alignment_score` 是可用接點，但其離散 stance 平均不足以直接代表已驗證 ranking feature。
- 海外交易日、台股 next-session、FX 時點、ADR corporate action 與 provider availability 是主要 leakage／錯價風險。
- Proxy relation 的 evidence 與 event context 不足時，最容易把相關性誤寫成因果；需以 taxonomy、reason code、review 與文案測試共同防守。

## 下一步

目前 source-level Consumer Release、AI／outward contract 與正式 API/MCP runtime adoption 已完成。下一步只補 M9 的 user-visible browser acceptance 與 rollback drill；M7/M8 需要累積 point-in-time 樣本，不能以現有 fixture 或 latest-cache projection 結果提早放行 Radar ranking。
