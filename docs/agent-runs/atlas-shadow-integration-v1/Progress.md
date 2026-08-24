# Atlas Shadow Integration v1 進度

## 目前狀態

Source 接線與 regression 已完成。Runtime feature flag 尚未啟用，未重啟 Atlas 或 OMI；目前等待 named-component adoption proof。

## 已完成

- 確認 Atlas consumer contract `1.1` 與 `evidence_pack_v1` response shape。
- 確認 Atlas live listener 當時未啟動，避免把 source state 誤當 runtime adoption。
- 確認 OMI 已有 `news_events` slot 與 provider-not-connected gap。
- 新增 Atlas loopback-only shadow client、timeout、版本/profile 驗證與有界欄位投影。
- 新增 `news.events` optional capability、provider mapping 與 capability status 採用狀態。
- 在 `omi.ask` query plan 前加入 optional auto-selection，並在 canonical result 投影前附加 bounded context。
- 保留 `decision_usable=false`、`unknown_not_observed` 與 core quality isolation。
- 新增 success、empty、timeout、contract mismatch、non-loopback、selection ownership、projection 與 provider boundary 測試。
- 以官方 generator 更新 MCP offline public contract snapshot，catalog 現含 67 個 capabilities 與 `news.events`。
- 驗證明確選取 `news.events` 時，`omi.ask` 會將 Atlas evidence 投影至 `omi.decision.v4`。

## 驗證證據

- 修改前 baseline：`42 passed, 239 subtests passed`；僅因 sandbox 無法寫 `.pytest_cache` 出現 warning。
- 修改後完整 targeted regression：`169 passed, 262 subtests passed in 12.80s`。
- MCP snapshot digest：`63f5197dc03e258d4f6f113000fe6baffc4055da82fa06dba8ca994869bdf717`。
- `git diff --check`：無 whitespace error；僅顯示既有 LF/CRLF working-copy warning。

## 決策紀錄

- OMI 不直接讀 Atlas SQLite，避免 schema 與 lifecycle 耦合。
- Atlas GET 只讀 canonical cache；OMI request path 不擁有 provider refresh。
- 自動規劃只把 `news.events` 放入 optional；caller 的 explicit selection 優先。
- 空集合代表 bounded query 沒有觀測到相符事件，不代表事件不存在。
- Feature flag 預設關閉；source readiness 與 runtime adoption 分開驗收。

## 已知限制

- v1 target matching 使用 OMI target label/name/symbol/id 作 bounded `q`；更完整 alias/entity bridge 需後續獨立契約。
- 自動規劃的 `news.events` 是 optional；若核心 response 已用盡 byte budget，v4 可裁掉該 capability，並在 `projection.omitted_capabilities` 如實標示。需要保證取得時，consumer 應明確選取 `news.events`。
- Atlas runtime schema v3 / contract `1.1` 的 cold-start 採用尚未在本次 source 工作中驗證。
- 尚未啟用 `.env.runtime`，也尚未做 MCP host fresh-session proof。

## 下一步

1. 取得 runtime restart authority 後，確認 Atlas 採用 schema v3 / contract `1.1`。
2. 設定 OMI runtime 的 Atlas shadow flag，僅重啟 OMI named component。
3. 以 fresh MCP session 執行 `initialize -> tools/list -> omi.ask` adoption proof。
