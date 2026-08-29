# Progress

## Status

- Current phase：Track A Pre-Core foundation complete；G0 handoff blocked。
- Current label：`US_PRE_CORE_FOUNDATION_READY`。
- Target label：`US_MARKET_DATA_PLATFORM_PRODUCTION_CONVERGED`。
- Last updated：2026-08-25 Asia/Taipei。
- Track：A0–A3／M0–M3已通過；B1–F3／M4–M9等待G0 Shared Core Readiness Gate。
- Authorization：使用者已授權將本task作為長專案並執行Pre-Core底層整理；未授權runtime restart、external provider smoke、DB migration/data mutation、commit、push或release。

## Completed

- 讀取兩份使用者附件，並明確將其視為待驗證proposal而非直接執行指令。
- 讀取repo AGENTS、ProductVision、OperatingModel、QualityBar、Roadmap、BackendArchitecture與OmiDecisionContract current truth。
- 完成US market-data source dependency audit，區分：
  - 已存在的provider descriptors、pure canonical adapters、Resolver/projection、cache-only resolved daily reads。
  - 尚未production-wired的Shared Control Plane／provider port／Dataset operation binding。
  - 仍由legacy `app.us_market.service`擁有的daily/intraday IO、fallback、chart refresh、AI tool與consumer path。
- 確認public router、AI、Frontend、full-market repair與dirty OHLC priority scheduler仍存在provider selection leakage。
- 確認現有`DataRequirement`與Dataset Registry是可重用prototype，但尚未滿足附件所需完整Data/Refresh Integration Contract。
- 建立Pre-Core與Post-Core兩段milestones、G0 readiness checklist、validation matrix、stop-and-fix與rollback條件。
- 對齊同日台股umbrella task `tw-market-data-platform-convergence-20260825`；它目前是planned/audited，不視為Core handoff已完成。
- 將美股工作擴成可續跑長專案控制面：
  - `ArchitectureMap.md`：current/target graph、ownership、asset disposition與gap map。
  - `WorkBreakdown.md`：A0–F3 packages、dependencies、acceptance、validation與file ownership。
  - `CoreHandoffChecklist.md`：G0-01至G0-15、台股handoff packet與US compile-only probe。
  - `AcceptanceMatrix.md`：planning、Pre-Core、Core、daily、lifecycle、realtime、consumer、closure狀態。
  - `RiskRegister.md`：24項active risks與automatic blockers。
  - `CutoverRunbook.md`：per-capability off/shadow/compare/canary/on、evidence與rollback。
- 明確決定「一次拉好」是完整scope、單一program與completion rule，不是Big Bang source rewrite或一次切production。
- 完成A0 baseline封存：`artifacts/A0Baseline.md`固定branch、HEAD、41個dirty entries、21個相關檔案SHA-256、ownership graph、contract snapshot與pre-edit test evidence。
- 完成A1 consumer/provider boundary guard：
  - 新增AST/import/frontend request guard，禁止product consumer、scheduler與shared layer擴張US provider selection。
  - 既有AI、full-market EOD、legacy job與US context debt採具名module/function allowlist，不使用脆弱行號。
  - `app.market_data.eod_coverage -> app.us_market.service`維持唯一具名Shared reverse-dependency debt，等待M6移除。
- 完成A2 legacy expansion quarantine：
  - Frontend US detail與regional tape不再指定Yahoo；移除開頁自動provider-specific OHLC repair。
  - 新OHLC repair改為明確diagnostic provider route，不再是product repair route。
  - priority OHLC scheduler source default off；即使手動啟用也只執行cache-only audit，`external_call_count=0`，缺口標`shared_core_refresh_unavailable`。
  - priority dataset在G0前明確`refreshable=False`／`repairable=False`；不宣稱不存在的operation binding。
  - cache-only priority audit不再延後或阻擋full-market EOD lifecycle。
- 完成A3 US market-data handoff package：
  - 建立`app.us_market.market_data` descriptors、pure adapters、candidate store、projection、integration manifest與legacy quarantine seam。
  - Candidate reader一次保留所有provider records、source/hash/fetched lineage，不接受provider selector、不做selection/fallback、不寫DB，transaction仍由caller擁有。
  - Integration manifest明確`production_binding_available=False`、`shared_core_contract_version=None`、`handoff_gate=G0`；未建立猜測版resolver、fallback executor或`bindings.py`。
  - Generic capability skill曾建議service-owned fallback；因與repo較新的架構憲法衝突，本task採repo current truth：fallback與final selection只由Shared Core擁有。

## Validation evidence

