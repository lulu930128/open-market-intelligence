# 進度

## 狀態

- 目前階段：complete；Milestone 1-7 已完成並由 source、snapshot、full regression 與 live runtime 四層證據驗收
- 最後更新：2026-08-10 00:58 Asia/Taipei
- Branch：`codex/tw-etf-provider-normalization`
- 工作樹：原本已有大量跨 market/AI/frontend/migration 變更；本任務採 additive、局部修改並保留既有變更

## 已完成

- 讀取 repo AGENTS、非空 `docs/product/` 產品文件與 Backend architecture，確認 backend-owned market/freshness/tool orchestration 邊界。
- 稽核 Backend public target catalog：22 種。
- 稽核 capability specs：57 項，其中2項 deprecated。
- 稽核 server-allowed tools：26 個。
- 稽核 public executable fills：20 個；確認沒有 public fill落在allowlist外。
- 找出6個allowed但未進public fill registry的operations。
- 稽核 curated capability/provider status：15項，10項connected/conditional/derived、5項provider未接。
- 稽核 Ask tool stage：目前只有US stock、crypto asset、JP/KR stock/index、TW stock、TW watchlist有external tool session分支。
- 稽核background timeout：會建立/重用 `ai.tool_refresh` job並回raw `/api/jobs/{id}`，但OMI_search沒有job status tool。
- 稽核schema/文件差異：selected action runtime limit與schema、MCP env名稱、ExternalInterfaces的OMI_search描述、health/core version語意。
- 完成 `CapabilityMatrix.md`、`ContractDesign.md`、`Plan.md` 與本進度文件。
- 完成 Milestone 1：新增 pure `capability_resolution_registry.py`，以 `(scope_type, capability_id)` 建立 210 筆唯一 resolution entries，覆蓋全部 57 項 capability 與 wildcard scopes。
- Registry 明確分類 24 個 canonical operations 與 2 個 internal-only operations；cross-market、TW watchlist、US profile/actions已有唯一 scoped owner並已啟用於 public fill plan。
- 新增 registry coverage、mode/status、allowlist parity、scope-specific refreshability、composite owner、private/key/scheduler/derived、deprecated replacement與JSON projection tests。
- 完成 Milestone 2：manifest、fill plan、tool-run capability reconciliation與signed continuation均改用scope-specific registry；四個既有operation可由public action安全下達。
- 完成 Milestone 3：新增 `already_satisfied/actions/jobs/deferred/unfillable/not_applicable` 六組compact partition；每個selected capability恰好出現一次，legacy action/deferred欄位保持相容。
- Continuation只有在backend重新驗證plan/action/target/selection後才強制執行；一般v4初次讀取仍只依freshness gap補值，不會每次外抓。
- US profile/actions、TW watchlist、cross-market composite planner與Ask tool stage已接通；US corporate-action gap有本機cache存在性檢查。
- 修正第一次全量metadata projection造成的compact byte-budget regression；manifest只保留必要resolution metadata，完整registry細節留給capability status surface。
- 完成 Milestone 4：新增 `GET /api/ai/refresh-status/{job_id}` 與 `omi.read_refresh_status`，只讀 redacted `ai.tool_refresh`；operation完成與evidence重建狀態分離，完成後提供cache-only resume template。
- Background job reference保留legacy `poll_url`，新增安全 `status_url`；fill plan會把仍在執行的selected capability分到`jobs`，不再同時重建duplicate action。
- 完成 Milestone 5：`capability_status` 同時提供15項provider contracts、57項capability aggregate與210項scope resolution；implementation readiness與live source health保持分離。
- `/api/ai/tools`、OpenAPI與MCP schema的`selected_action_ids`均限制最多8個；repo MCP schema timeout改讀`OMI_MCP_SCHEMA_TIMEOUT_SECONDS`並保留舊alias。
- Repo MCP public surface擴成`omi.ask`、`omi.ask_stream`、`omi.read_refresh_status`，動態schema、offline fallback、GET routing與protocol tests已完成。
- 修正consumer-facing projection遺漏：compact、required-core與emergency v4 projection都保留六組fill partition與安全job reference，Frontend/Kuro不需建立第二套分類邏輯。
- 已依使用者明確授權將獨立 `OMI_search` 七個指定檔案同步到正式路徑；同步前後 SHA256 逐檔一致，未覆寫其他檔案，正式 adapter 測試為 30 項全數通過。
- 已依正式生命週期重開 `OMI_search` 與 OMI launcher；`OMI_search` build id 為 `6ffe9eb74fcedf59`，Backend health/ready、實際 listener、repo venv command line 與 outward contract 均已驗證。
- 五個provider expansion gate維持`provider_not_connected`，每項均有blocking reason與next fill；未在license/key/quota/identity決策前假裝ready。

