# 韓股後端 v1 任務規格

## Goals

- 建立韓股作為 OMI 台股研究的外部 context layer，不改變台股核心定位。
- 先完成 backend data foundation：資料模型、migration、parser/provider boundary、service、API routes、source health、watchlist refresh job。
- 韓股資料缺口、stale、partial、provider failure 必須可見，不得用 placeholder 或假資料包裝成已完成。
- 外部 refresh 必須 bounded：以單檔、watchlist 或明確 resource 為單位，不做預設全市場大量回補。

## Non-goals

- 不做 frontend 韓股 UI。
- 不做自動交易、下單或交易建議。
- 不把韓股提升成與台股同等核心市場；它是跨市場輔助資訊。
- 不在 GET/read path 觸發昂貴外部抓取或大量 DB 寫入。

## Hard Constraints

- official-first：KRX/OpenDART 的模型與 parser contract 先就位。
- fallback-visible：若使用 Yahoo per-symbol chart 作為價格 fallback，provider 必須明確寫入與回傳。
- OpenDART API key 缺失時 fundamentals refresh 要回傳 skipped/partial 訊息，不得失敗成不明錯誤。
- migration 必須 additive，不能重建或覆蓋既有 SQLite data。
- routes 要盡量對齊 JP market API 節奏，保留後續 frontend 共用 pattern 的空間。

## Deliverables

- `backend/app/kr_market/` module。
- `backend/app/routers/kr_market.py` and `/api/kr-market` router registration。
- `kr_*` DB tables and Alembic migration。
- KR scheduler/job type/refresh execution settings integration。
- Mocked backend tests covering parser, DB upsert, source health, watchlist job behavior, route registration。

## Done Criteria

- Targeted backend tests pass without live network。
- `compileall backend/app` passes。
- Source health can report empty/stale/current provider state for `market="kr"`。
- README/env notes state 韓股 v1 limitations and provider keys.
