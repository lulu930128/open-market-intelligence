# Taiwan Data Surface v1 計畫

## 里程碑

1. Contract baseline 與安全隔離
   - 範圍：branch、task docs、現行 registry／public schema／MCP schema snapshot。
   - 驗收：基線 commit、dirty state、現行 target/capability inventory 與 focused regression 結果已記錄。
   - 驗證：`git status --short --branch`、focused pytest、`git diff --check`。

2. Canonical capability kernel
   - 範圍：`capability_contract.py`、`schemas.py`、`tool_catalog.py`、v4 envelope/query plan。
   - 驗收：registry version/digest 單一常數；CapabilitySpec 含 market applicability、metadata、parameter schema 與 compatibility；`selection.parameters` 可驗證且不破壞舊 request。
   - 驗證：`test_ai_capability_contract.py`、`test_ai_tool_boundaries.py`、`test_ai_public_v4_contract.py`、`test_ai_decision_envelope.py`。

3. Taiwan screening 垂直切片
   - 範圍：新增 pure/cache-first market service、market reader dispatch、capability projection。
   - 驗收：`market/TW + screening.ranking/coverage` 支援第一批 institutional/margin metrics、trading-day windows、stable snapshot/pagination 與完整 coverage semantics；不依賴 watchlist group。
   - 驗證：screening metric、coverage、dates、ties、pagination、selection projection tests。

4. Taiwan quote components
   - 範圍：重用 quote-depth／session contract，新增 order book、auction、official close capability projection。
   - 驗收：盤前 last trade unavailable 不影響可用 order book／auction；每個 component 有 event time、unit、freshness 與 quality。
   - 驗證：quote-depth、realtime contract、freshness guard、public v4 tests。

5. Taiwan market aggregates 與 events
   - 範圍：indices、contributions、institutional/margin aggregates、既有 derivatives capability、corporate events。
   - 驗收：不新增同義 derivatives capability；market/stock events 共用 service；previous-session/release-lag 語意可見。
   - 驗證：market context projection、indices、market chips、corporate events、cross-market regression。

6. Adapter schema parity
   - 範圍：repo MCP、standalone OMI_search、外部文件。
   - 驗收：adapter 由 backend-owned manifest snapshot／schema builder取得 target/capability/parameter schema；registry digest mismatch 可被測試偵測；不新增計算邏輯。
   - 驗證：`test_omi_mcp_server.py`、OMI_search server/http tests、schema digest tests。

7. 完整驗證與 runtime proof
   - 範圍：safe validation、launcher-selected runtime、HTTP／MCP representative calls。
   - 驗收：source、isolated tests、active runtime 與 consumer projection分別有證據；stale/partial/missing 與 business error 不被誤報。
   - 驗證：backend safe profile、`git diff --check`、health/tools/ask、MCP initialize/session/tools/list/tools/call。

8. 實測回報後收斂
   - 範圍：一般台股 context、market indices、自然語言 screening routing 與常駐 MCP schema。
   - 驗收：一般台股與 market indices 不再發生 runtime `NameError`；高信心台股排行問句會產生 backend-owned typed selection；8797 常駐 schema 與 backend registry digest 一致。
   - 驗證：focused regression、backend safe profile、isolated `/api/ai/ask` 三條 representative calls、live MCP initialize/session/tools/list/tools/call。

9. Taiwan Reference Contract 收斂
   - 範圍：Reference v1.0 的 P0 全部、P1 核心與主要 P2 schema 能力。
   - 驗收：同一 selected capability 只有一份 consumer-facing canonical status；
     正常 post-close/pending-release/not-applicable 不進 missing 或 fill loop；
     market aggregate 揭露 TWSE/TPEX coverage；screening 預設只排名完整窗口；
     required payload 在 8192 bytes 保留，無法保留時回明確 budget error；
     timestamps/units/source refs/schema version 可被 consumer 直接使用。
   - 驗證：2330、TW market、events、projection 4096/8192/16384/65536、
     invalid target/parameter golden regression；backend safe profile；
     launcher-selected HTTP 與 session-preserving MCP smoke。

