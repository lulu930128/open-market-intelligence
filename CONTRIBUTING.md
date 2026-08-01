# Contributing to Open Market Intelligence

感謝你願意改善 OMI。這個專案優先維持台股核心、本機優先、evidence-driven 與資料限制可見；它不是自動交易或保證績效的工具。

## 開始之前

1. 先搜尋現有 issue，確認問題尚未被回報。
2. 非平凡功能請先建立 issue，說明使用情境、資料來源、freshness、失敗語意與驗證方式。
3. 不要提交 `.env*`、token、私人 watchlist、SQLite 資料庫、logs、cache、下載資料或 generated build artifacts。
4. 市場邏輯、freshness 與 AI decision contract 應留在 backend；frontend、MCP 與其他 consumer 只呈現或消費 backend contract。

## 本機設定

主要開發環境是 Windows PowerShell。請依 [README.md](README.md) 完成 backend 與 frontend 設定，並從 repository root 執行安全驗證：

```powershell
.\scripts\run-safe-validation.ps1 -Profile quick
```

依修改範圍選擇更精準的檢查：

```powershell
.\scripts\run-safe-validation.ps1 -Profile backend
.\scripts\run-safe-validation.ps1 -Profile frontend
```

只有需要真實 browser/runtime 證據時才執行 E2E 或啟動長駐服務。

## Pull request

- 維持小而明確的 diff，不做無關 dependency upgrade 或格式化。
- 使用 Conventional Commits，例如 `feat:`, `fix:`, `docs:`, `test:`, `chore:`。
- PR 必須說明變更、主要檔案、實際驗證、風險與未完成事項。
- 資料問題要保留 stale、partial、missing、provider failure、來源與日期，不得以零值或合成資料掩蓋缺口。
- 若修改 public API、AI answer contract 或市場 schema，請同步檢查 frontend、MCP 與外部 consumer 相容性。

## 貢獻授權

除非你在提交時明確以書面標示其他安排，任何有意提交並納入本專案的貢獻，均依 [Apache License 2.0](LICENSE) 授權，且不附加額外條件。提交前請確認你有權提供相關程式碼、文件與素材；不要提交來源或再授權權利不明的內容。

## 投資與資料責任

提交內容不得暗示保證報酬或自動下單。研究輸出應包含 evidence、進場／失效條件、風險處理、反證與資料限制。
