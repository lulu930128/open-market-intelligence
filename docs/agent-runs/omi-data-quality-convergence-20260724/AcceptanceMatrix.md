# Acceptance Matrix

本表把 2026-07-24 驗收清單收斂為產品級 invariants。`implemented` 表示已有
程式行為與 focused regression；`explicit_gap` 表示 provider 能力仍不存在，但
outward contract 已誠實降級且不再產生錯誤結論；`deferred` 是使用者指定不處理。

| 狀態 | 問題 ID | 收斂結果 | 主要證據 |
| --- | --- | --- | --- |
| implemented | P0-01～04、P1-05～06 | 診斷 scope 與一般 decision pipeline 分離；capability/source-health 有 bounded 非空 projection 或明確 missing reason | `test_ai_supplemental_contexts.py`、`test_ai_capability_contract.py` |
| implemented | P0-07～11、P1-12 | `omi.data.quality.v1` 成為 manifest、slots、passport、readiness 的單一狀態來源 | `test_ai_decision_envelope.py`、`test_intraday_contract_remediation.py` |
| implemented | P0-13～16、P1-18～24 | TWD 成交值／單位／field status、breadth universe/unknown、樣本覆蓋與 selective payload 已明確；不足樣本保持 partial | `test_taiwan_market_state.py`、`test_market_index_daily_stats.py`、`test_ai_tool_boundaries.py`、`test_ai_freshness_guard.py` |
| deferred | P0-17 | 不變更 universe 定義或重算正式差異 | 使用者明確指定 |
| deferred | P0-25～27 | 不處理 TAIEX 開盤欄位、異常跳點與集合競價 flatline | 使用者明確指定 |
| implemented | P1-28～29 | interval 使用 provider 實際 `5s`；point_count、returned_count、bar_limit、truncated 分離 | `test_intraday_contract_remediation.py` |
| explicit_gap | P0-30 | TPEX 單一收盤快照不冒充 intraday series | `coverage_status=single_official_close_snapshot` |
| implemented | P0-31～34、P1-35 | single snapshot、quote/daily date、trade value/contribution date 進 canonical quality/fusion gate；跨日不得 decision-ready | `test_ai_decision_envelope.py`、`test_intraday_contract_remediation.py` |
| implemented | P0-36～38、P1-39～49 | evidence-only exclusion、quote/technical 基準一致性、前日 chips context-only、depth 狀態、收盤量 reconciliation、lineage、樣本數、refresh outcome、fundamentals/cross-market freshness 已收斂 | `test_ai_ask_stages.py`、`test_ai_decision_envelope.py`、`test_job_retry.py`、`test_technical_report.py` |
| deferred | P0-50 | 不重算 ADS ratio、FX 或 ADR 公式 | 使用者明確指定 |
| implemented | P1-51～52 | ADR aligned reference 與 latest comparison role 分離；broker trade date、aggregation window 與 ingestion time 語意分離 | `test_adr_parity.py`、`test_ai_outward_contract.py` |
| implemented | P0-53～55、P1-56～59 | JP stale 觸發 bounded refresh；volume not-provided、delivery status、previous-close date、source health 與 decision gate 明確 | `test_jp_market_data.py`、`test_ai_ask_stages.py` |
| explicit_gap | P1-60 | JP price 仍只有 Yahoo；contract 公開 provider 與 source-health，不宣稱雙來源 | `jp_market/source_health.py` |
| implemented | P0-61～63、P1-64～68 | KR stale daily、continuity gaps、source health、live summary、row-count 與 previous-close date 收斂 | `test_kr_market_data.py`、`test_ai_decision_envelope.py` |
| deferred | P0-69 | 不以本輪結果宣稱已完成故障注入與備援成功證明 | 使用者明確指定 |
| implemented | P0-70、P1-71～73 | fallback primary/secondary/switch reason、cache use、degraded failures 與 transition history 可查 | `test_provider_health.py`、`test_ai_supplemental_contexts.py`、`test_ai_decision_envelope.py` |
| deferred | P1-74 | 不統一跨市場 freshness thresholds | 使用者明確指定 |
| implemented | P0-75、P1-76～82 | 排除條件、繁中、數字/null 格式、診斷 headline、compact/limit、response vs decision readiness 收斂 | `test_ai_answer_composer.py`、`test_technical_report.py`、`test_ai_freshness_guard.py`、`test_ai_decision_envelope.py` |
| implemented | P0-83～85、P1-87～88 | canonical truth、跨日 fusion、unit/release-phase 與 missing-data decision gate 已建立 | `data_quality_contract.py`、`test_ai_decision_envelope.py` |
| implemented | P0-86（不含 deferred 序列語意） | duplicate、non-monotonic、missing interval、interval mismatch、insufficient points 與 KR gaps 可偵測；不檢測 P0-25～27 涉及的 TAIEX jump/flatline | `test_ai_decision_envelope.py`、`test_kr_market_data.py` |

## Canonical invariants

1. `evidence.quality` 是資料品質唯一 canonical 結論。
2. `status.readiness.response_ready=true` 不代表 `decision_ready=true`。
3. Required capability 的 stale、missing、cross-date、unit unknown 或 continuity
   partial 會阻止 decision-ready。
4. Diagnostic target 一律 evidence-only。
5. 未選取 capability 不進 `evidence.data`；超過欄位、row 或 byte limit 時必須
   先壓縮 metadata、再省略 optional、最後才省略 required，並提供
   omission/limitation metadata。
6. Refresh action 必須綁定 target、capability、operation、range/limit、calls、
   timeout 與 external/cache side effect。
7. Realtime/freshness 判定使用 backend 內部完整 observation；consumer 的
   field selection 只能改變輸出，不得改變品質結論。
8. Frontend、MCP、Kuro 與其他模型只消費 backend contract，不重建市場語意。

## Runtime evidence

- Launcher-selected backend：`http://127.0.0.1:8400`，listener PID
  `13344`；health runtime root 為本 checkout，Python 為 repo `.venv`；
  readyz 的 runtime/database 均為 `ok`。
- `/api/ai/tools`：public tool `omi.ask`，default
  `omi.decision.v4`，registry `omi.capability.registry.v1`，21
  capabilities，包含 `market.volume_state`。
- HTTP：
  - diagnostic `capability_status` 即使 request
    `decision_with_evidence`，quality output 仍強制 `evidence_only`。
  - 2330 quote-only 在 `max_response_bytes=32768` 內保留
    `quote.snapshot`，沒有 omitted capability。
  - 非法 capability field 回結構化 HTTP 400。
  - 999999 回 `ok=false`、`request_status=rejected`、
    `TARGET_NOT_FOUND`，沒有 adapter `RuntimeException`。
- Realtime：盤後 2330 local daily close 判定
  `latest_completed_session`，`policy_satisfied=true`，不冒充 live；
  consumer 只選五個欄位時判定仍一致。
- SSE：`text/event-stream` 包含 status/evidence/delta/final/done；
  final 是相同 `omi.decision.v4` 且保留 selected evidence。
- MCP stdio：已完成 MCP `2025-06-18` initialize、dynamic
  `tools/list`、2330 success、999999 business failure；business failure
  的 MCP `isError=false`，由 structured contract 表達。
- Frontend：lint、TypeScript、production build 通過；targeted
  Playwright smoke `1 passed`，確認台股／韓股 selection 送出同一 v4
  request controls。
- Regression：完整 backend `975 passed in 85.13s`。
