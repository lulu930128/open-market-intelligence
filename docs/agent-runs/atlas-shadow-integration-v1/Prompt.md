# Atlas Shadow Integration v1

## 背景

Open Intel Atlas 已提供 `GET /api/v1/brief?profile=evidence_pack_v1` 的本機唯讀 consumer contract。OMI 需要在不轉移市場資料、freshness 與決策語義所有權的前提下，取得 Atlas 已清洗、去重並帶來源歸因的外部事件情報，供桌寵、MCP 與其他 OMI consumer 經由既有 `omi.decision.v4` 契約使用。

## 目標

- OMI 後端以 loopback REST 唯讀 Atlas，不直接讀取 Atlas SQLite，也不觸發 Atlas provider refresh。
- 新增 optional `news.events` capability，投影至 `omi.decision.v4` evidence。
- Atlas unavailable、契約不相容或空結果時，保持 OMI 核心行情與決策品質不變。
- 對事件、evidence 與字串做有界裁切，不讓全文或未受控 payload 進入 OMI。
- 保留 Atlas 對 event identity、attribution、deduplication、coverage 與 freshness 的所有權。

## 非目標

- 不把 Atlas 情報納入 OMI decision score、方向、價位或 recommendation。
- 不開放 Atlas 公網、tunnel 或新的對外端點。
- 不在 OMI request path 觸發外部新聞供應商抓取。
- 不修改 Atlas 資料庫、排程器、provider 設定或 retention policy。
- 不在本里程碑切換 production runtime 或重啟任何元件。

## 硬限制

- `OMI_ATLAS_SHADOW_ENABLED` 預設為 `false`。
- `OMI_ATLAS_API_BASE_URL` 只接受明確帶 port 的 loopback HTTP URL。
- Atlas 契約版本必須是 `1.1`，profile 必須是 `evidence_pack_v1`；不相容時 fail closed。
- `decision_usable` 永遠為 `false`，空結果語義為 `unknown_not_observed`。
- 明確 capability selection 不得被自動規劃覆蓋；Atlas 只能以 optional capability 自動加入。
- 不把 Atlas failure 加入 OMI core `missing` 或 `warnings`。

## 交付物

- Atlas shadow context client 與欄位裁切器。
- `news.events` capability、resolution 與 provider contract 接線。
- `omi.ask` optional auto-selection 與 result attachment。
- `.env.example` 設定說明。
- success、empty、timeout、contract mismatch、SSRF boundary、selection ownership 與品質隔離測試。

## 完成條件

- Targeted tests 全數通過。
- Capability registry 能列出 `news.events`，並維持 cache-only/read-only 語義。
- 模擬 Atlas success 時，v4 projection 含有 bounded `news.events` evidence。
- 模擬 Atlas failure 時，OMI core missing/warnings 不變。
- 未啟用 feature flag 時不發出 HTTP request。
