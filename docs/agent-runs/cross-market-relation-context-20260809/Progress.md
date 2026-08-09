# 進度紀錄

## 目前狀態

- 專案狀態：Consumer Release、M6.1／M1.1／M2.1／M4.1／M9.1／M9.2 已完成；更新版回歸揭露兩個 P1，corrective hardening 計畫已建立、尚未開始實作。
- 目前里程碑：先執行 R0 regression freeze，再依序完成 M2.2 refresh trigger、M4.2 current／replay selector、M9.3 outward/runtime acceptance。M7–M8 暫停，Radar 維持 display-only。
- Branch：開始 M6.1 時為 `main`、與 `origin/main` 同步且 worktree clean；執行期間共享 worktree 被另一條在途工作切至 `codex/tw-etf-provider-normalization`。本任務未切換分支，也未修改該工作擁有的 ETF／Frontend 檔案。
- Worktree：目前位於 `codex/tw-etf-provider-normalization` 且有 cross-market、ETF、Frontend 與其他在途變更；corrective hardening 必須 localized，不覆寫或混入其他 owner 的修改。
- 發布邊界：本輪只更新長專案計畫與進度文件；未修改功能、未呼叫 provider、未寫 live DB、未重啟 runtime，也未 commit／push。

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

## 2026-08-09 Consumer hardening 診斷與計畫

### 已確認問題

- 2408／MU 並非「seed 不存在」：live DB 有 relation id 5 與兩筆 evidence。其 `verified_at=2026-08-09T12:00:00Z`，而測試 request 早於該 availability boundary；relation store 正確套用 `verified_at <= available_at`，因此回傳 `relation_registry:none`。問題是 seed 將固定未來時間當成 verification truth，不是讀取 filter 漏資料。
- Stock scope 的 cross-market domain inference 會同時候選 `market.cross_market`；selection 雖可先濾掉，後段 diagnostics 又從未過濾 domain candidates 將它加回 unsupported，導致 2330／2408 outward quality 被 phantom capability 誤判 blocked。
- MCP server-side live schema 已包含 `cross_market.relations` 與 `cross_market.parity` 的 include／required enum；剩餘邊界是 ChatGPT host 可能快取舊 tool schema，需要 reconnect，而不是再新增 adapter fallback。
- USD/TWD live resource event 約落後 512,207 秒，超過 72 小時 stale threshold；現有 AI overnight refresh planner 只規劃 US daily price，沒有把 FX resource refresh 納入同一 bounded operation。
- Live `cross_market_signal_snapshot` 筆數為 0。Materializer 與 Radar hook 已存在，但 Ask read path 尚未讀 materialized snapshot；目前若直接 materialize，payload 仍可能保留 `latest_local_cache_projection_not_materialized_snapshot` limitation，形成語意矛盾。

### 計畫決策

1. 先做 M6.1 scope fix，讓 outward blocked 語意回到真實資料限制，再處理資料補齊。
2. 不修改已套用 `20260809_0052`；等目前 dirty migration graph 穩定後，從實際 Alembic head 建立 forward-only temporal governance revision，未知人工異動一律 fail closed。
3. Refresh 留在 AI/tool orchestration，只有 `allow_external_fetch` 可觸發；GET、`cache_only`、Radar read path 繼續零 provider side effect。
4. Snapshot 先收斂 immutable lifecycle 與 projection source，再讓 Ask／Radar／Frontend 對帳；latest cache 不冒充 point-in-time materialization。
5. M9.1 完成前不宣稱 GPT／MCP／Frontend 端到端完善；M7／M8 gate 通過前不讓跨市場 context 影響 Radar 排名。

### 本輪驗證基線

- OMI_search generated snapshot：57 capabilities，digest `ff82494f4f50483649fb7a429ed28300443f6ce18bfe33fe3dae65d02231f3e9`，包含 overnight／relations／parity。
- OMI_search unit／protocol tests：`28 passed`。
- 先前針對目前行為的 focused regression：`26 passed`；證明現有測試可執行，但尚未鎖住上述 scope、temporal、refresh 與 materialization invariants。
- 本輪只建立 snapshot checkpoint 與長專案文件，未執行 provider refresh、migration、runtime restart 或 live DB 寫入。

## 2026-08-09 M6.1：Capability scope hardening

### 已完成

