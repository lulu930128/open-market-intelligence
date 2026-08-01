# Changelog

本專案的重要變更記錄於此。版本格式遵循 Semantic Versioning。

## [Unreleased]

### Changed

- 後續變更將從 OMI 4.0 產品基線延伸。

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
- 修正 Windows release 封裝使用不同 Python ABI 與硬編碼 stdlib 路徑時，安裝包無法啟動的問題。

[Unreleased]: https://github.com/lulu930128/open-market-intelligence/compare/v4.0.0...HEAD
[4.0.0]: https://github.com/lulu930128/open-market-intelligence/compare/v1.0.0...v4.0.0
