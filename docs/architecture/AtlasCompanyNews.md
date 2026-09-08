# OLA 個股新聞整合

OMI 以 `app/stocks/atlas_news.py` 唯讀消費 Open Intel Atlas 的
`GET /api/v1/stocks/{exchange}/{symbol}/news`，要求 contract `1.2` 與
`company_news_stock_v1`。StockMaster 的 exact market/symbol 用於定位，
不以公司名稱搜尋、不讀 Atlas DB、不抓第三方來源、不建新聞主資料庫。

## 設定與入口

- `OMI_ATLAS_NEWS_ENABLED=false` 預設關閉，獨立於 Event shadow flag。
- 共用 `OMI_ATLAS_API_BASE_URL` 與 `OMI_ATLAS_TIMEOUT_SECONDS`；只允許明確 port 的 loopback HTTP，停用環境 proxy 與 redirect，限制 response bytes；discovery 模式只在連線失敗且 endpoint 改變時重試一次。
- `GET /api/stocks/{stock_id}/news?limit=20&cursor=...`：limit 1–50。
- `omi.ask` capability：`news.company_documents`，schema `omi.external.company_news.v1`，只支援 Taiwan stock。selection.limits 控制筆數，selection.parameters 的 cursor 用於續頁。
- 在 flag 啟用、stock scope、問題包含新聞/news 且沒有 explicit selection 時，backend 將此 capability 納入 optional planning。明確 include/optional/exclude 優先。

```json
{
  "contract_version": "omi.decision.v4",
  "question": "2330 的個股新聞文件有哪些？",
  "target": {"type": "tw_stock", "id": "2330", "market": "TW"},
  "mode": "data_only",
  "output": "evidence_only",
  "realtime_policy": "cache_only",
  "selection": {
    "include": ["target.identity", "news.company_documents"],
    "limits": {"news.company_documents": 3},
    "max_response_bytes": 262144
  }
}
```

HTTP 呼叫可另設 `allow_llm=false`、`allow_write=false`、`allow_external_fetch=false`。
MCP adapter 的 readonly policy 仍由 server 管理，不允許 query 反向觸發 Atlas collector。
輸出位置為 `evidence.data["news.company_documents"]`。REST、HTTP ask、SSE final、MCP
保留同一組 Document identity、標題、rights、來源連結、coverage 與 freshness。
較小 response budget 仍受既有 v4 projection gate 控制，應檢查 projection 的省略／不足狀態。

## 語意與失敗

`status=available` 只表示有可讀文件；`freshness.status=stale` 可同時成立。
`ready_empty` 表示沒有可回傳文件，必須一起讀 coverage；不是沒有新聞的證明。
`decision_usable=false` 固定維持，Document 不升格 Event、不改 decision score。
這一階段提供結構化 evidence；不新增新聞摘要或交易建議模型。

來源權限不符為 disabled；連線／timeout 為 unavailable；版本、identity、rights 或
metadata 錯誤為 incompatible；不支援市場為 not_supported。錯誤 cursor 回 400。
News failure 不改行情、技術面與原有市場 facts。`news.events` 使用 Atlas `1.2` / `evidence_pack_v1`，未知或舊版契約仍 fail closed。

## 驗證與採用

`scripts/verify-atlas-stock-news-bridge.py` 需要明確 Atlas repo、來源 SQLite 與 OMI SQLite。
它以 readonly SQLite connection 備份 Atlas，只複製指定 StockMaster 列到隔離 OMI DB，
停用採集與 OMI lifespan，以 SQLite query_only 驗證既有 evidence 的 REST/MCP 串接，
並檢查 Atlas 關閉時降級。所有測試服務在結束後關閉，artifact 在 `.tmp/atlas-stock-news/`。

正式採用需讓 OLA 與 OMI runtime 載入本次 source、確認 content usage context、啟用
OMI news flag，再重新取得 MCP schema。隔離測試不代表桌面目前連線中的 MCP 已更新。

## 本機 endpoint discovery

`app/integrations/atlas_endpoint.py` 是新聞與 Event shadow 的共用 endpoint / HTTP owner。
`OMI_ATLAS_ENDPOINT_MODE=static` 預設保留明確 URL（隔離測試與舊版服務可用）；
`discovery` 必須設定 `OMI_ATLAS_ENDPOINT_STATE_PATH` 為 OLA 公告檔的絕對本機路徑。
不掃 port、不讀 OLA DB、不啟動服務、不觸發 provider。

OLA 正式 executable 在 listen 完成後原子發布 `data/runtime/atlas-endpoint.json`；
`GET /api/v1/runtime` 是 loopback-only、無 DB 統計的輕量實例識別。
公告包含 schema/service、installation/instance ID、PID、started_at、base_url。
OMI 驗證公告與 HTTP 實例一致；單看檔案、PID 或 HTTP 200 均不足。
公告是 readiness snapshot，不是 liveness lease：退出不改共享檔，避免舊程序覆蓋新程序。
檔案時間不作到期判斷，崩潰殘留透過 HTTP 身分檢查失效。

成功解析快取預設 5 秒、失敗最多 1 秒；以 lock 合併一般並行解析。
連線失敗可強制重新解析一次，只有 URL 改變才重新讀取；read timeout 不重試。
解析、等待與 HTTP 共用 monotonic deadline，socket 亦設 timeout，回應有大小上限。
檔案損壞或端點失效可回退到設定 URL，但必須通過 runtime identity；有有效公告時，
fallback 的 installation ID 亦須一致。static 模式不要求新 runtime endpoint。
設定 URL 與公告 URL 均限制 loopback HTTP，禁止 UNC discovery、redirect、環境 proxy。

`atlas-port.json` 保留 Tray 選埠偏好用途，與就緒公告分開。
Tray 的 occupied 保護維持不變；reserved 才使用既有 bounded fallback。
內嵌 `createAtlasRuntime` 預設不公告，自訂 DB 的 executable 須明確指定獨立公告路徑。
重啟空窗如實回傳 unavailable；服務重新就緒後自動恢復，不保證每次請求無中斷。

## Company relevance

Yahoo feed scope 是 discovery lineage，不代表文章提到該公司。OLA canonical identity context
提供名稱／唯一別名與 ticker；adapter 只由標題及 RSS 摘要建立內容命中，不能用查詢參數、
tag 或 category 直接建立證據。Ticker 需明確代號語法，不能以裸數字或數字子字串匹配。
唯一的兩字中文公司別名可用，通用詞與不唯一別名排除；缺少 canonical identity 則不產生 hint。

文字匹配輸出 `content_identity_match`，保存 matched_text、field 與 validator provenance；
confidence=0.9 是規則分級，非機率校準，也不代表新聞事實已驗證。Documents 仍不提供決策分數。
`last_success_at` 是採集成功，`last_match_at` 只有 validated target match 才更新。
舊 Yahoo feed-derived hints 透過 bounded remediation 撤回／重解析；原文與 discovery observation 保留。