- `SCOPE_DOMAIN_CAPABILITIES` 現在明確區分 stock 與 market 的 cross-market capabilities：stock 只推導 overnight／relations／parity，market 只推導 `market.cross_market`。
- Broad `requested_domains` 是 NLP domain inference，不再把同 domain 下 target-incompatible 的其他 capabilities 記成 required unsupported；`legacy_include` 仍只加入 target-compatible members。
- Caller 顯式要求 `market.cross_market` 搭配 stock target 時仍回 `unsupported_target_scope`，沒有靜默吞掉錯誤 request。
- 新增 2330／2408 query-plan、stock／market domain matrix 與顯式錯誤 capability regression。
- Repo MCP snapshot 由官方 generator 驗證為 canonical 且無內容 diff；standalone OMI_search 已同步至目前 backend digest `af734dde221a4fdc5d65eb4d460512c34c2c8571c62f174058078a8b03a3d8ed`，完整 generated diff 尚未 commit。

### 驗證證據

- Cross-market／capability targeted：`73 passed, 12 subtests passed`；新增 cases 單獨重跑：`11 passed, 2 subtests passed`。
- Decision envelope／outward／tool boundary：`75 passed, 15 subtests passed`。
- Repo MCP／public v4 contract：`34 passed, 8 subtests passed`。
- Standalone OMI_search：`28 tests OK`，57 capabilities，overnight／relations／parity 均存在。
- Backend safe validation：compileall、`1596 passed, 383 warnings`、`git diff --check` 全部通過；log：`.tmp/validation/20260809-185710`。
- 代表性 2330 source-level query plan 已由修正前 `market.cross_market` phantom unsupported／unmet，收斂為 exact 五項 required capabilities，unsupported／unmet 皆為空；2408 由同一 regression 鎖定。

### 邊界

- 本里程碑只修 selection／diagnostics truth，不把 stale、missing、provider failure 轉成 ready，也不改 freshness 或 data-quality 判斷。
- 未重啟正式 backend，因此正式 runtime adoption 與 ChatGPT host schema cache 仍留在 M9.1。

## 2026-08-09 M1.1：Proxy temporal governance

### 已完成

- 重新查證 Alembic graph，施工當下唯一 head 為 `20260809_0055`；新增 forward-only `20260809_0056`，沒有修改已可能套用的 `20260809_0052`。
- 0056 只在舊 2408／MU relation、兩筆 evidence、actor、時間、ratio／weight、review 狀態與 evidence hash 完整符合已知錯誤 seed fingerprint 時才修復；任何人工異動、缺列或多版本異常都 fail closed。
- 舊 version 1 保留 audit history 並改為 revoked／inactive；新 version 2 使用 migration 實際執行時間作 verification/review 時點，`valid_from` 固定為下一個 UTC 日期，避免同日較早 decision 回看見到尚未可用的 relation。
- 若舊 proxy seed 不存在，0056 會以相同保守時間規則建立 version 1；downgrade 刻意不刪除 governance history，re-upgrade 保持 idempotent。

### 驗證證據

- Migration focused：`4 passed`，涵蓋 repair、fingerprint mismatch fail closed、seed missing、downgrade/re-upgrade replay safety。
- Relation／context／aggregation／migration／model regression：`29 passed, 80 subtests passed`。
- M1.1 後 backend safe validation：compileall、`1610 passed, 663 warnings`、`git diff --check` 全部通過；log：`.tmp/validation/20260809-191149`。
- Alembic graph 驗證只有一個 head：`20260809_0056`。

### 邊界

- 新 version 的 evidence revalidation actor 是可稽核的 migration actor，不冒充人工即時複審；其用途限於把既有 reviewed Tier C company-profile evidence 移到真實可用時點。
- 0056 尚未套用 live DB，正式 runtime 仍會停留在已部署 schema，直到 M9.1 執行受控 migration／runtime acceptance。

## 2026-08-09 M2.1：AI/tool bounded refresh orchestration

### 已完成

