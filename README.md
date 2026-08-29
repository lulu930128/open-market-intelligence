# Open Market Intelligence

<p align="center">
  <strong>English</strong> (default)
</p>

<details>
<summary><strong>繁體中文</strong> — 點此在本頁閱讀</summary>

## Open Market Intelligence（繁體中文）

Open Market Intelligence（OMI）是一套在本機運作的市場研究工作台，適合想先把一檔股票看懂，再決定下一步的人。價格、圖表、市場廣度、自選股、技術面、公司資料與來源狀態，都能在同一個地方查看。

OMI 以台股為主要參考市場，美股則有完整的研究流程；日股、韓股、港股、期貨、商品與加密貨幣會在資料可用時提供額外的市場背景。

OMI 只協助研究，不會自動下單，也不保證任何投資績效。

![OMI 儀表板，包含市場廣度、群組、自選股與 Radar](docs/assets/readme/omi-v4-dashboard-radar-2k.png)

<sub>畫面來自 OMI 本機實際執行環境；截圖中的價格與市場狀態僅為歷史範例。</sub>

## OMI 可以幫你做什麼

| 你想知道的事 | OMI 提供的內容 |
| --- | --- |
| 先看懂整體市場 | 市場廣度、族群、指數、期貨與跨市場背景 |
| 深入研究一家公司 | 價格歷史、技術狀態、基本面、持股、事件與風險背景 |
| 把觀察整理成計畫 | 有證據的情境、進場條件、失效條件與風險提示 |
| 維持聚焦的研究空間 | 自選股、研究群組、Radar 候選標的與本機保存狀態 |
| 知道資料是否完整 | 清楚顯示來源、新鮮度、替代來源、缺漏與部分資料 |

## 實際功能畫面

### 不必在多個工具之間來回切換

個股工作區把圖表、市場結構、公司背景與研究內容放在一起，讓你能檢查一個想法背後的證據，而不是只看單一分數。

![OMI 個股研究工作區](docs/assets/readme/omi-v4-stock-research-2k.png)

### 讀圖，也把真正重要的條件記下來

專業圖表支援多週期、成交量分布、指標、訊號與繪圖工具。它用來幫助驗證假設，不是取代判斷。

![OMI 專業圖表、指標與成交量分布](docs/assets/readme/omi-v4-professional-chart-2k.png)

### 直接詢問目前畫面上的股票

Decision Dock 會使用目前標的，在同一個工作區呈現證據、可能情境、失效條件、風險與資料限制。

![個股圖表旁的 OMI Decision Dock](docs/assets/readme/omi-v4-decision-dock-2k.png)

### 不只看大盤漲跌，也看台股內部結構

OMI 把市場廣度、族群、期貨與個股背景放在一起，避免指數很強時，掩蓋了參與度不足的情況。

![OMI 台灣期貨市場背景](docs/assets/readme/omi-taiwan-futures-context.png)

### 研究美股時，同時保留大盤視角

美股工作區串連主要指數、活躍標的、自選股、交易時段與公司研究。

![OMI 美股市場背景與自選股](docs/assets/readme/omi-us-market-context.png)

### 看得見資料從哪裡來

來源揭露本身就是產品功能。OMI 會說明 provider 的責任與限制，不會把每一筆數字都包裝成同樣即時、同樣可靠。

![OMI 資料來源與責任揭露](docs/assets/readme/omi-settings-source-disclosure.png)

### 用其他市場補足背景

加密貨幣等額外工作區可作為研究背景；實際涵蓋範圍與品質會依市場和 provider 而不同。

![OMI 加密貨幣即時工作區](docs/assets/readme/omi-crypto-realtime-workbench.png)

想逐一了解主要畫面，可以閱讀[功能導覽（英文）](docs/guides/feature-tour.md)。

## 資料狀態也是答案的一部分

市場資料可能延遲、不完整、暫時無法取得，或改由替代來源提供。OMI 會把這些情況保留下來：

