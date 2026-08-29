# Market Temporal / Evidence Axes Contract

本文件定義 OMI 如何分離市場時間、evidence lifecycle、authority、release、reconciliation 與 freshness。它不建立 universal `TemporalState`，也不以 Markdown 取代 source 中的 typed contract。

## Canonical owner

- Shared typed axes 以 `backend/app/market_data/contracts.py` 為 executable truth。
- Market-specific calendar、session transition 與 release window 留在各 market owner。
- Outward AI／API projection 必須保留正交 axes，不重新壓成單一 readiness 或 finalization 字串。
- 缺少的 axis 優先 additive typed extension；只有改變既有 serialized value、field meaning 或 consumer contract 時才需要 migration／version gate。

## Independent axes

### 1. Market Session

`MarketSession` 回答「市場現在或 observation 所屬的交易階段」。目前 shared values 是：

- `pre_open`
- `opening_auction`
- `continuous`
- `closing_auction`
- `close_resolution`
- `post_close`
- `closed`
- `unknown`

Market-specific presentation 可以顯示 `regular` 等 label，但不得把 presentation label 反向寫成 shared canonical value。

### 2. Instrument Trading Status

`InstrumentTradability` 回答個別商品能否交易。Market closed 不代表 instrument suspended；No Quote、No Trade、Halted 與 Suspended 不互相推導。

### 3. Evidence-object finalization

Finalization 必須由 evidence object 的 contract 定義，不建立跨所有 evidence 的大一統 enum。

- `BarObservation` 使用 `BarFinalization = provisional | final | corrected | unknown`，描述該 bar／time bucket 的成熟程度。
- `final` 本身不代表 exchange authority、official daily 已發布或 reconciliation 已完成。
- Session-close quote 是獨立 projection contract；它可以有 `resolving`／`session_final` 等 status，但不得因此擴張 generic `BarFinalization`。

### 4. Authority and lineage

`SourceLineage.authority` 回答來源權威類型，例如 exchange、broker、vendor、derived、cache。Authority 不代表資料已發布或已 final；exchange realtime 與 exchange official daily 仍是不同 dataset／evidence。

### 5. Release / publication

Release 回答特定 dataset 是否已到合法發布窗口並實際可用，例如 `pending_release`、`released`、`unavailable`、`unknown`。在 shared typed owner 尚未建立前，既有 outward `release_status` 是 projection semantics，不得被誤當 `MarketSession` 或 `BarFinalization`。

若新增 shared `ReleaseStatus`，必須是 additive source contract，並由 dataset lifecycle／market release policy 提供，而不是 frontend 或 consumer 依時鐘猜測。

### 6. Reconciliation

Reconciliation 比較兩份已具 identity 的 evidence，例如 session close 與 official daily close。常見狀態是 `pending`、`matched`、`mismatched`、`not_applicable`；比較結果不得覆寫任一原始 observation 的 session、authority 或 finalization。

### 7. Freshness

Freshness 回答 evidence 相對需求與時間是否仍可用。`current`／`fresh`／`live` 不代表 official final；official evidence 也可能 stale。Freshness 必須考慮 requested policy、instrument eligibility、event time、received／fetched time與 market session。

Completed-session evidence 使用 market-specific expected trade date 驗證，不用
固定 wall-clock 秒數決定跨週末／休市日後是否仍有效。台股 session close 的
candidate 必須對齊 `taiwan_presentation_session()` 所給 expected trade date；新一個
completed session 出現後，舊 session 才失效。

Market-specific emergency closure overlay 高於 annual schedule cache。年度快取中
「該日不存在」只代表未列於原年度排程，不得壓過後續宣布的颱風或其他臨時休市；
所有 continuity、expected date 與 presentation-session 計算共用相同 calendar owner。

## Derived labels

`official_final` 若需要作為 outward convenience label，只能是 derived state，不是 primitive enum member。至少同時需要：

```text
dataset_semantics == official_daily
and authority == exchange
and release_status == released
and item_finalization in {final, corrected}
```

Derived label 必須保留其 constituent fields；consumer 不得只收到單一 `official_final=true` 而失去 lineage、release 或 correction semantics。

## Taiwan session-close example

14:00 後、official daily 尚未發布：

```text
market_session = post_close
session_close.status = session_final
session_close.authority = exchange
official_daily.release_status = pending_release
reconciliation.status = pending
```

Official daily 到達後：

```text
market_session = post_close
session_close.status = session_final
official_daily.release_status = released
official_daily.finalization = final
official_daily.authority = exchange
reconciliation.status = matched | mismatched
```

Official daily 的到達不應把 session-close observation 從 `session_final` 改成另一種跨軸狀態；兩份 evidence 與 comparison result 應分別保存。

## Invariants

- Market Session != Instrument Trading Status。
- Market Session != item finalization。
- Freshness != finalization。
- Authority != release。
- `BarFinalization.final` != official daily released。
- Session final != official daily final。
- Post close != official daily released。
- Reconciliation 不得 mutate 原始 evidence semantics。
- `post_close + session_final + pending_release` 是合法組合。
- release window 已到但 canonical official daily evidence 尚未到達時，必須投影為 released-but-unavailable；不得繼續顯示 `pending_release`，也不得用前一交易日 official close 假裝當日資料。

## Negative acceptance

任何下列變更都必須被 architecture／contract review 拒絕：

- 建立混合 `pre_open`、`continuous`、`session_final`、`official_final` 的 universal enum。
- 以 exchange authority 自動推導 released／official final。
- 以 `current` 自動推導 live 或 official final。
- 讓 frontend、MCP 或 AI consumer 自行依時間決定 release／finalization。
- Official reconciliation 完成後覆寫原始 session-close authority、event time 或 session status。