- AI planner 不再把台股跨市場 freshness gap 拆成多個 `us.refresh_daily_price`；改為單一 allowlisted `cross_market.refresh_context`，呼叫既有 backend-owned bounded refresh owner。
- Composite plan 以一檔台股為 target，最多 8 個來源、requested runtime 上限 120 秒；實際 AI request 仍受既有 `max_calls`、`max_external_fetches` 與較嚴格 wall-clock budget 限制。
- Refresh owner 同時規劃 relation registry 所需的 direct US daily、proxy source、proxy benchmark 與 ADR 適用時的 USD/TWD；symbol/resource 去重仍由同一 owner 負責。
- `allow_external_fetch=false`／`cache_only` 會在 execution policy 阻擋 composite tool，provider call 為零；GET relation/context 與 Radar read path 沒有接入此工具，仍保持 local-cache-only。
- Per-source failure 會寫入 `cross_market_orchestrator` provider event，保留錯誤 target／來源／requested provider；同來源在 300 秒失敗 cooldown 內 deterministic deferred，避免立即重試風暴。
- Partial failure 的 tool run 明示 `operation_status=partial`、error 與 cached fallback warning；refresh 後重新掃 freshness，既有 stale／missing context 不會因部分 provider 失敗被清空或冒充 current。
- Relation governance 與 candidate approval 不在 refresh code path，M2.1 只寫 market cache、provider event 與既有 job tracking。

### 驗證證據

- Cross-market refresh／overnight targeted：`17 passed`。
- AI capability／outward／freshness／tool reliability：`169 passed, 12 subtests passed`。
- Cross-market context／refresh／overnight、source-health、provider-health、job dedupe：`41 passed`。
- M2.1 後 backend safe validation：compileall、`1612 passed, 663 warnings`、`git diff --check` 全部通過；log：`.tmp/validation/20260809-192607`。

### 邊界

- 本輪測試以 mock provider 驗證 orchestration、failure event、cooldown 與 fallback；沒有消耗外部 quota，也不構成真實 provider acceptance。
- AI schema／runtime 尚未重載；正式 8400 listener、MCP host schema cache 與 GPT tool call 留在 M9.1 驗證。
- Legacy overnight GET 的既有相容 side effect 尚未移除；新 canonical context、Radar 與 AI composite path 不依賴該 side effect。

## 後續里程碑

- M7：event policy、rolling beta/correlation/stability statistics、purged walk-forward 與 Radar ranking shadow。
- M8：達到預先定義樣本門檻後的 promotion decision；目前 Radar 必須維持 display-only。
- M9：live DB migration、API/MCP protocol smoke、正式 launcher adoption 與 user-visible browser acceptance 已完成；破壞性 rollback drill 不在本輪執行。

## 已知風險

- Dirty worktree 涵蓋 AI contract、Radar、Frontend types 與 migration；實作前需逐檔確認 owner 與重疊範圍。
- Legacy overnight GET 有 bounded refresh side effect；不能在同一版直接破壞預設行為，需先轉移 internal consumers 與觀察 caller。
- Existing `context_alignment_score` 是可用接點，但其離散 stance 平均不足以直接代表已驗證 ranking feature。
- 海外交易日、台股 next-session、FX 時點、ADR corporate action 與 provider availability 是主要 leakage／錯價風險。
- Proxy relation 的 evidence 與 event context 不足時，最容易把相關性誤寫成因果；需以 taxonomy、reason code、review 與文案測試共同防守。
- 共享 worktree 目前在另一條 ETF feature branch 且有未提交修改；任何 commit 前必須重新確認 branch 與 staged scope，不能把 ETF／Frontend 在途檔案混入 cross-market commit。
- Standalone `C:\GPT_MCPtool\OMI_search\public_contract_snapshot.json` 現在包含 main 上其他已提交 capability field 的 generated parity 更新；它必須以完整 snapshot 原子提交，不能只挑 cross-market hunk。

## 2026-08-09 M4.1：Immutable snapshot lifecycle

### 已完成

- 新增 forward-only migration `20260809_0057` 與 `cross_market_signal_snapshot` lifecycle 欄位；materialized payload 固定保留 `projection_source`、`source_cutoff_at`、`materialized_at`、`materialized_by` 與可驗證 `payload_hash`。
- Context read path 優先讀 immutable snapshot；沒有 snapshot 時才回 `latest_local_cache`，並明示 `latest_local_cache_projection_not_materialized_snapshot`，不再把 cache projection 冒充 point-in-time snapshot。
- Radar materializer 只處理已核准且 decision date 有效的 relation，batch 有 500 檔上限、不觸發 provider refresh；Radar summary 以 typed contract 投影 materialization status、snapshot/methodology/relation lineage、limitations 與 `ranking_effect=none`。
- AI evidence、Taiwan projection、Overnight facade、MCP public contract snapshot 與 frontend types 已同步 lifecycle fields；public contract 為 57 capabilities、22 targets，digest `aeefa9330b2dc96eea8f78a168a2a379be66d61ee4f60533c335777bc522190a`。