## 驗證證據

- Live backend `/api/system/health`、`/readyz`：稽核時正常。
- Live `/api/ai/tools`：1個canonical public AI tool `omi.ask`，`omi.decision.v4`，22 targets，57 capabilities，default `allow_external_fetch=false`，external fetch硬上限8、總秒數硬上限90。
- Live OMI_search HTTP MCP：`initialize`、`tools/list`、代表性 `tools/call` 成功；當時public surface為六個read-only tools。
- Backend與獨立OMI_search contract snapshot SHA256：稽核時一致。
- 現行contract targeted tests：

```text
103 passed, 14 subtests passed in 1.91s
```

- 測試命令：

```powershell
cd "C:\project\Open Market Intelligence\backend"
& '..\.venv\Scripts\python.exe' -m pytest -p no:cacheprovider -q `
  tests\test_omi_mcp_server.py `
  tests\test_mcp_schema_contract.py `
  tests\test_ai_tool_boundaries.py `
  tests\test_ai_capability_contract.py
```

- 本輪docs-only驗證：五份Markdown均可UTF-8讀回；CapabilityMatrix解析到22個唯一targets與57個連續、唯一capability ids；必要章節完整；未發現未完成標記或trailing whitespace。
- `git status --short -- docs/agent-runs/omi-external-capability-closure-v1-20260809`：只有本任務新目錄，未修改原有檔案。
- Milestone 1 targeted regression：`81 passed, 12 subtests passed in 1.90s`。
- `python -m compileall -q app/ai/capability_resolution_registry.py app/ai/capability_contract.py`：通過。
- Registry audit：210 entries、24 canonical operations；resolution mode計數可重現且無duplicate key。
- Milestone 2-3 focused regression：`227 passed, 31 subtests passed in 25.15s`。
- 全registry fill partition：`14 passed, 214 subtests passed in 1.15s`，覆蓋210個scope×capability entries與4個signed composite continuation案例。
- Milestone 4-5 focused regression：`71 passed, 237 subtests passed in 8.73s`。
- Repo MCP/schema/job status regression：`47 passed, 4 subtests passed in 2.69s`。
- Capability registry與v4 projection最新回歸：`65 passed, 229 subtests passed in 1.65s`。
- `test_ai_capability_contract.py`、`test_ai_outward_contract.py`、`test_ai_ask_stages.py`：`91 passed, 12 subtests passed in 3.04s`。
- `test_ai_decision_envelope.py`全檔：`48 passed, 15 subtests passed in 1.58s`。
- 獨立`OMI_search`暫存patch：`30 tests`，包含initialize/session/tools list與`omi.read_refresh_status`代表性HTTP tools/call，全部通過。
- 正式 `C:\GPT_MCPtool\OMI_search`：`python -B -m unittest discover -s tests` 為 30 項全數通過；七個同步檔案與 staging SHA256 一致。
- 第一次 safe backend regression 找到唯一 stale inventory assertion（新 route 後仍期待 373 operations）；修正為 374 operations／373 `/api/` routes 並新增 refresh-status route assertion，targeted inventory regression 為 `10 passed, 60 subtests passed`。
- 修正後 `run-safe-validation.ps1 -Profile backend`：compileall、完整 backend pytest 與 diff check 全部通過，結果為 `1667 passed, 801 warnings in 197.19s`；warnings 為既有 SQLAlchemy/SQLite deprecation 與 LF/CRLF 提示。
- Live Backend：health=`ok`、ready=`ready`、`/api/ai/tools` 為 `omi.ask` 與 `omi.read_refresh_status`，`selected_action_ids.maxItems=8`；cache-only capability status 回傳 15 provider contracts、57 capabilities、210 scope resolutions與5個明確 blocked provider contracts。
- Live repo MCP stdio：`initialize`、`notifications/initialized`、`tools/list`、代表性 cache-only `tools/call` 成功；公開工具為 `omi.ask`、`omi.ask_stream`、`omi.read_refresh_status`。
- Live 獨立 HTTP MCP：建立 session 後七工具 `tools/list`、capability status與不存在標的 business error均通過；不存在標的為 transport success、`ok=false`、`TARGET_NOT_FOUND`，未知 refresh job 保留 `AI_REFRESH_JOB_NOT_FOUND`。
- Private portfolio live smoke只輸出 contract/status而未輸出持倉內容：caller為 `local_allowlist` server-trusted、`allow_external_fetch=false`、`can_user_data_write=false`；untrusted caller阻擋由 targeted trust regression覆蓋。
- MCP Control Center 最終狀態為 `Ready 6/6`；`OMI Search` core、OMI backend dependency與 Secure MCP Tunnel皆 Ready，PID ownership吻合。
- `git diff --check`：無whitespace error；既有工作樹檔案僅有LF/CRLF提示。

