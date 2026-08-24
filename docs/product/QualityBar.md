# Quality Bar

本文件定義 OMI 被視為「可長期使用」前必須維持的品質標準。

## 1. 市場資料可信度

OMI 必須讓使用者知道自己看到的是什麼：

- 哪個 provider / source。
- event time。
- fetched / received time。
- market session。
- instrument trading status。
- live / delayed / stale / completed session。
- partial / finalized。
- fallback 是否發生。
- missing / warning / provider failure。

不得只因 API 回傳數字就宣稱資料可用。

## 2. Canonical Data 品質

新增 provider 時：

- 不得偽裝成其他 provider。
- 必須轉成 provider-neutral observation。
- raw provider schema 不得擴散到 consumer。
- provider-specific semantic 不得偷偷塞進另一 provider contract。

Canonical contract 必須安全處理：

- null。
- missing。
- malformed payload。
- zero-like values。
- timezone。
- session boundary。
- partial bar。
- out-of-order event。
- duplicate event。

## 3. Unknown / Missing 語意

以下規則不可違反：

- Unknown != 0。
- Missing != empty confirmed。
- No Quote != No Trade。
- No Trade != Suspended。
- Provider unavailable != Dataset unavailable。
- Account unavailable != Empty portfolio。
- Unknown cost != Zero cost。

任何 fallback / coercion 都要有可追蹤 reason。

## 4. Resolution 品質

Resolver 必須 deterministic 且可解釋。

Resolved result 至少能回答：

- selected provider。
- selected event time。
- candidate status。
- selection reason。
- fallback chain。
- freshness。
- decision/execution usability。

`require_live` 未滿足時不得把 stale / completed session 冒充 live。

## 5. Trading Status 品質

Market Session 與 Instrument Trading Status 分開建模。

停牌、停止買賣、尚未第一筆成交、provider missing 與 market closed 必須能被區分或明確標成 unknown。

不得用「沒有 quote」直接推導 trading status。

## 6. Dataset Lifecycle 品質

每個 production dataset 都應有明確 owner。

重要 dataset 至少定義：

- expected state。
- eligibility。
- freshness。
- repairability。
- refresh operation。
- postcondition。
- source health。

如果資料 stale 但沒有 repair path，UI/AI 必須如實呈現，不得暗示 self-healing 已完成。

## 7. Provider / Dataset / Evidence Health

健康度至少分成：

1. Provider Health。
2. Dataset Health。
3. Resolved Evidence Health。

不得因 fallback provider stale 就將已由其他 provider 補齊的 selected dataset 宣稱 stale。

不得把 KGI Quote、KGI Data、KGI Account 合成單一紅綠燈。

## 8. Research / AI 品質

AI 回答必須可檢查與反駁。

涉及交易研究時，應盡量包含：

- evidence。
- scenario。
- support / resistance / technical level。
- entry confirmation。
- invalidation。
- risk。
- counter-evidence。
- data limitations。

AI 不得自行 call provider、推 freshness、填補 missing 或繞過 capability status。

## 9. Capability 品質

任何 outward supported capability：

- 必須有 projection。
- 必須有 schema。
- 必須有最小 contract test。
- 若宣告 refreshable，必須有 bounded operation。

`advertised => projection exists` 應由 CI 保護。

Planned / unsupported / not_applicable 必須是真實狀態，不得用 placeholder 假裝完成。

## 10. Account / Portfolio 品質

- Account 503 不破壞市場行情。
- Quote failure 不清空持倉。
- partial account payload 不 destructive replace。
- unknown cost 不計算假 PnL。
- Position truth 與 Market Price truth 分離。
- valuation failure 不改寫 position state。
- sync 必須有 observed_at / source / completeness semantics。

## 11. UX / UI 品質

Frontend 是研究工作台。

優先：

- 資訊密度。
- 掃描效率。
- 操作節奏。
- 資料品質可見。
- desktop/mobile 穩定。

避免：

- 文字溢出。
- 控制重疊。
- 同一 selection 重複多處。
- 為視覺效果隱藏 warning。
- 在 frontend hardcode backend market logic。
- 因市場不同就複製一套不相容 UI contract。

台股是 reference UI，美股可以是 first-class UI，但共用資訊架構與 backend contract。

## 12. Refresh / External IO 品質

任何 external refresh：

- bounded target。
- bounded range。
- timeout。
- call budget。
- provider identity。
- source lineage。
- outcome。
- error classification。

不得 silent retry 到無界。
不得在 cache-only read path 隱性消耗外部 quota。

## 13. 資料保存品質

- 不 silent data loss。
- drop/filter/merge mismatch 要可解釋。
- DB schema 變更走 migration。
- 不重建 local SQLite 來解資料 contract 問題。
- production-like local data 未確認前不得刪除。

## 14. 架構品質

新增抽象必須服務真實責任隔離，不為行數而拆。

優先保護：

```text
Provider
→ Canonical Observation
→ Resolver / Control
→ Market / Research
→ Consumer
```

Account Plane 獨立。

不要 Big Bang rewrite。
新地基先 shadow、比對、feature flag、再 cutover。

## 15. 驗證品質

依風險選擇最小足夠驗證：

- docs / prompt / AGENTS：UTF-8 + diff check。
- pure canonical / resolver：unit / contract tests。
- provider integration：fixture + targeted integration。
- freshness / repair / status：regression + data smoke。
- API / MCP / outward contract：contract inventory + runtime smoke。
- frontend：lint/typecheck/build；必要時 browser。
- Account/Portfolio：failure/partial/unknown-cost regression。
- external side effect：先確認，再驗證。

預設優先使用 repo safe validation wrapper，不把 E2E、全量 refresh、長駐 runtime 當普通修改預設。

## 16. 不可接受的捷徑

- KGI 假裝 MIS 作為新架構。
- 在 consumer 裡自行 fallback。
- stale 包成 current。
- missing 轉 0。
- no quote 直接當 no trade。
- 前端 hardcode backend 缺口。
- provider adapter 直接寫市場 business truth。
- 503 直接清空 account state。
- unsupported capability 仍宣告 supported。
- 為了 demo 隱藏 provider failure。