### 驗證證據

- M4.1 後 backend safe validation：compileall、`1618 passed, 801 warnings`、`git diff --check` 通過；log：`.tmp/validation/20260809-195941`。
- Standalone OMI_search regression：`28 passed, 9 subtests passed`，generated snapshot 與 backend registry digest 相同。
- Frontend typecheck 通過；snapshot idempotency、hash integrity、point-in-time replay、Radar display-only 與 AI lifecycle projection 均有 focused regression。

## 2026-08-09 M9.1：正式 runtime adoption 與端到端驗收

### 已完成

- 使用者重啟 OMI launcher 後，startup 正式套用 `0055 -> 0056 -> 0057`；live DB revision 為 `20260809_0057`，relation、evidence 與 signal snapshot tables 均存在。
- Standalone OMI_search 另以其 tray owner 受控重啟；actual/expected build identity 已一致，MCP 與 tunnel readiness 正常。
- 首次正式 Radar materialization 揭露兩個 production-only 問題並已修正：Radar 與 crypto writer 的 SQLite read-to-write contention，以及 exited event lookup 與 DB unique identity 不一致造成的重跑 duplicate INSERT。
- 新增共用 SQLite in-process write coordinator 與 bounded retry；lock 時 rollback 後重跑完整 Radar write operation，不會只重送 commit。Crypto realtime writer 使用同一 coordinator；重試耗盡時 API 回 predictable retryable 503，不再裸露 500。
- Radar event upsert 現在以 `event_key + direction` 對齊 identity，並復用同 onset date 的 exited event；同日 rerun idempotent，跨日事件週期仍可建立新 row。
- 正式 POST `/api/watchlists/groups/3/radar/v2/evaluate` 回 `200 OK`；live DB 產生 4 筆 immutable snapshots，Radar GET summary 為 `materialized_snapshot`、4 snapshots、4 relation versions、`ranking_effect=none`、79 missing、0 decision-usable。
- 2330 canonical GET 回同一 materialized snapshot：`cmctx:aa6a8845113ed52850d1b3c8`、owner `watchlist.radar_v2`、source cutoff `2026-08-07T05:30:00Z`、payload hash 存在；status 仍為 stale、`decision_usable=false`。
- MCP protocol smoke 完成 `initialize -> session id -> tools/list -> omi.ask`；`omi.ask isError=false`，v4 evidence 的 domain/capability/data surfaces 均讀到同一 materialized lineage、hash 與 stale status。
- Browser live acceptance：Radar 顯示「跨市場：外部脈絡受限」；2330 Overnight 展開後顯示「跨市場脈絡」「資料較舊」、ADR parity 與 FX/外資資訊。stale context 沒有被呈現成 ready，也沒有改變 Radar 排名。

### 驗證證據

- SQLite coordinator、cross-market materializer、Radar active/automation/event lifecycle、crypto writer 與 transaction ownership：`90 passed, 14 subtests passed`。
- 最終 backend safe validation：compileall、`1638 passed, 801 warnings`、`git diff --check` 通過；log：`.tmp/validation/20260809-205223`。
- Frontend `npm exec tsc -- --noEmit --incremental false` 通過；focused pytest 另有環境無法建立 `.pytest_cache` 的既知權限 warning，safe wrapper 已用 `-p no:cacheprovider` 完整通過。
- Runtime backend listener 經 exact command/parent ownership 驗證後由 launcher recovery 接管；最後 listener PID 49260，readiness 為 ready。

### 使用邊界

- 目前只有 relation registry 命中的 4/83 檔可產生 snapshot，其餘 79 檔明示 missing；這不是全市場覆蓋。
- 4 筆 snapshot 全為 stale/partial，0 筆 decision-usable；現階段只能作呈現、支持/反證與資料限制，不得改 Radar rank、technical score 或自動交易決策。
- Local MCP runtime 與 protocol 已驗證；若 ChatGPT host 曾快取舊 action schema，仍需重新連線該 MCP session 才能看到新 enum/fields。
- Browser 的 Overnight「資料完整」表示該 legacy overnight card 的欄位完整度；跨市場 freshness 以展開後的「資料較舊」與 canonical status 為準，兩者不可混為同一指標。

## 下一步

- M7：event policy、rolling beta/correlation/stability statistics、purged walk-forward 與 Radar ranking shadow。
- M8：達到預先定義樣本門檻後才做 promotion decision；目前 Radar 維持 display-only。

