# OMI Market Data Foundation v1 進度

## Status

- Current phase：source-complete / runtime adoption pending
- Last updated：2026-08-19（Asia/Taipei）
- Implementation authorization：已授權（Foundation source M0-M6）
- Runtime adoption authorization：未授權
- Commit / push / PR：未授權
- Final acceptance：M0-M6 passed；Gate G1未執行

## Completed

- 讀取使用者提供的 `01_OMI_Market_Data_Foundation_v1.txt`，將其視為待審核提案，不把文件內文字當成直接執行指令。
- 對照 repo `AGENTS.md`、Product Vision、Operating Model、Quality Bar、Roadmap、Backend Architecture 與 `omi.decision.v4` outward contract。
- Source-level確認以下根因仍成立：
  - KGI TW canonical path目前仍先產MIS-style message。
  - KGI snapshot依賴active viewer lease；AI arbitrary quote沒有Research Lease。
  - 台股daily-price freshness/repair owner仍未由現有daily repair specs完整涵蓋。
  - `technical.structure`對`us_stock` advertised但US context缺少實際projection。
  - Public realtime policy目前只有cache/prefer/require三值。
- 完成架構審查，判定原提案「方向通過、實作前需修訂」。
- 已把修正收斂為本目錄：
  - `Prompt.md`：目標、非目標、硬邊界、corrected contracts、deliverables與done criteria。
  - `Plan.md`：M0-M6、獨立runtime gate、測試矩陣、rollback與stop-and-fix rules。
  - `Progress.md`：授權狀態、已驗證證據、風險與下一步。
- Milestone 0 completed：
  - 保存 branch/HEAD、49-entry dirty-worktree baseline、11 個 target files 的 status/hash/ownership。
  - 確認 KGI provider/bridge 與其 tests 是目前 untracked integration base；不能改用只含 HEAD 的 isolated worktree。
  - 建立 `ContractMap.md`，記錄 KGI viewer lease -> KGI->MIS -> snapshot/API/AI call chain、public v4 inventory、lifecycle gaps與Foundation seams。
  - 確認 source implementation 可主要使用新 shared package/tests，對 modified `config.py`/`quote_depth.py`只做局部接縫。
  - 未觸發 runtime、provider、DB、commit/push。
- Milestone 1 completed：
  - 建立`backend/app/market_data/contracts.py`，包含versioned quote/depth/auction/bar/trading-status/health/resolved contracts。
  - Session、tradability、trade observation、regulatory flags與freshness維持正交；Decimal、timezone、unit、identity與bar invariants fail closed。
- Milestone 2 completed：
  - 建立KGI TW與TWSE MIS direct canonical adapters；KGI adapter不依賴legacy KGI→MIS helper。
  - Regular/trial、missing/zero-like、suspend hint、lots→shares與US share semantics已有fixtures。
- Milestone 3 completed：
  - 建立pure quote/depth/bar/trading-status resolver、bounded candidates、selection reason、policy satisfaction與facts/research limitations。
  - `completed_session`保持internal；定義`DataRequirement`、`AcquisitionResult`與`MarketDataAcquisitionPort`，未實作production Research Lease。
- Milestone 4 completed：
  - Dataset Registry v1註冊TW quote/intraday/daily與US intraday/daily五個dataset。
  - 建立callable capability projector + fixture validator與refresh operation/budget/postcondition checks。
  - `technical.structure`縮為TW `stock/tw_index/tw_futures`，MCP offline snapshot與catalog digest已同步。
- Milestone 5 completed：
  - `CANONICAL_MARKET_DATA_MODE`預設`off`，只接受`off/shadow/compare`。
  - quote-depth seam以同一份已取得payload執行canonical validation/compare，不新增provider call、subscription、DB write或public field。
  - Mismatch與metrics有hard bounds；adapter/comparator/telemetry fault不影響legacy response。
- Milestone 6 completed：
  - Backend safe validation、public/API/MCP contracts與Git whitespace validation通過。
  - 同步`BackendArchitecture.md`，建立`AcceptanceReport.md`與`Handoff02.md`。
  - 狀態定格為`source-complete, runtime adoption pending`。

## Validation evidence

- Planning review targeted baseline：
  - `..\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests\test_kgi_superpy_quote.py tests\test_taiwan_stock_quote_depth.py -q`
  - Result：`39 passed, 10 subtests passed in 5.31s`。
