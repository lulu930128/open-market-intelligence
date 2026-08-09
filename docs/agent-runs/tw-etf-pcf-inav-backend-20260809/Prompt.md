# 台股 ETF PCF 與盤中 iNAV Backend

## Goal

- 在既有 ETF foundation 上新增正式 PCF／成分曝險與盤中估計淨值能力。
- 維持 GET cache-only，只有明示 POST refresh 才接觸外部 provider。
- 讓 PCF、真正持股與盤中 iNAV 保持不同語意，並讓 source timestamp、session、stale、missing 與 provider failure 可見。

## Non-goals

- 本階段不修改 frontend、AI decision contract、MCP public snapshot 或 Kuro-facing payload。
- 不宣稱 PCF 等於基金完整持股；`holdings` capability 保持 `false`。
- 不建立全市場或背景常駐 iNAV collector；自動 15 秒刷新由後續 frontend／runtime owner 明確設計。
- 不以 `verify=False`、HTML scraping 或任意使用者 URL 繞過 provider TLS／信任邊界。

## Capability contract

| 項目 | 契約 |
|---|---|
| Product scope | 台股核心市場 ETF 研究工作面；提供申購籃子、曝險與折溢價 evidence，不涉及自動交易。 |
| Target | 第一版限定 TWSE 且元大投信 ETF；stock id canonical uppercase。0050 是 acceptance target。 |
| Provider | 元大官方 `ETFAPI PCF/Daily` 與官方 iNAV SignalR `compareHub/RetrieveCompare`；公開免 key，rate limit 未文件化，不 retry。 |
| TLS | 來源 CA 缺少 OpenSSL strict mode 要求的 SKI；僅 issuer-specific session 清除 `VERIFY_X509_STRICT`，仍保留 CA chain 與 hostname 驗證，不使用 `verify=False`。 |
| Resource | PCF effective/reference date、申購單位與 stock/future/ETF/bond exposure；iNAV、來源價格、折溢價與 source observation time。 |
| Freshness | Asia/Taipei；iNAV live <=90 秒為 current、<=15 分鐘為 delayed，非交易時段為 closed；PCF 依生效交易日判定。 |
| Request bounds | PCF 1 request；iNAV SignalR one-shot 5 requests；完整 refresh 最大 8 requests；每 request timeout 10 或 20 秒；不 retry。 |
| Persistence | PCF snapshot `(stock_id,effective_date)`、component `(snapshot_id,order_index)`、iNAV `(stock_id,observed_at)` unique upsert；iNAV 每檔保留最近 1,200 筆。 |
| Failure | Unsupported issuer、empty、schema drift、TLS/HTTP、partial refresh 分開回報；既有成功 cache 不清空，缺值不轉成 0。 |
| Transaction | Provider 純 IO/parser；service 擁有 upsert、component replacement、retention、commit/rollback；provider event 在 market data commit 後 best-effort 記錄。 |
| Public API | 延伸既有 `GET /api/market/etfs/{stock_id}/overview` 與 `POST /api/market/etfs/{stock_id}/refresh`；新增 request flags 預設 `false`，保持舊 consumer 行為。 |
| AI/consumer | 本階段不投影 AI/MCP；backend response 新增 `pcf`、`intraday_nav`、capabilities、source 與 freshness，供後續 frontend 消費。 |

## Done criteria

- 0050 provider live smoke 能解析官方 PCF 與 iNAV，且不關閉 TLS 驗證。
- Cache refresh idempotent，PCF component 不因重跑重複；iNAV source time 與折溢價可驗證。
- 非交易時段 iNAV 顯示 `closed`，不假稱 current；真正 holdings 仍不假稱已接入。
- Migration、provider parser、SignalR request bound、service 與 public response schema 有 targeted tests。
