# OMI 對外能力與補值閉環 v1

## 目標

- 將 OMI 目前 22 種 public target、57 項 backend capability、26 個 server-allowed tool、20 個 public executable fill operation、15 項 curated provider readiness 與三個 consumer 面（HTTP、repo MCP、獨立 `OMI_search`）整理成一個 backend-owned、可驗證、可續接的對外契約。
- 讓每個「target × capability」在對外回答中都有唯一且可執行的 resolution：`reader_fetch`、`granular_fill`、`composite_fill`、`background_job`、`scheduler_cache`、`cache_only`、`derived`、`private`、`key_required`、`provider_not_connected`、`not_applicable` 或 `deprecated`。
- 修正「能力看得到但不能補」、「內部工具可跑但 fill plan 不會列」、「補值逾時後 MCP 無法查進度」、「Backend、repo MCP、獨立 OMI_search schema／文件不同步」等不完整狀態。
- 完成一版可長期維護的 v1：所有已存在 provider/service 都能透過同一 registry 被正確分類與下達；尚未選定 provider 的能力維持明確 blocked contract，不偽裝成已接通。

## 非目標

- 不自動交易、不下單、不接券商帳戶，也不新增任何會替使用者執行交易的工具。
- 不在 frontend、Kuro、repo MCP 或獨立 `OMI_search` 重做市場判斷、freshness、provider fallback、fill planning 或 job orchestration。
- 不因為要追求「全部 ready」而自行採購新聞、options flow、TDnet、OpenDART 或港股 provider；涉及授權、API key、付費 quota、文件保存與資料使用條款時必須另立 provider gate。
- 不把 `cache_only`、`scheduler_cache` 或 `derived` 能力硬改成 read-path 外部抓取。
- 不做無限制全市場 backfill、不在 GET/read path 啟動大量外部請求、不重建或覆蓋 `data/open_market_intelligence.db`。
- 不在本任務規格階段修改 production code、重啟 runtime、改動 `C:\GPT_MCPtool\OMI_search` 或執行外部 provider refresh。

## 完整 v1 的定義

「完整」分成兩個不同層次，避免把產品契約完整與 provider 採購混為一談：

1. `contract_complete=true`
   - 57 項 capability 全部由單一 registry 描述。
   - 每個適用 target 都有唯一 resolution class、freshness owner、provider/readiness、side-effect、trust、request/time/row limits 與 consumer-visible status。
   - 所有被選取但不完整的 capability，必須恰好出現在 `actions`、`jobs`、`deferred`、`unfillable`、`not_applicable` 或 `already_satisfied` 其中一組。
   - HTTP、repo MCP、獨立 `OMI_search` 的 schema、snapshot、limit 與版本一致。
   - 背景補值可由對外 read-only 工具查詢並安全續接。

2. `provider_complete=true`
   - 需要另外選定並接通目前五個 `provider_not_connected` contract。
   - 本 v1 先做到 `contract_complete=true`；五個 provider gap 仍可存在，但不得再是無法判讀的缺值。

## 硬性限制

- OMI backend 是 evidence、freshness、market logic、provider fallback、fill plan、job lifecycle 與 answer contract 的唯一 owner。
- public contract 維持 `omi.decision.v4` additive 相容；若 registry 自身升版，既有 consumer 必須可忽略新欄位。
- `analysis.human_answer`、`analysis.decision_contract`、`result.data.slots`、warnings、missing、source refs、freshness 與 provider failure 不得被 consumer 丟棄。
- `not_applicable`、`missing`、`stale`、`partial`、`blocked`、`provider_not_connected`、`timeout` 與 `background_running` 不得互相折疊。
- `allow_external_fetch` 必須同時通過 caller intent 與 backend trust/policy；獨立 `OMI_search` 仍固定 `allow_llm=false`、`allow_write=false`。
- 每次 refresh 必須有明確 target、capability、provider、request count、wall-clock、row/date range、retry、cache write 與 transaction 邊界。
- Portfolio 只允許 server-trusted caller；外部 adapter 不直接讀 DB。
- 工作樹已有大量使用者變更；實作時只做局部 additive diff，不 revert、不格式化無關檔案。
- `C:\GPT_MCPtool\OMI_search` 是獨立 runtime／ownership boundary；修改與重啟必須在主 repo 變更驗證後，依其自己的測試與 Control Center lifecycle 進行。

