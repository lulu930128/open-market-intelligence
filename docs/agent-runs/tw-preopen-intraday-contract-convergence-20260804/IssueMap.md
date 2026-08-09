# OMI-TW-001～011 問題、owner 與修正矩陣

## 使用方式

- 本表是實作順序與驗收的追蹤入口；詳細限制與完成定義以 `Prompt.md` 為準。
- 「已確認」代表已由 source、fixed-time probe、live payload 或 DB 證據證明；
  「契約澄清」代表原始現象包含真 bug，但不能用原提案的單一布林規則修正。
- 實作時每一列先建立會失敗的 deterministic regression，再改 canonical owner。

## 問題矩陣

| ID | 判定 | Canonical owner | 預定修正 | 里程碑 | 核心驗收 |
| --- | --- | --- | --- | --- | --- |
| OMI-TW-001 | 已確認 | `realtime_contract`／Taiwan session resolver | 將 raw `preopen_auction` 經單一 resolver 映射到 canonical preopen active auction；quote depth/facts 與 trade price usability 分離 | M1 | 盤前 10 秒 quote 不因 phase alias 被判 stale；last trade unavailable 仍維持不可交易 |
| OMI-TW-002 | 已確認 | `taiwan_projection` 共用 session resolver | `quote.auction` relevance 使用 canonical phase，不在 projection 維護第二份 alias set | M1 | preopen／closing auction available 時不再回 `SESSION_NOT_AUCTION` |
| OMI-TW-003 | 已確認 | `taiwan_market_state` trade-value eligibility | 移除 previous daily value 對 current-session cumulative 的 fallback；依 phase/date/semantics/event time 選 eligible value | M2 | 08:50～08:59 當日累積值 unavailable/null；09:00 後只採當日證據；post-close 才可採同日 official value |
| OMI-TW-004 | 已確認 | observation-aware freshness resolver | 依 observation kind、bar interval、partial/finalized 與 provider delay 計算 freshness；policy 與 research usability 分離 | M1 | 31 秒級 1m bar 在合理 interval window 內 research usable；execution-grade 不被自動放寬 |
| OMI-TW-005 | 已確認 | `data_quality_contract` continuity | 先依交易日/session/calendar 分 segment；只對 segment 內預期間距找 missing interval | M2 | 隔夜、週末、休市不計 missing；同一 session 真缺 bar 仍被抓到 |
| OMI-TW-006 | 已確認 | market index service／AI market projection | current-session 優先讀 index minute snapshot；daily summary 明確為 official completed close，不能投影成 live | M3 | 無 current minute 時 previous close 有 fallback reason 且 `current_for_requested_session=false` |
| OMI-TW-007 | 契約澄清 | `data.freshness` aggregate／capability status | 分離 temporal、session alignment、completeness、coverage、oldest/newest as-of、mixed state；保留 `partial + current` 合法組合 | M3 | consumer 可判斷「資料新但不完整」與「完整但屬前一交易日」，不只看單一 `as_of` |
| OMI-TW-008 | 已確認＋scope 修正 | `source_health_context`／`provider_health` serializer | AI projection 重用 row age/stale 語意；aggregate 只看 requested/active scope；歷史 row 標 lifecycle | M4 | 181 筆過期 row 不會因 1 筆新 row 使整體 current；每列 age/stale 可見 |
| OMI-TW-009 | 已確認 | `decision_core` NLU hint matcher | 建立可重用的 negation/context-aware matcher；explicit intent 優先，否定詞只作用於鄰近 span | M5 | 「不做交易、持倉或風險判斷」不產生 position/risk intent；「分析下跌風險」仍是 risk check |
| OMI-TW-010 | 已確認 | futures context／capability registry | 有權威 health 就投影 supported payload；否則 capability 對 TXF 為 not-applicable | M4 | 不再出現 applicable/available 但 `semantic_payload_empty` |
| OMI-TW-011 | 非執行 bug；telemetry 缺口 | reconciliation／reader telemetry | 保留 `refresh_if_missing` 為 permission；分開 reader、provider、tool run、cache、outcome 與 not-attempted reason | M5 | `attempted=false` 只代表無 tracked tool run，不再被誤解成 reader/provider 完全未嘗試 |

## 共用契約決策

### Session identity

- 同時保留：`raw_session_phase`、`canonical_session_phase`、`market_session`、
  `observation_mix`。
