# OMI External Adapter AGENTS.md

本檔適用於 repo MCP 與其他 external adapters。Public business truth 屬於 OMI backend；adapter 必須保持 thin。

Adapter 可以：

- 驗證 transport 與 caller input。
- 翻譯 schema、轉送 request、保留必要 compatibility envelope。
- 呈現 backend warnings、missing、freshness、lineage 與 business errors。

Adapter 不得：

- 直接讀寫 OMI DB 或呼叫 market provider。
- 自行推導 freshness、market session、trading status、provider selection 或 fallback。
- 實作 capability、repair planning、portfolio valuation 或市場決策。
- 在 backend 缺資料時自行補零、抓另一來源或製造摘要取代 canonical contract。

修改 public contract adapter 前，先讀 `docs/architecture/OmiDecisionContract.md` 與 backend runtime schema；以 live schema／backend contract 為準，不保存容易過期的 capability inventory。完成前驗證 schema compatibility、成功與 business-error call，並分開回報 source、runtime 與 consumer evidence。