10. MCP 缺資料補抓與 outward refresh outcome 收斂
   - 範圍：tool execution status、selected-stock refresh aggregation、
     capability refresh strategy、fill-plan continuation、MCP offline snapshot。
   - 驗收：
     - transport 成功但 provider／dataset operation 失敗時，不得標成補抓成功；
       `transport_status`、`operation_status`、`evidence_status` 與
       `result_status` 分層輸出。
     - selected-stock refresh 將 nested provider error 彙整成 bounded
       `failed_steps`，保留 dataset、provider、target、error message 與 retryable。
     - 台股 quote／intraday 宣告 `reader_fetch`，不再產生不存在的
       `tw.refresh_quote`／`tw.refresh_intraday` fill action。
     - 真正可執行的 granular fill operation 維持 target/action/plan
       revalidation；即使整體 freshness 為 current，使用者選取 continuation
       仍會執行。
     - Repo MCP 與 standalone OMI_search fallback snapshot byte-for-byte
       一致，digest 與 backend manifest 相同。
   - 驗證：AI capability／envelope／freshness／tool boundary／outward contract、
     selected refresh、repo MCP 與 standalone MCP tests；`git diff --check`；
     launcher-selected HTTP／MCP smoke 歸 milestone 8。

## 里程碑狀態

- [x] 1. Contract baseline 與安全隔離
- [x] 2. Canonical capability kernel
- [x] 3. Taiwan screening 垂直切片
- [x] 4. Taiwan quote components
- [x] 5. Taiwan market aggregates 與 events
- [x] 6. Adapter schema parity
- [x] 7. 完整驗證與 runtime proof
- [x] 8. 實測回報後收斂（source／isolated runtime／8797／正式 launcher-selected
  runtime 已完成；明日保留使用者實際情境驗收）
- [x] 9. Taiwan Reference Contract 收斂（source、完整 backend regression、隔離 HTTP／stdio MCP proof 已完成；正式 8400 deployment 仍歸 milestone 8）
- [x] 10. MCP 缺資料補抓與 outward refresh outcome 收斂（source、252 項
  backend focused regression、31 項 standalone MCP regression、snapshot parity
  與正式 8400 HTTP／stdio MCP 驗收已完成）

## Stop-and-fix 規則

- 任一里程碑的 focused regression 失敗，先修正或確認為基線既有失敗，不能直接進下一階段。
- 發現新 capability 需要 full-market implicit refresh、昂貴 read-path side effect、資料表重建或未授權 provider 時，暫停並更新 Prompt。
- 發現 `evidence.data`、freshness、quality、manifest、slots 或 MCP projection 對同一 capability 狀態不一致時，先完成 end-to-end reconciliation。
- 發現 legacy path、patch seam 或跨市場 shared capability 退化時，保留 facade/alias 並補 regression，不做破壞性改名。
- Standalone OMI_search 修改只能 path-scoped；不得混入 `C:\GPT_MCPtool` 其他專案既有 dirty changes。

## 決策

- 2026-07-29：不新增 `tw_screener`／`tw_calendar` target；使用 `market + TW` 與 capability-scoped parameters，維持 target=查詢對象、capability=資料需求的分離。
- 2026-07-29：Public canonical projection 是 v4 `evidence.*`；`compact.*` 只作 reader source／legacy compatibility。
- 2026-07-29：不新增 `omi.read_tw_screener`／`omi.read_tw_calendar` shortcut；先讓 `omi.ask` 與現有 curated read tools 消費同一 manifest。
- 2026-07-29：`technical.plan` 留在 decision layer；`market.derivatives_sentiment` 不新增，優先重用既有 `derivatives.positioning`／`derivatives.structure`。
- 2026-07-29：registry schema additions 立即更新 registry version/digest，不等全部 P0 完成後才一次切版。
- 2026-07-29：自然語言 screening 只在 `market/TW`、明確排行語句且可辨識 metric 時推論；explicit selection 永遠優先，adapter 不重做 parsing。
- 2026-07-29：正式 8400 不在 Radar／US 並行修改持續變動時重啟；先用 isolated runtime 證明本任務 contract，再等待單一穩定 worktree deployment。
- 2026-07-29：`evidence.capability_status` 是新的 consumer-facing 唯一狀態；
  legacy manifest/slot/freshness 欄位先保留，但只能引用 canonical resolver
  結果。上游矛盾只保留在 debug evidence。
- 2026-07-29：P3 新 capability 不先於 P0/P1 contract correctness；所有
  read capability 維持 cache-only 或既有 bounded policy，不新增隱性全市場
  refresh。
- 2026-07-29：Reference Contract 的 source correctness 與隔離 runtime proof
  可獨立完成；不為了勾選本 milestone 而重啟仍載有 Radar／US 並行變更的正式
  8400。正式 deployment 與使用者最新版實測仍由 milestone 8 收斂。
- 2026-07-31：tool transport、provider operation 與 final evidence 是三個不同
  狀態軸；保留 legacy `tool_runs.status` 相容欄位，但 reconciliation 與
  current-request failure 以 `operation_status` 為判斷依據。
- 2026-07-31：台股 quote／intraday 是 primary reader 的 bounded fetch，
  不建立同義 executor tool；只有已存在於 allowlist、planner 與 executor 的
  granular operation 才可生成可執行 fill action。
