# Changelog

本專案的重要變更記錄於此。版本格式遵循 Semantic Versioning。

## [Unreleased]

### Changed

- 將專案正式以 Apache License 2.0 開源，著作權人為盧星豪，並補齊 NOTICE、貢獻與第三方資料授權邊界。
- Windows 發行包不再包含本機 SQLite 或股票主檔 seed；空白安裝首次啟動時改由 backend 以可追蹤、有界的官方 TWSE／TPEx refresh 建立股票代號。
- 將 launcher 與安裝捷徑圖示由 `ATRI-MyDearMoments.ico` 改名為 `OMI.ico`。

## [4.3.0] - 2026-08-27

### Changed

- 將投資組合估值責任拆回各市場 adapter，共用層只保留 provider-neutral valuation contract；台股服務不再承擔其他市場的估值語意。
- 台股 intraday current Market-State 改用一致的 index／breadth projection，並保留 session、freshness、partial 與 source lineage。
- 建立 `tw-4.3.0-source-checkpoint-20260827.json`，凍結本版 TW Shared Data Core source fingerprint、public schema 與 M5 harness／runbook／dated evidence。

### Validation

- 2026-08-27 M5 gates 通過 SourceOnly、runtime compare preflight、Opening、Regular／Level 5／symbol switch、Market-State、Closing Auction／formal match、compare→off rollback、off stable checks 與 final validation。
- final-source Preopen 因真實盤前時窗已過維持 pending；本版為台股中間封版，不宣告完整 live acceptance，狀態仍為 `runtime_accepted=false`、`release_ready=false`。
- 美股共用市場資料架構遷移不在本版範圍內。

## [4.0.1] - 2026-08-01

### Security

- 升級 `pydantic-settings` 至 `2.14.2`，修補 secrets directory symlink 越界讀取風險。
- 將 frontend lockfile 的 `@babel/core` 更新至已修補的 `7.29.7`。

### Changed

- Dependabot 只自動提出同 major 的相容更新，避免把 TypeScript、ESLint 或 Node types 的 breaking major 混入維護 PR。

## [4.0.0] - 2026-08-01

### Added

- 建立台股核心、本機優先、evidence-driven 的正式產品基線。
- 強化 AI decision core、market evidence、freshness、source health 與跨市場 context layer。
- 加入 2K 產品截圖、展示優先 README 與系統／決策流程圖。
- 補齊 Windows launcher、installer、GitHub community、Dependabot 與 CodeQL 發行基礎。

### Changed

- 統一產品版本為 `4.0.0`，frontend、backend API 與 installer 共用 release version contract。
- 升級 Next.js、React、Playwright 與 frontend 工具鏈至同 major 的最新安全 patch。
- CI 改為可取消重複執行、具 timeout，且失敗時保存 Playwright trace、report 與 screenshot。

### Fixed

- 修正 production SSR 暫時無法連到 backend 時，URL 分組選擇與區域市場 watchlist 無法在 hydration 後恢復的問題。
- 修正 Windows release 封裝使用不同 Python ABI 與硬編碼 stdlib 路徑時，安裝包無法啟動的問題，並排除本機 Python bytecode cache。

[Unreleased]: https://github.com/lulu930128/open-market-intelligence/compare/v4.3.0...HEAD
[4.3.0]: https://github.com/lulu930128/open-market-intelligence/compare/v4.2.0...v4.3.0
[4.0.1]: https://github.com/lulu930128/open-market-intelligence/compare/v4.0.0...v4.0.1
[4.0.0]: https://github.com/lulu930128/open-market-intelligence/compare/v1.0.0...v4.0.0
