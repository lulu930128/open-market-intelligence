# 進度

## 目前狀態

已完成。Standalone `OMI_search` 已收斂為 MCP protocol、schema surface、明確欄位/shortcut compatibility mapping、固定 read-only trust flags 與 HTTP transport。

## 已確認證據

- `OMI_search/server.py` 目前會解析 live quote 關鍵字、將 US auto horizon 改成 intraday、改寫 question，並在未明確指定時自動允許 external refresh。
- `OMI_search/server.py` 目前會替 tool budget、ranking、limits、refresh policy 等補值或修正數值。
- adapter 內仍有未被 runtime 使用的 response projection helpers；runtime 已直接回傳 backend v4 envelope。
- OMI backend 的 `decision_core.py` 與 `ask_question_stage.py` 已擁有 question understanding 與 effective horizon。
- OMI backend 的 ask policy/tool stage、finalizer 與 v4 envelope 已擁有 refresh、live summary、warnings、budget 與 response shaping。
- 修改前 standalone tests：31 tests passed。
- 修改前 backend targeted tests：50 passed，35 subtests passed。
- Backend ownership regression 證明：原始 question 不變、`auto` horizon 由 backend 解析成 `intraday`，`allow_external_fetch=false` 不會被擴權。
- Standalone adapter 不再含 live-intent terms、question rewrite、auto refresh、budget clamp/default 或 response projection helpers。
- Canonical `omi.ask` 不再用 `stock_id` / `symbol` 推斷 target；hidden legacy `omi.search` 仍保留相容映射。
- `tools/list` 正常時使用 backend `/api/ai/tools`，backend 不可用時使用 generated snapshot。

## 決策紀錄

- 不把判斷邏輯「搬」成新的 duplicate；backend 已有 owner，因此從 adapter 刪除並以 regression test 固定責任。
- canonical `omi.ask` 只接受 backend schema 欄位；`stock_id` / `symbol` 只留在隱藏 legacy `omi.search` 相容層。
- shortcuts 可保留明確 tool-to-target mapping，因為這是公開 MCP tool 的機械轉換，不是由自然語言推斷市場語意。
- schema 正常時讀 `/api/ai/tools`；generated snapshot 只作離線 fallback。

## 驗證結果

- `python -B -m unittest discover -s tests`：25 tests passed。
- Python AST syntax：4 files passed。
- Backend targeted tests：63 passed，35 subtests passed。
- Snapshot parity：與 OMI generator 產物 SHA-256 完全一致；22 targets、55 capabilities，digest `ed1d6ef622bb56b12e68eaae9cb81c29cd825c25e4917c01c3783001200c1fe9`。
- Source audit：沒有找到已移除的 heuristic/projection symbols。
- Controlled stdio MCP smoke：protocol `2025-06-18`、6 tools、live schema source、representative `omi.ask` call 均通過；question/target exact、refresh false、budget unclamped、horizon omitted、v4 response `isError=false`。
- `git diff --check`：相關檔案通過。

## Runtime 註記

驗收時正式 OMI `127.0.0.1:8400` 沒有 listener，因此未宣稱正式 runtime live call 通過。Protocol smoke 使用受控本機 backend contract stub；backend behavior 則由 targeted tests 與 generated schema parity 驗證。
