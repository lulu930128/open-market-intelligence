# Support

## 使用與問題回報

一般啟動、設定、資料 freshness、圖表或市場研究流程問題，請先確認：

1. Tray menu 顯示的實際 Dashboard 與 API Health URL；偏好 port `3000`／`8400` 不保證一定可用。
2. `logs/launcher/<date>/launcher.log` 的 `selected=` 與 service ready 記錄。
3. 資料日期、交易 session、source health、provider warning，以及資料是否 stale／partial／missing。
4. 使用最新 OMI 4.x release 或 `main`。

若仍可重現，請使用 GitHub bug report template，附上經遮蔽的證據。請勿上傳 `.env`、token、私人 watchlist、完整 SQLite database 或其他個人投資資料。

## 安全問題

安全漏洞請依 [SECURITY.md](SECURITY.md) 私下回報，不要建立公開 issue。

## 投資聲明

OMI 提供研究與條件化決策輔助，不提供保證績效，也不替使用者執行交易。市場資料可能延遲、不完整或受 provider 限制，使用者必須自行核對來源與風險。
