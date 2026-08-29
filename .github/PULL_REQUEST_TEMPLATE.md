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

## Architecture Impact / 架構影響

- Touched layers：
- Invariants affected：
- Architecture debt added／removed：
- Architecture guard result（actual／declared）：
- Compatibility seam 與 sunset：
- Migration／legacy removal：

## Notes / 備註

- 記錄限制、後續工作與 migration／部署注意事項。

### Checklist

- [ ] 沒有提交 `.env*`、token、私人資料庫、logs、cache 或 generated artifacts。
- [ ] 沒有隱藏 stale、partial、missing 或 provider failure。
- [ ] 若修改 public contract，已同步檢查 backend、frontend、MCP 與外部 consumer。
- [ ] Provider selection、fallback、freshness 與 repair 仍由 backend Resolution／Control Plane 擁有。
- [ ] GET／read path 沒有新增 provider fetch、refresh、repair 或其他 side effect。
- [ ] Transaction owner 明確，沒有新增未宣告 architecture debt。
- [ ] Compatibility seam 有 owner、scope、sunset 與 removal test；完成 migration 時舊 production path 已不可達。
- [ ] 若 architecture guard 已存在，已通過且 debt manifest 沒有默默擴張。
- [ ] Architecture violation 與 debt manifest 維持 exact equality；不存在 stale debt path／occurrence。
- [ ] 驗證結果與未驗證範圍已如實記錄。
