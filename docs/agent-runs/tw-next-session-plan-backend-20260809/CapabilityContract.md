# Capability Contract

| 項目 | v1 決策 |
| --- | --- |
| Product scope | 台股個股盤後／盤前技術位階推演；是條件式研究輔助，不是隔日價格預測或自動交易。 |
| Target | 單一 `stock_id`；完整適用於 TWSE／TPEX `instrument_type=stock`。缺主檔或 unknown 顯示 partial，明確非股票顯示 not-applicable。 |
| Provider | 無外部 provider call；只讀本機既有 `market_daily_price` 與 `stock_master`。 |
| Resource | raw/unadjusted completed daily OHLC。價格單位 TWD；日期為 Taiwan trade date。 |
| Freshness | Asia/Taipei；以 `expected_daily_price_date()`、daily price 15:15 release policy 與最新日 K 日期比較。 |
| Request bounds | 每次一檔；最多讀取 250 筆本機日 K；無 timeout/retry/provider quota。 |
| Persistence | 無新增 table、cache、upsert 或 migration；純 read/derive。 |
| Failure | `missing`、`partial`、`stale`、`pending`、`not_applicable` 與 reason codes/warnings/limitations 顯式輸出。 |
| Transaction | Service 不 commit/rollback；router 只 dispatch 與 HTTP error mapping。 |
| Public API | `GET /api/market/technical/{stock_id}/next-session-plan`；additive route；Pydantic response model。 |
| AI contract | 本階段不接；未來由 AI layer 明確投影同一 service contract。 |
| Consumer | 本階段不接 frontend/MCP/Kuro；不得在 consumer 重算公式或 freshness。 |
| Validation | Pure formula、history normalization、readiness/lifecycle、schema/OpenAPI 與 targeted backend regression。 |

## Formula

對週期 `N`，令 `S` 為最新 `N-1` 個已完成收盤價總和，目標交易日 hypothetical close 為 `x`：

```text
projected_ma_n(x) = (S + x) / N
transition_price_n = S / (N - 1)
```

因此：

```text
x >= projected_ma_n(x)  <=>  x >= transition_price_n
```

`transition_price_n` 是條件轉換價，不是隔日成交價預測。

## Readiness precedence

1. 明確非股票：`not_applicable`。
2. 無有效日 K／不足 MA20：`missing`。
3. 收盤後等待最新正式日 K：`pending`。
4. 最新日 K 落後 expected date：`stale`。
5. 僅部分 level 可用或主檔 metadata 不完整：`partial`。
6. 日期、instrument 與完整 level 均符合：`ready`。

## v1 limitations

- 使用 raw/unadjusted close；未套用 corporate-action adjustment。
- MA 支撐／壓力角色是以 as-of close 相對 transition price 的條件分類，不保證市場反應。
- 不含 ATR、tick buffer、量價確認、盤中假突破或回測勝率。
