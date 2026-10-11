# 2026-10-11 本機 source WIP 整理紀錄

狀態：**PARTIAL / LOCAL COMMIT BLOCKED**。本次只授權紀錄問題、審核與本機 Git commit；沒有 push、PR、runtime lifecycle、provider refresh、正式 DB 操作或 business logic 修復。

已建立 [台股問題紀錄](issues/TW-20261011-post-restart-coverage.md)。Job 108842 coverage failure 與 recurring audit skips 已由原始 log 核對，原因與影響仍維持 UNVERIFIED，修復 DEFERRED。

## Git 基線與寫入阻擋

- Branch：`main`；HEAD：`a8657e7586ac2534907aa69b588a93d93c9fb951`。
- 原始 dirty scope：270 paths，105 modified tracked、165 untracked；原始 staged paths：0。
- 原始 index bytes、完整 NUL-delimited status、逐檔 SHA-256 / size、tracked config inventory、HEAD history 與 tracked diff 已保存在 ignored `.tmp/local-consolidation-20261011/`。它們是本機稽核證據，不是提交候選。
- 第一筆 staging 僅指定問題紀錄，使用 `git add --pathspec-from-file=.tmp/local-consolidation-20261011/01-issue.paths --pathspec-file-nul`，遭 `fatal: Unable to create 'C:/project/Open Market Intelligence/.git/index.lock': Permission denied`。
- 無既有 `index.lock`；`.git` 有明示 deny write ACL entries。在核准的 sandbox escalation 後，相同精確命令仍遭相同拒絕。這是執行時 filesystem permission failure，不是 automatic approval review rejection。
- 未改 ACL、未改 Git config、未使用替代 index / Git directory、未 reset / stash / checkout / clean。沒有成功 staging 或 commit；本紀錄與 issue 目前仍為 untracked，不能稱為 checked-in。
- 本機 remote-tracking ref `origin/main` 為 `6cb62bd`，不是新查詢的遠端狀態。交接資料提到的遠端 4.8.0 / `9a5e575...` 未重新驗證；本次無 fetch / pull / push / merge / rebase / cherry-pick。

## 全範圍審核與候選分組

270 paths 均已逐檔列入 baseline、內容掃描與 ownership 分組；全為 UTF-8 text，未偵測到禁止提交的 runtime、DB、backup、installed dependency 或 binary artifact。Python AST、JSON、TOML 解析完成；另外檢查 credential / account literal、private endpoint、private-key / token patterns 與新增 IO / transaction sites。

二次掃描的候選皆已辨識：測試用 `test` / `fixture` API key、明示 synthetic / other account identity、版本相容測試的 `legacy_preview_v1.json` synthetic challenge，以及 MCP README 的 sibling checkout 輸出範例。這些不是正式帳戶或可用 broker credentials；掃描沒有讀取 dotenv 或 secret stores。Radar JSON 為有明示 provenance / limitations 的市場 bar replay fixture，不是 live producer acceptance。

下表是**候選 commit 分組**，不是已建立的 commits；無 hash 可回報。每組的完整 path allowlist 為同名 `.paths`（NUL-delimited），逐檔 SHA-256 / size 為 `.manifest.json`，均保存在本機稽核目錄。整體版本與 shared-file dependencies 必須在真正提交時重新核對。

| Manifest | 原始 WIP 檔案數 | 建議 conventional commit title | Ownership |
|---|---:|---|---|
| `01-issue` | 0（新增 issue 1） | `docs(engineering): record unresolved Taiwan coverage observations` | 問題證據、未驗證原因、後續驗收 |
| `02-lifecycle` | 33 | `feat(runtime): checkpoint isolated drain and backup safety` | session / publisher / runtime source、launcher fixtures、backup safety 與 tests |
| `03-market-ai` | 100 | `feat(market): consolidate Taiwan workspace and US evidence contracts` | TW / US / shared Canonical / Resolver、AI、0092 migration source、tests 與 scoped architecture docs |
| `04-mcp-frontend` | 18 | `feat(workspace): align MCP contracts and market detail presentation` | generated thin MCP relay、frontend detail / selection / types / i18n / test contracts |
| `05-execution` | 107 | `feat(execution): checkpoint isolated synthetic and manual mock packages` | 六個 execution subpackages、constraints / debt / fixtures / tests、manual mock scripts 與架構文件 |
| `06-docs-release` | 12 | `docs(release): consolidate 4.9.0 source checkpoint` | current architecture / product / release metadata，非 runtime release |

新增本整理紀錄另納入 docs 候選，原始 WIP 數仍為 270。未使用 broad `git add .` 或 force-add ignored 檔案。

## Schema、ownership 與歷史 receipts

