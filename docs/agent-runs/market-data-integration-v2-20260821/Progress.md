# Progress

## Status

- Current phase：`done`
- Current label：`02A_SOURCE_COMPLETE_DARK`
- Last updated：`2026-08-21 23:34 +08:00`
- Gate P：completed。
- Gate S：completed；使用者已授權並完成02A dark source implementation。
- Gate B：locked；Foundation 1.1尚未closure，02B不可執行。
- Gate C：not authorized；未commit/push。

## Completed

- 已讀取並審查原始附件；附件SHA-256=`f39b0809371f540dd857dc2de1742f0264877e638406786bb204890479fd54bc`。
- 已對照repo `AGENTS.md`、product current truth、Backend Architecture、Foundation Handoff02與現有market-data contracts。
- 已確認Foundation 30-target source baseline與`99f95233...` reference仍一致，但同一source已知存在`CLOSING_AUCTION_TRIAL_LEAKAGE_IN_REALTIME_STREAM`，不可作closure-eligible fingerprint。
- 已依OMI market capability checklist建立`CapabilityContract.md`。
- 已建立`artifacts/02a-source-baseline.json`：Foundation 30/30 mismatch=0、protected mismatch=0、production imports=0。
- 已完成pure `provider_policy.py`：injected descriptors、多維health、zero-I/O policies與route/call/subscription/deadline bounds。
- 已完成`research_lease.py`：non-blocking poll、cooperative cancellation、owned idempotent release、outcome/cleanup正交狀態與unknown activity truth。
- 已完成`control_plane.py`：bounded routes、canonical candidate collection、no cross-provider merge、cleanup-before-return，且不輸出final selected provider。
- 已完成allowlist `acquisition_observability.py`：不序列化snapshot、raw limitation、exception原文或private identity。
- 已完成test-only `market_data_fakes.py`與五個02A test files。
- 已完成AST dark import、protected hash、Foundation 30-target hash與package export guards。
- 已建立`artifacts/02a-source-manifest.json`與`artifacts/02a-validation.json`。

## Validation evidence

- Repo：`C:\project\Open Market Intelligence`。
- Branch：`codex/tw-etf-provider-normalization`。
- HEAD：`aa65e65424f2d5de7255c4168a18ded9f8794301`。
- 02A targeted：`65 passed in 2.25s`。
- Market Data/AI boundary相關回歸：`136 passed in 11.58s`。
- Official backend safe validation（正常Windows權限層）：compileall passed、`1980 passed, 801 warnings in 233.43s`、`git diff --check` passed。
- Authoritative validation log：`.tmp/validation/20260821-232937`。
- Restricted runner第一次full suite跑至100%後，pytest只在session-finish清理basetemp時因WinError 5失敗；正常Windows權限層以新basetemp重跑exit 0，未將restricted failure偽裝成pass。
- Final isolation：Foundation 30/30 mismatch=0、protected mismatch=0、unexpected production import=0、`backend/app/market_data/__init__.py` unchanged。
- Source manifest：10 files、combined SHA-256=`10923e7aaff8d8fb58ae03a8b97ee1f15db9f938060c20b55b30f48b8bcecca0`。
- Side effects：real provider calls=0、real Research Lease=0、runtime mutations=0、DB writes/migrations=0、Account/Order=0、commit/push=false。

## Decisions made

- `99f95233...`只保留為02A freeze reference；已知closing defect存在，因此不可再當成Foundation closure-eligible fingerprint。
- Foundation closing fix、新checkpoint與正式session gates由獨立track處理；02A dark工作可以保留，但不宣稱ready-for-02。
- 02A新增dark lifecycle protocol，不直接把舊one-shot acquisition port冒充Research Lease。
- Actual lifecycle seam採non-blocking `poll/cancel/release` owned handle；timeout/cancel必須證明terminal與no late callback。
- Acquisition outcome與cleanup status分開；`not_required`如實表達`cache_only/completed_session`不需要external acquisition。
- `port.start()`即使拋錯仍計入start attempt，external/subscription counts保持unknown，不假裝為0。
- Provider policy使用injected descriptors，不在shared layer硬編碼KGI/MIS production priority。
- Existing Resolver沒有generic public eligibility seam，因此02A執行plan內全部bounded routes並保留canonical candidates，不為short-circuit複製第二套selection。
- Control Plane回傳canonical candidates與attempt metadata；final selection仍由existing Resolver擁有。
- Observability採allowlist，exception原文、raw limitation與canonical snapshot不得進diagnostic artifact。
- 02A使用獨立source manifest與validation artifact，不修改Foundation checkpoint artifact。

## Known issues / risks

- Foundation 1.1仍有confirmed closing-auction trial leakage；正式Preopen、Opening、Regular、rollback與closure未完成。
- Worktree仍有大量並行modified/untracked entries；本次沒有reset、clean、revert或改動非02A owner。
- 02A只用cooperative fake ports證明generic contract；尚未證明真實KGI/MIS adapter可在deadline內cancel/release。
- 目前production import graph完全unwired；所以full backend tests證明source regression，不代表production Research Lease、runtime或市場時段驗收。
- 02B若需要short-circuit acquisition，應先建立Resolver-owned、可重用的candidate eligibility seam，不能在Control Plane內猜LIVE selection。
- Foundation若另行合法修改frozen files，02B前必須以新validated checkpoint重建reference baseline，不可沿用舊hash。

## Next step

- 02A沒有剩餘gate；維持dark/unwired。
- Foundation 1.1需在獨立track修正closing-auction leakage、建立新checkpoint並完成正式session closure。
- 只有Foundation closure與Gate B另行授權後，才建立02B真實TW provider ports與internal shadow wiring。