## 2026-08-09 M9.2：個股頁市場背景／個股映射資訊分層

### 已完成

- Overnight disclosure 明確標示為「市場背景」，保留 legacy factors／baskets、匯率與外資，以及原有資料完整度；canonical cross-market context 已移到外層獨立 disclosure，Overnight 收合時仍可直接掃描。
- 映射摘要直接顯示 backend contract 的 `source → target`、direct／proxy 類型、`summary.score`、status 與 signal `confidence_tier`；展開後顯示 residual、`configured_weight × quality_multiplier = effective_weight`、signal contribution、coverage、relation lineage 與 limitation。
- ADR parity 隨個股映射層呈現；`not_applicable` context 不建立可用映射列。Frontend 只做格式化與 layout，沒有重算 relation、score、freshness 或權重。
- 中／英／日文案與 Playwright contract assertions 已同步；proxy 明示「非因果」，避免將同業景氣代理誤寫成供應、客戶或持股關係。

### 驗證證據

- `npm exec tsc -- --noEmit --incremental false`：通過。
- `npm run lint -- --no-cache`：通過。
- Playwright 使用同 repo、既有 port 3000 dev server 並開啟 `PLAYWRIGHT_REUSE_EXISTING_SERVER=1`；沒有停止或重啟使用者 runtime：
  - `--grep "Taiwan overnight"`：proxy residual case `1 passed`。
  - `--grep "Taiwan stock overnight report"`：direct ADR／FX 分層 case `1 passed`。
  - `--grep "Taiwan technical sections collapse"`：技術區塊與 Overnight disclosure 順序 case `1 passed`。
- direct ADR case 的 browser screenshot 已人工檢查：市場背景與個股映射為兩個獨立層級，桌面版無重疊或文字溢出。

### 使用邊界

- 2408／MU relation 於 `2026-08-10` 生效；在此前的 point-in-time read 仍應是 `not_applicable`，前端不會用未生效 relation 填入映射列。
- `summary.score` 是 canonical 映射綜合分數，signal residual 與 contribution 分開呈現；不得和 legacy Overnight `weighted_change_pct` 直接相加。
- `confidence_tier` 是關係信心；Overnight 的「資料完整」仍只代表 legacy 市場背景的輸入完整度。
- Radar 保持 `ranking_effect=none`；本里程碑只改善個股頁可見性，不改排名或技術決策。

### 下一步

- M7 繼續處理 event policy、rolling statistics 與 Radar ranking shadow；達到 M8 promotion gate 前保持 display-only。

## 2026-08-09 更新版回歸確認與 corrective hardening 計畫

### 已確認

- P1 refresh trigger：2330 的 TSM 日線可由 current provider 滿足，但 USD/TWD resource quote 已 stale；`build_cross_market_refresh_plan` 會規劃 FX operation，上層 `scan_us_overnight_impact_gaps.refresh_recommended` 卻仍為 false，導致 AI 不加入 `cross_market.refresh_context`。
- P1 current projection：2330 materialized snapshot 的 ADR input 停在 2026-08-04，本機 parity 已有 2026-08-07 input；current Ask 會同時投影較新 parity 與較舊 canonical snapshot。
- Planner capability scope 與 immutable snapshot lifecycle 本身通過；問題分別位於 refresh execution gate，以及 current reader 對 snapshot supersession 的判斷。
- 2408／MU 在 `2026-08-10` 前 `not_applicable`、指定該日期後 relation ready 是正確 temporal governance；正式預設查詢需在台北時間 2026-08-10 08:00 後驗收。
- Backend `/api/ai/tools`、local OMI_search `tools/list` 與 MCP protocol 均已有 relations／parity schema；若 ChatGPT host 仍缺欄，應先分類為 host action cache，而不是 backend 或 adapter 缺口。

### 計畫決策

1. 先以 R0 fixtures 把兩個 P1 凍結成 deterministic regression，不使用 live DB 或外部 provider 讓測試碰巧通過。
2. M2.2 由完整 composite refresh plan 產生 execution decision；只有 planned operations 可執行，deferred-only 只回限制與 next eligible time。
3. M4.2 明確拆分 current 與 replay；current 比較逐來源 input lineage，replay 保留 immutable point-in-time semantics。`source_cutoff_at` 不是單獨的 currentness proof。
4. Ask／GET 不因 current snapshot 過舊而隱性 refresh 或 materialize；若 snapshot 被較新 local inputs 取代，回 latest-local projection 與 machine-readable limitation。
5. M9.3 分開驗證 backend schema、local MCP schema 與 ChatGPT host cache；不為 host cache 在 thin adapter 建永久旁路。
6. 完成 M9.3 前不恢復 M7／M8，也不允許跨市場 context 影響 Radar ranking。

