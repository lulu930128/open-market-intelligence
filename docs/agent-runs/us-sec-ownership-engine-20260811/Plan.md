# Plan

## Execution rule

- 一次依序完成本計畫；只有 `Prompt.md` 的 major-decision stop condition、資料安全風險、官方 schema 無法安全解析，或 regression 無法在既有 compatibility boundary 內修正時才停下來詢問使用者。
- 每個 stage 都先完成 acceptance 與最小足夠 validation，才進下一階段；失敗立即 stop-and-fix。
- Form 4 Stage 0–6 完成前，不開始 13F production code。

## Milestones

### Stage 0：Baseline、official fixtures 與 contract freeze

- Scope:
  - 固定既有 `/sec/{symbol}/facts`、`fundamentals`、`financials`、US source-health、job 與 frontend tab contract。
  - 建立 official-shaped Form 4/4-A fixtures：open-market P/S、F/G/M、award、multi-owner、derivative、footnotes、10b5-1、malformed/schema drift。
  - 建立 13F fixtures：HR、HR/A、NT、other manager、put/call、shared discretion、voting authority、unresolved CUSIP、confidential limitation。
  - 固定 parser/status/issue-code vocabulary。
- Acceptance:
  - Fixtures 不含私人資料且可進 Git；來源與裁切方式有註記。
  - Legacy SEC/US contract regression 在實作前可重現。
- Validation:
  - `rg` inventory、focused baseline pytest、`git diff --check`。

### Stage 1：Ownership foundation 與 Alembic migration

- Scope:
  - 新增 `sec_ownership/` pure package、dataset release/checkpoint contracts、local archive path/config與 safe archive helper。
  - 以實作時 next available revision 建立 shared metadata、Form 4 canonical tables與必要 indexes。
  - migration 不碰現有 `USSecCompanyFact`；model registry同步更新。
- Acceptance:
  - Empty SQLite 及代表性 populated SQLite 可 upgrade 到 head。
  - 相同 release/accession rerun 不重複；transaction failure rollback。
  - Cache path 可設定、排除 Git；zip-slip/oversize/invalid hash fail closed。
- Validation:
  - `backend/tests/test_database_migrations.py`
  - 新增 ownership migration/store targeted tests
  - `python -m compileall backend/app`

### Stage 2：Form 4 provider、XML/bulk parser 與 semantics

- Scope:
  - 擴充 SEC provider 以取得 issuer ownership filing metadata/XML與 Insider Transactions quarterly archive。
  - Parser 分離 submission、issuer、owner、relationship、non-derivative、derivative、holding、footnote。
  - Decimal、date、accession、transaction code、direct/indirect、amendment與 source refs normalization。
- Acceptance:
  - 所有 Stage 0 fixtures deterministic；輸入順序不改結果。
  - Malformed row 被 quarantine 並計數；無 silent drop。
  - `4/A` 原始與 amendment 並存；無法判定 supersession 時不自動去重。
- Validation:
  - Parser pure tests涵蓋正常、empty、malformed、schema drift、multi-owner、derivative、amendment。

### Stage 3：Form 4 store、bounded jobs 與 freshness

- Scope:
  - 實作 append-only filing store、atomic projection更新、release reconciliation、checkpoint、per-symbol/watchlist job。
  - Job retry/cancel/restart與 concurrency lock；接入 provider event/source health。
  - Historical bootstrap與recent incremental分開；GET不得觸發 refresh。
- Acceptance:
  - `source rows = persisted + quarantined + explicitly skipped`。
  - 同 archive/XML rerun為 idempotent；job failure保留先前可用 snapshot。
  - `ready_empty/missing/partial/stale/blocked`有 deterministic tests。
- Validation:
  - Service/store/job/source-health targeted tests。
  - Mock provider assertions證明GET external-call count=0、refresh bounds生效。

### Stage 4：Form 4 versioned API 與 AI evidence

- Scope:
  - 新增 `omi.sec.insiders.v1` schema、bounded read route、Form 4 sync job route與job retry inventory。
  - 新增 `ownership.insider_transactions` compact capability、freshness/data limits/source refs與decision adapter採用。
- Acceptance:
  - API cursor/date/code/limit validation完整；legacy routes unchanged。
  - AI不把F/G/M/award/derivative當open-market買賣，也不宣稱完整current position。
  - Streaming/non-streaming/MCP outward contract相容。
- Validation:
  - Router/OpenAPI inventory、AI capability/freshness/outward/MCP targeted tests。

### Stage 5：Form 4 frontend adoption