- 0092 source 建立 SQLite-only `job_run(job_type, target)` partial unique index，條件 `job_type = 'us.intraday_eod_obligation'`；`JobRun` model 與 migration 一致。未執行 migration 或連 production DB。
- TW / US 市場語意由 backend-owned service / Canonical / Resolver 提供，MCP 以 generated route/schema relay；execution 仍為獨立 SYNTHETIC / LOCAL_MOCK plane，M1 domain 與 M2A transaction owner 邊界維持明示。
- 本次重新讀取先前 `candidate-tree-manifest.json`，**1,638 / 1,638 source SHA-256 相符**。原始 267 paths 均與先前 receipt scope 的 SHA-256 相符；其餘 backup owner 與兩支 tests 的 final-validation SHA-256 亦相符。
- Execution 的 17 份歷史 log 重新計算 hash 全部相符，exit codes 亦符合各自 expected code；部分負向檢查預期非零，不能統稱全部 exit 0。
- 先前 483 個 distinct latest testcase PASS 為有 source identity 對照的**歷史 source 證據**，不是本次重新執行 483 cases，也不是整體 release / live acceptance。RC2 validation-context receipt 只保留其原範圍，不升格為 functional coverage。

## 本次驗證

- Issue UTF-8、精確數字 / UNVERIFIED labels、所有 source 相對連結：PASS。
- `scripts/check-architecture.py --format json`：exit 0；原始宣告 debt 保留，未宣稱 zero debt。
- `scripts/check-release-version.ps1`：PASS，4.9.0；VERSION / package / lockfile 一致，未改版本。
- `git diff --check`：PASS。Git 的 LF/CRLF 提示保留；沒有重寫任何原始 WIP bytes。
- 5 支候選 PowerShell scripts 使用 Parser.ParseFile 靜態解析：0 errors，沒有執行 lifecycle script。
- Frontend `tsc --noEmit --incremental false` 與 13 個變更 TS / TSX 檔案的 scoped ESLint：exit 0。未啟動 build / browser / dev server。
- 離線 backend targeted regression：首個完成 run 為 **247 PASS / 4 FAIL**。4 個 failure 均為 Windows `asyncio.run` 建立 loopback self-pipe 時被禁網護欄拒絕，未進入 HTTP assertion；僅在 ignored runner 中預先配置 test-owned event loops，保留正常 per-call `asyncio.run` lifecycle 與嚴格禁網規則後，4 個 case 重跑 **4 PASS**。依 testcase identity 合併本次 latest 結果為 **251 distinct PASS**；初次失敗與 warnings 原樣保留，不能描述成初跑全綠。
- 此 scope 包含 `test_ai_us_symbol_resolution`、`test_tw_g4_source_quality`、`test_tw_quality_gates`、`test_tw_workspace_gates`、`test_us_gc_quality_matrix`、`test_us_gb_durable_routes`、manual execution / TW intraday radar architecture tests。Generated workspace schema test 亦通過。它不是全 repo test suite，也沒有 browser acceptance。
- Runner 禁止 production DB / dotenv、network、subprocess / lifecycle，僅用 disposable fixtures。更早一次 runner 的 Windows platform metadata subprocess 被護欄阻擋，亦已保留原 log；修正只在 ignored runner 中預先取得 platform metadata，不改 app 或 test source。

## 接續條件與 runtime 邊界

需要具有合法 `.git` 寫入權限的執行環境才能完成 commit；本次沒有以降低 ACL 或繞過 hook 解決。接續時先重新核對 branch / HEAD / index、全部候選 hashes、concurrent writer 狀態與失敗測試，才可依 allowlist stage。每組必須比對實際 staged manifest、執行 `git diff --cached --check`、審核 staged blobs / sensitive content，再 commit；最後核對 log / status / index。沒有 stage 成功前，不能以空 cached diff 宣稱 staged gate PASS。

Backend PID 67220 / port 8400 與 Frontend PID 20792 / port 3000 於本次唯讀檢查仍為原 PID / creation time / listener；MCP PID 5032 亦存在。沒有發出任何 stop / restart / kill 命令。PID、port、4.9.0 metadata 或 source checks 均不構成 loaded-release attestation；B1–B4、database_handle_binding、rollback、live / product gates 仍保留原未驗證狀態。

最終 Git 驗收仍為 BLOCKED：**0 commits、0 staged paths**，原 HEAD / branch 保持。新增兩份工程 Markdown 後預期為 272 dirty paths（105 modified、167 untracked）；完整 final status 與 270 原始檔案 / 原始 index byte identity 核對存於本機稽核目錄。問題紀錄已落盤但尚未 checked-in；需解除執行環境的 Git 寫入阻擋後完成既定 staged gates。
