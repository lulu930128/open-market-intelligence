# 問題確認與規格修訂

## 結論

| 項目 | 判定 | 現況 | 計畫修訂 |
| --- | --- | --- | --- |
| C01 Trading Status authority/freshness | 已證實 | `official_first` 排在 freshness 前；stale official 仍 eligible 並壓過 live broker conflict | 使用 Trading Status 專用 currentness tier；不改共用 quote/depth/bar resolver |
| C02 Daily eligibility | 部分證實 | evaluator 已正確支援 `False -> NOT_APPLICABLE`、`None -> UNKNOWN`；`tw.daily.ohlcv` policy仍只有`listed_instrument` | 只補 eligibility policy/registry/test，不重寫 health enum或提前取得 official status |
| C03 US default capability truth | 已證實，另發現一項 | raw US defaults含`technical.structure`；`ownership.insider_transactions`另因market=`us`與`US`不相容；兩者normalize後才被移除 | 移除兩個US general auto defaults、將insider market正規化為`US`、加scoped subset與explicit-capability tests |
| Runtime adoption pending | 狀態已變動但未完成 | 21:00 runtime有正確launcher lineage、source時間順序與catalog hash；尚無mode/session/rollback證據 | 視為planning baseline，不宣告runtime-accepted；contract fix後重新執行Gate R |

## C01 — 決定性證據

Source：

- `backend/app/market_data/resolution.py` 的 `_resolve(... official_first=True)` 排序 key 為 `official_rank -> freshness_rank -> provider_priority`。
- `prefer_live` 只拒絕 missing/unknown；stale candidate仍 eligible。
- 既有 test只覆蓋fresh official勝過live broker，未覆蓋stale official conflict。

Pure reproducer結果：

```json
{
  "selected_provider": "twse",
  "selected_status": "tradable",
  "health": "stale",
  "candidates": [
    {"provider": "kgi", "freshness": "live", "eligible": true},
    {"provider": "twse", "freshness": "stale", "eligible": true}
  ]
}
```

判斷：這不是單純「結果標了 stale 所以可接受」。Selection仍把舊 official `TRADABLE` 放進 `trading_status`，consumer若只讀status就可能得到錯誤當前語意，因此必須在pure resolver修正。

## C02 — 決定性證據

Source：

- `evaluate_dataset_health()` 已接受 `eligible: bool | None`。
- `eligible=False` 產生 `DatasetHealthStatus.NOT_APPLICABLE / DATASET_NOT_ELIGIBLE`。
- `eligible=None` 產生 `DatasetHealthStatus.UNKNOWN / ELIGIBILITY_UNKNOWN`。
- `tw.daily.ohlcv` 的 `eligibility_policy` 目前為 `listed_instrument`，無法宣告instrument-at-date trading eligibility。
- 既有 test已覆蓋`False`，但沒有明確鎖住`None -> UNKNOWN`，也沒有驗證daily spec的instrument-level policy。

Pure probe結果：

```json
{
  "eligibility_policy": "listed_instrument",
  "health_cases": [
    {"eligible": false, "status": "not_applicable", "detail": "DATASET_NOT_ELIGIBLE"},
    {"eligible": null, "status": "unknown", "detail": "ELIGIBILITY_UNKNOWN"}
  ]
}
```

判斷：附件描述的產品風險成立，但實作範圍應縮小。Health outcome已正確；1.1只需要讓registry policy誠實表達caller應提供的eligibility facts。

## C03 — 決定性證據

Source：

- `technical.structure`正式spec只支援TW scopes/market。
- `_default_capabilities("us_stock", "general")`仍列入`technical.structure`。
- `ownership.insider_transactions` scope為`us_stock`，但market寫成小寫`us`，和`_target_market()`正規化後的`US`不相容。
- `normalize_selection()`再以`_compatible()`過濾，因此目前outward required list沒有該capability。

Pure probe結果：

```json
{
  "raw_contains_technical": true,
  "normalized_contains_technical": false,
  "raw_contains_insider_transactions": true,
  "normalized_contains_insider_transactions": false
}
```

判斷：technical項目目前不是outward correctness bug，但raw default intent與capability truth不一致。Insider項目另有explicit capability market casing defect；若只把`us`改成`US`，會意外讓每次US general query新增一項default capability。1.1的安全修法是同步把insider移出general auto defaults，只恢復explicit/domain selection，避免擴大預設外部工作量。

## Current runtime baseline

- Latest launcher：`logs/launcher/2026-08-19/launcher.log`。
- Launcher於`2026-08-19 21:00:20 +08:00`由`C:\project\Open Market Intelligence\scripts\omi-launcher.ps1`啟動。
- Backend wrapper PID 69668；listener PID 66124；command line為repo `.venv`執行`uvicorn app.main:app --host 127.0.0.1 --port 8400`。
- Frontend wrapper PID 26684；listener PID 55704；port 3000。
- `/api/system/health`回200並指向正確project root/backend dir/python runtime。
- Live `/api/ai/tools`與repo-local catalog的canonical JSON SHA-256同為`ebe6233ae0b3023a358e6976fc6bff4485879e74fa8e1ef0d132bb1438e2eb66`。
- Foundation target files的last-write time均早於backend listener start time `2026-08-19 21:00:24 +08:00`。

這些證據可確認launcher owner、selected ports、process/source directory與public catalog高度一致；但目前不能回答：

- Effective `CANONICAL_MARKET_DATA_MODE`是否可由running process證明。
- Off是否完全不執行canonical seam。
- Shadow/compare是否保持external call/subscription/DB write為0。
- 真實preopen/opening/regular payload語意。
- Compare mismatch taxonomy與rollback。

因此目前仍不得標記`runtime-accepted`。

## 與 current truth 的對齊

- 符合Strangler Pattern：1.1只驗證地基，不做consumer cutover。
- 符合Roadmap：完整official Trading Status acquisition與production eligibility owner不在1.1。
- 符合Quality Bar：unknown/missing不轉0，stale/partial/not-applicable保持可見。
- 符合Operating Model：Provider只產Observation，Resolver/Control Plane擁有selection，consumer不重算。

## 本輪未執行

- 未修改backend source或tests。
- 未切換canonical mode。
- 未停止或重啟runtime。
- 未觸發KGI login、subscription、provider refresh、repair job或DB write。
- 未執行commit、push、PR或release。
