# Shared Market Data Core Handoff Checklist

## 1. Purpose

本文件定義台股總平台完成後，美股如何判斷「可以開始接」；它不是要求台股使用特定內部檔名，而是要求穩定能力與可重現證據。

G0只接受實際checkout與runtime evidence，不接受下列替代物：

- 設計文件宣稱完成。
- type／interface已建立但production無caller。
- unit fake通過但沒有actual-data reference slice。
- shadow／dark path存在但production未adopt。
- 單一health endpoint正常但operation/consumer未接。

## 2. Required handoff packet

台股Core task交付時，至少提供：

| Artifact | Required content |
| --- | --- |
| Source identity | branch、commit SHA、dirty status、contract versions |
| Core surface map | public modules/types、registration API、gateway、resolver、registry/dispatcher、repository/transaction ports |
| Acceptance matrix | TW B–G required rows與status；不得有blocked |
| Test evidence | exact commands、exit codes、relevant logs/artifact paths |
| Actual-data proof | provider response/raw receipt、canonical candidates、persisted reread、resolved result、lineage、stable projection |
| Runtime proof | launcher selected PID/port/mode、adopted source SHA、health與bounded request evidence |
| Compatibility | v1 adapters、deprecated fields、removal window、known external callers |
| Rollout/rollback | per-capability modes、telemetry、rollback entrypoint與rehearsal result |
| Known limitations | unsupported capability、provider/plan restriction、schema/data limitation、deferred KGI/M5 scope |

建議保存為task artifact JSON＋人類可讀摘要；artifact schema未定版前不得由US自行假設欄位。

## 3. G0 critical checklist

狀態只使用`pending`、`passed`、`blocked`、`not_applicable_with_evidence`。Critical項目不可waive。

| ID | Critical requirement | Required proof | Initial status |
| --- | --- | --- | --- |
| G0-01 | `DataRequirementV2`可表達instrument/target、capability、purpose、realtime/session、freshness/quality、bounds與typed bars/dataset需求 | serialization/validation tests + public type path | pending |
| G0-02 | `RefreshRequirementV1`可表達dataset、target、reason、coverage、calls/runtime/range/symbol bounds、cursor、postcondition | contract tests + lifecycle caller | pending |
| G0-03 | Market-owned `ProviderCapabilityDescriptorV2`可注入；Shared Core無TW/US provider catalog | registration/catalog tests + import inventory | pending |
| G0-04 | Cache-first Gateway先resolve再決定acquisition；`cache_only`/completed-session zero I/O | fake store/port invocation tests | pending |
| G0-05 | Acquisition port/handle lifecycle定版，具timeout、cancel、external-call/subscription count、cleanup、health | fault-injection/cleanup tests | pending |
| G0-06 | Canonical candidates保持provider coherence；adapter不先fallback/selection | cross-provider conflict fixtures | pending |
| G0-07 | Resolver是唯一final selection owner，能輸出quote/depth/auction/bar/trading status/dataset evidence所需typed result | resolver/result contract tests | pending |
| G0-08 | `MarketDataResultV1`或等價stable envelope保留requirement、resolved payload、candidate summary、acquisition、provider/dataset/resolved health、lineage與limitations | serialization/API projection tests | pending |
| G0-09 | Dataset Registry具operation binding/dispatcher、expected state、eligibility、bounds、cursor、postcondition、result summary | production registry operation test | pending |
| G0-10 | Transaction ownership清楚；provider I/O不持有DB transaction；commit failure rollback/rethrow；post-write repository reread | DB/transaction/failure tests | pending |
| G0-11 | Provider Health、Dataset Health、Resolved Evidence Health分離且有request/persisted/effective semantics | contract + persistence/outward tests | pending |
| G0-12 | `cache_only`、`prefer_live`、`require_live`、`completed_session`語意與policy-unmet/fallback行為已定版 | policy matrix tests | pending |
| G0-13 | Per-capability off/shadow/compare/canary/on、telemetry與rollback可重用 | rollout registry tests + rehearsal artifact | pending |
| G0-14 | 至少一條TW actual-data vertical slice經provider→canonical→persist/reread→resolver→projection成為production path | actual-data + runtime + API evidence | pending |
| G0-15 | 台股task已標`TW_MARKET_DATA_PLATFORM_PRODUCTION_CONVERGED`，其AcceptanceMatrix B–G required rows全部passed | task docs + reproducible commands/artifacts | pending |