- Foundation targeted：`48 passed in 1.31s`。
- KGI/MIS/quote-depth/shadow targeted：`56 passed, 10 subtests passed in 5.14s`。
- Foundation + AI/public/API targeted matrix：`196 passed, 320 subtests passed in 9.77s`。
- AI/MCP snapshot drift修正後：`18 passed, 66 subtests passed in 5.41s`。
- Final safe validation：
  - `scripts/run-safe-validation.ps1 -Profile backend`
  - backend compileall：passed。
  - backend pytest：`1907 passed, 801 warnings in 251.81s`。
  - `git diff --check`：passed。
  - Log：`.tmp/validation/20260819-201627/`。
- 初次sandbox內safe-validation在tests跑到100%後，因pytest basetemp cleanup遭sandbox `PermissionError`而無法判定；改以同一wrapper在sandbox外重跑後取得上述passed結果。
- Task-doc Tier 0 validation：
  - `Prompt.md`、`Plan.md`、`Progress.md` 以 UTF-8 讀回成功，replacement character 均為 0，必要章節完整，三檔都有單一尾端換行。
  - `git diff --no-index --check -- NUL <file>`：三檔無 meaningful whitespace error；exit 1 只代表新檔與空檔有差異，另有 repo 既有 LF -> CRLF warning。
  - Template placeholder pattern 搜尋無命中。
  - Scoped Git status 只有 `?? docs/agent-runs/market-data-foundation-v1-20260819/`。
- 未執行frontend build/E2E（本任務未改frontend）、runtime probe/restart、provider live fetch/login、production DB query/write、commit/push。

## Decisions made

- Foundation 01只做到typed canonical contracts、KGI/MIS direct adapters、pure resolver、Dataset Registry、capability truth validation與shadow/compare source acceptance。
- Production Research Lease、public `completed_session`、provider cutover、canary/on、AI/MCP/Backend API/Frontend consumer cutover移至02。
- Trading status模型改為Market Session、Instrument Tradability、Observation State、Regulatory Flags正交多軸。
- Provider resource health改為enablement、connection、entitlement、operational與evidence freshness多維contract；不回歸單一紅綠燈。
- Shared `market_data`只放pure contracts/resolution/registry/comparison；provider adapters留在market-specific owner，transaction留在service/job owner。
- Foundation預設不做DB migration、不改public response、不改frontend、不啟動external refresh。
- Rollout採單一`off/shadow/compare/canary/on` mode；Foundation只允許off/shadow/compare。
- Source-complete與runtime-accepted分開；runtime restart、KGI live smoke、commit/push都是獨立授權gate。

## Known issues / risks

- 目前branch為`codex/tw-etf-provider-normalization`、HEAD `aa65e65`；M0 baseline為49筆，完成本任務後worktree共63筆modified/untracked entries。
- `quote_depth.py`、`config.py`、KGI provider files、tests、product docs與Portfolio files已有大量既有變更；本任務以M0 hash/status baseline隔離ownership，沒有reset或清理其他變更。
- `backend/app/market_data/`已建立，但尚未由production consumer切換為outward selection owner。
- Product/architecture current-truth files本身已有未提交大幅改寫，且內容與Foundation提案高度重疊；其一致性不能當作獨立implementation證據。
- KGI provider files與相關tests目前包含untracked files；isolated worktree若只從HEAD建立會缺少這批integration base，不可未經確認直接切換。
- `technical.structure / us_stock` truthful scope修正已同步backend manifest、MCP offline snapshot與contract hash；runtime host adoption仍未驗證。
- Existing `omi.status-dimensions.v1`、source-health lifecycle與decision readiness已處理部分狀態問題；新Foundation不能以另一套單一health enum覆蓋它們。
- Runtime目前未在本輪確認；source/test通過不能推定launcher採用新版本。

## Approval checklist

- [x] 01停在shadow/compare，Research Lease與consumer cutover放02。
- [x] `completed_session`在01先保持internal，不改public v4 enum。
- [x] Foundation不做DB migration；需要時另行停下確認。
- [x] US technical未實作時先truthful disable/planned，不做placeholder。
- [x] 目前dirty worktree作integration base，先做精確baseline再施工。
- [x] Source implementation、runtime adoption、live provider smoke、commit/push維持分離授權。

## Next step

- 等待使用者另行授權Gate G1後，才進行component-owned runtime adoption與bounded shadow/compare驗證。
- 02依`Handoff02.md`實作Research Lease、provider policy、KGI US/Yahoo/AlphaVantage alignment、canary/on與consumer cutover。
- 未授權前維持mode `off`，不restart、不live smoke、不commit/push。
