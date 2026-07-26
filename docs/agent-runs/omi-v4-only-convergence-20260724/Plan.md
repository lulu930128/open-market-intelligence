# 計畫

## Milestone 1：公開契約邊界

- 新增 v4-only public request model。
- HTTP/SSE router 改用 public request model。
- HTTP success response schema 收斂為 `AiDecisionEnvelopeV4`。
- 驗收：OpenAPI request/response schema 不再公開 v2/v3。

## Milestone 2：MCP 與工具目錄

- backend tool catalog 的 contract enum 只保留 v4。
- MCP fallback schema 只保留 v4。
- MCP payload builder 拒絕非 v4 contract。
- 驗收：動態與 fallback `tools/list` 都只宣告 v4。

## Milestone 3：v4 語意與文件

- 公開 envelope 的 compatibility metadata 改為 v4-only 語意。
- 更新 README、ExternalInterfaces、OmiDecisionContract 與 MCP README。
- 產出可做到/條件式可做到/不能做到的純文字設計表。
- 驗收：repo 搜尋不再出現「公開接受 v2/v3」的現行說明。

## Milestone 4：驗證

- Python compile 與 targeted tests。
- backend safe validation。
- frontend lint/typecheck。
- 重啟正確 checkout runtime 後驗證 HTTP、SSE、MCP 與舊版拒絕。
- stop-and-fix：任何 contract、freshness、payload budget 或 consumer regression
  失敗都先修正，不帶著失敗交付。