- `market_session` 由交易日曆與 authoritative clock 決定；provider observation
  phase 只能成為 observation metadata，不能把 09:00 市場狀態降成 `mixed`。

### Freshness axes

- `is_current`：現有 evidence 在自身 scope 內是否夠新。
- `current_for_requested_session`：required evidence 是否對齊本次要求的 session。
- `is_complete`／`completeness_status`：required capability 或欄位是否齊全。
- `coverage_status`：universe／sample 的覆蓋程度。
- `oldest_required_as_of`、`newest_required_as_of`、`mixed_as_of`：揭露時間混合。
- `as_of` 保留相容欄位，但必須附 `as_of_semantics`；consumer 不得只靠它判斷
  readiness。

### Indices

- Live index observation 與 official completed close 是兩種 component。
- `market.indices` 保留為相容 composite；若新增細分 capability，必須 additive。
- Previous close 可作 reference/fallback，但不得取得 live/current-session 標籤。

### Source health

- `request_health`、`persisted_health`、`effective_health` 與 row snapshot freshness
  分離。
- Aggregate freshness 以 requested capability/target 的 required rows 計算，不以
  全 market 的 `MAX(checked_at)` 代表整體。
- 舊 row 不刪除；以 `active`、`expired`、`historical` 或等價 lifecycle 投影。

### Refresh reconciliation

- `refresh_requested`：caller 是否要求／允許。
- `refresh_allowed`：policy 是否允許 bounded refresh。
- `primary_reader_attempted`：主要 reader 是否執行。
- `provider_fetch_attempted`：reader 是否真的呼叫外部 provider。
- `tool_run_attempted`：是否有受 reconciliation 追蹤的 executable tool run。
- `cache_hit`、`outcome`、`not_attempted_reason`：說明結果。
- `fill_actions` 是可能的補資料行為，不代表每一項都在同一 request 自動執行。

## 不得誤修的正常限制

| 狀態 | 正確 outward 語意 |
| --- | --- |
| 開盤初期 actual-trade breadth coverage 低 | `partial`／`pending`，揭露 coverage 與 unknown，不納入 `pz` |
| 盤中 cumulative trade value 為估計 | `estimate=true`、method／authority／confidence 可見 |
| Hot groups／ranking universe 不完整 | scheduler-owned、scope/coverage visible，不在 read path 全市場補抓 |
| 5d／20d baseline 歷史不足 | `warmup`／sample days visible，不標 provider failure |

## Live acceptance 時段對照

| 時段 | 主要 issue |
| --- | --- |
| 08:50～08:59 | 001、002、003、007、008、009、011 |
| 09:00～09:02 | 001、002、003、004、006、007 |
| 09:05～09:20 | 004、006、007、008、010、011 |
| 13:24～13:31 | 001、002、003、006、007 |
| Post-close／跨日 replay | 003、005、006、007、008 |

## 2026-08-04 非交易時段驗收狀態

| ID | Deterministic／formal smoke | 2026-08-05 live 狀態 |
| --- | --- | --- |
| OMI-TW-001 | Canonical `preopen_auction`／`regular_live` regressions passed | `not observed` |
| OMI-TW-002 | Auction projection alias regressions passed | `not observed` |
| OMI-TW-003 | Preopen trade-value quarantine + post-close eligibility regressions passed | `not observed` |
| OMI-TW-004 | Interval-aware 1m freshness regressions passed | `not observed` |
| OMI-TW-005 | Trading-day boundary／true intraday gap regressions passed | overnight replay 待驗收 |
| OMI-TW-006 | Formal post-close TAIEX/TPEX current close + timestamp normalization passed | intraday handoff `not observed` |
| OMI-TW-007 | Formal `ready/current/complete` post-close freshness passed | preopen／intraday `not observed` |
| OMI-TW-008 | Formal mixed-age aggregate + row age/stale/lifecycle projection passed | live active-scope `not observed` |
| OMI-TW-009 | Negation table tests與 formal REST/repo MCP UTF-8 parity passed | live prompt replay 待驗收 |
| OMI-TW-010 | Formal TXF quote/daily source-health semantic payload passed | stable intraday 待驗收 |
| OMI-TW-011 | Formal permission/reader/tool/provider/cache telemetry passed | live refresh-needed case `not observed` |

「passed」只代表 deterministic 或明列的 post-close/formal runtime surface；不等於
盤前、開盤第一分鐘或 closing auction 已實際觀察。
