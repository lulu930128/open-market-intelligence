# OMI 4.4.0 Source Consolidation Plan

## Milestones

1. Freeze與baseline
   - Scope：branch、dirty worktree、local main、version、architecture與consumer contract。
   - Acceptance：明確記錄current truth、重疊檔案與non-goals；不產生runtime／DB／provider side effect。
   - Validation：`git status --porcelain=v1 -uall`、`git rev-list --left-right --count main...HEAD`、read-only runtime GET。

2. P1 source remediation
   - Scope：TW OHLC overlay、Yahoo canonical INDEX volume、US AI selection-to-reader bound。
   - Acceptance：三個negative cases轉綠，既有新session overlay、stock／ETF volume與intraday selection行為不變。
   - Validation：targeted pytest、compileall。

3. Contract與architecture convergence
   - Scope：`omi.decision.v4` reader bound、Shared Resolver invariants、MCP／Frontend contract compatibility。
   - Acceptance：HTTP／SSE／MCP／Frontend不新增平行語意；architecture debt不擴張。
   - Validation：AI outward regressions、architecture checker／pytest、MCP snapshot、Frontend lint／typecheck。

4. 4.4.0 durable source checkpoint
   - Scope：VERSION、frontend package metadata、README、CHANGELOG、CurrentImplementationState、active plan progress。
   - Acceptance：所有version surface一致；文件分離Source／Runtime／Live／Product並保留`^SOX`限制。
   - Validation：version string scan、UTF-8 readback、`git diff --check`。

5. Exact integration closure
   - Scope：未來以local `main`建立isolated integration tree並套入exact paths／hunks。
   - Acceptance：migration、production dependency、tests、architecture、MCP snapshot、Frontend contract與docs完整；secret／DB／log／temp為零。
   - Validation：isolated staged-tree profile與staged-only scans。

## Milestone result

- Milestone 1-5 source acceptance：`completed`。
- Publication（正式stage／commit／push）：`pending_user_gate`。
- Runtime adoption／Live／Product acceptance：`pending_separate_gate`。

## Stop-and-fix rules

- 三個P1任一targeted regression失敗，先修正，不進版本與durable closeout。
- 若修正需要provider I/O、DB mutation、新migration或consumer-owned市場邏輯，停止並更新Prompt。
- 若architecture checker出現新增undeclared violation，不以更新debt manifest掩蓋，先修正依賴方向。
- 若isolated closure無法同時包含local `main`與dirty dependency，不在目前checkout broad-stage或merge。
- Runtime未restart採用前，CurrentImplementationState保持not_reverified／partial，不以source tests升格。

## Decisions

- 2026-08-29：使用者將本輪定義為4.4.0立腳點；採source consolidation而非全市場production completion。
- 2026-08-29：`^SOX`第二provider延後；truthful stale可接受，volume=0不可接受。
- 2026-08-29：未來integration以local `main` `0b7faa8`為base，避免遺失既有台股commit。
- 2026-08-29：commit／merge／push為publication gate，不由本輪source implementation自動推定。
- 2026-08-29：US `20260829_0073`已是既有production migration；TW `20260829_0073t`必須接在其後，禁止形成parallel Alembic heads。
