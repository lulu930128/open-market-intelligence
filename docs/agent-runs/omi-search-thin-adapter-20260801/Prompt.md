# OMI_search Thin Adapter

## 背景

`C:\GPT_MCPtool\OMI_search` 應只暴露並映射 OMI backend 的公開能力，不應自行判斷問題意圖、分析時間框架、target、freshness、refresh 時機或 response 語意。

目前 standalone adapter 仍包含 live quote 關鍵字判斷、US intraday 推斷、問題文字改寫、預設 refresh 決策、tool budget 數值修正，以及已失去 runtime caller 的 response projection helpers。這些責任與 OMI backend 的 AI decision contract 重複。

## 目標

- 讓 `OMI_search` 成為 thin MCP adapter：MCP protocol、公開 tool surface、相容欄位映射、固定 read-only 安全旗標、HTTP transport。
- 由 OMI backend 擁有 target resolution、question understanding、analysis horizon、freshness、refresh orchestration、budget/default validation、evidence shaping 與 canonical response。
- `tools/list` 優先使用 backend `/api/ai/tools` 的 `omi.ask` schema，離線時使用由 OMI 產生的 snapshot。
- 保留 `omi.search` legacy alias，但不讓 legacy 欄位污染 canonical `omi.ask`。
- MCP consumer 收到未經 adapter 語意投影的 `omi.decision.v4` envelope。

## 非目標

- 不改變 OMI backend 的市場判斷或 refresh policy。
- 不新增市場資料來源、DB 讀寫、LLM/report 寫入能力。
- 不重構 `agents/omi_mcp_server`；本次驗收範圍是 standalone `C:\GPT_MCPtool\OMI_search`。
- 不 commit、push 或發布。

## 硬性限制

- `allow_llm=false`、`allow_write=false`、`caller_profile=omi_search` 由 adapter 固定。
- `refresh_if_missing` 必須由 caller 明確指定；adapter 不得從問題、target 或 market 推斷。
- canonical `omi.ask` 不接受 `stock_id` / `symbol` 推斷 target；只有隱藏的 legacy `omi.search` alias 可做舊欄位相容映射。
- adapter 不得改寫 `question`、推斷 `analysis_horizon`、補預設 strategy/ranking/limits，或裁切 backend response。
- 不覆蓋兩個 dirty worktree 中與本任務無關的既有變更。

## 完成條件

- source audit 找不到 live intent / horizon / freshness / response projection 判斷。
- payload tests 證明 canonical question 與明確欄位原樣 forwarding，缺省時不觸發 refresh。
- backend test 證明 question understanding 在 backend 內把 intraday 提示解析為 intraday，且不改變 caller 的 external-fetch 權限。
- standalone unit tests、Python syntax、schema snapshot parity、stdio MCP smoke 通過。