## 已關閉 findings

以下六項是本輪基線稽核發現，均已由上方 implementation 與驗證證據關閉；五個尚未採購的 provider 以明確 blocked contract 保留，不屬於未完成的契約漂移。

1. `capability_status` 不完整覆蓋正式 registry
   - Backend正式有57項capability，但curated provider readiness只有15項。
   - Consumer無法從單一查詢得知每項capability在各scope的refreshability、bounds與blocking reason。

2. Allowed tools與public fills漂移
   - 26個allowed tools中只有20個能出現在public fill plan。
   - cross-market、TW stock/watchlist composite、US profile/actions/SEC alias處於internal-only灰區。

3. 同名capability跨scope不一致
   - `quote.snapshot`、`intraday.bars`、`daily.ohlcv`、crypto order book/derivatives在不同scope有不同action。
   - 目前metadata以capability為主，容易讓consumer誤認所有適用scope都可補。

4. Ask tool session覆蓋不完整
   - 沒有market、TW index/futures、resource、macro、regional watchlist、crypto market的canonical external tool session。
   - 其中部分正確owner應是scheduler/cache，不應一律新增即時refresh；目前缺的是明確resolution。

5. Background job沒有MCP閉環
   - backend逾時後有tracked job與poll URL。
   - 純MCP caller無同一public surface可安全查詢、等待與resume。

6. Schema與文件有小型漂移
   - runtime限制`continuation.selected_action_ids <= 8`，public schema缺`maxItems: 8`。
   - README寫`OMI_MCP_SCHEMA_TIMEOUT_SECONDS`，code讀`OMI_SCHEMA_TIMEOUT_SECONDS`。
   - `docs/ExternalInterfaces.md` 的獨立OMI_search tool/version描述落後live六工具surface。
   - `/health` transport version與MCP core version用途未清楚區分。

## 風險與限制

- 本輪達成 `contract_complete=true`，不代表 `provider_complete=true`。新聞／事件、美股 options+earnings、TDnet、OpenDART 與港股五項仍是 `provider_not_connected`，需另行確認授權、key、quota、identity、retention 與 provider terms。
- 完整 backend regression 的 801 warnings 均未造成 failure，但 SQLAlchemy/SQLite deprecation 應在獨立維護任務處理，不應混入本契約 closure。
- 工作樹原有大量未提交變更；本輪沒有 commit、push、重建 DB、啟動外部 refresh 或輸出 private portfolio 明細。
- PowerShell 對 stdio 子行程會加 UTF-8 BOM；repo MCP live smoke以一個可辨識的前導 parse-error隔離該 shell artifact，後續正式 `initialize`／`tools/list`／`tools/call` 均成功。HTTP MCP不受此限制。

## 下一步

- 由使用者決定是否啟動 Milestone 8 provider expansion；建議逐一選 provider，不把五個不同 license/quota/資料保存風險綁成一次上線。
- 若先不接新 provider，目前版本可直接作為完整 v1 使用；consumer 應以 blocked contract與 source health顯示缺口，不把未接資料當成空資料。
