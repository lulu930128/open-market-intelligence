# 新版完成矩陣

狀態定義：

- `runtime 完成`：source、regression、正式 launcher HTTP／MCP／consumer smoke 已通過。
- `待實盤`：可離線驗證部分已完成，仍需指定交易時段自然資料。
- `provider 限制`：契約已誠實表達，但來源不足，不能標 full。

| 項目 | Backend owner | 目前狀態 | 完成證據 |
| --- | --- | --- | --- |
| P0-1 TAIEX close handoff | Taiwan index projection／index replay | 待實盤 | resolution regression、正式 close contract；待下一交易日 13:24～13:34 capture |
| P0-2 TW／JP／KR post-close freshness | realtime contract／calendars | runtime 完成 | completed-session regression、正式 JP／KR cache-only calls |
| P0-3 required unsupported readiness | capability／quality／v4 envelope | runtime 完成 | required／optional negative tests、正式 breadth blocked call |
| P0-4 `tw_index` data.freshness | projection／v4 freshness | runtime 完成 | non-empty freshness、正式 TAIEX v4 call |
| P0-5 cache-only replay | market readers／persisted intraday | runtime 完成 | no-refresh regression、launcher restart 後 TW／JP／KR persisted hit |
| P1-1 metadata／quality E2E | quality／v4 budget projection | runtime 完成 | compact／standard／full regression、正式 TAIEX metadata |
| P1-2 JP／KR 1m→5m | regional service／projection | runtime 完成 | session-aware OHLCV regression、67／73 根 runtime calls |
| P1-3 top-5 depth projection | Taiwan projection／capability fields | runtime 完成 | compact／standard／full regression |
| P1-4 ranking field names | ranking service／schema | runtime 完成 | additive semantics regression、正式 group 3 scope／coverage |
| P1-5 source-health relevance | decision envelope | runtime 完成 | target + selected resource regression |
| P1-6 index volume／value／VWAP | index market／projection | runtime 完成 | unit／status／semantics regression、正式 TAIEX contract |
| P1-7 fixed slots + index replay | scheduler／snapshot repository | 待實盤 | 13:32／13:34、TAIEX／TPEX repository／route 完成；今日 captured 0 |
| P2-1 JP／KR breadth coverage | regional breadth contracts | provider 限制 | partial／coverage／reconciliation negative contract |
| P2-2 auction unmatched | quote-depth provider contract | runtime 完成 | `null + not_provided` regression |
| P2-3 depth order count | quote-depth provider contract | runtime 完成 | `null + not_provided` regression |

## 最終整合證據

- Regression：safe backend profile，pytest `1125 passed`。
- Runtime：launcher PID `6524`，backend `8400`，frontend `3000`，DB `20260727_0040 (head)`。
- MCP：initialize、session、tools/list、成功與 `TARGET_NOT_FOUND` business-error 均通過。
- Browser：dashboard DOM 可見，console 0 error。
- 待實盤：下一交易日 08:30、09:05、11:00、13:24、13:28、13:30、13:32、13:34。
