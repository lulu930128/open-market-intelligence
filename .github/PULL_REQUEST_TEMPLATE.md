## Summary / 摘要

- 說明這次變更解決的問題與使用者可見結果。

## Changed Files / 變更檔案

- 列出主要修改區域與重要 contract。

## Verification / 驗證

- 列出實際執行的測試、lint、typecheck、build 或 smoke check。
- 若未執行，請說明原因。

## Risks / 風險

- 說明行為、相容性、資料、freshness、schema 或 UI 風險。
- 若沒有已知重大風險，請填寫 `No known major risks.`。

## Notes / 備註

- 記錄限制、後續工作與 migration／部署注意事項。

### Checklist

- [ ] 沒有提交 `.env*`、token、私人資料庫、logs、cache 或 generated artifacts。
- [ ] 沒有隱藏 stale、partial、missing 或 provider failure。
- [ ] 若修改 public contract，已同步檢查 backend、frontend、MCP 與外部 consumer。
- [ ] 驗證結果與未驗證範圍已如實記錄。