### 本輪狀態

- 已在 `Plan.md` 新增 R0 → M2.2 → M4.2 → M9.3 的 scope、acceptance、validation 與 stop-and-fix 規則。
- 本輪只制定計畫，尚未修改 backend、frontend、MCP schema 或 runtime。

### 下一步

- 從 R0 開始：先新增「US daily current／FX stale」與「舊 materialized snapshot／較新 local input」兩組 failing regression，再進入 M2.2 owner 修正。

## 2026-08-09 R0：回歸案例與 currentness contract 凍結

### 已完成

- 新增 deterministic「US daily current／USD-TWD stale」fixture；完整 composite plan 只有一筆可執行 FX source，舊 `scan_us_overnight_impact_gaps.refresh_recommended` 仍錯誤為 false。
- 新增「舊 materialized snapshot／較新 local ADR input」fixture；current read 仍被舊 snapshot 截走，但 historical cutoff 可保留舊 snapshot replay。
- 測試使用 in-memory SQLite、固定日期與 mock calendar；未讀寫 live DB、未呼叫 provider、未重啟 runtime。

### 驗證證據

- 兩個新 regression 在修正前精準失敗：refresh gate 為 `False is not true`；current selector 為 `materialized_snapshot != latest_local_cache`。
- FX fixture 最初嘗試新增第二筆相同 resource identity 時觸發 unique constraint；已改成更新同一 cache row，確認最終失敗來自 selector，而不是 fixture。

### 下一步

- 進入 M2.2：讓完整 composite refresh plan 成為 AI trigger 的唯一 owner，並補 planned／deferred／cooldown 邊界測試。

## 2026-08-09 M2.2：完整 refresh plan 驅動 AI trigger

### 已完成

- `scan_us_overnight_impact_gaps` 現在以同一固定 `generated_at` 建立完整 `build_cross_market_refresh_plan`，並投影 machine-readable `refresh_decision` 與原始 bounded plan。
- AI tool trigger 以 `refresh_decision.should_execute` 為優先 owner；只有 `planned_source_count > 0` 才加入 `cross_market.refresh_context`。
- Deferred／cooldown source 仍使 freshness 非 current、保留 missing／warning 與 plan metadata，但 `refresh_recommended=false`，不產生 no-op tool loop。
- Legacy `refresh_symbols` 保留給既有 overnight compatibility route；AI composite path 不再以該 US-daily-only 清單判斷 FX 是否需要刷新。
- `attach_us_overnight_gaps_to_tw_stock_freshness` 已拆分 currentness 與 executability：不可立即 refresh 不代表資料 current。

### 驗證證據

- FX-only stale regression：TSM 與美股核心日線 current、完整 plan 只含一筆 `resource_quote:USD-TWD`，AI trigger 正確為 planned。
- Deferred-only regression：同一 FX source 進 300 秒 failure cooldown，freshness 保持 stale、tool steps 為空、deferred reason 可讀。
- `test_cross_market_refresh.py`、`test_overnight_impact.py`、`test_ai_tool_boundaries.py`、`test_cross_market_ai_contract.py`：`41 passed, 2 subtests passed`。
- 測試皆為 in-memory／mock；未呼叫真實 provider、未寫 live DB、未重啟 runtime。

### 下一步

- 進入 M4.2：比較 materialized snapshot 與 current local input lineage，修正 current projection 被舊 snapshot 截走，同時保留 historical replay。

## 2026-08-09 M4.2：Current projection 與 historical replay 分流

### 已完成

