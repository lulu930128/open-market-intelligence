# OMI 4.4.0 Source Consolidation Progress

## Status

- Current phase：`source_consolidation_accepted_publication_pending`
- Last updated：2026-08-29 Asia/Taipei
- Source status：`accepted`
- Runtime status：`not_reverified_for_4_4_0`
- Live status：`partial`
- Product status：`partial`

## Completed

- 將附件視為merge-prep proposal，不當成自動commit／merge／push指令。
- 完成root／backend／Shared Core、product、architecture、AI decision contract與Git topology preflight。
- 確認三個P1仍存在，並以cache-only runtime GET重現TW overlay與`^SOX` point volume矛盾。
- 確認current checkout等於`origin/main`，local `main`另有24-file commit且兩個檔案與dirty worktree重疊。
- 將本輪範圍凍結為4.4.0 Source Consolidation；`^SOX`第二provider與新功能延後。
- 修正三個P1並新增TW same-date finalized、Yahoo INDEX zero-volume、US normalized selection 260 reader-bound regression。
- 更新4.4.0 VERSION／Frontend package metadata／README／CHANGELOG與durable architecture／active progress truth。
- 將local `main`的TW intraday read index／repository read optimization納入exact integration closure，且保留current checkout的US Daily lineage欄位。
- 將migration線性化為`20260826_0072 -> 20260829_0073 -> 20260829_0073t`；既有已套用US `0073`的環境仍會正確執行TW index migration。
- 以local `main` `0b7faa8`為base建立alternate Git index與隔離source tree；真正index維持空白，未commit、未push。

## Validation evidence

- `git status --porcelain=v1 -uall`：114 modified、1 deleted、91 untracked；index空白。
- `git rev-list --left-right --count main...HEAD`：`1 0`。
- `GET /api/market/ohlc/3711?...include_intraday=true`：finalized 8/28仍被同日provisional overlay取代。
- `GET /api/us-market/ohlc/%5ESOX?...`：top-level `not_applicable`，但latest point volume仍為0。
- 三個P1 fixture：`23 passed`。
- Shared／TW／US／AI affected matrix：`282 passed / 27 subtests passed`。
- AI／API／US boundary補充matrix：`54 passed / 64 subtests passed`。
- Architecture：checker PASS，`22 actual / 22 declared`；pytest `18 passed`。
- Affected Backend compileall：PASS；Frontend ESLint、TypeScript no-emit：PASS。
- Migration integration：US lineage／TW intraday migration／TW repository `12 passed`；隔離tree完整matrix已包含兩個migration test。
- Isolated staged tree：Backend／Shared／TW／US／AI／API／migration `338 passed`；Architecture pytest `18 passed`，checker PASS（`22 actual / 22 declared`）。
- Isolated staged tree：MCP contract `32 passed`；Frontend ESLint與TypeScript no-emit PASS；release version一致為`4.4.0`。
- Staged-only closure scan：DB、secret、private path、log、cache、build output皆為0；`git diff --cached --check` PASS。
- Foundation dark-boundary：不改寫歷史artifact，新增4.4.0 append-only extension checkpoint後`7 passed`。

## Decisions made

- finalized-through boundary由market service傳給overlay helper；不讓helper自行推測provider／release語意。
- Yahoo Daily INDEX applicability在canonicalization處理；不只在outward projection遮蔽。
- US effective Daily reader bound由normalized selection limit傳入既有`bars`參數；不新增outward version或consumer fallback。
- Migration integration以production已採用的US `0073`為先，TW `0073t`接在其後；不建立parallel head，也不讓既有DB誤判TW index已完成。

## Known issues / risks

- 目前實體worktree仍高度混合；本輪用alternate index完成exact source closure，但尚未替使用者stage／commit／merge／push。
- 兩個pytest暫存目錄因Windows ACL不可讀，full-suite clean exit可能受環境影響。
- `^SOX` 2026-08-28仍缺可用第二provider，允許維持truthful stale。
- 4.4.0 source完成後仍需正式launcher runtime adoption與product readback。

## Next gate

- 使用者檢查source後，另行決定是否將exact manifest正式stage／commit／push；publication完成後，再以既有launcher做4.4.0 runtime adoption與direct／proxy／MCP／UI readback。
