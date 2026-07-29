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

## 里程碑狀態

- [x] 1. Contract baseline 與安全隔離
- [x] 2. Canonical capability kernel
- [x] 3. Taiwan screening 垂直切片
- [x] 4. Taiwan quote components
- [x] 5. Taiwan market aggregates 與 events
- [x] 6. Adapter schema parity
- [x] 7. 完整驗證與 runtime proof

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
