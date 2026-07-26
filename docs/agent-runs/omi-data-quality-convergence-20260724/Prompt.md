# OMI 資料品質與對外契約收斂

## Goal

- 將 2026-07-24 盤中驗收問題收斂為可長期維護的資料品質核心，而不是逐欄位修補。
- 讓 `omi.decision.v4` 對 outward consumer 提供唯一 canonical 的 availability、
  freshness、completeness、realtime、continuity、release phase 與
  decision usability 判定。
- 純診斷請求只回傳診斷 evidence，不進入投資決策合成。
- 阻止不同交易日、單位、發布階段或不完整序列被無條件合成為高強度結論。
- 補齊全域 source-health、provider failure、bounded refresh 與資料能力缺口的
  可觀測性。

## Non-goals

本輪依使用者指示不處理：

- P0-17：TWSE 市場廣度與正式數字差異的 universe 口徑。
- P0-25～P0-27：TAIEX 開盤、異常跳點與收盤集合競價序列。
- P0-50：ADR parity 的 ADS ratio、FX 與參考時點重算。
- P0-69：以故障注入證明雙來源備援實際切換。
- P1-74：重新統一各市場 freshness threshold。

以上項目可以在測試或文件中被標為 deferred，但不得在本輪順手改變其公式、
universe、provider 或 threshold。

## Hard constraints

- 台股維持核心市場；JP、KR、US、Crypto 是 context layer。
- Backend 是資料品質、freshness、fallback、AI reasoning 與 outward contract 的
  唯一 owner。
- Frontend、MCP、Kuro 只消費 backend contract，不重建市場語意。
- Kuro 不使用專用 response shape；可朗讀稿、persona、斷句與 TTS 留在 Kuro。
- 保留 `omi.decision.v3`、`omi.ai.ask.v2` 與既有 public route 相容性。
- 不刪除、重建或覆蓋 `data/open_market_intelligence.db`。
- 不在 GET/read path 觸發無界 backfill、付費 LLM、報告或記憶寫入。
- 外部 refresh 必須按 capability、target、range、calls、timeout 與 cost bounded。
- `missing`、`stale`、`partial`、`not_applicable`、provider failure 不得被包成
  正常 `0` 或 `ready`。
- 本輪不做自動交易或下單能力。

## Context

- Repo：`C:\project\Open Market Intelligence`
- Branch：`codex-kr-market-readiness`
- Acceptance source：
  `C:\Users\thoma\Downloads\OMI_功能驗收問題清單_2026-07-24.txt`
- Current outward contract：`omi.decision.v4`
- Current runtime：launcher-selected `http://127.0.0.1:8400`；`/api/ai/tools`
  已宣告 v4 與 capability registry。
- Worktree 含上一階段 v4 未提交變更；本輪必須保留並在其上增量收斂。

## Deliverables

- Canonical data-quality contract 與 deterministic projection。
- Diagnostic intent isolation 與 capability/source-health outward projection。
- Cross-date/unit/release/continuity fusion gate。
- Provider/source-health/fallback telemetry 的一致 outward 語意。
- 既有市場資料能力的 honest status、bounded fill 與必要缺口修正。
- Compact payload、limit、語言與缺值格式 regression。
- HTTP/SSE/MCP/Frontend consumer compatibility tests。
- Acceptance matrix、驗證證據與剩餘 limitations。

## Done criteria

- 納入範圍的 P0 invariant 有 focused regression。
- `status.readiness`、`evidence.quality`、manifest 與 slots 不再互相矛盾。
- 診斷 request 不含 stance、進場、突破、停損或投資操作段落。
- 不相容 observation 不得提升為 decision-ready。
- `capability_status` 與全域 `source_health` 可由 v4 bounded selection 取得非空、
  可解釋結果或明確 missing reason。
- `compact` 與各 limits 實際限制 outward payload。
- Backend full profile、相關 frontend profile、HTTP/SSE/MCP business probes 通過。

## Open questions / assumptions

- 驗收清單是問題輸入，不將每個推測直接視為 root cause；先以 v4
  request/response、DB、provider event 與 source payload 重現。
- 付費 API 原則上允許，但任何實際付費 smoke 仍需一次性明確 cost bound。
