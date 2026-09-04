# Changelog

本專案的重要變更記錄於此。版本格式遵循 Semantic Versioning。

## [Unreleased]

## [4.5.0] - 2026-09-05

### Changed

- 將專案正式以 Apache License 2.0 開源，著作權人為盧星豪，並補齊 NOTICE、貢獻與第三方資料授權邊界。
- Windows 發行包不再包含本機 SQLite 或股票主檔 seed；空白安裝首次啟動時改由 backend 以可追蹤、有界的官方 TWSE／TPEx refresh 建立股票代號。
- 將 launcher 與安裝捷徑圖示由 `ATRI-MyDearMoments.ico` 改名為 `OMI.ico`。
- 將台股與美股盤中資料收斂到 backend-owned canonical observation、resolution、read model與bounded producer責任，Frontend、AI與MCP只消費同一套 outward truth。
- 將市場 session、instrument status、freshness、finalization、authority與release維持為獨立語意，並為主要 read／consumer boundary補上architecture guard與精確debt inventory。
- 重寫公開 README，改以研究流程說明產品，並重畫 Provider → Canonical Observation → Resolver／Control → Market／Research → API／Decision → Consumer 的資料流。

### Fixed

- 修正台股 current-session bars、formal close、index previous close、market coverage、ETF watchlist、technical與official daily在收盤前後的語意落差，不以補零或合成行情掩蓋缺口。
- 修正美股盤中 materialization、read-model cache、extended-hours freshness與Frontend headline競態，避免較舊或缺少session proof的回應覆蓋較新canonical truth。
- 修正 AI capability、data-quality與Decision v4 projection在TW／US evidence裁切後遺失freshness、coverage或readiness依據的問題。

## [4.4.1] - 2026-08-31

### Changed

- 強化台股 Fugle realtime resilience，並將台股／美股 quote、intraday與index讀路徑進一步收斂到Shared Market Data Foundation。
- 補齊多語公開專案導覽與repo首頁語言切換。

### Fixed

- 修正美股缺漏index資料與CI在4.4 contract上的release metadata、architecture、Frontend hydration與smoke-test落差。

## [4.4.0] - 2026-08-29

### Changed

- 將 TW／US Daily、Shared Market Data Foundation、AI outward contract、MCP schema 與 Frontend compatibility 收斂為同一個 source consolidation 基線。
- 美股 Daily 由 market-owned descriptors、canonical acquisition、raw receipt／lineage、Shared Resolver、bounded history coverage與cache-only outward projection組成；AAPL／TSM保留Yahoo→Alpaca fallback與260-bar coverage證據。
- `omi.decision.v4` 的US Daily capability limit現在實際限制Backend canonical reader與chart reader，不再出現selection要求260根但context只讀90根的落差。

### Fixed

- 已released／finalized的台股Daily bar不再被同日期provisional intraday overlay取代；較新的未finalized session仍可形成暫估bar。
- Yahoo Daily INDEX即使回傳volume 0，也會canonicalize為`not_applicable`而不是0 shares；STOCK／ETF與intraday volume規則維持不變。

### Validation

- Shared／TW／US／AI targeted matrix：282 passed、27 subtests；補充AI／API／US architecture matrix：54 passed、64 subtests。
- Architecture pytest：18 passed；checker：PASS，22 actual／22 declared debt；affected Backend modules compileall通過。
- Frontend ESLint與TypeScript no-emit通過。
- 本版建立Source consolidation立腳點；4.4.0 runtime尚未restart採用，`^SOX`第二個Daily provider、完整Live／Product acceptance與publication仍是獨立gate。

## [4.3.2] - 2026-08-29

### Fixed

- 將台股 completed daily 的發布日期、official-source reconciliation、coverage 與 continuity 收斂到共用 canonical owner，避免未發布或樣本不足資料被當成完整市場事實。
- 強化 technical sufficiency、measurement unit lineage、intraday freshness 與市場 aggregate quality gate；不足 evidence 不再產生可交易的強方向分數。
- 讓 explicit 台股 capability selection 實際限制 Backend reader scope，並統一 AI、MCP snapshot 與 Dashboard 的 outward status projection。

### Validation

- 台股 Backend 與 AI／MCP targeted regression、architecture guards、compile 與 staged-diff 檢查已於 source checkpoint 通過。
- 本版只建立台股 source commit checkpoint；runtime adoption、下一交易日 live evidence 與完整 product acceptance 依使用者後續大幅調整完成後另行總驗證。
- 美股修改不在本版 commit 範圍內。

## [4.3.1] - 2026-08-28

### Fixed

- 統一台股現貨 `closing_auction`、`close_resolution` 與 `post_close` 邊界，在正式 EOD 發布前保留可追溯的 completed-session close，不再把盤中舊價或前一日收盤誤作今日收盤。
- 修正個股「今日」與日 K 在收盤後缺少當日資料的問題；provisional close 與 finalized official daily bar 維持分離，technical completed 不提前使用尚未發布的正式日線。
- 正式日線到達後由既有集中 owner 完成 session close reconciliation，並保留 TWSE／TPEx、stale、trial、日期不符與 mismatch 的可觀測語意。

### Validation

- 台股收盤／EOD targeted backend regression：265 passed、286 subtests。
- Frontend ESLint、TypeScript no-emit 與 `tw-eod-contract.spec.ts`（4 passed）通過。
- 本版只完成 source／contract regression；實際 runtime 與 live market acceptance 仍需獨立驗收。

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

[Unreleased]: https://github.com/lulu930128/open-market-intelligence/compare/v4.5.0...HEAD
[4.5.0]: https://github.com/lulu930128/open-market-intelligence/compare/v4.4.1...v4.5.0
[4.4.1]: https://github.com/lulu930128/open-market-intelligence/compare/v4.4.0...v4.4.1
[4.4.0]: https://github.com/lulu930128/open-market-intelligence/compare/v4.3.2...v4.4.0
[4.3.2]: https://github.com/lulu930128/open-market-intelligence/compare/v4.3.1...v4.3.2
[4.3.1]: https://github.com/lulu930128/open-market-intelligence/compare/v4.3.0...v4.3.1
[4.3.0]: https://github.com/lulu930128/open-market-intelligence/compare/v4.2.0...v4.3.0
[4.0.1]: https://github.com/lulu930128/open-market-intelligence/compare/v4.0.0...v4.0.1
[4.0.0]: https://github.com/lulu930128/open-market-intelligence/compare/v1.0.0...v4.0.0