- Scope:
  - 「內部人」tab接上`omi.sec.insiders.v1`，顯示summary、owner/role、code語意、股數/價格、after amount、direct/indirect、derivative/10b5-1/amendment/source。
  - loading、ready_empty、partial、stale、blocked與shared更新狀態；繁中/英文/日文文案。
- Acceptance:
  - 不做不相容交易類型的單一net number。
  - 390px與desktop無overflow；keyboard tab contract不退化。
  - Refresh/error只進既有JobStatusCenter／更新狀態。
- Validation:
  - `npm run lint`
  - `npm exec tsc -- --noEmit --incremental false`
  - `npm run build`
  - 有實際版面風險時加browser screenshot/DOM/console check。

### Stage 6：Form 4 production proof and freeze

- Scope:
  - 用bounded live SEC probe驗證AAPL及至少一個derivative/amendment代表issuer。
  - 驗證launcher-owned runtime、migration head、API、AI、frontend與source health。
  - 更新Progress並freeze Form 4 v1 contract。
- Acceptance:
  - Running system實際採用新contract；GET重複讀取不產生SEC request。
  - Runtime結果可追到accession/source URL/filing date/transaction code。
  - 無資料issuer顯示ready_empty；provider failure不偽裝ready。
- Validation:
  - Safe backend profile + bounded API/UI/runtime smoke。

### Stage 7：13F two-quarter capacity與mapping proof

- Scope:
  - 下載最近兩個官方quarter archives與Official 13(f) list，先只做manifest/integrity/streaming parse measurement。
  - 量測rows、sizes、peak memory、parse time、SQLite/index amplification與CUSIP mapping coverage。
  - 固定storage budget/free-space guard與full-history projection。
- Acceptance:
  - 產出CapacityReport：兩季實測與全歷史估算，不憑壓縮檔大小猜DB成本。
  - Mapping coverage達90% rows/95% value，或依Prompt重大決議規則暫停symbol-ready宣告。
  - Parser可chunk/stream，不把整季載入記憶體。
- Validation:
  - Offline archive/parser benchmark與reconciliation；不改production current projection。

### Stage 8：13F schema、quarter ingestion 與atomic release

- Scope:
  - 以新Alembic revision新增manager/filing/other-manager/holding/identifier-map/symbol-quarter tables與indexes。
  - 實作一季一job的discover/download/ingest/rebuild_projection stages。
  - 最近兩季全rows匯入，quarantine與release reconciliation完整。
- Acceptance:
  - 兩季每個source table counts完全對帳；hash rerun idempotent。
  - Quarter failure不切換current release；retry可從checkpoint續跑。
  - HR/A、NT與confidential限制不被當一般empty holdings。
- Validation:
  - Migration/store/job/reconciliation tests與兩季offline integration proof。

### Stage 9：CUSIP mapping、quarter projection與API

- Scope:
  - Versioned exact mapping、review candidates、manual override contract、coverage audit。
  - 建立bounded symbol/manager/CUSIP queries與`omi.sec.13f.v1`。
  - QoQ只比較同manager/security/basis；aggregate欄位使用`reported_*`語意。
- Acceptance:
  - 未映射rows保留且coverage可見；fuzzy name不自動ready。
  - 13F-NT不回傳零持股；shared discretion不被宣稱exact institutional ownership。
  - Latest symbol warm-cache p95 <= 1 second；否則先index/projection修正，再依重大決議規則處理。
- Validation:
  - Mapping/comparability/API/OpenAPI/performance targeted tests。

### Stage 10：13F AI與frontend「機構」頁

- Scope:
  - 新增`ownership.institutional_holdings` compact evidence。
  - 「機構」tab顯示report quarter、filed/release時間、top managers、reported position、QoQ comparable change、new/increased/reduced/exited與mapping/coverage limits。
  - 接入shared更新狀態與i18n。
- Acceptance:
  - UI/AI明示季度與申報延遲；不使用「今日法人買賣超」語言。
  - Confidential/shared-discretion/unresolved mapping會降低readiness並可見。
  - Payload bounded，frontend不拉全市場rows。
- Validation:
  - AI contract regressions、frontend lint/typecheck/build、代表symbol browser proof。

### Stage 11：All-published-history full-market backfill

- Scope:
  - Coordinator依official manifest從最新向舊enqueue單季jobs，直到SEC仍公開的最早quarter。
  - 每季完成後做counts/hash/checkpoint/storage/freshness audit；可暫停、resume、retry。
  - 保留compressed source archives；清理已完成staging。