## 4. US compile-only compatibility probe

台股handoff packet先通過人工審查後，US執行最小probe；仍不切production：

1. Import final Core public types，不import`app.market`。
2. 以fake Yahoo／AlphaVantage descriptors與ports註冊US market。
3. 建立cache-only daily requirement，證明port calls = 0。
4. 建立prefer-live daily requirement，證明primary candidate成功與fallback candidate情境。
5. 建立both-unavailable、timeout、rate-limited、plan-restricted情境。
6. 建立provider conflict與incoherent candidate fixture，證明Core不悄悄混欄位。
7. 以fake repository執行refresh、persist、reread、postcondition。
8. 驗證US projection只接resolved result，不接provider payload。

Probe通過後仍只解鎖B1；不自動解鎖Daily/Intraday/Consumer production on。

## 5. TW-US mapping

| US G0 item | TW umbrella task evidence |
| --- | --- |
| G0-01、04、07、08、12 | AcceptanceMatrix B-01、B-03、B-04、B-05、B-06 |
| G0-03、05、06 | B-02 + provider/catalog/port tests |
| G0-09、10 | E-01、E-02、E-04 + DB transaction evidence |
| G0-11 | B-07 + outward health tests |
| G0-13 | G-02 + rollout artifact |
| G0-14 | TW actual-data vertical slice + G-04 |
| G0-15 | TW completion rule |

若台股AcceptanceMatrix編號調整，以能力與證據內容為準；US task更新mapping，不降低gate。

## 6. Version and compatibility rules

- US binding只依賴Core公開contract/version，不依賴TW implementation modules。
- Contract breaking change必須有version bump、adapter/migration、consumer inventory與rollback。
- Additive optional field若影響lineage/freshness/health判斷，仍需US contract test，不視為純schema擴充。
- Deprecated v1 seam只能做內部compatibility；不得讓US新增依賴延長legacy壽命。
- 若TW final名稱與proposal不同，採actual final contract；附件名稱不構成API承諾。

## 7. Gate decision procedure

1. 固定台股source identity與handoff packet hash。
2. 逐項填寫G0-01至G0-15的evidence link／command／result。
3. 重跑最小shared contract與US compile-only probe。
4. 檢查dirty worktree是否改變已驗收source；有差異就重新評估。
5. 在`Progress.md`寫入：
   - `G0_status`
   - Core versions/SHA
   - passed/blocked items
   - probe commands/results
   - unresolved compatibility risks
6. 全部critical項passed才把B1改為`planned`／`in_progress`；否則維持`blocked`。

## 8. Automatic blockers

- `execute_acquisition`／Gateway仍無production caller或只支援單一Research purpose。
- Registry仍只有operation name，沒有可執行dispatcher/postcondition。
- Resolver input已被market adapter預先fallback成單一candidate。
- GET/cache-only可觸發provider、repair、subscription或write。
- Shared Core直接import TW/US provider service/catalog。
- Actual-data proof沒有DB reread、lineage或restart後readback。
- Runtime採用的SHA/mode/port無法證明。
- TW task只標source-complete、shadow-ready或canary-pending。
- AcceptanceMatrix有required `pending`／`blocked`。
- Rollback需要刪資料、downgrade schema或broad-kill未知process。

## 9. G0 output template

```text
G0_status: passed | blocked
reviewed_at:
tw_task_status:
tw_source_sha:
core_contract_versions:
handoff_artifact:
passed_items: []
blocked_items: []
us_probe_result:
runtime_identity:
compatibility_notes: []
next_unlocked_package: B1 | none
```