- ADR parity freshness additive 保存 `adr_parity.input_lineage.v1`：relation identity、ADR daily、FX quote、台股 reference／comparison 的 provider、日期、available/fetched time 與值。
- Canonical context 建立 `cross_market.input_lineage.v1` 與穩定 hash，涵蓋 relation/evidence versions、methodology、direct inputs、proxy source／benchmark、freshness state 與 missing。
- `read_cross_market_target_context` 新增明確 `current`／`replay` 模式；public route 有 `decision_at` 時使用 replay，Stock detail／一般 Ask 使用 current。
- Current 模式固定重建 local projection，確保 FX age、expected date 與 freshness 依查詢時間重新計算；lineage 相同時只附 matching snapshot reference，不回舊 snapshot payload。
- Materialized lineage 落後時回 `latest_local_cache` 與 `materialized_snapshot_superseded_by_local_inputs`，並保留舊 snapshot ID/cutoff/hash 作稽核；read path 不 refresh、不 materialize、不新增 DB row。
- Replay 模式維持 immutable snapshot、hash 驗證與 `available_at <= decision_at` 邊界。

### 驗證證據

- 舊 8/4 snapshot／新 8/7 ADR fixture：current 回最新 local projection，historical replay 仍回原 snapshot，snapshot row count 維持 1。
- 相同 input fixture：current 重新投影 freshness，並以 `matching_materialized_snapshot` 連回 immutable snapshot。
- 無新 row 但 FX 年齡跨過 72 小時 fixture：current 由 ready 正確降為 stale，不沿用舊 ready snapshot。
- ADR parity、context、point-in-time、golden、overnight、AI contract：`54 passed, 138 warnings, 2 subtests passed`。
- AI outward／decision envelope／market-context projection：`105 passed, 17 subtests passed`。

### 下一步

- 進入 M9.3：先跑 backend safe validation，再依正式 launcher/runtime 做 2330、2408、HTTP、MCP 與 ChatGPT host 分層驗收。

## 2026-08-09 M9.3：分層驗收進行中

### 已完成

- Backend safe validation 已完成：compileall、完整 backend pytest 與 `git diff --check` 均通過；pytest 結果為 `1644 passed, 801 warnings`，log 位於 `.tmp/validation/20260809-230638`。
- MCP Control Center 正式狀態為 `Ready 6/6`；`omi_search` core PID `5832`、tunnel PID `56164`，owner 與 managed PID 均符合預期，upstream probe 為 ready。
- Local MCP protocol smoke 完成 `initialize -> tools/list -> omi.ask`：protocol `2025-06-18`、session preserved、6 tools、`omi.ask isError=false`、contract `omi.decision.v4`。
- 2330 的 MCP evidence 同時投影 exact 五項 capability：`target.identity`、`cross_market.overnight`、`cross_market.relations`、`cross_market.parity`、`data.freshness`。
- Backend `/api/ai/tools` 與 local MCP `tools/list` 的 include／required enum 均為 57 項，且 overnight／relations／parity 三項全部存在；adapter/schema 層沒有缺欄。
- 正式 8400 listener ownership 已以提升權限唯讀 probe 確認：PID `52680`，command 指向 repo `.venv` 與 `uvicorn app.main:app`，parent／grandparent lineage 進入 launcher-owned service runner。

### 尚未通過的 deployment gate

- 8400 process 啟動時間早於本輪 M2.2／M4.2 source 修改，代表性 API 亦證明它仍是舊 runtime：2330 current context 回 `projection_source=materialized_snapshot`，沒有 `input_lineage_hash`；overnight response 沒有 `refresh_decision`。
- 因正式 runtime 尚未採用新碼，本輪沒有執行 FX bounded refresh，也沒有把舊 runtime 的 provider 結果當成 M2.2 acceptance。
- 台北時間 `2026-08-09 23:12` 的 2408 預設查詢仍為 `not_applicable`；正式 canary 依計畫必須等 `2026-08-10 08:00` 後再執行，不能以明確未來 `as_of` 取代預設牆鐘邊界。
- ChatGPT host schema cache 尚未做 Refresh Actions／reconnect acceptance；backend/local MCP schema 已正確，因此後續若 host 缺欄應分類為 host cache，不修改 thin adapter。
- `computer-use` skill 要求先讀 `sky.documentation(...)`，但本機載入的 `@oai/sky` 沒有該方法；依 skill 安全規則未盲目操作 tray，也未直接終止 launcher-owned PID。

### 下一步

- 從 OMI tray 執行一次 `Restart Services`；重啟後重新確認 launcher selected port、PID replacement、health、2330 current projection／refresh decision、HTTP／MCP outward parity。
- `2026-08-10 08:00` 後執行 2408 預設查詢 canary，再做 ChatGPT Refresh Actions／reconnect 與代表性 call；兩項完成後才能把 M9.3 標記完成並恢復 M7／M8。