- Acceptance:
  - Coverage API列出每季completed/partial/blocked與原因。
  - 所有completed quarters都是full-row warehouse，不是watchlist subset。
  - 磁碟安全門檻全程生效；不因backfill讓runtime GET或既有OMI功能失去可用性。
- Validation:
  - Per-quarter reconciliation、DB integrity、disk guard、job restart與代表歷史query。

### Stage 12：Operations、runtime adoption與final regression

- Scope:
  - Scheduler release check、provider/source health、job retry UI、backup/restore與維運文件。
  - 代表symbol/manager、ready_empty、unmapped、amendment、provider failure、stale quarter end-to-end proof。
  - 更新parent SEC fundamental progress指向ownership engine結果。
- Acceptance:
  - Launcher-owned backend/frontend實際採用migration與兩個versioned contracts。
  - Backup/restore可保留release/checkpoint/projection一致性；cache缺檔有可恢復路徑。
  - 相關backend/frontend/AI/MCP regressions通過，known limits完整記錄。
- Validation:
  - `scripts/run-safe-validation.ps1`最小足夠profiles。
  - Bounded runtime/API/UI/source-health/job smoke。

## Stop-and-fix rules

- 任一source row無法歸類為persisted/quarantined/explicitly skipped時，停止下一stage。
- 任一parser把malformed numeric轉0、使用float作唯一值、丟失accession/CUSIP/source hash或覆蓋amendment history時，立即修正。
- GET發生外部IO、archive extraction可path traversal、job無request bounds、retry無界或partial quarter可見時，停止。
- Legacy SEC/US/OpenAPI/AI/frontend contract regression失敗時，先保留compatibility seam或修正，不把breakage留到後續。
- Migration不能在empty與populated SQLite安全升級，或需要直接改production DB時，停止。
- 13F aggregate若混用report/filed date、把NT當empty、跨put/call/share basis比較或忽略shared discretion，不得進UI/AI。
- 命中Prompt的major-decision stop condition時，停止擴大範圍並向使用者提出具體證據與選項。

## Decisions

- 2026-08-11：Form 4先於13F，且先完成完整runtime adoption再開始13F production code。
- 2026-08-11：13F採全市場CUSIP-native warehouse，不採watchlist-only storage。
- 2026-08-11：最近兩季先作production/capacity gate，之後一季一job回補全部SEC公開歷史。
- 2026-08-11：SQLite仍是首選metadata/canonical store；是否引入另一個analytical storage engine只由實測capacity/performance gate決定。
- 2026-08-11：Form 4 first交付transaction ledger；未納入Form 3/5前不宣稱完整current insider position。
- 2026-08-11：13F symbol mapping與source completeness分開；mapping不足不得抹去CUSIP rows或假裝全symbol coverage。
- 2026-08-11：所有refresh/backfill由POST tracked job/scheduler owner負責，GET cache-only。
- 2026-08-12：Stage 7 storage gate 經使用者同意後採 Parquet/DuckDB analytical warehouse，SQLite 只負責 metadata、mapping 與 bounded materialized projection。
- 2026-08-12：全歷史 ingest 以 SEC 官方 manifest 為 completeness 基準；legacy 非 9 碼 identifier 保留 raw evidence 並 quarantine canonical mapping，不猜測補值。
- 2026-08-12：在沒有 OpenFIGI API key 與 review coverage 前，全市場 mapping 仍為重大決議；不以數萬筆匿名外部請求、issuer-name fuzzy match 或 frontend 推導繞過 gate。
- 2026-08-13：使用者提供本機 test key 並核准 authenticated full-market mapping；所有 lookup 仍走 bounded tracked jobs，只有唯一核准的 US-equity mapping 可進 symbol projection。

## Completion

- Stage 0–12 已於 2026-08-12 完成可在既定 trust boundary 內自主完成的範圍。
- Form 4 與 13F versioned contracts、full published history、operations scripts、AI evidence、frontend 與 launcher-owned runtime 已驗收。
- 全市場 CUSIP lookup inventory 與 approved symbol projection 已完成；source-native warehouse、ambiguous、unverified 與 unmapped rows 均完整保留並可審計。

## 2026-08-13 decision closure

- 使用者核准以本機 test key 執行 authenticated full-market OpenFIGI mapping。
- Stage 9 與 Stage 12 剩餘 mapping gate 已完成：每個 canonical CUSIP 都有 versioned result，approved mappings 已 atomically materialized 至 live full-market projection。
- Completion 不會把 ambiguous、unverified 或 unmapped identifier 改標 approved；outward contract 在 provider/source coverage 未真正改善前仍維持 `partial`。