- `git status --short`：branch `codex/tw-etf-provider-normalization`、HEAD `6d508c7021c1050680262ce4a83f5b33e9f5eda7`，目前41個modified/untracked entries；本輪不revert、不覆寫，新增範圍只限本task docs。
- Attachment SHA-256：US proposal `ecc996c57da5a3131ef82a081cbbb344c5d78226244ed5f583dddefd9c7a8c2a`；Core proposal `65e1b217aa3e4bbfaf9c31a7740d9bb3ed6ad605369742ac004f521f0eca3ce9`。
- `rg -n "build_us_acquisition_plan|execute_acquisition|ResearchAcquisitionPort" backend/app backend/tests`：US acquisition plan與control plane沒有production US port caller。
- `rg -n "provider.*(yahoo_chart|alphavantage)" backend/app frontend/src`：確認router、AI、Frontend、scheduler/repair與legacy service存在provider leakage。
- `rg -n "RefreshRequirement|DataRequirement" backend/app`：repo只有現有`DataRequirement` prototype，沒有附件所述final `RefreshRequirement`。
- `git diff`／source readback：dirty OHLC continuity/repair新增provider-specific path與default-enabled priority scheduler；未做runtime adoption判定。
- 2026-08-25 Tier 0 strict UTF-8 readback：9份task docs全部通過，replacement character=0、trailing whitespace=0。
- Structure scan：確認Prompt／Plan／Progress必要章節、A0–F3、M0–M9、G0-01至G0-15、AcceptanceMatrix、RiskRegister與CutoverRunbook皆存在。
- Internal reference check：所有backticked `.md` references都能解析到本task或repo現有文件。
- `git status --short -- docs/agent-runs/us-market-data-core-integration-20260825`：本task範圍只有新建文件，沒有production source。
- `git diff --check`與逐檔`git diff --no-index --check`：沒有whitespace error；只出現既有LF/CRLF conversion warnings。
- 初始planning pass是Tier 0 docs-only；本次Track A實作已升級為Tier 3 targeted backend/frontend驗證，仍不執行runtime或external smoke。
- A0 baseline targeted suite：設定`PYTHONPATH=backend`後`74 passed in 4.12s`；第一次未設定`PYTHONPATH`只產生10個collection import errors、0 tests executed，已在baseline artifact如實記錄。
- A1/A2 targeted regression：`51 passed, 60 subtests passed in 7.79s`。
- A3 package／boundary／canonical／policy／projection：`36 passed in 3.25s`。
- Track A latest cumulative backend regression：`97 passed, 60 subtests passed in 9.44s`。
- Safe validation backend profile：compileall passed、targeted pytest passed、`git diff --check` passed；artifact=`.tmp/validation/20260825-183027`（該次為新增最後一個fallback guard前的96-test run，最新97-test結果如上）。
- Frontend targeted ESLint：`USStockDetailPanel.tsx`與`useRegionalMarketTapeState.ts`通過，exit 0。
- Frontend TypeScript：`node_modules/.bin/tsc.cmd --noEmit`通過，exit 0。
- 所有驗證均使用fixture、in-memory SQLite或source scan；external provider calls=0、production DB mutations=0、runtime restart=0。

## Decisions made

- 不在Shared Core完成前建立US-only `DataRequirement`／`RefreshRequirement`或第二套operation dispatcher。
- Pre-Core優先處理boundary guard、package ownership、provider adapters、candidate store與legacy quarantine；不切production truth path。
- Integration必須先通過G0；台股Core只有source skeleton、dark path、unit prototype或未達`TW_MARKET_DATA_PLATFORM_PRODUCTION_CONVERGED`時仍視為blocked。
- G0以能力與證據為準，不綁附件猜測名稱；final Core若改module/type/version，US只調整binding，不複製compatibility Core。
- 每個capability/dataset獨立rollout與rollback；完整專案範圍不等於全域flag或全市場同時切換。
- US authority datasets保留market-specific domain；只有cross-provider quote/intraday/daily capabilities強制進Shared Core。
- 現有`USDailyPrice`可先作provider-coherent candidate store；任何lineage schema不足另走migration審查，不在架構整理中silent drift。
- Pre-Core manifest只描述US可交付資產，不具有production registration side effect；G0通過後才依final Core contract建立binding。
- 產品Frontend provider selector已先歸零，但legacy API／AI provider compatibility不在G0前強拆；由architecture allowlist鎖定，不得新增caller。

## Known issues / risks

- Dirty worktree同時包含台股Foundation與US OHLC continuity/repair變更；後續實作必須逐檔辨識ownership，不能假設全部可重寫。
- Priority OHLC scheduler source已default off且workflow為zero-I/O audit；runtime尚未restart/adopt，因此只宣稱source-ready，不宣稱live runtime已採用。
- Shared `app.market_data.eod_coverage`目前直接import US legacy service，是需要在M6消除的reverse dependency。
- Legacy daily refresh／OHLC product provider selector可能有repo外consumer；已由具名allowlist凍結，移除前仍需caller inventory與compatibility策略。
- 新candidate seam目前是read-only legacy-store adapter；final canonical write/repository transaction contract等待G0，不自行猜測。
- Existing canary/runtime結果屬歷史證據；進入M9前必須重新以當下launcher selected PID/port/mode驗證。

## Blockers

- G0／M4–M9：等待台股側Shared Market Data Core final contracts、registration/binding API、operation dispatcher、transaction ownership、actual-data/runtime/rollback evidence與`TW_MARKET_DATA_PLATFORM_PRODUCTION_CONVERGED`通過`CoreHandoffChecklist.md`。

## Next step

- 等台股Shared Core交付完整handoff packet後執行G0-01至G0-15與US compile-only fake-port probe；任一項不通過就維持B1–F3 blocked，不新增US-only Core或production shim。
