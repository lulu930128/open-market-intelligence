# Progress

## Status

- Current phase: done
- Last updated: 2026-07-22 Asia/Taipei

## Completed

- 已確認四組直接科技 ADR 與轉換比的實作範圍。
- 已追蹤既有 overnight route、service、schema、frontend consumer、US 日線與 USD/TWD cache。
- 已定義 capability contract、non-goals、failure 與 freshness 語意。
- 已新增 ADR registry、台幣隱含價 builder、直接 ADR bounded refresh 與 optional API schema。
- 已在右側 `OVERNIGHT` 報告加入可重算公式、台股基準價差與已交易後的剩餘價差。
- 已補齊 TypeScript type、zh-TW/en-US/ja-JP 文案與 focused Playwright fixture。
- 已依實際畫面回饋把 ADR 區塊改為預設收合；收合列只保留 ADR symbol、隱含台幣價與基準價差，公式、日期與剩餘價差點開後才顯示。

## Validation evidence

- `..\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests\test_adr_parity.py tests\test_overnight_impact.py -q`: 15 passed。
- `..\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests\test_api_contract_inventory.py -q`: 9 passed、30 subtests passed。
- `ruff check app\market\adr_parity.py app\market\schemas.py tests\test_adr_parity.py`: all checks passed。
- Targeted frontend ESLint 與 `npx tsc --noEmit`: passed。
- `npm run build`: Next.js production build passed。
- `PLAYWRIGHT_PORT=3000 PLAYWRIGHT_REUSE_EXISTING_SERVER=1 npx playwright test e2e/omi-smoke.spec.ts -g "Taiwan stock overnight report renders ADR TWD parity"`: 1 passed。
- 收合互動 focused Playwright：確認預設無 `open`、細節不可見，點擊 summary 後公式與日期內容可見；1 passed。
- Read-only local DB sample（expected US date `2026-07-21`）：2330/TSM 與 2303/UMC 為 ready；3711/ASX 與 8150/IMOS 因尚無 ADR cache 為 partial，會由選股時的 bounded refresh 補抓。
- Loopback runtime probe：`/api/market/overnight-impact/2303?refresh=false` 已回傳 ready 的 `UMC` parity 與隱含台幣價。
- `git diff --check`（本次檔案）：passed，只有 repo 既有 LF/CRLF 提示。

## Decisions made

- 不新增獨立頁面；直接擴充右側 `OVERNIGHT` 報告。
- 不把 ADR 漲跌幅等同台股台幣價差；另列台幣隱含價與參考價差。
- 不使用 adjusted close，避免股利/拆分調整破壞可交易價格換算。
- `USD-TWD` 為 canonical；只有它缺值時才反向換算 `TWD-USD` 並保留警告。
- UI skill 建議的整體 dark OLED theme 與既有 OMI 淺色密集報告衝突，因此只採金融資訊層級、tabular number、文字方向標籤與 responsive 規則。

## Known issues / risks

- 工作樹已有多項未提交變更；本次只改明確相關檔案並在結尾逐檔檢查 diff。
- ADR ratio 未由 filing 自動更新，必須保留 verified metadata 與來源。
- 整包 `overnight_impact.py` Ruff 仍會命中原本就存在的未使用 `category` 變數；本次未做無關清理，新增檔案與 schema 的 targeted Ruff 已通過。

## Next step

- 若要讓 3711/8150 在首次開啟前就有值，可在既有 US daily scheduler/watchlist seed 中預熱 ASX、IMOS。
