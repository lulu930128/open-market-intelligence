# M6 對內 AI 與對外契約

## 目的

跨市場 relation context 是台股技術判讀的輔助 evidence，不是新的方向模型。Backend 擁有 intent routing、capability selection、freshness、relation lineage、摘要與限制；Frontend、MCP 與 Kuro 只顯示 structured fields，不重算 mapping、權重、分數或因果關係。

固定邊界：

- `role = confirmation_or_counter_evidence`
- `ranking_effect = none`
- `technical_score_effect = none`
- 跨市場專問不產生買賣 action；一般技術問題只增加支持、反證或資料限制，不改寫原技術 headline、stance 與 action plan。
- `stale`、`partial`、`blocked`、`missing` 與 `decision_usable=false` 必須保留，不能壓成中性或省略。

## 代表性 request

```json
{
  "question": "2330 的 ADR 與美股隔夜影響如何？",
  "target": {
    "type": "stock",
    "id": "2330",
    "market": "TW"
  },
  "output": "decision",
  "realtime_policy": "cache_only",
  "selection": {
    "required": [
      "target.identity",
      "cross_market.overnight",
      "cross_market.relations",
      "cross_market.parity",
      "data.freshness"
    ]
  }
}
```

未明示 `selection` 時，`cross_market` intent 對台股個股使用同一組 bounded defaults；query plan 只要求 `cross_market` domain，不因問題文字啟動無關 reader。

## Stable consumer paths

### Evidence owner

- Readiness：`evidence.capability_status[capability_id]`
- Capability data：`evidence.data[capability_id]`
- Canonical capabilities：
  - `cross_market.overnight`
  - `cross_market.relations`
  - `cross_market.parity`

Consumer 應以 capability status 判斷資料是否可用，再讀對應 capability data。不得以欄位是否存在取代 readiness，也不得從中文句子推回狀態。

### Human answer

`answer`／內部 `analysis.human_answer` 的 additive fields：

```json
{
  "style": "cross_market_context_summary",
  "intent": "cross_market",
  "stance": "supportive",
  "cross_market_context": {
    "kind": "cross_market_decision_context_v1",
    "status": "ready",
    "decision_usable": true,
    "as_of": "2026-08-08",
    "decision_at": "2026-08-09T01:00:00Z",
    "snapshot_id": "cmctx:2330:...",
    "methodology_version": "cross_market.relation_context.v2",
    "relation_snapshot_version": "relation_registry:...",
    "coverage": {},
    "missing": [],
    "warnings": [],
    "limitations": []
  },
  "context_role": "confirmation_or_counter_evidence",
  "ranking_effect": "none",
  "technical_score_effect": "none",
  "action_plan": []
}
```

一般 `trend_view`、`entry_decision` 等回答保留原本技術主體，只 additive 掛入 `cross_market_context`；supportive context 進 evidence 摘要，adverse context 進 counter-evidence／risks，不自動翻轉答案。

### Decision projection

Kuro-facing decision contract 使用：

- `decision.context.cross_market`（`omi.decision.v4` outward envelope）
- 來源對應內部 `analysis.decision_contract.context.cross_market`

此 projection 固定保留 role、status、decision usability、stance/confidence、as-of、snapshot/methodology/relation lineage、coverage、missing、warnings 與 limitations。它刻意不帶完整 `signals`；需要完整 evidence 的 caller 應讀 `evidence.data[...]`，避免 decision summary 成為第二份資料真相。

## MCP／Kuro 規則

- MCP `omi.ask` 原樣轉交 backend request／response；adapter 不直接讀 DB，也不重建 cross-market context。
- `mode=data_only` 只承諾 evidence surface；需要 human answer 與 `decision.context.cross_market` 的 caller 必須使用 `mode=full`。兩者都維持 read-only，且 adapter 固定 `allow_llm=false`、`allow_write=false`。
- Kuro 以 stable capability IDs、enum 與 structured fields 呈現；中文、英文、日文句子可以改寫，不得作為 machine contract。
- HTTP 與 MCP 必須對同一 request 對帳 contract version、snapshot ID、methodology version、freshness 與 limitations。
- Public capability snapshot 應包含三個 cross-market capabilities；snapshot digest 由既有 contract test 鎖定。

## 2026-08-09 runtime acceptance

- 正式 launcher 所有的 8400 backend listener 已從 PID `42420` 重載為 `11668`；新 process command 指向 repo `.venv` 與 `uvicorn app.main:app`，health 為 `ok`。
- `GET /api/ai/tools` 已公開 `cross_market.overnight`、`cross_market.relations`、`cross_market.parity`。
- `POST /api/ai/ask` 以 `cache_only`、`allow_external_fetch=false`、`allow_llm=false` 驗證：回傳 `omi.decision.v4`、`cross_market_context_summary`、bounded `decision.context.cross_market` 與五個指定 evidence keys。
- 當 canonical context 因 FX cache 超過 72 小時而 stale 時，三個 capabilities 一致回報 stale／unusable，且 `facts_usable=false`、`decision_usable=false`；不再由 legacy top-level `missing=[]` 誤判為 current。
- Standalone OMI_search `8797` 已完成 `initialize` → `notifications/initialized` → `tools/list` → `tools/call omi.ask`；protocol `2025-06-18`、session preserved、6 tools、`isError=false`，`mode=full` 可讀到與 HTTP 相同的 structured answer、decision context 與 evidence limits。
- Live SQLite 現為 Alembic `20260809_0055`，relation 5 筆、evidence 6 筆、materialized signal snapshot 0 筆。Launcher startup 同時套用了 worktree 內其他在途 migration，因此這不是 cross-market-only rollback drill；未呼叫 provider refresh。

尚未完成的是 user-visible browser acceptance 與 rollback drill。現有 live cache 的 stale 狀態是正確、可見的資料限制，不是 runtime 接線失敗；`snapshot_count=0` 也表示目前仍是 latest-cache projection，不能宣稱已有 point-in-time snapshot coverage。
