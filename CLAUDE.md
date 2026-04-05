# CLAUDE.md — PainHunter JP v2
## プロジェクト概要

日本語圏のQ&Aサイトから「繰り返し現れる構造的課題」を自動抽出し、
クラスタ単位で評価した上で、自分が作れるビジネスアイデアに変換する個人用CLIツール。
cronで毎日深夜に自動実行し、朝にntfy.shで結果を通知する。

これは「感情分析ツール」ではなく「事業仮説探索ツール」である。

## 技術スタック

- **言語**: Python 3.12
- **スクレイピング**: requests + BeautifulSoup4
- **LLM**: Anthropic Claude API (claude-sonnet-4-20250514)
- **通知**: ntfy.sh (HTTPS POST)
- **定期実行**: WSL cron or GitHub Actions
- **データ保存**: ローカルJSON（DB不要）

## ディレクトリ構成

DESIGN.mdの「ディレクトリ構成」セクションを参照。
v1から変更あり: extractor.py, normalizer.py, clusterer.py, scorer.py, report.py が追加。
config.py, models.py も新設。

## コーディング規約

1. **型ヒント必須**: すべての関数にtype hintsをつける
2. **dataclass使用**: データ構造はmodels.pyにdataclassで定義（Pydanticは不要）
3. **エラーハンドリング**: スクレイピングとAPI呼び出しは必ずtry/exceptで囲み、1件の失敗で全体が止まらないようにする
4. **ログ**: loggingモジュールを使用、print()は使わない
5. **環境変数**: python-dotenvで.envから読み込み、config.pyで一元管理
6. **テスト**: pytestで主要ロジックのテストを書く
7. **docstring**: 各モジュール・クラス・主要関数に日本語docstringをつける
8. **JSON出力**: 各ステップの中間データをdata/配下に日付別JSONで保存する

## 実装順序（この順番で作ること）

### Step 0: プロジェクト基盤
- requirements.txt（既存を確認・更新）
- .env.example（既存を確認・OPPORTUNITY_THRESHOLD等を追加）
- src/__init__.py
- src/config.py: 環境変数の読み込みと設定値の一元管理
- src/models.py: DESIGN.mdの「データモデル」セクションにある5つのdataclassをすべて定義
- src/main.pyのスケルトン（パイプラインの呼び出し順序だけ書く）

### Step 1: Scraper
- src/scraper/base.pyにBaseScraper ABCを定義
- src/scraper/chiebukuro.pyを実装
  - **まずrobots.txtを確認し、許可されているパスのみアクセスする**
  - **対象カテゴリはDESIGN.mdの「ジャンル探索方針」に記載の3ジャンル・計13サブカテゴリ**
  - 各カテゴリの新着質問ページから質問URLを取得
  - 各質問ページからタイトル・本文・メタデータを抽出
  - category_major, category_minor をデータに含める
  - リクエスト間隔2秒以上
  - data/raw/{date}.jsonに保存
- テスト: tests/test_scraper.py

### Step 2: Filter
- src/filter.pyを実装
  - 文字数フィルタ（本文30文字未満除外）
  - スパムパターン検出（URL3つ以上、宣伝文言）
  - 重複排除（difflib.SequenceMatcher, 閾値0.8）
  - 過去7日以内に取得済みURL除外（data/raw/の過去分を参照）
  - **追加**: 知識質問の弱フィルタ（「〜とは何ですか」パターン）
  - **追加**: 比較質問の除外（「どちらが良い」パターン）
  - **追加**: 具体的作業・不満記述が少ない投稿の除外
  - data/filtered/{date}.jsonに保存
- テスト: tests/test_filter.py

### Step 3: Pain Extractor
- src/extractor.pyを実装
  - Anthropic Python SDKを使用
  - **プロンプトはDESIGN.mdのExtractedPainモデルに完全準拠した構造化JSON出力**
  - 重要: current_workaround と root_cause の抽出を重視するプロンプト設計
  - 重要: 「単なる知識不足」と「構造的に繰り返す課題」を区別する指示を含める
  - バッチ処理: 5件ずつまとめてAPI送信
  - レスポンスのJSONパース + バリデーション（不正JSON時のフォールバック）
  - data/extracted/{date}.jsonに保存
- テスト: tests/test_extractor.py（モックAPI使用）

### Step 4: Normalizer
- src/normalizer.pyを実装
  - persona_type, job_to_be_done, pain_category, root_cause, pain_summaryを正規化
  - 初期はルールベース辞書（同義語マッピング）で実装
  - ルールで吸収できないものはLLM補助（オプション、コスト見合い）
  - NormalizedPainを出力
  - data/normalized/{date}.jsonに保存
