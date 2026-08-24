# Atlas Shadow Integration v1 計畫

## 里程碑 1：契約與邊界確認

完成條件：

- 確認 Atlas `evidence_pack_v1` response shape、版本與 GET-only 行為。
- 確認 OMI `omi.ask`、capability selection、projection 與 supplemental gap 邊界。
- 確認兩個 repo 的既有 dirty worktree，不覆蓋無關變更。

驗證：read-only source inspection 與既有 registry tests baseline。

## 里程碑 2：Shadow client 與 capability 接線

完成條件：

- 新增 loopback-only Atlas client、timeout、契約驗證與 bounded projection。
- 新增 `news.events` capability 與 provider mapping。
- 在 `omi.ask` 以 optional auto-planning 接上 Atlas，尊重 caller explicit selection。
- Atlas result 只附加到 supplemental evidence，不改 OMI core quality。

驗證：Python compile 與 targeted unit tests。

## 里程碑 3：契約 regression

完成條件：

- Capability registry count/snapshot 與新 capability 一致。
- 既有 supplemental context、decision v4 與 MCP public contract regression 通過。
- `git diff --check` 無 whitespace error。

驗證：

```powershell
..\.venv\Scripts\python.exe -m pytest -q tests\test_ai_atlas_context.py tests\test_ai_supplemental_contexts.py tests\test_ai_capability_resolution_registry.py
```

必要時再跑 public contract snapshot generator 與 MCP smoke；若 generator 會納入 unrelated dirty changes，先檢查差異再決定是否更新。

## 里程碑 4：Runtime 採用

完成條件：

- Atlas runtime 已採用 schema v3 / consumer contract `1.1`，且 loopback API health 與 representative brief call 通過。
- OMI runtime 設定 `OMI_ATLAS_SHADOW_ENABLED=true` 後，只重啟 OMI named component。
- 以 fresh MCP session 驗證 `initialize -> tools/list -> omi.ask`，並確認 `news.events` 保持 optional/shadow-only。

此里程碑需要明確 runtime restart authority，本次 source implementation 不自動執行。

## Stop-and-fix 規則

- Atlas contract/profile 不符時停止採用，不做相容猜測。
- 非 loopback URL 一律拒絕。
- Atlas failure 若影響 OMI core missing、warnings、quality 或 decision，先修正再繼續。
- 測試若顯示 explicit selection 被自動擴充，先修正 ownership boundary。