- 缺少的資料不會被偷偷改成零；
- 過期與部分資料會持續標示；
- 不同來源與資料問題不會被壓成一顆籠統的「正常」燈號；
- 研究結果會交代證據、條件、風險與失效方式，不只給一個結論。

## 在 Windows 開始使用

### 使用打包好的版本

Windows 安裝包已包含所需的 Python 與 Node.js runtime。

1. 從 [Releases](https://github.com/lulu930128/open-market-intelligence/releases) 下載 Windows zip。
2. 完整解壓縮整個資料夾，不要直接從 zip 預覽執行。
3. 執行 <code>Start-OMI-Launcher.cmd</code>。
4. 從系統匣選單開啟儀表板。

可寫入的資料與 logs 會放在 <code>%LOCALAPPDATA%\Open Market Intelligence</code>。

### 從原始碼 checkout 啟動

如果 repository 已經設定完成：

~~~powershell
cd "C:\project\Open Market Intelligence"
.\Start-OMI-Launcher.cmd
~~~

第一次安裝原始碼版本、系統需求、動態 port 與疑難排解，請依照[開始使用指南（英文）](docs/guides/getting-started.md)。

## 指南與專案資訊

- [開始使用（英文）](docs/guides/getting-started.md) — 安裝包與原始碼版本
- [功能導覽（英文）](docs/guides/feature-tour.md) — 各主要工作區的用途
- [開發指南（英文）](docs/guides/development.md) — 本機開發、驗證與截圖
- [選配 KGI SuperPy 設定（英文）](docs/guides/kgi-superpy.md) — 即時行情與唯讀持股同步
- [使用支援](SUPPORT.md) · [版本紀錄](CHANGELOG.md) · [參與貢獻](CONTRIBUTING.md)
- [安全回報](SECURITY.md) · [授權](LICENSE) · [第三方聲明](THIRD_PARTY_NOTICES.md)

## 目前限制

- OMI 採本機優先，目前主要針對 Windows 最佳化。
- 台股、美股、日股、韓股、港股、加密貨幣、期貨與商品的涵蓋範圍並不完全相同。
- 部分功能需要選配的 provider 憑證、帳號權限或特定市場服務。
- 來源中斷或 provider 限制可能影響資料的新鮮度與完整性。
- Decision Dock 用來協助研究，不能取代獨立判斷。

## 免責聲明

OMI 僅供研究與資訊整理，不構成投資建議、績效保證或自主交易系統。重要資訊請再向第一手來源核對，並自行評估適合度與風險。

## 授權

本專案採用 [Apache License 2.0](LICENSE)。相關出處與第三方條款請見 [NOTICE](NOTICE) 與 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

</details>

<details>
<summary><strong>日本語</strong> — このページで読む</summary>

## Open Market Intelligence（日本語）

Open Market Intelligence（OMI）は、銘柄を理解してから次の判断を考えたい人のための、ローカルファーストな市場リサーチ・ワークスペースです。価格、チャート、市場の騰落状況、ウォッチリスト、テクニカル情報、企業データ、データソースの状態を一か所で確認できます。

台湾株を基準市場とし、米国株には本格的なリサーチ・フローを用意しています。日本、韓国、香港、先物、コモディティ、暗号資産についても、データが利用できる範囲で市場背景を提供します。

OMIはリサーチ支援ツールです。自動発注や投資成果の保証は行いません。

![市場の騰落状況、グループ、ウォッチリスト、Radarを表示するOMIダッシュボード](docs/assets/readme/omi-v4-dashboard-radar-2k.png)

<sub>OMIをローカルで実際に動かした画面です。スクリーンショット内の価格と市場状況は過去の例です。</sub>

## OMIでできること

| 知りたいこと | OMIが提供するもの |
| --- | --- |
| まず市場全体を理解したい | 騰落状況、セクター、指数、先物、他市場との関係 |
| 一社を詳しく調べたい | 価格履歴、テクニカル状態、ファンダメンタルズ、保有状況、イベント、リスク背景 |
| 観察を行動条件に整理したい | 根拠のあるシナリオ、エントリー条件、無効化条件、リスクメモ |
| 調査対象を絞り込みたい | ウォッチリスト、リサーチ・グループ、Radar候補、ローカル保存 |
| データが十分か確認したい | ソース、鮮度、フォールバック、欠損、部分データの表示 |

## 実際の機能

### 複数のツールを行き来せずに銘柄を調べる

銘柄ワークスペースでは、チャート、市場構造、企業情報、リサーチ内容を一緒に確認できます。一つのスコアだけでなく、アイデアの根拠をたどれます。

![OMIの銘柄リサーチ・ワークスペース](docs/assets/readme/omi-v4-stock-research-2k.png)

### チャートを読み、重要な条件を記録する

プロ向けチャートは、複数時間軸、出来高プロファイル、指標、シグナル、描画ツールに対応しています。仮説を検証するための機能であり、判断そのものを置き換えるものではありません。

![指標と出来高プロファイルを表示するOMIチャート](docs/assets/readme/omi-v4-professional-chart-2k.png)

### 画面で見ている銘柄について、そのままOMIに尋ねる

Decision Dockは現在の銘柄を引き継ぎ、根拠、シナリオ、無効化条件、リスク、データ上の制約を同じ画面に表示します。

![銘柄チャートの横に表示されたOMI Decision Dock](docs/assets/readme/omi-v4-decision-dock-2k.png)

### 指数だけでなく、台湾市場の内部構造を見る

市場の騰落状況、セクター、先物、個別銘柄の背景を組み合わせ、指数上昇の裏にある参加銘柄の弱さも確認できます。

![OMIの台湾先物コンテキスト](docs/assets/readme/omi-taiwan-futures-context.png)

### 米国株を市場全体と一緒に調べる

米国市場ワークスペースでは、主要指数、活発な銘柄、ウォッチリスト、取引セッション、企業リサーチをつなげて確認できます。

![OMIの米国市場コンテキストとウォッチリスト](docs/assets/readme/omi-us-market-context.png)

### データの出所を確認する

ソース開示も製品機能の一部です。OMIはproviderの役割と制約を示し、すべての数値を同じ鮮度・信頼度であるかのようには扱いません。

![OMIのデータソースと責任範囲の表示](docs/assets/readme/omi-settings-source-disclosure.png)

### 他市場を補助的な背景として使う

暗号資産などの追加ワークベンチは、市場背景を調べるために利用できます。カバレッジと品質は市場およびproviderによって異なります。

![OMIの暗号資産リアルタイム・ワークベンチ](docs/assets/readme/omi-crypto-realtime-workbench.png)

各画面の詳しい説明は、[機能ガイド（英語）](docs/guides/feature-tour.md)をご覧ください。

## データの状態も答えの一部です

市場データは、遅延、部分的な欠損、一時的な取得不能、代替ソースへの切り替えが起こり得ます。OMIはその状態を隠しません。

- 欠損値を自動的にゼロへ置き換えません。
- 古いデータと部分データには表示を残します。
- 異なるソースやデータの問題を、一つの曖昧な「正常」表示にまとめません。
- リサーチ結果には結論だけでなく、根拠、条件、リスク、無効化条件を含めます。

## Windowsで使い始める

### パッケージ版を使う

Windowsパッケージには、必要なPythonとNode.jsのruntimeが含まれています。

1. [Releases](https://github.com/lulu930128/open-market-intelligence/releases)からWindows用zipをダウンロードします。
2. フォルダー全体を展開します。zipのプレビュー画面から直接実行しないでください。
3. <code>Start-OMI-Launcher.cmd</code>を実行します。
4. システムトレイのメニューからダッシュボードを開きます。

書き込み可能なデータとログは、<code>%LOCALAPPDATA%\Open Market Intelligence</code>に保存されます。

### ソースcheckoutから起動する

すでにrepositoryのセットアップが完了している場合：

~~~powershell
cd "C:\project\Open Market Intelligence"
.\Start-OMI-Launcher.cmd
~~~

初回セットアップ、必要環境、動的port、トラブルシューティングについては、[導入ガイド（英語）](docs/guides/getting-started.md)をご覧ください。

## ガイドとプロジェクト情報

- [導入ガイド（英語）](docs/guides/getting-started.md) — パッケージ版とソース版
- [機能ガイド（英語）](docs/guides/feature-tour.md) — 主なワークスペースの目的
- [開発ガイド（英語）](docs/guides/development.md) — ローカル開発、検証、スクリーンショット
- [KGI SuperPyの任意設定（英語）](docs/guides/kgi-superpy.md) — ライブ価格と読み取り専用の保有銘柄同期
- [サポート](SUPPORT.md) · [変更履歴](CHANGELOG.md) · [コントリビューション](CONTRIBUTING.md)
- [セキュリティ](SECURITY.md) · [ライセンス](LICENSE) · [第三者ライセンス](THIRD_PARTY_NOTICES.md)

## 現在の制約

- OMIはローカルファーストで、現在は主にWindows向けに最適化されています。
- 台湾、米国、日本、韓国、香港、暗号資産、先物、コモディティでは、利用できる機能とデータ範囲が同一ではありません。
- 一部の機能には、任意のprovider認証情報、アカウント権限、市場固有のサービスが必要です。
- ソース停止やproviderの制約により、データの鮮度と完全性が変わることがあります。
- Decision Dockはリサーチを支援しますが、独立した判断を不要にするものではありません。

## 免責事項

OMIはリサーチと情報整理のみを目的としています。投資助言、成果保証、自律取引システムではありません。重要な情報は一次資料で確認し、適合性とリスクを自身で判断してください。

## ライセンス

[Apache License 2.0](LICENSE)で提供されています。帰属表示と第三者条項は、[NOTICE](NOTICE)および[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)をご覧ください。

</details>

<p align="center">
  <img alt="Version 4.4.0" src="https://img.shields.io/badge/version-4.4.0-2563eb">
  <img alt="Windows" src="https://img.shields.io/badge/platform-Windows-0f766e">
  <img alt="Apache License 2.0" src="https://img.shields.io/badge/license-Apache--2.0-334155">
</p>

Open Market Intelligence (OMI) is a local-first research workspace for people who want to understand a stock before deciding what to do. It brings prices, charts, market breadth, watchlists, technical context, company data, and source status into one place.

Taiwan is OMI’s reference market. US stocks have a dedicated research workflow, while Japan, Korea, Hong Kong, futures, commodities, and crypto provide additional market context where data is available.

OMI is a research tool. It does not place trades automatically or promise investment returns.

![OMI dashboard with market breadth, groups, watchlists, and Radar](docs/assets/readme/omi-v4-dashboard-radar-2k.png)

<sub>Actual OMI local runtime. Prices and market conditions shown in screenshots are historical examples.</sub>

## What OMI helps you do

| Need | What you get |
| --- | --- |
| Understand the market first | Market breadth, groups, indices, futures, and cross-market context |
| Research one company | Price history, technical state, fundamentals, ownership, events, and risk context |
| Turn observations into a plan | Evidence-backed scenarios, entry conditions, invalidation, and risk notes |
| Keep a focused workspace | Watchlists, research groups, Radar candidates, and saved local state |
| Know when data is incomplete | Source, freshness, fallback, missing, and partial states remain visible |

## A closer look

### Research a stock without jumping between tools

The stock workspace keeps the chart, market structure, company context, and research notes together, so you can inspect the evidence behind an idea instead of relying on a single score.

![OMI stock research workspace](docs/assets/readme/omi-v4-stock-research-2k.png)

### Read the chart and record the conditions that matter

Professional charts include multiple timeframes, volume profile, indicators, signals, and drawing tools. They are meant to support a hypothesis—not replace one.

![OMI professional chart with indicators and volume profile](docs/assets/readme/omi-v4-professional-chart-2k.png)

### Ask OMI about the stock already on screen

The Decision Dock works with the current symbol and presents evidence, scenarios, invalidation conditions, risks, and data limits in the same workspace.

![OMI Decision Dock beside a stock chart](docs/assets/readme/omi-v4-decision-dock-2k.png)

### See Taiwan market structure beyond the headline index

OMI combines breadth, sectors, futures, and stock-level context so a strong index does not hide weak participation underneath.

![Taiwan futures context in OMI](docs/assets/readme/omi-taiwan-futures-context.png)

### Research US stocks with the wider market in view

The US workspace keeps major indices, active symbols, watchlists, sessions, and company research connected.

![US market context and watchlist in OMI](docs/assets/readme/omi-us-market-context.png)

### Check where the data came from

Source disclosure is part of the product. OMI shows provider roles and limitations instead of presenting every value as equally current or authoritative.

![OMI source and responsibility disclosure](docs/assets/readme/omi-settings-source-disclosure.png)

### Use other markets as context

Additional workbenches, including crypto, are available as contextual research surfaces. Coverage and quality depend on the market and provider.

![OMI crypto real-time workbench](docs/assets/readme/omi-crypto-realtime-workbench.png)

For a screen-by-screen overview, see the [feature tour](docs/guides/feature-tour.md).

## Data status is part of the answer

Market data can be delayed, partial, unavailable, or supplied by a fallback source. OMI keeps those conditions visible:

- missing data is not silently converted to zero;
- stale and partial results stay labeled;
- different kinds of source and data problems are not reduced to one generic “healthy” light;
- research output includes evidence, conditions, risks, and invalidation—not only a conclusion.

## Start on Windows

### Use the packaged release

The Windows package includes its own Python and Node.js runtimes.

1. Download the Windows zip from [Releases](https://github.com/lulu930128/open-market-intelligence/releases).
2. Extract the entire folder. Do not run it from the zip preview.
3. Run <code>Start-OMI-Launcher.cmd</code>.
4. Use the tray menu to open the dashboard.

Your writable data and logs are stored under <code>%LOCALAPPDATA%\Open Market Intelligence</code>.

### Run from a source checkout

If the repository has already been set up:

~~~powershell
cd "C:\project\Open Market Intelligence"
.\Start-OMI-Launcher.cmd
~~~

For first-time source installation, requirements, dynamic ports, and troubleshooting, follow the [getting-started guide](docs/guides/getting-started.md).

## Guides and project information

- [Getting started](docs/guides/getting-started.md) — packaged release and source installation
- [Feature tour](docs/guides/feature-tour.md) — what each main workspace is for
- [Development guide](docs/guides/development.md) — local development, validation, and screenshots
- [Optional KGI SuperPy setup](docs/guides/kgi-superpy.md) — live quotes and read-only holdings sync
- [Support](SUPPORT.md) · [Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md) · [License](LICENSE) · [Third-party notices](THIRD_PARTY_NOTICES.md)

## Current limits

- OMI is local-first and currently optimized for Windows.
- Market coverage is not identical across Taiwan, the US, Japan, Korea, Hong Kong, crypto, futures, and commodities.
- Some capabilities require optional provider credentials, account permissions, or market-specific services.
- Source availability and provider restrictions can affect freshness and completeness.
- The Decision Dock supports research; it does not remove the need for independent judgment.

## Disclaimer

OMI is for research and information only. It is not investment advice, a performance guarantee, or an autonomous trading system. Verify important information with primary sources and assess suitability and risk independently.

## License

Licensed under the [Apache License 2.0](LICENSE). See [NOTICE](NOTICE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for attribution and third-party terms.
