# ETF Provider Coverage

Snapshot date: 2026-08-09
Issuer source: [SITCA ETF 專區](https://www.sitca.org.tw/ROC/SITCA_ETF/etf_info.aspx)

## Resource semantics

- `PCF`：申購買回摘要或籃子；是否包含 component exposure 由 provider resource 個別宣告。
- `component exposure`：只在官方來源真的提供申購籃子成分時啟用；不得把基金總持倉冒充成 PCF basket。
- `iNAV`：必須保留來源時間，由 service 依交易日與 session 判定 current／delayed／stale／closed。
- `not_connected`：issuer 已辨識，但尚無可驗證的 adapter；profile 與盤後 NAV 不受影響。

## Shared daily NAV source

- MOPS `t78sb35` 是免費官方來源，但回傳 HTML 會把同一投信後續基金代碼放在 malformed、沒有 `<tr>` 包覆的 `<td>` 中。
- Parser 必須依文件順序將每個基金代碼配對到下一個有日期的基金資料列，不能假設每個代碼都位於合法 table row。
- 2026-08-07 bounded smoke：單一 request 解析 61 筆 ETF NAV；修正前只得到每家投信第一筆附近的 19 筆。
- MOPS 這個報表本身仍不是完整 ETF universe；主動式與部分海外型 ETF 缺口必須維持 missing，後續由 issuer adapter 或其他可驗證官方來源補齊。

## Current adapters

| SITCA code | Issuer | PCF | Component exposure | iNAV | Provider | Notes |
|---|---|---:|---:|---:|---|---|
| A0005 | 元大投信 | connected | connected | connected | `yuanta_etfs` | PCF 1 request；SignalR iNAV 5 requests。 |
| A0009 | 統一投信 | connected | not connected | not connected | `upamc_etfs` | 官方 PCF page + JSON 共 2 requests；`asset` 是基金持有曝險，不冒充申贖籃子。 |
| A0010 | 富邦投信 | connected | not connected | connected | `fubon_etfs` | PCF summary 1 request；iNAV 1 request；Fund Asset 是整體持倉，不冒充 PCF basket。 |
| A0016 | 群益投信 | not connected | not connected | connected | `capital_etfs` | 官方全 ETF iNAV API 1 request；依證券代號做 exact match。 |
| A0022 | 復華投信 | not connected | not connected | connected | `fuh_hwa_etfs` | 官方 ETF 頁面 1 request；只解析 `data-type=etfnet` 卡片。 |
| A0032 | 野村投信 | not connected | not connected | connected | `nomura_etfs` | 官方 ETF API 1 request；TLS 仍驗證，只放寬舊憑證缺少 SKI 的 strict flag。 |
| A0037 | 國泰投信 | not connected | not connected | connected | `cathay_etfs` | 先以證券代號解析內部 fund code，再取得 iNAV，共 2 requests。 |

## Recognized issuers without adapters

| SITCA code | Issuer | State |
|---|---|---|
| A0001 | 兆豐投信 | `provider_not_connected` |
| A0003 | 第一金投信 | `provider_not_connected` |
| A0008 | 玉山投信 | `provider_not_connected` |
| A0011 | 摩根投信 | `provider_not_connected` |
| A0012 | 華南永昌投信 | `provider_not_connected` |
| A0018 | 聯博投信 | `provider_not_connected` |
| A0025 | 永豐投信 | `provider_not_connected` |
| A0026 | 中國信託投信 | `provider_not_connected` |
| A0031 | 貝萊德投信 | `provider_not_connected` |
| A0033 | 聯邦投信 | `provider_not_connected` |
| A0036 | 安聯投信 | `provider_not_connected` |
| A0041 | 凱基投信 | `provider_not_connected` |
| A0045 | 富蘭克林華美投信 | `provider_not_connected` |
| A0047 | 台新投信 | `provider_not_connected` |
| A0049 | 大華銀投信 | `provider_not_connected` |

## Market coverage

- TWSE：profile、盤後 NAV 與 issuer resolution 已建立；PCF/iNAV 依上表逐步接入。
- TPEx：尚未接入本 contract；不得將 TWSE provider coverage 套用到 TPEx。