## 現況基線

- Repo：`C:\project\Open Market Intelligence`
- Backend public contract：`POST /api/ai/ask`、`POST /api/ai/ask/stream`、`GET /api/ai/tools`
- Repo MCP：`omi.ask`、`omi.ask_stream`
- 獨立 HTTP MCP：`C:\GPT_MCPtool\OMI_search`，目前 public `tools/list` 為六個 read-only tools。
- 目前 public contract：`omi.decision.v4`
- 目前 capability registry：`omi.capability.registry.v3`
- 目前 public targets：22（含 `auto`、diagnostics 與 private portfolio）
- 目前 capability specs：57（其中 `market.sample_ranking`、`source.health` 已 deprecated）
- 目前 server-allowed tools：26；public executable fill operations：20；內部可執行但未進 public fill registry：6。
- 目前 curated provider status：15，其中 10 個 connected/conditional/derived、5 個 `provider_not_connected`。
- 稽核當下 live backend 與 HTTP MCP protocol 正常，contract snapshot digest 一致；targeted contract tests 為 `103 passed, 14 subtests passed`。這只證明現行契約可運作，不代表補值閉環完整。

## 交付物

- `CapabilityMatrix.md`：完整 target、capability、provider 與已知缺口矩陣。
- `ContractDesign.md`：單一 registry、resolution taxonomy、fill partition、background job、HTTP/MCP consumer 與相容策略。
- `Plan.md`：分 milestone 的施工順序、檔案 owner、acceptance、驗證命令與 stop-and-fix 規則。
- `Progress.md`：本次 audit 證據、已確認問題、風險與下一步。
- 後續實作完成時同步更新 `docs/ExternalInterfaces.md`、repo MCP README、獨立 `OMI_search` README 與 generated contract snapshots。

## 完成條件

- 57 項 capability 與所有適用 target 的 resolution partition 測試通過，沒有 orphan、重複分類或無 blocking reason 的 unresolved capability。
- `ALLOWED_TOOLS`、fill operations、produced capabilities、planner、executor 與 public schema 由單一 registry 衍生或有 parity assertion，不能再獨立漂移。
- `continuation.selected_action_ids` 的 runtime limit 與所有 schema 都是最多 8 個。
- cross-market、TW composite refresh、watchlist、US profile/actions 等六個現有內部工具要麼正式接入 public fill mapping，要麼被明確標成 internal-only 且附理由；不得維持隱性落差。
- 逾時的 `ai.tool_refresh` job 能被外部 caller 以 read-only、redacted contract 查詢；完成後可以重建 evidence，不必直接呼叫未公開的 raw jobs route。
- `capability_status` 能呈現完整 57 項 registry view，並另保留目前 15 項 provider readiness view；implementation readiness 與 live source health 分開。
- Backend HTTP、repo MCP stdio、獨立 OMI_search HTTP MCP 的代表性 cache-only、bounded refresh、background-job、blocked-provider、private-target 與 business-error smoke 全部符合相同語意。
- 不新增 secret、不提交本機 DB/log/cache、不產生無邊界外部抓取。

## 假設與決策 gate

- 本任務先完成「既有 provider 與 service 的對外閉環」；五個未接 provider 的詳細接法已列入矩陣，但真正接入需使用者確認來源、授權、金鑰與 quota。
- `omi.read_refresh_status` 視為 operational read tool，不是第二套 AI entrypoint；它只能讀取 `ai.tool_refresh` 並回傳 redacted job contract。
- `auto`、diagnostics、derived、cache-only 與 private 能力不一定有 refresh action；完整性來自正確分類與可見限制，不是每項都強制外部抓取。
- source code、generated snapshot、live runtime 是三種不同證據；三者都通過才能宣告 deployed complete。
