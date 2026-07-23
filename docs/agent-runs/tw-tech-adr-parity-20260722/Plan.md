# Plan

## Milestones

1. 建立後端 ADR parity contract
   - Scope: ADR registry、cache readers、公式、交易日對齊、nested schema、bounded US refresh。
   - Acceptance: 四組 mapping 正確；完整、缺值、stale 都有可預測 response。
   - Validation: `python -m pytest tests/test_adr_parity.py tests/test_overnight_impact.py -q`

2. 擴充右側 OVERNIGHT 報告
   - Scope: TypeScript type、compact parity strip、zh-TW/en-US/ja-JP 文案。
   - Acceptance: 顯示公式要素與高於/低於參考價文字，窄版不溢出，資料不足可降級。
   - Validation: `npm run lint -- src/components/stock-detail/OvernightDataViews.tsx src/types/market.ts src/i18n/messages/zh-TW.ts src/i18n/messages/en-US.ts src/i18n/messages/ja-JP.ts`

3. 契約與 UI 回歸驗證
   - Scope: Pydantic route contract、focused Playwright mock/assertion、frontend production build。
   - Acceptance: 新欄位向後相容，右側報告能在代表性個股資料下呈現。
   - Validation: `npm run build` 與 focused Playwright test。

## Stop-and-fix rules

- 若 formula、ADR ratio 或日期對齊測試失敗，先修正再進入 UI。
- 若 schema 需要 migration、GET 必須新增無界外部 refresh，或既有 overnight 分數遭到非預期改寫，暫停並更新本文件。
- 若 frontend build 或 focused UI assertion 失敗，先定位本次變更，不用無關 worktree 變更掩蓋失敗。

## Decisions

- 2026-07-22：只收錄同公司直接 ADR，排除產業 proxy。
- 2026-07-22：canonical FX 固定為 `USD-TWD`（一美元兌台幣），不在前端反推方向。
- 2026-07-22：ADR parity 作為既有 overnight response 的 optional nested object，避免右側報告多一次請求與 layout shift。
- 2026-07-22：保留現有隔夜加權分數；直接 ADR 用於 parity 與 refresh，不偷改原有因子權重。
