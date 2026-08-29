# Open Market Intelligence

<p align="center">
  <a href="./README.md">English</a> · <a href="./README.zh-TW.md">繁體中文</a> · <strong>日本語</strong>
</p>

<p align="center">
  <img alt="バージョン 4.4.0" src="https://img.shields.io/badge/version-4.4.0-2563eb">
  <img alt="Windows" src="https://img.shields.io/badge/platform-Windows-0f766e">
  <img alt="Apache License 2.0" src="https://img.shields.io/badge/license-Apache--2.0-334155">
</p>

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