- テスト: tests/test_normalizer.py

### Step 5: Clusterer
- src/clusterer.pyを実装
  - Phase 1: canonical_problem + canonical_job + canonical_root_cause の完全一致でグルーピング
  - Phase 1: タグ一致数による近傍判定（補助）
  - 件数1のクラスタも保持（後日合流用）
  - 過去LOOKBACK_DAYS日分のデータも読み込んでクラスタに合流させる
  - PainClusterを出力（平均スコア類は仮値で入れておく）
  - data/clustered/{date}.jsonに保存
- テスト: tests/test_clusterer.py

### Step 6: Opportunity Scorer
- src/scorer.pyを実装
  - DESIGN.mdの合成式に基づいてopportunity_scoreを算出
  - severity_score: クラスタ内の平均severity
  - recurrence_score: クラスタサイズ + 出現日数から算出
  - solution_gap_score: current_workaroundの弱さから推定（ルールベース or LLM）
  - wtp_score: 平均willingness_to_pay_proxy
  - builder_fit_score: 平均builder_fit
  - productability_score: recurrence_hint の分布から算出
  - PainClusterのスコアフィールドを更新
  - data/scored/{date}.jsonに保存
- テスト: tests/test_scorer.py

### Step 7: Idea Generator
- src/idea_generator.pyを実装
  - opportunity_score上位3クラスタのみ処理
  - 1クラスタにつき複数の切り口（自動化型、情報整理型、ワークフロー統合型、ニッチSaaS型）を出す
  - IdeaCandidateを出力
  - data/ideas/{date}.jsonに保存

### Step 8: Report + Notify
- src/report.pyを実装
  - DESIGN.mdのレポート例に準拠した日次Markdownを生成
  - reports/{date}.mdに保存
- src/notifier.pyを実装
  - ntfy.shへのHTTPS POST
  - レポートのサマリー版（通知に収まる長さ）を送信

### Step 9: main.pyで統合 + 定期実行
- 全モジュールをパイプラインとして繋ぐ
- コマンドライン引数: --dry-run, --categories, --limit, --skip-notify
- 実行ログをlogs/に保存
- crontab設定手順をREADME.mdに記載
- .github/workflows/daily.ymlを作成

## 重要な注意事項

### スクレイピング
- Yahoo!知恵袋のrobots.txtを事前に確認し、許可されているパスのみアクセス
- User-Agentを適切に設定
- リクエスト間隔は最低2秒
- 1回の実行で最大100リクエスト以内

### API呼び出し
- レート制限を考慮
- APIエラー時はexponential backoffでリトライ（最大3回）
- レスポンスがJSON以外の場合のフォールバック処理

### データ管理
- 個人情報（ユーザー名等）は取得・保存しない
- URLは参照用に保持するが公開はしない

### コスト最適化
- ExtractorとNormalizerを同一プロンプトにまとめることを検討
- Idea Generatorは上位3クラスタのみ
- 入力テキスト長を制限（本文500文字まで）

## ブランチ戦略
詳細: `docs/common/git_branch_strategy.md`

| ブランチ | 役割 |
|---|---|
| `dev` | 安定版・マージ先の基点 |
| `features/xxxx` | 機能追加・改修 |
| `bugfix/xxxx` | バグ修正 |

- `master` ブランチは使用しない
- 作業ブランチは常に `dev` から切り、`dev` にマージして削除する
- OSS的に、メジャーバージョン.マイナーバージョン.パッチバージョンで管理を行い、節目でGITタグを付与してスナップショット管理を行う（v0.1.0, v.0.1.2, v.1.00的な）

## ドキュメント管理

- 仕様・実装ドキュメントは `docs/vMAJOR.MINOR.x/` フォルダに格納する
- ファイル名はタグ名に合わせる（例: `docs/v0.1.x/v0.1.0.md`）
- マイナーバージョンが上がったら新フォルダを作成する（例: `docs/v0.2.x/`）
- パッチバージョン更新時は同フォルダ内に新ファイルを追加する（例: `docs/v0.1.x/v0.1.1.md`）

## よく使うコマンド

```bash
# 開発実行（ドライラン、5件のみ）
python src/main.py --dry-run --limit 5

# 本番実行
python src/main.py

# 特定カテゴリのみ
python src/main.py --categories "企業と経営" "税金、年金"

# 通知スキップ
python src/main.py --skip-notify

# テスト実行
pytest tests/ -v

# 環境セットアップ
pip install -r requirements.txt
cp .env.example .env
# .envにAPIキーを記入
```


