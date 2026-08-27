# 台股 Freeze Gate Debt Register

| ID | Debt | Class | Current containment | Closure gate |
|---|---|---|---|---|
| D-01 | 新source尚未由named launcher runtime adopt | Runtime | source與runtime狀態分離 | `ADOPT-01` |
| D-02 | KGI合法盤中session acceptance未完成 | Live | 所有live項目保持`PENDING` | `LIVE-01`～`LIVE-04` |
| D-03 | index list/contribution/legacy OHLC explicit acquisition physical code仍在`indices.py` | Physical boundary | GET已zero IO；只有explicit command可達 | 後續provider extraction |
| D-04 | EOD coverage shared module仍持有transaction debt | P2 physical closure | exact allowlist，不擴張 | `EOD-02` deferred |
| D-05 | US/JP/KR valuation為market-owned compatibility reader | Cross-market lineage | outward limitation=`REGIONAL_DAILY_LINEAGE_NOT_YET_SHARED_CORE` | regional Shared Core work |
| D-06 | disposition / holding ratio沒有canonical raw receipt | Sidecar lineage | `COMPATIBILITY_CACHE`、decision false | typed persistence migration |
| D-07 | chips/fundamentals/company profile仍為compatibility | Long tail | Catalog truthful status | long-tail migration sequence |
| D-08 | corporate events、ETF、futures/derivatives仍有lineage gap | Long tail | Catalog truthful status + GET boundary | per-capability migration |
| D-09 | minute/stock intraday state component raw IDs不完整 | Derived lineage | `COMPATIBILITY_DERIVED` | derived lineage migration |
| D-10 | 既有pytest temp directories權限拒絕 | Local environment | 不刪除、不修改；validation使用可讀test paths | user/local cleanup decision |

## Non-debt constraints

- Stream presentation-only是刻意的雙軌contract，不是第二條research truth。
- Runtime/live pending不是source failure，也不能被source pass消除。
- Long-tail compatibility不是platform-owned；文件與outward contract不得升級措辭。

## Debt admission rule

新outward台股surface必須先進TW Dataset Catalog，或進
`tw_sidecar_classification.py`的explicit exemption。CP0 allowlist必須與source實際
debt exact match；不存在的舊import不得保留以免未來回歸被放過。
