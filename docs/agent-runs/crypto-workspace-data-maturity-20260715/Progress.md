# Crypto 工作區資料成熟度進度

## 目前狀態

- 已完成：Crypto 資產庫、成熟度 contract、台股式 bounded 自動更新體驗與手動控制移除均已完成並通過 live 驗證。

## 已確認

- Backend registry 有 9 個資產；預設 watchlist 排除 USDT，因此側欄顯示 8。
- Provider contract 已涵蓋 BitoPro、Binance、OKX、CoinGecko、CoinGlass、OMI local 與 pending Bybit。
- 本機 DB 已有 ticker 18、order book 18、OHLCV 145368、derivatives 15、market cap 9、spread 4、long/short 2847 筆；liquidation、heatmap、CVD 目前為 0。
- Live workspace summary 為 registry 9、watchlist 8、ready 1、stale 8；BTC 是 always-on，其餘 8 個 registry 資產是 on-select。
- Realtime service 與 auto-refresh service 均為 running。

## 決策

- 新增 additive、read-only 的資產層級 workspace summary，不改既有 provider-contract 與 source-health route。
- Backend 負責 slot applicability、freshness 與 maturity；frontend 只呈現。
- 核心資料與進階資料分開評級，event-driven 空資料不視為 provider failure。
- 保留既有訂閱策略，不把所有資產改成 always-on，避免無邊界 provider 壓力與 DB 寫入。
- 修正 CoinGecko identity 使用 registry coin id，並把不適用的台灣價差、long/short、liquidation、CVD 明確標為 not applicable 或 provider pending。
- 管理表單改成獨立捲動區，避免把 Crypto 清單壓縮到不可見，沒有改動既有側欄資訊架構。
- 商品／貨幣沿用 backend subscription policy、on-select refresh、stale repair 與 quote polling，不新增第二套刷新邏輯。
- Resource `manual` policy 在 backend 解析時升級為 `on_select`；Crypto 的 always-on / on-select 分層保持不變。

## 交付內容

- `GET /api/crypto-market/workspace-summary`：回傳資產庫、watchlist、runtime、subscription 與每資產 slot maturity。
- Sidebar 顯示 `8 / 9`、資產庫摘要，以及每個幣種的即時、部分、待更或缺資料狀態。
- TON / GRAM market-cap identity、slot applicability 與 OHLCV 薄覆蓋判定已有 regression tests。
- Crypto 側欄、Crypto K 線與商品／貨幣 K 線均不再顯示手動 Reload／重載／刷新核心資料／更新報價按鈕。
- 所有貨幣與非核心商品在 live subscription contract 中均為 `on_select`；BTC 與黃金保留既有 `always_on`。

## 驗證證據

- Backend compileall：通過。
- Backend targeted regression：`55 passed`。
- Frontend ESLint：通過。
- Frontend TypeScript：通過。
- Next.js production build：通過。
- Crypto / resource Playwright smoke：`1 passed`。
- Live backend 與 frontend proxy 均回傳 registry 9、watchlist 8、ready 1、stale 8。
- In-app Browser 實際確認 BTC／ETH 成熟度可見、清單可捲動，console error 為 0。
- 本輪 backend subscription／resource／crypto targeted regression：`71 passed`。
- 本輪 resource auto-refresh Playwright smoke：`1 passed`，並驗證選取貨幣會發出自動 refresh request、手動更新控制不存在。
- Live API 確認 9 個貨幣皆為 `on_select`；In-app Browser 選取 `TWD-USD` 後顯示 `on select` 與約 1 秒 freshness，四種手動更新控制均不存在。

## 已知限制

- Liquidation event、liquidation heatmap 與 CVD 目前尚無持久化列；contract 會明確回傳 event quiet、provider pending 或 missing，不以假資料補齊。
- 非 BTC 資產維持 on-select，因此未被選取或自動刷新輪到前可能顯示 stale；這是目前 bounded refresh policy 的預期行為。
