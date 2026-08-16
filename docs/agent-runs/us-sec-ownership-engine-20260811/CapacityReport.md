# 13F Stage 7 Capacity and Mapping Report

## 結論

13F 的 CUSIP-native 全市場 warehouse 技術上可串流處理，但目前不能直接進入 production schema／全歷史回補：既定的 20 GiB storage gate 與 CUSIP→symbol mapping gate 都未通過，符合 `Prompt.md` 的 major-decision stop condition。

## 實測範圍

- SEC 官方完整資料集：`2026Q1`（2026 March–May release window）與 `2025Q4`（2025 December–2026 February release window）。
- SEC 官方 2026Q2 Section 13(f) Securities List TXT。
- 只寫 `data/cache/us_sec/ownership/capacity/two-quarter-pilot.sqlite`，未寫 production projection 或 `open_market_intelligence.db`。
- ZIP 全程保留壓縮檔，使用串流 TSV parser；沒有整季解壓 staging。

## 容量證據

| 指標 | 實測 |
|---|---:|
| 兩季壓縮 ZIP | 189,675,924 bytes |
| 兩季 ZIP 內未壓縮內容 | 766,711,315 bytes |
| INFOTABLE rows | 7,296,094 |
| Pilot SQLite（建索引前） | 722,616,320 bytes |
| Pilot SQLite（建索引後） | 1,414,598,656 bytes |
| 索引後 bytes / holding row | 193.88 |
| Python tracemalloc peak | 6,115,517 bytes |
| 完整掃描與建索引時間 | 324.429 秒 |

所有 `VALUE` 列都能以 Decimal 語意解析，`malformed_value_rows=0`。兩季同時包含 `13F-HR`、`13F-HR/A`、`13F-NT`、`13F-NT/A`，因此正式 ingestion 仍須保留 notice 與 amendment，而不能將 filing count 直接當有持倉 manager count。

## 全歷史估算

- SEC 頁面目前列出 53 個 published datasets，官方標示壓縮大小合計約 2.95 GB。
- 以兩季實測的 indexed SQLite / compressed archive amplification 套用全部官方檔案大小，warehouse + 保留來源 ZIP 約 **24.96 GB**。
- 以最近兩個最大資料集線性外推的保守上界約 **41.71 GB**。
- 以上均未包含 staging safety headroom、migration/index rebuild 暫存空間與未來季度成長。
- 既定 budget 是 20 GiB，因此 storage gate 未通過。

## Mapping 證據

- 官方 Section 13(f) list 對兩季 filed CUSIP 的 reference coverage：平均 rows 98.30%、reported value 99.55%。
- 這只能證明「CUSIP 是官方可辨識的 13(f) security」，官方 list 不提供 ticker。
- 現有 `us_stock_master` 沒有 CUSIP/FIGI 欄位；在不允許 issuer-name fuzzy mapping 自動升為 ready 的規則下，production exact CUSIP→symbol coverage 是 0%。
- 既定 gate 是 rows 90% / value 95%，因此 symbol projection gate 未通過。

## 需要決定的架構方向

1. Storage：將 ownership budget 提高到至少 32 GiB（另保留 staging/free-space headroom），或把 13F holdings 移到 Parquet/DuckDB 類 analytical store，SQLite 只留 metadata/current projection。
2. Mapping：採可版本化、可稽核的 identifier provider／資料集（CUSIP 或 FIGI→ticker/issuer CIK），或接受首版只有 CUSIP/manager 查詢，symbol「機構」頁保持 `partial/blocked`。

在這兩項決策完成前，Stage 8 不建立 production 13F tables，避免先把 730 萬列 pilot 形狀鎖進一個已知會超 budget、又無法服務 symbol UI 的 schema。
