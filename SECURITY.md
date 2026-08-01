# Security Policy

## 支援版本

目前只對最新的 OMI 4.x release 與 `main` 提供安全修正。早期 1.x package 僅保留歷史用途，不再主動維護。

## 私下回報漏洞

請使用 GitHub repository 的 **Security → Report a vulnerability** 建立 private vulnerability report：

https://github.com/lulu930128/open-market-intelligence/security/advisories/new

請勿在公開 issue 貼出 exploit、token、私人市場資料、完整 `.env`、資料庫或能識別本機環境的 log。回報內容建議包含：

- 受影響版本或 commit。
- 風險與可能影響。
- 最小重現步驟或 proof of concept。
- 建議修正與已知 workaround。

## 安全邊界

OMI 是本機研究工作台，不是自動交易系統。安全修正不得繞過 backend trust boundary、直接讓 frontend／MCP 寫入資料庫，或隱藏 provider failure 與資料缺口。
